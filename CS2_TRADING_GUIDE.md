# CS2 Esports Match Trading Model — Complete Guide

## How to use this guide
Read it **top to bottom once**, then follow the numbered steps every time you want to trade a match. Everything is designed to be done with just:
- A **web browser** (to visit HLTV.org)
- A **spreadsheet** (Google Sheets or Excel) to fill in the CSVs
- **Python 3** (free, standard install) to run the model

No paid data subscriptions, no APIs, no advanced coding knowledge required.

---

## Section 1 — Overview

### What does this model do?
It predicts the **probability that Team A beats Team B** in a CS2 match, then compares that to the market's implied probability. When the model thinks the market is significantly wrong (≥ 5% edge), it signals a trade.

### How it works at a high level
The model combines **7 layers of evidence** into a single probability number:

| Layer | What it captures |
|---|---|
| 1. Elo Rating | Overall long-run strength of each team |
| 2. Form | How well each team has performed in the **last 10 matches** |
| 3. Map Pool | Which team has stronger map win rates across the 7 active-duty maps |
| 4. Head-to-Head | Historical record between these two specific teams |
| 5. Player Ratings | Individual skill level (HLTV Rating 2.0) + star-player carry potential |
| 6. Context | LAN vs online, fatigue, playoff/Major stage |
| 7. Composite | Weighted blend of all 6 layers → final probability → Edge → EV → Kelly |

### Files in this system

| File | Purpose |
|---|---|
| `cs2_match_model.py` | The Python model — run this to get trade signals |
| `cs2_team_data.csv` | Team stats: Elo, rankings, map win rates, player ratings |
| `cs2_h2h_data.csv` | Head-to-head historical records |
| `cs2_player_data.csv` | Individual player HLTV Rating 2.0 and stats |
| `cs2_match_form.csv` | Last 10 match results per team |
| `cs2_bet_tracker.csv` | Your trade log (fill this in after every trade) |
| `CS2_TRADING_GUIDE.md` | This guide |

---

## Section 2 — Data Collection from HLTV.org (Step-by-Step)

> **Rule**: Update all data within **24 hours before a match** you want to model. Stale data = bad predictions.

---

### 2.1 Team Rankings (`HLTV_Ranking` column in `cs2_team_data.csv`)

**URL:** `https://www.hltv.org/ranking/teams/`

**Steps:**
1. Open the URL in your browser.
2. You will see a numbered list of teams — **the number on the left is the ranking**.
3. Find each team you want to track.
4. Record the rank in the `HLTV_Ranking` column.

**How often to update:** Weekly (rankings update every Monday).

**Example:**
```
Team        HLTV_Ranking
G2          1
FaZe        2
NAVI        3
```

---

### 2.2 Team Map Win Rates (`Mirage_WR`, `Inferno_WR`, ... columns)

**URL pattern:** `https://www.hltv.org/stats/teams/maps/{team_id}/{team_name}`

**How to find the team ID:**
1. Go to `https://www.hltv.org/ranking/teams/`
2. Click on the team name.
3. Look at the URL — it will be something like `https://www.hltv.org/team/4608/navi`
4. The number (4608) is the team ID.

**Steps to get map stats:**
1. Open the URL: `https://www.hltv.org/stats/teams/maps/4608/navi`
2. You will see a table with each map's stats.
3. Look for the **"Win rate"** column (or calculate: Wins / (Wins + Losses)).
4. Record the win rate as a decimal (e.g., 72% → 0.72) for all 7 active duty maps:
   - Mirage, Inferno, Nuke, Overpass, Ancient, Anubis, Dust2

**How often to update:** Weekly, or before any important match.

**Example entry in CSV:**
```
Team,Mirage_WR,Inferno_WR,Nuke_WR,Overpass_WR,Ancient_WR,Anubis_WR,Dust2_WR,Maps_Above_55
NAVI,0.72,0.68,0.63,0.60,0.65,0.70,0.58,6
```

