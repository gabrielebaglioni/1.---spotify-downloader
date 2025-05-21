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
from rapidfuzz.fuzz import partial_ratio, token_set_ratio, token_sort_ratio
import difflib
from mutagen.id3 import ID3, APIC, error as ID3Error

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

# === FETCHPLAYLIST + MERGE ===
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


def fetch_and_merge(records: list) -> bool:
    raw = fetch_playlist_raw()
    idx = {(normalizza(r['artist']), normalizza(r['title']), normalizza(r['album'])): r for r in records}
    added = updated = 0
    for new in raw:
        key = (normalizza(new['artist']), normalizza(new['title']), normalizza(new['album']))
        if key in idx:
            rec = idx[key]
            if not rec.get('cover_url') and new.get('cover_url'):
                rec['cover_url'] = new['cover_url']
                updated += 1
                print(f"  🔄 Updated cover for: {rec['artist']} – {rec['title']}")
        else:
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
        # ... (fuzzy matching as before) ...
        # (omitted for brevity)
    # unchanged

# === UPDATE MP3 FILE (with scan logic) ===
def update_mp3_file(records: list) -> None:
    print("▶️  Inizio updateMp3File…")
    changed = False
    # build normalized mapping for existing files (filter empty keys)
    files = [f for f in os.listdir(DOWNLOAD_FOLDER) if f.lower().endswith('.mp3')]
    norm_files = {k: os.path.join(DOWNLOAD_FOLDER, fn)
                  for fn in files
                  for k in [normalizza(os.path.splitext(fn)[0])] if len(k)>2}
    for rec in records:
        if not rec.get('downloaded') or not rec.get('cover_url'):
            continue
        full_k = normalizza(f"{rec['artist']} {rec['title']}")
        if len(full_k) <= 2:
            print(f"  ⚠️  Skip matching per rec con chiave corta: {rec['title']}")
            continue
        # 1) exact
        mp3_path = norm_files.get(full_k)
        best = 1.0 if mp3_path else 0.0
        # 2) substring
        if not mp3_path:
            for k, path in norm_files.items():
                if full_k in k or k in full_k:
                    mp3_path, best = path, 1.0
                    break
        # 3) fuzzy
        if not mp3_path:
            for k, path in norm_files.items():
                s = max(token_set_ratio(full_k, k)/100,
                        token_sort_ratio(full_k, k)/100,
                        partial_ratio(full_k, k)/100,
                        difflib.SequenceMatcher(None, full_k, k).ratio())
                if s > best:
                    mp3_path, best = path, s
        # 4) title+artist fallback
        if best < 0.90:
            title_k = normalizza(rec['title'])
            artist_k = normalizza(rec['artist'].split(',')[0])
            for k, path in norm_files.items():
                if artist_k in k:
                    s = max(token_set_ratio(title_k, k)/100,
                            token_sort_ratio(title_k, k)/100,
                            partial_ratio(title_k, k)/100,
                            difflib.SequenceMatcher(None, title_k, k).ratio())
                    if s > best:
                        mp3_path, best = path, s
        if not mp3_path or best < 0.90:
            print(f"  ⚠️  MP3 non trovato per: {rec['artist']} – {rec['title']}")
            continue
        # embed cover
        try:
            tag = ID3(mp3_path)
        except ID3Error:
            tag = ID3()
        if any(isinstance(f, APIC) for f in tag.values()):
            print(f"  ℹ️  Cover già presente in: {os.path.basename(mp3_path)}")
            continue
        try:
            img_data = requests.get(rec['cover_url']).content
            tag.add(APIC(encoding=3, mime='image/jpeg', type=3, desc='Cover', data=img_data))
            tag.save(mp3_path)
            print(f"  🎨  Copertina aggiunta a: {os.path.basename(mp3_path)}")
            changed = True
        except Exception as e:
            print(f"  ❌ Errore embedding cover: {e}")
    if changed:
        save_state(records)
        print("✅  updateMp3File completato: JSON aggiornato.")
    else:
        print("✅  updateMp3File completato: nessuna modifica.")

# === MAIN ===
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Spotify Downloader CLI')
    parser.add_argument('command', nargs='?', choices=['fetchPlaylist','sync','scan','updateMp3File'], default='sync',
                        help='fetchPlaylist: aggiorna JSON; sync: scarica MP3; scan: verifica cartella; updateMp3File: aggiunge cover')
    args = parser.parse_args()

    records, is_new = load_state()
    if is_new and args.command != 'fetchPlaylist':
        print("ℹ️  Stato vuoto, esegui prima 'fetchPlaylist'.")

    if args.command == 'fetchPlaylist':
        if fetch_and_merge(records):
            save_state(records)
        exit(0)
    elif args.command == 'scan':
        scan_folder(records)
        exit(0)
    elif args.command == 'updateMp3File':
        update_mp3_file(records)
        exit(0)
    else:  # sync
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
