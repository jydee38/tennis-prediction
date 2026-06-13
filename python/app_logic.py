import sys
import os
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

# Setup path so we can import from data
from python.data.data_loader import matches_data_loader, encode_data
from python.data.tennisexplorer_scraper import scrape_player_te_stats
from python.data.enrichment import analyze_elite_resistance, analyze_salmon_factor
from python.data.sportradar_scraper import get_fishnet_token, fetch_player_season_stats
from python.data.odds_api import get_all_tennis_data, match_odds


import subprocess
try:
    from mistralai import Mistral
except ImportError:
    Mistral = None

# --- CONFIGURATION MISTRAL ---
API_KEYS = [
    "noyn7OfOeoq2ND9WhYsCmsOfoUTsaHQt",
    "7yCUUUSu9f977WFqP303HP87cft3C3BN"
]
CHOSEN_MODEL = 'mistral-large-latest'

def configurer_mistral(api_key):
    """Configure l'API Mistral avec la clé fournie"""
    from mistralai import Mistral
    return Mistral(api_key=api_key)

def find_player_by_name(name, players_db):
    """
    Recherche robuste d'un joueur par son nom dans la base de données.
    
    Gère tous les formats de noms des bookmakers/API :
      - "Shelton B.(1)"        → Benjamin Shelton
      - "Auger Aliassime F.(6)"→ Felix Auger-Aliassime
      - "Medvedev D."          → Daniil Medvedev
      - "Chwalinska.Maja"      → Maja Chwalinska
      - "Mpetshi Perricard G." → Giovanni Mpetshi Perricard
    
    La base de données passée en paramètre DOIT déjà être filtrée par genre
    (players_db_atp ou players_db_wta) pour éviter toute confusion frère/sœur.
    """
    if not players_db or not name:
        return None

    import re
    import unicodedata

    def normalize(s):
        """Normalise un nom : enlève accents, ponctuation parasite, séparateurs."""
        s = str(s)
        # Enlever les seeds type "(4)", "(WC)", "(PR)", "(LL)", "(Q)"
        s = re.sub(r'\s*\([^)]*\)\s*', ' ', s)
        # Enlever les emojis et caractères non-ascii non-latins
        s = re.sub(r'[^\w\s\-\']', ' ', s)
        # Normaliser les tirets et apostrophes composés
        s = s.replace('-', ' ').replace('_', ' ').replace('.', ' ')
        # Supprimer les accents (é → e, ü → u, ñ → n, etc.)
        s = ''.join(
            c for c in unicodedata.normalize('NFD', s)
            if unicodedata.category(c) != 'Mn'
        )
        return s.lower().strip()

    def get_words(s, min_len=2):
        """Retourne les mots significatifs d'un nom normalisé."""
        return [w for w in normalize(s).split() if len(w) >= min_len]

    def is_initial(w):
        """Retourne True si le mot est une initiale (1 lettre)."""
        return len(w) == 1

    target_norm = normalize(name)
    # IMPORTANT : min_len=1 pour conserver les initiales comme "G" dans "Mpetshi Perricard G."
    target_words = get_words(name, min_len=1)

    if not target_words:
        return None

    # --- ÉTAPE 1 : Correspondance exacte après normalisation ---
    for p_obj in players_db.values():
        if normalize(p_obj.name) == target_norm:
            return p_obj

    # --- ÉTAPE 2 : Correspondance par mots triés (ordre prénom/nom inversé) ---
    target_words_sorted = sorted(target_words)
    for p_obj in players_db.values():
        db_words_sorted = sorted(get_words(p_obj.name))
        if target_words_sorted == db_words_sorted:
            return p_obj

    # Calculer non_initials et initials tôt pour pouvoir les utiliser dès l'étape 3
    non_initials = [w for w in target_words if not is_initial(w)]
    initials     = [w for w in target_words if is_initial(w)]

    # --- ÉTAPE 3 : Un nom contient l'autre (substring sur mots normalisés) ---
    # Vérifier aussi les initiales pour éviter Daphnée (D.) / Giovanni (G.)
    for p_obj in players_db.values():
        db_norm = normalize(p_obj.name)
        if target_norm in db_norm or db_norm in target_norm:
            # Validation initiale : si on a une initiale dans la cible,
            # vérifier qu'elle correspond à un mot de la DB
            if initials:
                db_words_check = get_words(p_obj.name)
                initial_ok = any(
                    dw.startswith(init) for init in initials
                    for dw in db_words_check if len(dw) > 1
                )
                if not initial_ok:
                    continue
            return p_obj


    if non_initials:
        # Chercher les joueurs dont tous les mots significatifs de la DB
        # sont présents dans les mots non-initiaux de la cible
        candidates = []
        for p_obj in players_db.values():
            db_words = get_words(p_obj.name)
            db_non_initials = [w for w in db_words if not is_initial(w)]
            if not db_non_initials:
                continue

            # Compter combien de mots de la DB correspondent aux mots cibles
            matched = sum(1 for w in db_non_initials if w in non_initials)
            total   = len(db_non_initials)

            if total > 0 and matched == total:
                # Si on a une initiale dans la cible, vérifier qu'elle correspond
                # au prénom du joueur dans la DB (évite les homonymes)
                if initials:
                    db_first_words = db_words  # tous les mots du nom complet
                    # L'initiale doit correspondre à AU MOINS un mot dans la DB
                    initial_ok = any(
                        dw.startswith(init) for init in initials
                        for dw in db_first_words
                        if not is_initial(dw)
                    )
                    score = matched + (1.0 if initial_ok else 0.0)
                    candidates.append((score, p_obj))
                else:
                    candidates.append((float(matched), p_obj))

        if candidates:
            # Prendre le candidat avec le meilleur score, favoriser l'initiale correspondante
            candidates.sort(key=lambda x: x[0], reverse=True)
            # Si on a des initiales et que le meilleur candidat n'a pas l'initiale validée,
            # c'est probablement un faux positif → on rejette
            if initials and candidates[0][0] == float(int(candidates[0][0])):
                # score entier = pas d'initiale validée → rejeter si on avait une initiale
                pass  # on laisse tomber, on ira au fallback
            else:
                return candidates[0][1]

    # --- ÉTAPE 5 : Fallback par le nom de famille seul (dernier mot long) ---
    # Uniquement si le mot fait plus de 4 lettres pour éviter les faux positifs
    long_words = [w for w in non_initials if len(w) >= 4]
    if long_words:
        # Prendre le mot le plus long comme "nom de famille probable"
        longest = max(long_words, key=len)
        best_match = None
        best_score = 0
        for p_obj in players_db.values():
            db_words = get_words(p_obj.name)
            if longest in db_words:
                # Scorer par nombre de mots en commun (pour éviter les homonymes courts)
                shared = sum(1 for w in non_initials if w in db_words)
                
                # CRITIQUE : si on a une initiale, vérifier qu'elle correspond
                # Sinon on risque de confondre Giovanni (G.) avec Daphnée (D.)
                if initials:
                    initial_ok = any(
                        dw.startswith(init) for init in initials
                        for dw in db_words if len(dw) > 1
                    )
                    if not initial_ok:
                        continue  # Refuser ce candidat si l'initiale ne match pas
                
                if shared > best_score:
                    best_score = shared
                    best_match = p_obj
        if best_match:
            return best_match

    return None



def get_data_and_train_model(progress_callback=None, force_update=False, tour="ATP", reload_from_csv=False, skip_training=False):
    import time
    
    # If the cached files are missing or too old, we scrape.
    # By default, we rely on the cached scraped files.
    needs_scraping = force_update
    
    suffix = "_wta" if tour == "WTA" else ""
    scraped_matches_path = f"data/scraped_matches{suffix}.csv"
    if not os.path.exists(scraped_matches_path) or not os.path.exists(f"data/scraped_players{suffix}.csv"):
        needs_scraping = True
    else:
        # If file is older than 2 hours (7200 seconds), update it
        file_age = time.time() - os.path.getmtime(scraped_matches_path)
        if file_age > 7200:
            needs_scraping = True    # Mise à jour automatique au démarrage
            
    # Mise à jour automatique au démarrage
    # 1. Calendrier (toujours car rapide et critique pour le point rouge)
    try:
        from python.data.schedule_scraper import scrape_match_schedule
        if progress_callback:
            progress_callback(f"Actualisation du calendrier {tour}...")
        scrape_match_schedule(output_dir="data")
    except Exception as e:
        print(f"Erreur calendrier démarrage: {e}")

    # 1.5 Toujours synchroniser LiveScore au démarrage pour mettre à jour les paris en attente (Bilan propre)
    try:
        if progress_callback:
            progress_callback(f"Synchronisation des résultats en direct {tour}...")
        from python.data.livescore_scraper import sync_livescore_to_csv
        sync_livescore_to_csv(output_dir="data", tour=tour)
    except Exception as e_ls_sync:
        print(f"Erreur LiveScore sync démarrage: {e_ls_sync}")

    # 2. Résultats récents (si nécessaire > 2h)
    if needs_scraping:
        try:
            from python.data.recent_scraper import scrape_recent_matches, scrape_current_tournaments
            if progress_callback:
                progress_callback(f"Mise à jour des résultats {tour} récents...")
            scrape_recent_matches(output_dir="data", tour=tour)
            scrape_current_tournaments(output_dir="data", tour=tour)
            
            # Sync scores from Odds API as backup
            from python.data.odds_api import get_all_tennis_data, sync_odds_scores_to_csv
            odds_data = get_all_tennis_data(force_update=force_update)
            sync_odds_scores_to_csv(odds_data.get("scores", []), output_dir="data", tour=tour)

            # Sync scores from LiveScore API for real-time results (fixes "pending" bilans)
            try:
                from python.data.livescore_scraper import fetch_upcoming_from_livescore
                # On force à 0 pour ne prendre que les matchs d'Aujourd'hui (pas ceux de demain)
                fetch_upcoming_from_livescore(output_dir="data", tour=tour, days_ahead=0)
            except Exception as e_ls:
                print(f"Erreur LiveScore scraper: {e_ls}")

            from python.data.charting_loader import update_charting_data
            update_charting_data()
        except Exception as e:
            print(f"Erreur résultats démarrage: {e}")
    else:
        if progress_callback:
            progress_callback(f"Données {tour} à jour (cache local).")

    if progress_callback:
        progress_callback("Analyse des matchs et calcul des variables...")
        
    os.makedirs("cache", exist_ok=True)
    
    data_df, players_db = matches_data_loader(
        path_to_data="data",
        path_to_cache="cache",
        flush_cache=force_update or reload_from_csv,  # Flush if requested or if we force update
        keep_values_from_year=2024,
        get_match_statistics=True,
        get_reversed_match_data=True,
        progress_callback=progress_callback,
        tour=tour
    )
    
    # Define columns exactly as in train_test.py
    columns_m = ["tournament", "tournament_surface", "tournament_level", "tournament_date", "round", "best_of", "Winner"]
    columns_1 = [
        "ID_1", "Ranking_1", "Ranking_Points_1", "Hand_1", "Height_1", "Versus_1",
        "Victories_Percentage_1", "Clay_Victories_Percentage_1", "Grass_Victories_Percentage_1",
        "Hard_Victories_Percentage_1", "Aces_Percentage_1",
        "Doublefaults_Percentage_1", "First_Serve_Success_Percentage_1", "Winning_on_1st_Serve_Percentage_1",
        "Winning_on_2nd_Serve_Percentage_1", "Overall_Win_on_Serve_Percentage_1", "BreakPoint_Face_Percentage_1",
        "BreakPoint_Saved_Percentage_1", "minutes_fatigue_1", "endurance_win_percentage_1", "current_win_streak_1",
        "charted_matches_1", "avg_winners_fh_1", "avg_winners_bh_1", "avg_unforced_fh_1", "avg_unforced_bh_1", 
        "winner_unforced_ratio_1", "return_pts_won_pct_1"
    ]
    columns_2 = [
        "ID_2", "Ranking_2", "Ranking_Points_2", "Hand_2", "Height_2", "Versus_2",
        "Victories_Percentage_2", "Clay_Victories_Percentage_2", "Grass_Victories_Percentage_2",
        "Hard_Victories_Percentage_2", "Aces_Percentage_2",
        "Doublefaults_Percentage_2", "First_Serve_Success_Percentage_2", "Winning_on_1st_Serve_Percentage_2",
        "Winning_on_2nd_Serve_Percentage_2", "Overall_Win_on_Serve_Percentage_2", "BreakPoint_Face_Percentage_2",
        "BreakPoint_Saved_Percentage_2", "minutes_fatigue_2", "endurance_win_percentage_2", "current_win_streak_2",
        "charted_matches_2", "avg_winners_fh_2", "avg_winners_bh_2", "avg_unforced_fh_2", "avg_unforced_bh_2", 
        "winner_unforced_ratio_2", "return_pts_won_pct_2"
    ]
    
    # We add names for the GUI display
    extra_cols = ["Name_1", "Name_2", "tournament_year", "match_id", "score", "w_ace", "l_ace"]
    
    # Filter available columns just in case
    available_cols = [c for c in columns_m + columns_1 + columns_2 + extra_cols if c in data_df.columns]
    
    # IMPORTANT: We no longer dropna(axis=0) here because it kills all recent matches 
    # that don't have advanced charting stats (MCP). We only prune for training later.
    data_df = data_df[available_cols].copy()
    data_df = data_df.fillna(0) # Fill NaNs for the GUI display too
    
    if progress_callback:
        progress_callback(f"Données chargées : {len(data_df)} matchs trouvés. Préparation des données...")
    
    # Add surface-specific win percentages as features
    def get_surf_pct(row, p_num):
        surf = str(row["tournament_surface"]).capitalize()
        # Fallback to general win pct if surface specific not available
        col = f"{surf}_Victories_Percentage_{p_num}"
        return row.get(col, row.get(f"Victories_Percentage_{p_num}", 50.0))

    data_df["surface_win_pct_1"] = data_df.apply(lambda r: get_surf_pct(r, 1), axis=1)
    data_df["surface_win_pct_2"] = data_df.apply(lambda r: get_surf_pct(r, 2), axis=1)

    if skip_training:
        if progress_callback:
            progress_callback("Prêt (stats mises à jour) !")
        return data_df, None, [], players_db

    # Prepare data for training
    # fdf contains all matches (including Upcoming) for feature engineering
    fdf = encode_data(data_df.copy())
    
    fdf = fdf.drop(["ID_1", "Versus_1", "ID_2", "Versus_2"], axis=1, errors='ignore')
    if "Ranking_1" in fdf.columns and "Ranking_2" in fdf.columns:
        fdf["diff_ranking"] = fdf["Ranking_2"] - fdf["Ranking_1"]
        
    # Fill NaNs with 0 for features to avoid crashing the model (important for recent matches)
    fdf = fdf.fillna(0)
    
    # Define features for training
    features = ["diff_ranking", "tournament_surface", "surface_win_pct_1", "surface_win_pct_2",
                "endurance_win_percentage_1", "endurance_win_percentage_2", 
                "current_win_streak_1", "current_win_streak_2", "minutes_fatigue_1", "minutes_fatigue_2",
                "winner_unforced_ratio_1", "winner_unforced_ratio_2", "return_pts_won_pct_1", "return_pts_won_pct_2",
                "avg_winners_fh_1", "avg_winners_fh_2", "avg_unforced_fh_1", "avg_unforced_fh_2"]
    
    existing_features = [f for f in features if f in fdf.columns]

    # Filter out "Upcoming" matches ONLY for the training set (they have no label 'Winner')
    train_df = fdf[fdf["score"] != "Upcoming"].copy()
    
    X = train_df[existing_features].values
    y = train_df.Winner
    
    if progress_callback:
        progress_callback("Entraînement de l'intelligence artificielle (Random Forest)...")
    
    # On utilise 100 arbres et une profondeur de 12 pour mieux capturer les complexités (features MCP)
    model = RandomForestClassifier(n_estimators=100, max_depth=12, random_state=42)
    print("Training model with features:", existing_features)
    model.fit(X, y)
    
    if progress_callback:
        progress_callback("Prêt !")
        
    return data_df, model, existing_features, players_db

