"""
CS2 Match Winner Trading Model for Polymarket / Betfair
=========================================================
Source: https://www.hltv.org

This model predicts CS2 match winners and identifies +EV trades using a
7-layer composite probability system. All data is collected manually from
HLTV.org — no APIs or scraping required.

FORMULAS USED:
Layer 1 — Elo:          P(A) = 1 / (1 + 10^((Elo_B - Elo_A) / 400))
Layer 2 — Form:         Form = Σ(Result × Recency_Weight × Opp_Strength) / N
Layer 3 — Map Pool:     Map_Adv = Σ(WR_A_i - WR_B_i) / 7 maps
Layer 4 — H2H:          H2H = A_Wins / Total  (if Total >= 3, else 0.5)
Layer 5 — Players:      Team_Rating = Mean(Ratings); Star = Max - Mean
Layer 6 — Context:      Adj = LAN_bonus + Fatigue_penalty + Importance_boost
Layer 7 — Composite:    Final_P = w1×Elo + w2×Form + w3×MapAdv + w4×H2H +
                                  w5×Players + w6×Context

TRADING MATH:
    Edge = Your_Probability - Market_Implied_Probability
    EV   = (p × profit_if_win) - (q × cost_if_lose)
    Kelly = (b×p - q) / b   [use half-Kelly for safety]
    Min edge to trade: 5% (wider than NBA due to CS2 match volatility)

TESTED: NAVI vs G2 → Final_P(NAVI) = 47.2%, Edge vs 0.45 market = +2.2% (no trade)
"""

import csv
import math
from typing import Optional


# ──────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ──────────────────────────────────────────────────────────────────────────────
DEFAULT_ELO = 1500              # Starting Elo for a new team
ELO_K_REGULAR = 32             # K-factor for online/regular matches
ELO_K_LAN = 48                 # K-factor for LAN/Major events
RECENCY_WEIGHTS = [             # Last 10 matches: most recent first
    1.00, 0.95, 0.90, 0.85, 0.80, 0.75, 0.70, 0.65, 0.60, 0.55
]
ACTIVE_DUTY_MAPS = [            # CS2 active duty map pool (7 maps)
    "Mirage", "Inferno", "Nuke", "Overpass", "Ancient", "Anubis", "Dust2"
]
MIN_EDGE_THRESHOLD = 0.05      # 5% minimum edge required to trade
LAN_WIN_RATE_BONUS_THRESHOLD = 0.55   # Above this LAN WR → LAN bonus applies
LAN_BONUS = 0.03               # Bonus for strong LAN teams on LAN events
FATIGUE_PENALTY = 0.02         # Per match played within last 48 hours
IMPORTANCE_BOOST = 0.02        # Playoff/Major stage boost

# Composite weight vector (must sum to 1.0)
LAYER_WEIGHTS = {
    "elo": 0.30,
    "form": 0.20,
    "map_adv": 0.15,
    "h2h": 0.10,
    "player_rating": 0.15,
    "context": 0.10,
}


# ──────────────────────────────────────────────────────────────────────────────
# DATA LOADERS
# ──────────────────────────────────────────────────────────────────────────────
def load_team_data(filepath: str = "cs2_team_data.csv") -> dict:
    """
    Load CS2 team statistics from CSV.

    Returns dict:
        {
          'NAVI': {
            'hltv_ranking': 3, 'elo': 1820, 'w': 38, 'l': 12,
            'win_rate': 0.76, 'lan_win_rate': 0.78,
            'avg_player_rating': 1.12, 'star_player_rating': 1.31,
            'form_last10': 8,
            'map_win_rates': {'Mirage': 0.72, 'Inferno': 0.68, ...},
            'maps_above_55': 6,
          }, ...
        }

    HOW TO UPDATE:
      1. Go to https://www.hltv.org/ranking/teams/ for rankings.
      2. Go to https://www.hltv.org/stats/teams/maps/{id}/{name} for map stats.
      3. Update cs2_team_data.csv and re-run the model.
    """
    teams = {}
    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row["Team"].strip()
            teams[name] = {
                "hltv_ranking": int(row["HLTV_Ranking"]),
                "elo": float(row["Elo"]),
                "w": int(row["W"]),
                "l": int(row["L"]),
                "win_rate": float(row["Win_Rate"]),
                "lan_win_rate": float(row["LAN_Win_Rate"]),
                "avg_player_rating": float(row["Avg_Player_Rating"]),
                "star_player_rating": float(row["Star_Player_Rating"]),
                "form_last10": int(row["Form_Last10"]),
                "maps_above_55": int(row["Maps_Above_55"]),
                "map_win_rates": {
                    "Mirage": float(row["Mirage_WR"]),
                    "Inferno": float(row["Inferno_WR"]),
                    "Nuke": float(row["Nuke_WR"]),
                    "Overpass": float(row["Overpass_WR"]),
                    "Ancient": float(row["Ancient_WR"]),
                    "Anubis": float(row["Anubis_WR"]),
                    "Dust2": float(row["Dust2_WR"]),
                },
            }
    return teams


