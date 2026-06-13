import customtkinter as ctk
import pandas as pd
import json
import os
import re
import threading
import time
import smtplib
import io
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from PIL import Image, ImageGrab
from python.app_logic import predict_match_outcome, calculate_betting_stats, find_player_by_name
from python.data.odds_api import get_all_tennis_data

_EMAIL_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "email_config.json")

def short_name(full_name, max_len=14):
    """Abrège prénom ET nom de famille en initiales si le nom est trop long."""
    s = str(full_name).strip()
    if len(s) <= max_len:
        return s
    parts = s.split()
    if len(parts) >= 3:
        return parts[0][0].upper() + ". " + " ".join(parts[1:-1]) + " " + parts[-1][0].upper() + "."
    elif len(parts) == 2:
        return parts[0][0].upper() + ". " + parts[1]
    return s

class TennisBulletinApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Magic Prediction IA - Bulletin Shorts")
        self.geometry("450x850")
        self.configure(fg_color="#050505")
        
        self.accent_color = "#eaff00" 
        self.turquoise = "#00ffd5" 
        self.p1_color = "#00d4ff"
        self.p2_color = "#ff8c00"
        
        self.players_db = {}
        self.data_df = None
        self.odds_data = {"odds": []}
        self.model = None
        self.is_summary_displayed = False
        self._cached_top_matches = None  
        self._cached_combined_bet = None 

        # Chargement des paramètres partagés (optimisés via gui_app.py)
        from python.analysis_settings_manager import load_analysis_settings
        self.analysis_settings = load_analysis_settings()
        self.min_prob_winner = self.analysis_settings.get("min_prob", 0.51)
        self.ou_target_prob = self.analysis_settings.get("ou_target_prob", 0.75)
        self.min_value = self.analysis_settings.get("min_value", 1.01)
        self.min_odds = self.analysis_settings.get("min_odds", 1.65)
        
        self.setup_ui()
        self.load_initial_data()

    def safe_after(self, delay, callback):
        def wrapper():
            try:
                if self.winfo_exists():
                    callback()
            except:
                pass
        try:
            if self.winfo_exists():
                self.after(delay, wrapper)
        except:
            pass

    def setup_ui(self):
        self.header = ctk.CTkFrame(self, fg_color="#111", height=80, corner_radius=0)
        self.header.pack(fill="x")
        self.title_label = ctk.CTkLabel(self.header, text="TENNIS IA PRO", font=ctk.CTkFont(family="Inter", size=28, weight="bold"), text_color=self.turquoise)
        self.title_label.pack(pady=(15, 0))
        self.emoji1 = ctk.CTkLabel(self.header, text="🎾😎👑", font=ctk.CTkFont(size=24), text_color=self.turquoise)
        self.emoji1.place(x=15, y=25)
        self.emoji2 = ctk.CTkLabel(self.header, text="👑😎🎾", font=ctk.CTkFont(size=24), text_color=self.turquoise)
        self.emoji2.place(relx=1.0, x=-15, y=25, anchor="ne")

        self.calc_btn = ctk.CTkButton(self, text="⏳ CHARGEMENT IA...",
                                      font=ctk.CTkFont(size=15, weight="bold"),
                                      height=46, corner_radius=15,
                                      fg_color="#1a3a5c", text_color="#7ec8e3",
                                      hover_color="#1e4a7a",
                                      state="disabled",
                                      command=self.magic_calculate)
        self.calc_btn.pack(fill="x", pady=(20, 4), padx=20)

        self.reveal_btn = ctk.CTkButton(self, text="✨ RÉVÉLER LE BULLETIN ✨",
                                       font=ctk.CTkFont(size=18, weight="bold"),
                                       height=55, corner_radius=27,
                                       fg_color="#2a2a2a", text_color="#555",
                                       hover_color="#444",
                                       state="disabled",
                                       command=self.magic_reveal)
        self.reveal_btn.pack(fill="x", pady=(4, 16), padx=20)

        self.scan_label = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=20, weight="bold"), text_color=self.accent_color)

        self.scroll = ctk.CTkFrame(self, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=10, pady=5)

        self.footer = ctk.CTkFrame(self, fg_color="#111", height=50, corner_radius=0)
        self.footer.pack(fill="x", side="bottom")
        ctk.CTkLabel(self.footer, text="ABONNE-TOI POUR LES PRONOS ! 🎾", font=ctk.CTkFont(size=14, weight="bold"), text_color=self.accent_color).pack(pady=15)
        
        self.blue_cycle = ["#00ffd5", "#00d2d8", "#00a5dc", "#0078df", "#004be3", "#001ee6", "#00008b"]
        self.blue_cycle += self.blue_cycle[-2:0:-1]
        
        self.yellow_cycle = ["#eaff00", "#77ff00", "#00ff00", "#ff0000", "#ff5500", "#ffaa00", "#ffcc00"]
        self.yellow_cycle += self.yellow_cycle[-2:0:-1]
        
        self.color_idx = 0
        self.animate_colors()

    def animate_colors(self):
        self.color_idx = (self.color_idx + 1) % len(self.blue_cycle)
        new_blue = self.blue_cycle[self.color_idx]
        idx_y = self.color_idx % len(self.yellow_cycle)
        new_yellow = self.yellow_cycle[idx_y]
        
        self.title_label.configure(text_color=new_blue)
        self.emoji1.configure(text_color=new_blue)
        self.emoji2.configure(text_color=new_blue)
        
        if self.calc_btn.cget("state") == "normal":
            self.calc_btn.configure(fg_color=new_blue, text_color="white")
        if self.reveal_btn.cget("state") == "normal":
            self.reveal_btn.configure(fg_color=new_yellow, text_color="black")
            
        self.safe_after(250, self.animate_colors)

    def load_initial_data(self):
        def _load():
            try:
                from python.app_logic import get_data_and_train_model
                import pandas as pd
                
                df, model, features, db = get_data_and_train_model(
                    progress_callback=lambda m: self.safe_after(0, lambda: self.calc_btn.configure(text=f"⏳ ATP: {m[:15]}...")),
                    tour="ATP"
                )
                
                df_wta, model_wta, features_wta, db_wta = get_data_and_train_model(
                    progress_callback=lambda m: self.safe_after(0, lambda: self.calc_btn.configure(text=f"⏳ WTA: {m[:15]}...")),
                    skip_training=False,
                    tour="WTA"
                )
                
                self.data_df = df
                self.model_atp = model
                self.model_wta = model_wta
                self.used_features_atp = features
                self.used_features_wta = features_wta
                self.players_db_atp = db
                self.players_db_wta = db_wta
                
                # Merge them into self.players_db for any generic usage
                self.players_db = {**db, **db_wta}
                
                self.odds_data = get_all_tennis_data()
                
                self.safe_after(0, lambda: self.calc_btn.configure(
                    state="normal", text="🔄 CALCULER LES OPPORTUNITÉS",
                    fg_color="#1a3a5c", text_color="#7ec8e3"
                ))
            except Exception as e:
                print(f"Error loading: {e}")
                self.safe_after(0, lambda: self.calc_btn.configure(text="❌ ERREUR CHARGEMENT"))
        
        threading.Thread(target=_load, daemon=True).start()

    def animate_wheel(self):
        if getattr(self, 'spinning', False) and hasattr(self, 'wheel_canvas'):
            self.wheel_canvas.delete("all")
            colors = ["#ff1493", "#00ff9d", "#ff9d00", "#3498db", "#9b59b6", "#f1c40f"]
            num_slices = len(colors)
            slice_angle = 360 / num_slices
            
            for i, color in enumerate(colors):
                start = self.spin_angle + i * slice_angle
                self.wheel_canvas.create_arc(10, 10, 90, 90, start=start, extent=slice_angle, fill=color, outline="")
                
            self.spin_angle = (self.spin_angle + 15) % 360
            self.safe_after(40, self.animate_wheel)
            
    def stop_wheel(self):
        self.spinning = False
        if hasattr(self, 'wheel_canvas'):
            self.wheel_canvas.pack_forget()
            self.wheel_canvas.destroy()

    def magic_calculate(self):
        self.calc_btn.configure(state="disabled", text="⏳ CALCUL EN COURS...")
        self.reveal_btn.configure(state="disabled", fg_color="#2a2a2a", text_color="#555", hover_color="#444")
        self.scan_label.pack(pady=5)

        for widget in self.scroll.winfo_children():
            widget.destroy()

        def _scan():
            self.safe_after(0, lambda: self.scan_label.configure(text="🔄 MISE À JOUR DES JOUEURS..."))
            try:
                from python.data.rapidapi_client import client
                from python.data.tennisexplorer_scraper import (
                    scrape_player_rapidapi_history,
                    scrape_player_te_history,
                    merge_te_to_base_socle
                )
                from python.data.te_cache import load_te_cache, save_te_cache
                from datetime import datetime as _dt_upd
                import time as _time_upd

                _all_odds = self.odds_data.get('odds', [])
                _unique_players = set()
                for _m in _all_odds:
                    _t_low = str(_m.get('sport_title', '')).lower()
                    if any(x in _t_low for x in [
                        "challenger", "itf", "srx", "utr", "exhibition",
                        "m15", "m25", "w15", "w25", "w35", "w50", "w75", "w100", "future"
                    ]):
                        continue
                    _unique_players.add(_m.get('home_team', ''))
                    _unique_players.add(_m.get('away_team', ''))
                _unique_players.discard('')

                if _unique_players:
                    _today = _dt_upd.now().strftime("%Y-%m-%d")
                    try:
                        client.populate_id_map_for_date(_today, tour="atp")
                        client.populate_id_map_for_date(_today, tour="wta")
                    except Exception:
                        pass

                    _total_p = len(_unique_players)
                    for _idx_p, _p_name in enumerate(_unique_players, 1):
                        self.safe_after(0, lambda i=_idx_p, t=_total_p, p=_p_name:
                            self.scan_label.configure(text=f"🔄 MAJ joueurs ({i}/{t}) : {p[:22]}")
                        )

                        # CORRECTION : On utilise la fonction intelligente de l'app principale
                        _p_obj = find_player_by_name(_p_name, self.players_db)

                        if _p_obj:
                            real_p_name = _p_obj.name # On utilise le vrai nom
                            if getattr(_p_obj, '_te_updated', False):
                                continue
                                
                            _r_id = client.get_player_id_by_name(real_p_name, tour="atp")
                            if not _r_id:
                                _r_id = client.get_player_id_by_name(real_p_name, tour="wta")

                            try:
                                _te_data = load_te_cache(real_p_name)
                                if _te_data:
                                    print(f"[Cache] Bulletin utilise données récentes pour {real_p_name}")
                                elif _r_id:
                                    _te_data = scrape_player_rapidapi_history(real_p_name, _r_id)
                                    save_te_cache(real_p_name, _te_data)
                                else:
                                    _te_data = scrape_player_te_history(real_p_name, nb_years=3)
                                    save_te_cache(real_p_name, _te_data)
                                
                                _p_obj.update_with_live_charting()
                                merge_te_to_base_socle(_p_obj, _te_data, self.players_db)
                                _p_obj.inject_scraped_history(_te_data)
                                _p_obj.latest_te_data = _te_data
                                _p_obj._te_updated = True
                            except Exception as _e_p:
                                print(f"⚠️ Bulletin MAJ {real_p_name}: {_e_p}")
                                
                            _time_upd.sleep(0.05)

                    print(f"✅ Bulletin : {_total_p} joueurs mis à jour avant analyse.")

            except Exception as _e_update:
                print(f"⚠️ Bulletin phase mise à jour: {_e_update}")

            self.safe_after(0, lambda: self.scan_label.configure(text="🎯 ANALYSE IA EN COURS..."))
            self.safe_after(0, lambda: self.reveal_btn.configure(text="⏳ GÉNÉRATION DU BULLETIN..."))
            
            match_data = []
            matches = self.odds_data.get('odds', [])
            total = len(matches)
            
            seen_signatures = []
            
            for i, match in enumerate(matches):
                try:
                    p1_raw, p2_raw = match['home_team'], match['away_team']
                    t_name = match.get('sport_title', 'Tennis')
                    
                    # Déterminer si c'est WTA ou ATP DÈS MAINTENANT pour éviter de confondre frère et soeur !
                    sport_title_upper = str(match.get('sport_title', '')).upper()
                    t_name_upper = str(t_name).upper()
                    is_wta = 'WTA' in sport_title_upper or 'WOMEN' in sport_title_upper or 'WTA' in t_name_upper or 'WOMEN' in t_name_upper
                    
                    target_db = self.players_db_wta if is_wta else self.players_db_atp
                    
                    # CORRECTION : Conversion des noms bookmakers en noms réels
                    _p1_obj_b = find_player_by_name(p1_raw, target_db)
                    _p2_obj_b = find_player_by_name(p2_raw, target_db)
                    
                    p1 = _p1_obj_b.name if _p1_obj_b else p1_raw
                    p2 = _p2_obj_b.name if _p2_obj_b else p2_raw
                    
                    # --- DÉDOUBLONNAGE ROBUSTE ---
                    import re
                    def is_same_player(n1, n2):
                        n1, n2 = str(n1).lower(), str(n2).lower()
                        if n1 == n2: return True
                        w1 = set(re.findall(r'[a-z]{4,}', n1))
                        w2 = set(re.findall(r'[a-z]{4,}', n2))
                        return bool(w1.intersection(w2))
                    
                    is_duplicate = False
                    for (s_p1, s_p2) in seen_signatures:
                        m11 = is_same_player(p1, s_p1)
                        m22 = is_same_player(p2, s_p2)
                        m12 = is_same_player(p1, s_p2)
                        m21 = is_same_player(p2, s_p1)
                        
                        same = (m11 and m22) or (m12 and m21)
                        if not same:
                            w1A = set(re.findall(r'[a-z]{4,}', p1.lower()))
                            w2A = set(re.findall(r'[a-z]{4,}', p2.lower()))
                            w1B = set(re.findall(r'[a-z]{4,}', s_p1.lower()))
                            w2B = set(re.findall(r'[a-z]{4,}', s_p2.lower()))
                            
                            if m11 and (not w2A or not w2B): same = True
                            elif m22 and (not w1A or not w1B): same = True
                            elif m12 and (not w2A or not w1B): same = True
                            elif m21 and (not w1A or not w2B): same = True
                        
                        if same:
                            is_duplicate = True
                            break
                            
                    if is_duplicate:
                        continue
                    seen_signatures.append((p1, p2))
                    
                    o1, o2 = "-", "-"
                    bookmakers = match.get('bookmakers', [])
                    
                    def _robust_bk_match(bk_name, ref_p):
                        import re as _re2
                        def _norm2(n):
                            n = str(n).lower().replace('.', ' ').replace('-', ' ')
                            return set(w for w in _re2.findall(r'[a-z]{3,}', n))
                        w1, w2 = _norm2(bk_name), _norm2(ref_p)
                        if not w1 or not w2: return False
                        return bool(w1.intersection(w2))
                    
                    if bookmakers:
                        b = bookmakers[0]
                        markets = b.get('markets', [])
                        for m in markets:
                            if m.get('key') == 'h2h':
                                outcomes = m.get('outcomes', [])
                                for out in outcomes:
                                    out_name = out.get('name', '')
                                    if _robust_bk_match(out_name, p1_raw) and not _robust_bk_match(out_name, p2_raw):
                                        o1 = out.get('price', '-')
                                    elif _robust_bk_match(out_name, p2_raw) and not _robust_bk_match(out_name, p1_raw):
                                        o2 = out.get('price', '-')
                                # Fallback: positional if still missing
                                if (o1 == "-" or o2 == "-") and len(outcomes) >= 2:
                                    o1 = outcomes[0].get('price', '-')
                                    o2 = outcomes[1].get('price', '-')
                                break
                                        
                    if o1 == "-" or o2 == "-":
                        continue
                    if float(o1) < 1.15 or float(o2) < 1.15:
                        continue
                        
                    commence_time_str = match.get('commence_time')
                    if commence_time_str:
                        try:
                            from datetime import datetime, timezone
                            match_time = datetime.strptime(commence_time_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                            if match_time < datetime.now(timezone.utc):
                                continue
                            if match_time.astimezone().date() > datetime.now().astimezone().date():
                                continue
                        except:
                            pass
                            
                    # On ne garde que la vérification des exclusions génériques
                    t_name_low = t_name.lower()
                    if any(x in t_name_low for x in ["challenger", "itf", "srx", "utr", "exhibition", "m15", "m25", "w15", "w25", "w35", "w50", "w75", "w100", "future"]):
                        continue
                        
                    t_name = t_name.replace(" - Singles", "").replace(" - Doubles", "")
                    t_short = t_name if len(t_name) <= 20 else t_name[:18].rstrip() + "."
                    
                    endur_1 = getattr(_p1_obj_b, 'endurance_win_percentage', 50.0) if _p1_obj_b else 50.0
                    endur_2 = getattr(_p2_obj_b, 'endurance_win_percentage', 50.0) if _p2_obj_b else 50.0
                    match_title = f"[{t_short}]\n{short_name(p1)} [E:{endur_1:.0f}%] ({o1}) vs {short_name(p2)} [E:{endur_2:.0f}%] ({o2})"
                    
                    real_thresholds = []
                    over_odds_map = {} 
                    if match.get('totals'):
                        for _t in match['totals']:
                            try:
                                pt = float(_t.get('point', 0))
                                if pt > 15.0:
                                    real_thresholds.append(pt)
                                    if 'price' in _t:
                                        over_odds_map[pt] = float(_t['price'])
                            except: pass
                        real_thresholds = sorted(list(set(real_thresholds)))
                    
                    _t_surf_low = t_name.lower()
                    if any(x in _t_surf_low for x in [
                        "roland", "garros", "french open", "clay", "terre battue",
                        "barcelona", "madrid", "monte carlo", "rome", "internazionali",
                        "buenos aires", "rio", "estoril", "lyon", "geneva", "hamburg"
                    ]):
                        _surface = "Clay"
                    elif any(x in _t_surf_low for x in [
                        "wimbledon", "grass", "halle", "queens", "nottingham", "hertogenbosch", "s-hertogenbosch"
                    ]):
                        _surface = "Grass"
                    else:
                        _surface = "Hard"

                    _level = "G" if any(x in _t_surf_low for x in [
                        "roland", "garros", "french open", "wimbledon",
                        "australian", "us open", "grand slam"
                    ]) else "M"

                    # is_wta est déjà calculé plus haut
                    
                    # CORRECTION : Variables de format exactes comme app principale
                    best_of_val = 5 if _level == "G" and not is_wta else 3

                    row = {
                        'player_1': p1, 'player_2': p2,
                        'Name_1': p1, 'Name_2': p2,
                        'tournament': t_name,
                        'tournament_surface': _surface,
                        'tournament_level': _level,
                        'round': 'R32',
                        'best_of': best_of_val
                    }

                    if _p1_obj_b: row['Aces_Percentage_1'] = getattr(_p1_obj_b, 'aces_percentage', 0.0)
                    if _p2_obj_b: row['Aces_Percentage_2'] = getattr(_p2_obj_b, 'aces_percentage', 0.0)

                    current_model = self.model_wta if is_wta else self.model_atp
                    current_features = self.used_features_wta if is_wta else self.used_features_atp

                    te_p1 = getattr(_p1_obj_b, 'latest_te_data', None) if _p1_obj_b else None
                    te_p2 = getattr(_p2_obj_b, 'latest_te_data', None) if _p2_obj_b else None

                    prob_1, prob_2, enrich_1, enrich_2, _ = predict_match_outcome(
                        current_model, row, current_features, self.players_db, p1, p2,
                        tournament_name=t_name, skip_te_scrape=True, te_p1=te_p1, te_p2=te_p2
                    )
                    
                    is_salmon_match = enrich_1.get("is_salmon", False) or enrich_2.get("is_salmon", False)
                    salmon_boost = 0.5 if is_salmon_match else 0.0
                    if is_salmon_match:
                        match_title = f"🐟 {match_title}"
                    if enrich_1.get("home_crowd") or enrich_2.get("home_crowd"):
                        match_title = f"🏟️ {match_title}"
                    
                    current_match_picks = []
                    
                    min_odds = self.min_odds
                    min_value = self.min_value
                    
                    winner_candidates = []
                    model_is_blind = (abs(prob_1 - 0.5) < 0.001 and abs(prob_2 - 0.5) < 0.001)

                    # CORRECTION : Filtre Top 20 basé sur le vrai ranking et non le seed texte
                    p1_top20 = (_p1_obj_b and _p1_obj_b.ranking and 0 < _p1_obj_b.ranking <= 25)
                    p2_top20 = (_p2_obj_b and _p2_obj_b.ranking and 0 < _p2_obj_b.ranking <= 25)

                    try:
                        o1_f = float(o1)
                        v1 = prob_1 * o1_f
                        
                        cond_fav_1 = prob_1 >= self.min_prob_winner and v1 >= min_value and o1_f >= min_odds
                        cond_out_1 = prob_1 >= 0.40 and o1_f >= 2.00 and v1 >= min_value
                        
                        if cond_fav_1 or cond_out_1:
                            if not (p2_top20 and prob_1 < 0.60):
                                winner_candidates.append((p1, prob_1, o1_f))
                    except: pass
                    
                    try:
                        o2_f = float(o2)
                        v2 = prob_2 * o2_f
                        
                        cond_fav_2 = prob_2 >= self.min_prob_winner and v2 >= min_value and o2_f >= min_odds
                        cond_out_2 = prob_2 >= 0.40 and o2_f >= 2.00 and v2 >= min_value
                        
                        if cond_fav_2 or cond_out_2:
                            if not (p1_top20 and prob_2 < 0.60):
                                winner_candidates.append((p2, prob_2, o2_f))
                    except: pass

                    if model_is_blind and not winner_candidates:
                        try:
                            o1_f = float(o1)
                            o2_f = float(o2)
                            if o1_f >= 3.0 and o1_f > o2_f:
                                winner_candidates.append((p1, 0.33, o1_f))
                            elif o2_f >= 3.0 and o2_f > o1_f:
                                winner_candidates.append((p2, 0.33, o2_f))
                        except: pass
                    
                    for w_name, w_prob, w_odds in winner_candidates:
                        underdog_bonus = 0.40 if w_odds >= 3.0 else (0.20 if w_odds >= 2.0 else 0.0)
                        
                        current_match_picks.append({
                            'type': 'Winner',
                            'prob': w_prob,
                            'sort_score': w_prob + salmon_boost + underdog_bonus,
                            'display': f"🏆 {short_name(w_name).upper()} (Cote: {w_odds:.2f})",
                            'prob_text': f"Probabilité estimée : {w_prob:.0%}" if w_prob > 0 else None,
                            'raw_player': w_name,
                            'raw_odds': w_odds,
                            'raw_prob': w_prob,
                        })
                    
                    is_grand_slam = any(x in t_name.lower() for x in ["roland", "french", "wimbledon", "australi", "us open", "new york", "grand slam"])
                    is_grand_slam_men = is_grand_slam and not is_wta

                    bet_stats = calculate_betting_stats(self.data_df, p1, p2, prob_1, prob_2, surface=_surface, real_thresholds=real_thresholds if real_thresholds else None, is_salmon=is_salmon_match, is_bo5=is_grand_slam_men)

                    balance = min(prob_1, prob_2)
                    balance_ratio = balance / 0.5

                    if is_grand_slam_men:
                        ideal_threshold = 27.5 + balance_ratio * 13.0
                        full_range = [t * 0.5 for t in range(55, 83)]
                    else:
                        ideal_threshold = 18.5 + balance_ratio * 9.0
                        full_range = [t * 0.5 for t in range(37, 57)]

                    ideal_threshold = round(ideal_threshold * 2) / 2

                    fav_player = p1 if prob_1 > prob_2 else p2
                    if balance >= 0.45:
                        context = "⚔️ MATCH SERRÉ"
                    elif balance >= 0.35:
                        context = "📊 MATCH ÉQUILIBRÉ"
                    elif balance >= 0.25:
                        context = f"💪 FAVORI : {short_name(fav_player).upper()}"
                    else:
                        context = f"🎯 GRAND FAVORI : {short_name(fav_player).upper()}"

                    if real_thresholds:
                        near = sorted([t for t in real_thresholds if abs(t - ideal_threshold) <= 3.5])
                        thresholds_to_check = near if near else sorted(real_thresholds)
                    else:
                        thresholds_to_check = sorted([
                            t for t in full_range if abs(t - ideal_threshold) <= 3.0
                        ])
                        if not thresholds_to_check:
                            thresholds_to_check = [ideal_threshold]

                    min_ou_prob = min(0.45, self.ou_target_prob)
                    best_ou = None

                    for threshold in thresholds_to_check:
                        p_over = bet_stats.get(f"over_{threshold}", 0)
                        if p_over >= min_ou_prob:
                            best_ou = {
                                'type': 'O/U',
                                'prob': p_over,
                                'sort_score': p_over + salmon_boost,
                                'display': f"🔥 OVER {threshold} ({context})",
                                'prob_text': f"Probabilité estimée : {p_over:.0%}" if p_over > 0 else None,
                                'raw_threshold': threshold,
                                'raw_prob': p_over,
                                'raw_odds': over_odds_map.get(threshold, None),
                            }
                        else:
                            break

                    if not best_ou and thresholds_to_check:
                        fallback_t = min(thresholds_to_check, key=lambda t: abs(t - ideal_threshold))
                        p_over = bet_stats.get(f"over_{fallback_t}", 0)
                        if p_over >= 0.38:
                            best_ou = {
                                'type': 'O/U',
                                'prob': p_over,
                                'sort_score': p_over + salmon_boost,
                                'display': f"🔥 OVER {fallback_t} ({context})",
                                'prob_text': f"Probabilité estimée : {p_over:.0%}",
                                'raw_threshold': fallback_t,
                                'raw_prob': p_over,
                                'raw_odds': over_odds_map.get(fallback_t, None),
                            }
                            
                    if best_ou:
                        current_match_picks.append(best_ou)
                            
                    if current_match_picks:
                        current_match_picks.sort(key=lambda x: x['sort_score'], reverse=True)
                        current_match_picks = current_match_picks[:2]
                        
                        match_data.append({
                            'title': match_title,
                            'picks': current_match_picks,
                            'max_score': max(p['sort_score'] for p in current_match_picks),
                            'is_wta': is_wta,
                            'p1': p1, 'p2': p2, 't_name': t_name,
                            'o1': o1, 'o2': o2,
                            'over_odds_map': over_odds_map,
                        })
                            
                except Exception as e:
                    pass
            
            self.safe_after(0, lambda: self.scan_label.configure(text="SÉLECTION DES MEILLEURS PARIS..."))
            time.sleep(1.5)
            
            match_data.sort(key=lambda x: x['max_score'], reverse=True)
            
            wta_matches = [m for m in match_data if m.get('is_wta', False)]
            top_matches = []
            
            if wta_matches:
                top_matches.append(wta_matches[0])
                match_data.remove(wta_matches[0])
                
            for m in match_data:
                if len(top_matches) >= 6:
                    break
                top_matches.append(m)
                
            top_matches.sort(key=lambda x: x['max_score'], reverse=True)

            self.auto_save_to_bilan(top_matches)

            self.safe_after(0, lambda: self.scan_label.configure(text="🤖 COMBINÉ IA EN COURS..."))
            try:
                from python.app_logic import suggest_combined_bet
                combined = suggest_combined_bet(top_matches)
                self._cached_combined_bet = combined
                print(f"✅ Combiné IA généré." if combined else "ℹ️ Pas de combiné IA disponible.")
            except Exception as e_cb:
                self._cached_combined_bet = None
                print(f"⚠️ Erreur combiné IA: {e_cb}")

            self._cached_top_matches = top_matches
            _n = len(top_matches)
            self.safe_after(0, lambda: self.scan_label.pack_forget())
            self.safe_after(0, lambda: self.calc_btn.configure(
                state="normal", text="🔄 RECALCULER",
                fg_color="#1a3a5c", text_color="#7ec8e3"
            ))
            self.safe_after(0, lambda: self.reveal_btn.configure(
                state="normal", text="✨ RÉVÉLER LE BULLETIN ✨",
                fg_color=self.accent_color, text_color="black", hover_color="#d4e600"
            ))
            print(f"✅ Calcul terminé : {_n} pronos prêts. Cliquez sur ✨ RÉVÉLER pour enregistrer le Short.")

        threading.Thread(target=_scan, daemon=True).start()

    def magic_reveal(self):
        if not self._cached_top_matches:
            return

        self.reveal_btn.configure(state="disabled", text="⏳ ANIMATION EN COURS...")

        for widget in self.scroll.winfo_children():
            widget.destroy()

        self.wheel_canvas = ctk.CTkCanvas(self, width=100, height=100, bg="#050505", highlightthickness=0)
        self.wheel_canvas.pack(pady=10)
        self.spin_angle = 0
        self.spinning = True
        self.animate_wheel()

        def _do_reveal():
            import time as _t_rev
            _t_rev.sleep(1.5)
            self.safe_after(0, self.stop_wheel)
            self.safe_after(150, lambda: self.display_picks(self._cached_top_matches))

        threading.Thread(target=_do_reveal, daemon=True).start()

    def auto_save_to_bilan(self, top_matches):
        try:
            import python.betting_manager as bm
            stake = 10.0
            count = 0
            existing_preds = bm.load_predictions()
            existing_ids = {p.get("id") for p in existing_preds if p.get("id")}

            for m in top_matches:
                p1 = m.get('p1', '')
                p2 = m.get('p2', '')
                t_name = m.get('t_name', 'Bulletin')
                o1_raw = m.get('o1', '-')
                o2_raw = m.get('o2', '-')
                over_odds_map = m.get('over_odds_map', {})

                if not p1 or not p2:
                    continue

                for pick in m.get('picks', []):
                    try:
                        pick_type = pick.get('type', '')
                        raw_prob = pick.get('raw_prob', pick.get('prob', 0.5))

                        if pick_type == 'Winner':
                            raw_player = pick.get('raw_player', p1)
                            raw_odds = float(pick.get('raw_odds', 1.80))
                            pick_label = f"WIN {raw_player}"
                            bet_type = "Value"
                            odds = raw_odds

                        elif pick_type == 'O/U':
                            threshold = pick.get('raw_threshold', 22.5)
                            raw_odds = pick.get('raw_odds', None)

                            if raw_odds is None:
                                try:
                                    avg_match_odds = (float(o1_raw) + float(o2_raw)) / 2
                                    fair = 0.93 / max(raw_prob, 0.10)
                                    estimated = round(min(max(fair * 0.6 + avg_match_odds * 0.4, 1.40), 2.80), 2)
                                except:
                                    estimated = round(min(max(0.93 / max(raw_prob, 0.10), 1.40), 2.80), 2)
                                odds = estimated
                            else:
                                odds = float(raw_odds)

                            pick_label = f"OVER {threshold}"
                            bet_type = "OU"
                        else:
                            continue

                        match_id = bm.get_prediction_id(p1, p2, t_name, bet_type)
                        if match_id in existing_ids:
                            continue

                        match_info = {
                            "player_1": p1, "player_2": p2,
                            "tournament": t_name,
                            "match_id": match_id
                        }
                        bm.add_prediction(match_info, pick_label, odds, raw_prob, stake)
                        count += 1
                    except Exception as e:
                        print(f"❌ Bulletin auto-save pick: {e}")

            if count > 0:
                print(f"✅ Bulletin: {count} pronos sauvegardés automatiquement dans le bilan.")
            else:
                print("ℹ️ Bulletin: Aucun nouveau prono à ajouter (tous déjà présents au bilan).")
        except Exception as e:
            print(f"❌ auto_save_to_bilan: {e}")

    def display_picks(self, top_matches):
        if not top_matches:
            for widget in self.scroll.winfo_children(): widget.destroy()
            ctk.CTkLabel(self.scroll, text="Aucun pari fiable trouvé aujourd'hui.",
                         font=ctk.CTkFont(size=18)).pack(expand=True)
            self.reveal_btn.configure(state="normal")
            return

        def get_pick_color(text):
            if "OVER" in text: return "#2ecc71"
            if "UNDER" in text: return "#e74c3c"
            if "🏆" in text: return "#f1c40f"
            return "white"

        def show_match(idx):
            for widget in self.scroll.winfo_children():
                widget.destroy()

            if idx < len(top_matches):
                match = top_matches[idx]
                n_picks = len(match.get('picks', []))

                top_sp = ctk.CTkFrame(self.scroll, fg_color="transparent", height=2)
                top_sp.pack(expand=True, fill="y")

                card = ctk.CTkFrame(self.scroll, fg_color="#151515", corner_radius=20,
                                    border_width=2, border_color=self.accent_color)
                card.pack(fill="x", padx=20)

                pick_size = 22 if n_picks <= 1 else 20

                title_color = "#b57bee" if match.get('is_wta') else "#aaa"
                ctk.CTkLabel(card, text=match['title'],
                             font=ctk.CTkFont(family="Helvetica", size=15),
                             text_color=title_color, wraplength=380,
                             justify="center").pack(pady=(20, 12), padx=10)

                for p in match['picks']:
                    pick_color = get_pick_color(p['display'])
                    ctk.CTkLabel(card, text=p['display'],
                                 font=ctk.CTkFont(family="Helvetica", size=pick_size, weight="bold"),
                                 text_color=pick_color, wraplength=380,
                                 justify="center").pack(pady=(8, 0), padx=10)
                    if p.get('prob_text'):
                        ctk.CTkLabel(card, text=p['prob_text'],
                                     font=ctk.CTkFont(family="Helvetica", size=13),
                                     text_color="#aaaaaa",
                                     justify="center").pack(pady=(0, 8))

                ctk.CTkLabel(card, text="").pack(pady=8)

                bot_sp = ctk.CTkFrame(self.scroll, fg_color="transparent", height=2)
                bot_sp.pack(expand=True, fill="y")

                self.safe_after(3000, lambda: show_match(idx + 1))

            else:
                n = len(top_matches)
                has_combo = bool(getattr(self, '_cached_combined_bet', None))

                total_rows = n + (3 if has_combo else 0)
                if total_rows <= 8:
                    title_sz, match_sz, pick_sz, pad_y = 15, 11, 12, (5, 3)
                elif total_rows <= 12:
                    title_sz, match_sz, pick_sz, pad_y = 13, 10, 11, (3, 2)
                else:
                    title_sz, match_sz, pick_sz, pad_y = 11, 9, 10, (2, 1)

                card = ctk.CTkFrame(self.scroll, fg_color="#111", corner_radius=15,
                                    border_width=1, border_color="#555")
                card.pack(fill="x", padx=5, pady=4)

                ctk.CTkLabel(card, text="📝 RÉSUMÉ DU JOUR",
                             font=ctk.CTkFont(family="Helvetica", size=title_sz, weight="bold"),
                             text_color=self.accent_color).pack(pady=pad_y)

                for m in top_matches:
                    summary_title_color = "#b57bee" if m.get('is_wta') else "#aaa"
                    ctk.CTkLabel(card, text=m['title'],
                                 font=ctk.CTkFont(family="Helvetica", size=match_sz),
                                 text_color=summary_title_color,
                                 wraplength=400, justify="center").pack(pady=(pad_y[0], 0), padx=5)

                    picks_frame = ctk.CTkFrame(card, fg_color="transparent")
                    picks_frame.pack(pady=(0, pad_y[1]))

                    for i, p in enumerate(m['picks']):
                        pick_color = get_pick_color(p['display'])
                        if i > 0:
                            ctk.CTkLabel(picks_frame, text=" | ",
                                         font=ctk.CTkFont(family="Helvetica", size=pick_sz, weight="bold"),
                                         text_color="#555").pack(side="left", padx=1)
                        summary_text = p['display']
                        if p.get('raw_prob', 0) > 0:
                            summary_text += f" ({p['raw_prob']:.0%})"
                        ctk.CTkLabel(picks_frame, text=summary_text,
                                     font=ctk.CTkFont(family="Helvetica", size=pick_sz, weight="bold"),
                                     text_color=pick_color).pack(side="left")

                if has_combo:
                    combo_sz = max(pick_sz - 1, 9)
                    sep = ctk.CTkFrame(card, fg_color="#f1c40f", height=1)
                    sep.pack(fill="x", padx=15, pady=(pad_y[0], 0))
                    ctk.CTkLabel(card, text="🤖 COMBINÉ IA DU JOUR",
                                 font=ctk.CTkFont(family="Helvetica", size=combo_sz + 1, weight="bold"),
                                 text_color="#f1c40f").pack(pady=(pad_y[0], 0))
                    ctk.CTkLabel(card, text=self._cached_combined_bet,
                                 font=ctk.CTkFont(family="Courier New", size=combo_sz),
                                 text_color="#ffe082", wraplength=400,
                                 justify="left").pack(pady=(0, pad_y[1]), padx=10)

                self.is_summary_displayed = True
                self.reveal_btn.configure(state="normal")
                threading.Thread(target=self.send_pronos_by_email, daemon=True).start()

        show_match(0)

    def _load_email_config(self):
        try:
            with open(_EMAIL_CONFIG_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"sender_email": "", "sender_app_password": "", "recipient_email": ""}

    def _save_email_config(self, cfg):
        try:
            with open(_EMAIL_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=4)
        except Exception as e:
            print(f"⚠️ Impossible de sauvegarder email_config.json : {e}")

    def show_email_setup_dialog(self, cfg):
        result = {"ok": False}

        dlg = ctk.CTkToplevel(self)
        dlg.title("⚙️ Configuration Email")
        dlg.geometry("420x400")
        dlg.grab_set()
        dlg.configure(fg_color="#111")

        ctk.CTkLabel(dlg, text="📧 Configuration de l'envoi email",
                     font=ctk.CTkFont(size=16, weight="bold"),
                     text_color="#eaff00").pack(pady=(20, 4))
        ctk.CTkLabel(dlg,
                     text="Utilisez un compte Gmail + Mot de passe d'application.\n"
                          "(Google → Compte → Sécurité → Mots de passe d'application)",
                     font=ctk.CTkFont(size=11), text_color="#aaa",
                     justify="center").pack(pady=(0, 16))

        def field(label, default="", show=""):
            ctk.CTkLabel(dlg, text=label, font=ctk.CTkFont(size=12),
                         text_color="#ccc", anchor="w").pack(fill="x", padx=30)
            e = ctk.CTkEntry(dlg, show=show, width=360)
            e.insert(0, default)
            e.pack(pady=(2, 10), padx=30)
            return e

        e_sender    = field("Email expéditeur (Gmail) :", cfg.get("sender_email", ""))
        e_password  = field("Mot de passe d'application (16 car.) :",
                            cfg.get("sender_app_password", ""), show="*")
        e_recipient = field("Email destinataire (votre portable) :",
                            cfg.get("recipient_email", ""))

        def on_save():
            cfg["sender_email"]        = e_sender.get().strip()
            cfg["sender_app_password"] = e_password.get().strip()
            cfg["recipient_email"]     = e_recipient.get().strip()
            self._save_email_config(cfg)
            result["ok"] = True
            dlg.destroy()

        def on_cancel():
            dlg.destroy()

        btn_frame = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_frame.pack(pady=10)
        ctk.CTkButton(btn_frame, text="✅ Enregistrer", fg_color="#27ae60",
                      hover_color="#2ecc71", command=on_save).pack(side="left", padx=10)
        ctk.CTkButton(btn_frame, text="Annuler", fg_color="gray",
                      command=on_cancel).pack(side="left", padx=10)

        self.wait_window(dlg)
        return result["ok"]

    def send_pronos_by_email(self):
        try:
            cfg = self._load_email_config()

            if not cfg.get("sender_email") or not cfg.get("sender_app_password") or not cfg.get("recipient_email"):
                ok = [False]
                def _ask():
                    ok[0] = self.show_email_setup_dialog(cfg)
                self.after(0, _ask)
                import time as _t
                for _ in range(600):
                    _t.sleep(0.1)
                    cfg2 = self._load_email_config()
                    if cfg2.get("sender_email") and cfg2.get("sender_app_password"):
                        cfg = cfg2
                        break
                else:
                    print("⚠️ Email non configuré — envoi annulé.")
                    return

            sender    = cfg["sender_email"]
            password  = cfg["sender_app_password"].replace(" ", "")
            recipient = cfg["recipient_email"]

            self.update_idletasks()
            x  = self.winfo_rootx()
            y  = self.winfo_rooty()
            w  = self.winfo_width()
            h  = self.winfo_height()
            screenshot = ImageGrab.grab(bbox=(x, y, x + w, y + h))

            img_bytes = io.BytesIO()
            screenshot.save(img_bytes, format="PNG")
            img_bytes.seek(0)

            import datetime
            today = datetime.date.today().strftime("%d/%m/%Y")

            msg = MIMEMultipart("related")
            msg["From"]    = sender
            msg["To"]      = recipient
            msg["Subject"] = f"🎾 Tennis IA Pro — Bulletin du {today}"

            html = f"""\
<html><body style="background:#111;color:#eee;font-family:Arial;padding:20px">
  <h2 style="color:#eaff00">🎾 Tennis IA Pro — Bulletin du {today}</h2>
  <p>Bonjour ! Voici vos pronostics du jour :</p>
  <img src="cid:bulletin" style="border:2px solid #eaff00;border-radius:12px;max-width:100%">
  <p style="color:#aaa;font-size:12px">Envoyé automatiquement par Magic Prediction IA</p>
</body></html>"""

            msg.attach(MIMEText(html, "html"))

            img_mime = MIMEImage(img_bytes.read(), name="bulletin.png")
            img_mime.add_header("Content-ID", "<bulletin>")
            img_mime.add_header("Content-Disposition", "inline", filename="bulletin.png")
            msg.attach(img_mime)

            with smtplib.SMTP("smtp.gmail.com", 587) as server:
                server.ehlo()
                server.starttls()
                server.login(sender, password)
                server.sendmail(sender, recipient, msg.as_string())

            print(f"✅ Bulletin envoyé par email à {recipient}")

        except smtplib.SMTPAuthenticationError:
            print("❌ Email : authentification Gmail échouée. Vérifiez le mot de passe d'application.")
            self.safe_after(0, lambda: self._show_email_toast("❌ Erreur auth Gmail", ok=False))
        except Exception as e:
            print(f"❌ Erreur envoi email : {e}")
            self.safe_after(0, lambda: self._show_email_toast(f"❌ Erreur : {str(e)[:40]}", ok=False))

    def _show_email_toast(self, message, ok=True):
        color = "#27ae60" if ok else "#c0392b"
        toast = ctk.CTkLabel(self, text=message,
                             font=ctk.CTkFont(size=13, weight="bold"),
                             fg_color=color, text_color="white",
                             corner_radius=8)
        toast.place(relx=0.5, rely=0.95, anchor="center")
        self.after(4000, toast.destroy)

if __name__ == "__main__":
    app = TennisBulletinApp()
    app.mainloop()