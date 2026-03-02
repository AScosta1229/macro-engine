# =====================================================
# INSTITUTIONAL MACRO ENGINE - FINAL VERSION
# =====================================================
import os
import asyncio
import datetime
import requests
import yfinance as yf

from openai import OpenAI
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# =====================================================
# ENVIRONMENT VARIABLES
# =====================================================
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
MARKETAUX_KEY = os.environ["MARKETAUX_KEY"]
CHANNEL_ID = "newsptmerbot"  # ou None se não usares canal

client = OpenAI(api_key=OPENAI_API_KEY)

# =====================================================
# SAFE SEND
# =====================================================

async def safe_send(bot, chat_id, text):
    MAX = 4000
    for i in range(0, len(text), MAX):
        await bot.send_message(chat_id=chat_id, text=text[i:i+MAX])


# =====================================================
# DATA ENGINE
# =====================================================

def get_change(symbol):
    try:
        d = yf.Ticker(symbol).history(period="2d", interval="1d")
        if len(d) < 2:
            return None, None
        prev = d["Close"].iloc[-2]
        last = d["Close"].iloc[-1]
        pct = ((last - prev) / prev) * 100
        return float(last), float(pct)
    except:
        return None, None


# =====================================================
# CROSS ASSET SNAPSHOT
# =====================================================

def cross_asset_snapshot():

    assets = {
        "S&P 500": "^GSPC",
        "Nasdaq": "^IXIC",
        "Russell 2000": "^RUT",
        "Emerging Markets": "EEM",
        "HYG": "HYG",
        "LQD": "LQD",
        "US 10Y": "^TNX",
        "US 2Y": "^IRX",
        "Dollar Index": "DX-Y.NYB",
        "VIX": "^VIX",
        "Gold": "GC=F",
        "Oil": "CL=F",
        "Bitcoin": "BTC-USD"
    }

    text = "📊 GLOBAL CROSS-ASSET SNAPSHOT\n"
    data = {}

    for name, symbol in assets.items():
        price, pct = get_change(symbol)

        if name == "Nasdaq" and price is None:
            price, pct = get_change("QQQ")

        if price is None:
            text += f"⚪ {name}: Data unavailable\n"
            continue

        emoji = "🟢" if pct >= 0 else "🔴"
        text += f"{emoji} {name}: {price:.2f} ({pct:+.2f}%)\n"
        data[name] = {"price": price, "pct": pct}

    return text, data


# =====================================================
# STRUCTURAL STATES
# =====================================================

def breadth_state(data):
    eq = ["S&P 500", "Nasdaq", "Russell 2000", "Emerging Markets"]
    positives = sum(1 for a in eq if a in data and data[a]["pct"] > 0)
    if positives == 4: return "Broad"
    if positives >= 2: return "Moderate"
    return "Narrow"


def credit_state(data):
    if "HYG" in data and "LQD" in data:
        return "Confirming" if data["HYG"]["pct"] > data["LQD"]["pct"] else "Diverging"
    return "Unavailable"


def yield_curve_state(data):
    if "US 10Y" in data and "US 2Y" in data:
        spread = data["US 10Y"]["price"] - data["US 2Y"]["price"]
        return spread, "Steep" if spread > 0 else "Inverted"
    return None, "Unavailable"


def volatility_state(data):
    vix = data.get("VIX", {}).get("price", None)
    if vix is None: return "Unknown"
    if vix < 18: return "Compressed"
    if vix < 25: return "Neutral"
    return "Elevated"


def dollar_state(data):
    pct = data.get("Dollar Index", {}).get("pct", 0)
    if pct > 0.4: return "Headwind"
    if pct < -0.4: return "Supportive"
    return "Neutral"


# =====================================================
# MARKET DIAGNOSTICS (NEW BLOCK)
# =====================================================

def market_diagnostics(data):

    large_small = "Confirming"
    if data.get("Russell 2000", {}).get("pct", 0) < data.get("S&P 500", {}).get("pct", 0):
        large_small = "Large Leading"

    credit_momentum = "Positive" if data.get("HYG", {}).get("pct", 0) > 0 else "Negative"

    commodity_signal = "Risk-Positive" if data.get("Oil", {}).get("pct", 0) > 0 else "Defensive"

    dollar_em = "Supportive" if (
        data.get("Emerging Markets", {}).get("pct", 0) > 0 and
        data.get("Dollar Index", {}).get("pct", 0) <= 0
    ) else "Neutral"

    return large_small, credit_momentum, commodity_signal, dollar_em


# =====================================================
# ALIGNMENT + STRESS
# =====================================================

def alignment_score(data):
    score = 0
    if data.get("S&P 500", {}).get("pct", 0) > 0: score += 1
    if data.get("HYG", {}).get("pct", 0) > 0: score += 1
    if data.get("VIX", {}).get("pct", 0) < 0: score += 1
    if data.get("Emerging Markets", {}).get("pct", 0) > 0: score += 1
    if data.get("Dollar Index", {}).get("pct", 0) <= 0: score += 1
    return score


