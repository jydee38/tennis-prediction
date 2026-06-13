import customtkinter as ctk
import threading
import pandas as pd
from python.app_logic import predict_match_outcome, calculate_betting_stats, find_player_by_name, get_data_and_train_model
from python.data.odds_api import get_all_tennis_data

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

class TennisDailyAllApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Magic Prediction IA - Tous les matchs du jour")
        self.geometry("800x800")
        self.configure(fg_color="#050505")
        
        self.players_db = {}
        self.data_df = None
        self.odds_data = {"odds": []}
        self.model_atp = None
        self.model_wta = None
        self.used_features_atp = None
        self.used_features_wta = None

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
        self.title_label = ctk.CTkLabel(self.header, text="PRONOSTICS DU JOUR (TOUS LES MATCHS)", font=ctk.CTkFont(family="Inter", size=24, weight="bold"), text_color="#00ffd5")
        self.title_label.pack(pady=(20, 20))

        self.btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.btn_frame.pack(fill="x", pady=(15, 15), padx=20)
        
        self.calc_btn = ctk.CTkButton(self.btn_frame, text="⏳ CHARGEMENT IA...",
                                      font=ctk.CTkFont(size=16, weight="bold"),
                                      height=45, corner_radius=10,
                                      state="disabled",
                                      command=self.analyze_all_matches)
        self.calc_btn.pack(side="left", fill="x", expand=True, padx=(0, 5))
        
        self.email_btn = ctk.CTkButton(self.btn_frame, text="📧 ENVOYER PAR MAIL",
                                       font=ctk.CTkFont(size=16, weight="bold"),
                                       height=45, width=220, corner_radius=10,
                                       fg_color="#8e44ad", hover_color="#9b59b6",
                                       state="disabled",
                                       command=self.send_pronos_by_email)
        self.email_btn.pack(side="right", padx=(5, 0))

        # Les onglets
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        
        self.tab_daily = self.tabview.add("Aujourd'hui / Demain")
        self.tab_history = self.tabview.add("Historique")
        
        self.tabview.set("Aujourd'hui / Demain")
        
        self.scroll = ctk.CTkScrollableFrame(self.tab_daily, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True)
        
        self.scroll_history = ctk.CTkScrollableFrame(self.tab_history, fg_color="transparent")
        self.scroll_history.pack(fill="both", expand=True)
        
        self.load_history()

    def load_history(self):
        for widget in self.scroll_history.winfo_children():
            widget.destroy()
            
        history = {}
        import os
        if os.path.exists("data/daily_predictions_history.json"):
            try:
                import json
                with open("data/daily_predictions_history.json", 'r', encoding='utf-8') as f:
                    history = json.load(f)
            except: pass
            
        if not history:
            ctk.CTkLabel(self.scroll_history, text="Aucun historique trouvé.", font=ctk.CTkFont(size=18)).pack(expand=True, pady=50)
            return
            
        sorted_hist = sorted(history.values(), key=lambda x: x.get('saved_at', ''), reverse=True)
        
        for m in sorted_hist:
            m_frame = ctk.CTkFrame(self.scroll_history, fg_color="#1a1a1a", corner_radius=10)
            m_frame.pack(fill="x", pady=5, padx=5)
            
            h_frame = ctk.CTkFrame(m_frame, fg_color="transparent")
            h_frame.pack(fill="x", padx=15, pady=(5, 0))
            
            date_saved_str = ""
            if "saved_at" in m:
                try:
                    from datetime import datetime
                    d = datetime.fromisoformat(m["saved_at"])
                    date_saved_str = f" [Sauvé le {d.strftime('%d/%m à %H:%M')}]"
                except: pass
                
            ctk.CTkLabel(h_frame, text=f"🏆 {m['t_name']}{date_saved_str}", font=ctk.CTkFont(size=12, weight="bold"), text_color="#aaa").pack(side="left")
            
            lbl_text = f"{m.get('date_str', '')} {m['p1']} vs {m['p2']}"
            ctk.CTkLabel(m_frame, text=lbl_text.strip(), font=ctk.CTkFont(size=13, weight="bold"), text_color="white").pack(anchor="w", padx=15, pady=(2, 0))
            
            prob_text = f"Victoire : {m['p1']} {m['prob_1']:.0%} vs {m['p2']} {m['prob_2']:.0%} | {m.get('max_val_str', '')}"
            ctk.CTkLabel(m_frame, text=prob_text, font=ctk.CTkFont(size=12), text_color="#7ec8e3").pack(anchor="w", padx=15)
            
            if m.get('best_ou'):
                if m['best_ou']['prob'] > 0:
                    ou_text = f"Conseil O/U : {m['best_ou']['display']} (Prob estimée : {m['best_ou']['prob']:.0%})"
                else:
                    ou_text = f"Conseil O/U : {m['best_ou']['display']}"
                ctk.CTkLabel(m_frame, text=ou_text, font=ctk.CTkFont(size=12, weight="bold"), text_color="#2ecc71").pack(anchor="w", padx=15, pady=(0, 5))

    def load_initial_data(self):
        def _load():
            try:
                df, model, features, db = get_data_and_train_model(
                    progress_callback=lambda m: self.safe_after(0, lambda: self.calc_btn.configure(text=f"⏳ ATP: {m[:20]}...")),
                    tour="ATP"
                )
                
                df_wta, model_wta, features_wta, db_wta = get_data_and_train_model(
                    progress_callback=lambda m: self.safe_after(0, lambda: self.calc_btn.configure(text=f"⏳ WTA: {m[:20]}...")),
                    skip_training=False,
                    tour="WTA"
                )
                
                self.data_df = pd.concat([df, df_wta], ignore_index=True)
                self.model_atp = model
                self.model_wta = model_wta
                self.used_features_atp = features
                self.used_features_wta = features_wta
                # IMPORTANT: Garder les deux DBs strictement séparées pour ne pas mélanger homme/femme
                self.players_db_atp = db        # DB ATP pure
                self.players_db_wta = db_wta    # DB WTA pure
                self.players_db = {**db, **db_wta}  # Merge pour usage générique
                
                self.safe_after(0, lambda: self.calc_btn.configure(text="⏳ FETCHING ODDS..."))
                # Force le rechargement des cotes pour avoir des dates fraîches du jour
                self.odds_data = get_all_tennis_data(force_update=True)
                
                self.safe_after(0, lambda: self.calc_btn.configure(
                    state="normal", text="🎯 ANALYSER TOUS LES MATCHS",
                    fg_color="#1a3a5c", text_color="#7ec8e3"
                ))
            except Exception as e:
                self.safe_after(0, lambda: self.calc_btn.configure(text=f"ERREUR INITIALISATION: {str(e)}"))

        threading.Thread(target=_load, daemon=True).start()


    def analyze_all_matches(self):
        self.calc_btn.configure(state="disabled", text="⏳ ANALYSE EN COURS...")
        for widget in self.scroll.winfo_children():
            widget.destroy()

        def _calc():
            try:
                all_matches_list = [] # Global list to sort by Value Bet
                seen_signatures = [] # Pour éviter les doublons
                
                from datetime import datetime, timezone
                import pandas as pd
                now_local = datetime.now().astimezone()
                
                for idx, match in enumerate(self.odds_data.get('odds', [])):
                    if idx % 5 == 0:
                        self.safe_after(0, lambda i=idx: self.calc_btn.configure(text=f"⏳ ANALYSE ({i}/{len(self.odds_data['odds'])})..."))
                        
                    p1, p2 = match.get('home_team'), match.get('away_team')
                    t_name = str(match.get('sport_title', match.get('tournament', ''))).replace(" - Singles", "").replace(" - Doubles", "")
                    
                    if not p1 or not p2: continue
                    
                    # Filtre anti-doublons
                    import re
                    def is_same_player(n1, n2):
                        n1, n2 = str(n1).lower(), str(n2).lower()
                        if n1 == n2: return True
                        w1 = set(re.findall(r'[a-z]{4,}', n1))
                        w2 = set(re.findall(r'[a-z]{4,}', n2))
                        return bool(w1.intersection(w2))
                        
                    is_dup = False
                    for (s_p1, s_p2) in seen_signatures:
                        if (is_same_player(p1, s_p1) and is_same_player(p2, s_p2)) or (is_same_player(p1, s_p2) and is_same_player(p2, s_p1)):
                            is_dup = True; break
                    if is_dup: continue
                    seen_signatures.append((p1, p2))
                    
                    # Extraction et formatage de la date
                    commence_time_str = match.get('commence_time')
                    match_date_str = ""
                    day_cat = "AUTRE"
                    if commence_time_str:
                        try:
                            match_time_utc = datetime.strptime(commence_time_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                            match_time_local = match_time_utc.astimezone()
                            
                            today_local = now_local.date()
                            match_date_local = match_time_local.date()
                            
                            if match_date_local == today_local:
                                match_date_str = f" [{match_time_local.strftime('%H:%M')}]"
                                day_cat = "AUJOURD'HUI"
                            elif match_date_local == (now_local + pd.Timedelta(days=1)).date():
                                match_date_str = f" [{match_time_local.strftime('%H:%M')}]"
                                day_cat = "DEMAIN"
                            elif match_date_local == (now_local - pd.Timedelta(days=1)).date():
                                # Cotes en cache d'hier : TennisExplorer met parfois la date d'hier en UTC
                                # (ex: 15:00 heure locale = 13:00 UTC mais si l'écart dépasse minuit → hier)
                                # On les traite comme aujourd'hui car ils sont dans les cotes du jour
                                match_date_str = f" [{match_time_local.strftime('%H:%M')}]"
                                day_cat = "AUJOURD'HUI"
                            else:
                                match_date_str = f" [{match_time_local.strftime('%d/%m %H:%M')}]"
                        except:
                            # Si on ne peut pas parser la date, on assume que c'est aujourd'hui
                            # car les cotes sont filtrées pour être récentes
                            day_cat = "AUJOURD'HUI"
                            
                    sport_title_upper = str(match.get('sport_title', '')).upper()
                    t_name_upper = t_name.upper()
                    t_name_low = t_name.lower()
                    
                    # Exclusion forte pour éviter les challengers, itf etc. comme dans le bulletin
                    if any(x in t_name_low for x in ["challenger", "itf", "srx", "utr", "exhibition", "m15", "m25", "w15", "w25", "w35", "w50", "w75", "w100", "future"]):
                        continue
                        
                    is_wta = 'WTA' in sport_title_upper or 'WOMEN' in sport_title_upper or 'WTA' in t_name_upper or 'WOMEN' in t_name_upper
                    
                    _t_surf_low = t_name.lower()
                    if any(x in _t_surf_low for x in ["roland", "french", "clay", "monte-carlo", "rome", "madrid", "barcelona", "estoril", "munich", "houston", "marrakech", "buenos aires", "rio", "santiago", "cordoba"]):
                        _surface = "Clay"
                    elif any(x in _t_surf_low for x in ["wimbledon", "grass", "halle", "queens", "nottingham", "hertogenbosch", "s-hertogenbosch"]):
                        _surface = "Grass"
                    else:
                        _surface = "Hard"

                    _level = "G" if any(x in _t_surf_low for x in ["roland", "garros", "french open", "wimbledon", "australian", "us open", "grand slam"]) else "M"
                    best_of_val = 5 if _level == "G" and not is_wta else 3

                    _p1_obj = find_player_by_name(p1, self.players_db_wta if is_wta else self.players_db_atp)
                    _p2_obj = find_player_by_name(p2, self.players_db_wta if is_wta else self.players_db_atp)
                    
                    api_p1, api_p2 = p1, p2
                    if _p1_obj: p1 = _p1_obj.name
                    if _p2_obj: p2 = _p2_obj.name

                    row = {
                        'player_1': p1, 'player_2': p2,
                        'Name_1': p1, 'Name_2': p2,
                        'tournament': t_name,
                        'tournament_surface': _surface,
                        'tournament_level': _level,
                        'round': 'R32',
                        'best_of': best_of_val
                    }
                    
                    current_model = self.model_wta if is_wta else self.model_atp
                    current_features = self.used_features_wta if is_wta else self.used_features_atp

                    te_p1 = getattr(_p1_obj, 'latest_te_data', None) if _p1_obj else None
                    te_p2 = getattr(_p2_obj, 'latest_te_data', None) if _p2_obj else None

                    try:
                        prob_1, prob_2, enrich_1, enrich_2, _ = predict_match_outcome(
                            current_model, row, current_features, self.players_db, p1, p2,
                            tournament_name=t_name, skip_te_scrape=True, te_p1=te_p1, te_p2=te_p2
                        )
                        
                        is_salmon_match = enrich_1.get("is_salmon", False) or enrich_2.get("is_salmon", False)
                        is_grand_slam = any(x in t_name.lower() for x in ["roland", "french", "wimbledon", "australi", "us open", "new york", "grand slam"])
                        is_grand_slam_men = is_grand_slam and not is_wta
                        
                        bet_stats = calculate_betting_stats(self.data_df, p1, p2, prob_1, prob_2, surface=_surface, is_salmon=is_salmon_match, is_bo5=is_grand_slam_men)
                        
                        balance = min(prob_1, prob_2)
                        balance_ratio = balance / 0.5
                        
                        if is_grand_slam_men:
                            ideal_threshold = 27.5 + balance_ratio * 13.0
                            full_range = [t * 0.5 for t in range(55, 83)]
                        else:
                            ideal_threshold = 18.5 + balance_ratio * 9.0
                            full_range = [t * 0.5 for t in range(37, 57)]

                        ideal_threshold = round(ideal_threshold * 2) / 2
                        
                        thresholds_to_check = sorted([t for t in full_range if abs(t - ideal_threshold) <= 3.0])
                        if not thresholds_to_check: thresholds_to_check = [ideal_threshold]

                        best_ou = None
                        for threshold in thresholds_to_check:
                            p_over = bet_stats.get(f"over_{threshold}", 0)
                            if p_over > 0.60:
                                best_ou = {"display": f"OVER {threshold}", "prob": p_over}
                            else:
                                break

                        # Format odds and Calculate Value Bet
                        o1, o2 = "-", "-"
                        v1, v2 = 0.0, 0.0
                        bookmakers = match.get('bookmakers', [])
                        
                        # Robust name matching for odds (bookmaker names can differ: "Tiafoe F.(6)" vs "Tiafoe F.")
                        def _robust_name_match(bk_name, ref_p):
                            import re as _re
                            def _norm(n):
                                n = str(n).lower().replace('.', ' ').replace('-', ' ')
                                return set(w for w in _re.findall(r'[a-z]{3,}', n))
                            w1, w2 = _norm(bk_name), _norm(ref_p)
                            if not w1 or not w2:
                                return False
                            return bool(w1.intersection(w2))
                        
                        if bookmakers:
                            markets = bookmakers[0].get('markets', [])
                            if markets:
                                outcomes = markets[0].get('outcomes', [])
                                for out in outcomes:
                                    out_name = out.get('name', '')
                                    if _robust_name_match(out_name, api_p1) and not _robust_name_match(out_name, api_p2):
                                        o1 = str(out.get('price', '-'))
                                        try: v1 = (prob_1 * float(o1)) - 1
                                        except: pass
                                    elif _robust_name_match(out_name, api_p2) and not _robust_name_match(out_name, api_p1):
                                        o2 = str(out.get('price', '-'))
                                        try: v2 = (prob_2 * float(o2)) - 1
                                        except: pass
                                # Fallback: if still not found, just take by position
                                if o1 == "-" and o2 == "-" and len(outcomes) >= 2:
                                    o1 = str(outcomes[0].get('price', '-'))
                                    o2 = str(outcomes[1].get('price', '-'))
                                    try: v1 = (prob_1 * float(o1)) - 1
                                    except: pass
                                    try: v2 = (prob_2 * float(o2)) - 1
                                    except: pass
                                        
                        max_value = max(v1, v2)
                        
                        if v1 > v2 and v1 > 0:
                            max_val_str = f"Value {p1} : +{v1*100:.1f}%"
                        elif v2 > v1 and v2 > 0:
                            max_val_str = f"Value {p2} : +{v2*100:.1f}%"
                        else:
                            max_val_str = f"Value : {max_value*100:.1f}%"
                            
                        all_matches_list.append({
                            't_name': t_name,
                            'p1': p1, 'p2': p2, 'o1': o1, 'o2': o2,
                            'prob_1': prob_1, 'prob_2': prob_2,
                            'v1': v1, 'v2': v2, 'max_value': max_value,
                            'max_val_str': max_val_str,
                            'best_ou': best_ou, 'is_wta': is_wta,
                            'date_str': match_date_str, 'day_cat': day_cat,
                            '_p1_obj': _p1_obj, '_p2_obj': _p2_obj
                        })
                    except Exception as e:
                        print(f"Erreur probabilité pour {p1} vs {p2} : {e}")

                all_matches_list.sort(key=lambda x: x['max_value'], reverse=True)
                self.safe_after(0, lambda: self.display_matches(all_matches_list))
                
            except Exception as e:
                self.safe_after(0, lambda: self.calc_btn.configure(text=f"ERREUR: {str(e)}", state="normal"))

        threading.Thread(target=_calc, daemon=True).start()

    def display_matches(self, all_matches_list):
        self.calc_btn.configure(text="🎯 ANALYSER TOUS LES MATCHS", state="normal")
        
        self.last_analyzed_matches = all_matches_list
        if all_matches_list:
            self.email_btn.configure(state="normal")
        else:
            self.email_btn.configure(state="disabled")
            
        if not all_matches_list:
            ctk.CTkLabel(self.scroll, text="Aucun match trouvé.", font=ctk.CTkFont(size=18)).pack(expand=True, pady=50)
            return
            
        today_matches = [m for m in all_matches_list if m.get('day_cat') in ["AUJOURD'HUI", "AUTRE"]]
        tomorrow_matches = [m for m in all_matches_list if m.get('day_cat') == "DEMAIN"]
        other_matches = [m for m in all_matches_list if m.get('day_cat') not in ["AUJOURD'HUI", "AUTRE", "DEMAIN"]]
        
        def render_section(title, matches, color):
            if not matches: return
            
            # En-tête de section
            ctk.CTkLabel(self.scroll, text=title, font=ctk.CTkFont(size=22, weight="bold"), text_color=color).pack(pady=(25, 10))
            
            for m in matches:
                m_frame = ctk.CTkFrame(self.scroll, fg_color="#1a1a1a", corner_radius=10)
                m_frame.pack(fill="x", pady=8, padx=5)
                
                color_t = "#b57bee" if m['is_wta'] else "#aaa"
                
                # Header frame for Title and Value Badge
                h_frame = ctk.CTkFrame(m_frame, fg_color="transparent")
                h_frame.pack(fill="x", padx=15, pady=(10, 2))
                
                ctk.CTkLabel(h_frame, text=f"🏆 {m['t_name']}", font=ctk.CTkFont(size=14, weight="bold"), text_color=color_t).pack(side="left")
                
                # Value Bet display
                val_text = f"🔥 {m['max_val_str']}" if m['max_value'] > 0 else m['max_val_str']
                val_color = "#2ecc71" if m['max_value'] > 0 else "#e74c3c"
                ctk.CTkLabel(h_frame, text=val_text, font=ctk.CTkFont(size=14, weight="bold"), text_color=val_color).pack(side="right")
                
                # Names, odds, and date
                lbl_text = f"{m['date_str']} {m['p1']} ({m['o1']}) vs {m['p2']} ({m['o2']})"
                name_color = "#ff99cc" if m['is_wta'] else "#3498db"
                
                n_frame = ctk.CTkFrame(m_frame, fg_color="transparent")
                n_frame.pack(fill="x", padx=15, pady=(5, 0))
                
                ctk.CTkLabel(n_frame, text=lbl_text.strip(), font=ctk.CTkFont(size=14, weight="bold"), text_color=name_color).pack(side="left")
                
                from python.gui_shared import show_player_matches_details
                if m.get('_p2_obj'):
                    ctk.CTkButton(n_frame, text="Détails P2", width=60, height=20, font=ctk.CTkFont(size=11), fg_color="#444", hover_color="#666",
                                  command=lambda p=m['_p2_obj']: show_player_matches_details(self, p)).pack(side="right", padx=(5, 0))
                if m.get('_p1_obj'):
                    ctk.CTkButton(n_frame, text="Détails P1", width=60, height=20, font=ctk.CTkFont(size=11), fg_color="#444", hover_color="#666",
                                  command=lambda p=m['_p1_obj']: show_player_matches_details(self, p)).pack(side="right", padx=(10, 0))
                # Probs and Value per player
                p1_v_str = f" [Value: +{m['v1']*100:.1f}%]" if m['v1'] > 0 else ""
                p2_v_str = f" [Value: +{m['v2']*100:.1f}%]" if m['v2'] > 0 else ""
                prob_text = f"Victoire : {m['p1']} {m['prob_1']:.0%}{p1_v_str} vs {m['p2']} {m['prob_2']:.0%}{p2_v_str}"
                ctk.CTkLabel(m_frame, text=prob_text, font=ctk.CTkFont(size=13), text_color="#7ec8e3").pack(anchor="w", padx=15)
                
                # O/U
                if m['best_ou']:
                    if m['best_ou']['prob'] > 0:
                        ou_text = f"Conseil O/U : {m['best_ou']['display']} (Prob estimée : {m['best_ou']['prob']:.0%})"
                    else:
                        ou_text = f"Conseil O/U : {m['best_ou']['display']}"
                    ctk.CTkLabel(m_frame, text=ou_text, font=ctk.CTkFont(size=13, weight="bold"), text_color="#2ecc71").pack(anchor="w", padx=15, pady=(0, 10))

        render_section("📅 AUJOURD'HUI", today_matches, "#f1c40f")
        render_section("📅 DEMAIN", tomorrow_matches, "#bdc3c7")
        render_section("📅 AUTRES DATES", other_matches, "#7f8c8d")
        
        # Save to history
        def _save_history():
            try:
                import os, json
                from datetime import datetime
                history = {}
                if os.path.exists("data/daily_predictions_history.json"):
                    with open("data/daily_predictions_history.json", 'r', encoding='utf-8') as f:
                        history = json.load(f)
                
                for m in all_matches_list:
                    match_id = f"{m['p1']}_vs_{m['p2']}"
                    history[match_id] = {
                        "t_name": m["t_name"],
                        "p1": m["p1"], "p2": m["p2"],
                        "prob_1": m["prob_1"], "prob_2": m["prob_2"],
                        "max_val_str": m["max_val_str"],
                        "best_ou": m["best_ou"],
                        "date_str": m.get("date_str", ""),
                        "saved_at": datetime.now().isoformat()
                    }
                    
                os.makedirs("data", exist_ok=True)
                with open("data/daily_predictions_history.json", 'w', encoding='utf-8') as f:
                    json.dump(history, f, indent=4, ensure_ascii=False)
                    
                self.safe_after(0, self.load_history)
            except Exception as e:
                print(f"History save error: {e}")
                
        threading.Thread(target=_save_history, daemon=True).start()

    # --- Email Logic ---
    def _load_email_config(self):
        try:
            import json, os
            cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "email_config.json")
            if os.path.exists(cfg_path):
                with open(cfg_path, encoding="utf-8") as f:
                    return json.load(f)
        except Exception: pass
        return {"sender_email": "", "sender_app_password": "", "recipient_email": ""}

    def _save_email_config(self, cfg):
        try:
            import json, os
            cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "email_config.json")
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=4)
        except Exception as e:
            print(f"Erreur sauvegarde config email: {e}")

    def show_email_setup_dialog(self, cfg):
        result = {"ok": False}
        dlg = ctk.CTkToplevel(self)
        dlg.title("⚙️ Configuration Email")
        dlg.geometry("420x400")
        dlg.grab_set()
        dlg.configure(fg_color="#111")

        ctk.CTkLabel(dlg, text="⚙️ Configuration de l'envoi email", font=ctk.CTkFont(size=16, weight="bold"), text_color="#eaff00").pack(pady=(20, 4))
        ctk.CTkLabel(dlg, text="Utilisez un compte Gmail + Mot de passe d'application.", font=ctk.CTkFont(size=11), text_color="#aaa", justify="center").pack(pady=(0, 16))

        def field(label, default="", show=""):
            ctk.CTkLabel(dlg, text=label, font=ctk.CTkFont(size=12), text_color="#ccc", anchor="w").pack(fill="x", padx=30)
            e = ctk.CTkEntry(dlg, show=show, width=360)
            e.insert(0, default)
            e.pack(pady=(2, 10), padx=30)
            return e

        e_sender = field("Email expéditeur (Gmail) :", cfg.get("sender_email", ""))
        e_password = field("Mot de passe d'application (16 car.) :", cfg.get("sender_app_password", ""), show="*")
        e_recipient = field("Email destinataire (votre portable) :", cfg.get("recipient_email", ""))

        def on_save():
            cfg["sender_email"] = e_sender.get().strip()
            cfg["sender_app_password"] = e_password.get().strip()
            cfg["recipient_email"] = e_recipient.get().strip()
            self._save_email_config(cfg)
            result["ok"] = True
            dlg.destroy()

        def on_cancel():
            dlg.destroy()

        btn_frame = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_frame.pack(pady=10)
        ctk.CTkButton(btn_frame, text="✅ Enregistrer", fg_color="#27ae60", hover_color="#2ecc71", command=on_save).pack(side="left", padx=10)
        ctk.CTkButton(btn_frame, text="Annuler", fg_color="gray", command=on_cancel).pack(side="left", padx=10)

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
                    return

            sender = cfg["sender_email"]
            password = cfg["sender_app_password"].replace(" ", "")
            recipient = cfg["recipient_email"]

            import datetime, smtplib
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText
            
            today = datetime.date.today().strftime("%d/%m/%Y")
            msg = MIMEMultipart("related")
            msg["From"] = sender
            msg["To"] = recipient
            msg["Subject"] = f"🎾 Tennis IA Pro - Tous les matchs du {today}"

            html = f"""<html>
<body style="background:#111; color:#eee; font-family:Arial; padding:20px">
  <h2 style="color:#00ffd5">🎾 Tennis IA Pro - Tous les matchs du {today}</h2>
  <p>Bonjour ! Voici l'ensemble des matchs analysés du jour :</p>
"""
            
            for m in getattr(self, 'last_analyzed_matches', []):
                t_color = "#ff99cc" if m.get('is_wta') else "#3498db"
                val_color = "#2ecc71" if m.get('max_value', 0) > 0 else "#e74c3c"
                val_text = m.get('max_val_str', '')
                
                html += f"""
                <div style="border-left: 4px solid {t_color}; padding-left: 10px; margin-bottom: 20px; background:#1a1a1a; padding: 15px; border-radius: 8px;">
                    <div style="font-size: 14px; font-weight: bold; color: {t_color}; margin-bottom: 5px;">🏆 {m.get('t_name', '')}</div>
                    <div style="font-size: 16px; font-weight: bold; margin-bottom: 5px; color: white;">{m.get('date_str', '')} {m.get('p1', '')} ({m.get('o1', '-')}) vs {m.get('p2', '')} ({m.get('o2', '-')})</div>
                    <div style="font-size: 14px; color: #7ec8e3; margin-bottom: 5px;">Victoire : {m.get('p1', '')} {m.get('prob_1', 0):.0%} vs {m.get('p2', '')} {m.get('prob_2', 0):.0%}</div>
                    <div style="font-size: 14px; font-weight: bold; color: {val_color}; margin-bottom: 5px;">🔥 {val_text}</div>
                """
                if m.get('best_ou'):
                    prob_str = f" (Prob estimée : {m['best_ou']['prob']:.0%})" if m['best_ou']['prob'] > 0 else ""
                    html += f"<div style='font-size: 14px; font-weight: bold; color: #2ecc71; margin-top: 5px;'>Conseil O/U : {m['best_ou']['display']}{prob_str}</div>"
                html += "</div>"
                
            html += """
  <p style="color:#aaa; font-size:12px; margin-top: 30px;">Généré automatiquement par Magic Prediction IA</p>
</body></html>"""

            part = MIMEText(html, "html", "utf-8")
            msg.attach(part)

            def _send():
                try:
                    server = smtplib.SMTP("smtp.gmail.com", 587)
                    server.starttls()
                    server.login(sender, password)
                    server.send_message(msg)
                    server.quit()
                    self.safe_after(0, lambda: self.email_btn.configure(text="✅ ENVOYÉ !"))
                    import time; time.sleep(2)
                    self.safe_after(0, lambda: self.email_btn.configure(text="📧 ENVOYER PAR MAIL"))
                except Exception as e:
                    self.safe_after(0, lambda: self.email_btn.configure(text="❌ ERREUR ENVOI"))
                    print(f"Erreur d'envoi d'email: {e}")
                    
            self.email_btn.configure(text="⏳ ENVOI...")
            import threading
            threading.Thread(target=_send, daemon=True).start()
            
        except Exception as e:
            print(f"Erreur prparation email: {e}")

if __name__ == "__main__":
    app = TennisDailyAllApp()
    app.mainloop()