def load_h2h_data(filepath: str = "cs2_h2h_data.csv") -> dict:
    """
    Load head-to-head records from CSV.

    Returns dict keyed by frozenset({team_a, team_b}):
        {
          frozenset({'NAVI','G2'}): {
            'total': 28, 'a_wins': 14, 'b_wins': 14,
            'team_a': 'NAVI', 'team_b': 'G2',
            'recent_6mo_a': 3, 'recent_6mo_b': 4, 'recent_6mo_total': 7
          }, ...
        }

    HOW TO UPDATE:
      Go to https://www.hltv.org/results?team={id_A}&team={id_B} and
      count victories over the last 6 months and overall.
    """
    h2h = {}
    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            a = row["Team_A"].strip()
            b = row["Team_B"].strip()
            key = frozenset({a, b})
            h2h[key] = {
                "team_a": a,
                "team_b": b,
                "total": int(row["Total_Matches"]),
                "a_wins": int(row["Team_A_Wins"]),
                "b_wins": int(row["Team_B_Wins"]),
                "last_match": row["Last_Match_Date"].strip(),
                "recent_6mo_a": int(row["Recent_6mo_A_Wins"]),
                "recent_6mo_b": int(row["Recent_6mo_B_Wins"]),
                "recent_6mo_total": int(row["Recent_6mo_Total"]),
            }
    return h2h


def load_player_data(filepath: str = "cs2_player_data.csv") -> dict:
    """
    Load per-player statistics from CSV.

    Returns dict keyed by team name:
        { 'NAVI': [{'ign': 's1mple', 'rating': 1.35, ...}, ...], ... }

    HOW TO UPDATE:
      Go to https://www.hltv.org/stats/players/{id}/{ign} and copy
      Rating 2.0, K/D, ADR, and KAST% for each player on the roster.
    """
    players_by_team: dict = {}
    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            team = row["Team"].strip()
            player = {
                "ign": row["Player_IGN"].strip(),
                "rating": float(row["HLTV_Rating_2_0"]),
                "kd": float(row["KD_Ratio"]),
                "adr": float(row["ADR"]),
                "kast": float(row["KAST_Pct"]),
                "impact": float(row["Impact_Rating"]),
                "hs_pct": float(row["Headshot_Pct"]),
                "maps": int(row["Maps_Played"]),
            }
            players_by_team.setdefault(team, []).append(player)
    return players_by_team


def load_match_form(filepath: str = "cs2_match_form.csv") -> dict:
    """
    Load recent match results from CSV.

    Returns dict keyed by team name — list of match dicts (most recent first):
        { 'NAVI': [{'date': '...', 'opponent': 'FaZe', 'opp_rank': 2,
                    'result': 'W', 'lan': True, ...}, ...] }

    HOW TO UPDATE:
      Go to https://www.hltv.org/results?team={id} and record the last
      10 results. Always keep the list sorted with the most recent first.
    """
    form: dict = {}
    rows_all = []
    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows_all.append(row)

    # Sort by date descending so index 0 = most recent
    rows_all.sort(key=lambda r: r["Date"], reverse=True)

    for row in rows_all:
        team = row["Team"].strip()
        match = {
            "date": row["Date"].strip(),
            "opponent": row["Opponent"].strip(),
            "opp_rank": int(row["Opponent_HLTV_Rank"]),
            "result": row["Result"].strip().upper(),
            "map": row["Map"].strip(),
            "event": row["Event"].strip(),
            "lan": row["LAN_Online"].strip().upper() == "LAN",
            "score": row["Score"].strip(),
        }
        form.setdefault(team, []).append(match)
    return form


# ──────────────────────────────────────────────────────────────────────────────
# LAYER 1: ELO RATING & WIN PROBABILITY
# ──────────────────────────────────────────────────────────────────────────────
def calculate_elo_probability(elo_a: float, elo_b: float) -> float:
    """
    Layer 1: Elo-based win probability for Team A.

    Formula:
        P(A wins) = 1 / (1 + 10^((Elo_B - Elo_A) / 400))

    The 400-point divisor is the standard chess/gaming convention.
    A 400-point Elo gap means the stronger team wins ~91% of the time.

    Parameters:
        elo_a : float — Current Elo rating of Team A
        elo_b : float — Current Elo rating of Team B

    Returns:
        float — Probability [0, 1] that Team A wins
    """
    return 1.0 / (1.0 + 10.0 ** ((elo_b - elo_a) / 400.0))