def get_recent_tournaments(df, lang="FR"):
    if "tournament" not in df.columns:
        return []

    import datetime
    import re
    import json
    
    # Load match schedules
    schedule_tours = set()
    schedule_path = os.path.join("data", "match_schedule.json")
    if os.path.exists(schedule_path):
        try:
            with open(schedule_path, "r", encoding="utf-8") as f:
                s_data = json.load(f)
                for m_item in s_data.values():
                    t_name = m_item.get("tournament", "")
                    if t_name and "challenger" not in t_name.lower():
                        schedule_tours.add(t_name.lower())
        except: pass

    date_col = "tournament_date" if "tournament_date" in df.columns else "tournament_year"
    year_col = "tournament_year" if "tournament_year" in df.columns else None
    has_score = "score" in df.columns
    
    group_cols = ["tournament"]
    if year_col:
        group_cols.append(year_col)

    records = []
    for keys, g in df.groupby(group_cols):
        t_name = keys[0] if not isinstance(keys, str) else keys
        
        # Skip empty or invalid tournament names
        if not t_name or str(t_name).strip() in ["", "0", "nan", "None"]:
            continue
        
        # Simple Challenger/ITF exclusion
        t_name_low = str(t_name).lower()
        if any(x in t_name_low for x in ["challenger", "itf", "futures", "juniors"]):
            continue
            
        t_year = keys[1] if year_col and not isinstance(keys, str) else (g[date_col].max() if date_col in g.columns else 0)
        
        # Skip invalid years (0, NaN, etc.)
        try:
            t_year_int = int(float(str(t_year)))
            if t_year_int < 2000 or t_year_int > 2030:
                continue
        except:
            continue
            
        max_date = str(g[date_col].max()) if date_col in g.columns else str(t_year)
        
        # A tournament is ongoing if it has 'Upcoming' matches in CSV OR if it's in the live schedule
        is_ongoing = (has_score and (g["score"] == "Upcoming").any())
        
        # Heuristic: if the Final (round 'F') has been played, it's not ongoing
        if is_ongoing and "round" in g.columns:
            has_final_played = ((g["round"] == "F") & (g["score"] != "Upcoming") & (g["score"].notna())).any()
            if has_final_played:
                is_ongoing = False
                
        if not is_ongoing:
            # Fuzzy match with schedule
            for st in schedule_tours:
                if st in t_name_low or t_name_low in st:
                    is_ongoing = True
                    break

        # Force non-ongoing if tournament started in the past and is not in the schedule anymore
        if is_ongoing and len(max_date) == 8:
            try:
                t_date = datetime.date(int(max_date[:4]), int(max_date[4:6]), int(max_date[6:8]))
                age_days = (datetime.date.today() - t_date).days
                if age_days >= 3 and len(schedule_tours) > 0:
                    has_live = False
                    for st in schedule_tours:
                        if st in t_name_low or t_name_low in st:
                            has_live = True
                            break
                    if not has_live:
                        is_ongoing = False
            except:
                pass
                
        # Fallback: Force ongoing if the tournament has matches in the last 2 days 
        # (Very useful for qualification tournaments that schedule_scraper might miss)
        if not is_ongoing and len(max_date) == 8:
            try:
                t_date = datetime.date(int(max_date[:4]), int(max_date[4:6]), int(max_date[6:8]))
                age_days = (datetime.date.today() - t_date).days
                if age_days <= 2:
                    is_ongoing = True
            except:
                pass

        records.append({
            "name": t_name,
            "year": t_year_int,
            "max_date": max_date,
            "is_ongoing": is_ongoing
        })

    # ---- DEDUPLICATION: merge tournaments with same year and overlapping names ----
    import re as _re2
    def tourney_keywords(name):
        s = _re2.sub(r"[^a-z0-9 ]", " ", str(name).lower())
        # Normalisation des grands tournois pour fusionner les appellations différentes
        if any(x in s for x in ["rome", "internazionali", "bnl", "italia"]):
            s += " rome"
        if any(x in s for x in ["madrid", "mutua"]):
            s += " madrid"
        if any(x in s for x in ["roland", "garros", "french"]):
            s += " paris roland"
            
        s = _re2.sub(r"\b(atp|wta|open|2026|2025|2024|challenger)\b", " ", s)
        return set(w for w in s.split() if len(w) >= 3)

    deduped = []
    used_indices = set()
    # Sort by count of rows (more data = preferred name)
    records_with_count = []
    for i, r in enumerate(records):
        t = r["name"]
        yr = r["year"]
        try:
            if year_col:
                cnt = len(df[(df["tournament"] == t) & (df[year_col].astype(float).astype(int) == yr)])
            else:
                cnt = len(df[df["tournament"] == t])
        except Exception:
            cnt = 1
        records_with_count.append((i, r, cnt))

    records_with_count.sort(key=lambda x: x[2], reverse=True)

    final_records = []
    absorbed_keys = set()

    for i, r, cnt in records_with_count:
        kw = tourney_keywords(r["name"])
        key = (r["year"], frozenset(kw))
        skip = False
        for ak in absorbed_keys:
            ak_year, ak_kw = ak
            if ak_year == r["year"] and len(kw & ak_kw) >= 1:
                skip = True
                break
        if not skip:
            final_records.append(r)
            absorbed_keys.add((r["year"], frozenset(kw)))

    records = final_records
    # ---- END DEDUPLICATION ----

    # Sort: ongoing first, then by most recent date
    records.sort(key=lambda r: r["max_date"], reverse=True)

    tournaments = []
    for r in records:
        label = f"{r['name']} ({r['year']})"
        if r["is_ongoing"]:
            if lang.upper() == "EN":
                label = f"🔴 Ongoing: {r['name']} ({r['year']})"
            else:
                label = f"🔴 En cours : {r['name']} ({r['year']})"
        tournaments.append(label)

    return tournaments

def _fetch_livescore_upcoming_for_tournament(tournament_name_with_year, t_year, tour="ATP", days_ahead=0):
    """
    Queries LiveScore API directly for upcoming (NS) matches for today + N days.
    Returns a list of dicts with keys: player_1, player_2, round, time, full_time.
    Matches are filtered to the given tournament by fuzzy name matching.
    """
    import re as _re
    import requests
    from datetime import datetime, timedelta

    def norm(n): return _re.sub(r'[^a-z0-9]', '', str(n).lower())

    # Build tournament keywords for fuzzy matching
    t_clean = tournament_name_with_year.lower()
    t_clean = t_clean.replace("🔴 en cours : ", "").replace("🔴 ongoing: ", "").strip()
    t_clean = _re.sub(r"\(\d{4}\)", "", t_clean)
    t_clean = _re.sub(r"[()'\'']", " ", t_clean).strip()
    t_words = set(w for w in t_clean.split() if len(w) >= 4)

    def ls_tour_matches(snm):
        s = _re.sub(r"[()'\'']", " ", snm.lower())
        
        # Gender mismatch check
        is_t_women = "women" in t_clean or "wta" in t_clean
        is_s_women = "women" in s or "wta" in s
        if is_t_women != is_s_women:
            return False
            
        is_t_men = "men" in t_clean or "atp" in t_clean
        is_s_men = "men" in s or "atp" in s
        if is_t_men != is_s_men:
            return False

        s_words = set(w for w in s.split() if len(w) >= 3) # Lower min length
        # Hardcoded aliases for major tournaments
        aliases = {
            "rome": ["internazionali", "italia", "italy", "bnl"],
            "madrid": ["mutua"],
            "roland garros": ["french", "paris"],
            "wimbledon": ["london"],
            "us open": ["new york"],
            "australian open": ["melbourne"]
        }
        # Check if any word matches or any alias matches
        if bool(t_words & s_words): return True
        if any(w in s for w in t_words): return True
        for tw in t_words:
            if tw in aliases:
                if any(alt in s for alt in aliases[tw]):
                    return True
        return False

    results = []
    seen = set()

    for days_offset in range(0, days_ahead + 1):
        date_str = (datetime.now() + timedelta(days=days_offset)).strftime("%Y%m%d")
        url = f"https://prod-public-api.livescore.com/v1/api/app/date/tennis/{date_str}/0?MD=1"
        try:
            res = requests.get(url, timeout=8)
            if res.status_code != 200:
                continue
            data = res.json()
        except Exception as e:
            print(f"[LiveScore upcoming] Error {date_str}: {e}")
            continue

        for stage in data.get('Stages', []):
            cnm = stage.get("Cnm", "")
            snm = stage.get("Snm", "")
            if "CHALLENGER" in cnm.upper() or "ITF" in cnm.upper():
                continue
            
            from python.data.livescore_scraper import should_skip_stage
            if should_skip_stage(cnm, snm, tour):
                continue

            snm = stage.get('Snm', '')
            if not ls_tour_matches(snm):
                continue

            if "DOUBLE" in cnm or "DOUBLES" in snm.upper():
                continue

            for event in stage.get('Events', []):
                eps = event.get('Eps', '')
                if eps not in ['NS', '']:
                    continue

                t1_list = event.get('T1', [])
                t2_list = event.get('T2', [])

                if len(t1_list) != 1 or len(t2_list) != 1:
                    continue

                p1 = t1_list[0].get('Nm', '')
                p2 = t2_list[0].get('Nm', '')
                if not p1 or not p2:
                    continue

                match_key = "-".join(sorted([norm(p1), norm(p2)]))
                if match_key in seen:
                    continue
                seen.add(match_key)

                start_time = event.get('Esd', '')
                time_str = ""
                full_time_str = ""
                if start_time:
                    try:
                        from datetime import datetime as _dt
                        dt = _dt.strptime(str(start_time)[:12], "%Y%m%d%H%M")
                        time_str = dt.strftime("%H:%M")
                        full_time_str = dt.strftime("%d/%m %H:%M")
                    except Exception:
                        pass

                # Round detection from ErnInf or Ernd field
                rnd_str = event.get('ErnInf', '')
                rnd_raw = event.get('Ernd', event.get('ErnId', 'R32'))
                rnd_map = {1: 'F', 2: 'SF', 3: 'QF', 4: 'R16', 5: 'R32', 6: 'R64', 7: 'R128'}
                
                if rnd_str:
                    rnd = rnd_str
                elif isinstance(rnd_raw, int):
                    rnd = rnd_map.get(rnd_raw, 'R32')
                else:
                    rnd = str(rnd_raw) if rnd_raw else 'R32'

                results.append({
                    "player_1": p1,
                    "player_2": p2,
                    "round": rnd,
                    "time": time_str,
                    "full_time": full_time_str,
                    "match_key": match_key,
                    "date": date_str
                })

    return results


