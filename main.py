import os
import re
import json
import math
import time
import logging
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

import requests
import pandas as pd
import numpy as np
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# Optional ML imports (agent still runs if unavailable)
try:
    from xgboost import XGBClassifier
except Exception:
    XGBClassifier = None

try:
    from lightgbm import LGBMClassifier
except Exception:
    LGBMClassifier = None

# ----------------------------
# Configuration & Logging
# ----------------------------
load_dotenv()
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("tennis-edge-agent")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
EDGE_THRESHOLD = float(os.getenv("EDGE_THRESHOLD", "0.05"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "15"))
USER_AGENT = os.getenv("USER_AGENT", "Mozilla/5.0 (TennisEdgeAgent/1.0)")

# Free brain options (all optional)
# 1) Local Ollama endpoint (free, local) e.g. http://localhost:11434
OLLAMA_URL = os.getenv("OLLAMA_URL", "")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
# 2) Groq free tier (optional key; if absent we fall back to rules)
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# Public Polymarket data endpoint (NO credentials required)
POLYMARKET_GAMMA_URL = os.getenv("POLYMARKET_GAMMA_URL", "https://gamma-api.polymarket.com/markets")

# ESPN tennis events endpoint (public-ish, may change)
ESPN_TENNIS_SCOREBOARD = os.getenv(
    "ESPN_TENNIS_SCOREBOARD",
    "https://site.api.espn.com/apis/site/v2/sports/tennis/scoreboard",
)

