import sqlite3
import requests
import time
import logging
from config import LASTFM_API_KEY 

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

DB_PATH = "staty.db"
try:
    from config import LASTFM_API_KEY
except ImportError:
    LASTFM_API_KEY = None
    logging.error("Brak klucza API w config.py")
    exit(1)

def get_artist_genres(artist_name):
    """Pobiera gatunki dla artysty z Last.fm."""
    url = "http://ws.audioscrobbler.com/2.0/"
    params = {
        "method": "artist.getInfo",
        "artist": artist_name,
        "api_key": LASTFM_API_KEY,
        "format": "json"
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code != 200:
            return []
        data = response.json()
        tags = data.get('artist', {}).get('tags', {}).get('tag', [])
        # Zwróć nazwy tagów (maksymalnie 5 najbardziej popularnych)
        return [tag['name'].lower() for tag in tags[:5]]
    except Exception as e:
        logger.error(f"Błąd dla {artist_name}: {e}")
        return []

def update_genres():
    """Pobiera wszystkich artystów z tracks i uzupełnia gatunki."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Pobierz wszystkich unikalnych artystów z tabeli tracks
    cursor.execute("SELECT DISTINCT artist FROM tracks WHERE artist IS NOT NULL AND artist != ''")
    artists = [row[0] for row in cursor.fetchall()]

    # Dla każdego artysty sprawdź, czy już ma gatunki w bazie
    for artist in artists:
        cursor.execute("SELECT 1 FROM artist_genres WHERE artist = ? LIMIT 1", (artist,))
        if cursor.fetchone():
            logger.info(f"⏩ Pomijam {artist} – już istnieje")
            continue

        logger.info(f"🔍 Pobieram gatunki dla: {artist}")
        genres = get_artist_genres(artist)

        if genres:
            for genre in genres:
                cursor.execute("INSERT INTO artist_genres (artist, genre) VALUES (?, ?)", (artist, genre))
            conn.commit()
            logger.info(f"✅ {artist}: {', '.join(genres)}")
        else:
            logger.warning(f"⚠️ Brak gatunków dla {artist}")

        # Opóźnienie, aby nie przeciążać API (Last.fm ma limit 5 zapytań/s)
        time.sleep(1)

    conn.close()
    logger.info("🎉 Zakończono aktualizację gatunków.")

if __name__ == "__main__":
    update_genres()