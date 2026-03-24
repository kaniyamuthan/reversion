import requests
import json
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime
from groq import Groq
from utils import detect_signal, compute_volatility

from dotenv import load_dotenv
import os
load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def get_markets():
    r = requests.get("https://gamma-api.polymarket.com/markets",
                     params={"active": "true", "closed": "false", "limit": 50})
    return r.json()

def get_price_history(token_id):
    r = requests.get("https://clob.polymarket.com/prices-history",
                     params={"market": token_id, "interval": "max", "fidelity": 1440})
    return r.json().get("history", [])

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
           description, headlines, threshold, days_left):
    news_block = "\n".join(
        f"  [{h['date']}] {h['title']}" for h in headlines
    ) if headlines else "  No recent headlines."
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
Description     : {description[:300]}

NEWS:
{news_block}

JSON only:
{{
  "action": "BUY" or "AVOID",
  "confidence": "HIGH" or "MEDIUM" or "LOW",
  "news_driven": true or false,
  "reason": "one sentence",
  "risk": "one sentence"
}}"""
    resp = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=300, temperature=0.1
    )
    raw = resp.choices[0].message.content
    raw = raw.strip().replace("```json","").replace("```","").strip()
    return json.loads(raw)

print("="*65)
print("  AI + NEWS SIGNAL ANALYZER")
print("  Adaptive threshold | Volume | Time decay | Two-sided")
print("="*65)

markets  = get_markets()
analyzed = 0
buys     = 0
avoids   = 0

for m in markets:
    try:
        token_ids = json.loads(m.get("clobTokenIds", "[]"))
        if not token_ids:
            continue
        history = get_price_history(token_ids[0])
        signal  = detect_signal(history, m)
        if not signal:
            continue
        yes_price = float(json.loads(m["outcomePrices"])[0])
        question  = m["question"]
        tag       = "BUY" if signal["direction"] == "BUY_YES" else "SHORT"
        print(f"\n[{tag}] {question[:52]}...")
        headlines = get_news(question.replace("Will","").replace("?","").strip())
        ai = ask_ai(
            question    = question,
            yes_price   = yes_price,
            change_3d   = signal["change"],
            direction   = signal["direction"],
            description = m.get("description",""),
            headlines   = headlines,
            threshold   = signal["threshold"],
            days_left   = signal["days_left"],
        )
        trade = "BUY YES" if signal["direction"] == "BUY_YES" else "SHORT YES"
        print(f"  Trade      : {trade}")
        print(f"  Threshold  : {signal['threshold']}% adaptive")
        print(f"  Days left  : {signal['days_left']}")
        print(f"  AI         : {ai['action']} ({ai['confidence']})")
        print(f"  Reason     : {ai['reason']}")
        if headlines:
            print(f"  News       : {headlines[0]['title'][:60]}")
        analyzed += 1
        if ai["action"] == "BUY":
            buys += 1
        else:
            avoids += 1
    except Exception as e:
        print(f"  Skipped: {e}")

print(f"\n{'='*65}")
print(f"  Scanned: {len(markets)} | Signals: {analyzed} | "
      f"Approved: {buys} | Filtered: {avoids}")
print("="*65)