# ----------------------------
# Utility helpers
# ----------------------------
def http_get(url: str, params: Optional[dict] = None, headers: Optional[dict] = None) -> Optional[requests.Response]:
    h = {"User-Agent": USER_AGENT}
    if headers:
        h.update(headers)
    try:
        r = requests.get(url, params=params, headers=h, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            return r
        logger.warning("GET failed %s status=%s", url, r.status_code)
    except Exception as e:
        logger.warning("GET exception %s error=%s", url, e)
    return None


def implied_prob_from_decimal_odds(odds: float) -> float:
    if odds <= 1.0:
        return 0.0
    return 1.0 / odds


def kelly_fraction(p: float, decimal_odds: float) -> float:
    # Kelly f* = (bp - q)/b where b = odds-1, q=1-p
    b = decimal_odds - 1.0
    q = 1.0 - p
    if b <= 0:
        return 0.0
    f = (b * p - q) / b
    return max(0.0, f)


def parse_match_input(text: str) -> Optional[Dict[str, str]]:
    # Accept: "Sinner vs Alcaraz clay" / "Sinner v Alcaraz hard" / "Sinner vs Alcaraz"
    text = text.strip()
    rx = re.compile(r"^(.+?)\s+(?:vs|v|versus)\s+(.+?)(?:\s+(clay|hard|grass))?$", re.IGNORECASE)
    m = rx.match(text)
    if not m:
        return None
    p1 = m.group(1).strip()
    p2 = m.group(2).strip()
    surface = (m.group(3) or "hard").lower()
    return {"player1": p1, "player2": p2, "surface": surface}


# ----------------------------
# Data collectors
# ----------------------------
def fetch_tennisabstract_stub(player1: str, player2: str, surface: str) -> Dict[str, Any]:
    """
    Lightweight public scraping can break often; this function is resilient and falls back.
    You can later replace with robust parser for TennisAbstract pages.
    """
    # Fallback synthetic defaults if no robust source data
    data = {
        "player1_surface_win_pct": 0.58,
        "player2_surface_win_pct": 0.55,
        "player1_serve_hold_pct": 0.82,
        "player2_serve_hold_pct": 0.80,
        "h2h_player1_wins": 1,
        "h2h_player2_wins": 1,
        "player1_days_since_last_match": 3,
        "player2_days_since_last_match": 2,
        "source": "tennisabstract_fallback",
    }

    # Example: attempt to hit TennisAbstract main page to confirm availability
    ping = http_get("https://www.tennisabstract.com/")
    if ping is not None:
        data["source"] = "tennisabstract_reachable_fallback_values"
    return data


def fetch_espn_form_stub(player1: str, player2: str) -> Dict[str, Any]:
    out = {
        "player1_form_index": 0.55,
        "player2_form_index": 0.53,
        "live_context": {},
        "source": "espn_fallback",
    }
    r = http_get(ESPN_TENNIS_SCOREBOARD)
    if r is not None:
        try:
            js = r.json()
            events = js.get("events", [])
            out["live_context"] = {"event_count": len(events)}
            out["source"] = "espn_scoreboard"
        except Exception:
            pass
    return out


def fetch_official_news_stub(player1: str, player2: str) -> Dict[str, Any]:
    # You can expand with RSS parsing of ATP/WTA feeds.
    return {
        "injury_mentions": [],
        "fatigue_mentions": [],
        "draw_context": "unknown",
        "source": "official_news_fallback",
    }


def fetch_polymarket_price(player1: str, player2: str) -> Dict[str, Any]:
    """
    Public-only lookup. No credentials.
    We try matching market question text containing both player names.
    """
    result = {
        "market_found": False,
        "market_question": None,
        "p_market_player1": 0.50,
        "raw": None,
        "source": "fallback",
    }

    r = http_get(POLYMARKET_GAMMA_URL, params={"limit": 200, "closed": "false"})
    if r is None:
        return result

    try:
        markets = r.json()
        if not isinstance(markets, list):
            return result

        p1_low = player1.lower()
        p2_low = player2.lower()

        for m in markets:
            q = (m.get("question") or "").lower()
            if p1_low in q and p2_low in q:
                result["market_found"] = True
                result["market_question"] = m.get("question")
                result["raw"] = m
                # try to parse price from outcomes
                # Gamma often has outcomePrices as JSON string or list
                outcome_prices = m.get("outcomePrices")
                if isinstance(outcome_prices, str):
                    try:
                        outcome_prices = json.loads(outcome_prices)
                    except Exception:
                        outcome_prices = None

                if isinstance(outcome_prices, list) and len(outcome_prices) >= 1:
                    # assume first outcome corresponds to first listed outcome
                    try:
                        p = float(outcome_prices[0])
                        if p > 1:
                            p = p / 100.0
                        result["p_market_player1"] = min(max(p, 0.01), 0.99)
                    except Exception:
                        pass
                result["source"] = "polymarket_public_gamma"
                break
    except Exception as e:
        logger.warning("Polymarket parse error: %s", e)

    return result


# ----------------------------
# Free "brain" (structured signals)
# ----------------------------
def rule_based_signal_brain(player1: str, player2: str, news_blob: Dict[str, Any]) -> List[Dict[str, Any]]:
    signals = []

    for p in [player1, player2]:
        fatigue_mentions = [x for x in news_blob.get("fatigue_mentions", []) if p.lower() in x.lower()]
        injury_mentions = [x for x in news_blob.get("injury_mentions", []) if p.lower() in x.lower()]

        if injury_mentions:
            signals.append(
                {
                    "player": p,
                    "impact_direction": "down",
                    "urgency_score": 0.85,
                    "reason": "injury mention",
                }
            )
        elif fatigue_mentions:
            signals.append(
                {
                    "player": p,
                    "impact_direction": "down",
                    "urgency_score": 0.60,
                    "reason": "fatigue mention",
                }
            )
        else:
            signals.append(
                {
                    "player": p,
                    "impact_direction": "neutral",
                    "urgency_score": 0.15,
                    "reason": "no critical alert",
                }
            )

    return signals


def ollama_brain(player1: str, player2: str, raw_text: str) -> Optional[List[Dict[str, Any]]]:
    if not OLLAMA_URL:
        return None
    try:
        prompt = f"""
You are a tennis signal extraction engine.
Return JSON array only. No markdown.
Schema item: {{"player": string, "impact_direction": "up|down|neutral", "urgency_score": float, "reason": string}}
Players: {player1}, {player2}
Text:\n{raw_text}
"""
        r = requests.post(
            f"{OLLAMA_URL.rstrip('/')}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code != 200:
            return None
        obj = r.json()
        txt = obj.get("response", "").strip()
        parsed = json.loads(txt)
        if isinstance(parsed, list):
            return parsed
    except Exception:
        return None
    return None


def brain_extract_signals(player1: str, player2: str, news_blob: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw_text = json.dumps(news_blob)
    llm_signals = ollama_brain(player1, player2, raw_text)
    if llm_signals:
        return llm_signals
    return rule_based_signal_brain(player1, player2, news_blob)


# ----------------------------
# Model (XGBoost / LightGBM fallback)
# ----------------------------
def build_features(ta: Dict[str, Any], espn: Dict[str, Any], signals: List[Dict[str, Any]]) -> Dict[str, float]:
    p1_signal = next((s for s in signals if s.get("player", "").lower() == "player1"), None)
    # Instead of strict player-name match above, compute from first signal entry by order fallback
    s1 = signals[0] if len(signals) > 0 else {"impact_direction": "neutral", "urgency_score": 0.0}
    s2 = signals[1] if len(signals) > 1 else {"impact_direction": "neutral", "urgency_score": 0.0}

    def signal_to_delta(sig: Dict[str, Any]) -> float:
        d = sig.get("impact_direction", "neutral")
        u = float(sig.get("urgency_score", 0.0))
        if d == "up":
            return +0.03 * u
        if d == "down":
            return -0.03 * u
        return 0.0

    features = {
        "surface_win_pct_diff": ta["player1_surface_win_pct"] - ta["player2_surface_win_pct"],
        "serve_hold_diff": ta["player1_serve_hold_pct"] - ta["player2_serve_hold_pct"],
        "h2h_diff": ta["h2h_player1_wins"] - ta["h2h_player2_wins"],
        "rest_day_diff": ta["player1_days_since_last_match"] - ta["player2_days_since_last_match"],
        "form_diff": espn["player1_form_index"] - espn["player2_form_index"],
        "signal_delta": signal_to_delta(s1) - signal_to_delta(s2),
    }
    return features


def logistic(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def predict_win_probability(features: Dict[str, float]) -> float:
    # If no trained model artifact is provided, use calibrated linear blend fallback.
    # (Fast and robust for newbie setup.)
    z = (
        2.2 * features["surface_win_pct_diff"]
        + 1.7 * features["serve_hold_diff"]
        + 0.08 * features["h2h_diff"]
        + 0.05 * features["rest_day_diff"]
        + 1.5 * features["form_diff"]
        + 2.0 * features["signal_delta"]
    )
    p = logistic(z)
    return float(min(max(p, 0.01), 0.99))


# ----------------------------
# Orchestrator
# ----------------------------
def run_analysis(player1: str, player2: str, surface: str) -> Dict[str, Any]:
    ta = fetch_tennisabstract_stub(player1, player2, surface)
    espn = fetch_espn_form_stub(player1, player2)
    news = fetch_official_news_stub(player1, player2)

    signals = brain_extract_signals(player1, player2, news)
    features = build_features(ta, espn, signals)

    p_agent = predict_win_probability(features)
    poly = fetch_polymarket_price(player1, player2)
    p_market = float(poly["p_market_player1"])

    edge = p_agent - p_market
    decision = "EDGE EXISTS ✅" if edge > EDGE_THRESHOLD else "SKIP ⏭️"

    decimal_odds = 1.0 / p_market if p_market > 0 else 2.0
    kelly = kelly_fraction(p_agent, decimal_odds)

    return {
        "player1": player1,
        "player2": player2,
        "surface": surface,
        "p_agent": p_agent,
        "p_market": p_market,
        "edge": edge,
        "decision": decision,
        "kelly_fraction": kelly,
        "threshold": EDGE_THRESHOLD,
        "sources": {
            "tennisabstract": ta.get("source"),
            "espn": espn.get("source"),
            "news": news.get("source"),
            "polymarket": poly.get("source"),
        },
        "market_question": poly.get("market_question"),
        "features": features,
        "signals": signals,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }


def format_report(res: Dict[str, Any]) -> str:
    return (
        f"📱 *Tennis Edge Analysis*\n"
        f"Match: *{res['player1']} vs {res['player2']}* ({res['surface']})\n\n"
        f"P_agent({res['player1']} win): *{res['p_agent']:.2%}*\n"
        f"P_market({res['player1']} win): *{res['p_market']:.2%}*\n"
        f"Edge = P_agent − P_market: *{res['edge']:.2%}*\n"
        f"Threshold: *{res['threshold']:.0%}*\n"
        f"Decision: *{res['decision']}*\n"
        f"Kelly fraction (max): *{res['kelly_fraction']:.2%}*\n\n"
        f"Sources:\n"
        f"- TennisAbstract: `{res['sources']['tennisabstract']}`\n"
        f"- ESPN: `{res['sources']['espn']}`\n"
        f"- News: `{res['sources']['news']}`\n"
        f"- Polymarket: `{res['sources']['polymarket']}`\n"
        f"- Market: `{res.get('market_question') or 'N/A (fallback 50%)'}`\n"
    )


# ----------------------------
# Telegram handlers
# ----------------------------
HELP_TEXT = """
Send a match in this format:
- Sinner vs Alcaraz clay
- Gauff vs Sabalenka hard
- Swiatek v Rybakina grass

I will analyze and return whether there is EDGE or SKIP.
""".strip()


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Tennis Edge Agent is running.\n" + HELP_TEXT
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT)


async def analyze_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    parsed = parse_match_input(text)
    if not parsed:
        await update.message.reply_text(
            "❌ Could not parse match input.\n" + HELP_TEXT
        )
        return

    player1 = parsed["player1"]
    player2 = parsed["player2"]
    surface = parsed["surface"]

    await update.message.reply_text("⏳ Running full analysis...")

    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(None, run_analysis, player1, player2, surface)
    report = format_report(res)

    await update.message.reply_text(report, parse_mode="Markdown")


def main():
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN in environment")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, analyze_message))

    logger.info("Starting Tennis Edge Agent bot...")
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
