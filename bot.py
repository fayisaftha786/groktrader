"""Grok-driven trading bot for Coinbase Advanced Trade.

Grok (xAI API) reads recent candle data and answers BUY / SELL / HOLD.
Hard risk rules in THIS code (stop-loss, take-profit, size caps, daily
trade cap) always override Grok. Default mode is PAPER (no real orders).
"""
import csv
import json
import os
import time
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# ---------- config ----------
PRODUCT = os.getenv("PRODUCT_ID", "BTC-USD")
GRANULARITY = os.getenv("GRANULARITY", "ONE_HOUR")  # ONE_MINUTE, FIVE_MINUTE, FIFTEEN_MINUTE, ONE_HOUR, SIX_HOUR, ONE_DAY
CANDLES = int(os.getenv("CANDLES", "48"))
LOOP_SECONDS = int(os.getenv("LOOP_SECONDS", "900"))
TRADE_USD = float(os.getenv("TRADE_USD", "25"))          # size of each buy
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "3"))
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", "5"))
MAX_TRADES_PER_DAY = int(os.getenv("MAX_TRADES_PER_DAY", "6"))
MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE", "0.65"))
LIVE = os.getenv("LIVE", "false").lower() == "true"       # real money only if true
GROK_MODEL = os.getenv("GROK_MODEL", "grok-4")
PAPER_START_USD = float(os.getenv("PAPER_START_USD", "1000"))

BASE = PRODUCT.split("-")[0]
GRAN_SECONDS = {"ONE_MINUTE": 60, "FIVE_MINUTE": 300, "FIFTEEN_MINUTE": 900,
                "THIRTY_MINUTE": 1800, "ONE_HOUR": 3600, "TWO_HOUR": 7200,
                "SIX_HOUR": 21600, "ONE_DAY": 86400}

grok = OpenAI(api_key=os.environ["XAI_API_KEY"], base_url="https://api.x.ai/v1")

cb = None
if LIVE or os.getenv("COINBASE_API_KEY"):
    from coinbase.rest import RESTClient
    cb = RESTClient(api_key=os.environ["COINBASE_API_KEY"],
                    api_secret=os.environ["COINBASE_API_SECRET"].replace("\\n", "\n"))
else:
    from coinbase.rest import RESTClient
    cb = RESTClient()  # public market data works without keys

STATE_FILE = "state.json"
LOG_FILE = "trades.csv"
LAST = {"time": None, "price": None, "action": None, "conf": None, "reason": None, "error": None}


def g(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


# ---------- state (paper portfolio + open position) ----------
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"paper_usd": PAPER_START_USD, "paper_base": 0.0, "entry_price": None,
            "trades_today": 0, "day": datetime.now(timezone.utc).strftime("%Y-%m-%d")}


def save_state(s):
    with open(STATE_FILE, "w") as f:
        json.dump(s, f, indent=2)


def log_trade(row):
    new = not os.path.exists(LOG_FILE)
    with open(LOG_FILE, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time_utc", "mode", "side", "price", "size_base", "usd", "reason"])
        w.writerow(row)


# ---------- market data ----------
def get_candles():
    end = int(time.time())
    start = end - GRAN_SECONDS[GRANULARITY] * CANDLES
    res = cb.get_public_candles(product_id=PRODUCT, start=start, end=end, granularity=GRANULARITY)
    rows = sorted(g(res, "candles"), key=lambda c: int(g(c, "start")))
    return [{"t": int(g(c, "start")), "o": float(g(c, "open")), "h": float(g(c, "high")),
             "l": float(g(c, "low")), "c": float(g(c, "close")), "v": float(g(c, "volume"))}
            for c in rows]


def live_balance(currency):
    accts = g(cb.get_accounts(limit=250), "accounts")
    for a in accts:
        if g(a, "currency") == currency:
            return float(g(g(a, "available_balance"), "value"))
    return 0.0


# ---------- Grok decision ----------
SYSTEM = (
    "You are a cautious crypto trading analyst. Given recent OHLCV candles and the "
    "current position, reply with ONLY a JSON object: "
    '{"action":"BUY|SELL|HOLD","confidence":0-1,"reason":"short"}. '
    "Prefer HOLD when the signal is unclear. Only BUY if flat, only SELL if holding."
)


def ask_grok(candles, holding, entry):
    compact = [[c["t"], c["o"], c["h"], c["l"], c["c"], round(c["v"], 2)] for c in candles]
    user = (f"Product: {PRODUCT}, granularity: {GRANULARITY}\n"
            f"Candles [time,open,high,low,close,volume]: {json.dumps(compact)}\n"
            f"Currently holding: {holding}. Entry price: {entry}.")
    r = grok.chat.completions.create(
        model=GROK_MODEL, temperature=0.2,
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}])
    text = r.choices[0].message.content.strip()
    text = text[text.find("{"): text.rfind("}") + 1]
    try:
        d = json.loads(text)
        return d["action"].upper(), float(d.get("confidence", 0)), str(d.get("reason", ""))[:200]
    except Exception:
        return "HOLD", 0.0, "unparseable Grok reply"


