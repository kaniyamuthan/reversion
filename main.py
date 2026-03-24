import requests
import json
from datetime import datetime
import urllib.parse
import xml.etree.ElementTree as ET
from utils import (detect_signal, run_backtest, kelly_fraction,
                   analyze_orderbook, ob_confirms_signal,
                   compute_volatility, days_to_resolution,
                   compute_confidence, allocate_portfolio)

from groq import Groq
from dotenv import load_dotenv
import os
load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def get_markets(limit=50):
    r = requests.get("https://gamma-api.polymarket.com/markets",
                     params={"active":"true","closed":"false","limit":limit})
    return r.json()

def get_price_history(token_id):
    try:
        r = requests.get("https://clob.polymarket.com/prices-history",
                         params={"market":token_id,"interval":"max","fidelity":1440},
                         timeout=10)
        return r.json().get("history", [])
    except:
        return []

def get_orderbook(token_id):
    r = requests.get("https://clob.polymarket.com/book",
                     params={"token_id": token_id})
    return r.json()

def get_news(query, max_results=4):
    try:
        encoded = urllib.parse.quote(query)
        url  = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
        r    = requests.get(url, timeout=5)
        root = ET.fromstring(r.content)
        out  = []
        for item in root.findall(".//item")[:max_results]:
            t = item.find("title")
            d = item.find("pubDate")
            if t is not None:
                out.append({"title": t.text,
                            "date": d.text[:16] if d is not None else ""})
        return out
    except:
        return []

def ask_ai(question, yes_price, change_3d, direction,
           description, headlines, ob, threshold, days_left):
    news_block = "\n".join(
        f"  [{h['date']}] {h['title']}" for h in headlines
    ) if headlines else "  No recent headlines."
    ob_block = (f"  {ob['signal']} imbalance:{ob['imbalance']:.1%} "
                f"spread:{ob['spread']:.3f}"
                if ob else "  Unavailable")
    direction_text = (
        "Price DROPPED — BUY YES (mean reversion up)"
        if direction == "BUY_YES" else
        "Price ROSE — SHORT YES (mean reversion down)"
    )
    prompt = f"""Quantitative analyst reviewing a Polymarket signal.

MARKET: "{question}"
YES probability : {yes_price*100:.1f}%
3-day change    : {change_3d:+.1f}%
Threshold       : {threshold}% (adaptive volatility)
Days left       : {days_left}
Signal          : {direction_text}
Description     : {description[:250]}
ORDERBOOK       : {ob_block}
NEWS:
{news_block}

JSON only:
{{
  "action": "BUY" or "AVOID",
  "confidence": "HIGH" or "MEDIUM" or "LOW",
  "news_driven": true or false,
  "ob_confirms": true or false,
  "reason": "one sentence",
  "risk": "one sentence"
}}"""
    resp = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=250, temperature=0.1
    )
    raw = resp.choices[0].message.content
    raw = raw.strip().replace("```json","").replace("```","").strip()
    return json.loads(raw)

