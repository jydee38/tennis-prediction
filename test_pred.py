from python.app_logic import predict_match_outcome, get_data_and_train_model, find_player_by_name
import pandas as pd

print("Loading data...")
df, model, features, db = get_data_and_train_model(tour="ATP")

row = {
    'player_1': "Hijikata R.", 'player_2': "Tiafoe F.",
    'Name_1': "Hijikata R.", 'Name_2': "Tiafoe F.",
    'tournament': "Stuttgart",
    'tournament_surface': "Grass",
    'tournament_level': "M",
    'round': 'R32',
    'best_of': 3
}

try:
    print("Predicting...")
    prob_1, prob_2, enrich_1, enrich_2, _ = predict_match_outcome(
        model, row, features, db, "Hijikata R.", "Tiafoe F.",
        tournament_name="Stuttgart", skip_te_scrape=True, te_p1=None, te_p2=None
    )
    print(f"Prob 1: {prob_1}, Prob 2: {prob_2}")
except Exception as e:
    import traceback
    traceback.print_exc()