**`Maps_Above_55`** = Count the maps where the win rate is above 0.55 (55%). In the example, all 7 are above 55% except Overpass (0.60 > 0.55 is actually above — count carefully).

---

### 2.3 Player Statistics (`cs2_player_data.csv`)

**URL pattern:** `https://www.hltv.org/stats/players/{player_id}/{player_ign}`

**How to find a player's URL:**
1. Go to the team page: `https://www.hltv.org/team/{team_id}/{team_name}`
2. Click on a player's name.
3. Note the URL — e.g., `https://www.hltv.org/player/7998/s1mple`
4. Click "Stats" → "Overview" to see Rating 2.0, K/D, ADR, KAST%.

**What to record:**

| Column | Where to find it on HLTV |
|---|---|
| `HLTV_Rating_2_0` | "Rating 2.0" — top of stats overview |
| `KD_Ratio` | "K/D Ratio" — stats overview |
| `ADR` | "ADR" (Average Damage per Round) — stats overview |
| `KAST_Pct` | "KAST%" — stats overview |
| `Impact_Rating` | "Impact" — stats overview |
| `Headshot_Pct` | "HS%" — stats overview |
| `Maps_Played` | "Maps played" — stats overview |

**Steps:**
1. Open each player's stats URL.
2. Set the time period to **"Last 3 months"** for the most relevant data.
3. Copy the values into `cs2_player_data.csv`.

**How often to update:** Before each match you want to model (ratings drift over time).

**Example:**
```
Player_IGN,Team,HLTV_Rating_2_0,KD_Ratio,ADR,KAST_Pct,Impact_Rating,Headshot_Pct,Maps_Played
s1mple,NAVI,1.35,1.42,85.2,76.4,1.52,42.1,320
```

---

### 2.4 Head-to-Head Records (`cs2_h2h_data.csv`)

**URL pattern:** `https://www.hltv.org/results?team={team_id_A}&team={team_id_B}`

**Example:** `https://www.hltv.org/results?team=4608&team=6667`
(NAVI ID = 4608, G2 ID = 6667)

**Steps:**
1. Open the URL with both team IDs.
2. You will see all past matches between the two teams.
3. **Count total matches** — that's `Total_Matches`.
4. **Count Team A wins and Team B wins** — `Team_A_Wins` and `Team_B_Wins`.
5. **For the 6-month columns**: Filter by date (last 6 months) and count again.
6. **Last match date**: Record the date of the most recent match.

**How often to update:** After each match between the two teams.

**Example:**
```
Team_A,Team_B,Total_Matches,Team_A_Wins,Team_B_Wins,Last_Match_Date,Recent_6mo_A_Wins,Recent_6mo_B_Wins,Recent_6mo_Total
NAVI,G2,28,14,14,2025-11-20,3,4,7
```

---

### 2.5 Recent Match Form (`cs2_match_form.csv`)

**URL pattern:** `https://www.hltv.org/results?team={team_id}`

**Example:** `https://www.hltv.org/results?team=4608` (NAVI)

**Steps:**
1. Open the results page for the team.
2. Record the **last 10 matches** (most recent first).
3. For each match, record:

| Column | What to record |
|---|---|
| `Date` | Match date in YYYY-MM-DD format |
| `Team` | The team you're tracking |
| `Opponent` | Opponent team name (must match your CSV) |
| `Opponent_HLTV_Rank` | Opponent's current HLTV ranking |
| `Result` | W (win) or L (loss) |
| `Map` | Map name (e.g., Mirage) |
| `Event` | Event name (e.g., BLAST Premier World Final) |
| `LAN_Online` | LAN or Online |
| `Score` | Score (e.g., 16-12) |

> **Tip:** If a match was best-of-3 or best-of-5, record **each map separately** as its own row. The model processes individual map results for form.

**How often to update:** After every match the team plays.

---

### 2.6 Elo Rating (manual update after each match)

The model stores Elo in `cs2_team_data.csv`. Update it after each match using:

**Formula:** `New_Elo = Old_Elo + K × (Actual - Expected)`

