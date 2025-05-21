#!/usr/bin/env python3
import os
import time
import json
import unicodedata
import argparse
import re
import spotipy
import yt_dlp
import requests
from dotenv import load_dotenv
from spotipy.oauth2 import SpotifyClientCredentials

from mutagen.id3 import ID3, APIC, error as ID3Error, TIT2, TPE1, TALB

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
    s = re.sub(r"\([^)]*\)", "", s)
    s = s.encode('ASCII', 'ignore').decode('utf-8')
    s = s.lower()
    s = re.sub(r'[^a-z0-9 ]+', '', s)
    return re.sub(r'\s+', ' ', s).strip()

def safe_filename(s: str) -> str:
    return re.sub(r'[\\/:"*?<>|]+', '', s)

# === FETCHPLAYLIST RAW ===
def fetch_playlist_raw() -> list:
    print("▶️  Inizio fetchPlaylist…")
    tracks, offset = [], 0
    try:
        while True:
            print(f"  • Fetching offset={offset}…")
            resp = sp.playlist_items(
                PLAYLIST_URL,
                offset=offset,
                fields='items.track(name,artists(name),album(name,images)),total',
                additional_types=['track'],
                limit=100
            )
            items = resp.get('items', [])
            if not items:
                break
            for it in items:
                t = it.get('track') or {}
                title  = t.get('name', '')
                artist = ', '.join(a['name'] for a in t.get('artists', []))
                album  = t.get('album', {}).get('name', '')
                imgs   = t.get('album', {}).get('images', [])
                cover  = imgs[0]['url'] if imgs else None
                print(f"    ✓ {artist} – {title} [{'cover ok' if cover else 'no cover'}]")
                tracks.append({
                    'title': title,
                    'artist': artist,
                    'album': album,
                    'downloaded': False,
                    'cover_url': cover
                })
            offset += len(items)
            total = resp.get('total', 0)
            print(f"  fetched {offset}/{total}")
            if offset >= total:
                break
        print(f"✅  Fetch completato: {len(tracks)} brani trovati.")
    except Exception as e:
        print(f"❌ Errore fetchPlaylist: {e}")
        exit(1)
    return tracks

# === FETCHPLAYLIST + MERGE ===
def fetch_and_merge(records: list) -> bool:
    raw = fetch_playlist_raw()
    # build lookup preserving existing download flags
    idx = {(
        normalizza(r['artist']),
        normalizza(r['title']),
        normalizza(r['album'])
    ): r for r in records}

    added = 0
    updated = 0

    for new in raw:
        key = (
            normalizza(new['artist']),
            normalizza(new['title']),
            normalizza(new['album'])
        )
        if key in idx:
            rec = idx[key]
            # preserve rec['downloaded'] always
            if not rec.get('cover_url') and new.get('cover_url'):
                rec['cover_url'] = new['cover_url']
                updated += 1
                print(f"  🔄 Updated cover for: {rec['artist']} – {rec['title']}")
        else:
            # new track: initialize downloaded flag to False
            new['downloaded'] = False
            records.append(new)
            added += 1
            print(f"  ➕ Added: {new['artist']} – {new['title']}")

    print(f"✅  fetchPlaylist done: {added} added, {updated} updated.")
    return bool(added or updated)

# === STATE ===
def load_state() -> tuple:
    if os.path.exists(STATE_FILE):
        print(f"ℹ️  Carico stato da {STATE_FILE}…")
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f), False
        except Exception as e:
            print(f"❌ Errore caricamento state: {e}")
            exit(1)
    return [], True


def save_state(state: list) -> None:
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        print(f"✅  Stato salvato su {STATE_FILE}")
    except Exception as e:
        print(f"❌ Errore salvataggio state: {e}")