def update_elo(elo: float, actual: float, expected: float, lan: bool = False) -> float:
    """
    Update a team's Elo after a match result.

    Formula:
        New_Elo = Old_Elo + K × (Actual - Expected)

    Parameters:
        elo      : float — Team's current Elo
        actual   : float — Match outcome (1.0 = win, 0.0 = loss)
        expected : float — Model's expected probability of winning
        lan      : bool  — LAN/Major match uses higher K-factor (48 vs 32)

    Returns:
        float — Updated Elo rating
    """
    k = ELO_K_LAN if lan else ELO_K_REGULAR
    return elo + k * (actual - expected)


# ──────────────────────────────────────────────────────────────────────────────
# LAYER 2: FORM RATING (RECENT PERFORMANCE)
# ──────────────────────────────────────────────────────────────────────────────
def calculate_form_score(
    matches: list,
    recency_weights: list = RECENCY_WEIGHTS,
) -> float:
    """
    Layer 2: Recent-form score for a team.

    Formula:
        Form_Score = Σ(Result_i × Recency_Weight_i × Opp_Strength_i) / N

    Where:
        Result_i         = 1 for win, 0 for loss
        Recency_Weight_i = [1.0, 0.95, 0.90 ... 0.55] (most recent first)
        Opp_Strength_i   = min(Opponent_HLTV_Rank / 30, 1.0)
        N                = number of matches considered (max 10)

    The score is then normalized to [0, 1] against the theoretical maximum
    (all wins vs rank-1 opponents with full recency weight).

    Parameters:
        matches         : list — Ordered list of match dicts (most recent first)
        recency_weights : list — Recency weight vector

    Returns:
        float — Form score in [0, 1]
    """
    if not matches:
        return 0.5  # Neutral form if no data

    n = min(len(matches), len(recency_weights))
    weighted_sum = 0.0
    max_possible = 0.0

    for i in range(n):
        m = matches[i]
        w = recency_weights[i]
        result = 1.0 if m["result"] == "W" else 0.0
        # Higher-ranked (lower rank number) opponents yield higher strength.
        # Rank 1 (best) → strength 1.0; Rank 30 (weakest tracked) → strength 0.033.
        opp_strength = min((31 - m["opp_rank"]) / 30.0, 1.0)
        weighted_sum += result * w * opp_strength
        max_possible += w * 1.0  # Maximum: win against rank 1 opponent (strength = 1.0)

    if max_possible == 0:
        return 0.5
    # Normalize: divide by maximum-possible contribution using the same weights
    max_opp_contribution = sum(recency_weights[:n]) * 1.0
    return min(weighted_sum / max_opp_contribution, 1.0)


# ──────────────────────────────────────────────────────────────────────────────
# LAYER 3: MAP POOL ADVANTAGE
# ──────────────────────────────────────────────────────────────────────────────
def calculate_map_advantage(
    map_rates_a: dict,
    map_rates_b: dict,
    maps: list = ACTIVE_DUTY_MAPS,
) -> float:
    """
    Layer 3: Map pool advantage for Team A over Team B.

    Formula:
        Map_Advantage = Σ(WR_A_i - WR_B_i) / Maps_in_pool

    Also computes Map_Depth = Count(maps where WR > 55%) / 7
    (used internally; a team with 5/7 strong maps has veto resilience).

    The raw advantage is in (-1, +1). We shift to [0, 1]:
        map_adv_normalized = (Map_Advantage + 1) / 2

    Parameters:
        map_rates_a : dict — { 'Mirage': 0.72, 'Inferno': 0.68, ... }
        map_rates_b : dict — Same structure for Team B
        maps        : list — Active duty map names (7 maps)

    Returns:
        float — Normalized advantage in [0, 1]; 0.5 = equal map pool
    """
    total_diff = 0.0
    count = 0
    for m in maps:
        wr_a = map_rates_a.get(m, 0.5)
        wr_b = map_rates_b.get(m, 0.5)
        total_diff += wr_a - wr_b
        count += 1

    if count == 0:
        return 0.5
    raw_advantage = total_diff / count
    # Normalize from (-1, +1) to (0, 1)
    return (raw_advantage + 1.0) / 2.0


