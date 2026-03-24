import json
import math
from datetime import datetime

SIGNAL_WINDOW = 4
GAP_BUFFER    = 3
HOLD_DAYS     = 3

def compute_volatility(history):
    if len(history) < 5:
        return 0.02
    changes = []
    for i in range(1, len(history)):
        prev = float(history[i-1]["p"])
        curr = float(history[i]["p"])
        if prev > 0:
            changes.append(abs(curr - prev))
    if not changes:
        return 0.02
    mean     = sum(changes) / len(changes)
    variance = sum((c - mean) ** 2 for c in changes) / len(changes)
    return round(max(0.01, min(math.sqrt(variance) * 1.5, 0.08)), 4)

def volume_confirmed(market):
    try:
        volume_24h   = float(market.get("volume24hr", 0))
        volume_total = float(market.get("volumeNum", 0))
        start_date   = market.get("startDateIso", "")
        if not start_date or volume_total == 0:
            return False
        start     = datetime.fromisoformat(start_date)
        days      = max((datetime.now() - start).days, 1)
        avg_daily = volume_total / days
        return volume_24h >= avg_daily * 1
    except:
        return False

def days_to_resolution(market):
    try:
        end_date = market.get("endDateIso", "")
        if not end_date:
            return 999
        end = datetime.fromisoformat(end_date)
        return max((end - datetime.now()).days, 0)
    except:
        return 999

def time_decay_ok(market, min_days=3):
    return days_to_resolution(market) >= min_days

def split_history(history):
    total_reserved = SIGNAL_WINDOW + GAP_BUFFER
    if len(history) < total_reserved + 5:
        return None, None
    training = history[:-total_reserved]
    signal   = history[-SIGNAL_WINDOW:]
    return training, signal

def detect_signal(history, market, threshold=None):
    if not time_decay_ok(market):
        return None
    if not volume_confirmed(market):
        return None
    training, signal_window = split_history(history)
    if training is None or signal_window is None:
        return None
    adaptive = threshold or compute_volatility(training)
    past     = float(signal_window[0]["p"])
    curr     = float(signal_window[-1]["p"])
    change   = curr - past
    if curr < 0.04 or curr > 0.96:
        return None
    if change < -adaptive:
        return {"direction": "BUY_YES",   "change": round(change*100, 2),
                "entry": curr, "threshold": round(adaptive*100, 2),
                "days_left": days_to_resolution(market)}
    elif change > adaptive:
        return {"direction": "SHORT_YES", "change": round(change*100, 2),
                "entry": curr, "threshold": round(adaptive*100, 2),
                "days_left": days_to_resolution(market)}
    return None

