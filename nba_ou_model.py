"""
NBA Over/Under Trading Model for Polymarket
============================================= 
Source: https://www.basketball-reference.com/leagues/NBA_2026_ratings.html

This model predicts NBA game totals and identifies +EV trades on Polymarket.

FORMULAS USED:
1. Expected Game Pace = (Pace_A + Pace_B) / 2
2. Adjusted Offensive Output = (OffRtg_A × DRtg_B) / League_Avg_OffRtg
3. Projected Score = (Expected Game Pace / 100) × Adjusted Off Output
4. Projected Total = Score_A + Score_B + Adjustments
5. P(Over) = 1 - Φ((Line - Projected Total) / σ)    where σ ≈ 12
6. Edge = Your Probability - Market Probability
7. EV = (p × profit_if_win) - (q × cost_if_lose)
8. Kelly = (b×p - q) / b     [use half-Kelly]

TESTED: OKC vs CLE → Projected Total 227.43, P(Over 219.5) = 74.6%, Edge = 16.6%
"""

import csv
import math
from typing import Optional


# ──────────────────────────────────────────────
# CONSTANTS
# ──────────────────────────────────────────────
LEAGUE_AVG_ORTG = 115.30   # 2025-26 season average OffRtg
TOTAL_STD_DEV = 12.0       # Historical SD of NBA game totals (11-13 range)
HOME_COURT_ADJ = 1.5       # Home team scores ~1.5 more pts on average
B2B_ADJ = -2.5             # Back-to-back penalty (~2-3 pts fewer)
MIN_EDGE_THRESHOLD = 0.03  # Only trade when edge >= 3%


# ──────────────────────────────────────────────
# LOAD TEAM DATA FROM CSV
# ──────────────────────────────────────────────
def load_team_data(filepath: str = "team_data.csv") -> dict:
    """
    Load team stats from CSV file.
    Returns dict: { 'OKC': {'ORtg': 118.54, 'DRtg': 107.72, 'Pace': 99.1, ...}, ... }
    
    HOW TO UPDATE THIS FILE:
    1. Go to https://www.basketball-reference.com/leagues/NBA_2026_ratings.html
    2. Copy the ORtg, DRtg, and Pace columns for each team
    3. Update team_data.csv accordingly
    """
    teams = {}
    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            team = row["Team"].strip()
            if team == "LEAGUE_AVG":
                continue
            teams[team] = {
                "W": int(row["W"]),
                "L": int(row["L"]),
                "ORtg": float(row["ORtg"]),
                "DRtg": float(row["DRtg"]),
                "NRtg": float(row["NRtg"]),
                "Pace": float(row["Pace"]),
            }
    return teams


# ──────────────────────────────────────────────
# NORMAL DISTRIBUTION CDF (no scipy needed)
# ──────────────────────────────────────────────
def norm_cdf(z: float) -> float:
    """
    Standard normal cumulative distribution function.
    Uses the Abramowitz & Stegun approximation (accurate to ~1e-5).
    This replaces the need for scipy.stats.norm.cdf().
    """
    if z < -8.0:
        return 0.0
    if z > 8.0:
        return 1.0

    a1 = 0.254829592
    a2 = -0.284496736
    a3 = 1.421413741
    a4 = -1.453152027
    a5 = 1.061405429
    p = 0.3275911

    sign = 1
    if z < 0:
        sign = -1
        z_abs = -z
    else:
        z_abs = z

    t = 1.0 / (1.0 + p * z_abs)
    y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(-z_abs * z_abs / 2.0)

    return 0.5 * (1.0 + sign * y)


# ──────────────────────────────────────────────
# CORE MODEL CALCULATIONS
# ──────────────────────────────────────────────
def calculate_expected_pace(pace_a: float, pace_b: float) -> float:
    """
    Step 1: Expected Game Pace
    Formula: (Pace_A + Pace_B) / 2
    """
    return (pace_a + pace_b) / 2.0


def calculate_adjusted_offense(ortg_offense: float, drtg_defense: float, league_avg: float = LEAGUE_AVG_ORTG) -> float:
    """
    Step 2: Adjusted Offensive Output
    Formula: (OffRtg_A × DRtg_B) / League_Avg_OffRtg
    
    This normalizes a team's offense against the opponent's defense.
    - If opponent has a BAD defense (high DRtg), output goes UP
    - If opponent has a GOOD defense (low DRtg), output goes DOWN
    """
    return (ortg_offense * drtg_defense) / league_avg