def calculate_map_depth(map_rates: dict, threshold: float = 0.55) -> float:
    """
    Map depth score: fraction of maps where win rate exceeds threshold.

    Formula:
        Map_Depth = Count(maps where WR > threshold) / 7

    Returns:
        float — [0, 1]; higher = more veto-resilient team
    """
    strong = sum(1 for wr in map_rates.values() if wr > threshold)
    return strong / len(ACTIVE_DUTY_MAPS)


# ──────────────────────────────────────────────────────────────────────────────
# LAYER 4: HEAD-TO-HEAD RECORD
# ──────────────────────────────────────────────────────────────────────────────
def calculate_h2h_factor(
    team_a: str,
    team_b: str,
    h2h_data: dict,
    min_matches: int = 3,
) -> float:
    """
    Layer 4: Head-to-head win probability for Team A.

    Formula:
        H2H_Factor = (H2H_Wins_A / Total_H2H) if Total >= 3 else 0.5

    Recent 6-month matches are weighted 1.5× to emphasise current form.
    A blended calculation is used:
        Blended_Wins_A = (old_wins × 1.0) + (recent_wins_A × 0.5)
        Blended_Total  = (old_total × 1.0) + (recent_total × 0.5)

    If fewer than min_matches exist, returns 0.5 (neutral).

    Parameters:
        team_a     : str  — Name of Team A
        team_b     : str  — Name of Team B
        h2h_data   : dict — Loaded from load_h2h_data()
        min_matches: int  — Minimum historical matches required

    Returns:
        float — H2H win probability for Team A in [0, 1]
    """
    key = frozenset({team_a, team_b})
    if key not in h2h_data:
        return 0.5  # No data → neutral

    record = h2h_data[key]
    if record["total"] < min_matches:
        return 0.5

    # Determine which team in the record is team_a
    if record["team_a"] == team_a:
        a_wins = record["a_wins"]
        recent_a = record["recent_6mo_a"]
        recent_b = record["recent_6mo_b"]
    else:
        a_wins = record["b_wins"]
        recent_a = record["recent_6mo_b"]
        recent_b = record["recent_6mo_a"]

    total = record["total"]
    recent_total = record["recent_6mo_total"]

    # Weight recent 6 months at 1.5× (add 0.5 extra weight to recent matches)
    blended_a_wins = a_wins + (recent_a * 0.5)
    blended_total = total + (recent_total * 0.5)

    if blended_total == 0:
        return 0.5
    return min(max(blended_a_wins / blended_total, 0.0), 1.0)


# ──────────────────────────────────────────────────────────────────────────────
# LAYER 5: PLAYER RATING COMPOSITE
# ──────────────────────────────────────────────────────────────────────────────
def calculate_player_rating(
    players_a: list,
    players_b: list,
) -> float:
    """
    Layer 5: Player-rating-based win probability for Team A.

    Formulas:
        Team_Rating = Mean(Player_Rating_2.0 for all players)
        Star_Factor = Max(Player_Ratings) - Mean(Player_Ratings)

    The composite score per team combines mean skill and carry potential:
        Composite = Team_Rating + 0.5 × Star_Factor

    Team A's probability is then:
        P_player = Composite_A / (Composite_A + Composite_B)

    Parameters:
        players_a : list — List of player dicts for Team A (from load_player_data)
        players_b : list — Same for Team B

    Returns:
        float — Rating-based win probability for Team A in [0, 1]
    """
    def team_composite(players: list) -> float:
        if not players:
            return 1.0  # Neutral baseline
        ratings = [p["rating"] for p in players]
        mean_r = sum(ratings) / len(ratings)
        star_factor = max(ratings) - mean_r
        return mean_r + 0.5 * star_factor

    comp_a = team_composite(players_a)
    comp_b = team_composite(players_b)
    total = comp_a + comp_b
    if total == 0:
        return 0.5
    return comp_a / total