def get_matches_for_tournament(df, tournament_name_with_year, data_dir="data", tour="ATP", skip_scrape=False):
    import re
    import json
    import os
    
    def norm(n): return re.sub(r'[^a-z0-9]', '', str(n).lower())

    if "🔴" in tournament_name_with_year and not skip_scrape:
         try:
             from python.data.livescore_scraper import sync_livescore_to_csv
             sync_livescore_to_csv(output_dir=data_dir, tour=tour, days_back=7)
         except: pass

    clean_label = tournament_name_with_year.replace("🔴 En cours : ", "").replace("🔴 Ongoing: ", "").strip()
    match = re.search(r"^(.*) \((\d{4})\)$", clean_label)
    
    import datetime
    current_year_sys = datetime.datetime.now().year

    if match:
        t_name = match.group(1).strip()
        t_year = int(match.group(2))
        tour_df = df[
            (df["tournament"].str.strip() == t_name) & 
            (df["tournament_year"].astype(float).astype(int) == t_year)
        ].copy()
    else:
        # Fallback if no year in parentheses: check if any 4-digit number looks like a year
        year_match = re.search(r"\b(20\d{2})\b", clean_label)
        if year_match:
            t_year = int(year_match.group(1))
            t_name = clean_label.replace(year_match.group(0), "").strip()
        else:
            t_name = clean_label
            t_year = current_year_sys
            
        tour_df = df[
            (df["tournament"].str.strip() == t_name) & 
            (df["tournament_year"].astype(float).astype(int) == t_year)
        ].copy()
        if tour_df.empty:
            tour_df = df[df["tournament"].str.strip() == clean_label].copy()
    
    if not skip_scrape:
        from python.data.schedule_scraper import scrape_match_schedule
        scrape_match_schedule(output_dir=data_dir)
    
    tour_df = tour_df.copy()
    tour_df['match_key'] = tour_df.apply(lambda r: "-".join(sorted([str(r.get('Name_1','')).strip(), str(r.get('Name_2','')).strip()])), axis=1)
    tour_df = tour_df.drop_duplicates(subset=["round", "match_key"])
    
    round_map = {
        "F": 10, "FINAL": 10, "FINALE": 10,
        "SF": 9, "DF": 9, "DEMI": 9,
        "QF": 8, "QUART": 8, "R8": 8,
        "R16": 7, "HUIT": 7, "1/8": 7,
        "R32": 6, "SEIZE": 6, "1/16": 6,
        "R64": 5, "TRENTE": 5, "1/32": 5,
        "R128": 4, "SOIXANTE": 4, "1/64": 4,
        "RR": 2, "BR": 1, "Q": 0
    }
    
    round_labels = {
        10: "Finale",
        9: "Demi-finale",
        8: "Quart de finale",
        7: "8ème de finale",
        6: "16ème de finale",
        5: "32ème de finale",
        4: "64ème de finale",
        0: "Qualif."
    }
    
    def guess_round(r):
        r_up = str(r).upper().strip()
        if r_up in ["F", "FINAL", "FINALE"]: return 10
        if any(x in r_up for x in ["SF", "DEMI", "SEMI", "1/2"]): return 9
        if any(x in r_up for x in ["QF", "QUART", "1/4"]): return 8
        # 8ème de finale / R16
        if any(x in r_up for x in ["R16", "1/8", "8ÈME", "8EME", "8TH", "ROUND OF 16", "4TH ROUND", "ROUND 4", "HUIT"]): return 7
        # 16ème de finale / R32
        if any(x in r_up for x in ["R32", "1/16", "16ÈME", "16EME", "ROUND OF 32", "3RD ROUND", "ROUND 3", "SEIZE"]): return 6
        # 32ème de finale / R64
        if any(x in r_up for x in ["R64", "1/32", "32ÈME", "32EME", "ROUND OF 64", "2ND ROUND", "ROUND 2", "TRENTE"]): return 5
        # 64ème de finale / R128
        if any(x in r_up for x in ["R128", "1/64", "64ÈME", "64EME", "ROUND OF 128", "1ST ROUND", "ROUND 1", "SOIXANTE"]): return 4
        
        # Raccourcis stricts pour les notations courtes
        if r_up == "R8": return 8
        if r_up == "R4": return 7
        if r_up == "R3": return 6
        if r_up == "R2": return 5
        if r_up == "R1": return 4
        
        if "RR" in r_up: return 2
        if "BR" in r_up: return 1
        if "Q" in r_up: return 0
        return 4 # Valeur par défaut : 1er Tour (au lieu de 6 qui forçait les 8èmes)
        
    tour_df = tour_df.copy()
    tour_df["round_val"] = tour_df["round"].apply(guess_round)
    tour_df = tour_df.sort_values("round_val", ascending=False)

    schedule = {}
    schedule_path = os.path.join(data_dir, "match_schedule.json")
    if os.path.exists(schedule_path):
        try:
            with open(schedule_path, "r", encoding="utf-8") as f:
                schedule = json.load(f)
        except: pass

    odds_data = get_all_tennis_data()
    all_odds = odds_data.get("odds", [])

    matches = []
    processed_schedule_ids = set()
    for _, row in tour_df.iterrows():
        orig_round = str(row.get("round", "??")).upper()
        
        # Big Draw (96 or 128 players) Round Adjustment
        # Rome/Madrid (96) et Grand Chelems (128) ont 7 tours : R1=R128, R2=R64, etc.
        is_big_draw = any(kw in clean_label.upper() for kw in ["MASTERS", "ROME", "MADRID", "INDIAN WELLS", "MIAMI", "MONTE CARLO", "CINCINNATI", "TORONTO", "MONTREAL", "SHANGHAI", "PARIS", "INTERNAZIONALI", "BNL", "ITALIA", "ROLAND", "GARROS", "WIMBLEDON", "US OPEN", "AUSTRALIAN OPEN", "CHLEM"])
        if "R" in orig_round and len(orig_round) <= 3:
            num_match = re.search(r"(\d+)", orig_round)
            if num_match:
                n = int(num_match.group(1))
                if is_big_draw:
                    # 96/128-draw: R1=128, R2=64, R3=32, R4=16(8ème), R5=QF, R6=SF, R7=F
                    big_map = {1: "R128", 2: "R64", 3: "R32", 4: "R16", 5: "R8", 6: "SF", 7: "F"}
                    orig_round = big_map.get(n, orig_round)
                else:
                    std_map = {1: "R64", 2: "R32", 3: "R16", 4: "R8", 5: "QF", 6: "SF", 7: "F"}
                    orig_round = std_map.get(n, orig_round)
        
        r_val = guess_round(orig_round)
        display_round = round_labels.get(r_val, orig_round)
            
        p1 = str(row.get("Name_1", "Player 1")).replace(".", " ")
        p2 = str(row.get("Name_2", "Player 2")).replace(".", " ")

        # Identification du gagnant
        winner_idx = row.get("Winner")
        final_row = row.to_dict()

        # --- PATCH : Zverev qualifié + Correction ciblée des 8èmes ---
        if "zverev" in p1.lower() and "altmaier" in p2.lower():
            winner_idx = 0
            r_val = 5 # Force 32ème (2ème tour historique)
            final_row["score"] = "Qualifié (W/O)"
        elif "zverev" in p2.lower() and "altmaier" in p1.lower():
            winner_idx = 1
            r_val = 5 # Force 32ème (2ème tour historique)
            final_row["score"] = "Qualifié (W/O)"
        # -------------------------------------------------------------

        final_p1, final_p2 = p1, p2
        if str(winner_idx) == "1" or str(winner_idx) == "1.0":
            final_p1, final_p2 = p2, p1
            final_row["Name_1"] = p2   
            final_row["Name_2"] = p1   
            final_row["Winner"] = 0 
        elif winner_idx is None or str(winner_idx) == "" or str(winner_idx) == "nan":
            pass
        else:
            final_row["Winner"] = 0 

        # Sanitisation stricte du score : None/nan/vide => Upcoming
        raw_score = final_row.get("score", "")
        if raw_score is None or str(raw_score).strip().lower() in ["", "none", "nan"]:
            final_row["score"] = "Upcoming"

        # --- FILTRE ANTI-DOUBLES : règle du 1v1 exclusif ---
        # Règle 1 : un nom de joueur contenant / & + ou ' and ' = paire de double
        _DOUBLES_CHARS = ['/', '&', '+']
        def _is_doubles_name(n):
            return any(c in str(n) for c in _DOUBLES_CHARS) or ' and ' in str(n).lower()
        if _is_doubles_name(p1) or _is_doubles_name(p2):
            continue
        # Règle 2 : nom du tournoi contient "double"
        if 'double' in str(final_row.get('tournament', '')).lower():
            continue
        # -------------------------------------------------------

        match_id = "-".join(sorted([norm(p1), norm(p2)]))
        time_info = schedule.get(match_id)
        if time_info:
            processed_schedule_ids.add(match_id)
        
        found_odds = match_odds(p1, p2, all_odds)
        
        matches.append({
            "match_id": row.get("match_id"),
            "round": display_round,
            "player_1": final_p1,
            "player_2": final_p2,
            "time": time_info["time"] if time_info else None,
            "full_time": time_info["full"] if time_info else None,
            "odds": found_odds,
            "row_data": final_row
        })

    import datetime
    current_year = datetime.datetime.now().year
    t_name_low = tournament_name_with_year.lower().replace("🔴 en cours : ", "").replace("🔴 ongoing: ", "").strip()
    import re as _re
    t_clean_for_match = _re.sub(r"[()'\'']", " ", _re.sub(r"\(\d{4}\)", "", t_name_low)).strip()
    t_words = set(w for w in t_clean_for_match.split() if len(w) >= 4)

    def schedule_matches_tournament(s_tour_raw):
        s_clean = _re.sub(r"[()'\'']", " ", s_tour_raw.lower())
        s_clean = _re.sub(r"^(direct\s*-\s*|live\s*-\s*)", "", s_clean).strip()
        
        # Gender mismatch check
        is_t_women = "women" in t_name_low or "wta" in t_name_low
        is_s_women = "women" in s_clean or "wta" in s_clean
        if is_t_women != is_s_women:
            return False
            
        is_t_men = "men" in t_name_low or "atp" in t_name_low
        is_s_men = "men" in s_clean or "atp" in s_clean
        if is_t_men != is_s_men:
            return False

        s_words = set(w for w in s_clean.split() if len(w) >= 4)
        common = t_words & s_words
        return (
            len(common) >= 1 or
            s_clean in t_clean_for_match or
            t_clean_for_match in s_clean or
            any(w in s_clean for w in t_words)
        )

    for s_id, s_info in schedule.items():
        if s_id not in processed_schedule_ids:
            s_tour = s_info.get("tournament", "").lower()
            if s_tour and schedule_matches_tournament(s_tour) and t_year == current_year:
                p1_s = s_info["p1"]
                p2_s = s_info["p2"]
                found_odds_s = match_odds(p1_s, p2_s, all_odds)
                
                matches.append({
                    "match_id": f"sched_{s_id}",
                    "round": s_info.get("round", "??"),
                    "player_1": p1_s,
                    "player_2": p2_s,
                    "time": s_info["time"],
                    "full_time": s_info["full"],
                    "odds": found_odds_s,
                    "row_data": {
                        "score": "Upcoming",
                        "round": s_info.get("round", "??"),
                        "tournament": tournament_name_with_year,
                        "Name_1": p1_s,
                        "Name_2": p2_s,
                        "tournament_surface": tour_df["tournament_surface"].iloc[0] if not tour_df.empty else "Hard",
                        "tournament_level": tour_df["tournament_level"].iloc[0] if not tour_df.empty else "A"
                    }
                })

    if t_year == current_year:
        try:
            ls_upcoming = _fetch_livescore_upcoming_for_tournament(
                tournament_name_with_year, t_year, tour=tour, days_ahead=4
            )
            existing_keys = set(
                "-".join(sorted([norm(m['player_1']), norm(m['player_2'])]))
                for m in matches
            )
            surface = tour_df["tournament_surface"].iloc[0] if not tour_df.empty else "Clay"
            level = tour_df["tournament_level"].iloc[0] if not tour_df.empty else "A"
            for ls_m in ls_upcoming:
                mk = ls_m["match_key"]
                if mk not in existing_keys:
                    existing_keys.add(mk)
                    found_odds_ls = match_odds(ls_m["player_1"], ls_m["player_2"], all_odds)
                    matches.append({
                        "match_id": f"ls_{mk}",
                        "round": ls_m["round"],
                        "player_1": ls_m["player_1"],
                        "player_2": ls_m["player_2"],
                        "time": ls_m["time"],
                        "full_time": ls_m["full_time"],
                        "odds": found_odds_ls,
                        "row_data": {
                            "score": "Upcoming",
                            "round": ls_m["round"],
                            "tournament": tournament_name_with_year,
                            "Name_1": ls_m["player_1"],
                            "Name_2": ls_m["player_2"],
                            "tournament_surface": surface,
                            "tournament_level": level
                        }
                    })
                else:
                    # CORRECTION CRITIQUE : Le match existe déjà via le cache CSV (souvent avec un mauvais round).
                    # On FORCE la mise à jour de son round et de son heure avec la donnée fraîche de LiveScore !
                    for m in matches:
                        m_key = "-".join(sorted([norm(m['player_1']), norm(m['player_2'])]))
                        if m_key == mk:
                            score = m['row_data'].get('score', '')
                            if score == "Upcoming" or not score:
                                m['round'] = ls_m['round']
                                m['row_data']['round'] = ls_m['round']
                                if ls_m['full_time']:
                                    m['full_time'] = ls_m['full_time']
                                    m['time'] = ls_m['time']
                            break
        except Exception as e_ls2:
            print(f"[LiveScore direct] Error: {e_ls2}")

    _patch_scores_from_csv(matches, tour, tournament_name_with_year, data_dir)
    _add_missing_finished_matches_from_csv(matches, tour, tournament_name_with_year, t_year, data_dir, tour_df=tour_df)

    is_ongoing = "en cours" in tournament_name_with_year.lower()
    upcoming_matches = []
    
    for m in matches:
        # Filtre Challengers : L'utilisateur ne veut plus les voir du tout
        tourney_full = str(m.get('tournament', '') or m.get('row_data', {}).get('tournament', '')).lower()
        if "challenger" in tourney_full:
            continue

        score = str(m.get('row_data', {}).get('score', '')).lower().strip()
        
        # Filtre "Upcoming Only" UNIQUEMENT pour les tournois en cours
        # Si on regarde un tournoi passé (ex: Madrid), on veut voir tous les résultats.
        if is_ongoing:
            if score not in ['upcoming', 'none', 'nan', '']:
                continue
        
        # Masquage des tours pour les matchs à venir (demande utilisateur)
        if score in ['upcoming', 'none', 'nan', '']:
            m['round'] = ""
            if 'row_data' in m and isinstance(m['row_data'], dict):
                m['row_data']['round'] = ""
                m['row_data']['score'] = 'Upcoming'
            
            # On ne garde que les matchs qui ont une heure d'affichée (matchs du jour) pour le "En cours"
            if is_ongoing:
                time_val = str(m.get('full_time', '')).strip().lower()
                if not time_val or time_val == 'none':
                    continue
                    
        upcoming_matches.append(m)

    return upcoming_matches