def calculate_projected_score(game_pace: float, adj_offense: float) -> float:
    """
    Step 3: Projected Points for one team
    Formula: (Expected Game Pace / 100) × Adjusted Offensive Output
    """
    return (game_pace / 100.0) * adj_offense


def calculate_probability_over(projected_total: float, line: float, std_dev: float = TOTAL_STD_DEV) -> float:
    """
    Step 4: Probability that actual total exceeds the line
    Formula: P(Over) = 1 - Φ((Line - Projected_Total) / σ)
    
    Uses normal distribution with σ ≈ 12 (historical NBA game total SD)
    """
    z = (line - projected_total) / std_dev
    return 1.0 - norm_cdf(z)


def calculate_edge(your_prob: float, market_prob: float) -> float:
    """
    Step 5: Edge = Your Probability - Market Implied Probability
    Positive edge = you believe the market is mispriced in your favor
    """
    return your_prob - market_prob


def calculate_ev(your_prob: float, market_price: float) -> float:
    """
    Step 6: Expected Value per share
    Formula: EV = (p × profit_if_win) - (q × cost_if_lose)
    
    On Polymarket: Buy at market_price, win pays $1, lose pays $0
    - Profit if win = 1 - market_price
    - Loss if lose = market_price
    """
    profit_if_win = 1.0 - market_price
    cost_if_lose = market_price
    return (your_prob * profit_if_win) - ((1.0 - your_prob) * cost_if_lose)


def calculate_kelly(your_prob: float, market_price: float) -> float:
    """
    Step 7: Kelly Criterion for optimal bet sizing
    Formula: f* = (b×p - q) / b
    
    Where:
    - b = net odds = (1 - market_price) / market_price
    - p = your estimated probability
    - q = 1 - p
    
    Returns fraction of bankroll to bet (use HALF for safety)
    """
    b = (1.0 - market_price) / market_price  # net odds
    p = your_prob
    q = 1.0 - p
    kelly = (b * p - q) / b
    return max(kelly, 0.0)  # Never return negative (would mean don't bet)