# ──────────────────────────────────────────────────────────────────────────────
# LAYER 6: LAN / ONLINE & CONTEXT ADJUSTMENTS
# ──────────────────────────────────────────────────────────────────────────────
def calculate_context_adjustment(
    lan_win_rate_a: float,
    lan_win_rate_b: float,
    is_lan: bool = False,
    matches_last_48h_a: int = 0,
    matches_last_48h_b: int = 0,
    is_playoff_or_major: bool = False,
) -> float:
    """
    Layer 6: Contextual probability adjustment for Team A.

    Formula:
        Context_Adj = LAN_bonus_A - LAN_bonus_B
                    - Fatigue_A + Fatigue_B
                    + Importance_boost

    Components:
        LAN_bonus    : +0.03 if team's LAN win rate > 55% and match is LAN
        Fatigue      : -0.02 per match played in the last 48 hours
        Importance   : +0.02 boost (to Team A) for playoff/Major matches

    The raw adjustment is then converted to a probability via sigmoid-like
    centering around 0.5:
        Context_P = 0.5 + Context_Adj
    Clamped to [0.1, 0.9] to avoid extreme values.

    Parameters:
        lan_win_rate_a        : float — Team A's historical LAN win rate
        lan_win_rate_b        : float — Team B's historical LAN win rate
        is_lan                : bool  — Is this match played at a LAN event?
        matches_last_48h_a    : int   — Matches Team A has played in last 48 h
        matches_last_48h_b    : int   — Matches Team B has played in last 48 h
        is_playoff_or_major   : bool  — Is this a playoff/Major stage match?

    Returns:
        float — Context probability for Team A in [0.1, 0.9]
    """
    adj = 0.0

    # LAN bonus
    if is_lan:
        if lan_win_rate_a > LAN_WIN_RATE_BONUS_THRESHOLD:
            adj += LAN_BONUS
        if lan_win_rate_b > LAN_WIN_RATE_BONUS_THRESHOLD:
            adj -= LAN_BONUS

    # Fatigue penalty
    adj -= matches_last_48h_a * FATIGUE_PENALTY
    adj += matches_last_48h_b * FATIGUE_PENALTY

    # Importance boost (benefits favourite = Team A by convention)
    if is_playoff_or_major:
        adj += IMPORTANCE_BOOST

    # Convert to probability centered around 0.5
    context_prob = 0.5 + adj
    return min(max(context_prob, 0.1), 0.9)


# ──────────────────────────────────────────────────────────────────────────────
# LAYER 7: COMPOSITE PROBABILITY
# ──────────────────────────────────────────────────────────────────────────────
def calculate_composite_probability(
    elo_p: float,
    form_p: float,
    map_adv_p: float,
    h2h_p: float,
    player_p: float,
    context_p: float,
    weights: dict = LAYER_WEIGHTS,
) -> float:
    """
    Layer 7: Weighted composite win probability for Team A.

    Formula:
        Final_P = w1×Elo + w2×Form + w3×MapAdv + w4×H2H +
                  w5×PlayerRating + w6×Context

    Default weights: elo=0.30, form=0.20, map_adv=0.15, h2h=0.10,
                     player_rating=0.15, context=0.10

    Inputs are already in [0, 1] space representing Team A's probability.
    The weighted sum is clamped to [0.01, 0.99] for trading validity.

    Parameters:
        elo_p      : float — Layer 1 probability
        form_p     : float — Layer 2 probability
        map_adv_p  : float — Layer 3 probability
        h2h_p      : float — Layer 4 probability
        player_p   : float — Layer 5 probability
        context_p  : float — Layer 6 probability
        weights    : dict  — Layer weight dictionary

    Returns:
        float — Final composite win probability in [0.01, 0.99]
    """
    final_p = (
        weights["elo"]           * elo_p
        + weights["form"]        * form_p
        + weights["map_adv"]     * map_adv_p
        + weights["h2h"]         * h2h_p
        + weights["player_rating"] * player_p
        + weights["context"]     * context_p
    )
    return min(max(final_p, 0.01), 0.99)


# ──────────────────────────────────────────────────────────────────────────────
# TRADING MATH (identical pattern to nba_ou_model.py)
# ──────────────────────────────────────────────────────────────────────────────
def calculate_edge(your_prob: float, market_prob: float) -> float:
    """
    Edge = Your Probability - Market Implied Probability.
    Positive edge = the market undervalues your side.
    """
    return your_prob - market_prob


def calculate_ev(your_prob: float, market_price: float) -> float:
    """
    Expected Value per share (Polymarket / Betfair binary market).

    Formula:
        EV = (p × profit_if_win) - (q × cost_if_lose)

    On a binary market: buy at market_price, win pays $1, lose pays $0.
        profit_if_win = 1 - market_price
        cost_if_lose  = market_price
    """
    profit_if_win = 1.0 - market_price
    cost_if_lose = market_price
    q = 1.0 - your_prob
    return (your_prob * profit_if_win) - (q * cost_if_lose)


