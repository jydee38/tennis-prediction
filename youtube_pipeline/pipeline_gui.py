import customtkinter as ctk
import subprocess
import threading
import sys
import os

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

class PipelineGUI(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Antigravity Pro - Générateur de Shorts")
        self.geometry("800x600")
        
        # Configuration de la grille
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        
        # En-tête
        self.header_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.header_frame.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="ew")
        
        self.title_label = ctk.CTkLabel(self.header_frame, text="🎬 Tableau de Bord d'Automatisation YouTube", font=ctk.CTkFont(size=20, weight="bold"))
        self.title_label.pack(side="left")
        
        self.start_btn = ctk.CTkButton(
            self.header_frame, 
            text="🚀 Lancer la Génération", 
            fg_color="#27ae60", hover_color="#2ecc71",
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self.start_pipeline
        )
        self.start_btn.pack(side="right")
        
        # Console de logs
        self.log_textbox = ctk.CTkTextbox(self, state="disabled", font=ctk.CTkFont(family="Consolas", size=12))
        self.log_textbox.grid(row=1, column=0, padx=20, pady=(0, 20), sticky="nsew")
        
        self.log_message("Prêt. Cliquez sur 'Lancer la Génération' pour démarrer le pipeline.\n")

    def log_message(self, message):
        """Ajoute un message dans la console de manière thread-safe."""
        def append():
            self.log_textbox.configure(state="normal")
            self.log_textbox.insert("end", message + "\n")
            self.log_textbox.see("end")
            self.log_textbox.configure(state="disabled")
        self.after(0, append)

    def start_pipeline(self):
        self.start_btn.configure(state="disabled", text="En cours...")
        self.log_message("="*50)
        self.log_message("Démarrage du processus dans un thread séparé...")
        
        # Lancer le thread
        thread = threading.Thread(target=self.run_process)
        thread.daemon = True
        thread.start()

    def run_process(self):
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        orchestrator_script = os.path.join(project_root, "youtube_pipeline", "pipeline_orchestrator.py")
        
        try:
            # Lancement du processus avec redirection des flux et encodage UTF-8 forcé
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            
            process = subprocess.Popen(
                [sys.executable, "-u", orchestrator_script],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                bufsize=1,
                cwd=project_root, # important pour les chemins relatifs potentiels
                env=env
            )
            
            # Lecture en temps réel
            for line in process.stdout:
                self.log_message(line.strip('\n'))
                
            process.wait()
            
            if process.returncode == 0:
                self.log_message("\n✅ Terminé avec succès !")
            else:
                self.log_message(f"\n❌ Erreur : Le processus s'est terminé avec le code {process.returncode}")
                
        except Exception as e:
            self.log_message(f"\n❌ Exception fatale lors du lancement : {str(e)}")
            
        finally:
            # Réactiver le bouton (thread-safe)
            self.after(0, lambda: self.start_btn.configure(state="normal", text="🚀 Lancer la Génération"))

if __name__ == "__main__":
    app = PipelineGUI()
    app.mainloop()
