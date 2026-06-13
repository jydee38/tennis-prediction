"""
Module partagé pour la persistance des paramètres d'analyse.
Utilisé par gui_app.py et gui_app_bulletin.py.
"""
import json
import os

SETTINGS_PATH = os.path.join("data", "analysis_settings.json")

DEFAULTS = {
    "min_history": 10,
    "min_value": 1.25,
    "min_odds": 1.65,
    "min_prob": 0.51,  # Ajusté à 51% pour avoir un mix équilibré Vainqueur / Over
    "ou_target_prob": 0.75,
    "initial_capital": 100.0
}

def load_analysis_settings():
    """Charge les paramètres depuis le fichier JSON, avec fallback sur les valeurs par défaut."""
    settings = DEFAULTS.copy()
    try:
        if os.path.exists(SETTINGS_PATH):
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            # Fusionner avec les defaults (pour les nouvelles clés ajoutées en cours de dev)
            settings.update({k: saved[k] for k in DEFAULTS if k in saved})
    except Exception as e:
        print(f"[settings] Erreur chargement : {e}")
    return settings

def save_analysis_settings(settings: dict):
    """Sauvegarde les paramètres dans le fichier JSON."""
    try:
        os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[settings] Erreur sauvegarde : {e}")