def run_backtest(history, strategy="mean_revert"):
    training, _ = split_history(history)
    if training is None or len(training) < HOLD_DAYS + 6:
        return None

    adaptive        = compute_volatility(training)
    cash            = 1000.0
    trades          = []
    open_positions  = []
    portfolio_curve = []

    def mark_to_market(positions, curr_price):
        val = 0.0
        for pos in positions:
            if pos["direction"] == "BUY_YES":
                val += pos["size"] * (1 + (curr_price - pos["entry_price"])
                                      / pos["entry_price"])
            else:
                val += pos["size"] * (1 + (pos["entry_price"] - curr_price)
                                      / pos["entry_price"])
        return val

    for i in range(3, len(training) - HOLD_DAYS):
        # Close positions that have held long enough
        still_open = []
        for pos in open_positions:
            if i >= pos["entry_idx"] + HOLD_DAYS:
                exit_price = float(training[pos["entry_idx"] + HOLD_DAYS]["p"])
                if pos["direction"] == "BUY_YES":
                    pnl = pos["size"] * (exit_price - pos["entry_price"]) / pos["entry_price"]
                else:
                    pnl = pos["size"] * (pos["entry_price"] - exit_price) / pos["entry_price"]
                cash += pos["size"] + pnl
                trades.append({
                    "direction":   pos["direction"],
                    "entry_price": pos["entry_price"],
                    "exit_price":  exit_price,
                    "pnl":         round(pnl, 4),
                    "hold_days":   HOLD_DAYS,
                })
            else:
                still_open.append(pos)
        open_positions = still_open

        curr   = float(training[i]["p"])
        past   = float(training[i-3]["p"])
        change = curr - past

        if curr < 0.04 or curr > 0.96:
            portfolio_curve.append(round(cash + mark_to_market(open_positions, curr), 2))
            continue

        if len(open_positions) >= 3:
            portfolio_curve.append(round(cash + mark_to_market(open_positions, curr), 2))
            continue

        direction = None
        if strategy == "mean_revert":
            if change < -adaptive:
                direction = "BUY_YES"
            elif change > adaptive:
                direction = "SHORT_YES"
        elif strategy == "momentum":
            if change > adaptive:
                direction = "BUY_YES"
            elif change < -adaptive:
                direction = "SHORT_YES"

        bet_size = cash * 0.1
        if direction and bet_size >= 10:
            cash -= bet_size
            open_positions.append({
                "entry_idx":   i,
                "direction":   direction,
                "entry_price": curr,
                "size":        bet_size,
            })

        portfolio_curve.append(round(cash + mark_to_market(open_positions, curr), 2))

    # Close remaining at last price
    last_price = float(training[-1]["p"])
    for pos in open_positions:
        if pos["direction"] == "BUY_YES":
            pnl = pos["size"] * (last_price - pos["entry_price"]) / pos["entry_price"]
        else:
            pnl = pos["size"] * (pos["entry_price"] - last_price) / pos["entry_price"]
        cash += pos["size"] + pnl
        trades.append({
            "direction":   pos["direction"],
            "entry_price": pos["entry_price"],
            "exit_price":  last_price,
            "pnl":         round(pnl, 4),
            "hold_days":   "open",
        })

    if not trades:
        return None

    wins      = [t for t in trades if t["pnl"] > 0]
    total_pnl = cash - 1000.0
    win_rate  = len(wins) / len(trades) * 100
    pnls      = [t["pnl"] for t in trades]
    avg       = sum(pnls) / len(pnls)
    std       = (sum((x-avg)**2 for x in pnls)/len(pnls))**0.5
    sharpe    = avg / std if std > 0 else 0

    peak   = 1000.0
    max_dd = 0.0
    for val in portfolio_curve:
        if val > peak:
            peak = val
        dd     = (peak - val) / peak * 100 if peak > 0 else 0
        max_dd = max(max_dd, dd)

    return {
        "trades":       len(trades),
        "buy_trades":   len([t for t in trades if t["direction"]=="BUY_YES"]),
        "short_trades": len([t for t in trades if t["direction"]=="SHORT_YES"]),
        "wins":         len(wins),
        "win_rate":     round(win_rate, 1),
        "total_pnl":    round(total_pnl, 2),
        "sharpe":       round(sharpe, 2),
        "max_drawdown": round(max_dd, 1),
        "threshold":    round(adaptive*100, 2),
        "hold_days":    HOLD_DAYS,
        "final_cash":   round(cash, 2),
        "curve":        portfolio_curve,
    }

def kelly_fraction(history, threshold=None):
    training, _ = split_history(history)
    if training is None:
        return 0, 0
    adaptive     = threshold or compute_volatility(training)
    wins, losses = [], []
    for i in range(3, len(training) - HOLD_DAYS):
        past   = float(training[i-3]["p"])
        curr   = float(training[i]["p"])
        exit_  = float(training[i + HOLD_DAYS]["p"])
        if curr < 0.04 or curr > 0.96:
            continue
        change = curr - past
        if change < -adaptive:
            pnl = exit_ - curr
            wins.append(pnl) if pnl > 0 else losses.append(abs(pnl))
        elif change > adaptive:
            pnl = curr - exit_
            wins.append(pnl) if pnl > 0 else losses.append(abs(pnl))
    if not wins or not losses:
        return 0, 0
    win_prob = len(wins) / (len(wins) + len(losses))
    avg_win  = sum(wins)   / len(wins)
    avg_loss = sum(losses) / len(losses)
    b        = avg_win / avg_loss
    f        = (win_prob * b - (1 - win_prob)) / b
    return round(max(0, min(f, 0.25)), 4), round(win_prob, 3)