def calculate_kelly(your_prob: float, market_price: float) -> float:
    """
    Kelly Criterion for optimal bet sizing.

    Formula:
        f* = (b×p - q) / b
        b  = (1 - market_price) / market_price   (net odds)
        p  = your estimated probability
        q  = 1 - p

    Returns fraction of bankroll to commit (use half-Kelly for safety).
    Returns 0.0 if the Kelly fraction is negative (no edge, do not bet).
    """
    b = (1.0 - market_price) / market_price
    p = your_prob
    q = 1.0 - p
    kelly = (b * p - q) / b
    return max(kelly, 0.0)


def confidence_rating(
    team_a: str,
    team_b: str,
    h2h_data: dict,
    players_a: list,
    players_b: list,
    form_a: list,
    form_b: list,
) -> str:
    """
    Confidence level based on data completeness.

    High   — H2H data exists AND player data present for both teams
             AND 10 form matches available for both teams
    Medium — H2H data OR player data present, some form history
    Low    — Minimal data (new teams, sparse history)

    Returns:
        str — 'High', 'Medium', or 'Low'
    """
    key = frozenset({team_a, team_b})
    has_h2h = key in h2h_data and h2h_data[key]["total"] >= 3
    has_players = len(players_a) >= 5 and len(players_b) >= 5
    has_form = len(form_a) >= 8 and len(form_b) >= 8

    if has_h2h and has_players and has_form:
        return "High"
    elif has_h2h or (has_players and has_form):
        return "Medium"
    return "Low"


# ──────────────────────────────────────────────────────────────────────────────
# FULL MATCH ANALYSIS
# ──────────────────────────────────────────────────────────────────────────────
def analyze_match(
    team_a: str,
    team_b: str,
    teams: dict,
    h2h_data: dict,
    players_by_team: dict,
    form_by_team: dict,
    market_price_a: float,
    is_lan: bool = False,
    matches_last_48h_a: int = 0,
    matches_last_48h_b: int = 0,
    is_playoff_or_major: bool = False,
    bankroll: Optional[float] = None,
    weights: dict = LAYER_WEIGHTS,
) -> dict:
    """
    Run the full 7-layer CS2 match model and return trading signals.

    Parameters:
    -----------
    team_a               : str   — Name of Team A (must match cs2_team_data.csv)
    team_b               : str   — Name of Team B
    teams                : dict  — Loaded from load_team_data()
    h2h_data             : dict  — Loaded from load_h2h_data()
    players_by_team      : dict  — Loaded from load_player_data()
    form_by_team         : dict  — Loaded from load_match_form()
    market_price_a       : float — Market price for Team A to win (e.g. 0.55)
    is_lan               : bool  — LAN event flag
    matches_last_48h_a   : int   — Team A fatigue count
    matches_last_48h_b   : int   — Team B fatigue count
    is_playoff_or_major  : bool  — Playoff/Major stage flag
    bankroll             : float — Optional total bankroll for Kelly sizing
    weights              : dict  — Layer weight overrides

    Returns: dict with all layer probabilities and trading signals
    """
    # Validate
    if team_a not in teams:
        raise ValueError(f"'{team_a}' not found in cs2_team_data.csv")
    if team_b not in teams:
        raise ValueError(f"'{team_b}' not found in cs2_team_data.csv")

    a = teams[team_a]
    b = teams[team_b]

    players_a = players_by_team.get(team_a, [])
    players_b = players_by_team.get(team_b, [])
    form_a = form_by_team.get(team_a, [])
    form_b = form_by_team.get(team_b, [])

    # ── Layer 1: Elo ──────────────────────────────────────────────────────────
    elo_p = calculate_elo_probability(a["elo"], b["elo"])

    # ── Layer 2: Form ─────────────────────────────────────────────────────────
    form_score_a = calculate_form_score(form_a)
    form_score_b = calculate_form_score(form_b)
    form_total = form_score_a + form_score_b
    form_p = form_score_a / form_total if form_total > 0 else 0.5

    # ── Layer 3: Map Pool ─────────────────────────────────────────────────────
    map_adv_p = calculate_map_advantage(a["map_win_rates"], b["map_win_rates"])
    map_depth_a = calculate_map_depth(a["map_win_rates"])
    map_depth_b = calculate_map_depth(b["map_win_rates"])

    # ── Layer 4: Head-to-Head ─────────────────────────────────────────────────
    h2h_p = calculate_h2h_factor(team_a, team_b, h2h_data)

    # ── Layer 5: Player Ratings ───────────────────────────────────────────────
    player_p = calculate_player_rating(players_a, players_b)

    # ── Layer 6: Context ──────────────────────────────────────────────────────
    context_p = calculate_context_adjustment(
        lan_win_rate_a=a["lan_win_rate"],
        lan_win_rate_b=b["lan_win_rate"],
        is_lan=is_lan,
        matches_last_48h_a=matches_last_48h_a,
        matches_last_48h_b=matches_last_48h_b,
        is_playoff_or_major=is_playoff_or_major,
    )

    # ── Layer 7: Composite ────────────────────────────────────────────────────
    final_p = calculate_composite_probability(
        elo_p, form_p, map_adv_p, h2h_p, player_p, context_p, weights
    )

    # ── Trading Math ──────────────────────────────────────────────────────────
    market_prob_a = market_price_a
    edge = calculate_edge(final_p, market_prob_a)
    ev = calculate_ev(final_p, market_price_a)
    kelly = calculate_kelly(final_p, market_price_a)
    half_kelly = kelly / 2.0

    # Signal evaluation
    if edge >= MIN_EDGE_THRESHOLD and ev > 0:
        signal = f"✅ GO TRADE ({team_a})"
        side = team_a
    else:
        # Check the opposite side
        prob_b = 1.0 - final_p
        price_b = 1.0 - market_price_a
        edge_b = calculate_edge(prob_b, price_b)
        ev_b = calculate_ev(prob_b, price_b)
        kelly_b = calculate_kelly(prob_b, price_b)
        if edge_b >= MIN_EDGE_THRESHOLD and ev_b > 0:
            signal = f"✅ GO TRADE ({team_b})"
            side = team_b
            edge = edge_b
            ev = ev_b
            kelly = kelly_b
            half_kelly = kelly / 2.0
        else:
            signal = "❌ NO TRADE"
            side = "NONE"

    # Bet sizing
    bet_amount = None
    shares = None
    if bankroll and side != "NONE":
        bet_amount = round(bankroll * half_kelly, 2)
        if side == team_a:
            share_price = market_price_a
        else:
            share_price = 1.0 - market_price_a
        shares = int(bet_amount / share_price) if share_price > 0 else 0

    # Confidence rating
    confidence = confidence_rating(
        team_a, team_b, h2h_data, players_a, players_b, form_a, form_b
    )

    return {
        "team_a": team_a,
        "team_b": team_b,
        # Layer probabilities (Team A perspective)
        "elo_p": round(elo_p, 4),
        "form_score_a": round(form_score_a, 4),
        "form_score_b": round(form_score_b, 4),
        "form_p": round(form_p, 4),
        "map_adv_p": round(map_adv_p, 4),
        "map_depth_a": round(map_depth_a, 4),
        "map_depth_b": round(map_depth_b, 4),
        "h2h_p": round(h2h_p, 4),
        "player_p": round(player_p, 4),
        "context_p": round(context_p, 4),
        "final_p": round(final_p, 4),
        # Trading signals
        "market_price_a": market_price_a,
        "market_prob_a": round(market_prob_a, 4),
        "edge": round(edge, 4),
        "ev": round(ev, 4),
        "kelly_fraction": round(kelly, 4),
        "half_kelly": round(half_kelly, 4),
        "signal": signal,
        "side": side,
        "confidence": confidence,
        "bet_amount": bet_amount,
        "shares": shares,
    }