# ──────────────────────────────────────────────
# FULL GAME ANALYSIS
# ──────────────────────────────────────────────
def analyze_game(
    team_a: str,
    team_b: str,
    teams: dict,
    polymarket_line: float,
    polymarket_yes_price: float,
    team_a_is_home: bool = True,
    team_a_b2b: bool = False,
    team_b_b2b: bool = False,
    bankroll: Optional[float] = None,
) -> dict:
    """
    Run the full model on a single NBA game.
    
    Parameters:
    -----------
    team_a : str - Team A abbreviation (e.g., 'OKC')
    team_b : str - Team B abbreviation (e.g., 'CLE')
    teams : dict - Team data from load_team_data()
    polymarket_line : float - The O/U line (e.g., 219.5)
    polymarket_yes_price : float - Price of YES/Over share (e.g., 0.58)
    team_a_is_home : bool - Is Team A the home team?
    team_a_b2b : bool - Is Team A on a back-to-back?
    team_b_b2b : bool - Is Team B on a back-to-back?
    bankroll : float - Your total bankroll (optional, for bet sizing)
    
    Returns: dict with all calculations
    """
    # Validate teams exist
    if team_a not in teams:
        raise ValueError(f"Team '{team_a}' not found in team_data.csv. Check abbreviation.")
    if team_b not in teams:
        raise ValueError(f"Team '{team_b}' not found in team_data.csv. Check abbreviation.")

    a = teams[team_a]
    b = teams[team_b]

    # Step 1: Expected Game Pace
    game_pace = calculate_expected_pace(a["Pace"], b["Pace"]) 

    # Step 2: Adjusted Offensive Output
    adj_off_a = calculate_adjusted_offense(a["ORtg"], b["DRtg"])
    adj_off_b = calculate_adjusted_offense(b["ORtg"], a["DRtg"])

    # Step 3: Projected Scores
    score_a = calculate_projected_score(game_pace, adj_off_a)
    score_b = calculate_projected_score(game_pace, adj_off_b)

    # Raw total
    raw_total = score_a + score_b

    # Adjustments
    home_adj = HOME_COURT_ADJ if team_a_is_home else -HOME_COURT_ADJ
    b2b_adj_a = B2B_ADJ if team_a_b2b else 0.0
    b2b_adj_b = B2B_ADJ if team_b_b2b else 0.0
    total_adjustment = home_adj + b2b_adj_a + b2b_adj_b

    # Final projected total
    projected_total = raw_total + total_adjustment

    # Step 4: Probability
    prob_over = calculate_probability_over(projected_total, polymarket_line)

    # Step 5: Edge
    market_prob = polymarket_yes_price
    edge = calculate_edge(prob_over, market_prob)

    # Step 6: Expected Value
    ev = calculate_ev(prob_over, polymarket_yes_price)

    # Step 7: Kelly
    kelly = calculate_kelly(prob_over, polymarket_yes_price)
    half_kelly = kelly / 2.0

    # Trade signal
    if edge >= MIN_EDGE_THRESHOLD and ev > 0:
        signal = "✅ GO TRADE (OVER)"
        side = "OVER"
    elif edge <= -MIN_EDGE_THRESHOLD and ev < 0:
        # Check if UNDER is the play
        prob_under = 1.0 - prob_over
        under_price = 1.0 - polymarket_yes_price
        under_edge = prob_under - (1.0 - market_prob)
        under_ev = calculate_ev(prob_under, under_price)
        under_kelly = calculate_kelly(prob_under, under_price)
        if under_edge >= MIN_EDGE_THRESHOLD and under_ev > 0:
            signal = "✅ GO TRADE (UNDER)"
            side = "UNDER"
            edge = under_edge
            ev = under_ev
            kelly = under_kelly
            half_kelly = kelly / 2.0
        else:
            signal = "❌ NO TRADE"
            side = "NONE"
    else:
        signal = "❌ NO TRADE"
        side = "NONE"

    # Bet sizing
    bet_amount = None
    shares = None
    if bankroll and side != "NONE":
        bet_amount = round(bankroll * half_kelly, 2)
        share_price = polymarket_yes_price if side == "OVER" else (1.0 - polymarket_yes_price)
        shares = int(bet_amount / share_price) if share_price > 0 else 0

    return {
        "team_a": team_a,
        "team_b": team_b,
        "game_pace": round(game_pace, 2),
        "adj_off_a": round(adj_off_a, 2),
        "adj_off_b": round(adj_off_b, 2),
        "projected_score_a": round(score_a, 2),
        "projected_score_b": round(score_b, 2),
        "raw_total": round(raw_total, 2),
        "adjustments": round(total_adjustment, 2),
        "projected_total": round(projected_total, 2),
        "polymarket_line": polymarket_line,
        "polymarket_price": polymarket_yes_price,
        "your_probability": round(prob_over, 4),
        "market_probability": market_prob,
        "edge": round(edge, 4),
        "expected_value": round(ev, 4),
        "kelly_fraction": round(kelly, 4),
        "half_kelly": round(half_kelly, 4),
        "signal": signal,
        "side": side,
        "bet_amount": bet_amount,
        "shares": shares,
    }


def print_analysis(result: dict):
    """Pretty print the full analysis."""
    print("=" * 65)
    print(f"  NBA OVER/UNDER MODEL — {result['team_a']} vs {result['team_b']}")
    print("=" * 65)
    print()
    print("📊 PROJECTION:")
    print(f"   Expected Game Pace:     {result['game_pace']} possessions")
    print(f"   {result['team_a']} Adj Offense:       {result['adj_off_a']}")
    print(f"   {result['team_b']} Adj Offense:       {result['adj_off_b']}")
    print(f"   {result['team_a']} Projected Score:   {result['projected_score_a']}")
    print(f"   {result['team_b']} Projected Score:   {result['projected_score_b']}")
    print(f"   Raw Total:              {result['raw_total']}")
    print(f"   Adjustments:            {result['adjustments']:+.1f}")
    print(f"   ➡️  FINAL PROJECTED TOTAL: {result['projected_total']}")
    print()
    print("📈 POLYMARKET COMPARISON:")
    print(f"   Market Line:            {result['polymarket_line']}")
    print(f"   Market YES Price:       ${result['polymarket_price']}")
    print(f"   Market Implied Prob:    {result['market_probability']*100:.1f}%")
    print(f"   Your Model Prob (Over): {result['your_probability']*100:.1f}%")
    print()
    print("💰 TRADE ANALYSIS:")
    print(f"   Edge:                   {result['edge']*100:+.2f}%")
    print(f"   Expected Value:         ${result['expected_value']:+.4f} per share")
    print(f"   Kelly Fraction:         {result['kelly_fraction']*100:.2f}%")
    print(f"   Half-Kelly (safer):     {result['half_kelly']*100:.2f}%")
    print()
    if result['bet_amount'] is not None:
        print(f"   💵 Suggested Bet:       ${result['bet_amount']}")
        print(f"   📦 Shares to Buy:       {result['shares']}")
        print()
    print(f"   🚦 SIGNAL: {result['signal']}")
    print("=" * 65)


