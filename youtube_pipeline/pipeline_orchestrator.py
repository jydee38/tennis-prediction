import os
import sys
import subprocess
from datetime import datetime

# Configure UTF-8 stdout encoding for Windows
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass


# Chemins globaux
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPELINE_DIR = os.path.join(PROJECT_ROOT, "youtube_pipeline")
ASSETS_DIR = os.path.join(PIPELINE_DIR, "assets")

# Fichiers sources (déplacés dans le projet)
INTRO_PATH = os.path.join(ASSETS_DIR, "intro.mp4")
AUDIO_PATH = os.path.join(ASSETS_DIR, "gigi.mp3")
CLIENT_SECRETS = os.path.join(PROJECT_ROOT, "json", "client_secret_618490937713-tjrisq3uq4d2i3ntske7a3gd1feavfde.apps.googleusercontent.com.json")

# Fichiers générés
CAPTURE_PATH = os.path.join(PROJECT_ROOT, "capture_brute.mp4")
FINAL_SHORT_PATH = os.path.join(PROJECT_ROOT, "short_final.mp4")

# Scripts du pipeline
CAPTURE_SCRIPT = os.path.join(PROJECT_ROOT, "youtube_pipeline", "capture_tkinter.py")
MONTAGE_SCRIPT = os.path.join(PROJECT_ROOT, "youtube_pipeline", "montage_video.py")
UPLOAD_SCRIPT = os.path.join(PROJECT_ROOT, "youtube_pipeline", "upload_youtube.py")

def main():
    print("=" * 50)
    print("🚀 DÉMARRAGE DU PIPELINE ANTIGRAVITY PRO 🚀")
    print("=" * 50)
    
    # Configuration de l'environnement UTF-8 pour les sous-processus
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    
    try:
        # --- TASK 1 : CAPTURE TKINTER ---
        print("\n[Etape 1/3] Génération de la vue et capture brute...")
        # Lancement avec sys.executable pour garantir le même environnement Python
        subprocess.run([sys.executable, "-u", CAPTURE_SCRIPT], env=env, check=True)
        
        if not os.path.exists(CAPTURE_PATH):
            raise FileNotFoundError(f"Échec de la création de {CAPTURE_PATH}")

        # --- TASK 2 : MONTAGE VIDEO ---
        print("\n[Etape 2/3] Montage avec l'intro et la piste son...")
        subprocess.run([
            sys.executable, "-u", MONTAGE_SCRIPT,
            "--capture", CAPTURE_PATH,
            "--intro", INTRO_PATH,
            "--audio", AUDIO_PATH,
            "--output", FINAL_SHORT_PATH
        ], env=env, check=True)
        
        if not os.path.exists(FINAL_SHORT_PATH):
            raise FileNotFoundError(f"Échec de la création du montage final {FINAL_SHORT_PATH}")

        # --- TASK 3 : UPLOAD YOUTUBE ---
        print("\n[Etape 3/3] Publication automatique sur YouTube...")
        today_str = datetime.now().strftime("%d/%m/%Y")
        time_str = datetime.now().strftime("%H:%M")
        title = f"Pronostics Tennis du {today_str} 🔥 #shorts"
        description = f"Pronostics générés le {today_str} à {time_str} par un outil de prédiction de tennis.\nLes meilleures opportunités de la journée ! Abonnez-vous pour ne rien rater. #tennis #pronostic #atp #wta"
        
        subprocess.run([
            sys.executable, "-u", UPLOAD_SCRIPT,
            "--video", FINAL_SHORT_PATH,
            "--title", title,
            "--desc", description,
            "--secrets", CLIENT_SECRETS,
            "--privacy", "public"
        ], env=env, check=True)

        # --- TASK 4 : NETTOYAGE ---
        print("\n[Nettoyage] Suppression des fichiers intermédiaires...")
        os.remove(CAPTURE_PATH)
        print("🗑️ capture_brute.mp4 supprimée.")
        
        print("\n" + "=" * 50)
        print("🎉 PIPELINE TERMINÉ AVEC SUCCÈS ! 🎉")
        print("Le Short est désormais disponible sur YouTube.")
        print("=" * 50)

    except subprocess.CalledProcessError as e:
        print(f"\n❌ ERREUR FATALE : Un des modules a échoué (Code retour: {e.returncode})")
        print("Arrêt immédiat du pipeline.")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERREUR : {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