def analyze_orderbook(book):
    bids = book.get("bids", [])
    asks = book.get("asks", [])
    if not bids or not asks:
        return None
    bid_liq   = sum(float(b["size"]) for b in bids)
    ask_liq   = sum(float(a["size"]) for a in asks)
    total     = bid_liq + ask_liq
    if total == 0:
        return None
    imbalance = bid_liq / total
    best_bid  = float(bids[0]["price"])
    best_ask  = float(asks[0]["price"])
    bid_walls = len([b for b in bids if float(b["size"]) > 500])
    ask_walls = len([a for a in asks if float(a["size"]) > 500])
    if imbalance > 0.65:
        ob_signal = "BUY_PRESSURE"
    elif imbalance < 0.35:
        ob_signal = "SELL_PRESSURE"
    else:
        ob_signal = "NEUTRAL"
    return {
        "imbalance": round(imbalance, 3),
        "spread":    round(best_ask - best_bid, 4),
        "signal":    ob_signal,
        "bid_walls": bid_walls,
        "ask_walls": ask_walls,
    }

def ob_confirms_signal(ob, direction):
    if not ob:
        return False
    if direction == "BUY_YES":
        return ob["signal"] == "BUY_PRESSURE"
    elif direction == "SHORT_YES":
        return ob["signal"] == "SELL_PRESSURE"
    return False

def compute_confidence(signal, bt, kelly, win_prob, ob,
                        volume_24h, ai_result=None):
    score = 0.0
    if win_prob > 0.5:
        score += min((win_prob - 0.5) / 0.3 * 40, 40)
    threshold = signal.get("threshold", 2.0)
    change    = abs(signal.get("change", 0))
    if threshold > 0:
        score += min((change / threshold) * 8, 15)
    if ob and ob_confirms_signal(ob, signal["direction"]):
        score += 15
        imbalance = ob["imbalance"]
        extra = ((imbalance - 0.65) / 0.35 * 10
                 if signal["direction"] == "BUY_YES"
                 else (0.35 - imbalance) / 0.35 * 10)
        score += max(0, min(extra, 10))
    if bt and bt.get("max_drawdown", 0) > 20:
        score -= 5
    days = signal.get("days_left", 0)
    if days >= 60:   score += 10
    elif days >= 30: score += 7
    elif days >= 14: score += 4
    elif days >= 7:  score += 2
    if volume_24h >= 50000:   score += 10
    elif volume_24h >= 10000: score += 6
    elif volume_24h >= 1000:  score += 3
    if ai_result:
        if ai_result["action"] == "BUY":
            score += 10 if ai_result["confidence"] == "HIGH" else 5
        elif ai_result["action"] == "AVOID":
            score -= 10 if ai_result["confidence"] == "HIGH" else 5
    return round(min(max(score, 0), 100), 1)

def allocate_portfolio(signals, total_capital=10000,
                        max_positions=5, min_confidence=40):
    eligible = [s for s in signals
                if s.get("confidence", 0) >= min_confidence]
    eligible.sort(key=lambda x: x["confidence"], reverse=True)
    selected       = eligible[:max_positions]
    allocated      = []
    total_deployed = 0.0
    event_groups   = {}
    for s in selected:
        kelly    = s.get("kelly", 0)
        vol24    = s.get("vol24", 0)
        question = s["market"]["question"]
        group_key   = " ".join(question.split()[:3])
        group_count = event_groups.get(group_key, 0)
        vol_mult   = 1.0 if vol24 >= 10000 else \
                     0.7 if vol24 >= 1000  else 0.4
        group_mult = 1.0 if group_count == 0 else \
                     0.5 if group_count == 1 else 0.0
        if group_mult == 0.0:
            continue
        raw_alloc    = total_capital * kelly * vol_mult * group_mult
        capped_alloc = min(raw_alloc, total_capital * 0.25)
        if total_deployed + capped_alloc > total_capital * 0.80:
            capped_alloc = max(0, total_capital * 0.80 - total_deployed)
        if capped_alloc < 50:
            continue
        total_deployed         += capped_alloc
        event_groups[group_key] = group_count + 1
        allocated.append({
            **s,
            "allocated":     round(capped_alloc, 2),
            "allocated_pct": round(capped_alloc / total_capital * 100, 1),
            "vol_mult":      vol_mult,
            "group_mult":    group_mult,
        })
    return allocated, round(total_capital - total_deployed, 2)