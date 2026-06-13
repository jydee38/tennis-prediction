import pandas as pd
from python.app_logic import get_data_and_train_model
data_df, _, _, _, _, _, _, _ = get_data_and_train_model()
print("Columns:", data_df.columns.tolist()[:15])
m = data_df[(data_df['winner_name'].str.contains('Zverev', na=False)) | (data_df['loser_name'].str.contains('Zverev', na=False))]
print(f"Zverev matches found: {len(m)}")
if len(m) > 0:
    print(m.sort_values('tournament_date').iloc[-1][['tournament_date', 'tournament', 'winner_name', 'loser_name', 'score', 'minutes']])
