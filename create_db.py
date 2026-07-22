import sqlite3
import os

# Nazwa pliku bazy danych
DB_NAME = 'staty.db'

# Połączenie (jeśli plik nie istnieje, zostanie automatycznie utworzony)
conn = sqlite3.connect(DB_NAME)
cursor = conn.cursor()

# Włączamy obsługę kluczy obcych (dobra praktyka)
cursor.execute("PRAGMA foreign_keys = ON;")

# --- Tworzenie tabel (twój schemat, ale bez tabeli artists) ---

# 1. Tabela utworów

cursor.execute('''
CREATE TABLE IF NOT EXISTS artist_genres (
    artist TEXT NOT NULL,
    genre TEXT NOT NULL,
    PRIMARY KEY (artist, genre)
);
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    spotify_id TEXT UNIQUE,        -- URI lub ID z Spotify
    title TEXT NOT NULL,
    artist TEXT NOT NULL,
    album TEXT,
    duration_ms INTEGER,           -- całkowita długość w ms
    genre TEXT,                    -- opcjonalnie, możesz później dodać
    image_url TEXT                 -- okładka (link URL)
)
''')

# 2. Tabela odsłuchań
cursor.execute('''
CREATE TABLE IF NOT EXISTS plays (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id INTEGER NOT NULL,
    played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    played_ms INTEGER,              -- ile milisekund faktycznie odsłuchano
    status TEXT CHECK(status IN ('FULL','PARTIAL','SKIPPED')),
    FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    track_id INTEGER NOT NULL,

    started_at TIMESTAMP,

    last_progress INTEGER DEFAULT 0,

    duration_ms INTEGER,

    FOREIGN KEY(track_id) REFERENCES tracks(id)
);
''')

# Zatwierdzenie zmian i zamknięcie połączenia
conn.commit()
conn.close()

print(f"✅ Baza danych '{DB_NAME}' została utworzona pomyślnie!")
print("📁 Znajdziesz ją w folderze:", os.path.abspath(DB_NAME))
print("\nTabele w bazie:")
print(" - tracks (utwory)")
print(" - plays (odsłuchania)")