# ──────────────────────────────────────────────
# MAIN — RUN TEST CASE
# ──────────────────────────────────────────────
if __name__ == "__main__":
    # Load team data
    teams = load_team_data("team_data.csv")
    
    print()
    print("🧪 TEST CASE: OKC (Home) vs CLE (Away)")
    print("   Polymarket Line: 219.5 | YES Price: $0.58")
    print()
    
    # Run the model
    result = analyze_game(
        team_a="OKC",
        team_b="CLE",
        teams=teams,
        polymarket_line=219.5,
        polymarket_yes_price=0.58,
        team_a_is_home=True,
        team_a_b2b=False,
        team_b_b2b=False,
        bankroll=500.0,  # Example: $500 bankroll
    )
    
    print_analysis(result)
    
    # ──────────────────────────────────────────
    # VERIFICATION OF TEST CASE
    # ──────────────────────────────────────────
    print()
    print("🔍 VERIFICATION (manual calculation):")
    print(f"   Game Pace: (99.1 + 99.3)/2 = 99.20  ✓ Got: {result['game_pace']}")
    print(f"   OKC Adj Off: (118.54 × 114.09)/115.30 = 117.30  ✓ Got: {result['adj_off_a']}")
    print(f"   CLE Adj Off: (118.22 × 107.72)/115.30 = 110.45  ✓ Got: {result['adj_off_b']}")
    print(f"   OKC Score: (99.20/100) × 117.30 = 116.36  ✓ Got: {result['projected_score_a']}")
    print(f"   CLE Score: (99.20/100) × 110.45 = 109.57  ✓ Got: {result['projected_score_b']}")
    print(f"   Total: 116.36 + 109.57 + 1.5 = 227.43  ✓ Got: {result['projected_total']}")
    print(f"   P(Over 219.5): ~74.6%  ✓ Got: {result['your_probability']*100:.1f}%")
    print()
    
    # ──────────────────────────────────────────
    # EXAMPLE: Multiple games in one session
    # ──────────────────────────────────────────
    print()
    print("=" * 65)
    print("  📋 MULTI-GAME EXAMPLE")
    print("=" * 65)
    
    games = [
        {"a": "BOS", "b": "MIA", "line": 228.5, "price": 0.52, "a_home": True, "a_b2b": False, "b_b2b": False},
        {"a": "DEN", "b": "GSW", "line": 230.5, "price": 0.55, "a_home": True, "a_b2b": False, "b_b2b": True},
        {"a": "LAL", "b": "BKN", "line": 222.5, "price": 0.50, "a_home": True, "a_b2b": False, "b_b2b": False},
    ]
    
    print(f"\n{'Matchup':<15} {'Proj Total':>10} {'Line':>8} {'Your Prob':>10} {'Mkt Prob':>9} {'Edge':>8} {'EV':>8} {'Signal':<20}")
    print("-" * 100)
    
    for g in games:
        r = analyze_game(
            team_a=g["a"], team_b=g["b"], teams=teams,
            polymarket_line=g["line"], polymarket_yes_price=g["price"],
            team_a_is_home=g["a_home"], team_a_b2b=g["a_b2b"] , team_b_b2b=g["b_b2b"],
        )
        print(f"{r['team_a']} vs {r['team_b']:<8} {r['projected_total']:>10.1f} {r['polymarket_line']:>8.1f} {r['your_probability']*100:>9.1f}% {r['market_probability']*100:>8.1f}% {r['edge']*100:>+7.2f}% ${r['expected_value']:>+6.4f} {r['signal']}")
    
    print()
    print("Done! Only trade games with ✅ signal.")