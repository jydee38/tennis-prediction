import mss
import cv2
import numpy as np
import time
import os
import sys

# Configure UTF-8 stdout encoding for Windows
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass


def record_tkinter_window(root, output_file="capture_brute.mp4", duration=15, fps=30):
    """
    Capture la fenêtre Tkinter via mss et l'encode en mp4v avec cv2.
    """
    print(f"[Capture] Préparation de l'enregistrement pour {duration} secondes à {fps} FPS...")
    
    # On s'assure que la fenêtre est bien affichée et positionnée
    root.update_idletasks()
    root.update()
    
    # Récupération dynamique de la géométrie de la fenêtre
    x = root.winfo_rootx()
    y = root.winfo_rooty()
    width = root.winfo_width()
    height = root.winfo_height()
    
    # Ajuster la taille pour s'assurer qu'elle est paire (requis par certains encodeurs vidéo)
    width = width if width % 2 == 0 else width - 1
    height = height if height % 2 == 0 else height - 1
    
    monitor = {"top": y, "left": x, "width": width, "height": height}
    
    # Configuration OpenCV
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_file, fourcc, fps, (width, height))
    
    sct = mss.mss()
    
    total_frames = duration * fps
    frame_time = 1.0 / fps
    
    print("[Capture] 🎬 Enregistrement en cours...")
    
    start_time = time.time()
    frames_captured = 0
    summary_frames_to_record = None
    
    while frames_captured < total_frames:
        loop_start = time.time()
        
        # Maintien de la fluidité de l'interface Tkinter
        root.update_idletasks()
        root.update()
        
        # Capture brute
        sct_img = sct.grab(monitor)
        
        # Conversion mss vers format OpenCV (BGRA -> BGR)
        frame = np.array(sct_img)
        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
        
        # Écriture de la frame
        out.write(frame)
        frames_captured += 1
        
        # Arrêt dynamique : si le résumé est affiché, on n'enregistre que 6 secondes supplémentaires
        if getattr(root, 'is_summary_displayed', False):
            if summary_frames_to_record is None:
                summary_frames_to_record = 6 * fps
                print(f"[Capture] 📝 Résumé détecté ! Enregistrement de {summary_frames_to_record} frames additionnelles...")
            else:
                summary_frames_to_record -= 1
                if summary_frames_to_record <= 0:
                    print("[Capture] ✅ Enregistrement du résumé terminé.")
                    break
        
        # Synchronisation pour respecter le FPS cible
        elapsed = time.time() - loop_start
        sleep_time = frame_time - elapsed
        if sleep_time > 0:
            time.sleep(sleep_time)
            
    # Nettoyage
    out.release()
    print(f"[Capture] ✅ Enregistrement terminé : {output_file}")
    return output_file

if __name__ == "__main__":
    # Ajouter le dossier racine au PYTHONPATH pour importer gui_app_bulletin
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import importlib
    gui_app_bulletin = importlib.import_module("1_gui_app_bulletin")
    
    print("[Capture] Initialisation de l'application TennisBulletinApp...")
    app = gui_app_bulletin.TennisBulletinApp()
    
    has_started_calculation = [False]

    def check_and_start():
        try:
            calc_state = app.calc_btn.cget("state")
            reveal_state = app.reveal_btn.cget("state")
            print(f"[Capture] État - Calculer: {calc_state}, Révéler: {reveal_state}")
            
            if reveal_state == "normal":
                print("[Capture] 🚀 Calcul IA terminé ! Déclenchement de la révélation...")
                app.magic_reveal()
                # On lance la capture après 1 seconde pour voir l'animation de chargement
                app.after(1000, run_capture)
            elif "ERREUR" in app.reveal_btn.cget("text") or "ERREUR" in app.calc_btn.cget("text"):
                print("[Capture] ❌ Erreur lors du chargement des données. Arrêt.")
                app.quit()
            else:
                # Si le bouton Calculer est prêt et qu'on ne l'a pas encore cliqué
                if calc_state == "normal" and not has_started_calculation[0]:
                    print("[Capture] 🔄 Chargement initial terminé. Lancement automatique du calcul lourd...")
                    has_started_calculation[0] = True
                    app.magic_calculate()
                
                # Re-vérifier toutes les secondes
                app.after(1000, check_and_start)
        except Exception as ex:
            print(f"[Capture] Erreur check_and_start : {ex}")
            app.quit()

    def run_capture():
        try:
            # Capture dynamique avec limite de sécurité à 50 secondes
            record_tkinter_window(app, output_file="capture_brute.mp4", duration=50, fps=30)
        except Exception as e:
            print(f"Erreur de capture : {e}")
        finally:
            app.quit()
            
    # Démarrer la surveillance du chargement après 2 secondes
    app.after(2000, check_and_start)
    app.mainloop()
