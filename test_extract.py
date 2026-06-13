import pandas as pd
from python.app_logic import get_data_and_train_model
import logging
logging.basicConfig(level=logging.ERROR)

print("Loading data...")
data_df, _, _, _, _, _, _, _ = get_data_and_train_model(force_update=False)
print("Data loaded. Extracting Zverev...")

p_name = "Alexander Zverev"
p_matches = data_df[(data_df['Name_1'] == p_name) | (data_df['Name_2'] == p_name)].copy()
date_col = 'tournament_date'
p_matches = p_matches.sort_values(by=date_col, ascending=False).head(2)

for _, row in p_matches.iterrows():
    m_date_val = str(row.get(date_col, ''))
    name_1 = str(row.get('Name_1', ''))
    name_2 = str(row.get('Name_2', ''))
    winner_val = row.get('Winner', 0)
    
    if str(winner_val) == '0' or str(winner_val) == '0.0':
        actual_winner = name_1
        actual_loser = name_2
    else:
        actual_winner = name_2
        actual_loser = name_1
        
    is_win = (actual_winner == p_name)
    opponent = actual_loser if is_win else actual_winner
    
    print(f"Match: {m_date_val} | Win? {is_win} | vs {opponent} | {row.get('score', '')}")
