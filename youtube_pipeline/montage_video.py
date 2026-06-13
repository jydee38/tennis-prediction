import os
import sys
from moviepy.editor import VideoFileClip, AudioFileClip, concatenate_videoclips

# Configure UTF-8 stdout encoding for Windows
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass


def assemble_video(capture_path, intro_path, audio_path, output_path="short_final.mp4"):
    """
    Assemble l'introduction, la capture brute et une piste audio pour créer le Short final.
    """
    print("[Montage] Démarrage de la post-production...")
    
    if not os.path.exists(capture_path):
        raise FileNotFoundError(f"Fichier de capture introuvable : {capture_path}")
    if not os.path.exists(intro_path):
        raise FileNotFoundError(f"Fichier d'intro introuvable : {intro_path}")
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Fichier audio introuvable : {audio_path}")

    video_clip = None
    intro_clip = None
    intro_final = None
    final_video_before_audio = None
    audio_clip = None
    final_video = None

    try:
        # 1. Charger la capture brute
        video_clip = VideoFileClip(capture_path)
        base_width, base_height = video_clip.size
        print(f"[Montage] Dimensions de la capture : {base_width}x{base_height}")

        # 2. Charger l'intro et la redimensionner pour correspondre à la capture
        intro_clip = VideoFileClip(intro_path)
        print("[Montage] Redimensionnement de l'intro...")
        intro_final = intro_clip.resize(newsize=(base_width, base_height))

        # 3. Concaténer
        print("[Montage] Fusion des clips vidéo...")
        final_video_before_audio = concatenate_videoclips([intro_final, video_clip])

        # 4. Charger et découper l'audio à la frame près
        total_duration = final_video_before_audio.duration
        audio_clip = AudioFileClip(audio_path)
        
        print(f"[Montage] Durée totale de la vidéo : {total_duration}s. Découpage de l'audio...")
        # Si l'audio est plus court, on prend la durée de l'audio (pour éviter un plantage)
        cut_duration = min(total_duration, audio_clip.duration)
        audio_subclip = audio_clip.subclip(0, cut_duration)

        # 5. Appliquer l'audio
        final_video = final_video_before_audio.set_audio(audio_subclip)

        # 6. Rendu final avec contraintes YouTube (libx264, aac)
        print(f"[Montage] Encodage et export vers {output_path}...")
        final_video.write_videofile(
            output_path, 
            codec="libx264", 
            audio_codec="aac",
            fps=30,
            preset="slow",
            bitrate="8000k",
            threads=4
        )
        print("[Montage] ✅ Post-production terminée avec succès !")
        return output_path

    finally:
        # Nettoyage rigoureux de la mémoire
        if video_clip: video_clip.close()
        if intro_clip: intro_clip.close()
        if intro_final: intro_final.close()
        if final_video_before_audio: final_video_before_audio.close()
        if audio_clip: audio_clip.close()
        if final_video: final_video.close()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture", required=True)
    parser.add_argument("--intro", required=True)
    parser.add_argument("--audio", required=True)
    parser.add_argument("--output", default="short_final.mp4")
    args = parser.parse_args()
    
    assemble_video(args.capture, args.intro, args.audio, args.output)