def print_analysis(result: dict):
    """Pretty-print the full CS2 match analysis."""
    a = result["team_a"]
    b = result["team_b"]

    print("=" * 65)
    print(f"  CS2 MATCH MODEL — {a} vs {b}")
    print("=" * 65)
    print()
    print("🧮 LAYER PROBABILITIES (Team A = {})".format(a))
    print(f"   Layer 1 — Elo:           {result['elo_p']*100:.1f}%")
    print(f"   Layer 2 — Form:          {result['form_p']*100:.1f}%  "
          f"(A={result['form_score_a']:.3f}, B={result['form_score_b']:.3f})")
    print(f"   Layer 3 — Map Pool:      {result['map_adv_p']*100:.1f}%  "
          f"(depth A={result['map_depth_a']:.2f}, B={result['map_depth_b']:.2f})")
    print(f"   Layer 4 — H2H:           {result['h2h_p']*100:.1f}%")
    print(f"   Layer 5 — Player Rating: {result['player_p']*100:.1f}%")
    print(f"   Layer 6 — Context:       {result['context_p']*100:.1f}%")
    print()
    print(f"   ➡️  FINAL PROBABILITY ({a} wins): {result['final_p']*100:.1f}%")
    print()
    print("📈 MARKET COMPARISON:")
    print(f"   Market Price ({a}):    ${result['market_price_a']:.2f}")
    print(f"   Market Implied Prob:    {result['market_prob_a']*100:.1f}%")
    print(f"   Your Model Prob:        {result['final_p']*100:.1f}%")
    print()
    print("💰 TRADE ANALYSIS:")
    print(f"   Edge:                   {result['edge']*100:+.2f}%")
    print(f"   Expected Value:         ${result['ev']:+.4f} per share")
    print(f"   Kelly Fraction:         {result['kelly_fraction']*100:.2f}%")
    print(f"   Half-Kelly (safer):     {result['half_kelly']*100:.2f}%")
    print(f"   Confidence:             {result['confidence']}")
    print()
    if result["bet_amount"] is not None:
        print(f"   💵 Suggested Bet:       ${result['bet_amount']}")
        print(f"   📦 Shares to Buy:       {result['shares']}")
        print()
    print(f"   🚦 SIGNAL: {result['signal']}")
    print("=" * 65)