def stress_state(data):
    flags = 0
    if data.get("VIX", {}).get("pct", 0) > 5: flags += 1
    if data.get("HYG", {}).get("pct", 0) < -1: flags += 1
    if data.get("Dollar Index", {}).get("pct", 0) > 0.8: flags += 1
    if flags >= 2: return "High"
    if flags == 1: return "Moderate"
    return "Low"


# =====================================================
# RISK SCORE (REFINED)
# =====================================================

def risk_score(data, alignment):

    base = 50
    base += (alignment - 2) * 7

    vix = data.get("VIX", {}).get("price", 20)
    if vix < 18: base += 6
    if vix > 25: base -= 12

    if data.get("HYG", {}).get("pct", 0) > data.get("LQD", {}).get("pct", 0):
        base += 5

    return max(0, min(100, round(base)))


# =====================================================
# CLEAN MACRO NEWS (STRICT FILTER)
# =====================================================

def get_macro_news():

    try:
        url = f"https://api.marketaux.com/v1/news/all?language=en&limit=30&api_token={MARKETAUX_KEY}"
        r = requests.get(url, timeout=10)
        data = r.json()

        macro_keywords = [
            "fed", "ecb", "bank of japan", "treasury",
            "inflation", "cpi", "rates", "yield",
            "recession", "economy", "payrolls",
            "opec", "geopolitics", "sanctions"
        ]

        headlines = []

        for a in data.get("data", []):
            title = a.get("title", "").lower()
            if any(k in title for k in macro_keywords):
                headlines.append(a.get("title"))
            if len(headlines) == 3:
                break

        if not headlines:
            return "\n📰 No systemic macro headlines detected.\n"

        text = "\n📰 MACRO HEADLINES\n\n"
        for h in headlines:
            text += f"• {h}\n"

        return text

    except:
        return "\n📰 News unavailable\n"


# =====================================================
# ULTRA-FRIO OVERLAY
# =====================================================

def ai_overlay(risk, breadth, credit, vol, dollar, curve, diagnostics):

    prompt = f"""
You are a macro portfolio manager.

Risk Score: {risk}
Breadth: {breadth}
Credit: {credit}
Volatility: {vol}
Dollar: {dollar}
Yield Curve: {curve}
Diagnostics: {diagnostics}

Write a strict institutional desk note (max 120 words).
No advice. No narrative. Analytical tone only.
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=250,
    )

    return response.choices[0].message.content


# =====================================================
# COMMAND
# =====================================================

async def brief(update: Update, context: ContextTypes.DEFAULT_TYPE):

    chat_id = update.effective_chat.id
    today = datetime.datetime.now().strftime("%d %b %Y")

    snapshot_text, data = cross_asset_snapshot()

    breadth = breadth_state(data)
    credit = credit_state(data)
    spread, curve = yield_curve_state(data)
    vol = volatility_state(data)
    dollar = dollar_state(data)

    large_small, credit_mom, commodity_sig, dollar_em = market_diagnostics(data)

    align = alignment_score(data)
    stress = stress_state(data)
    risk = risk_score(data, align)

    regime = "RISK-ON 🟢" if risk >= 65 else "RISK-OFF 🔴" if risk <= 35 else "TRANSITION 🟡"

    news = get_macro_news()
    diagnostics = f"{large_small}, {credit_mom}, {commodity_sig}, {dollar_em}"
    overlay = ai_overlay(risk, breadth, credit, vol, dollar, curve, diagnostics)

    diagnostics_block = (
        f"\n📈 MARKET DIAGNOSTICS\n"
        f"Large vs Small: {large_small}\n"
        f"Credit Momentum: {credit_mom}\n"
        f"Commodity Signal: {commodity_sig}\n"
        f"Dollar vs EM: {dollar_em}\n"
    )

    signal_matrix = (
        f"\n📌 SIGNAL MATRIX\n"
        f"Breadth: {breadth}\n"
        f"Credit: {credit}\n"
        f"Volatility: {vol}\n"
        f"Dollar: {dollar}\n"
        f"Curve: {curve}\n"
        f"Stress: {stress}\n"
    )

    block1 = (
        f"📊 MACRO ENGINE 6.0 | {today}\n\n"
        f"{snapshot_text}"
        f"{signal_matrix}"
        f"{diagnostics_block}\n"
        f"Risk Score: {risk}/100\n"
        f"Alignment: {align}/5\n"
        f"Regime: {regime}\n"
    )

    block2 = news
    block3 = "\n🧠 INSTITUTIONAL OVERLAY\n\n" + overlay

    await safe_send(context.bot, chat_id, block1)
    await safe_send(context.bot, chat_id, block2)
    await safe_send(context.bot, chat_id, block3)


# =====================================================
# START + MAIN
# =====================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 Macro Engine 6.0 Activated.\nUse /brief")


async def main():
    app = ApplicationBuilder().token(os.environ["TELEGRAM_TOKEN"]).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("brief", brief))

    PORT = int(os.environ.get("PORT", 8000))
    WEBHOOK_URL = os.environ["WEBHOOK_URL"]

    await app.bot.set_webhook(WEBHOOK_URL)

    print("🚀 MACRO ENGINE 6.0 LIVE (Webhook Mode)")

    await app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=WEBHOOK_URL,
    )

if __name__ == "__main__":
    asyncio.run(main())