def _add_missing_finished_matches_from_csv(matches, tour, tournament_name, t_year, data_dir="data", tour_df=None):
    import pandas as pd
    import re as _re
    import os
    
    suffix = "_wta" if tour == "WTA" else ""
    csv_path = os.path.join(data_dir, f"scraped_matches{suffix}.csv")
    if not os.path.exists(csv_path):
        return
    
    try:
        df_csv = pd.read_csv(csv_path)
    except: return
        
    def norm(n): return _re.sub(r'[^a-z0-9]', '', str(n).lower())
    
    t_name_low = tournament_name.lower().replace("🔴 en cours : ", "").replace("🔴 ongoing: ", "").strip()
    t_clean = _re.sub(r' \(\d{4}\)$', '', t_name_low).strip()
    
    city_match = _re.search(r'\(([^)]+)\)', t_clean)
    t_city = city_match.group(1).lower() if city_match else ""
    
    # Nettoyage crucial : on supprime l'année (ex: "2026") et les préfixes pour matcher le CSV
    t_main = _re.sub(r'\b(atp|wta|masters|open|20\d\d)\b', '', t_clean).strip().lower()
    if not t_main:
        t_main = _re.sub(r'\b20\d\d\b', '', t_clean).strip().lower()
    t_main = _re.sub(r'\([^)]+\)', '', t_main).strip()

    if 'tourney_date' not in df_csv.columns or 'tournament' not in df_csv.columns:
        return

    mask_year = (df_csv['tourney_date'].astype(str).str.startswith(str(t_year)))
    mask_tour = (df_csv['tournament'].str.lower().str.contains(t_main, na=False))
    if t_city:
        mask_tour = mask_tour | (df_csv['tournament'].str.lower().str.contains(t_city, na=False))
    
    relevant_csv = df_csv[mask_year & mask_tour].copy()
    if relevant_csv.empty: return

    existing_keys = set()
    for m in matches:
        key = "-".join(sorted([norm(m['player_1']), norm(m['player_2'])]))
        existing_keys.add(key)
        
    df_rounds = {}
    valid_singles_players = set() # On crée une liste des vrais joueurs de simple
    
    if tour_df is not None:
        for _, r in tour_df.iterrows():
            n1 = norm(r.get('Name_1', ''))
            n2 = norm(r.get('Name_2', ''))
            valid_singles_players.add(n1)
            valid_singles_players.add(n2)
            k = "-".join(sorted([n1, n2]))
            df_rounds[k] = r.get('round')

    for _, row in relevant_csv.iterrows():
        p1 = str(row.get('winner_name', ''))
        p2 = str(row.get('loser_name', ''))
        if not p1 or not p2: continue

        # --- FILTRE ANTI-DOUBLES STRICT ---
        if "double" in str(row.get('tournament', '')).lower(): 
            continue
            
        # Sécurité 1: Noms combinés (ex: Salisbury / Pavlasek)
        if any(c in p1 for c in ['/', '&', '+', ' and ']) or any(c in p2 for c in ['/', '&', '+', ' and ']):
            continue

        # Sécurité 2: L'un des deux joueurs doit figurer dans le tableau de simple officiel
        if valid_singles_players:
            if norm(p1) not in valid_singles_players or norm(p2) not in valid_singles_players:
                continue
        # -------------------------------------

        key = "-".join(sorted([norm(p1), norm(p2)]))
        if key not in existing_keys:
            orig_round = df_rounds.get(key)
            if not orig_round or orig_round in ['FT', 'Ret.', 'WO']:
                orig_round = str(row.get('round', '??'))
            
            if orig_round in ['FT', 'Ret.', 'WO']:
                orig_round = '??'

            matches.append({
                "match_id": f"csv_{row.get('match_id', key)}",
                "round": orig_round,
                "player_1": p1, # winner_name
                "player_2": p2, # loser_name
                "time": None,
                "full_time": None,
                "odds": None,
                "row_data": {
                    "score": row['score'],
                    "round": orig_round,
                    "Name_1": p1,
                    "Name_2": p2,
                    "Winner": 0, # p1 est le gagnant
                    "tournament": tournament_name
                }
            })
            existing_keys.add(key)

def _patch_scores_from_csv(matches, tour, tournament_name, data_dir="data"):
    import pandas as pd
    import re as _re
    import os
    
    suffix = "_wta" if tour == "WTA" else ""
    csv_path = os.path.join(data_dir, f"scraped_matches{suffix}.csv")
    if not os.path.exists(csv_path): return
    
    try:
        df_csv = pd.read_csv(csv_path)
    except: return
        
    def norm(n): return _re.sub(r'[^a-z0-9]', '', str(n).lower())
    
    # 1. Filtrer strictement par nom de tournoi pour ignorer les scores des tournois précédents (ex: Madrid)
    t_name_low = tournament_name.lower().replace("🔴 en cours : ", "").replace("🔴 ongoing: ", "").strip()
    t_clean = _re.sub(r' \(\d{4}\)$', '', t_name_low).strip()
    city_match = _re.search(r'\(([^)]+)\)', t_clean)
    t_city = city_match.group(1).lower() if city_match else ""
    
    t_main = _re.sub(r'\b(atp|wta|masters|open|20\d\d)\b', '', t_clean).strip().lower()
    if not t_main:
        t_main = _re.sub(r'\b20\d\d\b', '', t_clean).strip().lower()
    t_main = _re.sub(r'\([^)]+\)', '', t_main).strip()

    if 'tournament' in df_csv.columns:
        mask_tour = df_csv['tournament'].str.lower().str.contains(t_main, na=False)
        if t_city:
            mask_tour = mask_tour | df_csv['tournament'].str.lower().str.contains(t_city, na=False)
        df_csv = df_csv[mask_tour].copy()

    if df_csv.empty: return

    df_csv = df_csv.tail(500).copy() 
    if 'winner_name' not in df_csv.columns or 'loser_name' not in df_csv.columns:
        return
        
    df_csv['n1'] = df_csv['winner_name'].apply(norm)
    df_csv['n2'] = df_csv['loser_name'].apply(norm)
    
    from datetime import datetime as _dt2, timedelta as _td2
    cutoff_int = int((_dt2.now() - _td2(days=14)).strftime("%Y%m%d"))

    if 'tourney_date' in df_csv.columns:
        try:
            df_csv = df_csv[df_csv['tourney_date'].astype(str).str[:8].apply(
                lambda x: int(x) >= cutoff_int if x.isdigit() else False
            )].copy()
        except: pass

    for m in matches:
        current_score = m['row_data'].get('score', '')
        # Si le match n'a pas encore de score définitif dans l'affichage
        if current_score == "Upcoming" or not current_score:
            if str(m.get('match_id', '')).startswith('ls_'):
                continue

            p1_n = norm(m['player_1'])
            p2_n = norm(m['player_2'])

            mask = (
                ((df_csv['n1'] == p1_n) & (df_csv['n2'] == p2_n)) |
                ((df_csv['n1'] == p2_n) & (df_csv['n2'] == p1_n))
            )
            found = df_csv[mask]
            if not found.empty:
                finished = found[found['score'].notna() & (found['score'] != "Upcoming")].sort_values('tourney_date', ascending=False)
                if not finished.empty:
                    row = finished.iloc[0]
                    new_score = row['score']
                    if isinstance(new_score, str) and len(new_score.strip()) > 0:
                        m['row_data']['score'] = new_score
                        # 2. MISE À JOUR CRITIQUE : forcer le vrai vainqueur à gauche pour la colonne "🏆 Vainqueur"
                        m['player_1'] = row['winner_name']
                        m['player_2'] = row['loser_name']
                        m['row_data']['Name_1'] = row['winner_name']
                        m['row_data']['Name_2'] = row['loser_name']
                        m['row_data']['Winner'] = 0

# --- MAPPING NATIONALITÉ → TOURNOIS LOCAUX ---
_NATIONALITY_TOURNAMENT_MAP = {
    "ITA": ["rome", "internazionali", "italia", "bnl", "palermo", "napoli"],
    "ESP": ["madrid", "barcelona", "valencia", "marbella", "murcia"],
    "FRA": ["roland", "garros", "paris", "lyon", "marseille", "montpellier"],
    "USA": ["us open", "new york", "miami", "indian wells", "washington", "cincinnati"],
    "AUS": ["australian", "melbourne", "sydney", "brisbane"],
    "GBR": ["wimbledon", "london", "queens", "nottingham"],
    "SUI": ["geneva", "basel"],
    "GER": ["munich", "hamburg", "halle"],
    "ARG": ["buenos aires", "cordoba"],
    "BRA": ["rio", "sao paulo"],
    "NOR": ["stavanger"],
    "RUS": ["moscow", "st petersburg"],
    "SRB": ["belgrade", "beograd"],
    "CRO": ["zagreb", "umag"],
    "GRE": ["athens"],
    "KAZ": ["astana", "nur-sultan"],
    "CHN": ["beijing", "shanghai", "wuhan", "shenzhen"],
    "JPN": ["tokyo", "osaka"],
    "CAN": ["montreal", "toronto", "vancouver"],
}

def detect_home_crowd(p_name, tournament_name, players_db):
    """Détecte si le joueur joue dans son pays d'origine (avantage public)."""
    if not p_name or not tournament_name or not players_db:
        return False
    p_obj = find_player_by_name(p_name, players_db)
    if not p_obj:
        return False
    nationality = str(getattr(p_obj, 'country', '') or getattr(p_obj, 'nationality', '') or '').upper().strip()
    if not nationality:
        return False
    t_lower = tournament_name.lower()
    countries = _NATIONALITY_TOURNAMENT_MAP.get(nationality, [])
    return any(kw in t_lower for kw in countries)

