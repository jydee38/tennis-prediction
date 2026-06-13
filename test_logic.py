"""
Test script : Validation des corrections app_logic.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from python.data.data_loader import matches_data_loader
from python.app_logic import get_matches_for_tournament

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

data_df, players_db = matches_data_loader(path_to_data=DATA_DIR)
rome_names = [n for n in data_df['tournament'].unique() if 'rome' in str(n).lower() or 'internazionali' in str(n).lower() or 'italia' in str(n).lower()]
target = next((n for n in rome_names if '2026' in str(n)), rome_names[-1])

matches = get_matches_for_tournament(data_df, target, data_dir=DATA_DIR, tour="ATP")

print("LISTE DE TOUS LES MATCHS EN 8EME (Termines + Upcoming) :")
all_eighths = []
for m in matches:
    rnd   = str(m.get('round', '??'))
    score = str(m.get('row_data', {}).get('score', ''))
    if '8' in rnd:
        all_eighths.append(m)
        print(f"  - {rnd}: {m['player_1']} vs {m['player_2']} | Score: {score}")

print(f"\nTOTAL : {len(all_eighths)} matchs en 8eme.")
