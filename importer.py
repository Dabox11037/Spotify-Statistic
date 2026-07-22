import sqlite3
import json
import os
from datetime import datetime
from pathlib import Path

# --- KONFIGURACJA ---
DB_PATH = 'staty.db'
DATA_FOLDER = 'data'   # folder, w którym leży Twój JSON

# --- POŁĄCZENIE ---
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()
cursor.execute("PRAGMA foreign_keys = ON;")

# --- FUNKCJE ---
def get_or_create_track(spotify_id, title, artist, album, duration_ms, image_url=None):
    """Znajduje utwór po URI lub tytule+artyście, jeśli nie istnieje – dodaje."""
    if spotify_id:
        cursor.execute("SELECT id FROM tracks WHERE spotify_id = ?", (spotify_id,))
        row = cursor.fetchone()
        if row:
            return row[0]

    # Szukaj po tytule i artyście (na wypadek braku URI)
    cursor.execute("SELECT id FROM tracks WHERE title = ? AND artist = ?", (title, artist))
    row = cursor.fetchone()
    if row:
        return row[0]

    # Dodajemy nowy
    cursor.execute('''
        INSERT INTO tracks (spotify_id, title, artist, album, duration_ms, image_url)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (spotify_id, title, artist, album, duration_ms, image_url))
    return cursor.lastrowid

def import_json_file(file_path):
    print(f"📂 Przetwarzam: {file_path}")
    with open(file_path, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            print(f"   ⚠️ Plik {file_path} nie jest poprawnym JSON – pomijam.")
            return

    if not isinstance(data, list):
        print(f"   ⚠️ Oczekiwano listy, a jest {type(data)} – pomijam.")
        return

    for idx, entry in enumerate(data):
        # --- Wyciąganie danych ---
        spotify_uri = entry.get('uri')
        if spotify_uri and spotify_uri.startswith('spotify:track:'):
            spotify_id = spotify_uri
        else:
            spotify_id = None

        title = entry.get('name')
        if not title:
            continue

        artists = entry.get('artists', [])
        artist_name = artists[0].get('name') if artists else None
        if not artist_name:
            continue

        album_obj = entry.get('album', {})
        album_name = album_obj.get('name')

        duration_obj = entry.get('duration', {})
        duration_ms = duration_obj.get('milliseconds')

        # Data – listenDate to timestamp w ms
        listen_timestamp_ms = entry.get('listenDate')
        if listen_timestamp_ms:
            played_at = datetime.fromtimestamp(listen_timestamp_ms / 1000.0)
        else:
            played_at = datetime.now()

        # Obrazek (bierzemy standardowy)
        images = entry.get('images', [])
        image_url = None
        for img in images:
            if img.get('label') == 'standard':
                image_url = img.get('url')
                break
        if not image_url and images:
            image_url = images[0].get('url')

        played_ms = duration_ms if duration_ms else 0
        if played_ms < 5000:   # pomijamy krótsze niż 5s (np. błędy)
            continue

        # --- Dodaj utwór i odsłuchanie ---
        track_id = get_or_create_track(spotify_id, title, artist_name, album_name, duration_ms, image_url)

        cursor.execute('''
            INSERT INTO plays (track_id, played_at, played_ms, status)
            VALUES (?, ?, ?, ?)
        ''', (track_id, played_at, played_ms, 'FULL'))

        if idx % 500 == 0:
            conn.commit()

    conn.commit()
    print(f"   ✅ Dodano rekordy z pliku {os.path.basename(file_path)}")

# --- GŁÓWNA PĘTLA ---
if not os.path.exists(DATA_FOLDER):
    print(f"❌ Folder '{DATA_FOLDER}' nie istnieje!")
    conn.close()
    exit()

json_files = list(Path(DATA_FOLDER).rglob('*.json'))
if not json_files:
    print(f"❌ W folderze '{DATA_FOLDER}' nie znaleziono żadnych plików .json")
    conn.close()
    exit()

print(f"🔍 Znaleziono {len(json_files)} plików JSON.")
for file in json_files:
    import_json_file(file)

conn.close()
print("\n🎉 Import zakończony!")