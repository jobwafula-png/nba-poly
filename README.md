# Tennis Edge Telegram Agent (Single File)

This setup creates a **single Python file agent** that:
- accepts Telegram messages like `Sinner vs Alcaraz clay`
- gathers multi-source signals (ATP/WTA/TennisAbstract/ESPN/news stubs)
- computes `P_agent`
- fetches **public** Polymarket price data (**no credentials**)
- calculates edge: `Edge = P_agent - P_market`
- replies with:
  - `EDGE EXISTS ✅` if edge > 5%
  - `SKIP ⏭️` otherwise

> Note: No private Polymarket keys are required.

---

## Files
- `main.py` → full agent logic in one file
- `.env.example` → environment template
- `requirements.txt` → dependencies

---

## 1) Install

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

pip install -r requirements.txt
```

## 2) Configure env

```bash
cp .env.example .env
```

Edit `.env` and set:
- `TELEGRAM_BOT_TOKEN=...`

Optional (free local brain):
- install [Ollama](https://ollama.com/)
- run `ollama run llama3.1:8b`
- set `OLLAMA_URL=http://localhost:11434`

If Ollama is not configured, the agent uses built-in **rule-based structured signal extraction**.

## 3) Run bot

```bash
python main.py
```

## 4) Telegram usage

Send examples:
- `Sinner vs Alcaraz clay`
- `Gauff vs Sabalenka hard`
- `Swiatek v Rybakina grass`

You will get a report with:
- model probability
- market probability
- edge
- decision
- Kelly fraction

---

## Notes for newbie setup

- This version is designed to be robust and beginner-friendly.
- Some external sports endpoints can change format or block scraping.
- The code includes fallback values so the bot still responds.
- You can progressively harden each data collector later.

---

## Important disclaimer

This tool is for educational/statistical analysis only, not financial advice.
