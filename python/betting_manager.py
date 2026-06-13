import json
import os
import re
from datetime import datetime

PREDICTIONS_FILE = "data/predictions.json"

def load_predictions():
    if not os.path.exists(PREDICTIONS_FILE):
        return []
    try:
        with open(PREDICTIONS_FILE, "r", encoding="utf-8") as f:
            preds = json.load(f)
            
            # DÉDOUPLONNAGE ET NORMALISATION
            unique_preds = {}
            # On trie par timestamp pour traiter les plus anciens en premier
            preds.sort(key=lambda x: x.get('timestamp', ''))
            
            for p in preds:
                p1 = p.get('player_1', '')
                p2 = p.get('player_2', '')
                tourn = p.get('tournament', 'Unknown')
                pick_str = str(p.get('pick', ''))
                
                # Détection du type de pari
                bet_type = "OU" if ("_OU" in str(p.get('id', '')) or "Over" in pick_str or "Under" in pick_str) else "Value"

                # Conserver l'ID existant ou le générer
                if not p.get('id'):
                    p['id'] = get_prediction_id(p1, p2, tourn, bet_type)
                new_id = p['id']
                if new_id not in unique_preds:
                    unique_preds[new_id] = p
                else:
                    existing = unique_preds[new_id]
                    # Determine best entry based on status rank then profit then timestamp
                    status_rank = {'won': 3, 'pending': 2, 'lost': 1}
                    existing_rank = status_rank.get(existing.get('status'), 0)
                    new_rank = status_rank.get(p.get('status'), 0)
                    if new_rank > existing_rank:
                        unique_preds[new_id] = p
                    elif new_rank == existing_rank:
                        if p.get('profit', 0) > existing.get('profit', 0):
                            unique_preds[new_id] = p
                        elif p.get('profit', 0) == existing.get('profit', 0):
                            # fallback to latest timestamp
                            if p.get('timestamp', '') > existing.get('timestamp', ''):
                                unique_preds[new_id] = p
            
            # Retourner la liste triée par timestamp décroissant (plus récent en haut de l'UI)
            final_list = list(unique_preds.values())
            final_list.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
            return final_list
    except Exception as e:
        print(f"Error loading predictions: {e}")
        return []

