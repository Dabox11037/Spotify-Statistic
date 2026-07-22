import sqlite3
import json
import os
from datetime import datetime
from pathlib import Path
import sys

# === KONFIGURACJA ===
DB_PATH = 'staty.db'
DATA_FOLDER = 'data/spotify_history'   # ścieżka do folderu z JSON-ami
COMMIT_INTERVAL = 1000                 # commit co 1000 rekordów

# === POŁĄCZENIE Z BAZĄ ===
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# === FUNKCJE ===

def get_or_create_track(spotify_uri, title, artist, album):
    """
    Zwraca id utworu z tabeli tracks.
    Szuka po spotify_id, potem po tytule+artyście.
    Jeśli nie istnieje – tworzy nowy.
    """
    if spotify_uri:
        cursor.execute("SELECT id FROM tracks WHERE spotify_id = ?", (spotify_uri,))
        row = cursor.fetchone()
        if row:
            return row[0]

    cursor.execute("SELECT id FROM tracks WHERE title = ? AND artist = ?", (title, artist))
    row = cursor.fetchone()
    if row:
        return row[0]

    # Nowy utwór – tylko podstawowe pola (reszta NULL)
    cursor.execute('''
        INSERT INTO tracks (spotify_id, title, artist, album)
        VALUES (?, ?, ?, ?)
    ''', (spotify_uri, title, artist, album))
    return cursor.lastrowid

def parse_timestamp(ts_str):
    """Konwertuje timestamp Spotify (np. '2024-01-01T12:00:00Z') na datetime."""
    if not ts_str:
        return datetime.now()
    # Usuń Z i ew. strefę czasową
    ts_str = ts_str.replace('Z', '').replace('+00:00', '')
    if '.' in ts_str:
        ts_str = ts_str.split('.')[0]
    try:
        return datetime.fromisoformat(ts_str)
    except:
        return datetime.now()

def determine_status(skipped):
    """Zwraca status: SKIPPED jeśli True, w przeciwnym razie FULL."""
    return 'SKIPPED' if skipped else 'FULL'

def import_json_file(file_path):
    print(f"📂 Przetwarzam: {file_path.name}")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            print(f"   ⚠️ Błąd parsowania JSON – pomijam plik.")
            return 0, 0

    if not isinstance(data, list):
        print(f"   ⚠️ Oczekiwano listy, a jest {type(data)} – pomijam.")
        return 0, 0

    imported = 0
    skipped_records = 0

    for idx, entry in enumerate(data):
        try:
            # 1. Wymagane pola
            ts = entry.get('ts')
            ms_played = entry.get('ms_played', 0)
            if ms_played <= 0:
                skipped_records += 1
                continue

            track_name = entry.get('master_metadata_track_name')
            artist_name = entry.get('master_metadata_album_artist_name')
            album_name = entry.get('master_metadata_album_album_name')
            spotify_uri = entry.get('spotify_track_uri')
            skipped_flag = entry.get('skipped', False)

            # Pomijamy jeśli brak tytułu lub artysty
            if not track_name or not artist_name:
                skipped_records += 1
                continue

            # 2. Znajdź lub utwórz utwór
            track_id = get_or_create_track(spotify_uri, track_name, artist_name, album_name)

            # 3. Data odsłuchania
            played_at = parse_timestamp(ts)

            # 4. Status
            status = determine_status(skipped_flag)

            # 5. Wstaw odsłuchanie (tylko wymagane pola)
            cursor.execute('''
                INSERT INTO plays (track_id, played_at, played_ms, status)
                VALUES (?, ?, ?, ?)
            ''', (track_id, played_at, ms_played, status))

            imported += 1

        except Exception as e:
            print(f"   ⚠️ Błąd przetwarzania rekordu {idx}: {e}")
            skipped_records += 1
            continue

        # Commit co określoną liczbę rekordów
        if idx % COMMIT_INTERVAL == 0:
            conn.commit()
            print(f"   ... przetworzono {idx+1} rekordów (import: {imported}, pominięto: {skipped_records})")

    conn.commit()
    return imported, skipped_records

# === GŁÓWNA PĘTLA ===

def main():
    # Sprawdź czy folder istnieje
    if not os.path.exists(DATA_FOLDER):
        print(f"❌ Folder '{DATA_FOLDER}' nie istnieje.")
        print(f"   Utwórz go i umieść w nim pliki Streaming_History_Audio_*.json")
        conn.close()
        sys.exit(1)

    # Znajdź wszystkie pliki JSON spełniające wzorzec
    json_files = list(Path(DATA_FOLDER).glob('Streaming_History_Audio_*.json'))
    if not json_files:
        print(f"❌ W folderze '{DATA_FOLDER}' nie znaleziono plików pasujących do wzorca 'Streaming_History_Audio_*.json'")
        conn.close()
        sys.exit(1)

    print(f"🔍 Znaleziono {len(json_files)} plików do importu.\n")

    total_imported = 0
    total_skipped = 0

    for file in sorted(json_files):  # sortowanie chronologiczne
        imp, skip = import_json_file(file)
        total_imported += imp
        total_skipped += skip
        print(f"   ✅ Zakończono plik: import={imp}, pominięto={skip}\n")

    conn.close()

    print("\n🎉 Import zakończony!")
    print(f"   ✅ Poprawnie zaimportowano: {total_imported} odsłuchań")
    print(f"   ⏭️ Pominięto rekordów: {total_skipped}")

if __name__ == "__main__":
    main()