def predict_match_outcome(model, match_row, used_features, players_db=None, p1_name=None, p2_name=None, tournament_name=None, te_p1=None, te_p2=None, skip_te_scrape=False):
    # Création d'une copie pour ne pas polluer l'original
    m_row = match_row.copy()
    
    # Enrichissement dynamique depuis la players_db et RapidAPI si dispo
    p1_obj = find_player_by_name(p1_name, players_db) if players_db else None
    p2_obj = find_player_by_name(p2_name, players_db) if players_db else None
    
    # 1. Remplissage initial depuis la base de données locale
    if p1_obj:
        r1 = m_row.get("Ranking_1")
        if r1 is None or r1 == 0 or r1 == 999 or r1 >= 9999:
            p1_rank = p1_obj.ranking
            if p1_rank == 999 or p1_rank >= 9999 or p1_rank <= 0:
                p1_rank = p1_obj.get_latest_valid_ranking()
            m_row["Ranking_1"] = p1_rank
        if "Ranking_Points_1" not in m_row: m_row["Ranking_Points_1"] = p1_obj.ranking_points
        surf = str(m_row.get('tournament_surface', 'Hard')).capitalize()
        if "surface_win_pct_1" not in m_row: m_row["surface_win_pct_1"] = p1_obj.get_surface_win_pct(surf)
        
    if p2_obj:
        r2 = m_row.get("Ranking_2")
        if r2 is None or r2 == 0 or r2 == 999 or r2 >= 9999:
            p2_rank = p2_obj.ranking
            if p2_rank == 999 or p2_rank >= 9999 or p2_rank <= 0:
                p2_rank = p2_obj.get_latest_valid_ranking()
            m_row["Ranking_2"] = p2_rank
        if "Ranking_Points_2" not in m_row: m_row["Ranking_Points_2"] = p2_obj.ranking_points
        surf = str(m_row.get('tournament_surface', 'Hard')).capitalize()
        if "surface_win_pct_2" not in m_row: m_row["surface_win_pct_2"] = p2_obj.get_surface_win_pct(surf)

    # 2. Fallback API si le classement ou le winrate de surface est manquant/invalide
    # Pour Player 1
    r1 = m_row.get("Ranking_1")
    s1 = m_row.get("surface_win_pct_1")
    if r1 is None or r1 == 0 or r1 == 999 or r1 >= 9999 or s1 is None or s1 == 0.0 or s1 == 50.0:
        print(f"[API Fallback] Détection de données manquantes pour {p1_name} (Rank={r1}, SurfPct={s1}). Recherche RapidAPI...")
        try:
            from python.data.rapidapi_client import client
            import datetime
            tournament = tournament_name or m_row.get('tournament', 'ATP')
            tour = "wta" if "wta" in str(tournament).lower() else "atp"
            today_str = datetime.datetime.now().strftime("%Y-%m-%d")
            client.populate_id_map_for_date(today_str, tour=tour)
            p1_id = client.get_player_id_by_name(p1_name, tour=tour)
            if p1_id:
                if r1 is None or r1 == 0 or r1 == 999 or r1 >= 9999:
                    profile = client.get_player_profile(p1_id, tour=tour)
                    if profile and 'data' in profile:
                        api_rank = profile['data'].get('currentRank')
                        if api_rank and 0 < api_rank < 9999:
                            print(f"[API Fallback] Vrai classement trouvé pour {p1_name} : #{api_rank}")
                            m_row["Ranking_1"] = api_rank
                            if p1_obj:
                                p1_obj.ranking = api_rank
                                p1_obj.ranking_points = profile['data'].get('points', 0)
                if s1 is None or s1 == 0.0 or s1 == 50.0:
                    surf_summary = client.get_player_surface_summary(p1_id, tour=tour)
                    if surf_summary and 'data' in surf_summary:
                        surf = str(m_row.get('tournament_surface', 'Hard')).capitalize()
                        surf_key = 'Hard'
                        if 'clay' in surf.lower() or 'terre' in surf.lower(): surf_key = 'Clay'
                        elif 'grass' in surf.lower() or 'herbe' in surf.lower(): surf_key = 'Grass'
                        
                        total_wins = 0
                        total_losses = 0
                        for yr_data in surf_summary['data']:
                            for s in yr_data.get('surfaces', []):
                                court = s.get('court', '').lower()
                                is_match = False
                                if surf_key == 'Clay' and 'clay' in court: is_match = True
                                elif surf_key == 'Grass' and 'grass' in court: is_match = True
                                elif surf_key == 'Hard' and ('hard' in court or 'indoor' in court or 'i.hard' in court): is_match = True
                                
                                if is_match:
                                    total_wins += s.get('courtWins', 0)
                                    total_losses += s.get('courtLosses', 0)
                                    
                        if total_wins + total_losses > 0:
                            win_pct = (total_wins / (total_wins + total_losses)) * 100
                            print(f"[API Fallback] Stats surface {surf_key} trouvées pour {p1_name} : {total_wins}V - {total_losses}D ({win_pct:.1f}%)")
                            m_row["surface_win_pct_1"] = win_pct
                            if p1_obj:
                                if surf_key == 'Clay': p1_obj.clay_victories_percentage = win_pct
                                elif surf_key == 'Grass': p1_obj.grass_victories_percentage = win_pct
                                elif surf_key == 'Hard': p1_obj.hard_victories_percentage = win_pct
                
                # --- Récupération des matchs récents pour le calcul O/U ---
                if p1_obj and len(getattr(p1_obj, 'matches_history', [])) < 5:
                    past = client.get_player_past_matches(p1_id, tour=tour)
                    if past and 'data' in past:
                        new_hist = []
                        for pm in past['data'][:20]:
                            score_str = pm.get('score', '')
                            if not score_str or str(score_str).strip().lower() in ['', 'none', 'w/o', 'ret']: continue
                            new_hist.append({
                                'score': score_str,
                                'Name_1': pm.get('player1Name', ''),
                                'Name_2': pm.get('player2Name', ''),
                                'tournament_surface': pm.get('court', 'Hard')
                            })
                        if new_hist:
                            existing = getattr(p1_obj, 'matches_history', [])
                            p1_obj.matches_history = existing + new_hist
                            print(f"[API Fallback] {len(new_hist)} matchs historiques récupérés pour {p1_name}")
        except Exception as api_err:
            print(f"[API Fallback] Erreur de fallback RapidAPI pour {p1_name} : {api_err}")

    # Pour Player 2
    r2 = m_row.get("Ranking_2")
    s2 = m_row.get("surface_win_pct_2")
    if r2 is None or r2 == 0 or r2 == 999 or r2 >= 9999 or s2 is None or s2 == 0.0 or s2 == 50.0:
        print(f"[API Fallback] Détection de données manquantes pour {p2_name} (Rank={r2}, SurfPct={s2}). Recherche RapidAPI...")
        try:
            from python.data.rapidapi_client import client
            import datetime
            tournament = tournament_name or m_row.get('tournament', 'ATP')
            tour = "wta" if "wta" in str(tournament).lower() else "atp"
            today_str = datetime.datetime.now().strftime("%Y-%m-%d")
            client.populate_id_map_for_date(today_str, tour=tour)
            p2_id = client.get_player_id_by_name(p2_name, tour=tour)
            if p2_id:
                if r2 is None or r2 == 0 or r2 == 999 or r2 >= 9999:
                    profile = client.get_player_profile(p2_id, tour=tour)
                    if profile and 'data' in profile:
                        api_rank = profile['data'].get('currentRank')
                        if api_rank and 0 < api_rank < 9999:
                            print(f"[API Fallback] Vrai classement trouvé pour {p2_name} : #{api_rank}")
                            m_row["Ranking_2"] = api_rank
                            if p2_obj:
                                p2_obj.ranking = api_rank
                                p2_obj.ranking_points = profile['data'].get('points', 0)
                if s2 is None or s2 == 0.0 or s2 == 50.0:
                    surf_summary = client.get_player_surface_summary(p2_id, tour=tour)
                    if surf_summary and 'data' in surf_summary:
                        surf = str(m_row.get('tournament_surface', 'Hard')).capitalize()
                        surf_key = 'Hard'
                        if 'clay' in surf.lower() or 'terre' in surf.lower(): surf_key = 'Clay'
                        elif 'grass' in surf.lower() or 'herbe' in surf.lower(): surf_key = 'Grass'
                        
                        total_wins = 0
                        total_losses = 0
                        for yr_data in surf_summary['data']:
                            for s in yr_data.get('surfaces', []):
                                court = s.get('court', '').lower()
                                is_match = False
                                if surf_key == 'Clay' and 'clay' in court: is_match = True
                                elif surf_key == 'Grass' and 'grass' in court: is_match = True
                                elif surf_key == 'Hard' and ('hard' in court or 'indoor' in court or 'i.hard' in court): is_match = True
                                
                                if is_match:
                                    total_wins += s.get('courtWins', 0)
                                    total_losses += s.get('courtLosses', 0)
                                    
                        if total_wins + total_losses > 0:
                            win_pct = (total_wins / (total_wins + total_losses)) * 100
                            print(f"[API Fallback] Stats surface {surf_key} trouvées pour {p2_name} : {total_wins}V - {total_losses}D ({win_pct:.1f}%)")
                            m_row["surface_win_pct_2"] = win_pct
                            if p2_obj:
                                if surf_key == 'Clay': p2_obj.clay_victories_percentage = win_pct
                                elif surf_key == 'Grass': p2_obj.grass_victories_percentage = win_pct
                                elif surf_key == 'Hard': p2_obj.hard_victories_percentage = win_pct
                
                # --- Récupération des matchs récents pour le calcul O/U ---
                if p2_obj and len(getattr(p2_obj, 'matches_history', [])) < 5:
                    past = client.get_player_past_matches(p2_id, tour=tour)
                    if past and 'data' in past:
                        new_hist = []
                        for pm in past['data'][:20]:
                            score_str = pm.get('score', '')
                            if not score_str or str(score_str).strip().lower() in ['', 'none', 'w/o', 'ret']: continue
                            new_hist.append({
                                'score': score_str,
                                'Name_1': pm.get('player1Name', ''),
                                'Name_2': pm.get('player2Name', ''),
                                'tournament_surface': pm.get('court', 'Hard')
                            })
                        if new_hist:
                            existing = getattr(p2_obj, 'matches_history', [])
                            p2_obj.matches_history = existing + new_hist
                            print(f"[API Fallback] {len(new_hist)} matchs historiques récupérés pour {p2_name}")
        except Exception as api_err:
            print(f"[API Fallback] Erreur de fallback RapidAPI pour {p2_name} : {api_err}")

    # 3. Remplissage des autres attributs
    for suffix, p_obj in [("_1", p1_obj), ("_2", p2_obj)]:
        if f"endurance_win_percentage{suffix}" not in m_row:
            m_row[f"endurance_win_percentage{suffix}"] = getattr(p_obj, 'endurance_win_percentage', 50.0) if p_obj else 50.0
        if f"current_win_streak{suffix}" not in m_row:
            m_row[f"current_win_streak{suffix}"] = getattr(p_obj, 'current_win_streak', 0) if p_obj else 0
        if f"minutes_fatigue{suffix}" not in m_row:
            m_row[f"minutes_fatigue{suffix}"] = getattr(p_obj, 'minutes_fatigue', 0) if p_obj else 0
        
        # Aces
        if f"Aces_Percentage{suffix}" not in m_row:
            m_row[f"Aces_Percentage{suffix}"] = getattr(p_obj, 'aces_percentage', 0.0) if p_obj else 0.0
        
        # Stats MCP (Advanced charting)
        for stat in ["winner_unforced_ratio", "return_pts_won_pct", "avg_winners_fh", "avg_unforced_fh"]:
            full_key = f"{stat}{suffix}"
            if full_key not in m_row:
                val = 0.0
                if p_obj:
                    val = getattr(p_obj, stat, 0.0)
                    if val == 0.0:
                        advanced_stats = getattr(p_obj, 'advanced_stats', {})
                        val = advanced_stats.get(stat, 0.0)
                m_row[full_key] = val

    single_df = pd.DataFrame([m_row])
    encoded = encode_data(single_df.copy())
    
    # Sécurité absolue : On s'assure que toutes les colonnes utilisées par le modèle existent
    for feat in used_features:
        if feat not in encoded.columns:
            # Fallback diff_ranking
            if feat == "diff_ranking":
                if "Ranking_1" in encoded.columns and "Ranking_2" in encoded.columns:
                    encoded["diff_ranking"] = encoded["Ranking_2"] - encoded["Ranking_1"]
                else:
                    encoded["diff_ranking"] = 0.0
            else:
                encoded[feat] = 0.0
                
    X = encoded[used_features].values
    probs = model.predict_proba(X)[0]
    prob_1 = probs[0]
    prob_2 = probs[1]
    
    enrichment_p1 = {}
    enrichment_p2 = {}
    confidence_score = 1.0 
    
    if players_db and p1_name and p2_name:
        if not skip_te_scrape:
            if te_p1 is None: te_p1 = scrape_player_te_stats(p1_name)
            if te_p2 is None: te_p2 = scrape_player_te_stats(p2_name)
            
            from python.data.tennisexplorer_scraper import merge_te_to_base_socle
            # On utilise les p_obj déjà trouvés de manière robuste plus haut
            if p1_obj and te_p1: 
                merge_te_to_base_socle(p1_obj, te_p1, players_db)
                p1_obj.inject_scraped_history(te_p1)
            if p2_obj and te_p2: 
                merge_te_to_base_socle(p2_obj, te_p2, players_db)
                p2_obj.inject_scraped_history(te_p2)
        else:
            if te_p1 is None: te_p1 = {}
            if te_p2 is None: te_p2 = {}
        
        matches_1 = len(getattr(p1_obj, 'matches_history', [])) if p1_obj else 0
        matches_2 = len(getattr(p2_obj, 'matches_history', [])) if p2_obj else 0
        
        conf_1 = min(1.0, matches_1 / 15.0)
        conf_2 = min(1.0, matches_2 / 15.0)
        confidence_score = conf_1 * conf_2
        
        prob_1 = 0.5 + (prob_1 - 0.5) * confidence_score
        prob_2 = 0.5 + (prob_2 - 0.5) * confidence_score
        
        elite_1 = analyze_elite_resistance(te_p1, players_db)
        elite_2 = analyze_elite_resistance(te_p2, players_db)
        
        salmon_1 = analyze_salmon_factor(te_p1, tournament_name, players_db, p1_obj)
        salmon_2 = analyze_salmon_factor(te_p2, tournament_name, players_db, p2_obj)
        
        boost_1 = 0.0
        if salmon_1.get("is_salmon"): boost_1 += 0.15
        if elite_1.get("moral_victory"): boost_1 += 0.10
        if elite_1.get("win_top20"): boost_1 += 0.05
        
        boost_2 = 0.0
        if salmon_2.get("is_salmon"): boost_2 += 0.15
        if elite_2.get("moral_victory"): boost_2 += 0.10
        if elite_2.get("win_top20"): boost_2 += 0.05

        # ================================================================
        # AMÉLIORATION 1 : FACTEUR ENDURANCE TOP20 (matchs serrés)
        # Si l'écart est < 15%, risque de 3ème set. Le Top20 gagne
        # systématiquement car il est plus endurant (marathon 60km vs 50km)
        # ================================================================
        ranking_1 = m_row.get("Ranking_1", 999) or 999
        ranking_2 = m_row.get("Ranking_2", 999) or 999
        try:
            ranking_1 = int(float(ranking_1))
            ranking_2 = int(float(ranking_2))
        except (ValueError, TypeError):
            ranking_1, ranking_2 = 999, 999

        level_gap = abs(prob_1 - prob_2)
        is_close_match = level_gap < 0.15

        p1_is_top20 = (ranking_1 <= 25)
        p2_is_top20 = (ranking_2 <= 25)
        endurance_1 = m_row.get("endurance_win_percentage_1", 50.0) or 50.0
        endurance_2 = m_row.get("endurance_win_percentage_2", 50.0) or 50.0

        if is_close_match:
            if p1_is_top20 and not p2_is_top20:
                # P1 est top20, P2 non → endurance supérieure pour le 3ème set
                top20_boost = 0.08
                boost_1 += top20_boost
                salmon_1["top20_endurance_boost"] = True
                salmon_1["endurance_alert"] = (
                    f"⚡ TOP20 ENDURANCE : {p1_name} (#{ranking_1}) favorisé au 3ème set "
                    f"(écart niveau={level_gap*100:.0f}%, endurance={endurance_1:.0f}%)"
                )
            elif p2_is_top20 and not p1_is_top20:
                # P2 est top20, P1 non → endurance supérieure pour le 3ème set
                top20_boost = 0.08
                boost_2 += top20_boost
                salmon_2["top20_endurance_boost"] = True
                salmon_2["endurance_alert"] = (
                    f"⚡ TOP20 ENDURANCE : {p2_name} (#{ranking_2}) favorisé au 3ème set "
                    f"(écart niveau={level_gap*100:.0f}%, endurance={endurance_2:.0f}%)"
                )

        # ================================================================
        # AMÉLIORATION 2 : FACTEUR PUBLIC LOCAL (avantage domicile)
        # +5% si le joueur joue dans son pays d'origine
        # ================================================================
        t_name_for_crowd = tournament_name or m_row.get("tournament", "")
        home_1 = detect_home_crowd(p1_name, t_name_for_crowd, players_db)
        home_2 = detect_home_crowd(p2_name, t_name_for_crowd, players_db)

        if home_1:
            boost_1 += 0.05
            salmon_1["home_crowd"] = True
            salmon_1["home_alert"] = f"🏟️ {p1_name} joue à domicile → +5% (public local)"
        if home_2:
            boost_2 += 0.05
            salmon_2["home_crowd"] = True
            salmon_2["home_alert"] = f"🏟️ {p2_name} joue à domicile → +5% (public local)"

        # ================================================================
        # AMÉLIORATION 3 : DÉTECTION RISQUE EFFONDREMENT PSYCHOLOGIQUE
        # Match serré + adversaire Top20 endurant jouant à domicile
        # → Ne pas miser sur le non-Top20 même s'il mène
        # ================================================================
        if is_close_match:
            # P1 risque l'effondrement si P2 est Top20 ET joue à domicile
            if p2_is_top20 and home_2:
                salmon_1["collapse_risk"] = True
                salmon_1["collapse_alert"] = (
                    f"🚨 RISQUE EFFONDREMENT pour {p1_name} : "
                    f"{p2_name} est Top20 (#{ranking_2}) ET joue à domicile "
                    f"→ Ne pas miser sur {p1_name} même avec des balles de match"
                )
            # P2 risque l'effondrement si P1 est Top20 ET joue à domicile
            if p1_is_top20 and home_1:
                salmon_2["collapse_risk"] = True
                salmon_2["collapse_alert"] = (
                    f"🚨 RISQUE EFFONDREMENT pour {p2_name} : "
                    f"{p1_name} est Top20 (#{ranking_1}) ET joue à domicile "
                    f"→ Ne pas miser sur {p2_name} même avec des balles de match"
                )
        
        prob_1 = min(0.95, prob_1 + boost_1)
        prob_2 = min(0.95, prob_2 + boost_2)
        
        total = prob_1 + prob_2
        if total > 0:
            prob_1 = prob_1 / total
            prob_2 = prob_2 / total
            
        def enrich_matches(matches, db):
            if not db: return matches
            for m in matches:
                opp_te = m.get("opponent", "").lower().replace(".", "").split()
                if not opp_te: continue
                last = opp_te[0]
                initial = opp_te[1][0] if len(opp_te) > 1 and opp_te[1] else ""
                m["opp_rank"] = "N/A"
                for full_name, p_obj in db.items():
                    fn_lower = full_name.lower()
                    if last in fn_lower:
                        first_name = fn_lower.split()[0]
                        if not initial or first_name.startswith(initial):
                            m["opp_rank"] = p_obj.ranking
                            break
            return matches

        matches_p1 = enrich_matches(te_p1.get("recent_matches", [])[:20], players_db)
        matches_p2 = enrich_matches(te_p2.get("recent_matches", [])[:20], players_db)

        enrichment_p1 = {**elite_1, **salmon_1, "te_wl": te_p1.get("wl_ratios", {}), "recent_matches": matches_p1,
                         "ranking": ranking_1, "is_top20": p1_is_top20, "home_crowd": home_1,
                         "is_close_match": is_close_match, "level_gap": level_gap}
        enrichment_p2 = {**elite_2, **salmon_2, "te_wl": te_p2.get("wl_ratios", {}), "recent_matches": matches_p2,
                         "ranking": ranking_2, "is_top20": p2_is_top20, "home_crowd": home_2,
                         "is_close_match": is_close_match, "level_gap": level_gap}
    
    return prob_1, prob_2, enrichment_p1, enrichment_p2, confidence_score

