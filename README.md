# nba-poly — Sports & Esports Trading Models

A collection of data-driven trading models for sports prediction markets (Polymarket, Betfair). All models use only Python's standard library — no external dependencies required.

---

## 📁 Models

### 🏀 NBA Over/Under Model (`nba_ou_model.py`)

Predicts NBA game totals and identifies +EV trades on Polymarket.

**Data source:** [Basketball-Reference.com](https://www.basketball-reference.com/leagues/NBA_2026_ratings.html)

**Math used:**
- Expected game pace → adjusted offensive output → projected total
- Normal distribution to convert projected total to Over/Under probability
- Edge, EV, and Kelly Criterion for trade sizing

**Files:**
| File | Purpose |
|---|---|
| `nba_ou_model.py` | Main model |
| `team_data.csv` | NBA team stats (ORtg, DRtg, Pace) |
| `bet_tracker.csv` | NBA trade log |

**Quick start:**
```bash
python nba_ou_model.py
```

---

### 🎮 CS2 Match Winner Model (`cs2_match_model.py`)

Predicts CS2 esports match winners using a 7-layer mathematical model. All data is collected manually from **HLTV.org**.

**Data source:** [HLTV.org](https://www.hltv.org)

**Math used (7 layers):**

| Layer | Formula | Weight |
|---|---|---|
| 1. Elo | `P = 1 / (1 + 10^((Elo_B - Elo_A) / 400))` | 30% |
| 2. Form | Recency-weighted wins × opponent strength (last 10 matches) | 20% |
| 3. Map Pool | Average map win rate differential across 7 active-duty maps | 15% |
| 4. Head-to-Head | H2H win rate (recent 6 months weighted 1.5×) | 10% |
| 5. Player Rating | Mean HLTV Rating 2.0 + star-player carry factor | 15% |
| 6. Context | LAN bonus, fatigue penalty, playoff/Major boost | 10% |
| 7. Composite | Weighted blend → Edge → EV → Kelly Criterion | — |

**Files:**
| File | Purpose |
|---|---|
| `cs2_match_model.py` | Main model |
| `cs2_team_data.csv` | 20 CS2 teams: Elo, rankings, map win rates |
| `cs2_h2h_data.csv` | Head-to-head records |
| `cs2_player_data.csv` | Player HLTV Rating 2.0 and stats |
| `cs2_match_form.csv` | Recent match history (last 10 per team) |
| `cs2_bet_tracker.csv` | CS2 trade log |
| `CS2_TRADING_GUIDE.md` | **Complete step-by-step guide** with HLTV.org URLs |

**Quick start:**
```bash
python cs2_match_model.py
```

**📖 Read the full guide:** [CS2_TRADING_GUIDE.md](CS2_TRADING_GUIDE.md)

The guide covers exactly where to click on HLTV.org for every data point, how to fill each CSV, how to interpret the model output, Google Sheets formula equivalents, and bankroll management rules.

---

## ⚡ Trading Rules (both models)

- Minimum **5% edge** to trade (CS2) / **3% edge** (NBA)
- Always use **Half-Kelly** bet sizing
- Never risk more than **5% of bankroll** per trade
- Log every trade in the respective `*_bet_tracker.csv`
- Review weekly: are you beating the market over 20+ trades?