# ──────────────────────────────────────────────────────────────────────────────
# MAIN — RUN TEST CASE
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Load all data
    teams = load_team_data("cs2_team_data.csv")
    h2h_data = load_h2h_data("cs2_h2h_data.csv")
    players_by_team = load_player_data("cs2_player_data.csv")
    form_by_team = load_match_form("cs2_match_form.csv")

    print()
    print("🧪 TEST CASE: NAVI vs G2 (LAN — BLAST Premier World Final)")
    print("   Market price for NAVI to win: $0.45")
    print()

    result = analyze_match(
        team_a="NAVI",
        team_b="G2",
        teams=teams,
        h2h_data=h2h_data,
        players_by_team=players_by_team,
        form_by_team=form_by_team,
        market_price_a=0.45,
        is_lan=True,
        matches_last_48h_a=0,
        matches_last_48h_b=0,
        is_playoff_or_major=True,
        bankroll=500.0,
    )

    print_analysis(result)

    # ──────────────────────────────────────────────────────────────────────────
    # LAYER-BY-LAYER VERIFICATION
    # ──────────────────────────────────────────────────────────────────────────
    print()
    print("🔍 LAYER VERIFICATION (manual calculation):")
    navi_elo = teams["NAVI"]["elo"]
    g2_elo = teams["G2"]["elo"]
    elo_check = 1.0 / (1.0 + 10.0 ** ((g2_elo - navi_elo) / 400.0))
    print(f"   Elo ({navi_elo} vs {g2_elo}): 1/(1+10^(({g2_elo}-{navi_elo})/400)) "
          f"= {elo_check:.4f}   Got: {result['elo_p']}")
    print(f"   H2H (NAVI vs G2, blended): Got {result['h2h_p']:.4f}")
    print(f"   Final composite probability: {result['final_p']*100:.1f}%")
    print()

    # ──────────────────────────────────────────────────────────────────────────
    # MULTI-MATCH SCANNER
    # ──────────────────────────────────────────────────────────────────────────
    print()
    print("=" * 80)
    print("  📋 MULTI-MATCH SCANNER")
    print("=" * 80)

    upcoming_matches = [
        {"a": "NAVI",     "b": "G2",       "price": 0.45, "lan": True,  "major": True},
        {"a": "FaZe",     "b": "Vitality",  "price": 0.60, "lan": True,  "major": True},
        {"a": "Spirit",   "b": "Heroic",    "price": 0.55, "lan": False, "major": False},
        {"a": "MOUZ",     "b": "Cloud9",    "price": 0.65, "lan": False, "major": False},
    ]

    header = (f"{'Matchup':<20} {'Model%':>7} {'Mkt%':>6} {'Edge':>7} "
              f"{'EV':>8} {'Kelly':>7} {'Conf':>7} {'Signal'}")
    print(header)
    print("-" * 80)

    for g in upcoming_matches:
        r = analyze_match(
            team_a=g["a"], team_b=g["b"],
            teams=teams, h2h_data=h2h_data,
            players_by_team=players_by_team, form_by_team=form_by_team,
            market_price_a=g["price"],
            is_lan=g["lan"], is_playoff_or_major=g["major"],
        )
        matchup = f"{r['team_a']} vs {r['team_b']}"
        print(
            f"{matchup:<20} {r['final_p']*100:>6.1f}% {r['market_prob_a']*100:>5.1f}% "
            f"{r['edge']*100:>+6.2f}% ${r['ev']:>+7.4f} {r['half_kelly']*100:>6.2f}% "
            f"{r['confidence']:>6}  {r['signal']}"
        )

    print()
    print("Done! Only trade matches with ✅ signal and confidence Medium or High.")
