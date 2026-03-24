import requests
import json
from utils import (detect_signal, kelly_fraction, analyze_orderbook,
                   ob_confirms_signal, compute_volatility)

def get_markets():
    r = requests.get("https://gamma-api.polymarket.com/markets",
                     params={"active": "true", "closed": "false", "limit": 50})
    return r.json()

def get_price_history(token_id):
    r = requests.get("https://clob.polymarket.com/prices-history",
                     params={"market": token_id, "interval": "max", "fidelity": 1440})
    return r.json().get("history", [])

def get_orderbook(token_id):
    r = requests.get("https://clob.polymarket.com/book",
                     params={"token_id": token_id})
    return r.json()

print("="*70)
print("  ORDERBOOK + KELLY ANALYZER")
print("  Adaptive threshold | Two-sided | OB confirmation")
print("="*70)

markets = get_markets()
results = []

for m in markets:
    try:
        token_ids = json.loads(m.get("clobTokenIds", "[]"))
        if not token_ids:
            continue
        yes_token = token_ids[0]
        history   = get_price_history(yes_token)
        signal    = detect_signal(history, m)
        if not signal:
            continue
        book      = get_orderbook(yes_token)
        ob        = analyze_orderbook(book)
        if not ob:
            continue
        kelly, win_prob = kelly_fraction(history)
        yes_price       = float(json.loads(m["outcomePrices"])[0])
        confirmed       = ob_confirms_signal(ob, signal["direction"])
        results.append({
            "question":  m["question"][:52],
            "yes_price": yes_price,
            "direction": signal["direction"],
            "change":    signal["change"],
            "threshold": signal["threshold"],
            "days_left": signal["days_left"],
            "ob_signal": ob["signal"],
            "imbalance": ob["imbalance"],
            "win_prob":  win_prob,
            "kelly":     kelly,
            "confirmed": confirmed,
        })
    except:
        continue

results.sort(key=lambda x: (x["confirmed"], x["kelly"]), reverse=True)

print(f"\n{'Market':<54} {'Dir':<10} {'3dD':>6} {'Thresh':>7} "
      f"{'Days':>5} {'Kelly':>6} {'Confirmed'}")
print("-"*110)

for r in results[:15]:
    conf = "YES" if r["confirmed"] else "NO"
    print(f"{r['question']:<54} {r['direction']:<10} "
          f"{r['change']:>+5.1f}% {r['threshold']:>6.1f}%  "
          f"{r['days_left']:>5} {r['kelly']*100:>5.1f}%  {conf}")

print("-"*110)
confirmed = [r for r in results if r["confirmed"]]
print(f"\n  CONFIRMED SIGNALS: {len(confirmed)}")
for s in confirmed:
    bet   = 1000 * s["kelly"]
    trade = "BUY YES" if s["direction"] == "BUY_YES" else "SHORT YES"
    print(f"\n  Market     : {s['question']}")
    print(f"  Trade      : {trade}")
    print(f"  Price      : {s['yes_price']*100:.1f}%  ({s['change']:+.1f}% / 3d)")
    print(f"  Threshold  : {s['threshold']}% adaptive")
    print(f"  Orderbook  : {s['ob_signal']} ({s['imbalance']:.1%})")
    print(f"  Win Prob   : {s['win_prob']*100:.1f}%")
    print(f"  Kelly Bet  : ${bet:.2f} on $1,000")

print(f"\n{'='*70}")
print(f"  Analyzed: {len(results)} | Confirmed: {len(confirmed)}")
print("="*70)