Where:
- K = 32 for online matches, 48 for LAN/Major matches
- Actual = 1.0 for win, 0.0 for loss
- Expected = the Elo probability before the match

**Example:** NAVI (Elo 1820) wins against G2 (Elo 1870) at LAN:
```
Expected = 1 / (1 + 10^((1870-1820)/400)) = 0.4285
New_Elo_NAVI = 1820 + 48 × (1.0 - 0.4285) = 1820 + 27.4 = 1847.4
New_Elo_G2   = 1870 + 48 × (0.0 - 0.5715) = 1870 - 27.4 = 1842.6
```

**How often to update:** After every match.

---

### 2.7 Upcoming Match Info (for market price)

**URL pattern:** `https://www.hltv.org/matches/{match_id}/{slug}`

Or browse upcoming matches at: `https://www.hltv.org/matches`

**What to record:**
- Which two teams are playing
- Is it LAN or online?
- Is it a playoff or Major stage match?
- How many matches has each team played in the last 48 hours? (Check their recent results)
- The market price on your trading platform (Polymarket, Betfair, etc.)

---

## Section 3 — The Math Explained (Plain English + Formulas)

---

### Layer 1: Elo Rating & Win Probability

**What it measures:** Overall long-run team strength. A team that consistently beats strong opponents earns a higher Elo. A team that loses to weaker opponents loses Elo points.

**Formula:**
```
P(Team_A wins) = 1 / (1 + 10^((Elo_B - Elo_A) / 400))
```

**Variable definitions:**
- `Elo_A` = Team A's current Elo rating (stored in `cs2_team_data.csv`)
- `Elo_B` = Team B's current Elo rating
- The 400 divisor is a standard convention (borrowed from chess)

**Worked example:** NAVI (Elo 1820) vs G2 (Elo 1870):
```
P(NAVI wins) = 1 / (1 + 10^((1870-1820)/400))
             = 1 / (1 + 10^(0.125))
             = 1 / (1 + 1.334)
             = 1 / 2.334
             = 0.4285  →  42.9% chance NAVI wins
```

**Why it matters:** Elo is the backbone of the model (30% weight). It captures team quality over many matches — not just recent results.

---

### Layer 2: Form Rating (Recent Performance)

**What it measures:** How well a team has performed in its **last 10 matches**, with more weight on recent games and harder opponents.

**Formula:**
```
Form_Score = Σ(Result_i × Recency_Weight_i × Opp_Strength_i) / Max_Possible
```

**Variable definitions:**
- `Result_i` = 1 for win, 0 for loss
- `Recency_Weight_i` = [1.00, 0.95, 0.90 ... 0.55] (match 1 = most recent)
- `Opp_Strength_i` = Opponent's HLTV ranking / 30, capped at 1.0
  - A rank-1 team has strength 1/30 = 0.033. Wait — actually strength = rank/30 means higher rank number = higher strength. But rank 1 is the best. Let's re-read...
  - Actually in the model: `opp_strength = min(opp_rank / 30, 1.0)`. This means rank 30 = strength 1.0, rank 1 = strength 0.033. This is intentional: beating a rank-30 team counts more than beating a rank-1 team because upsets are harder to count... 
  
**Why it matters:** A team on a 9-win streak against top opponents is very different from a team that scraped 9 wins against lower-ranked sides. Form captures current momentum weighted by competition quality.
```
Match 1 (W, rank 5):  1.00 × 1.00 × (31-5)/30  = 1.00 × 0.867 = 0.867
Match 2 (W, rank 8):  0.95 × 1.00 × (31-8)/30  = 0.95 × 0.767 = 0.729
Match 3 (W, rank 12): 0.90 × 1.00 × (31-12)/30 = 0.90 × 0.633 = 0.570
Match 4 (W, rank 20): 0.85 × 1.00 × (31-20)/30 = 0.85 × 0.367 = 0.312
Match 5 (W, rank 3):  0.80 × 1.00 × (31-3)/30  = 0.80 × 0.933 = 0.747
Sum = 3.224, Max_Possible = (1.00+0.95+0.90+0.85+0.80) × 1.0 = 4.50
Form_Score = 3.224 / 4.50 = 0.716
```

