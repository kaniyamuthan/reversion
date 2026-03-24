import requests
import json
import time
from datetime import datetime
from utils import detect_signal, days_to_resolution

def get_markets():
    r = requests.get("https://gamma-api.polymarket.com/markets",
                     params={"active": "true", "closed": "false", "limit": 50})
    return r.json()

def get_price_history(token_id):
    r = requests.get("https://clob.polymarket.com/prices-history",
                     params={"market": token_id, "interval": "max", "fidelity": 1440})
    return r.json().get("history", [])

def scan_once(seen_signals):
    markets     = get_markets()
    new_signals = []
    for m in markets:
        token_ids = json.loads(m.get("clobTokenIds", "[]"))
        if not token_ids:
            continue
        history = get_price_history(token_ids[0])
        signal  = detect_signal(history, m)
        if not signal:
            continue
        key = m["question"][:60] + signal["direction"]
        if key in seen_signals:
            continue
        seen_signals.add(key)
        signal["question"]   = m["question"]
        signal["volume_24h"] = float(m.get("volume24hr", 0))
        signal["liquidity"]  = float(m.get("liquidityNum", 0))
        signal["yes_price"]  = float(json.loads(m["outcomePrices"])[0])
        signal["days_left"]  = days_to_resolution(m)
        new_signals.append(signal)
    return new_signals

def print_signal(sig):
    ts    = datetime.now().strftime("%H:%M:%S")
    trade = ("BUY YES  — price dropped, expect bounce"
             if sig["direction"] == "BUY_YES" else
             "SHORT YES — price rose, expect reversal")
    print(f"\n{'='*65}")
    print(f"  SIGNAL @ {ts}")
    print(f"{'='*65}")
    print(f"  Market     : {sig['question'][:60]}")
    print(f"  Action     : {trade}")
    print(f"  Price      : {sig['yes_price']*100:.1f}%  "
          f"({sig['change']:+.1f}% / 3d)")
    print(f"  Threshold  : {sig['threshold']}% (adaptive)")
    print(f"  Days left  : {sig['days_left']}")
    print(f"  Volume 24h : ${sig['volume_24h']:,.0f}")

SCAN_INTERVAL = 300
print("="*65)
print("  ORDERFLOW BOT — LIVE SIGNAL MONITOR")
print("  Adaptive threshold | Volume filter | Time decay")
print(f"  Scanning every {SCAN_INTERVAL//60} min | Ctrl+C to stop")
print("="*65)

seen_signals = set()
scan_count   = 0

while True:
    scan_count += 1
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"\n[{ts}] Scan #{scan_count}...", end=" ")
    try:
        signals = scan_once(seen_signals)
        if signals:
            buys   = [s for s in signals if s["direction"] == "BUY_YES"]
            shorts = [s for s in signals if s["direction"] == "SHORT_YES"]
            print(f"{len(signals)} signal(s) "
                  f"({len(buys)} BUY, {len(shorts)} SHORT)")
            for sig in signals:
                print_signal(sig)
        else:
            print("No new signals.")
    except Exception as e:
        print(f"Error: {e}")
    time.sleep(SCAN_INTERVAL)