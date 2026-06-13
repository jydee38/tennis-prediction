import os
import sys
import pickle
from google_auth_oauthlib.flow import InstalledAppFlow

# Configure UTF-8 stdout encoding for Windows
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request

# Le scope strict pour l'upload YouTube
SCOPES = ['https://www.googleapis.com/auth/youtube.upload']

def get_authenticated_service(secrets_path="json/client_secret.json"):
    """
    Authentifie l'utilisateur via OAuth 2.0.
    Sauvegarde le token pour éviter de se reconnecter à chaque fois.
    """
    credentials = None
    # Le chemin du token sera stocké à côté du secret
    token_path = os.path.join(os.path.dirname(secrets_path), "token.pickle")

    if os.path.exists(token_path):
        with open(token_path, 'rb') as token:
            credentials = pickle.load(token)
            
    # S'il n'y a pas de credentials valides, on lance le flux d'autorisation
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            print("[YouTube] Rafraîchissement du token d'accès...")
            credentials.refresh(Request())
        else:
            print("[YouTube] Ouverture du navigateur pour authentification OAuth...")
            if not os.path.exists(secrets_path):
                raise FileNotFoundError(f"Le fichier secret OAuth est introuvable : {secrets_path}")
                
            flow = InstalledAppFlow.from_client_secrets_file(secrets_path, SCOPES)
            # Port par défaut 0 = port aléatoire libre
            credentials = flow.run_local_server(port=0)
            
        # Sauvegarde pour la prochaine exécution
        with open(token_path, 'wb') as token:
            pickle.dump(credentials, token)

    print("[YouTube] ✅ Authentification réussie.")
    return build('youtube', 'v3', credentials=credentials)

def upload_short(service, video_path, title, description, privacy_status="unlisted"):
    """
    Pousse la vidéo sur YouTube avec les métadonnées spécifiques pour un Short de sport.
    """
    print(f"[YouTube] Préparation de l'upload pour '{video_path}'...")
    
    # Sécurité pour forcer le tag #shorts dans le titre
    if "#shorts" not in title.lower():
        title = f"{title} #shorts"

    body = {
        'snippet': {
            'title': title,
            'description': description,
            'tags': ['tennis', 'pronostic', 'atp', 'wta', 'betting'],
            'categoryId': '17'  # 17 = Sports
        },
        'status': {
            'privacyStatus': privacy_status,
            'selfDeclaredMadeForKids': False
        }
    }

    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype='video/mp4')
    
    request = service.videos().insert(
        part=','.join(body.keys()),
        body=body,
        media_body=media
    )

    print("[YouTube] 🚀 Envoi en cours (peut prendre plusieurs minutes)...")
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"[YouTube] Progression : {int(status.progress() * 100)}%")
            
    print(f"[YouTube] ✅ Vidéo importée avec succès ! ID de la vidéo : {response['id']}")
    return response['id']

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--desc", required=True)
    parser.add_argument("--secrets", default="json/client_secret.json")
    parser.add_argument("--privacy", default="unlisted", help="Privacy status: public, private, or unlisted")
    args = parser.parse_args()
    
    service = get_authenticated_service(args.secrets)
    upload_short(service, args.video, args.title, args.desc, privacy_status=args.privacy)