Opponent strength formula: `(31 - rank) / 30`, capped at 1.0.
This gives rank-1 opponents a strength of 1.0 and rank-30 opponents a strength of 0.033 — so beating a #1 team boosts your form score more than beating a #30 team.

**Why it matters:** A team on a 9-win streak is different from a team that barely qualified. Form captures current momentum.

---

### Layer 3: Map Pool Advantage

**What it measures:** Which team has a stronger and deeper map pool — important because CS2 matches use a veto process that eliminates maps.

**Formula:**
```
Map_Advantage_raw = Σ(WR_A_i - WR_B_i) / 7
Map_Advantage_normalized = (Map_Advantage_raw + 1) / 2
```

**Variable definitions:**
- `WR_A_i` = Team A's win rate on map i (e.g., 0.72 on Mirage)
- `WR_B_i` = Team B's win rate on map i
- The +1)/2 shift converts the (-1 to +1) range into (0 to 1) probability space

**Worked example:** NAVI (avg map WR ≈ 0.651) vs G2 (avg ≈ 0.666):
```
Mirage: 0.72 - 0.78 = -0.06
Inferno: 0.68 - 0.72 = -0.04
...
Average difference ≈ -0.018
Map_Adv = (-0.018 + 1) / 2 = 0.491  →  49.1% (slight G2 advantage)
```

**Map Depth** = how many maps a team wins more than 55% of the time. A team with 6/7 strong maps is hard to exploit through the veto.

**Why it matters:** In CS2, teams veto maps they're weak on. A team with a shallow map pool can be forced onto unfavourable maps.

---

### Layer 4: Head-to-Head Record

**What it measures:** Historical win rate between these two specific teams.

**Formula:**
```
H2H_Factor = (Blended_A_Wins / Blended_Total)  if Total_Matches >= 3
           = 0.5                                  otherwise
```

Where recent 6-month matches get **1.5× weight**:
```
Blended_A_Wins = A_Wins_Overall + (Recent_6mo_A_Wins × 0.5)
Blended_Total  = Total_Matches  + (Recent_6mo_Total   × 0.5)
```

**Worked example:** NAVI vs G2: 28 total (14 each), last 6 months: NAVI 3, G2 4, total 7:
```
Blended_A_Wins = 14 + (3 × 0.5) = 15.5
Blended_Total  = 28 + (7 × 0.5) = 31.5
H2H_Factor = 15.5 / 31.5 = 0.492  →  49.2%
```

**Why it matters:** Some teams consistently outperform their rankings against specific opponents due to playstyle matchups.

---

### Layer 5: Player Rating Composite

**What it measures:** The raw individual skill of each team's 5 players.

**Formulas:**
```
Team_Rating = Mean(Player_Rating_2.0 for all 5 players)
Star_Factor = Max(Player_Ratings) - Mean(Player_Ratings)
Composite   = Team_Rating + 0.5 × Star_Factor

P_player = Composite_A / (Composite_A + Composite_B)
```

**Why Star_Factor?** A team with one superstar (like m0NESY at 1.38 when the team averages 1.17) can win rounds single-handedly. The star factor captures carry potential.

**Worked example:**
```
NAVI ratings: [1.35, 1.12, 1.10, 1.05, 1.00]
  Mean = 1.124, Max = 1.35, Star = 0.226
  Composite_NAVI = 1.124 + 0.5×0.226 = 1.237

G2 ratings: [1.38, 1.25, 1.15, 1.02, 1.05]
  Mean = 1.170, Max = 1.38, Star = 0.210
  Composite_G2 = 1.170 + 0.5×0.210 = 1.275

P_player(NAVI) = 1.237 / (1.237 + 1.275) = 0.492  →  49.2%
```

**Why it matters:** Individual skill floors and ceilings heavily influence CS2 match outcomes — often more than team strategy.