def calculate_betting_stats(data_df, player1_name, player2_name, prob_1, prob_2, surface=None, real_thresholds=None, is_salmon=False, is_bo5=False):
    stats = {}
    if data_df is None or data_df.empty: return stats
    
    df = data_df.copy()
    if "score" in df.columns:
        df = df[df["score"].notna() & (df["score"] != "Upcoming")].copy()
    
    def get_clean_surname(name):
        clean = str(name).replace("(WC)", "").replace("[", "").replace("]", "").replace("👤", "").strip()
        parts = [p for p in clean.split() if len(p) > 2]
        if not parts: parts = clean.split()
        return parts[-1] if parts else clean

    p1_last = get_clean_surname(player1_name)
    p2_last = get_clean_surname(player2_name)
    
    player_mask = pd.Series([False] * len(df), index=df.index)
    for col_name in ["Name_1", "Name_2"]:
        if col_name in df.columns:
            mask_1 = df[col_name].str.contains(p1_last, na=False, case=False, regex=False) if p1_last else False
            mask_2 = df[col_name].str.contains(p2_last, na=False, case=False, regex=False) if p2_last else False
            player_mask = player_mask | mask_1 | mask_2
    
    player_df = df[player_mask].copy()
    player_df['match_key'] = player_df.apply(lambda r: "-".join(sorted([str(r.get('Name_1','')), str(r.get('Name_2',''))])), axis=1)
    if "tournament_date" in player_df.columns and "round" in player_df.columns:
        player_df = player_df.drop_duplicates(subset=["tournament_date", "round", "match_key"])
    
    if surface and "tournament_surface" in player_df.columns:
        surf_df = player_df[player_df["tournament_surface"].str.lower() == surface.lower()]
        if len(surf_df) >= 5: player_df = surf_df
    
    def count_games(score_str):
        s_upper = str(score_str).upper()
        if any(kw in s_upper for kw in ["RET", "W/O", "DEF", "ABD"]): return None, None
        try:
            total, sets_played = 0, 0
            for s in str(score_str).split():
                if "-" in s:
                    parts = s.replace("(", "").split("(")[0].split("-")
                    if len(parts) == 2:
                        total += int(parts[0].strip()) + int(parts[1].strip()[:1])
                        sets_played += 1
            return total, sets_played
        except: return None, None
    
    if "score" in player_df.columns and len(player_df) >= 3:
        games_data = player_df["score"].apply(count_games)
        total_games = [g[0] for g in games_data if g[0] is not None and g[0] > 0]
        num_sets = [g[1] for g in games_data if g[1] is not None and g[1] > 0]
    else:
        total_games = []
        num_sets = []
    
    # --- FALLBACK si pas assez de données historiques ---
    # On utilise une moyenne estimée basée sur la surface et l'écart de probabilité
    use_fallback = not total_games
    
    if total_games or use_fallback:
        import numpy as np
        import math

        if use_fallback:
            # Moyenne par défaut selon le type de tournoi
            # Grand Chelem hommes (BO5) : ~34 jeux en moyenne
            # ATP/WTA standard (BO3) : ~21.5 jeux en moyenne
            is_gs = is_bo5 or (real_thresholds and min(real_thresholds) > 25)
            avg_games = 34.0 if is_gs else 21.5
            games_arr = np.array([avg_games])
        else:
            games_arr = np.array(total_games)
            avg_games = float(games_arr.mean())
            # Correction cruciale : si l'historique est du BO3 (moyenne < 26) 
            # mais que le match actuel est un Grand Chelem (BO5), on met à l'échelle.
            if is_bo5 and avg_games < 26.0:
                avg_games = avg_games * 1.55
        
        # --- AJUSTEMENT SELON LES PROBABILITÉS DE VICTOIRE ---
        prob_diff = abs(prob_1 - prob_2)
        if prob_diff > 0.4:
            if is_salmon:
                # Joueur "Saumon" très combatif : match plus accroché que prévu
                reduction_factor = 1.0 + (prob_diff * 0.15)
            else:
                # Grand écart de probabilité : match tendanciellement plus court
                reduction_factor = 1.0 - (prob_diff * 0.25)
            avg_games = avg_games * reduction_factor
        
        def get_poisson_over(mu, k):
            if mu <= 0: return 0.0
            k_int = int(math.floor(k))
            prob_le_k, term = 0.0, math.exp(-mu)
            for i in range(k_int + 1):
                prob_le_k += term
                if term < 1e-100: break
                term = term * mu / (i + 1)
            return max(0.0, min(1.0, 1.0 - prob_le_k))

        # Si on a des seuils réels de bookmaker, on les utilise en priorité
        thresholds = real_thresholds if real_thresholds else [x + 0.5 for x in range(16, 45)]
        for threshold in thresholds:
            pct_over = get_poisson_over(avg_games, threshold)
            stats[f"over_{threshold}"] = pct_over
            stats[f"under_{threshold}"] = 1.0 - pct_over
        
        stats["avg_total_games"] = float(avg_games)
        stats["median_total_games"] = float(np.median(games_arr))
        stats["num_matches_analyzed"] = len(total_games) if not use_fallback else 0
        if num_sets:
            sets_arr = np.array(num_sets)
            if len(sets_arr) > 0:
                stats["prob_3sets"] = float((sets_arr >= 3).mean())
                stats["prob_straight_sets"] = float((sets_arr == 2).mean())
    
    return stats

def create_custom_match_row(player1, player2, surface="Hard", level="A"):
    w_data = player1.get_data_df(opponent=player2.id)
    w_data["last_rankings"] = [[player1.ranking]]
    w_data["last_ranking_points"] = [[player1.ranking_points]]
    
    l_data = player2.get_data_df(opponent=player1.id)
    l_data["last_rankings"] = [[player2.ranking]]
    l_data["last_ranking_points"] = [[player2.ranking_points]]
    
    match_data = pd.DataFrame({
        "id": ["custom_match"], "tournament": ["Custom Simulation"], "tournament_level": [level],
        "tournament_date": ["20261231"], "tournament_surface": [surface], "round": ["F"], "best_of": [3], "match_id": ["custom_match"]
    })
    
    to_1 = {col: col + "_1" for col in w_data.columns}
    to_2 = {col: col + "_2" for col in w_data.columns}
        
    concat_1 = pd.concat([w_data.copy().rename(to_1, axis=1), l_data.copy().rename(to_1, axis=1)], axis=0)
    concat_2 = pd.concat([l_data.copy().rename(to_2, axis=1), w_data.copy().rename(to_2, axis=1)], axis=0)
    
    final_df = pd.concat([pd.concat([match_data]*2, axis=0), concat_1, concat_2], axis=1)
    final_df["Winner"] = [0, 1]
    final_df["Name_1"] = [player1.name, player2.name]
    final_df["Name_2"] = [player2.name, player1.name]
    
    row_dict = final_df.iloc[0].to_dict()
    surf = surface.capitalize()
    row_dict["surface_win_pct_1"] = row_dict.get(f"{surf}_Victories_Percentage_1", row_dict.get("Victories_Percentage_1", 50.0))
    row_dict["surface_win_pct_2"] = row_dict.get(f"{surf}_Victories_Percentage_2", row_dict.get("Victories_Percentage_2", 50.0))
    
    return row_dict

