import requests
import json

def get_price_history(token_id):
    url = "https://clob.polymarket.com/prices-history"
    r = requests.get(url, params={"market": token_id,
                                  "interval": "max", "fidelity": 1440})
    return r.json().get("history", [])

def run_backtest(history, strategy="mean_revert", threshold=0.02):
    """
    mean_revert: trade both directions
      - price drops → BUY YES (expect bounce up)
      - price rises → SHORT YES (expect fall down)
    momentum: trade in direction of move
      - price rises → BUY YES
      - price drops → SHORT YES
    """
    if len(history) < 5:
        return None

    trades = []
    cash   = 1000.0

    for i in range(3, len(history) - 1):
        past   = float(history[i-3]["p"])
        curr   = float(history[i]["p"])
        next_  = float(history[i+1]["p"])
        change = curr - past

        if curr < 0.04 or curr > 0.96:
            continue

        bet_size = cash * 0.1

        if strategy == "mean_revert":
            if change < -threshold:
                # BUY YES — expect price to bounce back up
                pnl = bet_size * (next_ - curr) / curr
                cash += pnl
                trades.append({"direction": "BUY_YES", "pnl": pnl,
                                "entry": curr, "exit": next_})
            elif change > threshold:
                # SHORT YES — expect price to fall back down
                pnl = bet_size * (curr - next_) / curr
                cash += pnl
                trades.append({"direction": "SHORT_YES", "pnl": pnl,
                                "entry": curr, "exit": next_})

        elif strategy == "momentum":
            if change > threshold:
                # Price rising → keep riding up
                pnl = bet_size * (next_ - curr) / curr
                cash += pnl
                trades.append({"direction": "BUY_YES", "pnl": pnl,
                                "entry": curr, "exit": next_})
            elif change < -threshold:
                # Price falling → ride it down
                pnl = bet_size * (curr - next_) / curr
                cash += pnl
                trades.append({"direction": "SHORT_YES", "pnl": pnl,
                                "entry": curr, "exit": next_})

    if not trades:
        return None

    wins      = [t for t in trades if t["pnl"] > 0]
    total_pnl = cash - 1000.0
    win_rate  = len(wins) / len(trades) * 100
    pnls      = [t["pnl"] for t in trades]
    avg       = sum(pnls) / len(pnls)
    std       = (sum((x - avg) ** 2 for x in pnls) / len(pnls)) ** 0.5
    sharpe    = avg / std if std > 0 else 0

    buy_trades   = [t for t in trades if t["direction"] == "BUY_YES"]
    short_trades = [t for t in trades if t["direction"] == "SHORT_YES"]

    return {
        "trades":       len(trades),
        "buy_trades":   len(buy_trades),
        "short_trades": len(short_trades),
        "wins":         len(wins),
        "win_rate":     round(win_rate, 1),
        "total_pnl":    round(total_pnl, 2),
        "sharpe":       round(sharpe, 2),
        "final_cash":   round(cash, 2),
    }

def get_markets():
    r = requests.get("https://gamma-api.polymarket.com/markets",
                     params={"active": "true", "closed": "false", "limit": 30})
    return r.json()

# ── MAIN ─────────────────────────────────────────────────────────────────────
print("Fetching markets...")
markets = get_markets()
print(f"Running backtest on {len(markets)} markets...\n")

results = []
for m in markets:
    token_ids = json.loads(m.get("clobTokenIds", "[]"))
    if not token_ids:
        continue
    history = get_price_history(token_ids[0])
    if len(history) < 3:
        continue
    for strategy in ["mean_revert", "momentum"]:
        res = run_backtest(history, strategy=strategy)
        if res and res["trades"] >= 1:
            results.append({
                "question": m["question"][:48],
                "strategy": strategy,
                **res
            })

results.sort(key=lambda x: x["total_pnl"], reverse=True)

print(f"{'Market':<50} {'Strategy':<12} {'Trades':>6} {'Buy':>5} "
      f"{'Short':>6} {'Win%':>6} {'PnL ($)':>9} {'Sharpe':>7}")
print("-" * 110)

for r in results[:15]:
    print(f"{r['question']:<50} {r['strategy']:<12} {r['trades']:>6} "
          f"{r['buy_trades']:>5} {r['short_trades']:>6} "
          f"{r['win_rate']:>5.1f}% {r['total_pnl']:>+9.2f} {r['sharpe']:>7.2f}")

print("-" * 110)

if results:
    winning     = [r for r in results if r["total_pnl"] > 0]
    best        = results[0]
    mr_results  = [r for r in results if r["strategy"] == "mean_revert"]
    mom_results = [r for r in results if r["strategy"] == "momentum"]
    mr_avg_pnl  = sum(r["total_pnl"] for r in mr_results) / len(mr_results) if mr_results else 0
    mom_avg_pnl = sum(r["total_pnl"] for r in mom_results) / len(mom_results) if mom_results else 0

    print(f"\n{'='*65}")
    print(f"  QUANT PERFORMANCE REPORT")
    print(f"{'='*65}")
    print(f"  Strategy runs         : {len(results)}")
    print(f"  Profitable runs       : {len(winning)} / {len(results)}")
    print(f"  Best PnL              : ${best['total_pnl']:+,.2f} "
          f"({best['question'][:35]}, {best['strategy']})")
    print(f"  Mean Revert avg PnL   : ${mr_avg_pnl:+,.2f}")
    print(f"  Momentum avg PnL      : ${mom_avg_pnl:+,.2f}")
    print(f"  Winner                : "
          f"{'Mean Reversion' if mr_avg_pnl > mom_avg_pnl else 'Momentum'}")
    print(f"\n  Both strategies trade TWO directions:")
    print(f"  mean_revert: drop→BUY YES, rise→SHORT YES")
    print(f"  momentum   : rise→BUY YES, drop→SHORT YES")
    print(f"{'='*65}")