"""
Level-watch: continuously checks NQ / DXY / Gold spot price against
Daily / Weekly / Monthly OHLC levels (prior period High, Low, Close)
and fires a Telegram alert the first time price touches/crosses one.

Runs on its own frequent GitHub Actions cron (separate from the two
pre-session reports), free-tier friendly - one lightweight yfinance
call per instrument, no macro calendar hit.

State is tracked in data/level_alert_state.json so the same level
doesn't spam you every 15 minutes once touched - each level fires
once per UTC calendar day, then resets.
"""
from __future__ import annotations
import datetime as dt
import json
import os
import pandas as pd
from app.logger import get_logger

log = get_logger(__name__)

try:
    import yfinance as yf
except ImportError:  # pragma: no cover
    yf = None

STATE_PATH = "data/level_alert_state.json"

# How close (as a fraction of price) counts as "touching" a level.
# 0.0008 = 0.08%, tight enough to mean a real touch, loose enough to
# not be missed between 15-minute checks. Tune per instrument if needed.
TOUCH_TOLERANCE = {
    "NQ": 0.0008,
    "DXY": 0.0008,
    "GC": 0.0008,
}


def _load_state() -> dict:
    if not os.path.exists(STATE_PATH):
        return {"date": "", "triggered": {}}
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except Exception:
        return {"date": "", "triggered": {}}


def _save_state(state: dict):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


def _reset_state_if_new_day(state: dict) -> dict:
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    if state.get("date") != today:
        return {"date": today, "triggered": {}}
    return state


def _compute_levels(daily_df: pd.DataFrame) -> dict:
    """
    Returns prior Day/Week/Month High/Low/Close from a daily OHLC
    DataFrame (needs >= ~35 daily bars to safely derive a full prior
    week and prior month).
    """
    levels = {}
    if daily_df is None or daily_df.empty or len(daily_df) < 3:
        return levels

    # Prior day = second-to-last row (last row is "today", still forming)
    prior_day = daily_df.iloc[-2]
    levels["Prior Day High"] = float(prior_day["High"])
    levels["Prior Day Low"] = float(prior_day["Low"])
    levels["Prior Day Close"] = float(prior_day["Close"])

    # Weekly resample (W-FRI so the week ends Friday, standard for futures/FX)
    weekly = daily_df.resample("W-FRI").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last"}
    )
    if len(weekly) >= 2:
        prior_week = weekly.iloc[-2]
        levels["Prior Week High"] = float(prior_week["High"])
        levels["Prior Week Low"] = float(prior_week["Low"])
        levels["Prior Week Close"] = float(prior_week["Close"])

    # Monthly resample
    monthly = daily_df.resample("ME").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last"}
    )
    if len(monthly) >= 2:
        prior_month = monthly.iloc[-2]
        levels["Prior Month High"] = float(prior_month["High"])
        levels["Prior Month Low"] = float(prior_month["Low"])
        levels["Prior Month Close"] = float(prior_month["Close"])

    return levels


def fetch_levels_for_instrument(ticker: str, fallback_ticker: str | None) -> dict:
    """Pulls ~90 days of daily bars (enough for prior D/W/M) and returns
    both the current spot price and the computed level dict."""
    if yf is None:
        return {"ok": False, "reason": "yfinance not installed"}

    for candidate in [ticker, fallback_ticker]:
        if not candidate:
            continue
        try:
            tk = yf.Ticker(candidate)
            daily = tk.history(period="90d", interval="1d")
            intraday = tk.history(period="2d", interval="15m")
            if daily.empty:
                continue
            spot = float(intraday["Close"].iloc[-1]) if not intraday.empty else float(daily["Close"].iloc[-1])
            levels = _compute_levels(daily)
            return {"ok": True, "ticker_used": candidate, "spot": spot, "levels": levels}
        except Exception as e:
            log.warning(f"Level fetch failed for {candidate}: {e}")
            continue
    return {"ok": False, "reason": f"all tickers failed for {ticker}/{fallback_ticker}"}


def check_all_levels(cfg: dict) -> list[dict]:
    """
    Returns a list of freshly-triggered touch events (not yet alerted
    today), each: {"instrument": "NQ", "level_name": "Prior Week High",
    "level_value": ..., "spot": ...}
    """
    state = _load_state()
    state = _reset_state_if_new_day(state)

    events = []
    for key, meta in cfg["instruments"].items():
        if key == "TNX":
            continue  # yield isn't a tradeable level-touch instrument here
        result = fetch_levels_for_instrument(meta["yf_ticker"], meta.get("fallback_ticker"))
        if not result.get("ok"):
            log.warning(f"{key}: level check skipped - {result.get('reason')}")
            continue

        spot = result["spot"]
        tol = TOUCH_TOLERANCE.get(key, 0.001)
        already = state["triggered"].setdefault(key, [])

        for level_name, level_value in result["levels"].items():
            if level_value is None or level_value == 0:
                continue
            distance = abs(spot - level_value) / level_value
            touched = distance <= tol
            if touched and level_name not in already:
                events.append({
                    "instrument": key,
                    "level_name": level_name,
                    "level_value": level_value,
                    "spot": spot,
                })
                already.append(level_name)

    _save_state(state)
    return events


def format_alert_message(events: list[dict]) -> str:
    lines = ["🔔 Level Alert"]
    for e in events:
        lines.append(
            f"{e['instrument']}: touched {e['level_name']} "
            f"({e['level_value']:,.2f}) — spot {e['spot']:,.2f}"
        )
    return "\n".join(lines)