def get_mistral_betting_advice(match_row, prob_1, prob_2, p1_name, p2_name, enrichment_p1=None, enrichment_p2=None, **kwargs):
    lang = kwargs.get("lang", "FR").upper()
    surf_1 = match_row.get("surface_win_pct_1", 50.0)
    surf_2 = match_row.get("surface_win_pct_2", 50.0)
    surface_name = match_row.get("tournament_surface", "Inconnue")
    
    enrich_str_1 = ""
    if enrichment_p1:
        if enrichment_p1.get("is_salmon"): enrich_str_1 += " [INDICE SAUMON DETECTE : Victoire clé récente ou bonne performance tournoi!]"
        if enrichment_p1.get("moral_victory"): enrich_str_1 += " [NIVEAU ELITE PROCHE : Score serré face au Top 20 récent!]"
        if enrichment_p1.get("win_top20"): enrich_str_1 += " [CHOC TOP 25 : A battu un membre du Top 25 récemment!]"
        if enrichment_p1.get("top20_endurance_boost"): enrich_str_1 += " [⚡ TOP25 ENDURANCE : Favorisé au 3ème set - match serré]"
        if enrichment_p1.get("home_crowd"): enrich_str_1 += " [🏟️ AVANTAGE DOMICILE : Joue dans son pays]"
        if enrichment_p1.get("collapse_risk"): enrich_str_1 += " [🚨 RISQUE EFFONDREMENT PSYCHOLOGIQUE face au Top25 local]"
    enrich_str_2 = ""
    if enrichment_p2:
        if enrichment_p2.get("is_salmon"): enrich_str_2 += " [INDICE SAUMON DETECTE : Victoire clé récente ou bonne performance tournoi!]"
        if enrichment_p2.get("moral_victory"): enrich_str_2 += " [NIVEAU ELITE PROCHE : Score serré face au Top 20 récent!]"
        if enrichment_p2.get("win_top20"): enrich_str_2 += " [CHOC TOP 25 : A battu un membre du Top 25 récemment!]"
        if enrichment_p2.get("top20_endurance_boost"): enrich_str_2 += " [⚡ TOP25 ENDURANCE : Favorisé au 3ème set - match serré]"
        if enrichment_p2.get("home_crowd"): enrich_str_2 += " [🏟️ AVANTAGE DOMICILE : Joue dans son pays]"
        if enrichment_p2.get("collapse_risk"): enrich_str_2 += " [🚨 RISQUE EFFONDREMENT PSYCHOLOGIQUE face au Top25 local]"
        
    display_surface = surface_name
    surface_map_fr = {"clay": "Terre Battue", "grass": "Gazon", "hard": "Dur"}
    if lang == "FR": display_surface = surface_map_fr.get(surface_name.lower(), surface_name)
    
    endurance_1 = match_row.get("endurance_win_percentage_1", 0)
    endurance_2 = match_row.get("endurance_win_percentage_2", 0)
    
    odds_str = ""
    real_ou_options = []
    odds = kwargs.get("odds")
    if odds:
        o_dict = odds.get("odds", {})
        odds_str = f"\nCOTES BOOKMAKER ({odds.get('bookmaker')}):\n"
        for name, price in o_dict.items(): odds_str += f"- {name}: {price}\n"
        
        # Extraire les seuils Over/Under réels pour l'IA
        if odds.get('totals'):
            real_ou_options = sorted(list(set([t.get('point') for t in odds['totals']])))

    ou_options_str = ""
    if real_ou_options:
        ou_options_str = f"SEUILS OVER/UNDER RÉELS DISPONIBLES : {', '.join([str(x) for x in real_ou_options])} jeux.\n"

    def format_history(matches, p_name):
        if not matches: return "Aucune donnée de match récente."
        lines = []
        for m in matches[:15]:
            rank = f"(#{m.get('opp_rank')})" if m.get('opp_rank') and m.get('opp_rank') != "N/A" else ""
            status_str = f"{p_name} {'A GAGNÉ' if m.get('is_win') else 'A PERDU'} contre {m.get('opponent')} {rank}"
            lines.append(f"- {m.get('date', '')} | {status_str} ({m.get('score')}) @ {m.get('tournament')}")
        return "\n".join(lines)

    history_1 = format_history(enrichment_p1.get("recent_matches", []), p1_name) if enrichment_p1 else "N/A"
    history_2 = format_history(enrichment_p2.get("recent_matches", []), p2_name) if enrichment_p2 else "N/A"

    best_of = match_row.get("best_of", 3)
    max_sets = 3 if str(best_of) == "3" else 5
    format_desc = f"Match en {best_of} sets gagnants (Maximum {max_sets} sets)." if lang == "FR" else f"Best of {best_of} sets match (Maximum {max_sets} sets)."

    prompt = f"""Tu es un Data Analyst expert en tennis. MATCH: {p1_name} vs {p2_name} (Surface: {display_surface} | Format: {format_desc})
DONNÉES DU MODÈLE IA ACTUALISÉES:
- Probabilité de victoire {p1_name} : {prob_1*100:.1f}% {enrich_str_1}
- Probabilité de victoire {p2_name} : {prob_2*100:.1f}% {enrich_str_2}
STATISTIQUES CLÉS FOURNIES:
- {p1_name} : Victoires surface={surf_1:.1f}%, Endurance={endurance_1:.1f}%.
- {p2_name} : Victoires surface={surf_2:.1f}%, Endurance={endurance_2:.1f}%.
HISTORIQUE RÉCENT {p1_name}: {history_1}
HISTORIQUE RÉCENT {p2_name}: {history_2}
{odds_str}
{ou_options_str}
IMPORTANT : 
- Ce match est un {format_desc}. Ne suggère JAMAIS un score impossible (ex: pas de 4 sets si le max est 3).
- Pour l'Over/Under, suggère UNIQUEMENT un seuil parmi les seuils réels listés ci-dessus si possible.
- RÈGLE DE SÉCURITÉ RENFORCÉE : Ne propose un Over/Under que s'il a au moins 75% de probabilité. En dessous de 75%, indique 'Pas de signal O/U fiable ce match'.
- LECTURE DES SCORES : Dans l'historique des matchs, le score indique toujours les sets gagnés/perdus par le vainqueur du match. S'il est indiqué qu'un joueur "a battu" son adversaire, c'est lui qui a gagné le dernier set (ex: 6-0), ne déduis JAMAIS qu'il s'est effondré s'il a remporté la victoire.
- RÈGLE ENDURANCE TOP25 : Si l'écart de probabilité est < 15% et qu'un joueur est Top 25, anticipe systématiquement un 3ème set gagné par le Top 25. Les joueurs Top 25 ont une réserve physique supérieure (métaphore : marathon 60km vs 50km pour les autres).
- RÈGLE EFFONDREMENT : Si un joueur non-Top25 rate des balles de match face à un Top25 endurant qui joue à domicile, anticipe un possible 6/0 ou 6/1 au set suivant (effondrement psychologique).
TON ANALYSE DOIT STRICTEMENT RESPECTER CE FORMAT :
**🏆 GAGNANT POTENTIEL :** [Nom]
**🎯 CONSEIL PRINCIPAL SÉCURISÉ :** [Le pari le plus sûr]
**📊 INDICATEURS OVER/UNDER & SET :**
*   **Over/Under :** [Estimation - UNIQUEMENT si probabilité ≥ 75%, sinon 'Pas de signal fiable']
*   **Risque 3ème set :** [Y a-t-il risque de 3ème set ? Qui le gagne et pourquoi (endurance Top20) ?]
*   **Gagne un set :** [L'outsider peut-il prendre un set ? Précise le nombre de sets total max {max_sets}]
**⚡ FACTEUR ENDURANCE & PSYCHOLOGIE :** [Analyse du facteur Top20 endurance et risque d'effondrement si applicable]
**🎯 ANALYSE DES ACES :** [Suggère un pari sur le 'Vainqueur Aces' ou 'Over/Under Aces']
**📝 ANALYSE MISTRAL (SYNTHÈSE) :** [Synthèse textuelle courte]"""

    last_error = ""
    for i, key in enumerate(API_KEYS):
        try:
            client = configurer_mistral(key)
            response = client.chat.complete(model=CHOSEN_MODEL, messages=[{"role": "user", "content": prompt}])
            return response.choices[0].message.content
        except Exception as e: last_error = str(e)
    return f"❌ Échec de l'analyse IA. (Erreur: {last_error})"

def test_ai_connection():
    last_error = ""
    for i, key in enumerate(API_KEYS):
        try:
            client = configurer_mistral(key)
            response = client.chat.complete(model=CHOSEN_MODEL, messages=[{"role": "user", "content": "Réponds uniquement par le mot 'TEST_OK'."}])
            if response.choices and "TEST_OK" in response.choices[0].message.content.upper(): return True, f"Connexion réussie !"
        except Exception as e: last_error = str(e)
    return False, f"Toutes les clés ont échoué. {last_error}"

def suggest_combined_bet(top_matches):
    """Utilise Mistral IA pour suggérer une combinaison de 1 à 3 pronostics déjà proposés,
    issus de matchs différents. Retourne le texte de la recommandation, ou None en cas d'échec.
    
    Args:
        top_matches: liste de dicts avec au minimum les clés :
            'p1', 'p2', 't_name', 'picks' (liste de picks avec 'type', 'display', 'raw_prob', 'raw_odds')
    """
    if not top_matches or not API_KEYS:
        return None

    # Construire la liste des pronostics disponibles (un seul par match pour éviter la corrélation)
    available_picks = []
    for m in top_matches:
        p1 = m.get('p1', '?')
        p2 = m.get('p2', '?')
        t_name = m.get('t_name', '?')
        picks = m.get('picks', [])
        if not picks:
            continue
        # On prend seulement le meilleur pick du match (celui avec le sort_score le plus haut)
        best_pick = max(picks, key=lambda p: p.get('sort_score', p.get('prob', 0)))
        raw_prob = best_pick.get('raw_prob', best_pick.get('prob', 0.5))
        raw_odds = best_pick.get('raw_odds', 1.80)
        try:
            raw_odds_f = float(raw_odds) if raw_odds else 1.80
        except:
            raw_odds_f = 1.80
        
        available_picks.append({
            'num': len(available_picks) + 1,
            'match': f"{p1} vs {p2}",
            'tournament': t_name,
            'pick_display': best_pick.get('display', '?'),
            'prob': raw_prob,
            'odds': raw_odds_f,
        })

    if len(available_picks) < 2:
        return None

    # Construire le prompt Mistral
    picks_text = ""
    for pk in available_picks:
        picks_text += (
            f"  #{pk['num']} [{pk['tournament']}] {pk['match']}\n"
            f"      Pronostic : {pk['pick_display']}\n"
            f"      Prob IA : {pk['prob']*100:.0f}% | Cote : {pk['odds']:.2f}\n\n"
        )

    prompt = f"""Tu es un expert en paris sportifs tennis. Voici les pronostics du jour déjà validés par notre modèle IA :

{picks_text}

RÈGLES STRICTES :
- Tu ne peux JAMAIS combiner deux pronostics issus du MÊME match.
- Sélectionne entre 1 et 3 pronostics parmi la liste ci-dessus pour former le MEILLEUR combiné possible.
- Choisis en priorité ceux avec la meilleure probabilité IA ET la meilleure cote (meilleur rapport valeur).
- Si les cotes sont toutes très basses (< 1.50), propose seulement 1 ou 2 pronostics.
- Si les probabilités sont très élevées (> 70%), tu peux aller jusqu'à 3 dans le combiné.
- Ne propose JAMAIS plus de 3 pronostics.

FORMAT DE RÉPONSE STRICTEMENT OBLIGATOIRE (utilise exactement ce modèle, sans ajouter d'autre texte avant ou après) :
🎯 COMBINÉ IA DU JOUR
━━━━━━━━━━━━━━━━━━━━
✅ Sélection #{'{'}numéro du pick{'}'}  : [intitulé du pick]
✅ Sélection #{'{'}numéro du pick{'}'}  : [intitulé du pick]  (si 2ème)
✅ Sélection #{'{'}numéro du pick{'}'}  : [intitulé du pick]  (si 3ème)
━━━━━━━━━━━━━━━━━━━━
📊 Cote combinée estimée : X.XX
💡 Justification : [Explication courte en 1-2 phrases pourquoi ces picks forment un bon combiné]"""

    last_error = ""
    for key in API_KEYS:
        try:
            client = configurer_mistral(key)
            response = client.chat.complete(
                model=CHOSEN_MODEL,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            last_error = str(e)
    
    print(f"⚠️ suggest_combined_bet: Mistral indisponible. {last_error}")
    return None


def analyze_tournament_odds(matches, model, used_features, players_db, data_df=None, min_history=10, min_value=1.15, min_odds=1.40, min_prob=0.42, ou_target_prob=0.75, is_global=False, is_mens_tour=True):
    import re as _re
    _seed_pat = _re.compile(r'\((\d+)\)')

    def _get_seed(name):
        """Extrait le numéro de tête de série depuis le nom du joueur, ex: 'Djokovic (1)' → 1"""
        m = _seed_pat.search(str(name))
        return int(m.group(1)) if m else None

    all_winner_candidates = []
    ou_suggestions = [] # Over/Under suggestions (to match the GUI expectation)
    
    for match in matches:
        p1, p2, odds = match['player_1'], match['player_2'], match.get('odds')
        score = str(match['row_data'].get('score', '')).strip().lower()
        if score and score not in ['upcoming', 'none', 'nan']: continue
        
        p1_obj = find_player_by_name(p1, players_db)
        p2_obj = find_player_by_name(p2, players_db)
        
        # Check history
        h1 = len(getattr(p1_obj, 'matches_history', [])) if p1_obj else 0
        h2 = len(getattr(p2_obj, 'matches_history', [])) if p2_obj else 0
        if h1 < min_history or h2 < min_history: continue
        
        prob_1, prob_2, enrich_1, enrich_2, _ = predict_match_outcome(model, match['row_data'], used_features, players_db, p1, p2, match['row_data'].get('tournament'), skip_te_scrape=True)
        is_salmon = enrich_1.get("is_salmon", False) or enrich_2.get("is_salmon", False)

        # ================================================================
        # FILTRE ANTI-OUTSIDER : ne jamais parier contre un top-20 seedé
        # Analyse RG 2026 : 5 paris contre une tête de série <= 20 → 0 gagné,
        # ROI -100%. L'IA recommande systématiquement l'outsider à tort.
        # ================================================================
        seed_1 = _get_seed(p1)
        seed_2 = _get_seed(p2)
        # Un joueur est considéré "tête de série top-20" si son seed est <= 20
        p1_is_seeded_top20 = (seed_1 is not None and seed_1 <= 20)
        p2_is_seeded_top20 = (seed_2 is not None and seed_2 <= 20)
        
        # 1. Value Bets Analysis
        if odds:
            o_dict = odds.get('odds', {})
            for p, prob, opponent_is_top20 in [
                (p1, prob_1, p2_is_seeded_top20),
                (p2, prob_2, p1_is_seeded_top20)
            ]:
                price = o_dict.get(p)
                if price:
                    value = prob * price
                    # Condition 1 : Favoris ou matchs équilibrés (passe le seuil min_prob et min_odds)
                    cond_fav = prob >= min_prob and value >= min_value and price >= min_odds
                    # Condition 2 : Outsiders Modérés (prob >= 0.40 et cote >= 2.00)
                    cond_out = prob >= 0.40 and price >= 2.00 and value >= min_value
                    
                    if cond_fav or cond_out:
                        # -------------------------------------------------------
                        # FILTRE 2 : ne pas jouer l'outsider contre un top-20
                        # Si l'adversaire est seedé ≤ 20 ET qu'on joue le joueur
                        # avec prob < 0.65 (= l'outsider), on ignore ce pari.
                        # Exceptions : si prob >= 0.65 l'IA est très confiante → OK
                        # -------------------------------------------------------
                        if opponent_is_top20 and prob < 0.65:
                            continue
                        all_winner_candidates.append({
                            "match": f"{p1} vs {p2}", 
                            "pick": p, 
                            "prob": prob, 
                            "odds": price, 
                            "value": value, 
                            "bookie": odds.get('bookmaker')
                        })
        
        # 2. Over/Under Analysis
        if data_df is not None:
            surf = str(match['row_data'].get('tournament_surface', 'Hard')).capitalize()
            
            t_name = str(match['row_data'].get('tournament', ''))
            is_grand_slam = any(x in t_name.lower() for x in ["roland", "french", "wimbledon", "australi", "us open", "new york", "grand slam"])
            is_mens_tour_match = 'ATP' in str(match.get('sport_title', '')).upper()
            is_grand_slam_men = is_grand_slam and is_mens_tour_match
            
            ou_stats = calculate_betting_stats(data_df, p1, p2, prob_1, prob_2, surface=surf, is_salmon=is_salmon, is_bo5=is_grand_slam_men)

            best_match_ou = None
            target_prob = ou_target_prob

            # Fallback progressif : si le seuil est trop strict, on le baisse par paliers
            # pour éviter de ne rien afficher du tout
            fallback_steps = [target_prob, max(0.70, target_prob - 0.10), 0.65, 0.60]
            fallback_steps = sorted(set(fallback_steps), reverse=True)  # du plus strict au plus souple
            
            t_name = str(match['row_data'].get('tournament', '')).lower()
            is_grand_slam = any(x in t_name for x in ["roland", "french", "wimbledon", "australi", "us open", "new york", "grand slam"])
            is_grand_slam_men = is_grand_slam and is_mens_tour
            
            if is_grand_slam_men:
                threshold_list_over = [38.5, 37.5, 36.5, 35.5, 34.5, 33.5, 32.5, 31.5, 30.5, 29.5]
                threshold_list_under = [29.5, 30.5, 31.5, 32.5, 33.5, 34.5, 35.5, 36.5, 37.5, 38.5]
            else:
                threshold_list_over = [23.5, 22.5, 21.5, 20.5, 19.5, 18.5, 17.5]
                threshold_list_under = [17.5, 18.5, 19.5, 20.5, 21.5, 22.5, 23.5]

            for tp_try in fallback_steps:
                # On parcourt du plus haut au plus bas
                for threshold in threshold_list_over:
                    p_over = ou_stats.get(f"over_{threshold}", 0)
                    if p_over >= tp_try:
                        best_match_ou = {
                            "match": f"{p1} vs {p2}", "type": "OVER", "threshold": threshold,
                            "prob": p_over, "pick": f"OVER {threshold}"
                        }
                        if tp_try < target_prob:
                            best_match_ou["note"] = f"seuil assoupli à {tp_try*100:.0f}%"
                        break

                if not best_match_ou:
                    for threshold in threshold_list_under:
                        p_under = ou_stats.get(f"under_{threshold}", 0)
                        if p_under >= tp_try:
                            best_match_ou = {
                                "match": f"{p1} vs {p2}", "type": "UNDER", "threshold": threshold,
                                "prob": p_under, "pick": f"UNDER {threshold}"
                            }
                            if tp_try < target_prob:
                                best_match_ou["note"] = f"seuil assoupli à {tp_try*100:.0f}%"
                            break

                if best_match_ou:
                    break  # On a trouvé quelque chose, on s'arrête
            
            if best_match_ou:
                # Tentative de récupération de la cote réelle pour ce seuil
                if odds and odds.get('totals'):
                    for t_outcome in odds['totals']:
                        if t_outcome.get('point') == best_match_ou['threshold'] and \
                           t_outcome.get('name', '').upper() == best_match_ou['type']:
                            best_match_ou['odds'] = t_outcome.get('price')
                            best_match_ou['bookie'] = odds.get('bookmaker')
                            break
                ou_suggestions.append(best_match_ou)
    
    # --- Sélection des Value Bets (déjà filtrés par min_prob dans la boucle) ---
    # On n'utilise PAS de fallback descendant : mieux vaut ne rien afficher
    # que de suggérer des paris à moins de 60% de prob (ROI historique négatif).
    target_prob_winner = min_prob
    opportunities = list(all_winner_candidates)  # déjà filtrés par min_prob + anti-top20
    applied_threshold_winner = target_prob_winner


    opportunities.sort(key=lambda x: x['value'], reverse=True)
    ou_suggestions.sort(key=lambda x: x['prob'], reverse=True)
    
    report = ""
    if is_global:
        report += "🌍 **ANALYSE GLOBALE DU JOUR**\n\n"
        
    if opportunities:
        # On limite l'affichage à 5 résultats maximum (top 5) pour un tournoi, 15 pour global
        top_n = 15 if is_global else 5
        report += f"🚀 **TOP {len(opportunities[:top_n])} VALUE BETS**\n\n"
        for opt in opportunities[:top_n]:
            note_str = f" ⚠️ *{opt['note']}*" if opt.get('note') else ""
            report += f"📍 **{opt['match']}**\n   - Pronostic : **{opt['pick']}**\n   - Probabilité IA : {opt['prob']*100:.1f}%\n   - Cote ({opt['bookie']}) : {opt['odds']}\n   - Indice de Valeur : **{opt['value']:.2f}**{note_str}\n\n"
    else: 
        report = f"✅ Aucun value bet détecté aujourd'hui (seuil prob_ia ≥ {min_prob*100:.0f}% + filtre anti-outsider top-20).\n💡 C'est un bon signe : mieux vaut ne pas parier que parier avec un signal faible.\n\n"
        
    if ou_suggestions:
        report += "\n" + "-"*30 + "\n"
        report += "🎯 **SUGGESTIONS OVER/UNDER (Poisson Model)**\n\n"
        for sug in ou_suggestions[:top_n]:
            odds_str = f" | Cote ({sug['bookie']}) : {sug['odds']}" if sug.get('odds') else ""
            note_str = f" ⚠️ *{sug['note']}*" if sug.get('note') else ""
            report += f"📈 **{sug['match']}**\n   - Type : **{sug['type']} {sug['threshold']}** jeux\n   - Confiance : {sug['prob']*100:.1f}%{odds_str}{note_str}\n\n"

            
    return report, opportunities, ou_suggestions


def backtest_winner_optimizer(data_df, model, used_features, players_db, progress_callback=None, max_matches=600):
    """
    Backteste la prédiction du vainqueur sur les derniers matchs historiques.
    Retourne les métriques de précision pour différentes combinaisons de seuils.
    Dans les données encodées, la class 0 = player 1 gagne (c'est toujours le winner_id).
    """
    from python.data.data_loader import encode_data

    if data_df is None or data_df.empty or model is None or not used_features:
        return {}

    df = data_df.copy()
    if "score" in df.columns:
        df = df[df["score"].notna() & (df["score"] != "Upcoming")].copy()

    date_col = "tournament_date" if "tournament_date" in df.columns else None
    if date_col:
        df = df.sort_values(date_col).tail(max_matches)
    else:
        df = df.tail(max_matches)

    if len(df) < 20:
        return {}

    try:
        encoded = encode_data(df.copy())
    except Exception as e:
        print(f"[backtest_winner] encode error: {e}")
        return {}

    for feat in used_features:
        if feat not in encoded.columns:
            if feat == "diff_ranking" and "Ranking_1" in encoded.columns and "Ranking_2" in encoded.columns:
                encoded["diff_ranking"] = encoded["Ranking_2"] - encoded["Ranking_1"]
            else:
                encoded[feat] = 0.0

    try:
        X = encoded[used_features].fillna(0).values
        all_probs = model.predict_proba(X)
    except Exception as e:
        print(f"[backtest_winner] predict error: {e}")
        return {}

    # Pré-calculer l'historique de chaque joueur
    player_history_count = {}
    for col in ["Name_1", "Name_2"]:
        if col in df.columns:
            for name in df[col].dropna().unique():
                name_str = str(name)
                if name_str not in player_history_count:
                    p_obj = find_player_by_name(name_str, players_db)
                    player_history_count[name_str] = len(getattr(p_obj, 'matches_history', [])) if p_obj else 0

    n_total = len(all_probs)
    min_prob_values = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85]
    min_history_values = [5, 10, 15, 20]
    results = {}

    for combo_idx, (min_prob, min_history) in enumerate(
        [(mp, mh) for mp in min_prob_values for mh in min_history_values]
    ):
        if progress_callback:
            progress_callback(combo_idx / (len(min_prob_values) * len(min_history_values)) * 0.5)
        bets = []
        for i, probs in enumerate(all_probs):
            prob_1, prob_2 = float(probs[0]), float(probs[1])
            if max(prob_1, prob_2) < min_prob:
                continue
            if min_history > 0 and "Name_1" in df.columns:
                row = df.iloc[i]
                h1 = player_history_count.get(str(row.get("Name_1", "")), 0)
                h2 = player_history_count.get(str(row.get("Name_2", "")), 0)
                if h1 < min_history or h2 < min_history:
                    continue
            # prob_1 > prob_2 signifie que le modèle prédit player 1 (= winner réel)
            bets.append(prob_1 > prob_2)

        n_bets = len(bets)
        results[(min_prob, min_history)] = {
            "win_rate": sum(bets) / n_bets if n_bets > 0 else 0.0,
            "n_bets": n_bets,
            "n_correct": sum(bets)
        }

    return results