def save_predictions(predictions):
    os.makedirs("data", exist_ok=True)
    try:
        with open(PREDICTIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(predictions, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving predictions: {e}")

def add_prediction(match_info, pick, odds, prob, stake):
    predictions = load_predictions()
    
    # Check if already exists to avoid duplicates
    match_id = match_info.get("match_id", f"{match_info['player_1']}_{match_info['player_2']}_{match_info.get('tournament', 'unknown')}")
    
    new_pred = {
        "id": match_id,
        "timestamp": datetime.now().isoformat(),
        "tournament": match_info.get("tournament", "Unknown"),
        "match": f"{match_info['player_1']} vs {match_info['player_2']}",
        "player_1": match_info['player_1'],
        "player_2": match_info['player_2'],
        "pick": pick,
        "odds": odds,
        "prob_ia": prob,
        "stake": stake,
        "status": "pending",
        "result_score": None,
        "profit": 0
    }
    
    # Update if exists, else append
    for i, p in enumerate(predictions):
        if p["id"] == match_id:
            predictions[i] = new_pred
            save_predictions(predictions)
            return
            
    predictions.append(new_pred)
    save_predictions(predictions)

def delete_prediction(match_id):
    """Supprime un pronostic du fichier JSON."""
    try:
        predictions = load_predictions()
        print(f"🗑️ Tentative de suppression de : {match_id}")
        # On filtre pour exclure celui qu'on veut supprimer
        filtered = [p for p in predictions if p.get("id") != match_id]
        if len(filtered) < len(predictions):
            save_predictions(filtered)
            print(f"✅ Suppression réussie dans le fichier. {len(predictions) - len(filtered)} entrées retirées.")
            return True
        
        print(f"❌ Échec suppression : ID '{match_id}' non trouvé.")
        return False
    except Exception as e:
        print(f"🔥 Erreur critique lors de la suppression : {e}")
        return False

def normalize_name(name):
    if not isinstance(name, str):
        return ""
    # Remove dots, underscores, hyphens, spaces and lowercase
    return name.lower().replace(".", "").replace("_", "").replace(" ", "").replace("-", "").strip()

def get_prediction_id(p1, p2, tournament, bet_type="Value"):
    """Génère un ID unique et normalisé pour un match et un type de pari."""
    n1 = normalize_name(p1)
    n2 = normalize_name(p2)
    p_names = sorted([n1, n2])
    
    # Tournament normalization: remove emojis, year and markers
    t_norm = str(tournament).lower()
    # Remove emojis and special chars
    t_norm = re.sub(r'[^\w\s]', '', t_norm)
    # Remove markers
    for word in ["en cours", "ongoing", "atp", "wta", "masters", "open"]:
        t_norm = t_norm.replace(word, "")
    # Remove years (4 digits)
    t_norm = re.sub(r'\d{4}', '', t_norm)
    # Final cleanup: keep only a-z
    t_norm = re.sub(r'[^a-z]', '', t_norm).strip()
    
    if not t_norm: t_norm = "unknown"
    
    return f"{p_names[0]}_{p_names[1]}_{t_norm}_{bet_type}"


def _try_resolve_from_livescore(predictions):
    """
    Fallback: pour chaque pari encore 'pending', tente de trouver
    le résultat directement depuis l'API LiveScore (3 derniers jours).
    Retourne True si au moins un pari a été mis à jour.
    """
    import requests
    import re as _re
    from datetime import datetime, timedelta

    headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}
    updated = False
    pending = [p for p in predictions if p.get('status') == 'pending']
    if not pending:
        return False

    def _tennis_name_match(n1, n2):
        n1 = _re.sub(r'\(\d+\)', '', str(n1))
        n2 = _re.sub(r'\(\d+\)', '', str(n2))
        words1 = [w.lower() for w in _re.findall(r'[a-zA-Z]{3,}', n1)]
        words2 = [w.lower() for w in _re.findall(r'[a-zA-Z]{3,}', n2)]
        for w1 in words1:
            if w1 in words2:
                return True
        return False

    for days_ago in range(0, 5):
        if not any(p.get('status') == 'pending' for p in predictions):
            break
        date_str = (datetime.now() - timedelta(days=days_ago)).strftime("%Y%m%d")
        url = f"https://prod-public-api.livescore.com/v1/api/app/date/tennis/{date_str}/0?MD=1"
        print(f"\n[API Livescore] Commande DOS pour tester :\ncurl.exe -X GET \"{url}\" -H \"User-Agent: Mozilla/5.0\"\n")
        try:
            data = requests.get(url, headers=headers, timeout=8).json()
        except Exception:
            continue

        for stage in data.get('Stages', []):
            for event in stage.get('Events', []):
                if event.get('Eps') not in ['FT', 'AOT', 'Ret.', 'WO']:
                    continue
                api_p1 = event.get('T1', [{}])[0].get('Nm', '')
                api_p2 = event.get('T2', [{}])[0].get('Nm', '')
                if not api_p1 or not api_p2:
                    continue
                ewt = event.get('Ewt', 0)
                if ewt not in [1, 2]:
                    continue
                api_winner = api_p1 if ewt == 1 else api_p2

                # Reconstruct score string
                score_parts = []
                for i in range(1, 6):
                    s1 = event.get(f'Tr1S{i}')
                    s2 = event.get(f'Tr2S{i}')
                    if s1 is None:
                        break
                    if ewt == 1:
                        score_parts.append(f"{s1}-{s2}")
                    else:
                        score_parts.append(f"{s2}-{s1}")
                score_str = " ".join(score_parts) if score_parts else event.get('Eps', '')

                for pred in predictions:
                    if pred.get('status') != 'pending':
                        continue
                    pp1 = pred.get('player_1', '').replace('.', ' ')
                    pp2 = pred.get('player_2', '').replace('.', ' ')
                    match_found = (
                        (_tennis_name_match(api_p1, pp1) and _tennis_name_match(api_p2, pp2)) or
                        (_tennis_name_match(api_p1, pp2) and _tennis_name_match(api_p2, pp1))
                    )
                    if match_found:
                        pick = pred.get('pick', '')
                        won = False
                        
                        # Handle Over/Under
                        threshold, mode = parse_ou_threshold(pick)
                        if threshold is not None:
                            total_games = parse_total_games(score_str)
                            if mode == "Over":
                                won = total_games > threshold
                            else:
                                won = total_games < threshold
                        else:
                            # Handle Winner pick
                            pick_clean = pick.replace('.', ' ')
                            won = _tennis_name_match(api_winner, pick_clean)
                        
                        pred['result_score'] = score_str
                        pred['status'] = 'won' if won else 'lost'
                        pred['profit'] = pred['stake'] * (pred['odds'] - 1) if won else -pred['stake']
                        print(f"[LiveScore] {pred.get('match')} => {'WON' if won else 'LOST'} ({score_str})")
                        updated = True
                        break
    return updated

def parse_total_games(score_str):
    if not score_str or not isinstance(score_str, str):
        return 0
    import re
    # Remove tiebreak info like (4)
    clean_score = re.sub(r'\(\d+\)', '', score_str)
    # Find all sequences of digits
    parts = re.findall(r'\d+', clean_score)
    total = 0
    for p in parts:
        # Heuristic: if we have something like "76", and it's from the old bad format
        # where s1 and s2 were concatenated, we split it.
        # Tennis sets usually don't go above 7 games unless it's a long set or tiebreak.
        # But if it's "10", "12", etc., it's one number.
        if len(p) == 2 and int(p[0]) <= 7 and int(p[1]) <= 7 and int(p) > 13:
            total += int(p[0]) + int(p[1])
        else:
            total += int(p)
    return total

def parse_ou_threshold(pick_str):
    if not pick_str or not isinstance(pick_str, str):
        return None, None
    import re
    match = re.search(r'Over\s+([\d.]+)', pick_str, re.IGNORECASE)
    if match:
        return float(match.group(1)), "Over"
    match = re.search(r'Under\s+([\d.]+)', pick_str, re.IGNORECASE)
    if match:
        return float(match.group(1)), "Under"
    return None, None

def update_predictions_status(data_df):
    """
    Compares pending predictions with data_df to see if results are available.
    """
    import pandas as pd
    if data_df is None or data_df.empty:
        return
        
    predictions = load_predictions()
    updated = False
    
    # Create normalized columns for faster lookup
    df_copy = data_df.copy()
    df_copy["norm_1"] = df_copy["Name_1"].apply(normalize_name)
    df_copy["norm_2"] = df_copy["Name_2"].apply(normalize_name)
    
    for p in predictions:
        # Respect manual override: once a user sets a result, don't auto-change it
        if p.get("manual_override"):
            continue

        if p["status"] == "pending":
            # Normalize prediction names
            n1_p = normalize_name(p.get("player_1", ""))
            n2_p = normalize_name(p.get("player_2", ""))
            n1 = n1_p
            n2 = n2_p
            
            # Try to find the match
            mask = (
                ((df_copy["norm_1"] == n1) & (df_copy["norm_2"] == n2)) |
                ((df_copy["norm_1"] == n2) & (df_copy["norm_2"] == n1))
            )
            
        # Fallback: if exact match fails, try partial match (e.g. "Tien" vs "Learner Tien")
            if not df_copy[mask].any().any():
                mask = (
                    (df_copy["norm_1"].str.contains(n1, na=False, regex=False) & df_copy["norm_2"].str.contains(n2, na=False, regex=False)) |
                    (df_copy["norm_1"].str.contains(n2, na=False, regex=False) & df_copy["norm_2"].str.contains(n1, na=False, regex=False))
                )
            match_rows = df_copy[mask].copy()
            if not match_rows.empty:
                # 1. Prioritize matches from the SAME tournament if available
                if "tournament" in p and p["tournament"] != "Unknown":
                    clean_tourn = p["tournament"].lower()
                    for year in ["2024", "2025", "2026"]:
                        clean_tourn = clean_tourn.replace(year, "").strip()
                    clean_tourn = clean_tourn.replace("atp", "").replace("wta", "").strip()
                    
                    if clean_tourn:
                        tourn_mask = match_rows["tournament"].str.contains(clean_tourn, case=False, na=False, regex=False)
                        if tourn_mask.any():
                            match_rows = match_rows[tourn_mask]
                        else:
                            # The match in this specific tournament hasn't been found
                            continue
                
                if match_rows.empty:
                    continue

                # 2. Prioritize finished matches over 'Upcoming'
                match_rows = match_rows.copy()
                match_rows['is_upcoming'] = match_rows.get('score', '') == 'Upcoming'
                
                sort_cols = ['is_upcoming']
                sort_asc = [True]
                
                # 3. Sort by date to get the most recent one
                if "tourney_date" in match_rows.columns:
                    sort_cols.append("tourney_date")
                    sort_asc.append(False)
                elif "tournament_date" in match_rows.columns:
                    sort_cols.append("tournament_date")
                    sort_asc.append(False)
                    
                match_rows = match_rows.sort_values(sort_cols, ascending=sort_asc)
                
                # Get the most relevant row
                row = match_rows.iloc[0]
                score = row.get("score", "")
                
                if score and score != "Upcoming" and not pd.isna(score):
                    # Match is finished
                    winner_name = None
                    pick = p.get("pick", "")
                    p["result_score"] = score
                    
                    # Handle Over/Under
                    threshold, mode = parse_ou_threshold(pick)
                    if threshold is not None:
                        total_games = parse_total_games(score)
                        if mode == "Over":
                            won = total_games > threshold
                        else:
                            won = total_games < threshold
                    else:
                        # Handle Winner pick
                        p1_norm = normalize_name(row["Name_1"])
                        p2_norm = normalize_name(row["Name_2"])
                        winner_norm = p1_norm if row.get("Winner") == 0 else p2_norm
                        pick_norm = normalize_name(pick)
                        won = (winner_norm == pick_norm)
                    
                    if won:
                        p["status"] = "won"
                        p["profit"] = p["stake"] * (p["odds"] - 1)
                    else:
                        p["status"] = "lost"
                        p["profit"] = -p["stake"]
                    updated = True
    
    # Fallback: resolve remaining 'pending' bets directly from LiveScore API
    # This catches matches that data_df missed (name format mismatches, hyphenated names, etc.)
    try:
        livescore_updated = _try_resolve_from_livescore(predictions)
        updated = updated or livescore_updated
    except Exception as e_ls:
        print(f"[LiveScore fallback error] {e_ls}")

    if updated:
        save_predictions(predictions)

def calculate_stats(stake_default=10):
    predictions = load_predictions()
    total_profit = sum(p["profit"] for p in predictions)
    total_stake = sum(p["stake"] for p in predictions)
    total_bets = len(predictions)
    won_bets = len([p for p in predictions if p["status"] == "won"])
    lost_bets = len([p for p in predictions if p["status"] == "lost"])
    pending_bets = len([p for p in predictions if p["status"] == "pending"])

    return {
        "total_profit": total_profit,
        "total_stake": total_stake,
        "total_bets": total_bets,
        "won_bets": won_bets,
        "lost_bets": lost_bets,
        "pending_bets": pending_bets,
        "predictions": predictions
    }
