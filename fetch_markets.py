import requests
import json
from datetime import datetime
from utils import detect_signal, compute_volatility, days_to_resolution, volume_confirmed

def get_markets(limit=50):
    r = requests.get("https://gamma-api.polymarket.com/markets",
                     params={"active": "true", "closed": "false", "limit": limit})
    return r.json()

def get_price_history(token_id):
    r = requests.get("https://clob.polymarket.com/prices-history",
                     params={"market": token_id, "interval": "max", "fidelity": 1440})
    return r.json().get("history", [])

def edge_score(market, history):
    try:
        vol24      = float(market.get("volume24hr", 0))
        vol_total  = float(market.get("volumeNum", 1))
        spread     = float(market.get("spread", 1))
        start      = market.get("startDateIso", "")
        days       = max((datetime.now() - datetime.fromisoformat(start)).days, 1) if start else 365
        avg_daily  = vol_total / days
        vol_spike  = vol24 / avg_daily if avg_daily > 0 else 0
        volatility = compute_volatility(history)
        liq_score  = 1 / (spread + 0.001)
        return (vol_spike * 40) + (volatility * 100 * 20) + min(liq_score, 10) * 3
    except:
        return 0

print("Fetching markets...")
markets = get_markets(50)

results = []
for m in markets:
    try:
        token_ids = json.loads(m.get("clobTokenIds", "[]"))
        if not token_ids:
            continue
        history   = get_price_history(token_ids[0])
        signal    = detect_signal(history, m)
        yes       = float(json.loads(m["outcomePrices"])[0])
        vol24     = float(m.get("volume24hr", 0))
        days_left = days_to_resolution(m)
        vol_ok    = volume_confirmed(m)
        threshold = compute_volatility(history)
        score     = edge_score(m, history)
        results.append({
            "question":  m["question"],
            "yes":       yes,
            "vol24":     vol24,
            "score":     score,
            "signal":    signal,
            "days_left": days_left,
            "vol_ok":    vol_ok,
            "threshold": round(threshold * 100, 2),
        })
    except:
        continue

results.sort(key=lambda x: x["score"], reverse=True)

print(f"\n{'Question':<52} {'Yes%':>5} {'Signal':<11} {'Thresh':>7} "
      f"{'Days':>5} {'VolOK':>6} {'Edge':>7}")
print("-"*105)

for r in results[:15]:
    sig = r["signal"]["direction"] if r["signal"] else "NONE"
    vol = "YES" if r["vol_ok"] else "NO"
    print(f"{r['question'][:51]:<52} {r['yes']*100:>4.1f}% "
          f"{sig:<11} {r['threshold']:>6.1f}%  "
          f"{r['days_left']:>5}  {vol:>5} {r['score']:>7.1f}")

buy_sigs   = [r for r in results if r["signal"] and r["signal"]["direction"] == "BUY_YES"]
short_sigs = [r for r in results if r["signal"] and r["signal"]["direction"] == "SHORT_YES"]
print(f"\nSignals: {len(buy_sigs)} BUY YES | {len(short_sigs)} SHORT YES")
print(f"Filters: adaptive threshold + volume confirmation + time decay")