# ---------- execution ----------
def buy(state, price):
    mode = "LIVE" if LIVE else "PAPER"
    if LIVE:
        if live_balance("USD") < TRADE_USD:
            print("Not enough USD, skipping buy"); return
        res = cb.market_order_buy(client_order_id=str(uuid.uuid4()), product_id=PRODUCT,
                                  quote_size=f"{TRADE_USD:.2f}")
        if not g(res, "success"):
            print("Buy order rejected:", g(res, "error_response") or res); return
        size = TRADE_USD / price
        state["bot_base"] = state.get("bot_base", 0.0) + size
    else:
        if state["paper_usd"] < TRADE_USD:
            print("Not enough paper USD"); return
        size = TRADE_USD / price
        state["paper_usd"] -= TRADE_USD
        state["paper_base"] += size
    state["entry_price"] = price
    state["trades_today"] += 1
    log_trade([datetime.now(timezone.utc).isoformat(), mode, "BUY", price, size, TRADE_USD, ""])
    print(f"[{mode}] BUY ~{size:.6f} {BASE} @ {price}")


def sell(state, price, reason):
    mode = "LIVE" if LIVE else "PAPER"
    size = min(live_balance(BASE), state.get("bot_base", 0.0)) if LIVE else state["paper_base"]
    if size <= 0:
        return
    if LIVE:
        info = cb.get_product(PRODUCT)
        inc = g(info, "base_increment") or "0.00000001"
        decimals = len(inc.split(".")[1].rstrip("0")) if "." in inc else 0
        size_str = f"{int(size * 10**decimals) / 10**decimals:.{decimals}f}"
        res = cb.market_order_sell(client_order_id=str(uuid.uuid4()), product_id=PRODUCT,
                                   base_size=size_str)
        if not g(res, "success"):
            print("Sell order rejected:", g(res, "error_response") or res); return
        state["bot_base"] = 0.0
    else:
        state["paper_usd"] += size * price
        state["paper_base"] = 0.0
    pnl = (price / state["entry_price"] - 1) * 100 if state["entry_price"] else 0
    state["entry_price"] = None
    state["trades_today"] += 1
    log_trade([datetime.now(timezone.utc).isoformat(), mode, "SELL", price, size, size * price, reason])
    print(f"[{mode}] SELL {size:.6f} {BASE} @ {price} (PnL {pnl:+.2f}%) - {reason}")


def tick(state):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if state["day"] != today:
        state["day"], state["trades_today"] = today, 0

    candles = get_candles()
    price = candles[-1]["c"]
    base_held = state.get("bot_base", 0.0) if LIVE else state["paper_base"]
    holding = base_held * price > 1.0  # ignore dust under $1
    entry = state["entry_price"]

    # hard risk rules first (override Grok)
    if holding and entry:
        chg = (price / entry - 1) * 100
        if chg <= -STOP_LOSS_PCT:
            sell(state, price, f"stop-loss {chg:.2f}%"); return
        if chg >= TAKE_PROFIT_PCT:
            sell(state, price, f"take-profit {chg:.2f}%"); return

    if state["trades_today"] >= MAX_TRADES_PER_DAY:
        print("Daily trade cap reached, holding."); return

    action, conf, reason = ask_grok(candles, holding, entry)
    LAST.update(time=datetime.now().strftime("%H:%M:%S"), price=price, action=action,
                conf=conf, reason=reason)
    print(f"{datetime.now():%H:%M} price={price} grok={action} conf={conf:.2f} ({reason})")

    if conf < MIN_CONFIDENCE:
        return
    if action == "BUY" and not holding:
        buy(state, price)
    elif action == "SELL" and holding:
        sell(state, price, f"grok: {reason}")


def main():
    mode = "LIVE (REAL MONEY)" if LIVE else "PAPER"
    print(f"Starting {PRODUCT} bot in {mode} mode. Ctrl+C to stop.")
    if LIVE and input("Type YES to trade with real money: ") != "YES":
        return
    state = load_state()
    while True:
        try:
            tick(state)
            save_state(state)
        except Exception as e:
            print("Error:", e)
        time.sleep(LOOP_SECONDS)


if __name__ == "__main__":
    main()
