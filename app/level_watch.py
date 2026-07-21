"""
Level Watch

Checks NQ / DXY / Gold against previous Day / Week / Month
High, Low and Close levels.
"""

from __future__ import annotations

import datetime as dt
import json
import os

import pandas as pd
import yfinance as yf

from app.logger import get_logger

log = get_logger(__name__)

STATE_PATH = "data/level_alert_state.json"

TOUCH_TOLERANCE = {
    "NQ": 0.0008,
    "DXY": 0.0008,
    "GC": 0.0008,
}


def _load_state():
    if not os.path.exists(STATE_PATH):
        return {"date": "", "triggered": {}}

    try:
        with open(STATE_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {"date": "", "triggered": {}}


def _save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)

    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


def _reset_state_if_new_day(state):
    today = dt.datetime.utcnow().date().isoformat()

    if state.get("date") != today:
        return {
            "date": today,
            "triggered": {},
        }

    return state


def _compute_levels(df):
    levels = {}

    if df.empty or len(df) < 3:
        return levels

    prev = df.iloc[-2]

    levels["Prior Day High"] = float(prev.High)
    levels["Prior Day Low"] = float(prev.Low)
    levels["Prior Day Close"] = float(prev.Close)

    weekly = df.resample("W-FRI").agg(
        {
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
        }
    )

    if len(weekly) >= 2:
        prev = weekly.iloc[-2]

        levels["Prior Week High"] = float(prev.High)
        levels["Prior Week Low"] = float(prev.Low)
        levels["Prior Week Close"] = float(prev.Close)

    monthly = df.resample("ME").agg(
        {
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
        }
    )

    if len(monthly) >= 2:
        prev = monthly.iloc[-2]

        levels["Prior Month High"] = float(prev.High)
        levels["Prior Month Low"] = float(prev.Low)
        levels["Prior Month Close"] = float(prev.Close)

    return levels


def fetch_levels_for_instrument(ticker, fallback=None):

    for symbol in [ticker, fallback]:

        if not symbol:
            continue

        try:

            tk = yf.Ticker(symbol)

            daily = tk.history(period="90d", interval="1d")

            intraday = tk.history(period="2d", interval="15m")

            if daily.empty:
                continue

            if not intraday.empty:
                spot = float(intraday["Close"].iloc[-1])
            else:
                spot = float(daily["Close"].iloc[-1])

            return {
                "ok": True,
                "ticker_used": symbol,
                "spot": spot,
                "levels": _compute_levels(daily),
            }

        except Exception as e:
            log.warning(f"{symbol}: {e}")

    return {
        "ok": False,
        "reason": "No valid ticker",
    }


def check_all_levels(cfg):

    state = _reset_state_if_new_day(_load_state())

    events = []

    instruments = cfg.get(
        "level_watch_instruments",
        cfg["instruments"],
    )

    for key, meta in instruments.items():

        result = fetch_levels_for_instrument(
            meta["yf_ticker"],
            meta.get("fallback_ticker"),
        )

        if not result["ok"]:
            continue

        spot = result["spot"]

        tolerance = TOUCH_TOLERANCE.get(key, 0.001)

        already = state["triggered"].setdefault(key, [])

        for name, level in result["levels"].items():

            if level == 0:
                continue

            distance = abs(spot - level) / level

            if distance <= tolerance and name not in already:

                events.append(
                    {
                        "instrument": key,
                        "level_name": name,
                        "level_value": level,
                        "spot": spot,
                    }
                )

                already.append(name)

    _save_state(state)

    return events


def format_alert_message(events):

    lines = ["🔔 Level Alert"]

    for e in events:

        lines.append(
            f"{e['instrument']}: "
            f"{e['level_name']} "
            f"({e['level_value']:.2f}) "
            f"Spot: {e['spot']:.2f}"
        )

    return "\n".join(lines)