def main():
    TOTAL_CAPITAL  = 10000
    MAX_POSITIONS  = 5
    MIN_CONFIDENCE = 20

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("="*70)
    print("  ORDERFLOW 001 — POLYMARKET QUANT SYSTEM")
    print(f"  {ts}")
    print("  Signal → Confidence Score → Portfolio Allocation")
    print("="*70)

    print("\n[1/5] Fetching markets...")
    markets = get_markets(50)
    print(f"      {len(markets)} markets loaded")

    print("[2/5] Signal detection...")
    raw_signals = []
    for m in markets:
        try:
            token_ids = json.loads(m.get("clobTokenIds","[]"))
            if not token_ids:
                continue
            yes_token = token_ids[0]
            history   = get_price_history(yes_token)
            signal    = detect_signal(history, m)
            if not signal:
                continue
            bt        = run_backtest(history)
            kelly, wp = kelly_fraction(history)
            book      = get_orderbook(yes_token)
            ob        = analyze_orderbook(book)
            confirmed = ob_confirms_signal(ob, signal["direction"])
            yes_price = float(json.loads(m["outcomePrices"])[0])
            vol24     = float(m.get("volume24hr", 0))
            raw_signals.append({
                "market":    m,
                "yes_price": yes_price,
                "signal":    signal,
                "bt":        bt,
                "kelly":     kelly,
                "win_prob":  wp,
                "ob":        ob,
                "confirmed": confirmed,
                "vol24":     vol24,
                "ai":        None,
                "headlines": [],
            })
        except Exception as e:
            continue

    buys   = len([s for s in raw_signals if s["signal"]["direction"]=="BUY_YES"])
    shorts = len([s for s in raw_signals if s["signal"]["direction"]=="SHORT_YES"])
    print(f"      {len(raw_signals)} signals ({buys} BUY, {shorts} SHORT)")

    print("[3/5] AI validation (optional)...")
    ai_ok = ai_fail = 0
    for s in raw_signals:
        try:
            m         = s["market"]
            signal    = s["signal"]
            headlines = get_news(
                m["question"].replace("Will","").replace("?","").strip()
            )
            ai = ask_ai(
                question    = m["question"],
                yes_price   = s["yes_price"],
                change_3d   = signal["change"],
                direction   = signal["direction"],
                description = m.get("description",""),
                headlines   = headlines,
                ob          = s["ob"],
                threshold   = signal["threshold"],
                days_left   = signal["days_left"],
            )
            s["ai"]        = ai
            s["headlines"] = headlines
            ai_ok += 1
        except:
            ai_fail += 1
            continue
    print(f"      AI ok: {ai_ok} | failed (graceful): {ai_fail}")

    print("[4/5] Confidence scoring + ranking...")
    for s in raw_signals:
        s["confidence"] = compute_confidence(
            signal     = s["signal"],
            bt         = s["bt"],
            kelly      = s["kelly"],
            win_prob   = s["win_prob"],
            ob         = s["ob"],
            volume_24h = s["vol24"],
            ai_result  = s["ai"],
        )
    raw_signals.sort(key=lambda x: x["confidence"], reverse=True)

    print(f"\n      SIGNAL RANKING:")
    print(f"      {'Market':<45} {'Dir':<10} {'Conf':>5} "
          f"{'WinP':>5} {'Kelly':>6} {'OB':>4} {'AI'}")
    print("      " + "-"*88)
    for s in raw_signals:
        ob_tag = "Y" if s["confirmed"] else "N"
        ai_tag = (s["ai"]["action"][:3] + f"({s['ai']['confidence'][0]})"
                  if s["ai"] else "N/A")
        print(f"      {s['market']['question'][:44]:<45} "
              f"{s['signal']['direction']:<10} "
              f"{s['confidence']:>5.1f} "
              f"{s['win_prob']*100:>4.0f}% "
              f"{s['kelly']*100:>5.1f}%  "
              f"{ob_tag:>3}  {ai_tag}")

    print(f"\n[5/5] Portfolio allocation "
          f"(${TOTAL_CAPITAL:,} capital, "
          f"max {MAX_POSITIONS} positions, "
          f"min confidence {MIN_CONFIDENCE})...")
    allocated, cash_reserve = allocate_portfolio(
        raw_signals,
        total_capital  = TOTAL_CAPITAL,
        max_positions  = MAX_POSITIONS,
        min_confidence = MIN_CONFIDENCE,
    )

    print("\n" + "="*70)
    print("  EXECUTION REPORT")
    print("="*70)

    if allocated:
        for s in allocated:
            m      = s["market"]
            signal = s["signal"]
            bt     = s["bt"] or {}
            ai     = s["ai"]
            trade  = ("BUY YES — price dropped, expect bounce"
                      if signal["direction"] == "BUY_YES"
                      else "SHORT YES — price rose, expect reversal")
            print(f"\n  Market     : {m['question'][:60]}")
            print(f"  Action     : {trade}")
            print(f"  Confidence : {s['confidence']}/100")
            print(f"  Allocation : ${s['allocated']:,.2f} "
                  f"({s['allocated_pct']:.1f}% of portfolio)")
            print(f"  Price      : {s['yes_price']*100:.1f}%  "
                  f"({signal['change']:+.1f}% / 3d | "
                  f"threshold: {signal['threshold']}%)")
            print(f"  Days left  : {signal['days_left']}")
            print(f"  Win prob   : {s['win_prob']*100:.1f}%  "
                  f"Kelly: {s['kelly']*100:.1f}%")
            if bt:
                print(f"  Backtest   : {bt.get('trades',0)} trades | "
                      f"{bt.get('win_rate',0)}% win | "
                      f"${bt.get('total_pnl',0):+,.2f} PnL | "
                      f"MaxDD: {bt.get('max_drawdown',0):.1f}%")
            if s["ob"]:
                conf_tag = "CONFIRMED" if s["confirmed"] else "not confirmed"
                print(f"  Orderbook  : {s['ob']['signal']} "
                      f"({s['ob']['imbalance']:.1%}) — {conf_tag}")
            if ai:
                print(f"  AI         : {ai['action']} ({ai['confidence']}) "
                      f"— {ai['reason'][:55]}")
            else:
                print(f"  AI         : unavailable (quant score used)")
            if s["headlines"]:
                print(f"  News       : {s['headlines'][0]['title'][:58]}")
            print(f"  " + "-"*65)
    else:
        print("\n  No signals meet minimum confidence threshold.")
        if raw_signals:
            best = raw_signals[0]
            print(f"  Best signal : {best['market']['question'][:50]}")
            print(f"  Its score   : {best['confidence']}/100")
            print(f"  Min needed  : {MIN_CONFIDENCE}/100")

    total_deployed = sum(s["allocated"] for s in allocated)
    print(f"\n{'='*70}")
    print(f"  PORTFOLIO SUMMARY")
    print(f"{'='*70}")
    print(f"  Total capital     : ${TOTAL_CAPITAL:,}")
    print(f"  Positions taken   : {len(allocated)} / {MAX_POSITIONS} max")
    print(f"  Capital deployed  : ${total_deployed:,.2f} "
          f"({total_deployed/TOTAL_CAPITAL*100:.1f}%)")
    print(f"  Cash reserve      : ${cash_reserve:,.2f} "
          f"({cash_reserve/TOTAL_CAPITAL*100:.1f}%)")

    print(f"\n{'='*70}")
    print(f"  PIPELINE (7 layers):")
    print(f"{'='*70}")
    print(f"  1. Signal detection    — adaptive threshold + 3 filters")
    print(f"  2. Data split          — training/gap/signal (no leakage)")
    print(f"  3. Walk-forward BT     — mark-to-market equity curve")
    print(f"  4. Kelly Criterion     — optimal bet sizing")
    print(f"  5. Orderbook depth     — bid/ask confirmation")
    print(f"  6. AI + news filter    — optional LLaMA validator")
    print(f"  7. Confidence + alloc  — ranked, capital-constrained")
    print(f"\n  AI is optional — quant edge is in layers 1-5 + 7.")
    print("="*70)
    # Always show backtest stats even if no trades executed
    print(f"\n{'='*70}")
    print(f"  HISTORICAL BACKTEST STATS")
    print(f"{'='*70}")
    bt_signals = [s for s in raw_signals if s.get("bt")]
    if bt_signals:
        best_bt  = max(bt_signals, key=lambda x: x["bt"]["total_pnl"])
        avg_wr   = sum(s["bt"]["win_rate"] for s in bt_signals) / len(bt_signals)
        total_t  = sum(s["bt"]["trades"]   for s in bt_signals)
        avg_dd   = sum(s["bt"]["max_drawdown"] for s in bt_signals) / len(bt_signals)
        print(f"  Signals with history  : {len(bt_signals)}")
        print(f"  Best PnL              : ${best_bt['bt']['total_pnl']:+,.2f}")
        print(f"  Avg win rate          : {avg_wr:.1f}%")
        print(f"  Avg max drawdown      : {avg_dd:.1f}%")
        print(f"  Total trades tested   : {total_t}")
        print(f"  Hold period           : {best_bt['bt']['hold_days']} days")
    else:
        print(f"  No backtest data available for current signals")
    print("="*70)

if __name__ == "__main__":
    main()