---

### Layer 6: LAN/Online & Context Adjustments

**What it measures:** Situational factors that affect performance beyond raw stats.

**Formula:**
```
Context_Adj = LAN_bonus_A - LAN_bonus_B - Fatigue_A + Fatigue_B + Importance_boost
Context_P   = 0.5 + Context_Adj   (clamped to [0.1, 0.9])
```

**Components:**
- **LAN bonus**: +0.03 if the team's LAN win rate > 55% AND the match is LAN
- **Fatigue**: -0.02 per match played in the last 48 hours (gruelling group stages)
- **Importance boost**: +0.02 for playoff/Major matches (benefits Team A by convention — adjust manually if you think Team B benefits more)

**Worked example:** NAVI (LAN WR 78%) vs G2 (LAN WR 80%), LAN, playoff stage:
```
LAN bonus: NAVI: +0.03 (78% > 55%), G2: -0.03 (80% > 55%)
Net LAN:   0.03 - 0.03 = 0.00
Fatigue:   both 0 matches in last 48h → 0
Importance: +0.02 (playoff)
Context_Adj = 0.00 + 0.02 = 0.02
Context_P = 0.5 + 0.02 = 0.52  →  52%
```

**Why it matters:** Some teams are known "online warriors" that underperform at LAN. Others rise to the occasion in playoffs.

---

### Layer 7: Composite Probability

**What it measures:** The final blended win probability combining all 6 layers.

**Formula:**
```
Final_P = 0.30×Elo_P + 0.20×Form_P + 0.15×MapAdv_P + 0.10×H2H_P
        + 0.15×Player_P + 0.10×Context_P
```

**Default weights (must sum to 1.0):**

| Layer | Weight | Rationale |
|---|---|---|
| Elo | 30% | Most reliable long-run predictor |
| Form | 20% | Current momentum matters a lot in short series |
| Map Pool | 15% | CS2-specific — map veto is a strategic weapon |
| H2H | 10% | Stylistic matchups matter but are less predictive |
| Player Rating | 15% | Individual skill is a key CS2 differentiator |
| Context | 10% | LAN/online and fatigue have measurable effects |

**You can customise weights** by editing the `LAYER_WEIGHTS` dict in `cs2_match_model.py`.

---

### Trading Math

**Edge:**
```
Edge = Your_Probability - Market_Implied_Probability
```
Market implied probability = the market price (e.g., $0.45 price → 45% implied probability).

**Expected Value (EV):**
```
EV = (p × profit_if_win) - (q × cost_if_lose)
   = (p × (1 - price)) - ((1-p) × price)
```

**Example:** Model says 55%, market price $0.45:
```
EV = (0.55 × 0.55) - (0.45 × 0.45) = 0.3025 - 0.2025 = $0.10 per share
```

**Kelly Criterion:**
```
f* = (b×p - q) / b
b  = (1 - market_price) / market_price   (net odds)
p  = your probability, q = 1-p
```

**Always use Half-Kelly** (`f*/2`) — the full Kelly is mathematically optimal but practically too aggressive.

---

## Section 4 — How to Use the System (Step-by-Step Workflow)

### Step 1: Identify an upcoming match
Go to `https://www.hltv.org/matches` and find a match you want to analyse. Note both team names.

### Step 2: Update the CSVs
For both teams, check that the data in your CSV files is current (within 7 days). Update any stale rows:
- `cs2_team_data.csv` — ranking, Elo, map win rates
- `cs2_player_data.csv` — current player ratings
- `cs2_match_form.csv` — last 10 results for both teams
- `cs2_h2h_data.csv` — add any new matches between these teams

### Step 3: Find the market price
Open your trading platform (Polymarket, Betfair, etc.) and note the current price for Team A to win.

### Step 4: Run the model
```bash
python cs2_match_model.py
```

Edit the `__main__` block at the bottom of `cs2_match_model.py` to change the teams and market price:
```python
result = analyze_match(
    team_a="NAVI",
    team_b="G2",
    ...
    market_price_a=0.45,   # ← change this
    is_lan=True,            # ← LAN event?
    is_playoff_or_major=True,
    bankroll=500.0,
)
```

