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

def _level_type(level_name: str) -> str:
    if level_name.endswith("High"):
        return "high"
    if level_name.endswith("Low"):
        return "low"
    return "close"


def analyze_full_watchlist(cfg: dict) -> list[dict]:
    """
    For every instrument in level_watch_instruments: current spot, a simple
    HTF bias (EMA8 vs EMA21 + last vs prior close, same rule as analysis.py),
    and Prior Day/Week/Month High/Low/Close levels each with a plain-number
    distance from spot and whether today's session has already swept
    (traded through) that level.
    """
    results = []
    for key, meta in cfg.get("level_watch_instruments", {}).items():
        out = {"key": key, "label": meta.get("label", key), "ok": False}
        for candidate in [meta["yf_ticker"], meta.get("fallback_ticker")]:
            if not candidate:
                continue
            try:
                tk = yf.Ticker(candidate)
                daily = tk.history(period="90d", interval="1d")
                intraday = tk.history(period="2d", interval="15m")
                if daily.empty or len(daily) < 3:
                    continue

                spot = float(intraday["Close"].iloc[-1]) if not intraday.empty else float(daily["Close"].iloc[-1])
                today_bar = daily.iloc[-1]
                today_high = float(today_bar["High"])
                today_low = float(today_bar["Low"])

                ema_fast = daily["Close"].ewm(span=8).mean().iloc[-1]
                ema_slow = daily["Close"].ewm(span=21).mean().iloc[-1]
                prior_close = float(daily.iloc[-2]["Close"])
                if ema_fast > ema_slow and spot >= prior_close:
                    bias = "bullish"
                elif ema_fast < ema_slow and spot <= prior_close:
                    bias = "bearish"
                else:
                    bias = "neutral"

                levels = _compute_levels(daily)
                level_rows = []
                for name, value in levels.items():
                    distance = spot - value
                    ltype = _level_type(name)
                    if ltype == "high":
                        swept = today_high >= value
                    elif ltype == "low":
                        swept = today_low <= value
                    else:
                        swept = today_low <= value <= today_high
                    level_rows.append({
                        "name": name, "value": value,
                        "distance": distance, "swept_today": swept,
                    })

                out.update({"ok": True, "ticker_used": candidate, "spot": spot,
                            "bias": bias, "levels": level_rows})
                break
            except Exception as e:
                log.warning(f"Full-watchlist analysis failed for {candidate}: {e}")
                continue
        results.append(out)
    return results


def fetch_headline(ticker: str) -> str:
    """
    Best-effort single recent headline via Yahoo Finance's free, unofficial
    per-ticker RSS feed. No key needed, but no SLA either - many tickers
    (FX pairs, some indices) simply have no feed, in which case this
    returns a clear fallback string rather than raising.
    """
    import requests
    import xml.etree.ElementTree as ET
    from urllib.parse import quote

    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={quote(ticker)}&region=US&lang=en-US"
    try:
        resp = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        item = root.find(".//item")
        if item is not None:
            title = item.find("title")
            if title is not None and title.text:
                return title.text.strip()
        return "No headline available"
    except Exception as e:
        log.warning(f"Headline fetch failed for {ticker}: {e}")
        return "No headline available (feed unavailable)"


def rank_top_setups(watchlist: list[dict], top_n: int = 2) -> list[dict]:
    """
    Simple, transparent ranking: among instruments with a clear (non-neutral)
    bias, score by how close spot sits to its nearest UNSWEPT level in the
    direction that confirms the bias (closer = higher-conviction setup).
    """
    scored = []
    for inst in watchlist:
        if not inst.get("ok") or inst["bias"] == "neutral":
            continue
        candidates = [l for l in inst["levels"] if not l["swept_today"]]
        if not candidates:
            continue
        closest = min(candidates, key=lambda l: abs(l["distance"]))
        scored.append({
            "key": inst["key"], "label": inst["label"], "bias": inst["bias"],
            "spot": inst["spot"], "target_level": closest["name"],
            "target_value": closest["value"], "distance": closest["distance"],
        })
    scored.sort(key=lambda s: abs(s["distance"]))
    return scored[:top_n]
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
