#!/usr/bin/env python3
import os
import json
import sys

# —————— CONFIGURAZIONE ——————
# Metti qui il percorso al tuo file JSON
JSON_FILE   = '/Users/gabrielebaglioni/spotify-downloader/brani.json'
# Metti qui il percorso alla cartella con gli MP3
MP3_FOLDER  = '/Users/gabrielebaglioni/spotify-downloader/brani_preferiti'
# ————————————————————————————

def human_readable_size(size_bytes: int, decimals: int = 2) -> str:
    for unit in ['B','KB','MB','GB','TB']:
        if size_bytes < 1024.0 or unit == 'TB':
            return f"{size_bytes:.{decimals}f} {unit}"
        size_bytes /= 1024.0

def main():
    # Carica JSON
    try:
        with open(JSON_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"❌ Errore caricamento JSON: {e}")
        sys.exit(1)

    json_count = len(data)

    # Conta .mp3 e dimensioni
    try:
        files = [f for f in os.listdir(MP3_FOLDER) if f.lower().endswith('.mp3')]
    except Exception as e:
        print(f"❌ Errore accesso cartella MP3: {e}")
        sys.exit(1)

    file_count = len(files)
    total_bytes = 0
    for fn in files:
        fp = os.path.join(MP3_FOLDER, fn)
        try:
            total_bytes += os.path.getsize(fp)
        except OSError:
            pass

    print(f"📄 Record in JSON:    {json_count}")
    print(f"🎵 File .mp3 in cartella: {file_count}")
    print(f"💾 Dimensione totale: {total_bytes} byte ({human_readable_size(total_bytes)})")

if __name__ == '__main__':
    main()