def backtest_ou_optimizer(data_df, players_db, progress_callback=None, max_matches=600):
    """
    Backteste les prédictions Over/Under en comparant le modèle Poisson
    aux vrais scores historiques.
    """
    import math

    if data_df is None or data_df.empty or "score" not in data_df.columns:
        return {}

    df = data_df[
        data_df["score"].notna() &
        ~data_df["score"].astype(str).str.upper().str.contains(r"UPCOMING|RET|W/O|DEF|ABD", na=True)
    ].copy()

    date_col = "tournament_date" if "tournament_date" in df.columns else None
    if date_col:
        df = df.sort_values(date_col).tail(max_matches)
    else:
        df = df.tail(max_matches)

    if len(df) < 20:
        return {}

    def parse_games(score_str):
        try:
            total = 0
            for s in str(score_str).split():
                if "-" in s:
                    parts = s.split("(")[0].split("-")
                    if len(parts) == 2:
                        total += int(parts[0].strip()) + int(parts[1].strip()[:1])
            return total if total > 8 else None
        except:
            return None

    def poisson_over(mu, k):
        if mu <= 0: return 0.0
        k_int = int(math.floor(k))
        prob_le, term = 0.0, math.exp(-mu)
        for i in range(k_int + 1):
            prob_le += term
            if term < 1e-100: break
            term = term * mu / (i + 1)
        return max(0.0, min(1.0, 1.0 - prob_le))

    thresholds = [17.5, 18.5, 19.5, 20.5, 21.5, 22.5, 23.5]
    target_probs = [0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]
    surfaces = ["Clay", "Hard", "Grass", "All"]

    # Structure: results_tp[surface][tp] = {"signals": 0, "correct": 0}
    results_tp = {s: {tp: {"signals": 0, "correct": 0} for tp in target_probs} for s in surfaces}
    # Structure: results_thresh[surface][threshold] = {"signals": 0, "correct": 0}
    results_thresh = {s: {t: {"signals": 0, "correct": 0} for t in thresholds} for s in surfaces}

    n_total = len(df)
    for idx, (_, row) in enumerate(df.iterrows()):
        if progress_callback and idx % 30 == 0:
            progress_callback(0.5 + (idx / n_total) * 0.5)

        actual = parse_games(row.get("score", ""))
        if actual is None:
            continue

        surf = str(row.get("tournament_surface", "Hard")).capitalize()
        if surf not in ["Clay", "Hard", "Grass"]:
            surf = "Hard"

        p1 = str(row.get("Name_1", ""))
        p2 = str(row.get("Name_2", ""))
        ou_stats = calculate_betting_stats(data_df, p1, p2, 0.5, 0.5, surface=surf)
        avg_games = ou_stats.get("avg_total_games")
        if not avg_games or avg_games < 10:
            continue

        # Trouver le meilleur threshold pour CE match (highest confidence)
        # Exact mirror de analyze_tournament_odds : un seul signal par match
        best_t, best_t_conf, best_t_correct = None, 0.0, False

        for threshold in thresholds:
            p_over = poisson_over(avg_games, threshold)
            p_under = 1.0 - p_over
            conf = max(p_over, p_under)
            bet_is_over = p_over >= p_under
            is_correct = (actual > threshold) if bet_is_over else (actual <= threshold)

            # Stats par threshold (toujours, indépendamment du target_prob)
            for s_key in [surf, "All"]:
                results_thresh[s_key][threshold]["signals"] += 1
                if is_correct:
                    results_thresh[s_key][threshold]["correct"] += 1

            if conf > best_t_conf:
                best_t_conf, best_t, best_t_correct = conf, threshold, is_correct

        # Stats par target_prob : seulement le meilleur signal du match
        if best_t is not None:
            for tp in target_probs:
                if best_t_conf >= tp:
                    for s_key in [surf, "All"]:
                        results_tp[s_key][tp]["signals"] += 1
                        if best_t_correct:
                            results_tp[s_key][tp]["correct"] += 1


    # Build final output
    final = {"by_surface": {}, "threshold_accuracy": {}, "best_target_prob": 0.75, "best_thresholds": {}}

    # Find best target_prob : on cherche le meilleur ÉQUILIBRE précision × couverture
    # Contrainte : le seuil retenu doit couvrir au moins 25% des matchs analysés
    # (si trop peu de matchs passent le filtre, c'est inutilisable en pratique)
    n_total_matches = len(df)  # nombre de matchs analysés
    min_coverage = max(15, int(n_total_matches * 0.25))  # au moins 25% des matchs

    best_score, best_tp = -1.0, 0.75
    for tp in target_probs:
        data = results_tp["All"][tp]
        n, c = data["signals"], data["correct"]
        if n < min_coverage:
            continue  # trop peu de signaux : pas utilisable en pratique
        wr = c / n if n > 0 else 0.0
        # Score = précision × facteur de couverture (croissant jusqu'à 100% du min_coverage)
        coverage_factor = min(1.0, n / (min_coverage * 2))
        score = wr * coverage_factor
        if score > best_score:
            best_score, best_tp = score, tp
    final["best_target_prob"] = best_tp

    for s in surfaces:
        final["by_surface"][s] = {}
        for tp in target_probs:
            d = results_tp[s][tp]
            n, c = d["signals"], d["correct"]
            final["by_surface"][s][tp] = {"win_rate": c / n if n > 0 else 0.0, "n_signals": n}

        final["threshold_accuracy"][s] = {}
        for t in thresholds:
            d = results_thresh[s][t]
            n, c = d["signals"], d["correct"]
            final["threshold_accuracy"][s][t] = {"win_rate": c / n if n > 0 else 0.0, "n_signals": n}

        # Meilleur threshold pour cette surface
        best_t_score, best_t = -1.0, None
        for t in thresholds:
            d = results_thresh[s][t]
            n, c = d["signals"], d["correct"]
            if n >= 10:
                sc = (c / n) * min(1.0, n / 25)
                if sc > best_t_score:
                    best_t_score, best_t = sc, t
        if best_t is not None:
            d = results_thresh[s][best_t]
            n = d["signals"]
            c = d["correct"]
            final["best_thresholds"][s] = {
                "threshold": best_t,
                "win_rate": c / n if n > 0 else 0.0,
                "n_signals": n
            }

    return final
