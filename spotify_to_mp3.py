#!/usr/bin/env python3
import os
import time
import json
import unicodedata
import argparse
import re
import difflib
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import yt_dlp
from dotenv import load_dotenv
from rapidfuzz.fuzz import partial_ratio, token_set_ratio, token_sort_ratio

# === CONFIGURAZIONE ===
load_dotenv()
SPOTIFY_CLIENT_ID     = os.getenv('SPOTIFY_CLIENT_ID')
SPOTIFY_CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET')
PLAYLIST_URL          = os.getenv('PLAYLIST_URL')
DOWNLOAD_FOLDER       = os.getenv('DOWNLOAD_FOLDER')
STATE_FILE            = os.getenv('STATE_FILE')

if not all([SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, PLAYLIST_URL, DOWNLOAD_FOLDER, STATE_FILE]):
    print("❌ Errore: verifica variabili d'ambiente nel file .env")
    exit(1)

os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# === SPOTIFY AUTH ===
sp = spotipy.Spotify(
    client_credentials_manager=SpotifyClientCredentials(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET
    )
)

# === UTILITIES ===
def normalizza(s: str) -> str:
    s = unicodedata.normalize('NFKD', s)
    s = re.sub(r"\([^)]*\)", "", s)                   # rimuove parentesi e contenuto
    s = s.encode('ASCII', 'ignore').decode('utf-8')   # to ASCII
    s = s.lower()
    s = re.sub(r'[^a-z0-9 ]+', '', s)                 # solo lettere, numeri, spazi
    return re.sub(r'\s+', ' ', s).strip()

# === FETCH PLAYLIST ===
def fetch_playlist() -> list:
    tracks, offset = [], 0
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
                tracks.append({
                    'title'     : t.get('name', ''),
                    'artist'    : ', '.join(a['name'] for a in t.get('artists', [])),
                    'album'     : t.get('album', {}).get('name', ''),
                    'downloaded': False
                })
            offset += len(items)
            if offset >= resp.get('total', 0):
                break
    except Exception as e:
        print(f"❌ Errore fetch playlist: {e}")
        exit(1)
    return tracks

# === STATE ===
def load_state() -> tuple:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f), False
    state = fetch_playlist()
    save_state(state)
    return state, True

def save_state(state: list) -> None:
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

# === DOWNLOAD MP3 ===
def download_mp3(rec: dict) -> bool:
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
        'postprocessors': [{'key': 'FFmpegExtractAudio',
                            'preferredcodec': 'mp3',
                            'preferredquality': '0'}]
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([f"ytsearch1:{query}"])
        return success
    except Exception as e:
        print(f"❌ Errore download '{rec['title']}': {e}")
        return False

# === SCAN LOGICA AVANZATA ===
def scan_folder(records: list, download_folder: str) -> None:
    # carica tutti i file .mp3 e normalizza il nome (escludendo chiavi troppo corte)
    files = [f for f in os.listdir(download_folder) if f.lower().endswith('.mp3')]
    norm_files = {}
    for f in files:
        k = normalizza(os.path.splitext(f)[0])
        if len(k) > 2:
            norm_files[k] = f

    changed = False
    for rec in records:
        title_key  = normalizza(rec['title'])
        full_key   = normalizza(f"{rec['artist']} {rec['title']}")
        # prendi il primo artista per il title-only fallback
        artist_key = normalizza(rec['artist'].split(',')[0])

        matched, best_score = None, 0.0

        # 1) exact match su artist+title
        if full_key in norm_files:
            matched, best_score = norm_files[full_key], 1.0
        else:
            # 2) substring su full_key
            for k, fname in norm_files.items():
                if full_key and (full_key in k or k in full_key):
                    matched, best_score = fname, 1.0
                    break

        # 3) fuzzy su full_key
        if not matched:
            for k, fname in norm_files.items():
                scores = [
                    token_set_ratio(full_key, k) / 100,
                    token_sort_ratio(full_key, k) / 100,
                    partial_ratio(full_key, k) / 100,
                    difflib.SequenceMatcher(None, full_key, k).ratio()
                ]
                s = max(scores)
                if s > best_score:
                    matched, best_score = fname, s

        # 4) fallback fuzzy solo su title, **richiedendo** che nel filename compaia artist_key
        if not matched or best_score < 0.90:
            for k, fname in norm_files.items():
                # serve un buon titolo e l'artista nel nome
                if artist_key in k:
                    s = max(
                        token_set_ratio(title_key, k) / 100,
                        token_sort_ratio(title_key, k) / 100,
                        partial_ratio(title_key, k) / 100,
                        difflib.SequenceMatcher(None, title_key, k).ratio()
                    )
                    if s > best_score:
                        matched, best_score = fname, s

        exists = bool(matched and best_score >= 0.90)
        icon = '✅' if exists else '❌'
        print(f"Scan: title='{rec['title']}' vs file='{matched or 'None'}' -> score={best_score:.2f} {icon}")

        if rec.get('downloaded') != exists:
            rec['downloaded'] = exists
            changed = True

    if changed:
        save_state(records)
        print("Scan completato: JSON aggiornato.")
    else:
        print("Scan completato: nessuna modifica.")

# === MAIN ===
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Spotify Downloader CLI')
    parser.add_argument('command', nargs='?', choices=['sync', 'scan'], default='sync',
                        help='sync: scarica; scan: verifica folder vs JSON')
    args = parser.parse_args()

    records, is_new = load_state()
    if is_new:
        print(f"Nuovo JSON con {len(records)} record.")
        if args.command == 'sync' and input("Procedere al download? (s/n): ").strip().lower() != 's':
            exit(0)

    if args.command == 'scan':
        scan_folder(records, DOWNLOAD_FOLDER)
        exit(0)

    # sync: download massivo
    pending = [r for r in records if not r.get('downloaded')]
    total = len(pending)
    print(f"Download massivo: {total} brani.")
    for i, rec in enumerate(pending, 1):
        pct = (i / total) * 100
        print(f"[{i}/{total}] ({pct:.1f}%) Scarico: {rec['title']}")
        ok = download_mp3(rec)
        rec['downloaded'] = ok
        print("  ✅" if ok else "  ⚠️", rec['title'])
        save_state(records)
        time.sleep(1)
    print("Sync completato.")
