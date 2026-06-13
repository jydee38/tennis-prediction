import re
import threading
from datetime import datetime, timedelta
import tkinter as tk
from tkinter import ttk
import customtkinter as ctk
import sys

# Fermeture immédiate du splash screen PyInstaller pour éviter de masquer des erreurs
try:
    import pyi_splash
    pyi_splash.close()
except ImportError:
    pass

from python.app_logic import (
    get_data_and_train_model, 
    get_recent_tournaments, 
    get_matches_for_tournament,
    predict_match_outcome,
    get_mistral_betting_advice,
    create_custom_match_row,
    calculate_betting_stats,
    find_player_by_name
)
from python.translations import TRANSLATIONS
from python.data.qualification_fetcher import (
    get_today_matches_with_stats,
    get_roland_garros_qualification_matches,
)
import python.betting_manager as betting_manager

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class TennisApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.current_lang = "FR"
        self.title(self._tr("title"))
        self.geometry("1200x700")

        # Data placeholders
        self.data_df = None
        self.model = None
        self.players_db = {}
        self.current_matches = []
        self.used_features = []
        self.current_tour = "ATP"
        
        # Paramètres de détection (chargés depuis le fichier persistant)
        from python.analysis_settings_manager import load_analysis_settings
        self.analysis_settings = load_analysis_settings()
        
        # Combined bets state
        self.manual_combined_legs = []

        self.setup_ui()

        # Start loading data in a background thread with an explicit loading overlay
        self.show_loading_overlay("⏳ Chargement initial et analyse des données")
        threading.Thread(target=self.load_data, args=(False,), daemon=True).start()

    def _tr(self, key):
        return TRANSLATIONS.get(self.current_lang, TRANSLATIONS["FR"]).get(key, key)

    def show_loading_overlay(self, message="⏳ Veuillez patienter..."):
        """Affiche un panneau de chargement par-dessus toute l'interface."""
        # Annuler l'animation précédente si elle existe
        if hasattr(self, '_overlay_anim_id') and self._overlay_anim_id:
            try:
                self.after_cancel(self._overlay_anim_id)
            except Exception:
                pass
            self._overlay_anim_id = None
        # Détruire un overlay existant
        if hasattr(self, '_overlay') and self._overlay is not None:
            try:
                self._overlay.destroy()
            except Exception:
                pass
        self._overlay = ctk.CTkFrame(self, fg_color="#0d1117", corner_radius=0)
        self._overlay.place(x=0, y=0, relwidth=1, relheight=1)
        self._overlay.lift()
        # Conteneur centré
        card = ctk.CTkFrame(self._overlay, fg_color="#1c2333", corner_radius=18)
        card.place(relx=0.5, rely=0.5, anchor="center")
        self._overlay_base_msg = message.rstrip(".")
        self._overlay_label = ctk.CTkLabel(
            card,
            text=message,
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="#58a6ff",
            wraplength=600
        )
        self._overlay_label.pack(padx=50, pady=(35, 10))
        
        self._overlay_progress = ctk.CTkLabel(
            card,
            text="",
            font=ctk.CTkFont(size=13),
            text_color="gray",
            wraplength=550
        )
        self._overlay_progress.pack(padx=50, pady=(0, 35))
        self._overlay_dots = 0
        self._animate_overlay()

    def _animate_overlay(self):
        """Animation des points de suspension dans l'overlay."""
        if not hasattr(self, '_overlay') or self._overlay is None:
            return
        try:
            if not self._overlay.winfo_exists():
                return
        except Exception:
            return
        dots = "." * (self._overlay_dots % 4)
        self._overlay_label.configure(text=f"{self._overlay_base_msg}{dots}")
        self._overlay_dots += 1
        self._overlay_anim_id = self.after(450, self._animate_overlay)

    def hard_refresh_ui(self):
        """Reconstruction complète de l'interface (comme lors d'un changement de langue)."""
        # Détruire tous les widgets
        for widget in self.winfo_children():
            widget.destroy()
        self._overlay = None
        self._bilan_widgets = [] # Vider le registre spécifique

        self.setup_ui()

        # Si les données sont déjà chargées, repeupler les listes
        if self.data_df is not None:
            self.show_loading_overlay("⏳ Rafraîchissement de l'affichage")
            self.on_data_loaded()

    def hide_loading_overlay(self):
        """Masque et détruit l'overlay de chargement."""
        if hasattr(self, '_overlay_anim_id') and self._overlay_anim_id:
            try:
                self.after_cancel(self._overlay_anim_id)
            except Exception:
                pass
            self._overlay_anim_id = None
        if hasattr(self, '_overlay') and self._overlay is not None:
            try:
                self._overlay.destroy()
            except Exception:
                pass
            self._overlay = None

    def change_language(self, lang):
        if self.current_lang == lang:
            return
        self.current_lang = lang
        self.title(self._tr("title"))

        # Détruire tous les widgets (y compris l'overlay s'il existe)
        for widget in self.winfo_children():
            widget.destroy()
        self._overlay = None

        self.setup_ui()

        # Si les données sont chargées, repeupler avec un overlay pendant la reconstruction
        if self.data_df is not None:
            self.show_loading_overlay("⏳ Reconstruction de l'interface")
            self.on_data_loaded()
            # hide_loading_overlay() est appelé à la fin de on_data_loaded()

    def setup_ui(self):
        # Layout
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, weight=2)
        self.grid_rowconfigure(2, weight=1)
        
        # Header Frame
        self.header_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.header_frame.grid(row=0, column=0, columnspan=3, sticky="ew")
        self.header_frame.grid_columnconfigure(0, weight=0) # Logo
        self.header_frame.grid_columnconfigure(1, weight=1) # Titre
        self.header_frame.grid_columnconfigure(2, weight=0) # Switch Tour
        self.header_frame.grid_columnconfigure(3, weight=0) # Switch Lang
        self.header_frame.grid_columnconfigure(4, weight=0) # Refresh
        self.header_frame.grid_columnconfigure(5, weight=0) # Clean DB
        self.header_frame.grid_columnconfigure(6, weight=0) # Mode Video
        self.header_frame.grid_columnconfigure(7, weight=0) # Token API

        # Logo HD (PNG)
        try:
            from PIL import Image
            import os, sys
            
            logo_path = os.path.join(sys._MEIPASS, "logo-hd.png") if hasattr(sys, '_MEIPASS') else "logo-hd.png"
            if not os.path.exists(logo_path):
                logo_path = "logo-simple.png"
            
            if os.path.exists(logo_path):
                img = Image.open(logo_path).convert("RGBA")
                # Augmentation de la taille de 30% (145 * 1.3 ≈ 190)
                self.logo_ctk = ctk.CTkImage(light_image=img, dark_image=img, size=(190, 190))
                self.logo_label = ctk.CTkLabel(self.header_frame, image=self.logo_ctk, text="")
                self.logo_label.grid(row=0, column=0, padx=(15, 10), pady=(5, 5), sticky="w")
            else:
                ctk.CTkLabel(self.header_frame, text="🎾", font=ctk.CTkFont(size=40)).grid(row=0, column=0, padx=15)
        except Exception as e:
            print(f"Erreur chargement logo: {e}")
            ctk.CTkLabel(self.header_frame, text="🎾", font=ctk.CTkFont(size=40)).grid(row=0, column=0, padx=15)

        # Use translation
        header_text = self._tr("ready") if self.data_df is not None else self._tr("loading")
        self.header = ctk.CTkLabel(self.header_frame, text=header_text, font=ctk.CTkFont(size=24, weight="bold"))
        if self.data_df is not None:
            self.header.configure(text_color="green")
        self.header.grid(row=0, column=1, pady=(20, 5), sticky="w", padx=(20, 0))

        self.tour_switch = ctk.CTkSegmentedButton(self.header_frame, values=["ATP", "WTA"], command=self.on_tour_switch)
        self.tour_switch.set(self.current_tour)
        self.tour_switch.grid(row=0, column=2, padx=10, pady=(20, 5))

        self.lang_switch = ctk.CTkSegmentedButton(self.header_frame, values=["FR", "EN"], command=self.change_language)
        self.lang_switch.set(self.current_lang)
        self.lang_switch.grid(row=0, column=3, padx=10, pady=(20, 5))

        self.refresh_ui_btn = ctk.CTkButton(
            self.header_frame, 
            text="📺 Rafraîchir", 
            width=100, 
            command=self.hard_refresh_ui,
            fg_color="#27ae60",
            hover_color="#1e8449"
        )
        self.refresh_ui_btn.grid(row=0, column=4, padx=5, pady=(20, 5))

        self.reset_btn = ctk.CTkButton(
            self.header_frame, 
            text="🔄 Re-scrapper", 
            width=100, 
            command=self._on_header_hard_reset_click,
            fg_color="#3498db",
            hover_color="#2980b9"
        )
        self.reset_btn.grid(row=0, column=5, padx=5, pady=(20, 5))
        
        self.clean_btn = ctk.CTkButton(self.header_frame, text="Nettoyage Base", width=120, fg_color="#e67e22", hover_color="#d35400", command=self.run_database_cleanup)
        self.clean_btn.grid(row=0, column=6, padx=5, pady=(20, 5))

        self.video_btn = ctk.CTkButton(self.header_frame, text="🎬 Mode Vidéo", width=120, fg_color="#9b59b6", hover_color="#8e44ad", command=self.open_shorts_mode)
        self.video_btn.grid(row=0, column=7, padx=5, pady=(20, 5))

        self.token_btn = ctk.CTkButton(self.header_frame, text="🔑 Quota restant de tennis API", width=120, fg_color="#7f8c8d", hover_color="#95a5a6", command=self.show_api_tokens)
        self.token_btn.grid(row=0, column=8, padx=5, pady=(20, 5))

        self.api_btn = ctk.CTkButton(
            self.header_frame, 
            text=self._tr("test_api"), 
            width=100, 
            fg_color="#9b59b6", 
            hover_color="#8e44ad", 
            command=self.run_api_test
        )
        self.api_btn.grid(row=0, column=7, padx=(5, 20), pady=(20, 5))
        
        # Progress Label
        progress_text = self._tr("model_trained") if self.data_df is not None else self._tr("init")
        self.progress_label = ctk.CTkLabel(self, text=progress_text, font=ctk.CTkFont(size=14), text_color="#3498db" if self.data_df is None else "green")
        self.progress_label.grid(row=1, column=0, columnspan=3, pady=(0, 10))

        # Tabview for left panel
        self.tabview = ctk.CTkTabview(self)
        self.tabview.grid(row=2, column=0, columnspan=2, padx=10, pady=10, sticky="nsew")
        
        tab_hist = self._tr("tab_history")
        tab_sim = self._tr("tab_sim")
        tab_rank = self._tr("tab_rankings")
        
        self.tabview.add(tab_hist)
        self.tabview.add(tab_sim)
        
        self.tabview.tab(tab_hist).grid_columnconfigure(0, weight=1)
        self.tabview.tab(tab_hist).grid_columnconfigure(1, weight=1)
        self.tabview.tab(tab_hist).grid_rowconfigure(0, weight=1)

        # Historique Frames
        self.tournaments_frame = ctk.CTkScrollableFrame(self.tabview.tab(tab_hist), label_text=self._tr("tournaments"))
        self.tournaments_frame.grid(row=0, column=0, padx=5, pady=5, sticky="nsew")

        self.matches_container = ctk.CTkFrame(self.tabview.tab(tab_hist), fg_color="transparent")
        self.matches_container.grid(row=0, column=1, padx=5, pady=5, sticky="nsew")
        self.matches_container.grid_rowconfigure(1, weight=1)
        self.matches_container.grid_columnconfigure(0, weight=1)

        self.analyze_tournament_btn = ctk.CTkButton(self.matches_container, text=self._tr("analyze_tournament"), fg_color="#8e44ad", hover_color="#7d3c98", command=self.on_analyze_tournament_click)
        self.analyze_tournament_btn.grid(row=0, column=0, padx=(5, 40), pady=(0, 5), sticky="ew")
        self.analyze_tournament_btn.grid_remove() # Hide initially

        # Petit bouton réglages à droite du bouton analyse
        self.settings_btn = ctk.CTkButton(self.matches_container, text="⚙️", width=30, fg_color="gray", command=self.show_analysis_settings)
        self.settings_btn.grid(row=0, column=0, padx=(0, 40), pady=(0, 5), sticky="e")
        self.settings_btn.grid_remove()

        # Bouton Optimiser
        self.optimizer_btn = ctk.CTkButton(self.matches_container, text="🔬", width=30, fg_color="#16a085", hover_color="#1abc9c", command=self.show_optimizer_window)
        self.optimizer_btn.grid(row=0, column=0, padx=(0, 5), pady=(0, 5), sticky="e")
        self.optimizer_btn.grid_remove()
        
        self.matches_frame = ctk.CTkFrame(self.matches_container)
        self.matches_frame.grid(row=3, column=0, sticky="nsew", padx=5, pady=5)
        
        # Petit message d'aide pour l'analyse détaillée
        self.double_click_hint = ctk.CTkLabel(self.matches_container, 
                                              text="💡 Double-cliquez sur une rencontre pour lancer l'analyse détaillée", 
                                              font=ctk.CTkFont(size=11, slant="italic"), text_color="#bdc3c7")
        self.double_click_hint.grid(row=2, column=0, pady=(0, 2), sticky="n")
        self.double_click_hint.grid_remove() # Masqué initialement
        
        # Table (Treeview) configuration
        style = ttk.Style()
        style.theme_use("default")
        style.configure("Treeview", background="#2b2b2b", foreground="white", fieldbackground="#2b2b2b", borderwidth=0, rowheight=35)
        style.map("Treeview", background=[('selected', '#3d3d3d')])
        style.configure("Treeview.Heading", background="#3d3d3d", foreground="white", relief="flat")
        
        self.matches_tree = ttk.Treeview(
            self.matches_frame, 
            columns=("p1", "p2", "res", "odds"), 
            show="headings",
            selectmode="browse"
        )
        
        self.matches_tree.heading("p1", text="👤 Joueur 1", command=lambda: self._sort_tree("p1", False))
        self.matches_tree.heading("p2", text="👤 Joueur 2", command=lambda: self._sort_tree("p2", False))
        self.matches_tree.heading("res", text="Résultat / Heure", command=lambda: self._sort_tree("res", False))
        self.matches_tree.heading("odds", text="Cotes", command=lambda: self._sort_tree("odds", False))
        
        self.matches_tree.column("p1", width=180, anchor="w")
        self.matches_tree.column("p2", width=180, anchor="w")
        self.matches_tree.column("res", width=120, anchor="center")
        self.matches_tree.column("odds", width=80, anchor="center")
        
        # Tags for coloring
        self.matches_tree.tag_configure("upcoming", foreground="#ff9f43")
        self.matches_tree.tag_configure("finished", foreground="#2ecc71")
        self.matches_tree.tag_configure("highlight", foreground="#e67e22")
        
        self.matches_tree.pack(fill="both", expand=True, side="left")
        
        scrollbar = ctk.CTkScrollbar(self.matches_frame, command=self.matches_tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.matches_tree.configure(yscrollcommand=scrollbar.set)
        
        self.matches_tree.bind("<Double-1>", self._on_tree_double_click)
        self.matches_tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        
        self.matches_container.grid_rowconfigure(2, weight=1)

        # Barre de recherche pour les matchs
        self.matches_search_frame = ctk.CTkFrame(self.matches_container, fg_color="transparent")
        self.matches_search_frame.grid(row=1, column=0, padx=5, pady=(0, 5), sticky="ew")
        
        self.matches_search_entry = ctk.CTkEntry(self.matches_search_frame, placeholder_text=self._tr("search_match_ph"))
        self.matches_search_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.matches_search_entry.bind("<KeyRelease>", self.on_search_matches)

        # Simulateur Libre Frames
        self.tabview.tab(tab_sim).grid_columnconfigure(0, weight=1)
        self.tabview.tab(tab_sim).grid_columnconfigure(1, weight=1)
        self.setup_simulator_ui()
        
        # Classements Frames
        self.tabview.add(tab_rank)
        self.tabview.tab(tab_rank).grid_columnconfigure(0, weight=1)
        self.tabview.tab(tab_rank).grid_columnconfigure(1, weight=1)
        self.setup_rankings_ui()

        self.analysis_frame = ctk.CTkScrollableFrame(self)
        self.analysis_frame.grid(row=2, column=2, padx=10, pady=10, sticky="nsew")

        self.setup_analysis_ui()

        # Bilan Tab
        tab_bilan = self._tr("tab_bilan")
        self.tabview.add(tab_bilan)
        self.setup_bilan_ui()

        # Live Tab
        self.tabview.add("🔴 Live")
        self.tabview.tab("🔴 Live").grid_columnconfigure(0, weight=1)
        self.tabview.tab("🔴 Live").grid_rowconfigure(1, weight=1)
        self.setup_live_ui()



    def setup_live_ui(self):
        """Onglet d'analyse en temps réel des matchs en cours."""
        tab = self.tabview.tab("🔴 Live")
        
        # Header
        header = ctk.CTkFrame(tab, fg_color="transparent")
        header.grid(row=0, column=0, padx=10, pady=8, sticky="ew")
        header.grid_columnconfigure(1, weight=1)
        
        ctk.CTkLabel(header, text="Analyse Live des Matchs en Cours",
                     font=ctk.CTkFont(size=18, weight="bold"),
                     text_color="#e74c3c").grid(row=0, column=0, padx=10, sticky="w")
        
        # Tour filter
        self.live_tour_var = ctk.StringVar(value="ATP+WTA")
        tour_menu = ctk.CTkOptionMenu(
            header,
            values=["ATP+WTA", "ATP", "WTA"],
            variable=self.live_tour_var,
            width=100,
            command=lambda _: self.refresh_live()
        )
        tour_menu.grid(row=0, column=1, padx=10, sticky="e")
        
        # Auto-refresh toggle
        self.live_auto_refresh = ctk.BooleanVar(value=True)
        auto_chk = ctk.CTkCheckBox(header, text="Auto-refresh (30s)",
                                    variable=self.live_auto_refresh,
                                    command=self._toggle_live_autorefresh)
        auto_chk.grid(row=0, column=2, padx=10)
        
        self.live_refresh_btn = ctk.CTkButton(
            header, text=self._tr("refresh"), width=100,
            fg_color="#e74c3c", hover_color="#c0392b",
            command=self.refresh_live
        )
        self.live_refresh_btn.grid(row=0, column=3, padx=10)

        # Challenger Filter
        self.live_hide_challengers = ctk.BooleanVar(value=True)
        chall_chk = ctk.CTkCheckBox(header, text="Masquer Challengers",
                                    variable=self.live_hide_challengers,
                                    command=self.refresh_live)
        chall_chk.grid(row=0, column=4, padx=10)
        
        # Value Bets Filter
        self.live_only_value_bets = ctk.BooleanVar(value=False)
        value_bets_chk = ctk.CTkCheckBox(header, text="🔥 Filtrer Opportunités (Value/Saumon)",
                                         variable=self.live_only_value_bets,
                                         command=self.refresh_live)
        value_bets_chk.grid(row=0, column=5, padx=10)
        
        self.live_status_label = ctk.CTkLabel(
            header, text="", text_color="gray", font=ctk.CTkFont(size=11)
        )
        self.live_status_label.grid(row=1, column=0, columnspan=4, padx=10, sticky="w")
        
        # Main scrollable area
        self.live_matches_frame = ctk.CTkScrollableFrame(
            tab, label_text="Matchs en cours",
            fg_color="#1a1a2e"
        )
        self.live_matches_frame.grid(row=1, column=0, padx=10, pady=5, sticky="nsew")
        self.live_matches_frame.grid_columnconfigure(0, weight=1)
        
        # Start auto-refresh loop
        self._live_refresh_job = None
        self.after(1000, self.refresh_live)  # Première mise à jour au démarrage

    def _toggle_live_autorefresh(self):
        if self.live_auto_refresh.get():
            self.refresh_live()
        elif self._live_refresh_job:
            self.after_cancel(self._live_refresh_job)
            self._live_refresh_job = None

    def refresh_live(self):
        """Rafraîchit le panneau d'analyse live."""
        import threading
        threading.Thread(target=self._fetch_and_render_live, daemon=True).start()

    def _fetch_and_render_live(self):
        def safe_status(txt, col):
            try:
                if hasattr(self, 'live_status_label') and self.live_status_label.winfo_exists():
                    self.live_status_label.configure(text=txt, text_color=col)
            except:
                pass

        def safe_render(live, finished):
            try:
                if hasattr(self, 'live_matches_frame') and self.live_matches_frame.winfo_exists():
                    self._render_live_matches(live, finished)
            except:
                pass

        try:
            from python.data.live_analysis import get_live_analysis_for_all, fetch_today_results

            tour_val = self.live_tour_var.get()
            tour_filter = None if tour_val == "ATP+WTA" else tour_val

            self.after(0, lambda: safe_status("Récupération des données live...", "orange"))

            from python.data.rapidapi_client import client
            try:
                today_str = datetime.now().strftime("%Y-%m-%d")
                client.populate_id_map_for_date(today_str, tour="atp")
                client.populate_id_map_for_date(today_str, tour="wta")
            except Exception as rapid_err:
                print(f"Erreur RapidAPI ID map: {rapid_err}")

            live_results = get_live_analysis_for_all(
                players_db=self.players_db,
                tour_filter=tour_filter
            )

            # Récupérer aussi les matchs terminés du jour + hier
            finished_results = []
            try:
                finished_results = fetch_today_results(tour_filter=tour_filter, days_back=1)
            except Exception as e_fin:
                print(f"Erreur chargement résultats terminés: {e_fin}")

            self.after(0, lambda: safe_render(live_results, finished_results))
        except Exception as e:
            self.after(0, lambda: safe_status(f"Erreur: {e}", "red"))
        finally:
            try:
                if hasattr(self, 'live_auto_refresh') and self.live_auto_refresh.winfo_exists() and self.live_auto_refresh.get():
                    self._live_refresh_job = self.after(30000, self.refresh_live)
            except:
                pass

    def _on_live_bet(self, match, player_name, prob_ia):
        from tkinter import simpledialog, messagebox
        import python.betting_manager as bm
        
        stake = simpledialog.askfloat("Pari Live", f"Montant de la mise sur {player_name} (€) :", initialvalue=10.0)
        if stake is None or stake <= 0:
            return
            
        odds = simpledialog.askfloat("Pari Live", f"Cote actuelle pour {player_name} :", initialvalue=1.80)
        if odds is None or odds <= 1.0:
            return
            
        match_info = {
            "player_1": match['p1_name'],
            "player_2": match['p2_name'],
            "tournament": f"Live - {match.get('tournament', 'Unknown')}"
        }
        
        bm.add_prediction(match_info, player_name, odds, prob_ia, stake)
        if hasattr(self, 'refresh_bilan'):
            self.refresh_bilan()
        messagebox.showinfo("Pari enregistré", f"Pari Live de {stake}€ sur {player_name} ajouté à vos pronos !")

    def _render_live_matches(self, results, finished_results=None):
        """Affiche les cartes de matchs live dans l'onglet."""

        import math
        
        # Guard : vérifier que le widget est toujours valide
        try:
            if not self.live_matches_frame.winfo_exists():
                return
        except Exception:
            return
        
        # Nettoyer l'ancienne liste
        try:
            for w in self.live_matches_frame.winfo_children():
                w.destroy()
        except Exception:
            return


        # Filtrage Challengers si demandé
        if hasattr(self, 'live_hide_challengers') and self.live_hide_challengers.get():
            def is_challenger(m):
                # On vérifie le tournoi ET le circuit (certains Challengers ne l'ont que dans le champ circuit/Cnm)
                full_text = f"{m.get('tournament', '')} {m.get('circuit', '')}".lower()
                return "challenger" in full_text
            
            results = [(m, a) for m, a in results if not is_challenger(m)]
            if finished_results:
                finished_results = [r for r in finished_results if not is_challenger(r)]

        # Filtrage Value Bets et Remontées (Saumon) si demandé
        if hasattr(self, 'live_only_value_bets') and self.live_only_value_bets.get():
            results = [(m, a) for m, a in results if a.get('is_value_bet', False) or a.get('is_comeback', False)]
            if finished_results:
                finished_results = []

        now_str = datetime.now().strftime("%H:%M:%S")
        count = len(results)
        
        if count == 0:
            self.live_status_label.configure(
                text=f"Aucun match en cours  |  Dernière MAJ: {now_str}",
                text_color="gray"
            )
            if not finished_results:
                ctk.CTkLabel(
                    self.live_matches_frame,
                    text="Aucun match ATP/WTA en cours pour le moment.",
                    text_color="gray", font=ctk.CTkFont(size=14)
                ).pack(pady=40)
                return
        else:
            self.live_status_label.configure(
                text=f"{count} match(s) en cours  |  Dernière MAJ: {now_str}",
                text_color="#2ecc71"
            )
        
        COLOR_MAP = {
            "green": "#27ae60", "lightgreen": "#2ecc71",
            "red": "#e74c3c", "orange": "#e67e22",
            "yellow": "#f39c12", "gray": "#95a5a6"
        }
        
        for match, analysis in results:
            is_val = analysis.get('is_value_bet', False)
            is_comb = analysis.get('is_comeback', False)
            
            if is_val:
                border_color = "#e67e22"
                border_w = 2
                fg_col = "#2a1b0d"
            elif is_comb:
                border_color = "#9b59b6"
                border_w = 2
                fg_col = "#201430"
            else:
                border_color = "#2c3e50"
                border_w = 1
                fg_col = "#16213e"
            
            card = ctk.CTkFrame(
                self.live_matches_frame,
                fg_color=fg_col, corner_radius=12,
                border_width=border_w, border_color=border_color
            )
            card.pack(fill="x", padx=10, pady=6)
            card.grid_columnconfigure(0, weight=1)
            
            # --- Ligne 1: Tournoi + Circuit ---
            header_frame = ctk.CTkFrame(card, fg_color="#0f3460", corner_radius=8)
            header_frame.pack(fill="x", padx=8, pady=(8, 0))
            
            if is_val:
                ctk.CTkLabel(
                    header_frame,
                    text="  🔥 VALUE BET  ",
                    fg_color="#e67e22", corner_radius=6,
                    font=ctk.CTkFont(size=10, weight="bold"),
                    text_color="white"
                ).pack(side="left", padx=(8, 2), pady=4)
            elif is_comb:
                ctk.CTkLabel(
                    header_frame,
                    text="  ⚡ REMONTÉE  ",
                    fg_color="#9b59b6", corner_radius=6,
                    font=ctk.CTkFont(size=10, weight="bold"),
                    text_color="white"
                ).pack(side="left", padx=(8, 2), pady=4)
                
            ctk.CTkLabel(
                header_frame,
                text=f"  {match['circuit']}  -  {match['tournament']}  |  Set {match['current_set']}",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color="#3498db"
            ).pack(side="left", padx=8, pady=4)
            
            # Status badge
            ctk.CTkLabel(
                header_frame,
                text=f"  {match['status']}  ",
                fg_color="#e74c3c", corner_radius=6,
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color="white"
            ).pack(side="right", padx=8, pady=4)
            
            # --- Ligne 2: Scores des joueurs ---
            scores_frame = ctk.CTkFrame(card, fg_color="transparent")
            scores_frame.pack(fill="x", padx=8, pady=4)
            scores_frame.grid_columnconfigure((0, 1, 2), weight=1)
            
            for col_idx, (pname, sets_won, prob, rank, is_server) in enumerate([
                (match['p1_name'], match['sets1'], analysis['prob1'],
                 analysis['p1_rank'], match['server'] == 1),
                (match['p2_name'], match['sets2'], analysis['prob2'],
                 analysis['p2_rank'], match['server'] == 2),
            ]):
                player_col = ctk.CTkFrame(scores_frame, fg_color="transparent")
                player_col.grid(row=0, column=col_idx * 2, padx=8, sticky="nsew")
                
                srv_txt = " ●" if is_server else "  "
                color = "#2ecc71" if prob > 55 else ("#e74c3c" if prob < 45 else "white")
                
                ctk.CTkLabel(
                    player_col,
                    text=f"{pname}{srv_txt}",
                    font=ctk.CTkFont(size=13, weight="bold"),
                    text_color=color
                ).pack(anchor="w")
                
                ctk.CTkLabel(
                    player_col,
                    text=f"Rank #{rank}  |  {sets_won} set(s)",
                    font=ctk.CTkFont(size=10),
                    text_color="gray"
                ).pack(anchor="w", pady=(0, 2))
                
                # NOUVEAU : Bouton pour parier sur le joueur
                btn = ctk.CTkButton(
                    player_col, text="💰 Parier", width=60, height=20,
                    font=ctk.CTkFont(size=10, weight="bold"),
                    fg_color="#27ae60", hover_color="#2ecc71",
                    command=lambda m=match, p=pname, pr=prob: self._on_live_bet(m, p, pr)
                )
                btn.pack(anchor="w", pady=(2, 0))
            
            # Set scores au centre
            sets_str = "   ".join([f"{s1}-{s2}" for s1, s2 in match['set_scores']])
            g1 = match['game_score1'] or '-'
            g2 = match['game_score2'] or '-'
            ctk.CTkLabel(
                scores_frame,
                text=f"{sets_str}\nJeu: {g1}-{g2}",
                font=ctk.CTkFont(size=14, weight="bold"),
                text_color="white",
                justify="center"
            ).grid(row=0, column=2, padx=12)
            
            # --- Ligne 3: Barre de probabilité ---
            prob_frame = ctk.CTkFrame(card, fg_color="transparent")
            prob_frame.pack(fill="x", padx=12, pady=(2, 4))
            prob_frame.grid_columnconfigure(1, weight=1)
            
            p1_short = match['p1_name'].split()[-1]
            p2_short = match['p2_name'].split()[-1]
            
            ctk.CTkLabel(prob_frame, text=f"{p1_short}",
                         font=ctk.CTkFont(size=10), text_color="#3498db",
                         width=80).grid(row=0, column=0, sticky="w")
            
            # Barre visuelle
            bar_outer = ctk.CTkFrame(prob_frame, height=12, fg_color="#2c3e50", corner_radius=6)
            bar_outer.grid(row=0, column=1, padx=6, sticky="ew")
            bar_outer.grid_columnconfigure(0, weight=1)
            bar_outer.update_idletasks()
            
            rec_color = COLOR_MAP.get(analysis['rec_color'], "#95a5a6")
            prob1_frac = max(0.02, min(0.98, analysis['prob1'] / 100))
            
            # On simule la barre avec deux labels côte à côte
            bar_frame = ctk.CTkFrame(bar_outer, fg_color="transparent", height=12)
            bar_frame.pack(fill="x")
            bar_p1 = ctk.CTkFrame(bar_frame, height=12,
                                   fg_color=rec_color, corner_radius=6)
            bar_p1.place(relx=0, rely=0, relwidth=prob1_frac, relheight=1)
            
            ctk.CTkLabel(prob_frame, text=f"{p2_short}",
                         font=ctk.CTkFont(size=10), text_color="#e74c3c",
                         width=80).grid(row=0, column=2, sticky="e")
            
            # --- Ligne 4: Probabilités + Recommandation ---
            reco_frame = ctk.CTkFrame(card, fg_color="#0a0a23", corner_radius=8)
            reco_frame.pack(fill="x", padx=8, pady=(0, 4))

            reco_color = COLOR_MAP.get(analysis['rec_color'], "white")

            # Badge SAUMON si remontée active
            is_salmon_event = analysis.get('is_comeback', False) or "SAUMON" in analysis['recommendation'] or "REMONTEE" in analysis['recommendation']
            if is_salmon_event:
                ctk.CTkLabel(
                    reco_frame,
                    text="  🐟 ",
                    font=ctk.CTkFont(size=14),
                    text_color="#e67e22"
                ).pack(side="left", padx=2, pady=6)

            ctk.CTkLabel(
                reco_frame,
                text=f"  {analysis['recommendation']}",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=reco_color
            ).pack(side="left", padx=4, pady=6)

            ctk.CTkLabel(
                reco_frame,
                text=f"{analysis['prob1']}% / {analysis['prob2']}%   Confiance: {analysis['confidence']}%  ",
                font=ctk.CTkFont(size=11),
                text_color="#bdc3c7"
            ).pack(side="right", padx=8, pady=6)

            # Tags Saumon / Momentum (streaks, breaks, fight)
            salmon_label = analysis.get('salmon_label', '')
            detail = analysis.get('detail', {})
            salmon_net = detail.get('salmon_net', 0)

            if salmon_label or abs(salmon_net) > 1:
                salmon_frame = ctk.CTkFrame(card, fg_color="#1a0a00", corner_radius=6)
                salmon_frame.pack(fill="x", padx=8, pady=(0, 8))

                # Barre momentum salmon
                net_color = "#e67e22" if salmon_net > 0 else "#3498db"
                tags1 = detail.get('salmon_tags1', [])
                tags2 = detail.get('salmon_tags2', [])

                if tags1:
                    p1_short = match['p1_name'].split()[-1]
                    ctk.CTkLabel(
                        salmon_frame,
                        text=f"  {p1_short}: " + " | ".join(tags1),
                        font=ctk.CTkFont(size=10, weight="bold"),
                        text_color="#e67e22"
                    ).pack(side="left", padx=8, pady=4)

                if tags2:
                    p2_short = match['p2_name'].split()[-1]
                    ctk.CTkLabel(
                        salmon_frame,
                        text=" | ".join(tags2) + f"  :{p2_short}  ",
                        font=ctk.CTkFont(size=10, weight="bold"),
                        text_color="#3498db"
                    ).pack(side="right", padx=8, pady=4)

                if not tags1 and not tags2 and abs(salmon_net) > 1:
                    ctk.CTkLabel(
                        salmon_frame,
                        text=f"  Momentum Saumon: {salmon_net:+.0f}%  ",
                        font=ctk.CTkFont(size=10),
                        text_color=net_color
                    ).pack(padx=8, pady=4)

        # --- Section: Résultats Terminés ---
        if finished_results:
            # Séparateur / Header
            header_sep = ctk.CTkFrame(self.live_matches_frame, height=2, fg_color="#34495e")
            header_sep.pack(fill="x", padx=20, pady=20)
            
            ctk.CTkLabel(
                self.live_matches_frame,
                text="🏆  RÉSULTATS RÉCENTS (Terminés)",
                font=ctk.CTkFont(size=14, weight="bold"),
                text_color="#95a5a6"
            ).pack(pady=(0, 10))

            for res in finished_results:
                f_card = ctk.CTkFrame(
                    self.live_matches_frame,
                    fg_color="#1a1a2e", corner_radius=10,
                    border_width=1, border_color="#2c3e50"
                )
                f_card.pack(fill="x", padx=15, pady=4)
                
                # Top info: Tournoi + Heure
                top_f = ctk.CTkFrame(f_card, fg_color="transparent")
                top_f.pack(fill="x", padx=8, pady=4)
                
                ctk.CTkLabel(
                    top_f,
                    text=f"{res['circuit']} - {res['tournament']}  |  {res['match_time']}",
                    font=ctk.CTkFont(size=10),
                    text_color="gray"
                ).pack(side="left", padx=5)
                
                # Badge Terminé
                badge_text = "TERMINÉ" if res['status'] == 'FT' else res['status']
                ctk.CTkLabel(
                    top_f,
                    text=f" {badge_text} ",
                    fg_color="#2c3e50", corner_radius=4,
                    font=ctk.CTkFont(size=9, weight="bold"),
                    text_color="#95a5a6"
                ).pack(side="right", padx=5)
                
                # Main result
                mid_f = ctk.CTkFrame(f_card, fg_color="transparent")
                mid_f.pack(fill="x", padx=10, pady=2)
                
                # Vainqueur en gras/couleur
                w_label = ctk.CTkLabel(
                    mid_f,
                    text=f"🏆 {res['winner']}",
                    font=ctk.CTkFont(size=12, weight="bold"),
                    text_color="#2ecc71"
                )
                w_label.pack(side="left")
                
                # Score au centre
                ctk.CTkLabel(
                    mid_f,
                    text=f"{res['score_str']}",
                    font=ctk.CTkFont(size=11, weight="bold"),
                    text_color="white"
                ).pack(side="right", padx=10)
                
                # Perdant
                bot_f = ctk.CTkFrame(f_card, fg_color="transparent")
                bot_f.pack(fill="x", padx=10, pady=(0, 6))
                ctk.CTkLabel(
                    bot_f,
                    text=f"      {res['loser']}",
                    font=ctk.CTkFont(size=11),
                    text_color="#95a5a6"
                ).pack(side="left")

    def setup_bilan_ui(self):
        tab = self.tabview.tab(self._tr("tab_bilan"))
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(4, weight=1)

        ctk.CTkLabel(tab, text=self._tr("bilan_title"), font=ctk.CTkFont(size=20, weight="bold")).grid(row=0, column=0, pady=10)

        # Settings Frame
        settings_frame = ctk.CTkFrame(tab, fg_color="transparent")
        settings_frame.grid(row=1, column=0, padx=20, pady=5, sticky="ew")
        
        ctk.CTkLabel(settings_frame, text="Déposer de l'argent (€) :").pack(side="left", padx=5)
        self.credit_entry = ctk.CTkEntry(settings_frame, width=70, placeholder_text="Ex: 50.00")
        self.credit_entry.pack(side="left", padx=5)
        self.credit_entry.bind("<Return>", lambda e: self.on_confirm_deposit())
        
        self.apply_deposit_btn = ctk.CTkButton(settings_frame, text="💳 Confirmer le dépôt", width=140, fg_color="#27ae60", hover_color="#2ecc71", command=self.on_confirm_deposit)
        self.apply_deposit_btn.pack(side="left", padx=(0, 15))
        
        self.total_deposited_label = ctk.CTkLabel(settings_frame, text="Total déposé : 0.00€", font=ctk.CTkFont(weight="bold"))
        self.total_deposited_label.pack(side="left", padx=10)
        
        ctk.CTkLabel(settings_frame, text="Mise par pari (€) par défaut :").pack(side="left", padx=(15, 5))
        self.stake_entry = ctk.CTkEntry(settings_frame, width=60)
        self.stake_entry.insert(0, "10")
        self.stake_entry.pack(side="left", padx=5)

        self.apply_stake_btn = ctk.CTkButton(settings_frame, text="💾 Appliquer aux paris en cours", width=180, fg_color="#34495e", command=self.on_apply_default_stake)
        self.apply_stake_btn.pack(side="left", padx=10)

        # Les boutons ont été déplacés dans le header global pour plus de clarté

        # --- NOUVEAU: Formulaire d'ajout manuel ---
        self.setup_manual_bet_ui(tab)

        # Stats Frame
        self.bilan_stats_frame = ctk.CTkFrame(tab)
        self.bilan_stats_frame.grid(row=3, column=0, padx=20, pady=10, sticky="nsew")
        self.bilan_stats_frame.grid_columnconfigure((0,1), weight=1)

        self.balance_label = ctk.CTkLabel(self.bilan_stats_frame, text=self._tr("total_balance") + "0€", font=ctk.CTkFont(size=16, weight="bold"))
        self.balance_label.grid(row=0, column=0, pady=10)

        self.profit_label = ctk.CTkLabel(self.bilan_stats_frame, text=self._tr("total_profit") + "0€", font=ctk.CTkFont(size=16, weight="bold"))
        self.profit_label.grid(row=0, column=1, pady=10)
        
        # Container pour les tuiles de stats
        self.bilan_tiles_frame = ctk.CTkFrame(self.bilan_stats_frame, fg_color="transparent")
        self.bilan_tiles_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=5, pady=5)

        # Predictions List
        self.predictions_frame = ctk.CTkScrollableFrame(tab, label_text="Historique des paris")
        self.predictions_frame.grid(row=4, column=0, padx=20, pady=10, sticky="nsew")
        tab.grid_rowconfigure(4, weight=2)

        self.refresh_bilan()

    def on_confirm_deposit(self):
        try:
            val_str = self.credit_entry.get().strip()
            if not val_str:
                return
            val = float(val_str)
            if val <= 0:
                return
            
            # Ajouter au capital actuel
            current_cap = self.analysis_settings.get("initial_capital", 100.0)
            new_cap = current_cap + val
            self.analysis_settings["initial_capital"] = new_cap
            
            from python.analysis_settings_manager import save_analysis_settings
            save_analysis_settings(self.analysis_settings)
            
            # Vider le champ
            self.credit_entry.delete(0, 'end')
            
            # Rafraîchir l'étiquette
            if getattr(self, 'total_deposited_label', None) and self.total_deposited_label.winfo_exists():
                self.total_deposited_label.configure(text=f"Total déposé : {new_cap:.2f}€")
                
            print(f"💰 Dépôt réussi de {val:.2f}€. Capital total : {new_cap:.2f}€")
            
            # Message box de confirmation
            from tkinter import messagebox
            messagebox.showinfo("Dépôt validé", f"Dépôt de {val:.2f}€ effectué avec succès !\nVotre capital total est maintenant de {new_cap:.2f}€.")
            
        except Exception as e:
            print(f"❌ Erreur lors du dépôt : {e}")
            from tkinter import messagebox
            messagebox.showerror("Erreur", "Veuillez entrer un montant numérique valide pour le dépôt.")
        self.refresh_bilan()

    def refresh_bilan(self):
        if not getattr(self, 'profit_label', None) or not self.profit_label.winfo_exists():
            return
            
        try:
            stake = float(self.stake_entry.get())
        except:
            stake = 10.0
            
        credit = self.analysis_settings.get("initial_capital", 100.0)
        
        # Mettre à jour l'étiquette du total déposé
        if getattr(self, 'total_deposited_label', None) and self.total_deposited_label.winfo_exists():
            self.total_deposited_label.configure(text=f"Total déposé : {credit:.2f}€")

        if self.data_df is not None:
            betting_manager.update_predictions_status(self.data_df)

        stats = betting_manager.calculate_stats(stake)
        preds = stats["predictions"]
        print(f"🔄 Rafraîchissement Bilan : {len(preds)} pronostics trouvés dans la base.")
        
        # Initialiser le registre de widgets si besoin
        if not hasattr(self, '_bilan_widgets'):
            self._bilan_widgets = []

        # Nettoyage robuste : on détruit les widgets enregistrés
        for w in self._bilan_widgets:
            try:
                if w.winfo_exists():
                    w.destroy()
            except:
                pass
        self._bilan_widgets = []

        profit = stats["total_profit"]
        self.profit_label.configure(
            text=f"{self._tr('total_profit')} {profit:.2f}€",
            text_color="green" if profit >= 0 else "red"
        )
        
        preds = stats["predictions"]
        won = stats["won_bets"]
        lost = stats["lost_bets"]
        pending = stats["pending_bets"]
        
        resolved = [p for p in preds if p["status"] in ("won", "lost")]
        total_staked = sum(p.get("stake", stake) for p in resolved)
        roi = (profit / total_staked * 100) if total_staked > 0 else 0.0
        win_rate = (won / (won + lost) * 100) if (won + lost) > 0 else 0.0
        avg_odds_won = (sum(p.get("odds", 1) for p in preds if p["status"] == "won") / won) if won > 0 else 0.0
        pending_stakes = sum(p.get("stake", stake) for p in preds if p.get("status") == "pending")
        balance = credit + profit - pending_stakes
        balance_text = f"Crédit restant : {balance:.2f}€  |  En cours: {pending_stakes:.2f}€  |  Profit: {profit:+.2f}€  |  ROI: {roi:+.1f}%"
        self.balance_label.configure(
            text=balance_text,
            text_color="green" if balance >= credit else "red"
        )

        # Mise à jour du frame de statistiques
        if not hasattr(self, 'bilan_tiles_frame') or not self.bilan_tiles_frame.winfo_exists():
            self.bilan_tiles_frame = ctk.CTkFrame(self.bilan_stats_frame, fg_color="transparent")
            self.bilan_tiles_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=5, pady=5)
            
        self.clear_frame(self.bilan_tiles_frame)
        self.bilan_tiles_frame.grid_columnconfigure((0, 1, 2, 3, 4, 5), weight=1)
        
        def stat_tile(col, label, value, color="white"):
            f = ctk.CTkFrame(self.bilan_tiles_frame, fg_color=("gray85", "gray20"), corner_radius=8)
            f.grid(row=0, column=col, padx=6, pady=6, sticky="nsew")
            ctk.CTkLabel(f, text=label, font=ctk.CTkFont(size=11), text_color="gray").pack(pady=(6, 0))
            ctk.CTkLabel(f, text=value, font=ctk.CTkFont(size=16, weight="bold"), text_color=color).pack(pady=(0, 6))
        
        stat_tile(0, "💶 Montant restant", f"{balance:.2f}€", "green" if balance >= credit else "red")
        stat_tile(1, "✅ Gagnés / ❌ Perdus", f"{won} / {lost}", "green" if won >= lost else "red")
        stat_tile(2, "⏳ En attente", str(pending), "orange")
        stat_tile(3, "💰 Profit Net", f"{profit:+.2f}€", "green" if profit >= 0 else "red")
        stat_tile(4, "📊 ROI", f"{roi:+.1f}%", "green" if roi >= 0 else "red")
        
        if avg_odds_won > 0:
            stat_tile(5, "📈 Cote moy.", f"{avg_odds_won:.2f}", "#f1c40f")

        self.clear_frame(self.predictions_frame)
        self.predictions_frame.configure(label_text=f"Historique des paris ({len(preds)} au total)")
        
        if not preds:
            lbl = ctk.CTkLabel(self.predictions_frame, text=self._tr("no_predictions"))
            lbl.pack(pady=20)
            self._bilan_widgets.append(lbl)
            return

        for p in preds:
            p_frame = ctk.CTkFrame(self.predictions_frame)
            p_frame.pack(fill="x", pady=2, padx=5)
            self._bilan_widgets.append(p_frame)
            
            color = "gray"
            if p["status"] == "won": color = "#2ecc71"
            elif p["status"] == "lost": color = "#e74c3c"
            elif p["status"] == "pending": color = "#f39c12"
            
            status_tr = self._tr(f"status_{p['status']}")
            profit_sign = "+" if p["profit"] > 0 else ""
            
            txt = f"[{p['tournament']}] {p['match']}\n"
            current_stake = p.get('stake', stake)
            txt += f"  Pick: {p['pick']} @ {p['odds']} (Mise: {current_stake:.2f}€)  |  {status_tr}  |  {profit_sign}{p['profit']:.2f}€"
            if p.get("result_score"):
                txt += f"  |  Score: {p['result_score']}"
            
            ctk.CTkLabel(p_frame, text=txt, justify="left", text_color=color,
                         font=ctk.CTkFont(size=12)).pack(side="left", padx=10, pady=5)
            
            # Boutons d'action
            actions_frame = ctk.CTkFrame(p_frame, fg_color="transparent")
            actions_frame.pack(side="right", padx=5)

            # Bouton Gagné
            won_btn = ctk.CTkButton(actions_frame, text="✅", width=30, fg_color="#27ae60", hover_color="#2ecc71",
                                    command=lambda p_id=p["id"]: self.on_set_status(p_id, "won"))
            won_btn.pack(side="left", padx=2)
            
            # Bouton Perdu
            lost_btn = ctk.CTkButton(actions_frame, text="❌", width=30, fg_color="#c0392b", hover_color="#e74c3c",
                                     command=lambda p_id=p["id"]: self.on_set_status(p_id, "lost"))
            lost_btn.pack(side="left", padx=2)

            # Bouton Supprimer
            del_btn = ctk.CTkButton(actions_frame, text="🗑", width=30, fg_color="#7f8c8d", hover_color="#95a5a6",
                                    command=lambda p_id=p["id"]: self.on_delete_prediction(p_id))
            del_btn.pack(side="left", padx=2)

            # Bouton Editer Mise
            edit_btn = ctk.CTkButton(actions_frame, text="💰", width=30, fg_color="#34495e", hover_color="#2c3e50",
                                     command=lambda p_id=p["id"], old_stake=p.get("stake", stake): self.on_edit_stake(p_id, old_stake))
            edit_btn.pack(side="left", padx=2)

    def setup_simulator_ui(self):
        tab = self.tabview.tab(self._tr("tab_sim"))
        
        ctk.CTkLabel(tab, text=self._tr("sim_desc"), font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, columnspan=2, pady=(10, 20))
        
        # Player 1 Search
        ctk.CTkLabel(tab, text=self._tr("p1")).grid(row=1, column=0, padx=10, pady=5, sticky="w")
        self.sim_p1_search = ctk.CTkEntry(tab, placeholder_text="Chercher joueur 1...", width=200)
        self.sim_p1_search.grid(row=2, column=0, padx=10, pady=(0, 5), sticky="ew")
        self.sim_p1_search.bind("<KeyRelease>", lambda e: self._filter_sim_combos(1))
        
        self.sim_p1_combo = ctk.CTkComboBox(tab, values=[self._tr("loading_options")], width=200)
        self.sim_p1_combo.grid(row=3, column=0, padx=10, pady=5, sticky="ew")
        
        # Player 2 Search
        ctk.CTkLabel(tab, text=self._tr("p2")).grid(row=1, column=1, padx=10, pady=5, sticky="w")
        self.sim_p2_search = ctk.CTkEntry(tab, placeholder_text="Chercher joueur 2...", width=200)
        self.sim_p2_search.grid(row=2, column=1, padx=10, pady=(0, 5), sticky="ew")
        self.sim_p2_search.bind("<KeyRelease>", lambda e: self._filter_sim_combos(2))
        
        self.sim_p2_combo = ctk.CTkComboBox(tab, values=[self._tr("loading_options")], width=200)
        self.sim_p2_combo.grid(row=3, column=1, padx=10, pady=5, sticky="ew")
        
        # Surface & Level
        ctk.CTkLabel(tab, text=self._tr("tournament_opt")).grid(row=4, column=0, padx=10, pady=(20, 5), sticky="w")
        self.sim_tourney_combo = ctk.CTkComboBox(tab, values=[self._tr("loading_options")], width=200)
        self.sim_tourney_combo.grid(row=5, column=0, padx=10, pady=5, sticky="ew")

        ctk.CTkLabel(tab, text=self._tr("level")).grid(row=4, column=1, padx=10, pady=(20, 5), sticky="w")
        self.sim_level_combo = ctk.CTkComboBox(tab, values=[self._tr("gs"), self._tr("m1000"), self._tr("atp500"), self._tr("davis")], width=200)
        self.sim_level_combo.grid(row=5, column=1, padx=10, pady=5, sticky="ew")
        self.sim_level_combo.set(self._tr("atp500"))
        
        ctk.CTkLabel(tab, text=self._tr("surface")).grid(row=6, column=0, padx=10, pady=(20, 5), sticky="w")
        self.sim_surface_combo = ctk.CTkComboBox(tab, values=[self._tr("hard"), self._tr("clay"), self._tr("grass")], width=200)
        self.sim_surface_combo.grid(row=7, column=0, padx=10, pady=5, sticky="ew")
        self.sim_surface_combo.set(self._tr("hard"))
        
        self.sim_btn = ctk.CTkButton(tab, text=self._tr("predict_btn"), font=ctk.CTkFont(weight="bold"), fg_color="#27ae60", command=self.on_simulate_click)
        self.sim_btn.grid(row=8, column=0, columnspan=2, pady=30)

    def setup_rankings_ui(self):
        tab = self.tabview.tab(self._tr("tab_rankings"))
        
        # Boutons pour les classements spéciaux (algorithme)
        self.salmon_btn = ctk.CTkButton(tab, text=self._tr("salmons"), font=ctk.CTkFont(weight="bold"), fg_color="#e67e22", command=self.show_salmons)
        self.salmon_btn.grid(row=0, column=0, padx=10, pady=10, sticky="ew")

        self.servers_btn = ctk.CTkButton(tab, text=self._tr("servers"), font=ctk.CTkFont(weight="bold"), fg_color="#3498db", command=self.show_top_servers)
        self.servers_btn.grid(row=0, column=1, padx=10, pady=10, sticky="ew")
        
        # Cadre pour le classement ATP
        self.atp_frame = ctk.CTkScrollableFrame(tab, label_text=f"{self._tr('gen_ranking')} ({self.current_tour})")
        self.atp_frame.grid(row=3, column=0, columnspan=2, padx=10, pady=10, sticky="nsew")
        tab.grid_rowconfigure(3, weight=1)
        
        # Barre de recherche
        self.search_frame = ctk.CTkFrame(tab, fg_color="transparent")
        self.search_frame.grid(row=1, column=0, columnspan=2, padx=10, pady=(0, 5), sticky="ew")
        
        self.search_entry = ctk.CTkEntry(self.search_frame, placeholder_text=self._tr("search_ph"))
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.search_entry.bind("<KeyRelease>", self.on_search_ranking)
        
        self.search_btn = ctk.CTkButton(self.search_frame, text=self._tr("search_btn"), width=100, command=self.on_search_ranking)
        self.search_btn.pack(side="right")

    def setup_analysis_ui(self):
        # Analysis Header
        self.analysis_title = ctk.CTkLabel(self.analysis_frame, text=self._tr("analysis_title"), font=ctk.CTkFont(size=20, weight="bold"))
        self.analysis_title.pack(pady=5)

        # Match Info
        self.match_info_label = ctk.CTkLabel(self.analysis_frame, text=self._tr("select_match"), font=ctk.CTkFont(size=16))
        self.match_info_label.pack(pady=2)

        self.score_label = ctk.CTkLabel(self.analysis_frame, text="", font=ctk.CTkFont(size=22, weight="bold"), text_color="#2ecc71")
        self.score_label.pack(pady=2)

        # Players comparison frame
        self.comp_frame = ctk.CTkFrame(self.analysis_frame, fg_color="transparent")
        self.comp_frame.pack(fill="both", expand=True, padx=20, pady=5)
        self.comp_frame.grid_columnconfigure(0, weight=1)
        self.comp_frame.grid_columnconfigure(1, weight=1)

        # Player name buttons - encadrés avec bordure visible
        self.p1_frame = ctk.CTkFrame(self.comp_frame, border_width=2, border_color="#3498db", corner_radius=8)
        self.p1_frame.grid(row=0, column=0, pady=(5,0), padx=10, sticky="ew")
        self.p1_name = ctk.CTkButton(self.p1_frame, text=self._tr("p1_btn"), font=ctk.CTkFont(size=18, weight="bold"), fg_color="transparent", text_color="#3498db", hover_color=("gray85", "gray25"), command=lambda: self.show_player_stats(1))
        self.p1_name.pack(padx=5, pady=3)
        
        self.p2_frame = ctk.CTkFrame(self.comp_frame, border_width=2, border_color="#3498db", corner_radius=8)
        self.p2_frame.grid(row=0, column=1, pady=(5,0), padx=10, sticky="ew")
        self.p2_name = ctk.CTkButton(self.p2_frame, text=self._tr("p2_btn"), font=ctk.CTkFont(size=18, weight="bold"), fg_color="transparent", text_color="#3498db", hover_color=("gray85", "gray25"), command=lambda: self.show_player_stats(2))
        self.p2_name.pack(padx=5, pady=3)

        self.stats_hint = ctk.CTkLabel(self.comp_frame, text="👆 Cliquer sur un nom pour voir la fiche du joueur", font=ctk.CTkFont(size=11, slant="italic"), text_color="gray")
        self.stats_hint.grid(row=1, column=0, columnspan=2, pady=(0, 5))

        self.p1_rank = ctk.CTkLabel(self.comp_frame, text=f"{self._tr('ranking')}-")
        self.p1_rank.grid(row=2, column=0, pady=2)

        self.p2_rank = ctk.CTkLabel(self.comp_frame, text=f"{self._tr('ranking')}-")
        self.p2_rank.grid(row=2, column=1, pady=2)

        # Predictions Frame
        self.pred_frame = ctk.CTkFrame(self.analysis_frame)
        self.pred_frame.pack(fill="x", padx=20, pady=10)

        self.pred_title = ctk.CTkLabel(self.pred_frame, text=self._tr("pred_title"), font=ctk.CTkFont(size=16, weight="bold"))
        self.pred_title.pack(pady=5)

        self.p1_prob_label = ctk.CTkLabel(self.pred_frame, text=f"{self._tr('prob_win')} {self._tr('p1')} : -%", text_color="green", font=ctk.CTkFont(size=16))
        self.p1_prob_label.pack(pady=2)

        self.p2_prob_label = ctk.CTkLabel(self.pred_frame, text=f"{self._tr('prob_win')} {self._tr('p2')} : -%", text_color="orange", font=ctk.CTkFont(size=16))
        self.p2_prob_label.pack(pady=2)

        # Odds Display
        self.odds_frame = ctk.CTkFrame(self.analysis_frame, fg_color="transparent")
        self.odds_frame.pack(fill="x", padx=20, pady=5)
        self.odds_label = ctk.CTkLabel(self.odds_frame, text="", font=ctk.CTkFont(size=15, weight="bold"), text_color="#f1c40f")
        self.odds_label.pack()
        
        # Betting Stats Frame
        self.betting_frame = ctk.CTkFrame(self.analysis_frame)
        self.betting_frame.pack(fill="x", padx=20, pady=10)
        
        self.betting_title = ctk.CTkLabel(self.betting_frame, text=self._tr("bet_stats"), font=ctk.CTkFont(size=16, weight="bold"))
        self.betting_title.pack(pady=10)
        
        self.betting_textbox = ctk.CTkTextbox(self.betting_frame, wrap="word", font=ctk.CTkFont(size=13), height=150)
        self.betting_textbox.pack(fill="x", padx=10, pady=(0, 10))
        self.betting_textbox.insert("0.0", self._tr("bet_select"))
        self.betting_textbox.configure(state="disabled")

        # AI Advice Frame
        self.ai_frame = ctk.CTkFrame(self.analysis_frame)
        self.ai_frame.pack(fill="both", expand=True, padx=20, pady=10)
        
        self.ai_buttons_frame = ctk.CTkFrame(self.ai_frame, fg_color="transparent")
        self.ai_buttons_frame.pack(pady=5)
        
        self.ai_btn = ctk.CTkButton(self.ai_buttons_frame, text=self._tr("ai_btn"), fg_color="#3498db", font=ctk.CTkFont(weight="bold"), command=self.on_ai_click)
        self.ai_btn.pack(side="left", padx=5)

        self.view_odds_btn = ctk.CTkButton(self.ai_buttons_frame, text=self._tr("view_odds"), fg_color="#27ae60", font=ctk.CTkFont(weight="bold"), command=self.show_detailed_odds)
        self.view_odds_btn.pack(side="left", padx=5)
        self.view_odds_btn.configure(state="disabled") # Disabled until a match is selected

        self.export_pdf_btn = ctk.CTkButton(self.ai_buttons_frame, text=self._tr("export_pdf"), fg_color="#27ae60", font=ctk.CTkFont(weight="bold"), command=self.export_analysis_pdf)
        self.export_pdf_btn.pack(side="left", padx=5)

        # Nouveau cadre pour les boutons d'enregistrement (pour éviter l'encombrement)
        self.save_buttons_frame = ctk.CTkFrame(self.ai_frame, fg_color="transparent")
        self.save_buttons_frame.pack(pady=5)

        self.save_bilan_btn = ctk.CTkButton(self.save_buttons_frame, text=self._tr("save_to_bilan"), fg_color="#e67e22", font=ctk.CTkFont(weight="bold"), width=200, command=self.on_save_individual_bet)
        self.save_bilan_btn.pack(side="left", padx=5)
        self.save_bilan_btn.configure(state="disabled")

        self.save_all_btn = ctk.CTkButton(self.save_buttons_frame, text=self._tr("save_to_bilan") + " (TOP)", fg_color="#e67e22", font=ctk.CTkFont(weight="bold"), width=200, command=self.save_all_opportunities)
        self.save_all_btn.pack(side="left", padx=5)
        self.save_all_btn.pack_forget() # Hidden by default
        
        self.ai_textbox = ctk.CTkTextbox(self.ai_frame, wrap="word", font=ctk.CTkFont(size=14))
        self.ai_textbox.pack(fill="both", expand=True, padx=10, pady=10)
        self.ai_textbox.insert("0.0", self._tr("ai_ready"))
        self.ai_textbox.configure(state="disabled")

        # --- NOUVEAU: Console de Logs en fenêtre séparée ---
        self.log_window = ctk.CTkToplevel(self)
        self.log_window.title("Console de Suivi")
        self.log_window.geometry("700x400")
        self.log_window.protocol("WM_DELETE_WINDOW", self.log_window.withdraw)
        
        self.log_textbox = ctk.CTkTextbox(self.log_window, wrap="word", font=ctk.CTkFont(family="Consolas", size=11), fg_color="black", text_color="#2ecc71")
        self.log_textbox.pack(fill="both", expand=True, padx=10, pady=(10, 5))
        self.log_textbox.insert("0.0", "> Système prêt. En attente d'analyse...\n")
        self.log_textbox.configure(state="disabled")
        
        def copy_logs():
            self.clipboard_clear()
            self.clipboard_append(self.log_textbox.get("0.0", "end"))
            
        self.copy_log_btn = ctk.CTkButton(self.log_window, text="Copier les logs", command=copy_logs, fg_color="#27ae60", hover_color="#2ecc71")
        self.copy_log_btn.pack(pady=(5, 10))
        
        # Bouton dans l'interface principale pour rouvrir la console si on la ferme
        self.show_logs_btn = ctk.CTkButton(self.analysis_frame, text="💻 Afficher la Console de Logs", command=self.log_window.deiconify, fg_color="#34495e")
        self.show_logs_btn.pack(fill="x", padx=20, pady=(5, 10))
        
        # Redirection des prints vers la console de l'UI et log.txt
        self.redirect_stdout()

    def redirect_stdout(self):
        import sys
        import os
        from datetime import datetime
        log_file_path = os.path.join(os.path.dirname(__file__), "log.txt")
        
        class StdoutRedirector:
            def __init__(self, textbox):
                self.textbox = textbox
            def write(self, string):
                if string.strip():
                    line = f"> {string.strip()}"
                    def _update(s=line):
                        try:
                            self.textbox.configure(state="normal")
                            self.textbox.insert("end", f"{s}\n")
                            self.textbox.see("end")
                            self.textbox.configure(state="disabled")
                        except Exception:
                            pass
                    # Exécuter dans le thread UI
                    if hasattr(self.textbox, "after"):
                        self.textbox.after(0, _update)
                    
                    # Sauvegarde dans log.txt
                    try:
                        with open(log_file_path, "a", encoding="utf-8") as f:
                            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {line}\n")
                    except Exception:
                        pass
            def flush(self):
                pass
        
        # Guard : si stdout est déjà redirigé
        if isinstance(sys.stdout, StdoutRedirector):
            sys.stdout.textbox = self.log_textbox
            return
        sys.stdout = StdoutRedirector(self.log_textbox)

    def on_tour_switch(self, value):
        self.current_tour = value
        if hasattr(self, 'search_entry'):
            self.search_entry.delete(0, "end")
        self.header.configure(text=self._tr("data_loading").format(value), text_color="white")
        self.clear_frame(self.tournaments_frame)
        # Clear matches
        for item in self.matches_tree.get_children():
            self.matches_tree.delete(item)
        self.clear_frame(self.atp_frame)
        self.show_loading_overlay(f"⏳ Chargement des données {value}")
        threading.Thread(target=self.load_data, args=(False,), daemon=True).start()

    def run_database_cleanup(self):
        self.show_loading_overlay("🧹 Nettoyage de la base de données")
        self.progress_label.configure(text="Nettoyage en cours...", text_color="orange")
        self.update()
        import subprocess
        import os
        import threading
        import sys
        import pandas as pd

        def run_scripts():
            try:
                from python.data.cleanup_utils import run_surgical_cleanup
                
                # Exécution du nettoyage chirurgical interne
                run_surgical_cleanup(progress_callback=self.update_progress)

                # Rechargement intelligent (on ne force pas le re-scrape total)
                self.update_progress("🧹 Redémarrage rapide de l'analyse...")
                
                # Charger directement les données en restant sous l'overlay de chargement
                self.load_data(force_update=False, reload_from_csv=True)

            except Exception as e:
                self.update_progress(f"❌ Erreur critique : {e}")
                self.after(2000, self.hide_loading_overlay)

            finally:
                pass

        threading.Thread(target=run_scripts, daemon=True).start()

    def run_api_test(self):
        self.show_loading_overlay("🔑 Test des clés The Odds API...")
        self.update_progress("Vérification des quotas en cours...")
        
        def run_test():
            try:
                from python.data.odds_api import test_odds_api, get_all_tennis_data
                results = test_odds_api()
                
                # Construire le message de résultat
                msg = "📊 RÉSULTATS API KEYS :\n\n"
                any_ok = False
                for r in results:
                    status_icon = "✅" if r['status'] == "OK" else "❌"
                    msg += f"{status_icon} Clé {r['key']} : {r['status']}\n"
                    if r['status'] == "OK":
                        msg += f"   ↳ Quota : {r['remaining']} restants (utilisés: {r['used']})\n\n"
                        any_ok = True
                    else:
                        msg += "\n"

                if any_ok:
                    msg += "\n🔄 Mise à jour des cotes en cours..."
                    self.update_progress(msg)
                    # Trigger actual odds update
                    get_all_tennis_data(force_update=True)
                    msg += "\n✅ Cotes actualisées avec succès !"
                else:
                    msg += "\n⚠️ Aucune clé n'est actuellement fonctionnelle."

                self.update_progress(msg)
                self.after(3000, self.hide_loading_overlay)
                
            except Exception as e:
                self.update_progress(f"❌ Erreur pendant le test : {e}")
                self.after(3000, self.hide_loading_overlay)

        threading.Thread(target=run_test, daemon=True).start()


    def update_progress(self, msg):
        # Mettre à jour le texte depuis n'importe quel thread
        def _update():
            self.progress_label.configure(text=msg)
            # Mettre à jour l'overlay s'il est visible
            if hasattr(self, '_overlay') and self._overlay is not None and self._overlay.winfo_exists():
                if hasattr(self, '_overlay_progress'):
                    self._overlay_progress.configure(text=msg)
        self.after(0, _update)

    def load_data(self, force_update=False, reload_from_csv=False, skip_training=False, skip_ui_refresh=False):
        if force_update:
            print("Actualisation complète en cours, veuillez patienter (temps supérieur à une minute)...")
            self.after(0, lambda: self.show_loading_overlay("⏳ Actualisation complète des données"))
        self.after(0, lambda: self.header.configure(text=self._tr("data_loading").format(self.current_tour), text_color="orange"))
        self.after(0, lambda: self.reset_btn.configure(state="disabled"))
        self.after(0, lambda: self.refresh_ui_btn.configure(state="disabled"))
        self.after(0, lambda: self.tour_switch.configure(state="disabled"))
        self.after(0, lambda: self.lang_switch.configure(state="disabled"))
        try:
            new_df, new_model, new_features, new_db = get_data_and_train_model(
                progress_callback=self.update_progress, 
                force_update=force_update,
                tour=self.current_tour,
                reload_from_csv=reload_from_csv,
                skip_training=skip_training
            )
            
            self.data_df = new_df
            self.players_db = new_db
            
            if not skip_training:
                self.model = new_model
                self.used_features = new_features
            
            if not skip_ui_refresh:
                # Force a complete refresh and reconstruction of the display (hard refresh)
                self.after(0, self.hard_refresh_ui)
        except Exception as e:
            error_msg = str(e)
            import traceback
            traceback.print_exc()
            self.after(0, lambda: self.hide_loading_overlay())
            self.after(0, lambda err=error_msg: self.header.configure(text=f"{self._tr('error_loading')}{err}", text_color="red"))
        finally:
            self.after(0, lambda: self.reset_btn.configure(state="normal"))
            self.after(0, lambda: self.refresh_ui_btn.configure(state="normal"))
            self.after(0, lambda: self.tour_switch.configure(state="normal"))
            self.after(0, lambda: self.lang_switch.configure(state="normal"))

    def on_data_loaded(self):
        # Masquer l'overlay immédiatement dès que les données principales sont prêtes
        self.after(0, self.hide_loading_overlay)
        
        self.reset_btn.configure(state="normal")
        self.refresh_ui_btn.configure(state="normal")
        self.header.configure(text=self._tr("ready"), text_color="green")
        self.progress_label.configure(text=self._tr("model_trained"), text_color="green")
        self.update_progress("✅ Prêt ! (Les classements se chargent en arrière-plan)")
        tournaments = get_recent_tournaments(self.data_df, lang=self.current_lang)
        
        # Invalider le cache salmon pour forcer un recalcul lors de la prochaine ouverture
        if self.players_db:
            for p in self.players_db.values():
                p._salmon_cache = None
        
        # Update Ranking label based on tour
        self.atp_frame.configure(label_text=f"{self._tr('gen_ranking')} ({self.current_tour})")
        
        # Vider la liste des tournois avant de la repeupler pour éviter les doublons
        self.clear_frame(self.tournaments_frame)
        self.tournament_buttons = {}
        
        self.analyze_global_btn = ctk.CTkButton(self.tournaments_frame, text="🌍 Analyse Globale du Jour", fg_color="#e67e22", hover_color="#d35400", command=self.on_analyze_global_click)
        self.analyze_global_btn.pack(pady=(5, 15), padx=10, fill="x")
        
        for t in tournaments:
            btn = ctk.CTkButton(self.tournaments_frame, text=t, command=lambda name=t: self.on_tournament_selected(name))
            btn.pack(pady=5, padx=10, fill="x")
            self.tournament_buttons[t] = btn
            
            # Si c'était le tournoi déjà sélectionné avant le refresh, on remet la couleur
            if hasattr(self, 'current_tournament_name') and t == self.current_tournament_name:
                btn.configure(fg_color="#2ecc71", hover_color="#27ae60")
            
        # Populate Comboboxes for Simulator
        if self.players_db:
            # Sort players by ranking (assuming valid ranking is numeric, ignoring 9999 and 0)
            valid_players = [p for p in self.players_db.values() if isinstance(p.ranking, (int, float))]
            valid_players.sort(key=lambda p: p.ranking if 0 < p.ranking < 9999 else 99999)
            player_names = [p.name for p in valid_players][:500] # Top 500
            
            if not player_names:
                player_names = [p.name for p in self.players_db.values()][:500]
                
            self.sim_p1_combo.configure(values=player_names)
            self.sim_p2_combo.configure(values=player_names)
            if len(player_names) >= 2:
                self.sim_p1_combo.set(player_names[0])
                self.sim_p2_combo.set(player_names[1])
                
        # Populate Tournaments for Simulator
        if self.data_df is not None:
            tourney_names = sorted([str(t) for t in self.data_df["tournament"].unique()])
            self.sim_tourney_combo.configure(values=tourney_names)
            if tourney_names:
                self.sim_tourney_combo.set(tourney_names[-1])

        # Start incremental RapidAPI enrichment for current tournaments in background
        import threading
        threading.Thread(target=self.run_incremental_rapidapi_enrichment, daemon=True).start()
                
        # Update Rankings buttons text if needed
        servers_key = "servers_wta" if self.current_tour == "WTA" else "servers"
        self.servers_btn.configure(text=self._tr(servers_key))
        
        # Populate ATP Rankings (Incremental loading to avoid UI stutter)
        if self.players_db:
            valid_players = [p for p in self.players_db.values() if isinstance(p.ranking, (int, float)) and 0 < p.ranking < 9999]
            valid_players.sort(key=lambda p: p.ranking)
            
            self.clear_frame(self.atp_frame)
            # Démarrer le chargement progressif, puis masquer l'overlay une fois terminé
            self.populate_rankings_incremental(valid_players[:100], 0, on_done=self.hide_loading_overlay)
        else:
            self.hide_loading_overlay()
            
        # Update Bilan status
        if self.data_df is not None:
            betting_manager.update_predictions_status(self.data_df)
            self.refresh_bilan()

    def run_incremental_rapidapi_enrichment(self):
        """
        Récupère progressivement les stats RapidAPI de tous les joueurs des tournois en cours.
        Ceci permet à 'Analyse Globale' et aux clics d'être instantanés et précis.
        """
        from python.data.rapidapi_client import client
        from python.app_logic import get_matches_for_tournament
        from python.data.tennisexplorer_scraper import scrape_player_rapidapi_history, scrape_player_te_history, merge_te_to_base_socle
        from datetime import datetime
        import time
        
        try:
            today_str = datetime.now().strftime("%Y-%m-%d")
            # 1. Populate ID map for today
            self.after(0, lambda: self.progress_label.configure(text=self._tr("model_trained") + " - Init API..."))
            client.populate_id_map_for_date(today_str, tour=self.current_tour.lower())
            
            # 2. Collect all unique players in upcoming matches
            unique_players = set()
            for t in self.tournament_buttons.keys():
                matches = get_matches_for_tournament(self.data_df, t, tour=self.current_tour, skip_scrape=True)
                for m in matches:
                    score = str(m['row_data'].get('score', '')).strip().lower()
                    if not score or score in ['upcoming', 'none', 'nan']:
                        unique_players.add(m['player_1'])
                        unique_players.add(m['player_2'])
            
            if not unique_players:
                self.after(0, lambda: self.progress_label.configure(text=self._tr("model_trained") + " (API OK)"))
                return

            total = len(unique_players)
            count = 0
            
            # 3. Fetch RapidAPI data for each player
            for p_name in unique_players:
                count += 1
                self.after(0, lambda c=count, t=total, p=p_name: self.progress_label.configure(
                    text=f"Enrichissement API... ({c}/{t}) : {p}", text_color="orange"
                ))
                
                r_id = client.get_player_id_by_name(p_name, tour=self.current_tour.lower())
                p_obj = None
                for p_iter in self.players_db.values():
                    if p_iter.name.lower() == p_name.lower():
                        p_obj = p_iter
                        break
                        
                if p_obj:
                    if r_id:
                        te_data = scrape_player_rapidapi_history(p_name, r_id)
                    else:
                        print(f"⚠️ RapidAPI ID introuvable pour {p_name} lors de l'enrichissement incrémental, fallback TennisExplorer")
                        te_data = scrape_player_te_history(p_name, nb_years=3)
                    
                    merge_te_to_base_socle(p_obj, te_data, self.players_db, tour=self.current_tour)
                        
                time.sleep(0.5)
                
            self.after(0, lambda: self.progress_label.configure(text=self._tr("model_trained") + f" (Enrichi : {total} joueurs)", text_color="green"))
            print(f"✅ Enrichissement incrémental RapidAPI terminé pour {total} joueurs.")
            
        except Exception as e:
            print(f"Erreur lors de l'enrichissement incrémental: {e}")
            self.after(0, lambda: self.progress_label.configure(text=self._tr("model_trained"), text_color="green"))

    def populate_rankings_incremental(self, players, start_idx, on_done=None):
        """Affiche les joueurs par petits groupes pour ne pas figer l'interface"""
        chunk_size = 10
        end_idx = min(start_idx + chunk_size, len(players))
        
        for i in range(start_idx, end_idx):
            p = players[i]
            frame = ctk.CTkFrame(self.atp_frame, fg_color="transparent")
            frame.pack(fill="x", pady=2, padx=5)
            
            ctk.CTkLabel(frame, text=f"#{p.ranking} {p.name}", font=ctk.CTkFont(weight="bold", size=14)).pack(side="left", padx=10, pady=5)
            btn = ctk.CTkButton(frame, text=self._tr("view_stats"), width=80, fg_color="#34495e", command=lambda name=p.name: self.show_player_stats(direct_name=name))
            btn.pack(side="right", padx=10, pady=5)
            
            if hasattr(p, 'ranking_points') and p.ranking_points > 0:
                ctk.CTkLabel(frame, text=f"{p.ranking_points} {self._tr('pts')}", text_color="gray").pack(side="right", padx=10, pady=5)
        
        if end_idx < len(players):
            # Planifier la suite au prochain cycle de l'event loop (10ms)
            self.after(10, lambda: self.populate_rankings_incremental(players, end_idx, on_done=on_done))
        else:
            # Chargement terminé : appeler le callback si fourni (ex: hide_loading_overlay)
            if on_done:
                self.after(50, on_done)

    def show_api_tokens(self):
        """Affiche le quota d'API restant"""
        from python.data.rapidapi_client import client
        from tkinter import messagebox
        
        if client.last_requests_remaining == "Inconnu":
            # On indique à l'utilisateur qu'on va interroger l'API
            self.progress_label.configure(text="Vérification du quota API en cours...")
            self.update()
            
            # Forcer une petite requête
            tour = self.current_tour.lower() if hasattr(self, 'current_tour') else "atp"
            client.force_refresh_quota(tour)
            
            self.progress_label.configure(text=self._tr("ready"))
            
        status = client.get_token_status()
        messagebox.showinfo("Quota API", f"Jetons RapidAPI restants :\n\n{status}")

    def on_search_ranking(self, event=None):
        if not self.players_db:
            return
            
        search_query = self.search_entry.get().lower().strip()
        
        # On repart de la liste complète des joueurs valides
        valid_players = [p for p in self.players_db.values() if isinstance(p.ranking, (int, float)) and 0 < p.ranking < 9999]
        valid_players.sort(key=lambda p: p.ranking)
        
        self.clear_frame(self.atp_frame)
        
        if search_query:
            # Filtrer par nom
            filtered = [p for p in valid_players if search_query in p.name.lower().replace(".", " ")]
            self.populate_rankings_incremental(filtered, 0)
        else:
            # Retour au Top 100 par défaut
            self.populate_rankings_incremental(valid_players[:100], 0)

    def clear_frame(self, frame):
        """Vider un cadre de tous ses widgets de manière sûre."""
        def _destroy_rec(w):
            for child in w.winfo_children():
                w_name = str(child).lower()
                if "canvas" in w_name or "scrollbar" in w_name or "scroll" in w_name:
                    _destroy_rec(child)
                else:
                    try:
                        child.destroy()
                    except:
                        pass
        _destroy_rec(frame)
        self.update_idletasks()

    def on_tournament_selected(self, tournament_name=None):
        """Sélection d'un tournoi : chargement des matchs en thread BG pour éviter le freeze."""
        # Mise en évidence visuelle du bouton sélectionné
        if hasattr(self, 'tournament_buttons'):
            for t_name, btn in self.tournament_buttons.items():
                if t_name == tournament_name:
                    btn.configure(fg_color="#2ecc71", hover_color="#27ae60") # Vert pour le sélectionné
                else:
                    # Reset aux couleurs par défaut de CustomTkinter
                    btn.configure(fg_color=["#3a7ebf", "#1f538d"], hover_color=["#325882", "#14375e"])
        
        self.current_tournament_name = tournament_name
        self.show_loading_overlay(f"⏳ Chargement des matchs")
        # Clear tree
        for item in self.matches_tree.get_children():
            self.matches_tree.delete(item)

        def _fetch_matches():
            matches = get_matches_for_tournament(self.data_df, tournament_name, tour=self.current_tour)
            
            # Enrichir tous les joueurs de ce tournoi de manière synchrone dans le thread d'arrière-plan
            self._enrich_matches_rapidapi(matches)
            
            # Une fois l'enrichissement terminé, afficher les matchs et masquer l'overlay
            self.after(0, lambda m=matches: self._populate_matches_ui(m))

        threading.Thread(target=_fetch_matches, daemon=True).start()

    def _enrich_matches_rapidapi(self, matches):
        """Récupère les infos manquantes via RapidAPI/TennisExplorer pour un groupe de matchs précis."""
        from python.data.rapidapi_client import client
        from python.data.tennisexplorer_scraper import scrape_player_rapidapi_history, scrape_player_te_history, merge_te_to_base_socle
        from datetime import datetime
        import time

        unique_players = set()
        for m in matches:
            unique_players.add(m['player_1'])
            unique_players.add(m['player_2'])
            
        if not unique_players: return
        
        total = len(unique_players)
        count = 0
        
        needs_reload = False
        for p_name in unique_players:
            count += 1
            # Mise à jour thread-safe de la progression sur l'overlay de chargement
            self.update_progress(f"Enrichissement API Tournoi... ({count}/{total}) : {p_name}")
            
            r_id = client.get_player_id_by_name(p_name, tour=self.current_tour.lower())
            p_obj = None
            for p_iter in self.players_db.values():
                if p_iter.name.lower() == p_name.lower():
                    p_obj = p_iter
                    break
                    
            if p_obj:
                # 1. Update live charting stats from Tennis Abstract
                print(f"📊 Mise à jour DNA Live pour {p_name}...")
                p_obj.update_with_live_charting()
                
                # 2. Enrich history from RapidAPI / TennisExplorer
                if r_id:
                    te_data = scrape_player_rapidapi_history(p_name, r_id)
                else:
                    print(f"⚠️ RapidAPI ID introuvable pour {p_name} lors de l'enrichissement du tournoi, fallback TennisExplorer")
                    te_data = scrape_player_te_history(p_name, nb_years=3)
                
                if merge_te_to_base_socle(p_obj, te_data, self.players_db, tour=self.current_tour):
                    needs_reload = True
                
            time.sleep(0.5)
            
        if needs_reload:
            print("🔄 Rechargement de la base de données (CSV -> in-memory)...")
            self.update_progress("Mise à jour des stats joueurs...")
            # Rechargement direct et synchrone dans le thread d'arrière-plan courant pour garantir
            # que les données sont prêtes au moment de l'affichage.
            try:
                self.load_data(reload_from_csv=True, skip_training=True, skip_ui_refresh=True)
            except Exception as e:
                print(f"Erreur lors du reload post-enrichissement : {e}")
            
        self.update_progress("✅ Prêt ! (Tournoi enrichi)")

    def on_refresh_matches(self):
        """Recharge les rencontres du tournoi actif (force la mise à jour depuis le CSV et LiveScore)."""
        if not hasattr(self, 'current_tournament_name') or not self.current_tournament_name:
            return
        self.show_loading_overlay(f"🔄 Mise à jour des rencontres...")
        
        def _reload():
            matches = get_matches_for_tournament(self.data_df, self.current_tournament_name, tour=self.current_tour)
            
            # Enrichir aussi les joueurs lors du rafraîchissement
            self._enrich_matches_rapidapi(matches)
            
            def _done(m=matches):
                self._populate_matches_ui(m)
            self.after(0, _done)

        threading.Thread(target=_reload, daemon=True).start()

    def on_search_matches(self, event=None):
        """Filtre les matchs du tournoi actuel par nom de joueur."""
        if not hasattr(self, 'all_tournament_matches') or not self.all_tournament_matches:
            return
            
        query = self.matches_search_entry.get().lower().strip()
        if not query:
            self._populate_matches_ui(self.all_tournament_matches, is_filtering=True)
            return
            
        filtered = [
            m for m in self.all_tournament_matches 
            if query in m['player_1'].lower() or query in m['player_2'].lower()
        ]
        self._populate_matches_ui(filtered, is_filtering=True)

    def _populate_matches_ui(self, matches, is_filtering=False):
        """Peuple le tableau de matchs, puis masque l'overlay."""
        if not is_filtering:
            self.all_tournament_matches = matches
        
        # Sort matches: upcoming first
        def is_match_upcoming(m):
            s = m['row_data'].get('score', '')
            if s is None or str(s).strip().lower() in ["", "none", "nan", "upcoming"]:
                return True
            return False
            
        matches = sorted(matches, key=lambda m: 0 if is_match_upcoming(m) else 1)
        self.current_matches = matches
        
        # Clear existing items
        for item in self.matches_tree.get_children():
            self.matches_tree.delete(item)
        
        for idx, match in enumerate(matches):
            row = match['row_data']
            score = row.get('score', '')
            
            # Round Display
            rnd_key = str(match['round'])
            rnd_display = self._tr('round_' + rnd_key)
            if rnd_display.startswith("round_"):
                rnd_display = rnd_key # Fallback
            
            # Sanitisation stricte : 'None', 'nan', vide => Upcoming
            if score is None or str(score).strip().lower() in ["", "none", "nan"]:
                score = "Upcoming"
            
            # Result / Time Display
            is_upcoming = (score == "Upcoming" or not str(score).strip())
            p1_display = match['player_1']
            p2_display = match['player_2']
            
            # Identify winner for trophy
            winner_idx = row.get('Winner') # 0 for P1, 1 for P2
            if not is_upcoming and winner_idx is not None:
                if str(winner_idx) == '0':
                    p1_display = f"🏆 {p1_display}"
                elif str(winner_idx) == '1':
                    p2_display = f"🏆 {p2_display}"
                
            if is_upcoming:
                res_display = match.get('full_time', 'À venir')
                tag = "upcoming"
                if match.get('time'): tag = "highlight"
            else:
                res_display = score
                tag = "finished"
            
            # Odds display
            odds_obj = match.get('odds')
            odds_display = "-"
            if odds_obj and 'odds' in odds_obj:
                o_dict = odds_obj['odds']
                # On utilise les noms de joueurs originaux (sans le trophée éventuel) pour matcher les clés
                p1_clean = match['player_1']
                p2_clean = match['player_2']
                o1 = o_dict.get(p1_clean)
                o2 = o_dict.get(p2_clean)
                if o1 and o2:
                    odds_display = f"{o1} / {o2}"
            
            self.matches_tree.insert(
                "", "end", iid=str(idx), 
                values=(p1_display, p2_display, res_display, odds_display),
                tags=(tag,)
            )
        
        # Show analysis button if matches found
        if matches:
            self.analyze_tournament_btn.grid()
            self.settings_btn.grid()
            self.optimizer_btn.grid()
            self.double_click_hint.grid() # Show the hint
            # Prefetch live charting for upcoming matches in background
            if not is_filtering:
                threading.Thread(target=self.prefetch_live_charting_for_matches, args=(matches,), daemon=True).start()
        else:
            self.analyze_tournament_btn.grid_remove()
            self.settings_btn.grid_remove()
            self.optimizer_btn.grid_remove()
            
        self.hide_loading_overlay()

    def prefetch_live_charting_for_matches(self, matches):
        """Pre-fetch DNA stats from Tennis Abstract for upcoming matches."""
        upcoming = [m for m in matches if str(m['row_data'].get('score', 'Upcoming')).strip() == 'Upcoming']
        if not upcoming: return
        
        # Limit to first 12 matches to avoid being blocked (covering most of a day's play)
        upcoming = upcoming[:12]
        
        print(f"📊 Pré-chargement DNA Live (Tennis Abstract) pour {len(upcoming)} matchs...")
        import time
        for m in upcoming:
            for p_name in [m['player_1'], m['player_2']]:
                p_obj = find_player_by_name(p_name, self.players_db)
                if p_obj and getattr(p_obj, '_ta_updated', False) is False:
                    # Update only if not already updated in this session
                    p_obj.update_with_live_charting()
                    p_obj._ta_updated = True 
                    time.sleep(0.4) # Small delay

    def _on_tree_double_click(self, event):
        """Analyse le match sélectionné par double-clic."""
        item_id = self.matches_tree.identify_row(event.y)
        if item_id:
            idx = int(item_id)
            match = self.current_matches[idx]
            self.on_match_selected(match)

    def _on_tree_select(self, event):
        """Optionnel : on pourrait aussi analyser au simple clic, mais le double-clic est plus sûr."""
        pass

    def _sort_tree(self, col, reverse):
        """Trie le tableau par colonne."""
        l = [(self.matches_tree.set(k, col), k) for k in self.matches_tree.get_children('')]
        
        # Tentative de tri numérique pour les cotes si possible
        def try_float(v):
            try: return float(v.split('/')[0].strip())
            except: return v

        l.sort(key=lambda t: try_float(t[0]), reverse=reverse)

        # Rearrange items in sorted order
        for index, (val, k) in enumerate(l):
            self.matches_tree.move(k, '', index)

        # Reverse sort next time
        self.matches_tree.heading(col, command=lambda: self._sort_tree(col, not reverse))

    def on_analyze_tournament_click(self):
        """Lance l'analyse Mistral sur toutes les rencontres du tournoi actuel."""
        if not self.current_matches:
            return
            
        self.show_loading_overlay(self._tr("ai_tournament_working"))
        self.ai_textbox.configure(state="normal")
        self.ai_textbox.delete("0.0", "end")
        self.ai_textbox.insert("0.0", f"🔄 {self._tr('ai_tournament_working')}\n")
        self.ai_textbox.configure(state="disabled")

        def run_analysis():
            try:
                from python.app_logic import analyze_tournament_odds
                report, opportunities, ou_suggestions = analyze_tournament_odds(
                    self.current_matches, self.model, self.used_features, self.players_db,
                    data_df=self.data_df,
                    min_history=self.analysis_settings["min_history"],
                    min_value=self.analysis_settings["min_value"],
                    min_odds=self.analysis_settings["min_odds"],
                    min_prob=self.analysis_settings["min_prob"],
                    ou_target_prob=self.analysis_settings["ou_target_prob"]
                )
                self.last_opportunities = opportunities[:7]
                self.last_ou_suggestions = ou_suggestions[:5]
                
                def update_ui():
                    self.ai_textbox.configure(state="normal")
                    self.ai_textbox.delete("0.0", "end")
                    self.ai_textbox.insert("0.0", report)
                    
                    if not opportunities and not ou_suggestions:
                        from tkinter import messagebox
                        messagebox.showinfo("Analyse", "Aucune opportunité détectée avec les réglages actuels.\n\nConseil : Essayez de baisser le seuil de Value ou l'historique minimum via la petite roue crantée ⚙️.")
                    else:
                        if opportunities:
                            self.ai_textbox.insert("end", "\n" + "-"*30 + "\n")
                            self.ai_textbox.insert("end", f"✨ {self._tr('prediction_saved') if hasattr(self, '_all_saved') else ''}")
                            
                            # Show the existing save all button
                            self.save_all_btn.pack(side="left", padx=5)
                            self.save_all_btn.configure(state="normal", text=self._tr("save_to_bilan") + " (TOP)")
                            self.save_bilan_btn.pack_forget() # Hide individual save during tournament analysis

                    self.ai_textbox.configure(state="disabled")
                    self.hide_loading_overlay()
                    
                self.after(0, update_ui)
            except Exception as e:
                print(f"CRITICAL ERROR in analysis: {e}")
                import traceback
                traceback.print_exc()
                err_msg = str(e)  # Capture dans une variable locale pour la lambda
                self.after(0, lambda msg=err_msg: [self.ai_textbox.configure(state='normal'), self.ai_textbox.insert('0.0', f'ERREUR: {msg}'), self.ai_textbox.configure(state='disabled'), self.hide_loading_overlay()])

        threading.Thread(target=run_analysis, daemon=True).start()

    def on_analyze_global_click(self):
        """Lance l'analyse sur toutes les rencontres à venir de la journée, tous tournois confondus (aligné sur le Bulletin)."""
        self.show_loading_overlay("Recherche globale des opportunités...")
        self.ai_textbox.configure(state="normal")
        self.ai_textbox.delete("0.0", "end")
        self.ai_textbox.insert("0.0", "🌍 Recherche globale des opportunités en cours...\n")
        self.ai_textbox.configure(state="disabled")

        def run_global_analysis():
            try:
                import pandas as pd
                import time
                import datetime
                import re
                import python.betting_manager as bm
                from python.app_logic import predict_match_outcome, calculate_betting_stats, get_data_and_train_model
                from python.data.odds_api import get_all_tennis_data
                
                # --- 1. CHARGEMENT MULTI-CIRCUITS (ATP + WTA) ---
                other_tour = "WTA" if self.current_tour == "ATP" else "ATP"
                
                self.after(0, lambda: self.show_loading_overlay(f"⏳ Synchronisation circuit {other_tour}..."))
                other_df, other_model, other_features, other_db = get_data_and_train_model(tour=other_tour, skip_training=False)
                
                self.after(0, lambda: self.show_loading_overlay("🎯 Analyse des cotes en direct..."))
                
                combined_db = {**self.players_db, **other_db}
                combined_df = pd.concat([self.data_df, other_df], ignore_index=True)
                
                model_atp = self.model if self.current_tour == "ATP" else other_model
                model_wta = other_model if self.current_tour == "ATP" else self.model
                features_atp = self.used_features if self.current_tour == "ATP" else other_features
                features_wta = other_features if self.current_tour == "ATP" else self.used_features

                min_prob_winner = self.analysis_settings.get("min_prob", 0.51)
                ou_target_prob = self.analysis_settings.get("ou_target_prob", 0.75)

                # --- 2. RÉCUPÉRATION DES COTES (ODDS API) ---
                odds_data = get_all_tennis_data()
                matches = odds_data.get('odds', [])
                
                if not matches:
                    self.after(0, lambda: [
                        self.hide_loading_overlay(),
                        self.ai_textbox.configure(state="normal"),
                        self.ai_textbox.delete("0.0", "end"),
                        self.ai_textbox.insert("0.0", "❌ Aucun match avec cotes trouvé aujourd'hui (Odds API).\n"),
                        self.ai_textbox.configure(state="disabled")
                    ])
                    return

                # --- 3. ANALYSE ET SÉLECTION DES PRONOSTICS ---
                def short_name(full_name, max_len=14):
                    s = str(full_name).strip()
                    if len(s) <= max_len:
                        return s
                    parts = s.split()
                    if len(parts) >= 3:
                        return parts[0][0].upper() + ". " + " ".join(parts[1:-1]) + " " + parts[-1][0].upper() + "."
                    elif len(parts) == 2:
                        return parts[0][0].upper() + ". " + parts[1]
                    return s

                match_data = []
                seen_signatures = []
                
                for match in matches:
                    try:
                        p1, p2 = match['home_team'], match['away_team']
                        
                        # --- DÉDOUBLONNAGE ROBUSTE ---
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

                        # Extraire les cotes
                        o1, o2 = "-", "-"
                        bookmakers = match.get('bookmakers', [])
                        if bookmakers:
                            b = bookmakers[0]
                            markets = b.get('markets', [])
                            for m in markets:
                                if m.get('key') == 'h2h':
                                    for out in m.get('outcomes', []):
                                        name = out.get('name', '')
                                        if p1.lower() in name.lower() or name.lower() in p1.lower():
                                            o1 = out.get('price', '-')
                                        elif p2.lower() in name.lower() or name.lower() in p2.lower():
                                            o2 = out.get('price', '-')
                                            
                        if o1 == "-" or o2 == "-":
                            continue
                        if float(o1) < 1.15 or float(o2) < 1.15:
                            continue
                            
                        # Filtrer les temps
                        commence_time_str = match.get('commence_time')
                        if commence_time_str:
                            try:
                                from datetime import datetime as dt_p, timezone
                                match_time = dt_p.strptime(commence_time_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                                if match_time < dt_p.now(timezone.utc):
                                    continue
                                if match_time.astimezone().date() > dt_p.now().astimezone().date():
                                    continue
                            except:
                                pass
                                
                        t_name = match.get('sport_title', 'Tennis')
                        t_name_low = t_name.lower()
                        
                        if any(x in t_name_low for x in ["challenger", "itf", "srx", "utr", "exhibition", "m15", "m25", "w15", "w25", "w35", "w50", "w75", "w100", "future"]):
                            continue
                            
                        t_name = t_name.replace(" - Singles", "").replace(" - Doubles", "")
                        t_short = t_name if len(t_name) <= 20 else t_name[:18].rstrip() + "…"
                        match_title = f"[{t_short}] {short_name(p1)} ({o1}) vs {short_name(p2)} ({o2})"

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

                        # Surface / Niveau
                        _t_surf_low = t_name.lower()
                        if any(x in _t_surf_low for x in ["roland", "garros", "french open", "clay", "terre battue", "barcelona", "madrid", "monte carlo", "rome", "internazionali", "buenos aires", "rio", "estoril", "lyon", "geneva", "hamburg"]):
                            _surface = "Clay"
                        elif any(x in _t_surf_low for x in ["wimbledon", "grass", "halle", "queens", "nottingham", "s-hertogenbosch"]):
                            _surface = "Grass"
                        else:
                            _surface = "Hard"

                        _level = "G" if any(x in _t_surf_low for x in ["roland", "garros", "french open", "wimbledon", "australian", "us open", "grand slam"]) else "M"

                        row = {
                            'player_1': p1, 'player_2': p2,
                            'tournament': t_name,
                            'tournament_surface': _surface,
                            'tournament_level': _level,
                            'round': 'R32'
                        }
                        
                        is_wta = 'WTA' in match.get('sport_title', '').upper()
                        current_model = model_wta if is_wta else model_atp
                        current_features = features_wta if is_wta else features_atp
                        
                        prob_1, prob_2, enrich_1, enrich_2, _ = predict_match_outcome(
                            current_model, row, current_features, combined_db, p1, p2,
                            tournament_name=t_name, skip_te_scrape=True
                        )
                        
                        is_salmon_match = enrich_1.get("is_salmon", False) or enrich_2.get("is_salmon", False)
                        salmon_boost = 0.5 if is_salmon_match else 0.0
                        if is_salmon_match:
                            match_title = f"🐟 {match_title}"
                        if enrich_1.get("home_crowd") or enrich_2.get("home_crowd"):
                            match_title = f"🏟️ {match_title}"
                        
                        current_match_picks = []

                        # 1. Winner / Value Bets
                        min_odds = 1.65
                        min_value = 1.01
                        winner_candidates = []
                        model_is_blind = (abs(prob_1 - 0.5) < 0.001 and abs(prob_2 - 0.5) < 0.001)

                        _seed_re_b = re.compile(r'\((\d+)\)')
                        def _seed_b(name):
                            m = _seed_re_b.search(str(name))
                            return int(m.group(1)) if m else None
                        seed_p1 = _seed_b(p1)
                        seed_p2 = _seed_b(p2)
                        p1_top20 = seed_p1 is not None and seed_p1 <= 20
                        p2_top20 = seed_p2 is not None and seed_p2 <= 20

                        try:
                            o1_f = float(o1)
                            v1 = prob_1 * o1_f
                            if (prob_1 >= min_prob_winner and v1 >= min_value and o1_f >= min_odds) or (prob_1 >= 0.40 and o1_f >= 2.00 and v1 >= min_value):
                                if not (p2_top20 and prob_1 < 0.60):
                                    winner_candidates.append((p1, prob_1, o1_f))
                        except: pass
                        
                        try:
                            o2_f = float(o2)
                            v2 = prob_2 * o2_f
                            if (prob_2 >= min_prob_winner and v2 >= min_value and o2_f >= min_odds) or (prob_2 >= 0.40 and o2_f >= 2.00 and v2 >= min_value):
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

                        # 2. Over/Under
                        sport_title_upper = str(match.get('sport_title', '')).upper()
                        t_name_upper = str(t_name).upper()
                        is_wta_match = 'WTA' in sport_title_upper or 'WOMEN' in sport_title_upper or 'FEMMES' in sport_title_upper or 'WTA' in t_name_upper or 'WOMEN' in t_name_upper
                        
                        is_grand_slam = any(x in t_name.lower() for x in ["roland", "french", "wimbledon", "australi", "us open", "new york", "grand slam"])
                        is_grand_slam_men = is_grand_slam and not is_wta_match

                        bet_stats = calculate_betting_stats(combined_df, p1, p2, prob_1, prob_2, surface="Hard", real_thresholds=real_thresholds if real_thresholds else None, is_salmon=is_salmon_match, is_bo5=is_grand_slam_men)

                        balance = min(prob_1, prob_2)
                        balance_ratio = balance / 0.5

                        if is_grand_slam_men:
                            ideal_threshold = 27.5 + balance_ratio * 13.0
                            full_range = [t * 0.5 for t in range(55, 83)]
                        else:
                            ideal_threshold = 18.5 + balance_ratio * 9.0
                            full_range = [t * 0.5 for t in range(37, 57)]

                        ideal_threshold = round(ideal_threshold * 2) / 2

                        # Label de contexte
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
                            thresholds_to_check = sorted([t for t in full_range if abs(t - ideal_threshold) <= 3.0])
                            if not thresholds_to_check:
                                thresholds_to_check = [ideal_threshold]

                        min_ou_prob = 0.45
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
                    except Exception as e_m:
                        print(f"Skipping match in global: {e_m}")
                        pass
                
                # Sélection finale (Top 6 avec WTA garanti)
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

                # --- 4. SAUVEGARDE AUTOMATIQUE AU BILAN ---
                stake = 10.0
                count_saved = 0
                existing_preds = bm.load_predictions()
                existing_ids = {p.get("id") for p in existing_preds if p.get("id")}
                
                opportunities = []
                ou_suggestions = []

                for m in top_matches:
                    p1 = m.get('p1', '')
                    p2 = m.get('p2', '')
                    t_name = m.get('t_name', 'Bulletin')
                    o1_raw = m.get('o1', '-')
                    o2_raw = m.get('o2', '-')

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
                                
                                opportunities.append({
                                    "match": f"{p1} vs {p2}",
                                    "pick": pick_label,
                                    "prob": raw_prob,
                                    "odds": odds,
                                    "tournament": t_name,
                                    "value": raw_prob * odds,
                                    "bookie": "Odds API"
                                })

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
                                
                                ou_suggestions.append({
                                    "match": f"{p1} vs {p2}",
                                    "pick": pick_label,
                                    "prob": raw_prob,
                                    "odds": odds,
                                    "tournament": t_name,
                                    "type": "OVER",
                                    "threshold": threshold,
                                    "bookie": "Odds API"
                                })
                            else:
                                continue

                            # Vérification de doublon
                            match_id = bm.get_prediction_id(p1, p2, t_name, bet_type)
                            if match_id not in existing_ids:
                                match_info = {
                                    "player_1": p1, "player_2": p2,
                                    "tournament": t_name,
                                    "match_id": match_id
                                }
                                bm.add_prediction(match_info, pick_label, odds, raw_prob, stake)
                                count_saved += 1
                        except Exception as e_save:
                            print(f"Error saving in global: {e_save}")

                self.last_opportunities = opportunities
                self.last_ou_suggestions = ou_suggestions

                # --- 5. COMBINÉ IA MISTRAL ---
                self.after(0, lambda: self.show_loading_overlay("🤖 Génération du Combiné IA Mistral..."))
                combined_bet_text = None
                try:
                    from python.app_logic import suggest_combined_bet
                    combined_bet_text = suggest_combined_bet(top_matches)
                except Exception as e_cb:
                    print(f"⚠️ Erreur combiné IA: {e_cb}")

                # --- 6. FORMATTAGE DU RAPPORT ---
                report = "🌍 **BULLETIN DU JOUR - TENNIS IA PRO**\n"
                report += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                report += "⚡ *Détection unifiée ATP & WTA - Format Bulletin Shorts*\n\n"
                
                if top_matches:
                    report += f"🚀 **TOP {len(top_matches)} OPPORTUNITÉS DU JOUR :**\n\n"
                    for idx, m in enumerate(top_matches, 1):
                        report += f"{idx}. **{m['title']}**\n"
                        for p in m['picks']:
                            emoji = "🏆" if p['type'] == 'Winner' else "🔥"
                            report += f"   - {emoji} Pronostic : **{p['display']}**\n"
                            if p.get('prob_text'):
                                report += f"     *{p['prob_text']}*\n"
                        report += "\n"
                else:
                    report += "ℹ️ Aucun prono fiable détecté pour aujourd'hui avec les cotes actuelles.\n\n"
                    
                report += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                if count_saved > 0:
                    report += f"✅ **{count_saved} NOUVEAUX PRONOSTICS ENREGISTRÉS AUTOMATIQUEMENT AU BILAN !**\n"
                else:
                    report += "✨ Tous les pronostics sont déjà présents au bilan !\n"

                # Ajouter le combiné IA si disponible
                if combined_bet_text:
                    report += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    report += f"🤖 **COMBINÉ IA MISTRAL DU JOUR**\n"
                    report += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    report += combined_bet_text + "\n"


                def update_ui():
                    self.ai_textbox.configure(state="normal")
                    self.ai_textbox.delete("0.0", "end")
                    self.ai_textbox.insert("0.0", report)
                    self.ai_textbox.configure(state="disabled")
                    
                    if opportunities:
                        self.save_all_btn.pack(side="left", padx=5)
                        self.save_all_btn.configure(state="disabled", text=f"✅ {len(top_matches)} Pronos Bulletin Sauvés")
                        self.save_bilan_btn.pack_forget()
                        self.refresh_bilan()
                    
                    self.hide_loading_overlay()
                    
                self.after(0, update_ui)
                
            except Exception as e:
                print(f"CRITICAL ERROR in global analysis: {e}")
                import traceback
                traceback.print_exc()
                err_msg = str(e)
                self.after(0, lambda msg=err_msg: [self.ai_textbox.configure(state='normal'), self.ai_textbox.insert('0.0', f'ERREUR: {msg}'), self.ai_textbox.configure(state='disabled'), self.hide_loading_overlay()])

        threading.Thread(target=run_global_analysis, daemon=True).start()

    def show_analysis_settings(self):
        """Ouvre une popup pour ajuster les paramètres de détection."""
        if hasattr(self, 'settings_popup') and self.settings_popup.winfo_exists():
            self.settings_popup.lift()
            return

        self.settings_popup = ctk.CTkToplevel(self)
        popup = self.settings_popup
        popup.title("Réglages Détection")
        popup.geometry("350x480")
        popup.grab_set()
        
        ctk.CTkLabel(popup, text="Paramètres d'Analyse Globale", font=ctk.CTkFont(size=16, weight="bold")).pack(pady=20)
        
        # Min History
        hist_label = ctk.CTkLabel(popup, text=f"Historique min. ({self.analysis_settings['min_history']} matchs)")
        hist_label.pack()
        hist_slider = ctk.CTkSlider(popup, from_=0, to=30, number_of_steps=30, 
                                    command=lambda v: hist_label.configure(text=f"Historique min. ({int(v)} matchs)"))
        hist_slider.set(self.analysis_settings['min_history'])
        hist_slider.pack(pady=5)
        
        # Min Value
        value_label = ctk.CTkLabel(popup, text=f"Seuil de Value ({self.analysis_settings['min_value']:.2f})")
        value_label.pack()
        value_slider = ctk.CTkSlider(popup, from_=1.0, to=2.0, number_of_steps=20,
                                     command=lambda v: value_label.configure(text=f"Seuil de Value ({v:.2f})"))
        value_slider.set(self.analysis_settings['min_value'])
        value_slider.pack(pady=5)
        
        # Min Odds
        odds_label = ctk.CTkLabel(popup, text=f"Cote min. ({self.analysis_settings['min_odds']:.2f})")
        odds_label.pack()
        odds_slider = ctk.CTkSlider(popup, from_=1.1, to=3.0, number_of_steps=19,
                                    command=lambda v: odds_label.configure(text=f"Cote min. ({v:.2f})"))
        odds_slider.set(self.analysis_settings['min_odds'])
        odds_slider.pack(pady=5)
        
        # Min Prob (vainqueur)
        prob_label = ctk.CTkLabel(popup, text=f"Probabilité min. vainqueur ({self.analysis_settings['min_prob']*100:.0f}%)")
        prob_label.pack()
        prob_slider = ctk.CTkSlider(popup, from_=0.30, to=0.80, number_of_steps=50,
                                    command=lambda v: prob_label.configure(text=f"Probabilité min. vainqueur ({int(v*100)}%)"))
        prob_slider.set(self.analysis_settings['min_prob'])
        prob_slider.pack(pady=5)

        # Séparateur
        ctk.CTkLabel(popup, text="── Over / Under ──", text_color="gray", font=ctk.CTkFont(size=11)).pack(pady=(8, 0))

        # OU Target Prob
        ou_prob_val = self.analysis_settings.get('ou_target_prob', 0.75)
        ou_prob_label = ctk.CTkLabel(popup, text=f"Confiance min. O/U ({ou_prob_val*100:.0f}%)", text_color="#1abc9c")
        ou_prob_label.pack()
        ou_prob_slider = ctk.CTkSlider(popup, from_=0.55, to=0.95, number_of_steps=40,
                                       command=lambda v: ou_prob_label.configure(text=f"Confiance min. O/U ({int(v*100)}%)"),
                                       button_color="#1abc9c", button_hover_color="#16a085")
        ou_prob_slider.set(ou_prob_val)
        ou_prob_slider.pack(pady=5)
        
        def save():
            self.analysis_settings['min_history'] = int(hist_slider.get())
            self.analysis_settings['min_value'] = round(value_slider.get(), 2)
            self.analysis_settings['min_odds'] = round(odds_slider.get(), 2)
            self.analysis_settings['min_prob'] = round(prob_slider.get(), 2)
            self.analysis_settings['ou_target_prob'] = round(ou_prob_slider.get(), 2)
            from python.analysis_settings_manager import save_analysis_settings
            save_analysis_settings(self.analysis_settings)
            popup.destroy()
            
        ctk.CTkButton(popup, text="Enregistrer", command=save).pack(pady=20)

    def show_optimizer_window(self):
        """Fenêtre d'optimisation par backtesting: vainqueur + Over/Under."""
        if self.data_df is None or self.model is None:
            from tkinter import messagebox
            messagebox.showwarning("Optimisation", "Les données doivent être chargées avant de lancer l'optimisation.")
            return

        if hasattr(self, 'optimizer_popup') and self.optimizer_popup.winfo_exists():
            self.optimizer_popup.lift()
            return

        self.optimizer_popup = ctk.CTkToplevel(self)
        popup = self.optimizer_popup
        popup.title("🔬 Optimisation des Paramètres")
        popup.geometry("700x560")
        popup.grab_set()

        # Header
        ctk.CTkLabel(popup, text="🔬 Optimisation par Backtesting",
                     font=ctk.CTkFont(size=18, weight="bold"), text_color="#1abc9c").pack(pady=(18, 4))
        ctk.CTkLabel(popup, text="Analyse les matchs historiques pour trouver les meilleurs seuils",
                     font=ctk.CTkFont(size=12), text_color="gray").pack(pady=(0, 10))

        # Progress bar area
        progress_frame = ctk.CTkFrame(popup, fg_color="transparent")
        progress_frame.pack(fill="x", padx=20, pady=(0, 8))
        progress_bar = ctk.CTkProgressBar(progress_frame, width=600)
        progress_bar.set(0)
        progress_bar.pack(fill="x")
        progress_label = ctk.CTkLabel(progress_frame, text="En attente du lancement...", text_color="gray",
                                      font=ctk.CTkFont(size=11))
        progress_label.pack(pady=2)

        # Two-tab results area
        tabs = ctk.CTkTabview(popup)
        tabs.pack(fill="both", expand=True, padx=15, pady=5)
        tab_winner = tabs.add("🏆 Pronostic Vainqueur")
        tab_ou = tabs.add("🎯 Over / Under")

        winner_text = ctk.CTkTextbox(tab_winner, font=ctk.CTkFont(family="Courier New", size=12), state="disabled")
        winner_text.pack(fill="both", expand=True, padx=5, pady=5)

        ou_text = ctk.CTkTextbox(tab_ou, font=ctk.CTkFont(family="Courier New", size=12), state="disabled")
        ou_text.pack(fill="both", expand=True, padx=5, pady=5)

        # Buttons frame
        btn_frame = ctk.CTkFrame(popup, fg_color="transparent")
        btn_frame.pack(fill="x", padx=15, pady=8)

        apply_winner_btn = ctk.CTkButton(btn_frame, text="Appliquer (Vainqueur)", state="disabled",
                                          fg_color="#16a085", hover_color="#1abc9c", width=180)
        apply_winner_btn.pack(side="left", padx=5)

        apply_ou_btn = ctk.CTkButton(btn_frame, text="Appliquer (O/U)", state="disabled",
                                      fg_color="#8e44ad", hover_color="#9b59b6", width=160)
        apply_ou_btn.pack(side="left", padx=5)

        ctk.CTkButton(btn_frame, text="Fermer", fg_color="gray", width=100,
                      command=popup.destroy).pack(side="right", padx=5)

        launch_btn = ctk.CTkButton(btn_frame, text="▶ Lancer l'optimisation",
                                    fg_color="#e67e22", hover_color="#d35400", width=180)
        launch_btn.pack(side="right", padx=5)

        # State containers
        best_winner = {"min_prob": None, "min_history": None}
        best_ou = {"target_prob": None}

        def update_progress(val, msg="Calcul en cours..."):
            popup.after(0, lambda: [progress_bar.set(val), progress_label.configure(text=msg)])

        def write_text(widget, content):
            widget.configure(state="normal")
            widget.delete("0.0", "end")
            widget.insert("0.0", content)
            widget.configure(state="disabled")

        def run_backtest():
            from python.app_logic import backtest_winner_optimizer, backtest_ou_optimizer
            import threading

            launch_btn.configure(state="disabled", text="⏳ Calcul...")
            update_progress(0.02, "Backtesting vainqueur (peut prendre 30s)...")

            # --- WINNER BACKTEST ---
            winner_results = backtest_winner_optimizer(
                self.data_df, self.model, self.used_features, self.players_db,
                progress_callback=lambda v: update_progress(v * 0.5, f"Vainqueur: {int(v*100)}%"),
                max_matches=600
            )

            update_progress(0.52, "Backtesting Over/Under...")

            # --- O/U BACKTEST ---
            ou_results = backtest_ou_optimizer(
                self.data_df, self.players_db,
                progress_callback=lambda v: update_progress(v, f"Over/Under: {int((v-0.5)*200)}%"),
                max_matches=600
            )

            update_progress(1.0, "Terminé ✅")

            # ---- Build Winner Table ----
            def build_winner_table():
                if not winner_results:
                    write_text(winner_text, "Pas assez de données pour le backtesting.")
                    return

                # Find best combo (balance win_rate × coverage)
                best_score, best_key = -1.0, None
                for key, val in winner_results.items():
                    n = val["n_bets"]
                    wr = val["win_rate"]
                    if n >= 15:
                        score = wr * min(1.0, n / 50)
                        if score > best_score:
                            best_score, best_key = score, key

                if best_key:
                    best_winner["min_prob"] = best_key[0]
                    best_winner["min_history"] = best_key[1]

                # Sort by min_prob then min_history
                sorted_keys = sorted(winner_results.keys())
                lines = [f"{'Seuil':>8}  {'Hist.':>6}  {'Réussite':>10}  {'N Matchs':>10}  {'N OK':>6}"]
                lines.append("-" * 48)
                for key in sorted_keys:
                    val = winner_results[key]
                    mp, mh = key
                    star = "★ " if key == best_key else "  "
                    lines.append(f"{star}{mp*100:>5.0f}%   {mh:>5}    {val['win_rate']*100:>7.1f}%    {val['n_bets']:>8}   {val['n_correct']:>5}")

                if best_key:
                    lines.append("")
                    lines.append(f"★ Meilleur équilibre : min_prob={best_key[0]*100:.0f}%, hist={best_key[1]}")
                    lines.append(f"  Réussite : {winner_results[best_key]['win_rate']*100:.1f}% sur {winner_results[best_key]['n_bets']} matchs")

                write_text(winner_text, "\n".join(lines))
                if best_key:
                    apply_winner_btn.configure(state="normal",
                        text=f"Appliquer (prob={best_key[0]*100:.0f}%, hist={best_key[1]})")

            # ---- Build O/U Table ----
            def build_ou_table():
                if not ou_results or "by_surface" not in ou_results:
                    write_text(ou_text, "Pas assez de données pour le backtesting O/U.")
                    return

                best_tp = ou_results.get("best_target_prob", 0.75)
                best_ou["target_prob"] = best_tp

                lines = ["=== Seuil de confiance O/U (toutes surfaces) ===\n"]
                lines.append(f"{'Seuil':>8}  {'Réussite':>10}  {'N Signaux':>10}")
                lines.append("-" * 35)
                all_surface = ou_results["by_surface"].get("All", {})
                for tp in sorted(all_surface.keys()):
                    data = all_surface[tp]
                    star = "★ " if tp == best_tp else "  "
                    lines.append(f"{star}{tp*100:>5.0f}%    {data['win_rate']*100:>7.1f}%    {data['n_signals']:>9}")

                lines.append(f"\n★ Meilleur seuil O/U : {best_tp*100:.0f}%")
                lines.append("")
                lines.append("=== Thresholds les plus fiables par surface ===\n")
                icons = {"Clay": "🟤", "Hard": "🔵", "Grass": "🟢", "All": "⚪"}
                for surf, info in ou_results.get("best_thresholds", {}).items():
                    if surf == "All":
                        continue
                    icon = icons.get(surf, "")
                    t = info.get("threshold", "?")
                    wr = info.get("win_rate", 0)
                    n = info.get("n_signals", 0)
                    lines.append(f"  {icon} {surf:<6}: threshold {t} → {wr*100:.1f}% réussite ({n} signaux)")

                lines.append("")
                lines.append("=== Détail par seuil (Argile / Clay) ===")
                clay_thresh = ou_results["threshold_accuracy"].get("Clay", {})
                for t in sorted(clay_thresh.keys()):
                    d = clay_thresh[t]
                    lines.append(f"  {t:>5} : {d['win_rate']*100:.1f}% ({d['n_signals']} signaux)")

                write_text(ou_text, "\n".join(lines))
                apply_ou_btn.configure(state="normal",
                    text=f"Appliquer (O/U seuil={best_tp*100:.0f}%)")

            popup.after(0, build_winner_table)
            popup.after(0, build_ou_table)
            popup.after(0, lambda: launch_btn.configure(state="normal", text="▶ Relancer"))

        def on_apply_winner():
            if best_winner["min_prob"] is not None:
                self.analysis_settings["min_prob"] = best_winner["min_prob"]
                self.analysis_settings["min_history"] = best_winner["min_history"]
                from python.analysis_settings_manager import save_analysis_settings
                save_analysis_settings(self.analysis_settings)
                from tkinter import messagebox
                messagebox.showinfo("Appliqué", f"Paramètres vainqueur mis à jour :\n  min_prob = {best_winner['min_prob']*100:.0f}%\n  min_history = {best_winner['min_history']} matchs")

        def on_apply_ou():
            if best_ou["target_prob"] is not None:
                self.analysis_settings["ou_target_prob"] = best_ou["target_prob"]
                from python.analysis_settings_manager import save_analysis_settings
                save_analysis_settings(self.analysis_settings)
                from tkinter import messagebox
                messagebox.showinfo("Appliqué", f"Seuil O/U mis à jour :\n  target_prob = {best_ou['target_prob']*100:.0f}%")

        apply_winner_btn.configure(command=on_apply_winner)
        apply_ou_btn.configure(command=on_apply_ou)
        launch_btn.configure(command=lambda: threading.Thread(target=run_backtest, daemon=True).start())


    def save_all_opportunities(self):
        """Enregistre toutes les opportunités détectées (Value Bets et Over/Under) dans le bilan."""
        if not hasattr(self, 'last_opportunities') and not hasattr(self, 'last_ou_suggestions'):
            return

            
        try:
            stake = float(self.stake_entry.get())
        except:
            stake = 10.0
            
        tour_name = "Tournoi Actuel"
        if hasattr(self, 'all_tournament_matches') and self.all_tournament_matches:
            tour_name = self.all_tournament_matches[0].get("row_data", {}).get("tournament", "Tournoi")

        count_value = 0
        count_ou = 0
        import python.betting_manager as bm
        
        # 1. Sauvegarder les Value Bets
        if hasattr(self, 'last_opportunities'):
            for opt in self.last_opportunities:
                try:
                    # Découpage robuste : on split sur " vs " et on nettoie
                    parts = [p.strip() for p in opt["match"].split(" vs ")]
                    if len(parts) != 2: continue
                    p1, p2 = parts
                    
                    t_name = opt.get("tournament", tour_name)
                    match_info = {
                        "player_1": p1, "player_2": p2,
                        "tournament": t_name,
                        "match_id": bm.get_prediction_id(p1, p2, t_name, "Value")
                    }
                    bm.add_prediction(match_info, opt["pick"], opt["odds"], opt["prob"], stake)
                    count_value += 1
                except Exception as e:
                    print(f"❌ Erreur sauvegarde Value Bet ({opt.get('match')}): {e}")

        # 2. Sauvegarder les Over/Under
        if hasattr(self, 'last_ou_suggestions'):
            for ou in self.last_ou_suggestions:
                try:
                    parts = [p.strip() for p in ou["match"].split(" vs ")]
                    if len(parts) != 2: continue
                    p1, p2 = parts
                    
                    t_name = ou.get("tournament", tour_name)
                    match_info = {
                        "player_1": p1, "player_2": p2,
                        "tournament": t_name,
                        "match_id": bm.get_prediction_id(p1, p2, t_name, "OU")
                    }
                    # Utilisation de la cote réelle si disponible, sinon défaut 1.80
                    odds = ou.get("odds", 1.80)
                    bm.add_prediction(match_info, ou["pick"], odds, ou["prob"], stake)
                    count_ou += 1
                except Exception as e:
                    print(f"❌ Erreur sauvegarde OU ({ou.get('match')}): {e}")
        
        total = count_value + count_ou
        if total > 0:
            self.save_all_btn.configure(text=f"✅ {total} Sauvés", state="disabled")
            self.refresh_bilan()
            from tkinter import messagebox
            messagebox.showinfo("Bilan", f"Enregistré au bilan :\n- {count_value} Value Bets\n- {count_ou} Over/Under\n\n(Total: {total} pronostics)")
            self.after(3000, lambda: self.save_all_btn.pack_forget())
        else:
            from tkinter import messagebox
            messagebox.showwarning("Bilan", "Aucun pari n'a pu être enregistré. Vérifiez les noms des joueurs.")

    def setup_manual_bet_ui(self, parent):
        """Formulaire pour ajouter un pari manuellement."""
        self.manual_frame = ctk.CTkFrame(parent, fg_color=("gray90", "gray15"), corner_radius=10)
        self.manual_frame.grid(row=2, column=0, padx=20, pady=10, sticky="ew")
        
        title = ctk.CTkLabel(self.manual_frame, text="➕ Ajouter un pari manuellement", font=ctk.CTkFont(size=14, weight="bold"), text_color="#3498db")
        title.grid(row=0, column=0, columnspan=2, pady=(10, 5), padx=10, sticky="w")
        
        self.combined_legs_label = ctk.CTkLabel(self.manual_frame, text="", font=ctk.CTkFont(size=12, slant="italic"), text_color="#f39c12")
        self.combined_legs_label.grid(row=0, column=2, columnspan=4, pady=(10, 5), padx=10, sticky="e")

        # Ligne 1: Tournoi et Match
        ctk.CTkLabel(self.manual_frame, text="Tournoi").grid(row=1, column=0, padx=10, pady=2, sticky="w")
        self.m_tourney = ctk.CTkEntry(self.manual_frame, placeholder_text="ex: Rome Masters", width=150)
        self.m_tourney.grid(row=2, column=0, padx=10, pady=(0, 10))

        ctk.CTkLabel(self.manual_frame, text="Match (P1 vs P2)").grid(row=1, column=1, padx=10, pady=2, sticky="w")
        self.m_match = ctk.CTkEntry(self.manual_frame, placeholder_text="ex: Djokovic vs Alcaraz", width=200)
        self.m_match.grid(row=2, column=1, padx=10, pady=(0, 10))

        # Ligne 2: Type, Pick, Cote, Mise
        ctk.CTkLabel(self.manual_frame, text="Type").grid(row=3, column=0, padx=10, pady=2, sticky="w")
        self.m_type = ctk.CTkSegmentedButton(self.manual_frame, values=["H2H", "O/U"], command=self._update_manual_pick_options)
        self.m_type.set("H2H")
        self.m_type.grid(row=4, column=0, padx=10, pady=(0, 10))

        self.m_pick_label = ctk.CTkLabel(self.manual_frame, text="Pronostic")
        self.m_pick_label.grid(row=3, column=1, padx=10, pady=2, sticky="w")
        
        # Le pick combo change selon le type
        self.m_pick_combo = ctk.CTkComboBox(self.manual_frame, values=["Joueur 1", "Joueur 2"], width=150)
        self.m_pick_combo.grid(row=4, column=1, padx=10, pady=(0, 10))
        
        self.m_value_label = ctk.CTkLabel(self.manual_frame, text="Valeur (ex: 22.5)")
        self.m_value_entry = ctk.CTkEntry(self.manual_frame, width=100)
        # On les cache par défaut car H2H est sélectionné
        
        ctk.CTkLabel(self.manual_frame, text="Cote").grid(row=3, column=2, padx=10, pady=2, sticky="w")
        self.m_odds = ctk.CTkEntry(self.manual_frame, width=80)
        self.m_odds.insert(0, "1.80")
        self.m_odds.grid(row=4, column=2, padx=10, pady=(0, 10))

        ctk.CTkLabel(self.manual_frame, text="Mise (€)").grid(row=3, column=3, padx=10, pady=2, sticky="w")
        self.m_stake = ctk.CTkEntry(self.manual_frame, width=80)
        self.m_stake.insert(0, "10")
        self.m_stake.grid(row=4, column=3, padx=10, pady=(0, 10))

        ctk.CTkLabel(self.manual_frame, text="Statut").grid(row=3, column=4, padx=10, pady=2, sticky="w")
        self.m_status = ctk.CTkComboBox(self.manual_frame, values=["pending", "won", "lost"], width=100)
        self.m_status.set("pending")
        self.m_status.grid(row=4, column=4, padx=10, pady=(0, 10))

        self.m_save_btn = ctk.CTkButton(self.manual_frame, text="💾 Enregistrer", fg_color="#27ae60", hover_color="#2ecc71", width=120, command=self.on_add_manual_bet)
        self.m_save_btn.grid(row=4, column=5, padx=10, pady=(0, 10))

        self.m_combine_btn = ctk.CTkButton(self.manual_frame, text="🔗 Combiner", fg_color="#8e44ad", hover_color="#9b59b6", width=120, command=self.on_add_combined_leg)
        self.m_combine_btn.grid(row=4, column=6, padx=10, pady=(0, 10))

    def _update_manual_pick_options(self, bet_type):
        """Met à jour les options de pronostic selon le type choisi."""
        if bet_type == "H2H":
            self.m_pick_combo.configure(values=["Joueur 1", "Joueur 2"])
            self.m_pick_combo.set("Joueur 1")
            self.m_value_label.grid_forget()
            self.m_value_entry.grid_forget()
        else:
            self.m_pick_combo.configure(values=["Over", "Under"])
            self.m_pick_combo.set("Over")
            self.m_value_label.grid(row=3, column=5, padx=10, pady=2, sticky="w")
            self.m_value_entry.grid(row=4, column=5, padx=10, pady=(0, 10))
            # On décale les boutons
            self.m_save_btn.grid(row=4, column=7, padx=10, pady=(0, 10))
            self.m_combine_btn.grid(row=4, column=8, padx=10, pady=(0, 10))

    def on_add_combined_leg(self):
        """Ajoute une 'jambe' au pari combiné actuel."""
        tourney = self.m_tourney.get().strip()
        match = self.m_match.get().strip()
        bet_type = self.m_type.get()
        pick_side = self.m_pick_combo.get()
        
        try:
            odds = float(self.m_odds.get())
        except:
            from tkinter import messagebox
            messagebox.showerror("Erreur", "Veuillez entrer une cote valide.")
            return

        if not match:
            from tkinter import messagebox
            messagebox.showerror("Erreur", "Veuillez entrer le nom du match.")
            return

        final_pick = pick_side
        if bet_type == "O/U":
            val = self.m_value_entry.get().strip()
            if not val:
                from tkinter import messagebox
                messagebox.showerror("Erreur", "Valeur O/U manquante.")
                return
            final_pick = f"{pick_side} {val}"

        leg = {
            "match": match,
            "pick": final_pick,
            "odds": odds,
            "tourney": tourney
        }
        self.manual_combined_legs.append(leg)
        
        # Mise à jour du label et calcul de la cote totale
        total_odds = 1.0
        for l in self.manual_combined_legs:
            total_odds *= l["odds"]
        
        legs_txt = " + ".join([f"{l['match']} ({l['pick']})" for l in self.manual_combined_legs])
        self.combined_legs_label.configure(text=f"Combiné ({len(self.manual_combined_legs)} legs): {legs_txt} | Cote: {total_odds:.2f}")
        
        # Reset les champs pour la jambe suivante (sauf tournoi si identique)
        self.m_match.delete(0, "end")
        self.m_odds.delete(0, "end")
        self.m_odds.insert(0, "1.80")
        
        # On met à jour la cote totale dans le champ cote par confort
        self.m_odds.delete(0, "end")
        self.m_odds.insert(0, f"{total_odds:.2f}")

    def on_add_manual_bet(self):
        """Enregistre un pari manuel dans le fichier JSON."""
        tourney = self.m_tourney.get().strip()
        match = self.m_match.get().strip()
        bet_type = self.m_type.get()
        pick_side = self.m_pick_combo.get()
        
        try:
            odds = float(self.m_odds.get())
            stake = float(self.m_stake.get())
        except:
            from tkinter import messagebox
            messagebox.showerror("Erreur", "Veuillez entrer une cote et une mise valides.")
            return

        if not tourney or not match:
            from tkinter import messagebox
            messagebox.showerror("Erreur", "Veuillez entrer le nom du tournoi et du match.")
            return

        # Construire le pick final et la cote totale
        if self.manual_combined_legs:
            # Calcul de la cote cumulée des jambes déjà enregistrées
            total_legs_odds = 1.0
            for l in self.manual_combined_legs:
                total_legs_odds *= l["odds"]
            
            # Si le formulaire contient un match non encore combiné, on l'ajoute au calcul final
            current_match_in_form = match and match not in [l["match"] for l in self.manual_combined_legs]
            
            if current_match_in_form:
                # On multiplie la cote du formulaire par la cote des jambes précédentes
                odds = total_legs_odds * odds
                final_match = " & ".join([l["match"] for l in self.manual_combined_legs] + [match])
                
                # Pick descriptif
                form_pick = f"{pick_side} {self.m_value_entry.get().strip()}" if bet_type == "O/U" else pick_side
                final_pick = " / ".join([f"{l['match']}:{l['pick']}" for l in self.manual_combined_legs] + [f"{match}:{form_pick}"])
            else:
                # On utilise juste la cote des jambes (le formulaire est vide ou déjà inclus)
                odds = total_legs_odds
                final_match = " & ".join([l["match"] for l in self.manual_combined_legs])
                final_pick = " / ".join([f"{l['match']}:{l['pick']}" for l in self.manual_combined_legs])
        elif bet_type == "O/U":
            val = self.m_value_entry.get().strip()
            if not val:
                from tkinter import messagebox
                messagebox.showerror("Erreur", "Veuillez entrer une valeur pour l'Over/Under (ex: 22.5).")
                return
            final_pick = f"{pick_side} {val}"
        else:
            final_pick = pick_side

        # Préparer l'objet pari
        final_match_name = match
        if self.manual_combined_legs:
            all_matches = [l["match"] for l in self.manual_combined_legs]
            if match and match not in all_matches:
                all_matches.append(match)
            final_match_name = " & ".join(all_matches)

        new_bet = {
            "tournament": tourney,
            "match": final_match_name,
            "pick": final_pick,
            "odds": odds,
            "stake": stake,
            "status": self.m_status.get(),
            "profit": 0,
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "manual_override": True if self.m_status.get() != "pending" else False,
            "player_1": "Combined" if self.manual_combined_legs else (match.split("vs")[0].strip() if "vs" in match else match),
            "player_2": "Bet" if self.manual_combined_legs else (match.split("vs")[1].strip() if "vs" in match else "Unknown")
        }

        # ID unique pour la suppression
        safe_match = match.lower().replace(" ", "_").replace("vs", "_").replace(".", "")
        safe_tourney = tourney.lower().replace(" ", "_")
        new_bet["id"] = f"manual_{safe_tourney}_{safe_match}_{datetime.now().strftime('%H%M%S')}"

        import python.betting_manager as bm
        predictions = bm.load_predictions()
        predictions.append(new_bet)
        bm.save_predictions(predictions)

        print(f"✅ Pari manuel enregistré : {match} ({final_pick})")
        from tkinter import messagebox
        messagebox.showinfo("Succès", "Pari manuel enregistré avec succès.")
        
        # Réinitialiser les champs et rafraîchir
        self.m_tourney.delete(0, "end")
        self.m_match.delete(0, "end")
        self.manual_combined_legs = []
        self.combined_legs_label.configure(text="")
        self.refresh_bilan()

    def on_set_status(self, p_id, status):
        """Force manuellement le statut d'un pari."""
        import python.betting_manager as bm
        predictions = bm.load_predictions()
        updated = False
        for p in predictions:
            if p.get("id") == p_id:
                p["status"] = status
                # Calculer le profit
                if status == "won":
                    p["profit"] = (p["stake"] * p["odds"]) - p["stake"]
                elif status == "lost":
                    p["profit"] = -p["stake"]
                else:
                    p["profit"] = 0
                
                # Marquer comme override pour éviter l'écrasement automatique
                p["manual_override"] = True
                updated = True
                break
        
        if updated:
            bm.save_predictions(predictions)
            print(f"✏️ Statut mis à jour pour {p_id} -> {status}")
            self.refresh_bilan()

    def on_apply_default_stake(self):
        """Applique la mise par défaut à tous les paris en cours."""
        try:
            new_stake = float(self.stake_entry.get())
        except:
            return
            
        import python.betting_manager as bm
        predictions = bm.load_predictions()
        count = 0
        for p in predictions:
            if p.get("status") == "pending":
                p["stake"] = new_stake
                count += 1
        
        if count > 0:
            bm.save_predictions(predictions)
            self.refresh_bilan()
            from tkinter import messagebox
            messagebox.showinfo("Bilan", f"Mise de {new_stake}€ appliquée à {count} paris en cours.")

    def on_edit_stake(self, p_id, old_stake):
        """Ouvre un dialogue pour modifier la mise d'un pari spécifique."""
        from tkinter import simpledialog
        new_stake = simpledialog.askfloat("Modifier la mise", f"Entrez la nouvelle mise pour ce pari :", initialvalue=old_stake)
        
        if new_stake is not None:
            import python.betting_manager as bm
            predictions = bm.load_predictions()
            updated = False
            for p in predictions:
                if p.get("id") == p_id:
                    p["stake"] = new_stake
                    # Recalculer le profit si déjà résolu
                    if p["status"] == "won":
                        p["profit"] = (new_stake * p["odds"]) - new_stake
                    elif p["status"] == "lost":
                        p["profit"] = -new_stake
                    updated = True
                    break
            
            if updated:
                bm.save_predictions(predictions)
                self.refresh_bilan()

    def on_delete_prediction(self, p_id):
        print(f"🗑️ Suppression automatique pour l'ID : {p_id}")
        import python.betting_manager as bm
        if bm.delete_prediction(p_id):
            print(f"✅ ID {p_id} supprimé avec succès.")
            self.refresh_bilan()
        else:
            print(f"❌ Échec de la suppression de l'ID {p_id}.")

    def on_save_individual_bet(self):
        from tkinter import messagebox
        if not hasattr(self, 'selected_match') or not self.selected_match:
            messagebox.showwarning("Bilan", "Veuillez d'abord sélectionner ou simuler un match.")
            return
        
        match = self.selected_match
        p1 = match['player_1']
        p2 = match['player_2']
        odds_data = match.get('odds')
        
        # Probs check
        if not hasattr(self, 'last_probs'):
            messagebox.showwarning("Bilan", "Les probabilités ne sont pas encore calculées.")
            return
            
        prob_1, prob_2 = self.last_probs
        pick = p1 if prob_1 >= prob_2 else p2
        prob = prob_1 if prob_1 >= prob_2 else prob_2
        
        # Odds extraction
        odds = 1.0
        if odds_data:
            o_dict = odds_data.get('odds', {})
            odds = o_dict.get(pick, 1.0)
        
        try:
            stake = float(self.stake_entry.get())
        except:
            stake = 10.0
            
        match_info = {
            "player_1": p1,
            "player_2": p2,
            "tournament": match.get('row_data', {}).get('tournament', 'Unknown'),
            "match_id": betting_manager.get_prediction_id(p1, p2, match.get('row_data', {}).get('tournament', 'Unknown'), "Value")
        }
        
        try:
            betting_manager.add_prediction(match_info, pick, odds, prob, stake)
            messagebox.showinfo("Bilan", f"Pari enregistré : {pick} @ {odds}")
            self.save_bilan_btn.configure(text=self._tr("prediction_saved"), state="disabled")
            self.refresh_bilan()
        except Exception as e:
            messagebox.showerror("Bilan", f"Erreur lors de l'enregistrement : {e}")

    def on_match_selected(self, match):
        p1 = match['player_1']
        p2 = match['player_2']
        row = match['row_data']
        
        # Afficher l'overlay global en plus du message dans la textbox AI
        self.show_loading_overlay(f"⏳ Analyse approfondie de {p1} vs {p2}")

        # Show loading status in AI textbox with estimated time
        self.ai_textbox.configure(state="normal")
        self.ai_textbox.delete("0.0", "end")
        self.ai_textbox.insert("0.0", f"🔄 Synchronisation TennisExplorer (3 ans) pour {p1} et {p2}...\n")
        self.ai_textbox.insert("end", "⏳ Temps estimé : ~10-15 secondes...\n")
        self.ai_textbox.configure(state="disabled")
        
        # Run enrichment in background before doing anything else
        threading.Thread(target=self.run_auto_enrichment_thread, args=(p1, p2, match), daemon=True).start()

    def run_auto_enrichment_thread(self, p1, p2, match):
        from python.data.tennisexplorer_scraper import scrape_player_te_history, scrape_player_rapidapi_history, merge_te_to_base_socle
        from python.data.rapidapi_client import client
        from python.data.te_cache import load_te_cache, save_te_cache
        
        rapidapi_id1 = client.get_player_id_by_name(p1)
        rapidapi_id2 = client.get_player_id_by_name(p2)

        # Vérifier le cache partagé en premier (données récentes du bulletin)
        te_p1_data = load_te_cache(p1)
        if te_p1_data:
            print(f"[Cache] Données récentes utilisées pour {p1} (evite re-scrape)")
        elif rapidapi_id1:
            print(f"Utilisation de RapidAPI pour {p1} (ID: {rapidapi_id1})")
            te_p1_data = scrape_player_rapidapi_history(p1, rapidapi_id1)
            save_te_cache(p1, te_p1_data)
        else:
            print(f"RapidAPI ID introuvable pour {p1}, fallback TennisExplorer")
            te_p1_data = scrape_player_te_history(p1, nb_years=3)
            save_te_cache(p1, te_p1_data)

        te_p2_data = load_te_cache(p2)
        if te_p2_data:
            print(f"[Cache] Données récentes utilisées pour {p2} (evite re-scrape)")
        elif rapidapi_id2:
            print(f"Utilisation de RapidAPI pour {p2} (ID: {rapidapi_id2})")
            te_p2_data = scrape_player_rapidapi_history(p2, rapidapi_id2)
            save_te_cache(p2, te_p2_data)
        else:
            print(f"RapidAPI ID introuvable pour {p2}, fallback TennisExplorer")
            te_p2_data = scrape_player_te_history(p2, nb_years=3)
            save_te_cache(p2, te_p2_data)
        
        needs_reload = False
        p1_obj = find_player_by_name(p1, self.players_db)
        p2_obj = find_player_by_name(p2, self.players_db)
        
        if p1_obj:
            print(f"📊 Mise à jour DNA Live pour {p1}...")
            p1_obj.update_with_live_charting()
        if p2_obj:
            print(f"📊 Mise à jour DNA Live pour {p2}...")
            p2_obj.update_with_live_charting()
            
        # TennisExplorer Sync
        if p1_obj and merge_te_to_base_socle(p1_obj, te_p1_data, self.players_db, tour=self.current_tour):
            needs_reload = True
        if p2_obj and merge_te_to_base_socle(p2_obj, te_p2_data, self.players_db, tour=self.current_tour):
            needs_reload = True
            
        # Ingestion en mémoire des données fraîches scrapées (TennisExplorer / RapidAPI)
        if p1_obj and te_p1_data:
            added_p1 = p1_obj.inject_scraped_history(te_p1_data)
            if added_p1 > 0:
                print(f"📥 {added_p1} match(s) injecté(s) en mémoire pour {p1_obj.name}.")
        if p2_obj and te_p2_data:
            added_p2 = p2_obj.inject_scraped_history(te_p2_data)
            if added_p2 > 0:
                print(f"📥 {added_p2} match(s) injecté(s) en mémoire pour {p2_obj.name}.")

        if needs_reload:
            # merge_te_to_base_socle a déjà mis à jour p1_obj et p2_obj directement en mémoire
            # dans self.players_db. Inutile de tout relire depuis le CSV (5000+ matchs).
            # Les données fraîches sont déjà disponibles pour la prédiction.
            print(f"✅ Données de {p1} et {p2} mises à jour en mémoire (sans rechargement CSV).")
            
        self.after(0, lambda: self.finish_auto_enrichment(match, te_p1_data, te_p2_data))

    def finish_auto_enrichment(self, match, te_p1, te_p2):
        self.process_match_selection(match, te_p1, te_p2)

    def process_match_selection(self, match, te_p1=None, te_p2=None):
        self.selected_match = match # Store for AI callback
        p1 = match['player_1']
        p2 = match['player_2']
        row = match['row_data']
        odds = match.get('odds')

        # Display Odds
        if odds:
            o_dict = odds.get('odds', {})
            odds_text = f"{self._tr('odds')} {p1}: {o_dict.get(p1, 'N/A')} | {p2}: {o_dict.get(p2, 'N/A')} ({odds.get('bookmaker')})"
            self.odds_label.configure(text=odds_text)
        else:
            self.odds_label.configure(text="")

        surface_en = str(row.get('tournament_surface', 'N/A')).capitalize()
        surface_fr = {"Hard": self._tr("hard"), "Clay": self._tr('clay'), "Grass": self._tr("grass")}.get(surface_en, surface_en)
        
        level_desc = {"G": self._tr("gs"), "M": self._tr("m1000"), "A": self._tr("atp500"), "D": self._tr("davis")}.get(row.get('tournament_level'), row.get('tournament_level', 'N/A'))
        
        orig_round = str(row.get('round', 'N/A')).upper()
        round_fr = self._tr(f"round_{orig_round}")
        if round_fr.startswith("round_"): # If not translated
            round_fr = {
                "F": self._tr("round_F"), "FINAL": self._tr("round_F"), "FINALE": self._tr("round_F"),
                "SF": self._tr("round_SF"), "DF": self._tr("round_SF"), "DEMI": self._tr("round_SF"),
                "QF": self._tr("round_QF"), "QUART": self._tr("round_QF"),
                "R16": self._tr("round_R16"), "HUIT": self._tr("round_R16"), "1/8": self._tr("round_R16"),
                "R32": self._tr("round_R32"), "1/16": self._tr("round_R32"), "SEIZE": self._tr("round_R32"),
                "R64": self._tr("round_R64"), "1/32": self._tr("round_R64"), "TRENTE": self._tr("round_R64"),
                "R128": self._tr("round_R128"), "1/64": self._tr("round_R128"), "SOIXANTE": self._tr("round_R128"),
                "RR": self._tr("round_RR")
            }.get(orig_round, orig_round)
        
        best_of = row.get('best_of', '3')
        score = row.get('score', 'Upcoming')
        
        info_text = f"🏟️ {row['tournament']} ({level_desc})\n"
        info_text += f"📅 {round_fr} | 🧱 {self._tr('surface')}: {surface_fr} | 🎾 {self._tr('best_of').format(best_of)}"
        
        if match.get('full_time'):
            info_text += f"\n⏰ {match['full_time']}"
            
        self.match_info_label.configure(text=info_text)

        # Winner & Score Display
        winner_idx = row.get('Winner')
        if score and score != "Upcoming" and winner_idx is not None:
            self.score_label.configure(text=f"{self._tr('score')}{score}", text_color="#00FF00") # Fluorescent green
            
            if winner_idx == 0:
                self.p1_name.configure(text=f"🟢 {p1}", text_color="#2ecc71")
                self.p2_name.configure(text=p2, text_color="#3498db")
            else:
                self.p1_name.configure(text=p1, text_color="#3498db")
                self.p2_name.configure(text=f"🟢 {p2}", text_color="#2ecc71")
        else:
            self.score_label.configure(text="")
            self.p1_name.configure(text=p1, text_color="#3498db")
            self.p2_name.configure(text=p2, text_color="#3498db")

        # Use centralized robust matching from app_logic
        p1_obj = find_player_by_name(p1, self.players_db)
        p2_obj = find_player_by_name(p2, self.players_db)

        # Rankings display with fallback to player object
        r1 = row.get('Ranking_1')
        if (r1 is None or r1 == 0 or r1 == 999 or r1 >= 9999) and p1_obj:
            r1 = p1_obj.ranking
            if (r1 is None or r1 == 0 or r1 == 999 or r1 >= 9999):
                r1 = p1_obj.get_latest_valid_ranking()
        # Fetch Endurance for display
        endurance_1 = row.get("endurance_win_percentage_1", getattr(p1_obj, 'endurance_win_percentage', 50.0) if p1_obj else 50.0)
        # Display fallback: show N/A only for actual placeholders (0, 999, 9999+)
        r1_disp = r1 if r1 and r1 != 999 and r1 < 9999 else 'N/A'
        self.p1_rank.configure(text=f"{self._tr('ranking')}{r1_disp} | Endur: {endurance_1:.0f}%")
        
        r2 = row.get('Ranking_2')
        if (r2 is None or r2 == 0 or r2 == 999 or r2 >= 9999) and p2_obj:
            r2 = p2_obj.ranking
            if (r2 is None or r2 == 0 or r2 == 999 or r2 >= 9999):
                r2 = p2_obj.get_latest_valid_ranking()
        endurance_2 = row.get("endurance_win_percentage_2", getattr(p2_obj, 'endurance_win_percentage', 50.0) if p2_obj else 50.0)
        r2_disp = r2 if r2 and r2 != 999 and r2 < 9999 else 'N/A'
        self.p2_rank.configure(text=f"{self._tr('ranking')}{r2_disp} | Endur: {endurance_2:.0f}%")

        # Vérifier si on a assez de stats pour prédire
        # Seulement masquer si le joueur est totalement inconnu (absent de la DB)
        player_unknown = not p1_obj or not p2_obj
        limited_data_warning = False  # Avertissement si stats limitées mais prediction quand même

        if not player_unknown:
            for p_obj in [p1_obj, p2_obj]:
                num_matches = len(getattr(p_obj, 'matches_history', []))
                if num_matches < 5:
                    limited_data_warning = True
                    break

        # Injection des stats d'aces pour l'affichage (utilisé par display_betting_stats)
        if p1_obj: row['Aces_Percentage_1'] = getattr(p1_obj, 'aces_percentage', 0.0)
        if p2_obj: row['Aces_Percentage_2'] = getattr(p2_obj, 'aces_percentage', 0.0)

        # Recherche intelligente du nom du tournoi (corriger "Men's Singles" issu de LiveScore)
        t_name = match.get('tournament', '')
        if not t_name: t_name = row.get('tournament', '')
        
        if not t_name or "men's singles" in t_name.lower() or "women's singles" in t_name.lower() or "custom match" in t_name.lower():
            p1_norm = str(p1).lower().replace(' ', '')
            p2_norm = str(p2).lower().replace(' ', '')
            for idx, r in self.data_df.iterrows():
                df_p1 = str(r.get('player_1_name', '')).lower().replace(' ', '')
                df_p2 = str(r.get('player_2_name', '')).lower().replace(' ', '')
                if (p1_norm in df_p1 and p2_norm in df_p2) or (p1_norm in df_p2 and p2_norm in df_p1):
                    real_t = str(r.get('tournament', ''))
                    if real_t and "men's singles" not in real_t.lower() and "women's singles" not in real_t.lower():
                        t_name = real_t
                        break

        # Prediction
        prob_1, prob_2, enrich_1, enrich_2, conf_score = predict_match_outcome(
            self.model, row, self.used_features, 
            players_db=self.players_db, 
            p1_name=p1, 
            p2_name=p2, 
            tournament_name=t_name,
            te_p1=te_p1,
            te_p2=te_p2,
            skip_te_scrape=True
        )
        
        self.last_probs = (prob_1, prob_2)
        
        # Enable save button if we have odds and match is upcoming
        is_upcoming = (str(row.get('score')) == "Upcoming")
        if odds and is_upcoming:
            self.save_bilan_btn.pack(side="left", padx=5)
            self.save_bilan_btn.configure(state="normal", text=self._tr("save_to_bilan"))
            self.save_all_btn.pack_forget() # Hide tournament save when selecting individual match
        else:
            self.save_bilan_btn.pack_forget()
        
        # Determine confidence label
        if conf_score > 0.8:
            conf_label = self._tr("confidence_high")
            conf_color = "#2ecc71"
        elif conf_score > 0.4:
            conf_label = self._tr("confidence_medium")
            conf_color = "#f1c40f"
        else:
            conf_label = self._tr("confidence_low")
            conf_color = "#e67e22"

        insufficient_data = player_unknown or conf_score < 0.15  # Seulement si joueur inconnu ou score ultra-bas

        if insufficient_data:
            self.p1_prob_label.configure(text=f"{self._tr('insufficient_stats').format(p1)} ({conf_label})", text_color="orange")
            self.p2_prob_label.configure(text=f"{self._tr('insufficient_stats').format(p2)} ({conf_label})", text_color="orange")
        else:
            # Add Salmon / Elite / Warning Badges
            badge_1 = ""
            if limited_data_warning: badge_1 += " ⚠️ Stats limitées"
            if enrich_1.get("is_salmon"): badge_1 += " 🐟 Saumon"
            if enrich_1.get("moral_victory") or enrich_1.get("win_top20"): badge_1 += " 💪 Impact Top 20"
            if enrich_1.get("top20_endurance_boost"): badge_1 += " ⚡ Endurance"
            if enrich_1.get("home_crowd"): badge_1 += " 🏟️ Domicile"
            if enrich_1.get("collapse_risk"): badge_1 += " 🚨 Effondrement"
            
            badge_2 = ""
            if limited_data_warning: badge_2 += " ⚠️ Stats limitées"
            if enrich_2.get("is_salmon"): badge_2 += " 🐟 Saumon"
            if enrich_2.get("moral_victory") or enrich_2.get("win_top20"): badge_2 += " 💪 Impact Top 20"
            if enrich_2.get("top20_endurance_boost"): badge_2 += " ⚡ Endurance"
            if enrich_2.get("home_crowd"): badge_2 += " 🏟️ Domicile"
            if enrich_2.get("collapse_risk"): badge_2 += " 🚨 Effondrement"
            
            self.p1_prob_label.configure(text=f"{self._tr('prob_win')} {p1} : {prob_1*100:.1f}%{badge_1} ({conf_label})", text_color="green")
            self.p2_prob_label.configure(text=f"{self._tr('prob_win')} {p2} : {prob_2*100:.1f}%{badge_2} ({conf_label})", text_color="orange")
        
            # Highlight winning prediction if match played
            if winner_idx is not None and str(row.get('score')) != "Upcoming":
                if winner_idx == 0:
                    self.p1_prob_label.configure(text=f"✅ {self._tr('prob_win')} {p1} : {prob_1*100:.1f}%", text_color="#00FF00")
                    self.p2_prob_label.configure(text_color="orange")
                else:
                    self.p1_prob_label.configure(text_color="green")
                    self.p2_prob_label.configure(text=f"✅ {self._tr('prob_win')} {p2} : {prob_2*100:.1f}%", text_color="#00FF00")
            else:
                self.p1_prob_label.configure(text_color="green")
                self.p2_prob_label.configure(text_color="orange")
        self.betting_textbox.delete("0.0", "end")
        self.betting_textbox.insert("0.0", self._tr("calc_bet"))
        self.betting_textbox.configure(state="disabled")
        
        surface = row.get('tournament_surface', None)
        # On utilise after pour ne pas bloquer l'UI même si c'est rapide
        self.after(100, lambda: self.display_betting_stats(p1, p2, prob_1, prob_2, surface, row, enrich_1, enrich_2))
        
        # Reset AI text
        self.ai_textbox.configure(state="normal")
        self.ai_textbox.delete("0.0", "end")
        self.ai_textbox.insert("0.0", self._tr("ai_prep"))
        self.ai_textbox.configure(state="disabled")
        
        # Rebind AI button
        self.ai_btn.configure(command=lambda: self.trigger_ai_advice(row, prob_1, prob_2, p1, p2, enrich_1, enrich_2))

        # Enable View Odds button and store match data
        self.view_odds_btn.configure(state="normal")
        self.current_match_for_odds = match

    def trigger_ai_advice(self, row, prob_1, prob_2, p1, p2, enrich_1=None, enrich_2=None):
        self.ai_btn.configure(state="disabled", text=self._tr("ai_analyzing"))
        self.ai_textbox.configure(state="normal")
        self.ai_textbox.delete("0.0", "end")
        self.ai_textbox.insert("0.0", self._tr("ai_working"))
        self.ai_textbox.configure(state="disabled")
        
        # Run in thread
        threading.Thread(target=self.run_ai_thread, args=(row, prob_1, prob_2, p1, p2, enrich_1, enrich_2), daemon=True).start()

    def run_ai_thread(self, row, prob_1, prob_2, p1, p2, enrich_1, enrich_2):
        advice = get_mistral_betting_advice(match_row=row, prob_1=prob_1, prob_2=prob_2, p1_name=p1, p2_name=p2, enrichment_p1=enrich_1, enrichment_p2=enrich_2, lang=self.current_lang)
        # Update UI back
        self.after(0, lambda: self.update_ai_ui(advice))
        
    def update_ai_ui(self, advice):
        # Nettoyage des blocs de code Markdown (triple backticks)
        advice = advice.strip()
        if advice.startswith("```"):
            # Supprimer la première ligne (ex: ```markdown ou ```python)
            advice = re.sub(r'^```[\w]*\n', '', advice)
            # Supprimer les backticks de fin
            advice = re.sub(r'\n```$', '', advice)
            advice = advice.strip("`").strip()
            
        # Nettoyage du format Markdown (le Textbox ne le supporte pas)
        clean_advice = advice.replace("**", "")
        # Nettoyer aussi les puces Markdown
        clean_advice = clean_advice.replace("*  ", "• ").replace("* ", "• ")
        
        self.ai_textbox.configure(state="normal")
        self.ai_textbox.delete("0.0", "end")
        self.ai_textbox.insert("0.0", clean_advice)
        self.ai_textbox.configure(state="disabled")
        self.ai_btn.configure(state="normal", text=self._tr("ai_btn"))

    def on_simulate_click(self):
        """Simulation d'un match : calcul en thread pour éviter le freeze de l'UI."""
        p1_name = self.sim_p1_combo.get()
        p2_name = self.sim_p2_combo.get()
        tourney_name = self.sim_tourney_combo.get()
        surface_label = self.sim_surface_combo.get()
        level_label = self.sim_level_combo.get()
        
        if p1_name == p2_name:
            self.match_info_label.configure(text=self._tr("same_player"))
            return
            
        self.show_loading_overlay(f"⏳ Simulation : {p1_name} vs {p2_name}")
        
        def _run_simulation():
            try:
                # Mapping labels
                level_map = {self._tr("gs"): "G", self._tr("m1000"): "M", self._tr("atp500"): "A", self._tr("davis"): "D"}
                level = level_map.get(level_label, "A")
                surface_map = {self._tr("hard"): "Hard", self._tr("clay"): "Clay", self._tr("grass"): "Grass"}
                surface = surface_map.get(surface_label, "Hard")
                
                p1_obj = next((p for p in self.players_db.values() if p.name == p1_name), None)
                p2_obj = next((p for p in self.players_db.values() if p.name == p2_name), None)
                
                if not p1_obj or not p2_obj:
                    self.after(0, lambda: [self.match_info_label.configure(text=self._tr("error_p_not_found")), self.hide_loading_overlay()])
                    return
                
                # Heavy work
                row = create_custom_match_row(p1_obj, p2_obj, surface, level)
                row["tournament"] = tourney_name
                
                prob_1, prob_2, enrich_1, enrich_2, conf_score = predict_match_outcome(
                    self.model, row, self.used_features,
                    players_db=self.players_db, p1_name=p1_name, p2_name=p2_name, tournament_name=tourney_name,
                    skip_te_scrape=True, te_p1=getattr(p1_obj, 'latest_te_data', None), te_p2=getattr(p2_obj, 'latest_te_data', None)
                )
                
                # Update UI on main thread
                self.after(0, lambda: self._update_sim_results_ui(p1_name, p2_name, tourney_name, level_label, surface_label, surface, row, prob_1, prob_2, enrich_1, enrich_2, p1_obj, p2_obj, conf_score))
            except Exception as e:
                self.after(0, lambda err=str(e): [self.match_info_label.configure(text=f"{self._tr('err_sim')}{err}"), self.hide_loading_overlay()])

        threading.Thread(target=_run_simulation, daemon=True).start()

    def _update_sim_results_ui(self, p1_name, p2_name, tourney_name, level_label, surface_label, surface, row, prob_1, prob_2, enrich_1, enrich_2, p1_obj, p2_obj, conf_score):
        """Met à jour l'interface avec les résultats de la simulation."""
        self.last_probs = (prob_1, prob_2)
        # Injection des stats d'aces pour l'affichage
        if p1_obj: row['Aces_Percentage_1'] = getattr(p1_obj, 'aces_percentage', 0.0)
        if p2_obj: row['Aces_Percentage_2'] = getattr(p2_obj, 'aces_percentage', 0.0)
        
        # On crée un faux match_info pour le bouton de sauvegarde
        self.selected_match = {
            'player_1': p1_name,
            'player_2': p2_name,
            'row_data': row or {'tournament': tourney_name, 'score': 'Upcoming'},
            'odds': None # Pas de cotes en simulation libre pour l'instant
        }
        self.save_bilan_btn.pack(side="left", padx=5)
        self.save_bilan_btn.configure(state="normal", text=self._tr("save_to_bilan"))

        self.odds_label.configure(text="") # Clear previous odds
        info_text = f"🏟️ {tourney_name} ({level_label})\n"
        info_text += f"📅 {self._tr('simulation')} | 🧱 {self._tr('surface')}: {surface_label} | 🎾 {self._tr('best_of').format(3)}"
        self.match_info_label.configure(text=info_text)
        
        self.score_label.configure(text="")
        self.p1_name.configure(text=p1_name, text_color="#3498db")
        self.p2_name.configure(text=p2_name, text_color="#3498db")
        endur_1 = getattr(p1_obj, 'endurance_win_percentage', 50.0) if p1_obj else 50.0
        endur_2 = getattr(p2_obj, 'endurance_win_percentage', 50.0) if p2_obj else 50.0
        self.p1_rank.configure(text=f"{self._tr('current_ranking')}{p1_obj.ranking if p1_obj else 'N/A'} | Endur: {endur_1:.0f}%")
        self.p2_rank.configure(text=f"{self._tr('current_ranking')}{p2_obj.ranking if p2_obj else 'N/A'} | Endur: {endur_2:.0f}%")
        
        def check_limited(p_obj):
            if not p_obj: return True
            num_matches = len(getattr(p_obj, 'matches_history', []))
            return num_matches < 5

        player_unknown = not p1_obj or not p2_obj
        limited_data_warning = check_limited(p1_obj) or check_limited(p2_obj)
        insufficient_data = player_unknown or conf_score < 0.15
            
        # Determine confidence label
        if conf_score > 0.8:
            conf_label = self._tr("confidence_high")
        elif conf_score > 0.4:
            conf_label = self._tr("confidence_medium")
        else:
            conf_label = self._tr("confidence_low")

        if insufficient_data:
            self.p1_prob_label.configure(text=f"{self._tr('insufficient_stats').format(p1_name)} ({conf_label})", text_color="orange")
            self.p2_prob_label.configure(text=f"{self._tr('insufficient_stats').format(p2_name)} ({conf_label})", text_color="orange")
        else:
            badge_1 = ((" ⚠️ Stats limitées") if limited_data_warning else "") + (" 🐟 Saumon" if enrich_1.get("is_salmon") else "") + (" 💪 Impact Top 20" if enrich_1.get("moral_victory") or enrich_1.get("win_top20") else "") + (" ⚡ Endurance" if enrich_1.get("top20_endurance_boost") else "") + (" 🏟️ Domicile" if enrich_1.get("home_crowd") else "") + (" 🚨 Effondrement" if enrich_1.get("collapse_risk") else "")
            badge_2 = ((" ⚠️ Stats limitées") if limited_data_warning else "") + (" 🐟 Saumon" if enrich_2.get("is_salmon") else "") + (" 💪 Impact Top 20" if enrich_2.get("moral_victory") or enrich_2.get("win_top20") else "") + (" ⚡ Endurance" if enrich_2.get("top20_endurance_boost") else "") + (" 🏟️ Domicile" if enrich_2.get("home_crowd") else "") + (" 🚨 Effondrement" if enrich_2.get("collapse_risk") else "")
            self.p1_prob_label.configure(text=f"{self._tr('prob_win')} {p1_name} : {prob_1*100:.1f}%{badge_1} ({conf_label})", text_color="green")
            self.p2_prob_label.configure(text=f"{self._tr('prob_win')} {p2_name} : {prob_2*100:.1f}%{badge_2} ({conf_label})", text_color="orange")
        
        self.betting_textbox.configure(state="normal")
        self.betting_textbox.delete("0.0", "end")
        self.betting_textbox.insert("0.0", self._tr("calc_bet"))
        self.betting_textbox.configure(state="disabled")
        
        self.ai_textbox.configure(state="normal")
        self.ai_textbox.delete("0.0", "end")
        self.ai_textbox.insert("0.0", self._tr("ai_prep"))
        self.ai_textbox.configure(state="disabled")
        self.ai_btn.configure(command=lambda: self.trigger_ai_advice(row, prob_1, prob_2, p1_name, p2_name, enrich_1, enrich_2))

        # Appel final pour les stats de paris (cache/hide overlay à l'intérieur)
        self.display_betting_stats(p1_name, p2_name, prob_1, prob_2, surface, row, enrich_1, enrich_2)

    def display_betting_stats(self, p1_name, p2_name, prob_1, prob_2, surface=None, row=None, enrich_1=None, enrich_2=None):
        """Affiche les statistiques de paris dans le panneau dédié."""
        # Récupérer les seuils Over/Under réels disponibles chez les bookmakers (>15.0 pour éviter les paris sur le 1er set)
        real_thresholds = []
        odds_obj = self.selected_match.get('odds') if hasattr(self, 'selected_match') else None
        if odds_obj and odds_obj.get('totals'):
             real_thresholds = sorted(list(set([float(t.get('point')) for t in odds_obj['totals'] if float(t.get('point')) > 15.0])))
        
        # Passer les seuils réels au calcul de stats (ou None pour utiliser les défauts)
        stats = calculate_betting_stats(self.data_df, p1_name, p2_name, prob_1, prob_2, surface, real_thresholds=real_thresholds if real_thresholds else None)
        
        self.betting_textbox.configure(state="normal")
        self.betting_textbox.delete("0.0", "end")
        
        if not stats:
            self.betting_textbox.insert("1.0", self._tr("no_data_bet"))
            self.betting_textbox.configure(state="disabled")
            return
        
        # Parse actual results
        actual_score = str(row.get('score', '')) if row is not None else ""
        is_played = actual_score != "Upcoming" and "-" in actual_score
        actual_games = 0
        actual_sets = 0
        if is_played:
            parts = actual_score.split()
            actual_sets = len(parts)
            for s in parts:
                if "-" in s:
                    try:
                        m = re.search(r'(\d+)-(\d+)', s)
                        if m:
                            actual_games += int(m.group(1)) + int(m.group(2))
                    except: pass

        lines = []
        green_lines = [] # 1-indexed
        
        def add_line(text, highlight=False):
            lines.append(text)
            if highlight:
                green_lines.append(len(lines))

        n = stats.get("num_matches_analyzed", 0)
        avg = stats.get("avg_total_games", 0)
        add_line(self._tr("bet_based").format(n, avg))
        add_line("")
        
        # 1. OVER/UNDER TOTAL JEUX
        avg_games = stats.get("avg_total_games", 0)
        add_line(f"📈 NOMBRE DE JEUX ESTIMÉ : ~{avg_games:.1f} jeux")
        
        best_pick = ""
        best_prob = 0
        is_safe = False
        
        # On itère sur les seuils calculés (qui sont soit les réels soit les défauts)
        thresholds_to_check = real_thresholds if real_thresholds else [21.5, 22.5]
        for t in thresholds_to_check:
            key_over = f"over_{t}"
            if key_over in stats:
                p_over = stats[key_over] * 100
                p_under = 100 - p_over
                
                # On cherche la probabilité la plus élevée
                # Si on trouve une proba >= 70%, elle devient prioritaire
                if p_over > best_prob:
                    best_prob = p_over
                    best_pick = f"Over {t}"
                if p_under > best_prob:
                    best_prob = p_under
                    best_pick = f"Under {t}"
                    
        if best_pick:
            is_safe = best_prob >= 70
            prefix = "🔥 CONSEIL SÉCURISÉ" if is_safe else "⚠️ Conseil (risque élevé)"
            source_txt = "(disponible chez bookmaker)" if real_thresholds else "(estimation théorique)"
            add_line(f"  {prefix} : {best_pick} ({best_prob:.0f}%) {source_txt}", highlight=is_safe)
        
        # 2. SETS
        if "prob_3sets" in stats:
            add_line("")
            p3 = stats['prob_3sets'] * 100
            add_line(f"🎾 PROBABILITÉ 3 SETS : {p3:.0f}%")

        # 3. ACES
        if row is not None:
            add_line("")
            ace_pct_1 = row.get('Aces_Percentage_1', 0)
            ace_pct_2 = row.get('Aces_Percentage_2', 0)
            est_games = stats.get("avg_total_games", 22)
            
            theo_aces_1 = ace_pct_1 * 3 * est_games / 100
            theo_aces_2 = ace_pct_2 * 3 * est_games / 100
            total_aces_est = theo_aces_1 + theo_aces_2
            under_aces_threshold = int(total_aces_est) + 0.5
            
            p1_short = str(row.get('Name_1', p1_name)).split('.')[-1].strip()
            p2_short = str(row.get('Name_2', p2_name)).split('.')[-1].strip()
            
            add_line(f"🎯 CONSEIL ACES : UNDER {under_aces_threshold} (Est. ~{total_aces_est:.1f})")
            add_line(f"  ({p1_short} : ~{theo_aces_1:.1f} | {p2_short} : ~{theo_aces_2:.1f})")

        # 4. QUALITATIF (Très bref)
        if enrich_1 or enrich_2:
            add_line("")
            add_line("🌟 INFOS TENNIS-EXPLORER :")
            if enrich_1 and (enrich_1.get("is_salmon") or enrich_1.get("moral_victory")):
                add_line(f"  {p1_name} : Joueur en pleine montée (Saumon/Impact Top 20)")
            if enrich_2 and (enrich_2.get("is_salmon") or enrich_2.get("moral_victory")):
                add_line(f"  {p2_name} : Joueur en pleine montée (Saumon/Impact Top 20)")
            
        self.betting_textbox.insert("1.0", "\n".join(lines))
        
        # Application des styles
        self.betting_textbox.tag_config("correct_pred", foreground="#00FF00")
        for line_no in green_lines:
            self.betting_textbox.tag_add("correct_pred", f"{line_no}.0", f"{line_no}.end")
            
        self.betting_textbox.configure(state="disabled")
        
        # Masquer l'overlay de chargement à la fin de tout le processus (simulation ou clic match)
        self.hide_loading_overlay()

    def on_ai_click(self):
        """Callback pour le bouton Analyse IA d'un match spécifique."""
        if not hasattr(self, 'selected_match') or not self.selected_match:
            return

        match = self.selected_match
        p1 = match['player_1']
        p2 = match['player_2']
        row = match['row_data']
        odds = match.get('odds')

        self.ai_textbox.configure(state="normal")
        self.ai_textbox.delete("0.0", "end")
        self.ai_textbox.insert("0.0", f"💡 {self._tr('ai_working')}\n")
        self.ai_textbox.configure(state="disabled")

        def run_advice():
            from python.app_logic import predict_match_outcome, get_mistral_betting_advice
            
            # Recalculer les probabilités avec enrichment complet
            prob_1, prob_2, enrich_1, enrich_2, _ = predict_match_outcome(
                self.model, row, self.used_features, self.players_db, p1, p2, 
                row.get('tournament')
            )
            
            advice = get_mistral_betting_advice(
                row, prob_1, prob_2, p1, p2, enrich_1, enrich_2, 
                lang=self.current_lang, odds=odds
            )
            
            def update_ui():
                self.ai_textbox.configure(state="normal")
                self.ai_textbox.delete("0.0", "end")
                self.ai_textbox.insert("0.0", advice)
                self.ai_textbox.configure(state="disabled")
                
            self.after(0, update_ui)

        threading.Thread(target=run_advice, daemon=True).start()

    def _on_header_hard_reset_click(self):
        """Réinitialisation complète via le bouton en haut à droite."""
        from tkinter import messagebox
        if not messagebox.askyesno("Réinitialisation Totale", 
                                  "Voulez-vous vraiment TOUT réinitialiser ?\n\nCela va supprimer les bases de données et les fichiers de matchs (hors dossier 'save') pour tout re-scrapper à zéro.\n\nCette opération est irréversible."):
            return
            
        import os, shutil
        data_dir = "data"
        # On ne touche pas à 'save' comme demandé
        files_to_delete = [
            "scraped_matches.csv", "scraped_matches_wta.csv",
            "scraped_players.csv", "scraped_players_wta.csv",
            "match_schedule.csv", "match_schedule.json",
            "odds_cache.json", "odds_history.csv"
        ]
        
        # Supprimer aussi les .db s'ils existent dans le répertoire courant ou data
        for root_dir in [".", "data"]:
            if os.path.exists(root_dir):
                for f in os.listdir(root_dir):
                    if f.endswith(".db"):
                        try: os.remove(os.path.join(root_dir, f))
                        except: pass
        
        for f in files_to_delete:
            p = os.path.join(data_dir, f)
            if os.path.exists(p):
                try: os.remove(p)
                except: pass
                
        # Relancer tout le chargement avec force_update=True
        threading.Thread(target=self.load_data, args=(True,), daemon=True).start()

    def _filter_sim_combos(self, p_num):
        """Filtre les listes de joueurs dans la simulation."""
        search_text = self.sim_p1_search.get().lower() if p_num == 1 else self.sim_p2_search.get().lower()
        all_names = sorted([p.name for p in self.players_db.values()])
        
        filtered = [n for n in all_names if search_text in n.lower()]
        if not filtered: filtered = ["Aucun résultat"]
        
        if p_num == 1:
            self.sim_p1_combo.configure(values=filtered)
            if len(filtered) == 1: self.sim_p1_combo.set(filtered[0])
        else:
            self.sim_p2_combo.configure(values=filtered)
            if len(filtered) == 1: self.sim_p2_combo.set(filtered[0])

    def export_analysis_pdf(self):
        """Exporte l'analyse actuelle au format PDF."""

        import tkinter.filedialog as filedialog
        import tkinter.messagebox as messagebox
        try:
            import markdown
            from xhtml2pdf import pisa
        except ImportError:
            messagebox.showerror("Export PDF", "Veuillez installer les dépendances : pip install markdown xhtml2pdf")
            return

        # Récupération des données
        match_info = self.match_info_label.cget("text")
        p1_prob = self.p1_prob_label.cget("text")
        p2_prob = self.p2_prob_label.cget("text")
        betting_stats = self.betting_textbox.get("1.0", "end")
        ai_advice = self.ai_textbox.get("1.0", "end")

        if not ai_advice.strip() or ai_advice.strip() in [self._tr("ai_ready"), self._tr("ai_prep")]:
            messagebox.showwarning("Export PDF", "Veuillez d'abord générer une analyse.")
            return

        # Construction du document Markdown
        md_content = f"# {self._tr('analysis_title')}\n\n"
        md_content += f"### {match_info.splitlines()[0] if match_info else 'Match'}\n"
        md_content += f"**Détails :**  \n{match_info.replace(chr(10), '  ' + chr(10))}\n\n"
        
        md_content += f"## {self._tr('pred_title')}\n"
        md_content += f"- {p1_prob}\n"
        md_content += f"- {p2_prob}\n\n"
        
        md_content += f"## {self._tr('bet_stats')}\n"
        md_content += f"```\n{betting_stats}\n```\n\n"
        
        md_content += f"## Conseil IA (Mistral)\n"
        md_content += f"{ai_advice}\n"

        # Remplacement des émojis pour xhtml2pdf (support limité)
        replacements = {
            '✅': '[V]', '❌': '[X]', '🏆': '[WIN]', '📊': '[STATS]', '💡': '[AI]', '🎾': '[TENNIS]',
            '🏟️': '[TOUR]', '📅': '[DATE]', '🧱': '[SURF]', '⏰': '[TIME]', '👤': '[P]',
            '🐟': '[SALMON]', '💪': '[TOP20]', '🔴': '[LIVE]', '🟡': '[WARN]', '🎯': '[GOAL]',
            '•': '-', '⭐': '[*]', '🟢': '[O]', '⚡': '[!]', '🕒': '[TIME]', '⏳': '[WAIT]',
            '🔥': '[HOT]', '👍': '[OK]', '📈': '[UP]', '📉': '[DOWN]', '💵': '[$]', '🧊': '[ICE]',
            '🚨': '[ALERT]', '⚠️': '[WARNING]', '🏆': '[CUP]', '🥇': '[1]', '🎖️': '[MEDAL]'
        }
        for emoji, rep in replacements.items():
            md_content = md_content.replace(emoji, rep)
            
        # Regex pour supprimer tous les autres caractères de type "emoji" ou "symbole complexe" 
        # qui causent les carrés noirs (ex: \u25A0 à \u2BFF et le plan supplémentaire entier)
        import re
        md_content = re.sub(r'[\u2500-\u2BFF\U00010000-\U0010ffff]', '', md_content)

        # Conversion MD -> HTML
        html_body = markdown.markdown(md_content, extensions=['extra', 'nl2br'])
        
        # Template HTML avec CSS
        full_html = f"""
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                @page {{ margin: 2cm; }}
                body {{ font-family: Helvetica, sans-serif; font-size: 11px; color: #333; line-height: 1.5; }}
                h1 {{ color: #1a5276; border-bottom: 2px solid #1a5276; padding-bottom: 10px; text-align: center; }}
                h2 {{ color: #1e8449; margin-top: 25px; border-bottom: 1px solid #ddd; }}
                h3 {{ color: #d35400; }}
                pre {{ background-color: #f4f4f4; padding: 10px; border-left: 5px solid #1a5276; white-space: pre-wrap; font-family: Courier, monospace; font-size: 10px; }}
                .footer {{ position: fixed; bottom: 0; width: 100%; text-align: center; font-size: 9px; color: #777; }}
            </style>
        </head>
        <body>
            {html_body}
            <div class="footer">Généré le {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')} - Tennis Match Analyzer</div>
        </body>
        </html>
        """

        # Dialogue de sauvegarde
        filename = f"Analyse_Match_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
        filepath = filedialog.asksaveasfilename(
            defaultextension=".pdf", 
            initialfile=filename, 
            title="Enregistrer l'analyse PDF",
            filetypes=[("Fichiers PDF", "*.pdf")]
        )
        
        if filepath:
            self.show_loading_overlay("📄 Génération du PDF")
            self.update() # Force l'affichage immédiat avant le freeze
            try:
                with open(filepath, "wb") as f:
                    pisa.CreatePDF(full_html, dest=f)
                self.hide_loading_overlay()
                messagebox.showinfo("Export PDF", f"Analyse exportée avec succès :\n{filepath}")
            except Exception as e:
                self.hide_loading_overlay()
                messagebox.showerror("Export PDF", f"Erreur lors de l'export PDF :\n{e}")

    def show_history_window(self):
        """Ouvre une popup avec l'historique complet pour un joueur ou un H2H."""
        if hasattr(self, 'history_popup') and self.history_popup.winfo_exists():
            self.history_popup.lift()
            return

        self.history_popup = ctk.CTkToplevel(self)
        popup = self.history_popup
        popup.title("Historique Détaillé")

    def show_player_stats(self, player_num=None, direct_name=None):
        if hasattr(self, 'stats_popup') and self.stats_popup.winfo_exists():
            self.stats_popup.lift()
            return

        if direct_name:
            player_name = direct_name
        else:
            player_name = self.p1_name.cget("text") if player_num == 1 else self.p2_name.cget("text")
        
        # Nettoyer le nom (enlever les émojis 👤, 🟢 et les espaces)
        if "👤" in player_name or "🟢" in player_name:
            player_name = player_name.replace("👤", "").replace("🟢", "").strip()
            
        if not player_name or player_name.startswith("Joueur"):
            return
        if not self.players_db:
            return
            
        player_obj = find_player_by_name(player_name, self.players_db)
                
        if not player_obj:
            print(f"DEBUG: Joueur non trouvé pour '{player_name}'")
            return
            
        popup = ctk.CTkToplevel(self)
        popup.title(self._tr('stats_title').format(player_name))
        popup.geometry("600x700")
        popup.grab_set()
        
        scrollable_frame = ctk.CTkScrollableFrame(popup)
        scrollable_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        def add_stat_row(parent, label, value):
            frame = ctk.CTkFrame(parent, fg_color="transparent")
            frame.pack(fill="x", pady=2)
            ctk.CTkLabel(frame, text=label, font=ctk.CTkFont(weight="bold")).pack(side="left")
            ctk.CTkLabel(frame, text=str(value)).pack(side="right")
            
        ctk.CTkLabel(scrollable_frame, text=player_name, font=ctk.CTkFont(size=24, weight="bold")).pack(pady=10)
        
        # Age Calculation

        age = "N/A"
        if hasattr(player_obj, 'birthdate') and player_obj.birthdate:
            try:
                # Handle possible float representations of dates (e.g., 19990101.0)
                b_str = str(int(float(player_obj.birthdate)))
                if len(b_str) == 8:
                    b_date = datetime.datetime.strptime(b_str, "%Y%m%d")
                    age = (datetime.datetime.now() - b_date).days // 365
            except:
                pass
                
        add_stat_row(scrollable_frame, self._tr('age'), age)
        add_stat_row(scrollable_frame, self._tr('current_rank'), getattr(player_obj, 'ranking', 'N/A'))
        
        # Hand translation
        hand = getattr(player_obj, 'hand', 'N/A')
        hand_trans = {"R": self._tr('right_handed'), "L": self._tr('left_handed'), "U": self._tr('unknown')}.get(hand, hand)
        add_stat_row(scrollable_frame, self._tr('hand'), hand_trans)
        
        # Height formatting
        height = getattr(player_obj, 'height', 'N/A')
        if height == 0 or height == "0" or height == 0.0:
            height = self._tr('unknown')
        add_stat_row(scrollable_frame, self._tr('height'), height)
        
        ctk.CTkLabel(scrollable_frame, text=self._tr('perf_gen'), font=ctk.CTkFont(size=18, weight="bold")).pack(pady=(20, 10))
        
        total_matches = len(getattr(player_obj, 'matches_history', []))
        win_pct = getattr(player_obj, 'victories_percentage', 0.0)
        matches_won = int(total_matches * (win_pct / 100))
        matches_lost = total_matches - matches_won
        
        add_stat_row(scrollable_frame, self._tr('victories'), matches_won)
        add_stat_row(scrollable_frame, self._tr('defeats'), matches_lost)
        add_stat_row(scrollable_frame, self._tr('win_pct'), f"{win_pct:.1f}%" if total_matches > 0 else "N/A")
        
        # Fatigue index
        games_fatigue = getattr(player_obj, 'games_fatigue', 0)
        recent_matches = 1
        if hasattr(player_obj, 'fatigue_features'):
            recent_matches = player_obj.fatigue_features.get("current tournament", {}).get("num_matchs", 1) + \
                             player_obj.fatigue_features.get("previous tournament", {}).get("num_matchs", 0)
            if recent_matches == 0: recent_matches = 1
            
        fatigue_idx = games_fatigue / recent_matches
        
        fatigue_str = f"{fatigue_idx:.1f}" if fatigue_idx > 0 else "N/A"
        
        f_frame = ctk.CTkFrame(scrollable_frame, fg_color="transparent")
        f_frame.pack(fill="x", pady=2)
        ctk.CTkLabel(f_frame, text=self._tr('fatigue') + ":", text_color="gray").pack(side="left")
        
        val_frame = ctk.CTkFrame(f_frame, fg_color="transparent")
        val_frame.pack(side="right")
        
        from python.gui_shared import show_player_matches_details
        ctk.CTkButton(val_frame, text="Détails", width=60, height=20, font=ctk.CTkFont(size=11), 
                      command=lambda p=player_obj: show_player_matches_details(self, p)).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(val_frame, text=fatigue_str, font=ctk.CTkFont(weight="bold")).pack(side="left")

        # Small help text for fatigue index
        ctk.CTkLabel(scrollable_frame, text=self._tr('fatigue_help'), text_color="gray", font=ctk.CTkFont(size=11, slant="italic")).pack(pady=(0, 10))
        add_stat_row(scrollable_frame, self._tr('win_streak'), getattr(player_obj, 'current_win_streak', 0))
        
        # Notes et Evaluations
        if hasattr(player_obj, 'get_ratings'):
            ctk.CTkLabel(scrollable_frame, text=self._tr('ratings'), font=ctk.CTkFont(size=18, weight="bold")).pack(pady=(20, 10))
            ratings = player_obj.get_ratings()
            
            def add_rating_bar(parent, label, score):
                frame = ctk.CTkFrame(parent, fg_color="transparent")
                frame.pack(fill="x", pady=5)
                ctk.CTkLabel(frame, text=f"{label}: {score}", font=ctk.CTkFont(weight="bold")).pack(side="left")
                
                pb = ctk.CTkProgressBar(frame, width=200)
                pb.pack(side="right", padx=10)
                pb.set(score / 100.0)
                
                # Colors based on score
                if score >= 80: pb.configure(progress_color="#2ecc71")
                elif score >= 60: pb.configure(progress_color="#f1c40f")
                elif score >= 40: pb.configure(progress_color="#e67e22")
                else: pb.configure(progress_color="#e74c3c")
                
            add_rating_bar(scrollable_frame, self._tr('endurance'), ratings["Endurance"])
            add_rating_bar(scrollable_frame, self._tr('service'), ratings["Service"])
            add_rating_bar(scrollable_frame, self._tr('talent'), ratings["Talent"])
            add_rating_bar(scrollable_frame, self._tr('forme'), ratings["Forme"])
            
            ctk.CTkLabel(scrollable_frame, text="", font=ctk.CTkFont(size=5)).pack() # Espacement
            add_rating_bar(scrollable_frame, self._tr('global_rating'), ratings["Global"])

        ctk.CTkLabel(scrollable_frame, text=self._tr('perf_surface'), font=ctk.CTkFont(size=18, weight="bold")).pack(pady=(20, 10))
        
        surfaces = [
            (self._tr('hard'), 'hard', 'matches_hard'),
            (self._tr('clay'), 'clay', 'matches_clay'),
            (self._tr('grass'), 'grass', 'matches_grass')
        ]
        
        for surf_name, attr_prefix, attr_matches in surfaces:
            surf_matches = len(getattr(player_obj, attr_matches, []))
            if surf_matches > 0:
                s_pct = getattr(player_obj, f'{attr_prefix}_victories_percentage', 0.0)
                s_won = int(surf_matches * (s_pct / 100))
                s_lost = surf_matches - s_won
                add_stat_row(scrollable_frame, surf_name, f"{s_pct:.1f}% ({s_won}-{s_lost})")
                    
        ctk.CTkLabel(scrollable_frame, text=self._tr('adv_stats_serve'), font=ctk.CTkFont(size=18, weight="bold")).pack(pady=(20, 10))
        
        add_stat_row(scrollable_frame, self._tr('1st_serve_succ'), f"{getattr(player_obj, 'first_serve_success_percentage', 0):.1f}%")
        add_stat_row(scrollable_frame, self._tr('pts_won_1st'), f"{getattr(player_obj, 'winning_on_1st_serve_percentage', 0):.1f}%")
        add_stat_row(scrollable_frame, self._tr('pts_won_2nd'), f"{getattr(player_obj, 'winning_on_2nd_serve_percentage', 0):.1f}%")
        add_stat_row(scrollable_frame, self._tr('aces'), f"{getattr(player_obj, 'aces_percentage', 0):.1f}%")
        add_stat_row(scrollable_frame, self._tr('df'), f"{getattr(player_obj, 'doublefaults_percentage', 0):.1f}%")
        add_stat_row(scrollable_frame, self._tr('bp_saved'), f"{getattr(player_obj, 'breakpoint_saved_percentage', 0):.1f}%")

        if getattr(player_obj, 'charted_matches', 0) > 0:
            ctk.CTkLabel(scrollable_frame, text=self._tr('style_play'), font=ctk.CTkFont(size=18, weight="bold")).pack(pady=(20, 10))
            
            # Winners/Errors Stats
            w_ue = getattr(player_obj, 'winner_unforced_ratio', 1.0)
            fh_w = getattr(player_obj, 'avg_winners_fh', 0)
            bh_w = getattr(player_obj, 'avg_winners_bh', 0)
            ret_pct = getattr(player_obj, 'return_pts_won_pct', 0)
            
            add_stat_row(scrollable_frame, self._tr('ratio_w_ue'), f"{w_ue:.2f}")
            add_stat_row(scrollable_frame, "Coup Droit / Revers (Gagnants)", f"{fh_w:.1f} / {bh_w:.1f}")
            add_stat_row(scrollable_frame, self._tr('pts_won_ret'), f"{ret_pct:.1f}%")
            add_stat_row(scrollable_frame, "Matchs Chartés (Data Source)", getattr(player_obj, 'charted_matches', 0))

        # New Manual Update Button for Tennis Abstract
        def trigger_ta_update():
            btn_ta.configure(state="disabled", text="⏳ Scraping Winners/Errors...")
            threading.Thread(target=run_ta_update, daemon=True).start()
            
        def run_ta_update():
            print(f"📊 Extraction Tennis Abstract pour {player_name}...")
            updated = player_obj.update_with_live_charting()
            if updated:
                print(f"✅ DNA Live mis à jour pour {player_name}.")
                self.after(0, lambda: btn_ta.configure(state="normal", text="✅ DNA Charting à jour", fg_color="#1a6b3c"))
                # Note: The popup won't refresh automatically, but the next time it opens it will have the data.
                # We could potentially refresh the popup but it's simpler to ask the user to reopen it.
            else:
                print(f"⚠️ Aucune donnée de charting récente trouvée pour {player_name}.")
                self.after(0, lambda: btn_ta.configure(state="normal", text="⚠️ Pas de données TA", fg_color="#e67e22"))

        btn_ta = ctk.CTkButton(scrollable_frame, text="📊 Actualiser Winners/Unforced Errors (Tennis Abstract)", 
                               fg_color="#e67e22", hover_color="#d35400", command=trigger_ta_update)
        btn_ta.pack(pady=10)

        # --- Historique des Matchs depuis le data_df (chargé en thread) ---
        ctk.CTkLabel(scrollable_frame, text="📋 Historique des Matchs", font=ctk.CTkFont(size=18, weight="bold")).pack(pady=(20, 5))
        
        match_section_frame = ctk.CTkFrame(scrollable_frame, fg_color="transparent")
        match_section_frame.pack(fill="x", pady=5)
        
        hist_loading = ctk.CTkLabel(match_section_frame, text="⏳ Chargement de l'historique...", text_color="gray", font=ctk.CTkFont(size=12))
        hist_loading.pack(pady=10)
        
        def load_match_history_bg():
            result = []
            if self.data_df is None or player_obj is None:
                popup.after(0, lambda: render_history(result))
                return
            try:
                pid = player_obj.id
                if 'ID_1' in self.data_df.columns and 'ID_2' in self.data_df.columns:
                    mask = (self.data_df['ID_1'] == pid) | (self.data_df['ID_2'] == pid)
                    df = self.data_df[mask].copy()
                    # Winner=0 rows: ID_1=actual winner, ID_2=actual loser  (correct perspective)
                    # Winner=1 rows: ID_1=actual loser,  ID_2=actual winner (inverted perspective)
                    # Sort Winner ASC so Winner=0 rows always come first → drop_duplicates keeps the correct row.
                    # Then _is_win = (ID_1 == pid) is reliable because ID_1 is always the actual winner.
                    df['_is_win'] = (df['ID_1'] == pid)
                    if len(df) > 0:
                        def norm_n(n): return re.sub(r'[^a-z0-9]', '', str(n).lower().strip())
                        # Normalize tournament name: remove ATP/WTA/Masters/Open/20xx to merge variants
                        # e.g. "ATP Miami Masters" and "ATP Miami" both become "miami"
                        def norm_t(t): return re.sub(r'[^a-z]', '', re.sub(r'\b(atp|wta|masters|open|20\d\d)\b', '', str(t).lower()))
                        df['match_key'] = df.apply(lambda r: "-".join(sorted([norm_n(r.get('Name_1','')), norm_n(r.get('Name_2',''))])), axis=1)
                        df['tournament_key'] = df['tournament'].astype(str).str.strip().apply(norm_t)
                        df['is_upcoming'] = df['score'].apply(lambda x: 1 if "Upcoming" in str(x) else 0)
                        df['tournament'] = df['tournament'].astype(str).str.strip()
                        # For dedup: sort tournament_date ASC so the EARLIEST entry (original ATP data)
                        # is preferred over later TE-scraped duplicates which may have wrong winner.
                        # Winner ASC ensures Winner=0 rows (ID_1=winner) come first within same date.
                        df = df.sort_values(['match_key', 'tournament_key', 'Winner', 'is_upcoming', 'tournament_date'], ascending=[True, True, True, True, True])
                        df = df.drop_duplicates(subset=['match_key', 'tournament_key'], keep='first')
                        # Recompute _is_win after dedup (Winner=0 rows kept: ID_1 = actual winner)
                        df['_is_win'] = (df['ID_1'] == pid)
                        # Display sort: most recent matches first
                        if 'tournament_date' in df.columns:
                            df = df.sort_values(['is_upcoming', 'tournament_date'], ascending=[False, False])
                        result = df.to_dict('records')
            except Exception as e:
                print(f"Erreur hist matchs: {e}")
            popup.after(0, lambda r=result: render_history(r))
        
        def render_history(all_matches):
            if not popup.winfo_exists(): return
            hist_loading.destroy()
            
            if not all_matches:
                ctk.CTkLabel(match_section_frame, text="Aucun historique disponible dans la base", text_color="gray", font=ctk.CTkFont(size=12)).pack(pady=5)
                ctk.CTkButton(scrollable_frame, text=self._tr('btn_close'), command=popup.destroy).pack(pady=20)
                return
            
            INITIAL_COUNT = 10
            shown_count_var = [INITIAL_COUNT]
            match_rows_frame = ctk.CTkFrame(match_section_frame, fg_color="transparent")
            match_rows_frame.pack(fill="x")
            show_more_btn_var = [None]
            
            def render_matches(count):
                for w in match_rows_frame.winfo_children():
                    w.destroy()
                for m in all_matches[:count]:
                    date_val = str(m.get('tournament_date', ''))
                    date_str = f"{date_val[6:8]}/{date_val[4:6]}/{date_val[:4]}" if len(date_val) == 8 else date_val
                    is_win = bool(m.get('_is_win', True))
                    
                    winner_name = str(m.get('Name_1', '?'))
                    loser_name = str(m.get('Name_2', '?'))
                    score = str(m.get('score', ''))
                    tourney = str(m.get('tournament', ''))[:22]
                    
                    if "Upcoming" in score or not score:
                        result_icon = "⏳"
                        color = "#f1c40f"
                        # Essayer de trouver la date exacte du match dans current_matches
                        def norm(n): return re.sub(r'[^a-z0-9]', '', str(n).lower())
                        m_key = "-".join(sorted([norm(winner_name), norm(loser_name)]))
                        for cm in self.current_matches:
                            cm_key = "-".join(sorted([norm(cm['player_1']), norm(cm['player_2'])]))
                            if m_key == cm_key and cm.get('full_time'):
                                date_str = cm['full_time']
                                break
                    else:
                        result_icon = "✅" if is_win else "❌"
                        color = "#2ecc71" if is_win else "#e74c3c"
                        
                        # Inverser le score si c'est une défaite (pour afficher le score du joueur en premier)
                        if not is_win and "-" in score:
                            try:
                                sets = score.replace(",", " ").split()
                                flipped_sets = []
                                for s in sets:
                                    if "-" in s:
                                        # Gérer les tie-breaks ex: 7-6(5)
                                        match = re.match(r'(\d+)-(\d+)(\(.*\))?', s)
                                        if match:
                                            g1, g2, tb = match.groups()
                                            flipped_sets.append(f"{g2}-{g1}{tb if tb else ''}")
                                        else: flipped_sets.append(s)
                                    else: flipped_sets.append(s)
                                score = ", ".join(flipped_sets)
                            except: pass
                    
                    opponent = loser_name if is_win else winner_name
                    
                    row_f = ctk.CTkFrame(match_rows_frame, fg_color=("gray90", "gray20"), corner_radius=6)
                    row_f.pack(fill="x", pady=2, padx=5)
                    ctk.CTkLabel(row_f, text=f"{result_icon} {date_str}", font=ctk.CTkFont(size=11), text_color=color, width=100).pack(side="left", padx=5)
                    ctk.CTkLabel(row_f, text=f"vs {opponent}", font=ctk.CTkFont(size=11, weight="bold"), anchor="w").pack(side="left", padx=5, fill="x", expand=True)
                    ctk.CTkLabel(row_f, text=score, font=ctk.CTkFont(family="Consolas", size=11), text_color="gray").pack(side="right", padx=5)
                    ctk.CTkLabel(row_f, text=tourney, font=ctk.CTkFont(size=10), text_color="gray").pack(side="right", padx=5)
            
            render_matches(INITIAL_COUNT)
            
            if len(all_matches) > INITIAL_COUNT:
                def toggle_more():
                    if shown_count_var[0] == INITIAL_COUNT:
                        shown_count_var[0] = len(all_matches)
                        render_matches(shown_count_var[0])
                        show_more_btn_var[0].configure(text="▲ Réduire")
                    else:
                        shown_count_var[0] = INITIAL_COUNT
                        render_matches(shown_count_var[0])
                        show_more_btn_var[0].configure(text=f"▼ Voir tous ({len(all_matches)}) matchs")
                show_more_btn_var[0] = ctk.CTkButton(
                    match_section_frame, text=f"▼ Voir tous ({len(all_matches)}) matchs",
                    fg_color="transparent", border_width=1, border_color="gray",
                    text_color="gray", font=ctk.CTkFont(size=12), command=toggle_more
                )
                show_more_btn_var[0].pack(pady=5)
        # Bouton Fermer toujours visible en bas de la popup (unique)
        ctk.CTkButton(popup, text=self._tr('btn_close'), command=popup.destroy).pack(pady=5)
        
        threading.Thread(target=load_match_history_bg, daemon=True).start()

    def show_salmons(self):
        if not self.players_db:
            return
            
        if hasattr(self, 'salmon_popup') and self.salmon_popup.winfo_exists():
            self.salmon_popup.lift()
            return

        self.salmon_popup = ctk.CTkToplevel(self)
        popup = self.salmon_popup
        popup.title(self._tr('salmons_title').format(self.current_tour))
        popup.geometry("600x600")
        popup.grab_set()
        
        ctk.CTkLabel(popup, text=self._tr('salmons_title').format(self.current_tour), font=ctk.CTkFont(size=24, weight="bold"), text_color="#e67e22").pack(pady=10)
        ctk.CTkLabel(popup, text=self._tr('salmons_subtitle'), font=ctk.CTkFont(size=14, slant="italic")).pack(pady=(0, 10))
        
        scrollable_frame = ctk.CTkScrollableFrame(popup)
        scrollable_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Indicateur de chargement immédiat
        loading_label = ctk.CTkLabel(scrollable_frame, text="⏳ Calcul en cours...", text_color="gray", font=ctk.CTkFont(size=14))
        loading_label.pack(pady=40)
        
        ctk.CTkButton(popup, text=self._tr('btn_close'), command=popup.destroy).pack(pady=10)
        
        def compute_salmons():
            salmons = []
            for p in self.players_db.values():
                if not hasattr(p, 'is_salmon'): continue
                # On force le recalcul pour appliquer les nouveaux critères
                # On passe players_db pour activer la détection "Tueur de Géants"
                p._salmon_cache = p.is_salmon(players_db=self.players_db)
                is_s, score, reason = p._salmon_cache
                if is_s:
                    salmons.append((p, score, reason))
            salmons.sort(key=lambda x: x[1], reverse=True)
            popup.after(0, lambda: populate_salmons(salmons))
        
        def populate_salmons(salmons):
            if not popup.winfo_exists(): return
            loading_label.destroy()
            if not salmons:
                ctk.CTkLabel(scrollable_frame, text=self._tr('no_salmons')).pack(pady=20)
            else:
                # Augmenter la limite à 50 pour éviter que des saumons visibles ailleurs ne soient absents ici
                for i, (p, score, reason) in enumerate(salmons[:50]):
                    frame = ctk.CTkFrame(scrollable_frame)
                    frame.pack(fill="x", pady=5, padx=5)
                    header = ctk.CTkLabel(frame, text=f"#{i+1} {p.name} ({self._tr('rank')}{p.ranking})", font=ctk.CTkFont(weight="bold", size=16))
                    header.pack(anchor="w", padx=10, pady=(10, 0))
                    desc = ctk.CTkLabel(frame, text=reason, wraplength=500, justify="left", text_color="#2ecc71")
                    desc.pack(anchor="w", padx=10, pady=(5, 10))
        
        threading.Thread(target=compute_salmons, daemon=True).start()

    def show_top_players(self):
        if not self.players_db:
            return
            
        if hasattr(self, 'top_players_popup') and self.top_players_popup.winfo_exists():
            self.top_players_popup.lift()
            return

        self.top_players_popup = ctk.CTkToplevel(self)
        popup = self.top_players_popup
        title_key = 'top_players_title_wta' if self.current_tour == "WTA" else 'top_players_title'
        popup.title(self._tr(title_key).format(self.current_tour))
        popup.geometry("600x600")
        popup.grab_set()
        
        ctk.CTkLabel(popup, text=self._tr(title_key).format(self.current_tour), font=ctk.CTkFont(size=24, weight="bold"), text_color="#8e44ad").pack(pady=10)
        ctk.CTkLabel(popup, text=self._tr('top_players_subtitle'), font=ctk.CTkFont(size=14, slant="italic")).pack(pady=(0, 10))
        
        scrollable_frame = ctk.CTkScrollableFrame(popup)
        scrollable_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        loading_label = ctk.CTkLabel(scrollable_frame, text="⏳ Calcul des notes en cours...", text_color="gray", font=ctk.CTkFont(size=14))
        loading_label.pack(pady=40)
        
        ctk.CTkButton(popup, text=self._tr('btn_close'), command=popup.destroy).pack(pady=10)
        
        def compute_top_players():
            players_rated = []
            for p in self.players_db.values():
                if hasattr(p, 'get_ratings') and 0 < p.ranking < 9999 and len(getattr(p, 'matches_history', [])) > 10:
                    ratings = p.get_ratings()
                    players_rated.append((p, ratings['Global'], ratings))
            players_rated.sort(key=lambda x: x[1], reverse=True)
            popup.after(0, lambda: populate_top(players_rated))
        
        def populate_top(players_rated):
            if not popup.winfo_exists(): return
            loading_label.destroy()
            if not players_rated:
                ctk.CTkLabel(scrollable_frame, text=self._tr('no_players_rated')).pack(pady=20)
                return
            for i, (p, global_score, ratings) in enumerate(players_rated[:50]):
                frame = ctk.CTkFrame(scrollable_frame)
                frame.pack(fill="x", pady=5, padx=5)
                header_text = f"#{i+1} {p.name} ({self._tr('rank')}{p.ranking}) - {self._tr('global_score')}{global_score}/100"
                color = "#f1c40f" if i == 0 else "#bdc3c7" if i == 1 else "#cd7f32" if i == 2 else "#ffffff"
                ctk.CTkLabel(frame, text=header_text, font=ctk.CTkFont(weight="bold", size=16), text_color=color).pack(anchor="w", padx=10, pady=(10, 0))
                details = f"{self._tr('endurance')}: {ratings['Endurance']} | {self._tr('service')}: {ratings['Service']} | {self._tr('talent')}: {ratings['Talent']} | {self._tr('forme')}: {ratings['Forme']}"
                ctk.CTkLabel(frame, text=details, text_color="gray", font=ctk.CTkFont(size=12)).pack(anchor="w", padx=10, pady=(5, 10))
        
        threading.Thread(target=compute_top_players, daemon=True).start()

    def show_top_servers(self):
        if not self.players_db:
            return
            
        if hasattr(self, 'top_servers_popup') and self.top_servers_popup.winfo_exists():
            self.top_servers_popup.lift()
            return

        self.top_servers_popup = ctk.CTkToplevel(self)
        popup = self.top_servers_popup
        # Use tour-specific title
        title_key = 'servers_title_wta' if self.current_tour == "WTA" else 'servers_title'
        popup.title(self._tr(title_key).format(self.current_tour))
        popup.geometry("600x600")
        popup.grab_set()
        
        ctk.CTkLabel(popup, text=self._tr('servers_title').format(self.current_tour), font=ctk.CTkFont(size=24, weight="bold"), text_color="#3498db").pack(pady=10)
        ctk.CTkLabel(popup, text=self._tr('servers_subtitle'), font=ctk.CTkFont(size=14, slant="italic")).pack(pady=(0, 10))
        
        scrollable_frame = ctk.CTkScrollableFrame(popup)
        scrollable_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        players_rated = []
        for p in self.players_db.values():
            if hasattr(p, 'get_ratings'):
                if p.ranking > 0 and p.ranking < 9999 and len(getattr(p, 'matches_history', [])) > 10:
                    ratings = p.get_ratings()
                    players_rated.append((p, ratings['Service'], ratings))
                    
        # Trier par note de service décroissante
        players_rated.sort(key=lambda x: x[1], reverse=True)
        
        if not players_rated:
            ctk.CTkLabel(scrollable_frame, text=self._tr('no_players_rated')).pack(pady=20)
        else:
            for i, (p, service_score, ratings) in enumerate(players_rated[:50]): # Top 50
                frame = ctk.CTkFrame(scrollable_frame)
                frame.pack(fill="x", pady=5, padx=5)
                
                header_text = f"#{i+1} {p.name} ({self._tr('rank')}{p.ranking}) - {self._tr('note_service')}{service_score}/100"
                
                color = "#ffffff"
                if i == 0: color = "#f1c40f"
                elif i == 1: color = "#bdc3c7"
                elif i == 2: color = "#cd7f32"
                
                header = ctk.CTkLabel(frame, text=header_text, font=ctk.CTkFont(weight="bold", size=16), text_color=color)
                header.pack(anchor="w", padx=10, pady=(10, 0))
                
                # Show raw service stats directly instead of just the aggregated note
                details = self._tr('servers_stats').format(p.aces_percentage, p.first_serve_success_percentage, p.winning_on_1st_serve_percentage)
                desc = ctk.CTkLabel(frame, text=details, text_color="gray", font=ctk.CTkFont(size=12))
                desc.pack(anchor="w", padx=10, pady=(5, 10))
                
        ctk.CTkButton(popup, text=self._tr('btn_close'), command=popup.destroy).pack(pady=10)

    def show_detailed_odds(self):
        """Affiche une fenêtre avec tous les paris disponibles chez les bookmakers."""
        if not hasattr(self, 'current_match_for_odds'):
            return
            
        match = self.current_match_for_odds
        p1 = match['player_1']
        p2 = match['player_2']
        
        from python.data.odds_api import get_all_tennis_data, get_detailed_match_odds
        # On force la mise à jour pour être sûr d'avoir les marchés alternatifs (spreads/totals)
        odds_data = get_all_tennis_data(force_update=True)
        detailed_odds = get_detailed_match_odds(p1, p2, odds_data.get('odds', []))
        
        if hasattr(self, 'detailed_odds_popup') and self.detailed_odds_popup.winfo_exists():
            self.detailed_odds_popup.lift()
            return

        self.detailed_odds_popup = ctk.CTkToplevel(self)
        popup = self.detailed_odds_popup
        popup.title(f"{self._tr('view_odds')} - {p1} vs {p2}")
        popup.geometry("800x600")
        popup.attributes("-topmost", True)
        
        ctk.CTkLabel(popup, text=f"📋 {self._tr('view_odds')}", font=ctk.CTkFont(size=20, weight="bold"), text_color="#2ecc71").pack(pady=10)
        ctk.CTkLabel(popup, text=f"{p1} vs {p2}", font=ctk.CTkFont(size=14, slant="italic")).pack(pady=(0, 10))
        
        scrollable_frame = ctk.CTkScrollableFrame(popup)
        scrollable_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        if not detailed_odds:
            ctk.CTkLabel(scrollable_frame, text="Aucune cote détaillée trouvée pour ce match.").pack(pady=20)
        else:
            # Group by Market Type
            market_titles = {
                "h2h": "🏆 Vainqueur (H2H)",
                "spreads": "⚖️ Handicap (Spreads)",
                "totals": "🔢 Total Jeux (Over/Under)",
                "aces": "🎾 Aces (Total / Vainqueur)"
            }
            
            for m_key, m_title in market_titles.items():
                # Check if any bookie has this market
                has_market = any(m_key in b_odds['markets'] for b_odds in detailed_odds)
                
                # Special case for Aces: also show our prediction even if no odds
                if m_key == "aces":
                    # Calculate our theoretical total
                    p1_obj, p2_obj = None, None
                    for p in self.players_db.values():
                        if p.name == p1: p1_obj = p
                        if p.name == p2: p2_obj = p
                    
                    aces_1 = getattr(p1_obj, 'aces_per_match', 0) if p1_obj else 0
                    aces_2 = getattr(p2_obj, 'aces_per_match', 0) if p2_obj else 0
                    # Estimation sur un match standard de 2.2 sets
                    theo_total = (aces_1 + aces_2) * 1.1 
                    
                    ctk.CTkLabel(scrollable_frame, text=m_title, font=ctk.CTkFont(size=16, weight="bold"), text_color="#3498db").pack(pady=(15, 5), anchor="w", padx=10)
                    pred_frame = ctk.CTkFrame(scrollable_frame, fg_color="#1a5276")
                    pred_frame.pack(fill="x", pady=2, padx=5)
                    ctk.CTkLabel(pred_frame, text=f"📊 Estimation IA : ~{theo_total:.1f} Aces au total", font=ctk.CTkFont(weight="bold")).pack(pady=5)
                    
                    if not has_market:
                        ctk.CTkLabel(scrollable_frame, text="   (Aucune cote bookmaker en direct pour les Aces)", font=ctk.CTkFont(size=11, slant="italic"), text_color="gray").pack(anchor="w", padx=20)
                        continue
                
                if not has_market: continue
                
                if m_key != "aces": # Aces header already added
                    ctk.CTkLabel(scrollable_frame, text=m_title, font=ctk.CTkFont(size=16, weight="bold"), text_color="#3498db").pack(pady=(15, 5), anchor="w", padx=10)
                
                for b_odds in detailed_odds:
                    if m_key not in b_odds['markets']: continue
                    
                    data = b_odds['markets'][m_key]
                    row_frame = ctk.CTkFrame(scrollable_frame, fg_color="gray15")
                    row_frame.pack(fill="x", pady=2, padx=5)
                    
                    # Bookie name
                    ctk.CTkLabel(row_frame, text=b_odds['bookmaker'], width=150, anchor="w", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=10)
                    
                    if m_key == "h2h":
                        ctk.CTkLabel(row_frame, text=f"{p1}: {data.get(p1, 'N/A')}", text_color="#2ecc71").pack(side="left", padx=10)
                        ctk.CTkLabel(row_frame, text=f"{p2}: {data.get(p2, 'N/A')}", text_color="#e67e22").pack(side="left", padx=10)
                    
                    elif m_key == "spreads":
                        # Group by point for cleaner display
                        grouped = {}
                        for o in data:
                            pt = o.get('point')
                            if pt not in grouped: grouped[pt] = {}
                            grouped[pt][o.get('player')] = o.get('price')
                        lines = [f"[{pt}] " + "/".join([f"{pr}" for pr in grouped[pt].values()]) for pt in sorted(grouped.keys())]
                        ctk.CTkLabel(row_frame, text=" | ".join(lines), font=ctk.CTkFont(size=11), wraplength=550, justify="left").pack(side="left", padx=10, fill="x", expand=True)
                        
                    elif m_key == "totals" or m_key == "aces":
                        # Group by point (Over/Under pairs)
                        grouped = {}
                        for o in data:
                            pt = o.get('point')
                            if pt not in grouped: grouped[pt] = {}
                            name = "O" if "over" in str(o.get('name')).lower() else "U"
                            grouped[pt][name] = o.get('price')
                        
                        lines = []
                        for pt in sorted(grouped.keys()):
                            v = grouped[pt]
                            lines.append(f"[{pt}] O:{v.get('O','?')}/U:{v.get('U','?')}")
                        
                        ctk.CTkLabel(row_frame, text=" | ".join(lines), font=ctk.CTkFont(size=11), wraplength=550, justify="left").pack(side="left", padx=10, fill="x", expand=True)
                
    def open_shorts_mode(self):
        """Ouvre une fenêtre verticale optimisée pour les réseaux sociaux (Shorts/TikTok)."""
        if not hasattr(self, 'selected_match') or not self.selected_match:
            from tkinter import messagebox
            messagebox.showwarning("Shorts Mode", "Veuillez d'abord sélectionner un match dans la liste pour générer le visuel.")
            return

        match = self.selected_match
        p1 = match['player_1']
        p2 = match['player_2']
        
        # Récupérer les données de probabilité si déjà calculées, sinon recalculer
        # (On assume que si un match est sélectionné, on a les données dans self.current_analysis_data)
        if not hasattr(self, 'current_analysis_data'):
            from tkinter import messagebox
            messagebox.showwarning("Shorts Mode", "Veuillez d'abord lancer l'analyse du match (double-clic) pour charger les stats.")
            return

        data = self.current_analysis_data
        prob1 = data['prob_1']
        prob2 = data['prob_2']
        
        if hasattr(self, 'shorts_popup') and self.shorts_popup.winfo_exists():
            self.shorts_popup.lift()
            return

        self.shorts_popup = ctk.CTkToplevel(self)
        shorts_win = self.shorts_popup
        shorts_win.title(f"🎬 Mode Vidéo - {p1} vs {p2}")
        shorts_win.geometry("450x800")
        shorts_win.configure(fg_color="#0a0a0a") # Fond ultra sombre
        shorts_win.attributes("-topmost", True)

        # Header stylé
        header = ctk.CTkFrame(shorts_win, fg_color="#1a1a1a", height=80, corner_radius=0)
        header.pack(fill="x")
        ctk.CTkLabel(header, text="TENNIS PREDICTION IA", font=ctk.CTkFont(size=22, weight="bold"), text_color="#2ecc71").pack(pady=20)

        # VS Section
        vs_frame = ctk.CTkFrame(shorts_win, fg_color="transparent")
        vs_frame.pack(pady=30, fill="x", padx=20)
        
        # Player 1
        p1_frame = ctk.CTkFrame(vs_frame, fg_color="#222", corner_radius=15)
        p1_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(p1_frame, text=p1, font=ctk.CTkFont(size=24, weight="bold"), text_color="white").pack(pady=10)
        
        # Prob Bar 1
        bar1 = ctk.CTkProgressBar(shorts_win, width=350, height=20, progress_color="#2ecc71", fg_color="#333")
        bar1.pack(pady=5)
        bar1.set(prob1)
        ctk.CTkLabel(shorts_win, text=f"{prob1*100:.1f}%", font=ctk.CTkFont(size=18, weight="bold"), text_color="#2ecc71").pack()

        ctk.CTkLabel(shorts_win, text="VS", font=ctk.CTkFont(size=30, weight="bold"), text_color="gray").pack(pady=15)

        # Player 2
        p2_frame = ctk.CTkFrame(shorts_win, fg_color="#222", corner_radius=15)
        p2_frame.pack(fill="x", pady=5, padx=20)
        ctk.CTkLabel(p2_frame, text=p2, font=ctk.CTkFont(size=24, weight="bold"), text_color="white").pack(pady=10)
        
        # Prob Bar 2
        bar2 = ctk.CTkProgressBar(shorts_win, width=350, height=20, progress_color="#e67e22", fg_color="#333")
        bar2.pack(pady=5)
        bar2.set(prob2)
        ctk.CTkLabel(shorts_win, text=f"{prob2*100:.1f}%", font=ctk.CTkFont(size=18, weight="bold"), text_color="#e67e22").pack()

        # Divider
        ctk.CTkFrame(shorts_win, fg_color="#2ecc71", height=2).pack(fill="x", pady=30, padx=50)

        # Advice Section
        advice_frame = ctk.CTkFrame(shorts_win, fg_color="#111", corner_radius=20)
        advice_frame.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        
        ctk.CTkLabel(advice_frame, text="💡 CONSEIL DE L'IA", font=ctk.CTkFont(size=18, weight="bold"), text_color="#3498db").pack(pady=15)
        
        # Extraction du conseil principal de l'IA (on prend le texte de Mistral si présent)
        ai_text = self.ai_textbox.get("1.0", "end").strip()
        if "Synthèse textuelle courte" in ai_text or len(ai_text) < 10:
             # Fallback si pas encore d'IA
             advice_txt = f"Vainqueur suggéré : {p1 if prob1 > prob2 else p2}\nIndice de confiance : 🔥 High"
        else:
             # On essaie d'extraire le gagnant potentiel et le conseil principal
             import re
             winner_match = re.search(r"\*\*🏆 GAGNANT POTENTIEL :.*?\*\*\s*(.*)", ai_text)
             tip_match = re.search(r"\*\*🎯 CONSEIL PRINCIPAL SÉCURISÉ :.*?\*\*\s*(.*)", ai_text)
             
             advice_txt = ""
             if winner_match: advice_txt += f"🏆 GAGNANT : {winner_match.group(1).strip()}\n\n"
             if tip_match: advice_txt += f"🎯 PRONO : {tip_match.group(1).strip()}"
             
             if not advice_txt: advice_txt = ai_text[:200] + "..."

        ctk.CTkLabel(advice_frame, text=advice_txt, font=ctk.CTkFont(size=16), wraplength=380, justify="center").pack(pady=10, padx=10)

        # Footer / CTA
        footer = ctk.CTkLabel(shorts_win, text="Abonne-toi pour plus de pronos ! 🎾", font=ctk.CTkFont(size=14, slant="italic"), text_color="#2ecc71")
        footer.pack(side="bottom", pady=20)

        # Animation d'entrée des barres
        def animate():
            bar1.set(0)
            bar2.set(0)
            for i in range(101):
                shorts_win.after(i*10, lambda v=i/100: bar1.set(v * prob1))
                shorts_win.after(i*10, lambda v=i/100: bar2.set(v * prob2))
        
        shorts_win.after(500, animate)

    def on_cleanup_database(self):
        """Lancement manuel du nettoyage chirurgical de la base."""
        from python.data.cleanup_utils import cleanup_tennis_database
        from tkinter import messagebox
        
        if messagebox.askyesno("Nettoyage Base", "Voulez-vous effectuer un nettoyage chirurgical de la base de données ?\n(Ceci supprimera les doublons et corrigera les incohérences sans tout re-scrapper)"):
            try:
                count = cleanup_tennis_database(output_dir="data")
                messagebox.showinfo("Succès", f"Nettoyage terminé !\n{count} entrées problématiques ont été traitées.")
                self.on_refresh_matches()
            except Exception as e:
                messagebox.showerror("Erreur", f"Erreur lors du nettoyage : {e}")

    def on_rescrape_tournament(self):
        """Re-scrapper le tournoi sélectionné."""
        if not hasattr(self, 'current_tournament_label') or not self.current_tournament_label:
             return
        self.on_tournament_selected(self.current_tournament_label, force_update=True)

    def on_test_odds_api(self):
        """Teste la connexion à l'API Odds et affiche le quota restant."""
        from python.data.odds_api import check_api_quota
        from tkinter import messagebox
        
        quota_info = check_api_quota()
        if quota_info:
            msg = f"API Odds connectée !\n\n"
            msg += f"Requêtes restantes : {quota_info.get('remaining', 'N/A')}\n"
            msg += f"Quota total : {quota_info.get('used', 0) + quota_info.get('remaining', 0)}\n"
            messagebox.showinfo("Test API Cotes", msg)
        else:
            messagebox.showerror("Test API Cotes", "Impossible de contacter l'API Odds. Vérifiez vos clés dans le fichier .env.")

if __name__ == "__main__":
    app = TennisApp()
    app.mainloop()