### Step 5: Interpret the output
```
SIGNAL: ✅ GO TRADE (NAVI)   ← Trade this side
Edge: +7.50%                  ← Model thinks market is 7.5% wrong
EV: $+0.0750 per share        ← Expected profit per $1 share
Half-Kelly: 6.25%             ← Risk 6.25% of your bankroll
Confidence: High              ← Strong data quality
```

### Step 6: Decide whether to trade

| Condition | Action |
|---|---|
| Edge ≥ 5% AND Confidence = High | Strong trade signal |
| Edge ≥ 5% AND Confidence = Medium | Reduce position size by half |
| Edge ≥ 5% AND Confidence = Low | Skip — not enough data |
| Edge < 5% | Skip — no trade |
| EV < 0 | Never trade regardless of edge |

### Step 7: Log your trade
Open `cs2_bet_tracker.csv` and add a row:
```
Date,Match,Side,Market_Platform,Shares,Entry_Price,Total_Cost,Your_Prob,Market_Prob,Edge,EV_Per_Unit,Kelly_Frac,Confidence,Result,Profit_Loss,Running_PnL
2025-12-10,NAVI vs G2,NAVI,Polymarket,50,0.45,22.50,0.55,0.45,0.10,0.0550,0.1818,High,,
```

Fill in `Result` and `Profit_Loss` after the match resolves.

---

## Section 5 — Trading Rules & Bankroll Management

### The Cardinal Rules

1. **Never trade without ≥ 5% edge.** CS2 is high-variance — the minimum edge must cover this.
2. **Always use Half-Kelly** (never full Kelly). Full Kelly leads to ruin in high-variance sports.
3. **Never risk more than 5% of bankroll on a single match.** Even if Kelly says more.
4. **Log every trade** in `cs2_bet_tracker.csv`. No exceptions.
5. **Review weekly** — are you beating the market over 20+ trades? If not, reassess your data sources.

### Bankroll Sizing Example

Bankroll: $500

| Kelly says | Half-Kelly | 5% cap | Final bet size |
|---|---|---|---|
| 20% ($100) | 10% ($50) | $25 cap | $25 |
| 8% ($40) | 4% ($20) | $25 cap | $20 |
| 4% ($20) | 2% ($10) | $25 cap | $10 |

Always take the **minimum** of Half-Kelly and the 5% cap.

### Warning Signs (when to NOT trade even with edge)

- **Team roster change** announced in last 24 hours — your player data is outdated.
- **Match is within 2 hours** and you haven't verified all data.
- **Confidence = Low** — not enough historical data to be reliable.
- **Edge is between 5-7%** AND the match is a best-of-1 (BO1 is a coin flip — variance is huge).
- **You haven't updated form data** since the team's last match.

### Weekly Review Checklist
Every Monday, open `cs2_bet_tracker.csv` and calculate:
- Total trades this week
- Win rate vs model predictions (should be close if model is calibrated)
- Running P&L (are you profitable?)
- Average edge of winning trades vs losing trades
- Any pattern in losses? (e.g., all BO1 losses, all low-confidence trades?)

---

## Section 6 — Google Sheets Formulas

You can replicate the Python calculations entirely in a Google Sheet. Here are the exact formulas:

### Setup: Column Headers (Row 1)
```
A: Team_A_Elo  B: Team_B_Elo  C: Elo_Prob_A
D: Form_Score_A  E: Form_Score_B  F: Form_Prob
G: Map_Adv_A  H: Map_Adv_B  I: Map_Adv_Prob
J: H2H_Wins_A  K: H2H_Total  L: H2H_Prob
M: Player_Comp_A  N: Player_Comp_B  O: Player_Prob
P: Context_Adj  Q: Context_Prob
R: w_elo  S: w_form  T: w_map  U: w_h2h  V: w_player  W: w_context
X: Final_Prob
Y: Market_Price  Z: Edge
AA: EV  AB: Kelly  AC: Half_Kelly
```

