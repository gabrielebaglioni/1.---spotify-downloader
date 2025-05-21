# Spotify Downloader CLI

Questo progetto ti permette di scaricare brani da una playlist Spotify, mantenerne lo stato in un file JSON, aggiornare le copertine e formattare i file MP3 per l'importazione su iPod Classic.

## Setup

1. **Clona il repository**

   ```bash
   git clone https://<tuo-repo-url>.git spotify-downloader
   cd spotify-downloader
   ```

2. **Crea e attiva un ambiente virtuale**

   ```bash
   python3 -m venv venv
   source venv/bin/activate   # macOS/Linux
   venv\Scripts\activate    # Windows
   ```

3. **Installa le dipendenze**

   ```bash
   pip install -r requirements.txt
   ```

4. **Crea il file `.env`**

   Nella root del progetto, crea un file `.env` con le seguenti variabili:

   ```ini
   SPOTIFY_CLIENT_ID=<tuo_client_id>
   SPOTIFY_CLIENT_SECRET=<tuo_client_secret>
   PLAYLIST_URL=<url_playlist>
   DOWNLOAD_FOLDER=/percorso/assoluto/brani_preferiti
   STATE_FILE=/percorso/assoluto/brani.json
   ```

   * `SPOTIFY_CLIENT_ID` e `SPOTIFY_CLIENT_SECRET`: credenziali API di Spotify.
   * `PLAYLIST_URL`: URL della playlist Spotify.
   * `DOWNLOAD_FOLDER`: cartella dove salvare gli MP3.
   * `STATE_FILE`: file JSON per lo stato delle tracce.

## Comandi disponibili

Esegui sempre con:

```bash
python3 spotify_to_mp3.py <comando>
```

* **fetchPlaylist**
  Aggiorna (o crea) lo stato JSON con i brani della playlist. Aggiunge nuove tracce e aggiorna le cover URL per quelle esistenti.

* **sync**
  Scarica tutti i brani non ancora presenti in `DOWNLOAD_FOLDER` e aggiorna il flag `downloaded` nel JSON.

* **scan**
  Verifica la presenza dei file MP3 nella cartella e sincronizza il flag `downloaded` nel JSON.

* **updateMp3File**
  Per ogni traccia scaricata e con `cover_url`, inserisce la copertina nei tag ID3 se mancante.

* **formatForIpod**
  Prepara i tag ID3 (TIT2, TPE1, TALB e copertina) in modo compatibile con iPod Classic.

## Validazione formato

Dopo aver eseguito `formatForIpod`, puoi controllare i tag ID3 in due modi:

1. **Con id3v2** (su macOS installabile con Homebrew):

   ```bash
   brew install id3v2
   id3v2 -l "/percorso/assoluto/brani_preferiti/<file>.mp3"
   ```

2. **Con EyeD3** (cross-platform, installabile via pip):

   ```bash
   pip install eyeD3
   eyeD3 "/percorso/assoluto/brani_preferiti/<file>.mp3"
   ```

Per verificare frame specifici, puoi passare opzioni:

* `--print-image` per stampare informazioni sulla copertina.

Assicurati che:

* `TIT2`: titolo del brano
* `TPE1`: artista
* `TALB`: album
* `APIC`: cover frontale

Se tutti i frame sono presenti e valorizzati, il file è pronto per l'iPod Classic.
