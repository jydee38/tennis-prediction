"""
Test script to verify that bulletin and main app give IDENTICAL probabilities.
Uses the SAME scraped data for both paths to eliminate API variability.
Follows the EXACT same order as each app.
"""
import pandas as pd
from python.app_logic import get_data_and_train_model, predict_match_outcome, find_player_by_name
from python.data.tennisexplorer_scraper import (
    scrape_player_rapidapi_history, scrape_player_te_history, merge_te_to_base_socle
)
from python.data.rapidapi_client import RapidAPIClient
from datetime import datetime

def pcb(msg): pass

p1_name = "Jakub Mensik"
p2_name = "Joao Fonseca"
t_name  = "Roland Garros"
row_template = {
    'player_1': p1_name, 'player_2': p2_name,
    'tournament': t_name,
    'tournament_surface': 'Clay',
    'tournament_level': 'M',
    'round': 'R32',
    'score': 'Upcoming'
}

# ── Scrape player data ONCE (shared between both paths) ──────────────────────
print("=== Scraping player data ONCE ===")
client = RapidAPIClient()
_today = datetime.now().strftime("%Y-%m-%d")
try: client.populate_id_map_for_date(_today, tour="atp")
except: pass

r1_id = client.get_player_id_by_name(p1_name, tour="atp")
r2_id = client.get_player_id_by_name(p2_name, tour="atp")

te_p1_data = scrape_player_rapidapi_history(p1_name, r1_id) if r1_id else scrape_player_te_history(p1_name, nb_years=3)
te_p2_data = scrape_player_rapidapi_history(p2_name, r2_id) if r2_id else scrape_player_te_history(p2_name, nb_years=3)
print(f"  P1 matches scraped: {len(te_p1_data.get('recent_matches', []))}")
print(f"  P2 matches scraped: {len(te_p2_data.get('recent_matches', []))}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MAIN APP PATH
# Order: live_charting → merge → inject → predict(skip_te_scrape=True)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n=== MAIN APP PATH ===")
df_main, model_main, features_main, db_main = get_data_and_train_model(
    progress_callback=pcb, tour="ATP", skip_training=False
)

p1_main = find_player_by_name(p1_name, db_main)
p2_main = find_player_by_name(p2_name, db_main)

# Step 1: live charting (Tennis Abstract) — same as main app line 3310-3313
if p1_main: p1_main.update_with_live_charting()
if p2_main: p2_main.update_with_live_charting()

# Step 2: merge to CSV — same as main app line 3316-3319
if p1_main: merge_te_to_base_socle(p1_main, te_p1_data, db_main)
if p2_main: merge_te_to_base_socle(p2_main, te_p2_data, db_main)

# Step 3: inject in memory — same as main app line 3322-3329
if p1_main and te_p1_data: p1_main.inject_scraped_history(te_p1_data)
if p2_main and te_p2_data: p2_main.inject_scraped_history(te_p2_data)

# Step 4: capture X passed to model
last_X = []
orig_pp = model_main.predict_proba
def mock_pp(X):
    last_X.clear()
    last_X.append(X.copy())
    return orig_pp(X)
model_main.predict_proba = mock_pp

row_main = row_template.copy()
if p1_main: row_main['Aces_Percentage_1'] = getattr(p1_main, 'aces_percentage', 0.0)
if p2_main: row_main['Aces_Percentage_2'] = getattr(p2_main, 'aces_percentage', 0.0)

prob_1_main, prob_2_main, _, _, _ = predict_match_outcome(
    model_main, row_main, features_main, db_main,
    p1_name, p2_name, t_name,
    te_p1=te_p1_data, te_p2=te_p2_data, skip_te_scrape=True
)
model_main.predict_proba = orig_pp

print(f"  MAIN APP result: {p1_name} {prob_1_main:.1%} | {p2_name} {prob_2_main:.1%}")
main_feats = dict(zip(features_main, last_X[0][0]))
for f, v in main_feats.items():
    print(f"    {f}: {v:.4f}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# BULLETIN PATH
# Order: live_charting → merge → inject → store latest_te_data → predict(skip_te_scrape=True)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n=== BULLETIN PATH ===")
df_bull, model_bull, features_bull, db_bull = get_data_and_train_model(
    progress_callback=pcb, tour="ATP", skip_training=False
)

p1_bull = find_player_by_name(p1_name, db_bull)
p2_bull = find_player_by_name(p2_name, db_bull)

# Step 1: live charting — same order as main app (after my fix)
if p1_bull: p1_bull.update_with_live_charting()
if p2_bull: p2_bull.update_with_live_charting()

# Step 2: merge
if p1_bull: merge_te_to_base_socle(p1_bull, te_p1_data, db_bull)
if p2_bull: merge_te_to_base_socle(p2_bull, te_p2_data, db_bull)

# Step 3: inject
if p1_bull and te_p1_data:
    p1_bull.inject_scraped_history(te_p1_data)
    p1_bull.latest_te_data = te_p1_data
if p2_bull and te_p2_data:
    p2_bull.inject_scraped_history(te_p2_data)
    p2_bull.latest_te_data = te_p2_data

# Step 4: capture X
last_X2 = []
orig_pp2 = model_bull.predict_proba
def mock_pp2(X):
    last_X2.clear()
    last_X2.append(X.copy())
    return orig_pp2(X)
model_bull.predict_proba = mock_pp2

row_bull = row_template.copy()
if p1_bull: row_bull['Aces_Percentage_1'] = getattr(p1_bull, 'aces_percentage', 0.0)
if p2_bull: row_bull['Aces_Percentage_2'] = getattr(p2_bull, 'aces_percentage', 0.0)

te_p1_b = getattr(p1_bull, 'latest_te_data', None)
te_p2_b = getattr(p2_bull, 'latest_te_data', None)

prob_1_bull, prob_2_bull, _, _, _ = predict_match_outcome(
    model_bull, row_bull, features_bull, db_bull,
    p1_name, p2_name, t_name,
    te_p1=te_p1_b, te_p2=te_p2_b, skip_te_scrape=True
)
model_bull.predict_proba = orig_pp2

print(f"  BULLETIN result:  {p1_name} {prob_1_bull:.1%} | {p2_name} {prob_2_bull:.1%}")
bull_feats = dict(zip(features_bull, last_X2[0][0]))
for f, v in bull_feats.items():
    print(f"    {f}: {v:.4f}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# COMPARISON
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n=== COMPARISON ===")
print(f"  MAIN:     {prob_1_main:.4f} vs {prob_2_main:.4f}")
print(f"  BULLETIN: {prob_1_bull:.4f} vs {prob_2_bull:.4f}")
delta = abs(prob_1_main - prob_1_bull)
print(f"  Delta: {delta:.4f}")
if delta < 0.001:
    print("  [OK] IDENTICAL (delta < 0.1%)")
else:
    print("  [FAIL] DIFFERENT -- Feature diffs:")
    for f in features_main:
        v1 = main_feats.get(f)
        v2 = bull_feats.get(f)
        if v1 is not None and v2 is not None and abs(v1 - v2) > 0.0001:
            print(f"    {f}: MAIN={v1:.4f} vs BULL={v2:.4f}")