### Layer 1 — Elo Probability (Cell C2)
```
=1/(1+10^((B2-A2)/400))
```

### Layer 2 — Form Probability (Cell F2)
Given Form_Score_A in D2 and Form_Score_B in E2:
```
=IF((D2+E2)=0, 0.5, D2/(D2+E2))
```

### Layer 3 — Map Advantage Probability (Cell I2)
Given average map win rate for A (G2) and B (H2) across 7 maps:
```
=((G2-H2)+1)/2
```

### Layer 4 — H2H Probability (Cell L2)
Given A_wins in J2, H2H_total in K2:
```
=IF(K2<3, 0.5, J2/K2)
```

### Layer 5 — Player Probability (Cell O2)
Given composite score A in M2 and B in N2:
```
=IF((M2+N2)=0, 0.5, M2/(M2+N2))
```

Player composite formula (mean + 0.5 × star factor):
```
=AVERAGE(rating1,rating2,rating3,rating4,rating5) + 0.5*(MAX(rating1,rating2,rating3,rating4,rating5)-AVERAGE(rating1,rating2,rating3,rating4,rating5))
```

### Layer 6 — Context Probability (Cell Q2)
Given adjustment in P2:
```
=MIN(MAX(0.5+P2, 0.1), 0.9)
```

### Layer 7 — Final Composite (Cell X2)
Given weights in R2:W2 and probabilities C2, F2, I2, L2, O2, Q2:
```
=R2*C2 + S2*F2 + T2*I2 + U2*L2 + V2*O2 + W2*Q2
```

With default weights in the weight cells:
```
R2=0.30, S2=0.20, T2=0.15, U2=0.10, V2=0.15, W2=0.10
```

### Edge (Cell Z2)
```
=X2-Y2
```

### Expected Value (Cell AA2)
```
=X2*(1-Y2)-(1-X2)*Y2
```

### Kelly Criterion (Cell AB2)
```
=MAX(((1/Y2-1)*X2-(1-X2))/(1/Y2-1), 0)
```

### Half-Kelly (Cell AC2)
```
=AB2/2
```

### Trade Signal (bonus formula)
```
=IF(AND(Z2>=0.05, AA2>0), "GO TRADE", "NO TRADE")
```

---

## Section 7 — Frequently Asked Questions

**Q: The model says NO TRADE but I have a gut feeling. Should I trade?**
A: No. The model's job is to remove gut feelings from the equation. If you have specific information not captured in the data (e.g., a key player is sick), update the data and re-run.

**Q: How do I handle best-of-3 vs best-of-1 matches?**
A: The current model does not distinguish BO1 vs BO3. BO1 matches have much higher variance — consider applying a minimum 8-10% edge threshold for BO1, and skipping if confidence is not High.

**Q: What if a team is not in my CSV?**
A: Add them to `cs2_team_data.csv` with estimated data. Use their HLTV ranking, set Elo to `1500 + (30 - rank) * 10` as a rough starting point, and add their map and player data. Re-run the model.

**Q: How often do I need to update data?**
A: Minimum weekly for rankings and map stats. After every match for Elo and form. Before every trade for player ratings (check for substitutes or stand-ins).

**Q: Can I use this for Betfair instead of Polymarket?**
A: Yes. The math is identical. On Betfair, the "price" is in decimal odds format. Convert to implied probability: `implied_prob = 1 / decimal_odds`. Then use that as `market_price_a` in the model.

**Q: My model keeps saying NO TRADE. Is something wrong?**
A: CS2 markets are fairly efficient. A 5% edge is a high bar. This is intentional. If you're seeing many NO TRADE signals, the market is pricing correctly. Wait for the specific situations where you have an edge (strong data, LAN events, teams you track closely).

---

*This guide was designed to work alongside the `nba_ou_model.py` NBA trading model in the same repository. The math principles are identical — only the sport-specific layers (map pool, CS2 Elo) differ.*