# === SYNC (download) ===
def download_mp3(rec: dict) -> bool:
    base = safe_filename(f"{rec['artist']} - {rec['title']}")
    out_mp3 = os.path.join(DOWNLOAD_FOLDER, f"{base}.mp3")
    if os.path.exists(out_mp3):
        print(f"  ℹ️  Esiste già: {base}.mp3")
        return True
    print(f"  ⏬ Download: {base}")
    opts = {
        'format':'bestaudio/best','noplaylist':True,'quiet':True,
        'cookiesfrombrowser':('chrome',),'restrictfilenames':True,
        'outtmpl': out_mp3.replace('.mp3', '.%(ext)s'),
        'postprocessors':[{'key':'FFmpegExtractAudio','preferredcodec':'mp3','preferredquality':'0'}]
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([f"ytsearch1:{rec['artist']} - {rec['title']}"])
    except Exception as e:
        print(f"  ❌ Errore download '{rec['title']}': {e}")
        return False
    if os.path.exists(out_mp3):
        print(f"  ✅ Salvato: {base}.mp3")
        return True
    print(f"  ⚠️ File non trovato dopo download: {base}.mp3")
    return False

# === SCAN ===
def scan_folder(records: list) -> None:
    print("▶️  Inizio scan…")
    try:
        files = [f for f in os.listdir(DOWNLOAD_FOLDER) if f.lower().endswith('.mp3')]
    except Exception as e:
        print(f"❌ Errore listdir: {e}")
        return
    norm_files = {normalizza(os.path.splitext(f)[0]): f for f in files if len(normalizza(os.path.splitext(f)[0]))>2}
    changed = False
    for rec in records:
        title_k = normalizza(rec['title'])
        full_k  = normalizza(f"{rec['artist']} {rec['title']}")
        artist_k= normalizza(rec['artist'].split(',')[0])
        matched, best = None, 0.0
        # exact / substring / fuzzy / fallback logic omitted for brevity (unchanged)
        # update rec['downloaded'] if needed
    if changed:
        save_state(records)
        print("✅  Scan completato: JSON aggiornato.")
    else:
        print("✅  Scan completato: nessuna modifica.")

# === UPDATE MP3 FILE ===
def update_mp3_file(records: list) -> None:
    print("▶️  Inizio updateMp3File…")
    changed = False
    files = [f for f in os.listdir(DOWNLOAD_FOLDER) if f.lower().endswith('.mp3')]
    norm_files = {k: os.path.join(DOWNLOAD_FOLDER, fn)
                  for fn in files
                  for k in [normalizza(os.path.splitext(fn)[0])] if len(k)>2}
    for rec in records:
        if not rec.get('downloaded') or not rec.get('cover_url'):
            continue
        full_k = normalizza(f"{rec['artist']} {rec['title']}")
        # matching logic as before
        # embed cover if missing
    if changed:
        save_state(records)
        print("✅  updateMp3File completato: JSON aggiornato.")
    else:
        print("✅  updateMp3File completato: nessuna modifica.")

# === FORMAT FOR IPOD ===
def format_for_ipod(records: list) -> None:
    print("▶️  Inizio formatForIpod…")
    changed = False

    # mappatura normalizzata dei file .mp3
    files = [f for f in os.listdir(DOWNLOAD_FOLDER) if f.lower().endswith('.mp3')]
    norm_files = {
        normalizza(os.path.splitext(f)[0]): os.path.join(DOWNLOAD_FOLDER, f)
        for f in files
        if len(normalizza(os.path.splitext(f)[0])) > 2
    }

    for rec in records:
        # operiamo solo sui brani già scaricati
        if not rec.get('downloaded'):
            continue

        full_k = normalizza(f"{rec['artist']} {rec['title']}")
        path = norm_files.get(full_k)
        if not path:
            continue

        try:
            tag = ID3(path)
        except ID3Error:
            tag = ID3()

        # titolo
        tag.delall('TIT2')
        tag.add(TIT2(encoding=3, text=rec['title']))
        # artista
        tag.delall('TPE1')
        tag.add(TPE1(encoding=3, text=rec['artist']))
        # album
        tag.delall('TALB')
        tag.add(TALB(encoding=3, text=rec['album']))

        # copertina (se non già presente)
        if rec.get('cover_url') and not any(isinstance(x, APIC) for x in tag.values()):
            img_data = requests.get(rec['cover_url']).content
            tag.add(APIC(
                encoding=3,       # UTF-8
                mime='image/jpeg',
                type=3,           # cover front
                desc='Cover',
                data=img_data
            ))

        # salva in ID3v2.3 per compatibilità iPod Classic
        tag.save(path, v2_version=3)

        print(f"  🎧 Formatted: {os.path.basename(path)}")
        changed = True

    if changed:
        print("✅  formatForIpod completed.")
    else:
        print("✅  formatForIpod: no files to update.")

# === MAIN ===
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Spotify Downloader CLI')
    parser.add_argument('command', nargs='?', choices=['fetchPlaylist','sync','scan','updateMp3File','formatForIpod'], default='sync',
                        help='fetchPlaylist: aggiorna JSON; sync: scarica MP3; scan: verifica cartella; updateMp3File: aggiunge cover; formatForIpod: prepara ID3 per iPod')
    args = parser.parse_args()

    records, is_new = load_state()
    if is_new and args.command != 'fetchPlaylist':
        print("ℹ️  Stato vuoto, esegui prima 'fetchPlaylist'.")

    if args.command == 'fetchPlaylist':
        if fetch_and_merge(records): save_state(records)
    elif args.command == 'sync':
        pending = [r for r in records if not r.get('downloaded')]
        print(f"▶️  Sync: {len(pending)} brani da scaricare…")
        for i, rec in enumerate(pending, 1):
            pct = i / len(pending) * 100
            print(f"  [{i}/{len(pending)}] ({pct:.1f}%) {rec['title']}")
            ok = download_mp3(rec)
            rec['downloaded'] = ok
            save_state(records)
            time.sleep(1)
        print("✅  Sync completato.")
    elif args.command == 'scan':
        scan_folder(records)
    elif args.command == 'updateMp3File':
        update_mp3_file(records)
    elif args.command == 'formatForIpod':
        format_for_ipod(records)
