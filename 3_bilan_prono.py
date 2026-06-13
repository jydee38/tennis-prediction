#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Antigravity Pro - Pronos Viewer (Hybrid Edition)
Un outil d'élite à zéro dépendance qui détecte automatiquement son environnement :
- Mode Desktop : Ouvre un tableau de bord Tkinter Dark Mode fluide et interactif.
- Mode Headless / Serveur : Affiche un tableau de bord CLI ANSI en couleur ultra-design.
"""

import os
import sys
import json
import re
from datetime import datetime

# Configuration du fichier de données
PREDICTIONS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "predictions.json")

# Ensure proper import of betting_manager module
project_root = os.path.abspath(os.path.dirname(__file__))
python_dir = os.path.join(project_root, "python")
if python_dir not in sys.path:
    sys.path.append(python_dir)
import betting_manager as bm

def load_predictions_safe():
    return bm.load_predictions()

def deduplicate_predictions_file():
    """
    Ensure predictions.json contains only unique predictions.
    Uses the betting_manager loading logic for deduplication.
    """
    try:
        import python.betting_manager as bm
        deduped = bm.load_predictions()
        bm.save_predictions(deduped)
        print("[System] Predictions file deduplicated using betting_manager.")
    except Exception:
        # Fallback simple dedup based on ID
        try:
            with open(PREDICTIONS_FILE, "r", encoding="utf-8") as f:
                preds = json.load(f)
            unique = {}
            for p in preds:
                unique[p.get('id')] = p
            with open(PREDICTIONS_FILE, "w", encoding="utf-8") as f:
                json.dump(list(unique.values()), f, indent=4, ensure_ascii=False)
            print("[System] Predictions file deduplicated with simple method.")
        except Exception as e:
            print(f"Error deduplicating predictions: {e}")
        except Exception as e:
            print(f"Error loading: {e}")
            return []

# Détection de la disponibilité de l'interface graphique (Tkinter)
try:
    import tkinter as tk
    from tkinter import ttk
    HAS_GUI = True
except ImportError:
    HAS_GUI = False


# =====================================================================
# 📊 SECTION 1 : MODE GRAPHIQUE (Tkinter Premium Dark Mode)
# =====================================================================

if HAS_GUI:
    class ScrollableFrame(tk.Frame):
        """Un conteneur scrollable en pur Tkinter pour accueillir les cartes de pronos."""
        def __init__(self, container, bg_color, *args, **kwargs):
            super().__init__(container, *args, **kwargs)
            self.configure(bg=bg_color)
            
            # Canvas de dessin pour le scroll
            self.canvas = tk.Canvas(self, bg=bg_color, borderwidth=0, highlightthickness=0)
            self.scrollbar = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
            
            self.scrollable_frame = tk.Frame(self.canvas, bg=bg_color)
            
            # Liaison dynamique du scroll
            self.scrollable_frame.bind(
                "<Configure>",
                lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
            )
            
            self.canvas_window = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
            
            # Adapter la largeur du frame à celle du canvas
            self.canvas.bind('<Configure>', self._on_canvas_configure)
            self.canvas.configure(yscrollcommand=self.scrollbar.set)
            
            self.canvas.pack(side="left", fill="both", expand=True)
            self.scrollbar.pack(side="right", fill="y")
            
            # Support de la molette de la souris
            self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        def _on_canvas_configure(self, event):
            self.canvas.itemconfig(self.canvas_window, width=event.width)

        def _on_mousewheel(self, event):
            try:
                self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            except:
                pass


    class PronosViewerApp(tk.Tk):
        def __init__(self):
            super().__init__()

            # Configuration de la fenêtre principale
            self.title("Antigravity Pro - Pronos Dashboard 📊")
            self.geometry("1280x780")
            self.minsize(1100, 600)
            
            # Palette de couleurs Premium Dark Mode
            self.bg_color = "#0a0a0d"
            self.header_bg = "#111116"
            self.card_bg = "#15151e"
            self.card_hover = "#1e1e2b"
            self.accent_blue = "#1a8cff"
            self.turquoise = "#00ffd5"
            self.yellow_neon = "#eaff00"
            self.green_success = "#2ecc71"
            self.red_danger = "#e74c3c"
            self.text_main = "#f1f2f6"
            self.text_dim = "#8a8a9e"

            self.configure(bg=self.bg_color)

            # États internes de l'application
            self.filter_state = "Tous"
            self.search_text = ""
            self.predictions_list = []
            self.filter_buttons = {}

            # Construction de l'interface graphique
            self.setup_ui()
            self.refresh_data()

        def setup_ui(self):
            # Configuration des styles TTK de base
            style = ttk.Style()
            style.theme_use("clam")
            style.configure("TProgressbar", thickness=8, troughcolor="#20202a", background=self.accent_blue)

            # ═══════════════════════════════════════════════════════════════════
            # 1. EN-TÊTE (Header Frame)
            # ═══════════════════════════════════════════════════════════════════
            self.header_frame = tk.Frame(self, bg=self.header_bg, height=65)
            self.header_frame.pack(fill="x", side="top")
            self.header_frame.pack_propagate(False)

            # Titre stylé
            lbl_logo = tk.Label(
                self.header_frame, 
                text=" TENNIS IA PRO  •  Pronos Dashboard", 
                font=("Arial", 16, "bold"),
                fg=self.turquoise,
                bg=self.header_bg
            )
            lbl_logo.pack(side="left", padx=20, pady=15)

            # Bouton de Fermeture
            btn_close = tk.Button(
                self.header_frame,
                text="❌ FERMER",
                font=("Arial", 10, "bold"),
                fg="#ff9999",
                bg="#3a1111",
                activebackground=self.red_danger,
                activeforeground="white",
                relief="flat",
                bd=0,
                cursor="hand2",
                padx=15,
                command=self.destroy
            )
            btn_close.pack(side="right", padx=20, pady=15)

            # Bouton d'Actualisation
            btn_refresh = tk.Button(
                self.header_frame,
                text="🔄 Actualiser",
                font=("Arial", 10, "bold"),
                fg="#8a8ab0",
                bg="#1c1c28",
                activebackground="#2b2b3d",
                activeforeground="white",
                relief="flat",
                bd=0,
                cursor="hand2",
                padx=15,
                command=self.refresh_data
            )
            btn_refresh.pack(side="right", padx=(0, 10), pady=15)

            # ═══════════════════════════════════════════════════════════════════
            # 2. PANEL SUPÉRIEUR (Stats & KPI)
            # ═══════════════════════════════════════════════════════════════════
            self.stats_panel = tk.Frame(self, bg=self.bg_color)
            self.stats_panel.pack(fill="x", padx=20, pady=15)

            # Configuration des colonnes KPI
            self.stats_panel.grid_columnconfigure((0, 1, 2, 3, 4, 5, 6, 7), weight=1)

            # --- CARTE 1 : Bilan global ---
            self.card_profit = tk.Frame(self.stats_panel, bg=self.card_bg, bd=0)
            self.card_profit.grid(row=0, column=0, padx=(0, 10), sticky="ew", ipady=12)
            tk.Label(self.card_profit, text="BILAN GLOBAL", font=("Arial", 9, "bold"), fg=self.text_dim, bg=self.card_bg).pack(pady=(10, 2))
            self.lbl_profit_val = tk.Label(self.card_profit, text="0.00 €", font=("Arial", 20, "bold"), fg=self.text_main, bg=self.card_bg)
            self.lbl_profit_val.pack()

            # --- CARTE 2 : Taux de réussite ---
            self.card_reussite = tk.Frame(self.stats_panel, bg=self.card_bg, bd=0)
            self.card_reussite.grid(row=0, column=1, padx=(0, 10), sticky="ew", ipady=12)
            tk.Label(self.card_reussite, text="RÉUSSITE / ROI", font=("Arial", 9, "bold"), fg=self.text_dim, bg=self.card_bg).pack(pady=(10, 2))
            self.lbl_reussite_val = tk.Label(self.card_reussite, text="0.0%  (+0.0% ROI)", font=("Arial", 13, "bold"), fg=self.turquoise, bg=self.card_bg)
            self.lbl_reussite_val.pack()

            # --- CARTE 3 : Volume des paris ---
            self.card_volume = tk.Frame(self.stats_panel, bg=self.card_bg, bd=0)
            self.card_volume.grid(row=0, column=2, padx=(0, 10), sticky="ew", ipady=12)
            tk.Label(self.card_volume, text="VOLUME DE PARIS", font=("Arial", 9, "bold"), fg=self.text_dim, bg=self.card_bg).pack(pady=(10, 2))
            self.lbl_volume_val = tk.Label(self.card_volume, text="0 ✅ | 0 ❌ | 0 ⏳", font=("Arial", 13, "bold"), fg=self.text_main, bg=self.card_bg)
            self.lbl_volume_val.pack(pady=(4, 0))

            # --- CARTE 4 : Total des mises ---
            self.card_total_stake = tk.Frame(self.stats_panel, bg=self.card_bg, bd=0)
            self.card_total_stake.grid(row=0, column=3, padx=(0, 10), sticky="ew", ipady=12)
            tk.Label(self.card_total_stake, text="TOTAL MISE", font=("Arial", 9, "bold"), fg=self.text_dim, bg=self.card_bg).pack(pady=(10, 2))
            self.lbl_total_stake_val = tk.Label(self.card_total_stake, text="0.00 €", font=("Arial", 13, "bold"), fg=self.text_main, bg=self.card_bg)
            self.lbl_total_stake_val.pack(pady=(4, 0))

            # --- CARTE 5 : Moyenne des cotes ---
            self.card_avg_odds = tk.Frame(self.stats_panel, bg=self.card_bg, bd=0)
            self.card_avg_odds.grid(row=0, column=4, padx=(0, 10), sticky="ew", ipady=12)
            tk.Label(self.card_avg_odds, text="Moy. COTE", font=("Arial", 9, "bold"), fg=self.text_dim, bg=self.card_bg).pack(pady=(10, 2))
            self.lbl_avg_odds_val = tk.Label(self.card_avg_odds, text="0.00", font=("Arial", 13, "bold"), fg=self.text_main, bg=self.card_bg)
            self.lbl_avg_odds_val.pack(pady=(4, 0))

            # --- CARTE 6 : Gain moyen par pari ---
            self.card_avg_profit = tk.Frame(self.stats_panel, bg=self.card_bg, bd=0)
            self.card_avg_profit.grid(row=0, column=5, padx=(0, 10), sticky="ew", ipady=12)
            tk.Label(self.card_avg_profit, text="GAIN MOYEN", font=("Arial", 9, "bold"), fg=self.text_dim, bg=self.card_bg).pack(pady=(10, 2))
            self.lbl_avg_profit_val = tk.Label(self.card_avg_profit, text="0.00 €", font=("Arial", 13, "bold"), fg=self.text_main, bg=self.card_bg)
            self.lbl_avg_profit_val.pack(pady=(4, 0))

            # --- CARTE 7 : Total gains nets ---
            self.card_gains = tk.Frame(self.stats_panel, bg=self.card_bg, bd=0)
            self.card_gains.grid(row=0, column=6, padx=(0, 10), sticky="ew", ipady=12)
            tk.Label(self.card_gains, text="GAINS NETS", font=("Arial", 9, "bold"), fg=self.text_dim, bg=self.card_bg).pack(pady=(10, 2))
            self.lbl_gains_val = tk.Label(self.card_gains, text="+0.00 €", font=("Arial", 13, "bold"), fg=self.green_success, bg=self.card_bg)
            self.lbl_gains_val.pack(pady=(4, 0))

            # --- CARTE 8 : Total pertes nettes ---
            self.card_pertes = tk.Frame(self.stats_panel, bg=self.card_bg, bd=0)
            self.card_pertes.grid(row=0, column=7, padx=(0, 0), sticky="ew", ipady=12)
            tk.Label(self.card_pertes, text="PERTES NETTES", font=("Arial", 9, "bold"), fg=self.text_dim, bg=self.card_bg).pack(pady=(10, 2))
            self.lbl_pertes_val = tk.Label(self.card_pertes, text="-0.00 €", font=("Arial", 13, "bold"), fg=self.red_danger, bg=self.card_bg)
            self.lbl_pertes_val.pack(pady=(4, 0))

            # ═══════════════════════════════════════════════════════════════════
            # 3. FILTRES & RECHERCHE (Segmented Control & Search)
            # ═══════════════════════════════════════════════════════════════════
            self.filter_bar = tk.Frame(self, bg=self.bg_color)
            self.filter_bar.pack(fill="x", padx=20, pady=(0, 15))

            self.filter_buttons_frame = tk.Frame(self.filter_bar, bg=self.bg_color)
            self.filter_buttons_frame.pack(side="left")

            filters = [("Tous", "Tous"), ("En cours", "pending"), ("Réussis", "won"), ("Perdus", "lost")]
            for label, status_val in filters:
                btn = tk.Button(
                    self.filter_buttons_frame,
                    text=label,
                    font=("Arial", 9, "bold"),
                    fg="#a0a0c0",
                    bg="#14141c",
                    activebackground=self.accent_blue,
                    activeforeground="white",
                    relief="flat",
                    bd=0,
                    padx=15,
                    pady=6,
                    cursor="hand2",
                    command=lambda lbl=label: self.on_filter_changed(lbl)
                )
                btn.pack(side="left", padx=(0, 4))
                self.filter_buttons[label] = btn

            self.update_filter_buttons_ui("Tous")

            # Barre de recherche avec style
            search_frame = tk.Frame(self.filter_bar, bg="#14141d", highlightbackground="#2b2b3a", highlightthickness=1)
            search_frame.pack(side="right", fill="y", ipadx=5)

            tk.Label(search_frame, text=" 🔍 ", font=("Arial", 11), fg=self.text_dim, bg="#14141d").pack(side="left")
            
            self.search_entry = tk.Entry(
                search_frame,
                font=("Arial", 11),
                fg="white",
                bg="#14141d",
                insertbackground="white",
                bd=0,
                width=30
            )
            self.search_entry.pack(side="left", padx=5, ipady=5)
            self.search_entry.insert(0, "Rechercher un match, tournoi...")
            
            self.search_entry.bind("<FocusIn>", self._clear_placeholder)
            self.search_entry.bind("<FocusOut>", self._restore_placeholder)
            self.search_entry.bind("<KeyRelease>", self.on_search_keypress)

            # ═══════════════════════════════════════════════════════════════════
            # 4. ZONE DE SCROLL (Cartes des pronostics)
            # ═══════════════════════════════════════════════════════════════════
            self.scroll_frame = ScrollableFrame(self, self.bg_color)
            self.scroll_frame.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        def _clear_placeholder(self, event):
            if self.search_entry.get() == "Rechercher un match, tournoi...":
                self.search_entry.delete(0, tk.END)
                self.search_entry.configure(fg="white")

        def _restore_placeholder(self, event):
            if not self.search_entry.get().strip():
                self.search_entry.insert(0, "Rechercher un match, tournoi...")
                self.search_entry.configure(fg=self.text_dim)

        def update_filter_buttons_ui(self, selected_label):
            for label, btn in self.filter_buttons.items():
                if label == selected_label:
                    btn.configure(bg=self.accent_blue, fg="white")
                else:
                    btn.configure(bg="#14141c", fg="#a0a0c0")

        def on_filter_changed(self, label):
            self.filter_state = label
            self.update_filter_buttons_ui(label)
            self.render_predictions_list()

        def on_search_keypress(self, event):
            val = self.search_entry.get().strip()
            if val == "Rechercher un match, tournoi...":
                self.search_text = ""
            else:
                self.search_text = val.lower()
            self.render_predictions_list()

        def refresh_data(self):
            self.predictions_list = load_predictions_safe()

            # Auto-check LiveScore pour les paris en attente (force la MAJ si trouvé)
            try:
                import python.betting_manager as bm_local
                if bm_local._try_resolve_from_livescore(self.predictions_list):
                    bm_local.save_predictions(self.predictions_list)
                    self.predictions_list = load_predictions_safe()
            except Exception as e:
                pass

            # Calcul des stats globales
            total_bets = len(self.predictions_list)
            won_bets = sum(1 for p in self.predictions_list if p.get('status') == 'won')
            lost_bets = sum(1 for p in self.predictions_list if p.get('status') == 'lost')
            pending_bets = sum(1 for p in self.predictions_list if p.get('status') == 'pending')
            
            total_profit = sum(p.get('profit', 0) for p in self.predictions_list)
            total_stake_resolved = sum(p.get('stake', 0) for p in self.predictions_list if p.get('status') in ['won', 'lost'])
            
            win_rate = (won_bets / (won_bets + lost_bets) * 100) if (won_bets + lost_bets) > 0 else 0.0
            roi = (total_profit / total_stake_resolved * 100) if total_stake_resolved > 0 else 0.0

            # KPI Bilan Global
            if total_profit > 0:
                self.lbl_profit_val.configure(text=f"+{total_profit:.2f} €", fg=self.green_success)
            elif total_profit < 0:
                self.lbl_profit_val.configure(text=f"{total_profit:.2f} €", fg=self.red_danger)
            else:
                self.lbl_profit_val.configure(text="0.00 €", fg=self.text_main)

            # KPI Taux de Réussite & ROI
            self.lbl_reussite_val.configure(text=f"{win_rate:.1f}%  ({roi:+.1f}% ROI)")
            
            # KPI Volume de Paris
            self.lbl_volume_val.configure(text=f"{won_bets} ✅ | {lost_bets} ❌ | {pending_bets} ⏳")

            # KPI stats supplémentaires
            self.lbl_total_stake_val.configure(text=f"{total_stake_resolved:.2f} €")
            avg_odds = sum(p.get('odds', 0) for p in self.predictions_list) / total_bets if total_bets > 0 else 0
            self.lbl_avg_odds_val.configure(text=f"{avg_odds:.2f}")
            avg_profit = total_profit / total_bets if total_bets > 0 else 0
            self.lbl_avg_profit_val.configure(text=f"{avg_profit:+.2f} €")

            # KPI Gains nets et Pertes nettes
            total_gains = sum(p.get('profit', 0) for p in self.predictions_list if p.get('profit', 0) > 0)
            total_pertes = sum(p.get('profit', 0) for p in self.predictions_list if p.get('profit', 0) < 0)
            self.lbl_gains_val.configure(text=f"+{total_gains:.2f} €")
            self.lbl_pertes_val.configure(text=f"{total_pertes:.2f} €")

            self.render_predictions_list()

        def set_manual_result(self, match_id, result):
            try:
                if not os.path.exists(PREDICTIONS_FILE):
                    return
                with open(PREDICTIONS_FILE, "r", encoding="utf-8") as f:
                    preds = json.load(f)

                for p in preds:
                    if p.get('id') == match_id:
                        p['status'] = result
                        p['manual_override'] = True
                        p['result_score'] = "Manuel"
                        stake = p.get('stake', 0.0)
                        odds = p.get('odds', 0.0)
                        if result == 'won':
                            p['profit'] = stake * (odds - 1)
                        else:
                            p['profit'] = -stake
                        break
                
                with open(PREDICTIONS_FILE, "w", encoding="utf-8") as f:
                    json.dump(preds, f, indent=4, ensure_ascii=False)
                
                self.refresh_data()
            except Exception as e:
                print(f"Erreur lors de la sauvegarde du résultat: {e}")

        def delete_prediction_ui(self, match_id):
            try:
                import python.betting_manager as bm
                bm.delete_prediction(match_id)
                self.refresh_data()
            except Exception as e:
                print(f"Erreur lors de la suppression: {e}")

        def render_predictions_list(self):
            container = self.scroll_frame.scrollable_frame
            for widget in container.winfo_children():
                widget.destroy()

            filtered = self.predictions_list
            
            if self.filter_state == "En cours":
                filtered = [p for p in filtered if p.get('status') == 'pending']
            elif self.filter_state == "Réussis":
                filtered = [p for p in filtered if p.get('status') == 'won']
            elif self.filter_state == "Perdus":
                filtered = [p for p in filtered if p.get('status') == 'lost']

            if self.search_text:
                filtered = [
                    p for p in filtered 
                    if self.search_text in p.get('match', '').lower() 
                    or self.search_text in p.get('tournament', '').lower() 
                    or self.search_text in p.get('pick', '').lower()
                ]

            if not filtered:
                lbl_empty = tk.Label(
                    container, 
                    text="Aucun pronostic ne correspond à la sélection 🎾", 
                    font=("Arial", 11, "italic"),
                    fg=self.text_dim,
                    bg=self.bg_color
                )
                lbl_empty.pack(pady=60)
                return

            for p in filtered:
                row_frame = tk.Frame(container, bg=self.card_bg, height=85)
                row_frame.pack(fill="x", pady=5, padx=10)
                row_frame.pack_propagate(False)

                # --- DATE ---
                date_frame = tk.Frame(row_frame, bg=self.card_bg)
                date_frame.pack(side="left", padx=15, pady=10, fill="y")
                
                try:
                    date_obj = datetime.fromisoformat(p.get('timestamp', ''))
                    date_str = date_obj.strftime("%d/%m")
                    time_str = date_obj.strftime("%H:%M")
                except:
                    date_str, time_str = "-/-", "--:--"
                    
                lbl_date = tk.Label(date_frame, text=date_str, font=("Arial", 12, "bold"), fg=self.accent_blue, bg=self.card_bg)
                lbl_date.pack()
                lbl_time = tk.Label(date_frame, text=time_str, font=("Arial", 9), fg=self.text_dim, bg=self.card_bg)
                lbl_time.pack()

                # --- MATCH ---
                info_frame = tk.Frame(row_frame, bg=self.card_bg)
                info_frame.pack(side="left", padx=10, pady=10, fill="y")
                
                lbl_tourn = tk.Label(info_frame, text=str(p.get('tournament', 'Unknown')).upper(), font=("Arial", 8, "bold"), fg=self.text_dim, bg=self.card_bg)
                lbl_tourn.pack(anchor="w")
                
                lbl_match = tk.Label(info_frame, text=p.get('match', ''), font=("Arial", 11, "bold"), fg=self.text_main, bg=self.card_bg)
                lbl_match.pack(anchor="w", pady=(2, 0))

                # --- STATUT ---
                status_frame = tk.Frame(row_frame, bg=self.card_bg, width=190)
                status_frame.pack(side="right", padx=15, pady=10, fill="y")
                status_frame.pack_propagate(False)
                
                status = p.get('status')
                score = p.get('result_score')
                profit = p.get('profit', 0.0)

                if status == "won":
                    badge_bg = "#1b4d22"
                    badge_fg = self.green_success
                    badge_text = "▲ RÉUSSI"
                    profit_text = f"+{profit:.2f} €"
                    profit_fg = self.green_success
                elif status == "lost":
                    badge_bg = "#4d1b1b"
                    badge_fg = self.red_danger
                    badge_text = "▼ PERDU"
                    profit_text = f"{profit:.2f} €"
                    profit_fg = self.red_danger
                else:
                    badge_bg = "#3a3a10"
                    badge_fg = self.yellow_neon
                    badge_text = "⏳ EN COURS"
                    profit_text = "-    "
                    profit_fg = self.text_dim

                action_frame = tk.Frame(status_frame, bg=self.card_bg)
                action_frame.pack(anchor="e")

                # Bouton corbeille (supprimer définitivement) pour tous les paris
                btn_delete = tk.Button(action_frame, text="🗑️", bg="#333333", fg="white", bd=0, cursor="hand2", width=3, command=lambda pid=p.get('id'): self.delete_prediction_ui(pid))
                btn_delete.pack(side="right", padx=(5, 0))

                badge_lbl = tk.Label(action_frame, text=badge_text, font=("Arial", 8, "bold"), fg=badge_fg, bg=badge_bg, padx=6, pady=2)
                badge_lbl.pack(side="right")

                if status == "pending":
                    btn_lost = tk.Button(action_frame, text="❌", bg="#4d1b1b", fg="white", bd=0, cursor="hand2", width=2, command=lambda pid=p.get('id'): self.set_manual_result(pid, 'lost'))
                    btn_lost.pack(side="right", padx=(0, 5))
                    btn_won = tk.Button(action_frame, text="✅", bg="#1b4d22", fg="white", bd=0, cursor="hand2", width=2, command=lambda pid=p.get('id'): self.set_manual_result(pid, 'won'))
                    btn_won.pack(side="right", padx=(0, 5))

                score_lbl_text = f"Score: {score}" if score else ""
                lbl_score = tk.Label(status_frame, text=score_lbl_text, font=("Arial", 8, "italic"), fg=self.text_dim, bg=self.card_bg)
                lbl_score.pack(anchor="e", pady=(2, 0))
                
                lbl_profit = tk.Label(status_frame, text=profit_text, font=("Arial", 11, "bold"), fg=profit_fg, bg=self.card_bg)
                lbl_profit.pack(anchor="e", pady=(2, 0))

                # --- PRONOSTIC / COTE ---
                pick_frame = tk.Frame(row_frame, bg=self.card_bg)
                pick_frame.pack(side="right", padx=20, pady=10, fill="y")
                
                pick_str = p.get('pick', '')
                odds = p.get('odds', 0.0)
                stake = p.get('stake', 0.0)
                
                lbl_pick = tk.Label(pick_frame, text=f"👉 {pick_str}", font=("Arial", 10, "bold"), fg=self.yellow_neon, bg=self.card_bg)
                lbl_pick.pack(anchor="e")
                
                lbl_details = tk.Label(pick_frame, text=f"Cote: {odds:.2f}  •  Mise: {stake:.1f}€", font=("Arial", 9), fg="#bdc3c7", bg=self.card_bg)
                lbl_details.pack(anchor="e")

                # Callbacks d'effet de survol (hover) synchronisés sur tous les composants de la ligne
                def make_hover(rf, frames, color):
                    return lambda e: [rf.configure(bg=color), *[f.configure(bg=color) for f in frames]]

                sub_frames = [date_frame, info_frame, status_frame, pick_frame]
                on_enter = make_hover(row_frame, sub_frames, self.card_hover)
                on_leave = make_hover(row_frame, sub_frames, self.card_bg)

                # Survol interactif
                for widget in [row_frame, date_frame, lbl_date, lbl_time, info_frame, lbl_tourn, lbl_match,
                               status_frame, action_frame, lbl_score, lbl_profit, pick_frame, lbl_pick, lbl_details]:
                    widget.bind("<Enter>", on_enter)
                    widget.bind("<Leave>", on_leave)


# =====================================================================
# 💻 SECTION 2 : MODE TERMINAL (ANSI Dashboards CLI)
# =====================================================================

# Codes ANSI
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
CYAN = "\033[36m"
WHITE = "\033[37m"
BG_DARK = "\033[48;5;234m"

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def format_date_cli(iso_str):
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%d/%m %H:%M")
    except:
        return "-"

def get_status_badge_cli(status, score=None):
    if status == "won":
        badge = f"{GREEN}▲ REUSSI{RESET}"
        score_str = f" {DIM}({score}){RESET}" if score else ""
        return f"{badge}{score_str}"
    elif status == "lost":
        badge = f"{RED}▼ PERDU{RESET}"
        score_str = f" {DIM}({score}){RESET}" if score else ""
        return f"{badge}{score_str}"
    else:
        return f"{YELLOW}⏳ PENDING{RESET}"

def render_cli_dashboard(filter_status=None, search_query=None):
    if not os.path.exists(PREDICTIONS_FILE):
        print(f"\n{RED}❌ Fichier predictions.json introuvable à l'emplacement : {PREDICTIONS_FILE}{RESET}")
        return

    try:
        with open(PREDICTIONS_FILE, "r", encoding="utf-8") as f:
            predictions = json.load(f)
    except Exception as e:
        print(f"\n{RED}❌ Erreur lors de la lecture : {e}{RESET}")
        return

    predictions.sort(key=lambda x: x.get('timestamp', ''), reverse=True)

    # Calcul stats
    total_bets = len(predictions)
    won_bets = sum(1 for p in predictions if p.get('status') == 'won')
    lost_bets = sum(1 for p in predictions if p.get('status') == 'lost')
    pending_bets = sum(1 for p in predictions if p.get('status') == 'pending')
    
    total_profit = sum(p.get('profit', 0) for p in predictions)
    total_stake_resolved = sum(p.get('stake', 0) for p in predictions if p.get('status') in ['won', 'lost'])
    
    win_rate = (won_bets / (won_bets + lost_bets) * 100) if (won_bets + lost_bets) > 0 else 0.0
    roi = (total_profit / total_stake_resolved * 100) if total_stake_resolved > 0 else 0.0

    # Filtres
    filtered_preds = predictions
    if filter_status:
        filtered_preds = [p for p in filtered_preds if p.get('status') == filter_status]
    if search_query:
        q = search_query.lower()
        filtered_preds = [p for p in filtered_preds if q in p.get('match', '').lower() or q in p.get('tournament', '').lower() or q in p.get('pick', '').lower()]

    print(f"\n{CYAN}{BOLD}╔══════════════════════════════════════════════════════════════════════════════╗")
    print(f"║ 🎾 {WHITE}{BOLD}ANTIGRAVITY PRO — CONSOLE DE SUIVI DES PRONOSTICS{RESET}{CYAN}{BOLD}                       ║")
    print(f"╚══════════════════════════════════════════════════════════════════════════════╝{RESET}")

    profit_color = GREEN if total_profit >= 0 else RED
    profit_sign = "+" if total_profit >= 0 else ""

    # Calcul gains nets et pertes nettes
    total_gains = sum(p.get('profit', 0) for p in predictions if p.get('profit', 0) > 0)
    total_pertes = sum(p.get('profit', 0) for p in predictions if p.get('profit', 0) < 0)
    total_stake_all = sum(p.get('stake', 0) for p in predictions)
    avg_odds = sum(p.get('odds', 0) for p in predictions) / total_bets if total_bets > 0 else 0

    print(f"  {BOLD}BILAN FINANCIER :{RESET}")
    print(f"  ┌───────────────────────┬───────────────────────┬───────────────────────┬───────────────────────┬───────────────────────┐")
    print(f"  │ {BOLD}Bilan Global{RESET}          │ {BOLD}Taux de Réussite{RESET}       │ {BOLD}ROI (Sur validés){RESET}       │ {BOLD}Gains nets{RESET}             │ {BOLD}Pertes nettes{RESET}          │")
    print(f"  │ {profit_color}{BOLD}{profit_sign}{total_profit:.2f} €{RESET}             │ {GREEN}{BOLD}{win_rate:.1f}%{RESET} (sur {won_bets+lost_bets} paris)  │ {BLUE}{BOLD}{roi:+.1f}%{RESET}                  │ {GREEN}{BOLD}+{total_gains:.2f} €{RESET}             │ {RED}{BOLD}{total_pertes:.2f} €{RESET}             │")
    print(f"  └───────────────────────┴───────────────────────┴───────────────────────┴───────────────────────┴───────────────────────┘")

    print(f"  {BOLD}Volume : {RESET}{WHITE}{total_bets}{RESET} paris enregistrés  |  {GREEN}▲ Réussis : {won_bets}{RESET}  |  {RED}▼ Perdus : {lost_bets}{RESET}  |  {YELLOW}⏳ En cours : {pending_bets}{RESET}  |  Mise totale : {WHITE}{total_stake_all:.0f} €{RESET}  |  Moy. cote : {WHITE}{avg_odds:.2f}{RESET}")
    
    col_widths = [11, 16, 32, 16, 8, 8, 14]
    headers = ["DATE", "TOURNOI", "MATCH", "CHOIX", "COTE", "MISE", "STATUT/SCORE"]
    
    top_line = "  ┌" + "┬".join("─" * w for w in col_widths) + "┐"
    header_line = "  │" + "│".join(f" {BOLD}{h.ljust(w-2)}{RESET} " for h, w in zip(headers, col_widths)) + "│"
    sep_line = "  ├" + "┼".join("─" * w for w in col_widths) + "┤"
    bot_line = "  └" + "┴".join("─" * w for w in col_widths) + "┘"
    
    print(top_line)
    print(header_line)
    print(sep_line)
    
    if not filtered_preds:
        empty_msg = "Aucun pronostic ne correspond aux critères."
        padding = (sum(col_widths) + len(col_widths) - 1 - len(empty_msg)) // 2
        print("  │" + " " * padding + f"{DIM}{empty_msg}{RESET}" + " " * (sum(col_widths) + len(col_widths) - 1 - len(empty_msg) - padding) + "│")
    else:
        max_display = 20 if not search_query else len(filtered_preds)
        for p in filtered_preds[:max_display]:
            date_str = format_date_cli(p.get('timestamp', ''))
            tourn = p.get('tournament', 'Unknown')
            if len(tourn) > col_widths[1] - 2: tourn = tourn[:col_widths[1] - 5] + "..."
            match = p.get('match', '')
            if len(match) > col_widths[2] - 2: match = match[:col_widths[2] - 5] + "..."
            pick = p.get('pick', '')
            if len(pick) > col_widths[3] - 2: pick = pick[:col_widths[3] - 5] + "..."
            odds = f"{p.get('odds', 0.0):.2f}"
            stake = f"{p.get('stake', 0.0):.1f}€"
            status_val = get_status_badge_cli(p.get('status'), p.get('result_score'))
            
            line_start = "  │"
            bg_prefix = BG_DARK if p.get('status') in ['won', 'lost'] else ""
                
            row_content = (
                f" {bg_prefix}{date_str.ljust(col_widths[0]-2)}{RESET} │"
                f" {bg_prefix}{tourn.ljust(col_widths[1]-2)}{RESET} │"
                f" {bg_prefix}{match.ljust(col_widths[2]-2)}{RESET} │"
                f" {bg_prefix}{pick.ljust(col_widths[3]-2)}{RESET} │"
                f" {bg_prefix}{odds.rjust(col_widths[4]-2)}{RESET} │"
                f" {bg_prefix}{stake.rjust(col_widths[5]-2)}{RESET} │"
                f" {status_val.ljust(col_widths[6]-2 + len(GREEN) + len(RESET))} "
            )
            print(f"{line_start}{row_content}│")
            
        if len(filtered_preds) > max_display:
            more_count = len(filtered_preds) - max_display
            more_msg = f"... et {more_count} autres paris plus anciens (utilisez la recherche pour filtrer) ..."
            padding = (sum(col_widths) + len(col_widths) - 1 - len(more_msg)) // 2
            print("  ├" + "─" * (sum(col_widths) + len(col_widths) - 1) + "┤")
            print("  │" + " " * padding + f"{DIM}{more_msg}{RESET}" + " " * (sum(col_widths) + len(col_widths) - 1 - len(more_msg) - padding) + "│")

    print(bot_line)

def run_cli_mode():
    if os.name == 'nt':
        os.system('')
        try:
            sys.stdout.reconfigure(encoding='utf-8')
            sys.stderr.reconfigure(encoding='utf-8')
        except:
            pass
        
    filter_status = None
    search_query = None
    
    while True:
        clear_screen()
        render_cli_dashboard(filter_status, search_query)
        print(f"\n  {BOLD}Options de filtrage et navigation :{RESET}")
        print(f"  {CYAN}[P]{RESET} Afficher uniquement les {YELLOW}PENDING{RESET} (En cours)")
        print(f"  {CYAN}[W]{RESET} Afficher uniquement les {GREEN}REUSSIS{RESET}")
        print(f"  {CYAN}[L]{RESET} Afficher uniquement les {RED}PERDUS{RESET}")
        print(f"  {CYAN}[A]{RESET} Afficher {WHITE}{BOLD}TOUS{RESET} les paris")
        print(f"  {CYAN}[S]{RESET} Rechercher un joueur, tournoi ou choix")
        print(f"  {CYAN}[Q]{RESET} Quitter la visualisation")
        
        choice = input(f"\n  {BOLD}Votre choix > {RESET}").strip().lower()
        
        if choice == 'q':
            print(f"\n  {GREEN}Merci d'avoir utilisé Antigravity Pronos Viewer ! À bientôt. 🎾{RESET}\n")
            break
        elif choice == 'p':
            filter_status = "pending"
            search_query = None
        elif choice == 'w':
            filter_status = "won"
            search_query = None
        elif choice == 'l':
            filter_status = "lost"
            search_query = None
        elif choice == 'a':
            filter_status = None
            search_query = None
        elif choice == 's':
            search_query = input(f"  {BOLD}Entrez un mot-clé (nom du joueur, tournoi, etc.) : {RESET}").strip()
            filter_status = None


# =====================================================================
# 🚀 POINT D'ENTRÉE PRINCIPAL
# =====================================================================

def main():
    if HAS_GUI:
        # Lancement de l'application graphique Tkinter
        print("[System] Mode graphique (Tkinter Desktop) détecté.")
        app = PronosViewerApp()
        app.mainloop()
    else:
        # Lancement de la console ANSI CLI
        print("[System] Mode sans écran (Headless CLI) détecté.")
        run_cli_mode()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n  {GREEN}À bientôt ! 🎾{RESET}\n")
