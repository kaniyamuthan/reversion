import requests
import json
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
from utils import run_backtest, compute_volatility, split_history

def get_markets():
    r = requests.get("https://gamma-api.polymarket.com/markets",
                     params={"active": "true", "closed": "false", "limit": 30})
    return r.json()

def get_price_history(token_id):
    r = requests.get("https://clob.polymarket.com/prices-history",
                     params={"market": token_id, "interval": "max", "fidelity": 1440})
    return r.json().get("history", [])

print("Fetching markets and building charts...")
markets = get_markets()

bt_results = []
for m in markets:
    token_ids = json.loads(m.get("clobTokenIds", "[]"))
    if not token_ids:
        continue
    history = get_price_history(token_ids[0])
    res     = run_backtest(history)
    if res and res["trades"] >= 3:
        bt_results.append((m, history, res))

bt_results.sort(key=lambda x: x[2]["total_pnl"], reverse=True)
top5 = bt_results[:5]

fig, axes = plt.subplots(2, 1, figsize=(13, 10))
fig.patch.set_facecolor("#0f0f1a")
for ax in axes:
    ax.set_facecolor("#0f0f1a")

colors = ["#00ff88", "#ff6b6b", "#00aaff", "#ffcc00", "#bb88ff"]
ax1    = axes[0]

for (m, history, res), color in zip(top5, colors):
    curve  = res.get("curve", [])
    if not curve:
        continue
    # Use training history timestamps for x-axis
    training, _ = split_history(history)
    if training is None:
        continue
    ts_slice = training[3:3+len(curve)]
    if not ts_slice:
        continue
    dates = [datetime.fromtimestamp(p["t"]) for p in ts_slice]
    # Trim to same length
    min_len = min(len(dates), len(curve))
    ax1.plot(dates[:min_len], curve[:min_len],
             color=color, linewidth=1.8,
             label=m["question"][:38] + "...")

ax1.axhline(1000, color="#555555", linestyle="--",
            linewidth=1, label="Starting capital ($1,000)")
ax1.set_title("Mean Reversion — True Equity Curve (Cash + Open Positions)",
              color="white", fontsize=12, pad=10)
ax1.set_ylabel("Portfolio Value ($)", color="white")
ax1.tick_params(colors="white")
ax1.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
ax1.legend(fontsize=7, facecolor="#1a1a2e", labelcolor="white", loc="upper left")
ax1.spines[["top","right","left","bottom"]].set_color("#333355")
ax1.grid(True, alpha=0.15, color="white")

ax2       = axes[1]
labels    = [r[0]["question"][:20] + "..." for r in top5]
win_rates = [r[2]["win_rate"]     for r in top5]
max_dds   = [r[2]["max_drawdown"] for r in top5]
pnls      = [r[2]["total_pnl"]   for r in top5]

bar_colors = ["#00ff88" if w >= 50 else "#ff6b6b" for w in win_rates]
bars = ax2.bar(labels, win_rates, color=bar_colors,
               edgecolor="#333355", linewidth=0.8)

for bar, pnl, dd in zip(bars, pnls, max_dds):
    ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
             f"${pnl:+,.0f}\nDD:{dd:.1f}%",
             ha="center", va="bottom", color="white", fontsize=7)

ax2.axhline(50, color="#ffcc00", linestyle="--",
            linewidth=1.2, label="50% baseline")
ax2.set_title("Win Rate + Max Drawdown by Market",
              color="white", fontsize=12, pad=10)
ax2.set_ylabel("Win Rate (%)", color="white")
ax2.set_ylim(0, 85)
ax2.tick_params(colors="white")
ax2.legend(facecolor="#1a1a2e", labelcolor="white")
ax2.spines[["top","right","left","bottom"]].set_color("#333355")
ax2.grid(True, alpha=0.15, color="white", axis="y")

plt.tight_layout(pad=3)
plt.savefig("backtest_results.png", dpi=150,
            bbox_inches="tight", facecolor="#0f0f1a")
print("Chart saved as backtest_results.png")
plt.show()