import customtkinter as ctk
import pandas as pd

def show_player_matches_details(parent, player_obj, title="Détails du joueur"):
    dlg = ctk.CTkToplevel(parent)
    dlg.title(title)
    dlg.geometry("600x400")
    dlg.grab_set()
    dlg.configure(fg_color="#111")
    
    ctk.CTkLabel(dlg, text=f"🎾 Historique de {player_obj.name} (Tournoi actuel & Qualifs)", 
                 font=ctk.CTkFont(size=18, weight="bold"), text_color="#00ffd5").pack(pady=(15, 5))
                 
    # Placeholder for total time label (will be updated after calculating)
    total_time_lbl = ctk.CTkLabel(dlg, text="", font=ctk.CTkFont(size=14, slant="italic"), text_color="#f1c40f")
    total_time_lbl.pack(pady=(0, 10))
                 
    scroll = ctk.CTkScrollableFrame(dlg, fg_color="transparent")
    scroll.pack(fill="both", expand=True, padx=15, pady=10)
    
    te_data = getattr(player_obj, 'latest_te_data', {})
    recent_matches = te_data.get("recent_matches", []) if te_data else []
    
    if not recent_matches:
        # Fallback to data_df
        df = getattr(parent, 'data_df', None)
        if df is not None and not df.empty:
            p_id = getattr(player_obj, 'id', '')
            p_name = getattr(player_obj, 'name', '')
            
            if 'Name_1' in df.columns and 'Name_2' in df.columns:
                p_matches = df[(df['Name_1'] == p_name) | (df['Name_2'] == p_name)].copy()
                
                date_col = 'tournament_date' if 'tournament_date' in p_matches.columns else ('tourney_date' if 'tourney_date' in p_matches.columns else None)
                
                if date_col:
                    p_matches = p_matches.sort_values(by=date_col, ascending=False).head(15)
                    
                for _, row in p_matches.iterrows():
                    m_date_val = str(row[date_col]) if date_col else ''
                    
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
                    
                    m = {
                        'date': m_date_val,
                        'tournament': str(row.get('tournament', row.get('tourney_name', ''))),
                        'round': str(row.get('round', '?')),
                        'is_win': is_win,
                        'opponent': opponent,
                        'score': str(row.get('score', '')),
                        'minutes': row.get('minutes', 0)
                    }
                    recent_matches.append(m)
                
    if not recent_matches:
        ctk.CTkLabel(scroll, text="Aucun match trouvé pour ce joueur (données récentes indisponibles).", text_color="#aaa").pack(pady=20)
        return

    # Extract fatigue dates to match the fatigue index logic
    current_t_date = str(player_obj.fatigue_features.get("current tournament", {}).get("date", ""))
    prev_t_date = str(player_obj.fatigue_features.get("previous tournament", {}).get("date", ""))
    
    display_matches = []
    
    # For te_data, the dates might not precisely match '20260525' format, they are usually "dd.mm.yyyy" or "dd.mm."
    # We will just rely on the fact that TE data is sorted.
    # To be smart, we will grab the tournament name of the very first match and get all matches from that tournament,
    # plus any preceding qualifiers if they share a similar name or date.
    
    latest_t_name = recent_matches[0].get('tournament', '')
    for m in recent_matches:
        # Include matches from the exact same tournament name
        # OR if it's the 5 most recent matches, we just show them anyway
        display_matches.append(m)
        
    # Deduplicate, ignore upcoming/empty, and limit to top 3 for a fair comparison
    unique_matches = []
    seen = set()
    for m in display_matches:
        score_str = str(m.get('score', '')).lower()
        if 'upcoming' in score_str or score_str in ['nan', 'none', 'n/a', '']:
            continue
            
        m_date = str(m.get('date', ''))
        opp = str(m.get('opponent', ''))
        key = (m_date, opp)
        
        if key not in seen:
            seen.add(key)
            unique_matches.append(m)
            
    # On se base sur les 3 derniers matchs pour que la comparaison soit équitable (qualifs incluses)
    display_matches = unique_matches[:3]
    
    total_minutes_accumulated = 0
        
    for m in display_matches:
        m_date = str(m.get('date', ''))
        tourney = str(m.get('tournament', 'Inconnu'))
        m_round = str(m.get('round', '?'))
        
        # Win/Loss
        is_win = m.get('is_win', False)
        if is_win:
            wl_str = "VICTOIRE"
            wl_color = "#2ecc71"
        else:
            wl_str = "DÉFAITE"
            wl_color = "#e74c3c"
            
        opp_name = str(m.get('opponent', 'Inconnu'))
        score = str(m.get('score', 'N/A'))
        
        # Extract duration/time and games
        games = 0
        minutes = m.get('minutes', 0)
        try:
            minutes = float(minutes) if minutes and str(minutes) != 'nan' else 0
        except:
            minutes = 0
            
        try:
            # By summing individual digits, we safely parse '76 64' as 7+6+6+4=23 games instead of 76+64=140
            games = sum(int(c) for c in score if c.isdigit())
        except:
            pass
            
        if minutes > 0:
            time_str = f"{int(minutes)} min"
            total_minutes_accumulated += int(minutes)
        else:
            estimated = int(games * 4.2) if games > 0 else 0
            time_str = f"~{estimated} min (estimé)" if estimated > 0 else "N/A"
            total_minutes_accumulated += estimated
            
        # Display Card
        card = ctk.CTkFrame(scroll, fg_color="#1a1a1a", corner_radius=8)
        card.pack(fill="x", pady=5)
        
        header_frame = ctk.CTkFrame(card, fg_color="transparent")
        header_frame.pack(fill="x", padx=10, pady=(10, 5))
        
        ctk.CTkLabel(header_frame, text=f"{tourney} ({m_date}) - {m_round}", 
                     font=ctk.CTkFont(size=12, weight="bold"), text_color="#ccc").pack(side="left")
                     
        ctk.CTkLabel(header_frame, text=wl_str, font=ctk.CTkFont(size=12, weight="bold"), 
                     text_color=wl_color).pack(side="right")
                     
        content_frame = ctk.CTkFrame(card, fg_color="transparent")
        content_frame.pack(fill="x", padx=10, pady=(0, 10))
        
        ctk.CTkLabel(content_frame, text=f"Contre : {opp_name}", font=ctk.CTkFont(size=14)).pack(side="left")
        
        stats_text = f"Score : {score} | Temps : {time_str}"
        ctk.CTkLabel(content_frame, text=stats_text, font=ctk.CTkFont(size=13), text_color="#7ec8e3").pack(side="right")
        
    # Update total time label
    if total_minutes_accumulated > 0:
        h = total_minutes_accumulated // 60
        mn = total_minutes_accumulated % 60
        total_time_lbl.configure(text=f"⏱ Temps passé sur le court (3 derniers matchs) : {total_minutes_accumulated} min (soit {h}h {mn}min)")
    else:
        total_time_lbl.configure(text="⏱ Temps passé sur le court (3 derniers matchs) : Inconnu")

    # Add a close button
    ctk.CTkButton(dlg, text="Fermer", fg_color="gray", command=dlg.destroy).pack(pady=15)
