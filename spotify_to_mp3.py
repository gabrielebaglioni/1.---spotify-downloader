import os
import time
import json
import unicodedata
import argparse
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import yt_dlp
from dotenv import load_dotenv

# === CONFIGURAZIONE ===

# Load environment variables
load_dotenv()
# Credenziali Spotify (hardcoded)
SPOTIFY_CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID')
SPOTIFY_CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET')
PLAYLIST_URL = os.getenv('PLAYLIST_URL')
DOWNLOAD_FOLDER = os.getenv('DOWNLOAD_FOLDER')
STATE_FILE = os.getenv('STATE_FILE')

# Crea la cartella di download
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# === AUTENTICAZIONE SPOTIFY ===
sp = spotipy.Spotify(
    client_credentials_manager=SpotifyClientCredentials(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET
    )
)

# === UTILITIES ===
def normalizza(s):
    s = unicodedata.normalize('NFKD', s)
    s = s.encode('ASCII', 'ignore').decode('utf-8')
    return s.lower().replace('&', 'and').replace("’", "'").strip()

# === FETCH PLAYLIST ===

def fetch_playlist():
    tracks = []
    offset = 0
    try:
        while True:
            resp = sp.playlist_items(
                PLAYLIST_URL,
                offset=offset,
                fields='items.track.name,items.track.artists.name,items.track.album.name,total',
                additional_types=['track'],
                limit=100
            )
            items = resp.get('items', [])
            if not items:
                break
            for it in items:
                t = it.get('track') or {}
                title = t.get('name', '')
                album = t.get('album', {}).get('name', '')
                artists = [a['name'] for a in t.get('artists', [])]
                tracks.append({
                    'title': title,
                    'artist': ', '.join(artists),
                    'album': album,
                    'downloaded': False
                })
            offset += len(items)
            if offset >= resp.get('total', 0):
                break
    except Exception as e:
        print(f"❌ Errore durante fetch playlist: {e}")
        print("Verifica che CLIENT_ID e CLIENT_SECRET siano corretti.")
        exit(1)
    return tracks

# === STATO ===
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f), False
    state = fetch_playlist()
    save_state(state)
    return state, True

def save_state(state):
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

# === DOWNLOAD MP3 ===
def download_mp3(rec):
    query = f"{rec['artist']} - {rec['title']}"
    success = False
    def hook(d):
        nonlocal success
        if d.get('status') == 'finished':
            success = True
    opts = {
        'format': 'bestaudio/best',
        'noplaylist': True,
        'quiet': True,
        'cookiesfrombrowser': ('chrome',),
        'outtmpl': os.path.join(DOWNLOAD_FOLDER, '%(title)s.%(ext)s'),
        'progress_hooks': [hook],
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '0'
        }]
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([f"ytsearch1:{query}"])
        return success
    except Exception as e:
        print(f"❌ Errore '{rec['title']}': {e}")
        return False

# === MAIN ===
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Spotify Downloader CLI')
    parser.add_argument(
        'command',
        nargs='?',
        choices=['sync', 'scan'],
        default='sync',
        help='sync: aggiorna JSON e scarica; scan: verifica cartella vs JSON'
    )
    args = parser.parse_args()

    # Carica o inizializza stato
    records, is_new = load_state()
    if is_new:
        print(f"Nuovo JSON creato con {len(records)} record.")
        if args.command == 'sync' and input("Procedere al download? (s/n): ").strip().lower() != 's':
            print("Uscita.")
            exit()

    # scan: verifica coerenza tra file e stato
    if args.command == 'scan':
        files = [f for f in os.listdir(DOWNLOAD_FOLDER) if f.lower().endswith('.mp3')]
        norm_files = {normalizza(os.path.splitext(f)[0]) for f in files}
        changed = False
        for rec in records:
            key = normalizza(f"{rec['artist']} - {rec['title']}")
            exists = key in norm_files
            if rec.get('downloaded') != exists:
                rec['downloaded'] = exists
                changed = True
        if changed:
            save_state(records)
            print("Scan completato: JSON aggiornato.")
        else:
            print("Scan completato: nessuna modifica.")
        exit()

    # sync: download massivo di record non ancora scaricati
    pending = [r for r in records if not r.get('downloaded')]
    total = len(pending)
    print(f"Download massivo: {total} brani da processare.")
    for i, rec in enumerate(pending, 1):
        pct = (i / total) * 100
        print(f"[{i}/{total}] ({pct:.2f}%) Scarico: {rec['artist']} - {rec['title']}")
        ok = download_mp3(rec)
        if ok:
            rec['downloaded'] = True
            print(f"  ✅ {rec['title']}")
        else:
            print(f"  ⚠️ {rec['title']} fallito")
        save_state(records)
        time.sleep(1)
    print("Sync completato. JSON aggiornato.")
