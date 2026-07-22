from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import sqlite3
from datetime import datetime, timedelta
import json
import logging
from contextlib import contextmanager
import time

app = Flask(__name__)
CORS(app)

DB_PATH = "staty.db"

# Konfiguracja logowania
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Wycisz logi HTTP (werkzeug) – zostaw tylko błędy
werkzeug_logger = logging.getLogger('werkzeug')
werkzeug_logger.setLevel(logging.ERROR)

# --------------------------------------------------
# PAMIĘĆ PODRĘCZNA DLA "TERAZ GRAM" (NIE W BAZIE)
# --------------------------------------------------
current_track_cache = {
    'image_url': None,
    'title': None,
    'artist': None,
    'album': None,
    'uri': None,
    'duration_ms': 0,
    'progress_ms': 0,
    'playing': False,
    'track_id': None,          # id z tabeli tracks
    'last_update': None,       # timestamp ostatniego progresu
}

# --------------------------------------------------
# KONTEXT MANAGER DLA POŁĄCZEŃ Z BAZĄ
# --------------------------------------------------
@contextmanager
def get_db_connection():
    conn = sqlite3.connect(
        DB_PATH,
        timeout=20,  # dłuższy timeout na wypadek blokad
        detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
    )
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")  # 30s oczekiwania na odblokowanie
    try:
        yield conn
    except Exception as e:
        conn.rollback()
        logger.error(f"Błąd bazy: {e}")
        raise
    finally:
        conn.close()

# --------------------------------------------------
# POMOCNICZE: get_or_create_track
# --------------------------------------------------
def get_or_create_track(spotify_id, title, artist, album=None, duration_ms=None):
    """
    Znajduje utwór po spotify_id lub tytule+artyście.
    Jeśli nie istnieje – tworzy nowy rekord w tabeli tracks.
    Zwraca id utworu.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if spotify_id:
            cursor.execute("SELECT id FROM tracks WHERE spotify_id = ?", (spotify_id,))
            row = cursor.fetchone()
            if row:
                return row[0]

        cursor.execute("SELECT id FROM tracks WHERE title = ? AND artist = ?", (title, artist))
        row = cursor.fetchone()
        if row:
            return row[0]

        cursor.execute('''
            INSERT INTO tracks (spotify_id, title, artist, album, duration_ms)
            VALUES (?, ?, ?, ?, ?)
        ''', (spotify_id, title, artist, album, duration_ms))
        conn.commit()
        return cursor.lastrowid

# --------------------------------------------------
# POMOCNICZE – filtrowanie po okresie
# --------------------------------------------------
def get_period_filter(period):
    now = datetime.now()
    if period == 'day':
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == 'week':
        start = now - timedelta(days=now.weekday())
        return start.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == 'month':
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:  # all
        return None

def apply_period_to_query(query, period, has_where=False):
    start = get_period_filter(period)
    if start:
        if has_where:
            return query + " AND p.played_at >= ?", [start]
        else:
            return query + " WHERE p.played_at >= ?", [start]
    return query, []

# --------------------------------------------------
# ENDPOINTY STATYSTYK
# --------------------------------------------------

@app.route('/stats/overview', methods=['GET'])
def stats_overview():
    period = request.args.get('period', 'all')
    with get_db_connection() as conn:
        cursor = conn.cursor()
        base_query = "FROM plays p JOIN tracks t ON p.track_id = t.id"
        query, params = apply_period_to_query(
            f"SELECT SUM(played_ms)/1000.0 {base_query}", period, has_where=False
        )
        cursor.execute(query, params)
        total_seconds = cursor.fetchone()[0] or 0

        query, _ = apply_period_to_query(
            f"SELECT COUNT(DISTINCT track_id) {base_query}", period, has_where=False
        )
        cursor.execute(query, params)
        total_tracks = cursor.fetchone()[0] or 0

        query, _ = apply_period_to_query(
            f"SELECT COUNT(DISTINCT artist) {base_query}", period, has_where=False
        )
        cursor.execute(query, params)
        total_artists = cursor.fetchone()[0] or 0

        query, _ = apply_period_to_query(
            f"SELECT COUNT(*) {base_query}", period, has_where=False
        )
        cursor.execute(query, params)
        total_plays = cursor.fetchone()[0] or 0

        query, _ = apply_period_to_query(
            f"SELECT AVG(played_ms)/1000.0 {base_query}", period, has_where=False
        )
        cursor.execute(query, params)
        avg_session = cursor.fetchone()[0] or 0

        query, _ = apply_period_to_query(
            f"SELECT MAX(played_ms)/1000.0 {base_query}", period, has_where=False
        )
        cursor.execute(query, params)
        longest_session = cursor.fetchone()[0] or 0

    return jsonify({
        'total_seconds': total_seconds,
        'total_tracks': total_tracks,
        'total_artists': total_artists,
        'total_plays': total_plays,
        'avg_session_seconds': avg_session,
        'longest_session_seconds': longest_session,
    })

@app.route('/stats/top-artists', methods=['GET'])
def top_artists():
    period = request.args.get('period', 'all')
    limit = int(request.args.get('limit', 10))
    with get_db_connection() as conn:
        cursor = conn.cursor()
        query = """
            SELECT t.artist, SUM(p.played_ms)/1000.0 as total_seconds
            FROM plays p
            JOIN tracks t ON p.track_id = t.id
        """
        query, params = apply_period_to_query(query, period, has_where=False)
        query += " GROUP BY t.artist ORDER BY total_seconds DESC LIMIT ?"
        params.append(limit)
        cursor.execute(query, params)
        rows = cursor.fetchall()
    return jsonify([{'artist': row[0], 'seconds': row[1]} for row in rows])

@app.route('/stats/top-tracks', methods=['GET'])
def top_tracks():
    period = request.args.get('period', 'all')
    limit = int(request.args.get('limit', 10))
    with get_db_connection() as conn:
        cursor = conn.cursor()
        query = """
            SELECT t.title, t.artist, SUM(p.played_ms)/1000.0 as total_seconds
            FROM plays p
            JOIN tracks t ON p.track_id = t.id
        """
        query, params = apply_period_to_query(query, period, has_where=False)
        query += " GROUP BY p.track_id ORDER BY total_seconds DESC LIMIT ?"
        params.append(limit)
        cursor.execute(query, params)
        rows = cursor.fetchall()
    return jsonify([{'title': row[0], 'artist': row[1], 'seconds': row[2]} for row in rows])

@app.route('/stats/top-skipped-tracks', methods=['GET'])
def top_skipped_tracks():
    period = request.args.get('period', 'all')
    limit = int(request.args.get('limit', 10))
    with get_db_connection() as conn:
        cursor = conn.cursor()
        query = """
            SELECT t.title, t.artist, COUNT(*) as skip_count
            FROM plays p
            JOIN tracks t ON p.track_id = t.id
            WHERE p.status = 'SKIPPED'
        """
        query, params = apply_period_to_query(query, period, has_where=True)
        query += " GROUP BY p.track_id ORDER BY skip_count DESC LIMIT ?"
        params.append(limit)
        cursor.execute(query, params)
        rows = cursor.fetchall()
    return jsonify([{'title': row[0], 'artist': row[1], 'skips': row[2]} for row in rows])

@app.route('/stats/top-skipped-artists', methods=['GET'])
def top_skipped_artists():
    period = request.args.get('period', 'all')
    limit = int(request.args.get('limit', 10))
    with get_db_connection() as conn:
        cursor = conn.cursor()
        query = """
            SELECT t.artist, COUNT(*) as skip_count
            FROM plays p
            JOIN tracks t ON p.track_id = t.id
            WHERE p.status = 'SKIPPED'
        """
        query, params = apply_period_to_query(query, period, has_where=True)
        query += " GROUP BY t.artist ORDER BY skip_count DESC LIMIT ?"
        params.append(limit)
        cursor.execute(query, params)
        rows = cursor.fetchall()
    return jsonify([{'artist': row[0], 'skips': row[1]} for row in rows])

@app.route('/stats/listening-hours', methods=['GET'])
def listening_hours():
    period = request.args.get('period', 'all')
    with get_db_connection() as conn:
        cursor = conn.cursor()
        query = """
            SELECT strftime('%H', p.played_at) as hour,
                   SUM(p.played_ms)/1000.0 as total_seconds
            FROM plays p
        """
        query, params = apply_period_to_query(query, period, has_where=False)
        query += " GROUP BY hour ORDER BY hour"
        cursor.execute(query, params)
        rows = cursor.fetchall()
    hours = {str(i).zfill(2): 0 for i in range(24)}
    for h, sec in rows:
        hours[h] = sec
    return jsonify([{'hour': int(h), 'seconds': sec} for h, sec in sorted(hours.items())])

@app.route('/stats/weekday', methods=['GET'])
def weekday_stats():
    period = request.args.get('period', 'all')
    with get_db_connection() as conn:
        cursor = conn.cursor()
        query = """
            SELECT strftime('%w', p.played_at) as dow,
                   SUM(p.played_ms)/1000.0 as total_seconds
            FROM plays p
        """
        query, params = apply_period_to_query(query, period, has_where=False)
        query += " GROUP BY dow ORDER BY dow"
        cursor.execute(query, params)
        rows = cursor.fetchall()
    days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
    result = []
    for dow, sec in rows:
        result.append({'day': days[int(dow)], 'seconds': sec})
    return jsonify(result)

@app.route('/stats/status-distribution', methods=['GET'])
def status_distribution():
    period = request.args.get('period', 'all')
    with get_db_connection() as conn:
        cursor = conn.cursor()
        query = """
            SELECT p.status, COUNT(*) as count
            FROM plays p
        """
        query, params = apply_period_to_query(query, period, has_where=False)
        query += " GROUP BY p.status"
        cursor.execute(query, params)
        rows = cursor.fetchall()
    return jsonify({status: count for status, count in rows})

@app.route('/stats/top-albums', methods=['GET'])
def top_albums():
    period = request.args.get('period', 'all')
    limit = int(request.args.get('limit', 10))
    with get_db_connection() as conn:
        cursor = conn.cursor()
        query = """
            SELECT t.album, SUM(p.played_ms)/1000.0 as total_seconds
            FROM plays p
            JOIN tracks t ON p.track_id = t.id
            WHERE t.album IS NOT NULL AND t.album != ''
        """
        query, params = apply_period_to_query(query, period, has_where=True)
        query += " GROUP BY t.album ORDER BY total_seconds DESC LIMIT ?"
        params.append(limit)
        cursor.execute(query, params)
        rows = cursor.fetchall()
    return jsonify([{'album': row[0], 'seconds': row[1]} for row in rows])

@app.route('/stats/best-day', methods=['GET'])
def best_day():
    period = request.args.get('period', 'all')
    with get_db_connection() as conn:
        cursor = conn.cursor()
        query = """
            SELECT DATE(p.played_at) as date,
                   SUM(p.played_ms)/1000.0 as total_seconds,
                   COUNT(*) as plays
            FROM plays p
        """
        query, params = apply_period_to_query(query, period, has_where=False)
        query += " GROUP BY DATE(p.played_at) ORDER BY total_seconds DESC LIMIT 1"
        cursor.execute(query, params)
        row = cursor.fetchone()
    if row:
        return jsonify({'date': row[0], 'seconds': row[1], 'plays': row[2]})
    return jsonify({})

# --------------------------------------------------
# ENDPOINTY DLA LISTENERA
# --------------------------------------------------

@app.route('/listen', methods=['POST'])
def listen():
    """
    Odbiera dane o nowym utworze od listenera.
    Kończy poprzednią sesję (zapisuje do plays) i tworzy nową w pamięci.
    """
    data = request.get_json()
    if not data or 'uri' not in data or 'name' not in data:
        return jsonify({'status': 'error', 'message': 'Brak wymaganych danych'}), 400

    global current_track_cache

    # --------------------------------------------------
    # ZAKOŃCZ POPRZEDNIĄ SESJĘ (zapisz do plays)
    # --------------------------------------------------
    if current_track_cache.get('playing') and current_track_cache.get('track_id'):
        track_id = current_track_cache['track_id']
        played_ms = current_track_cache['progress_ms']
        duration_ms = current_track_cache['duration_ms']

        # Zabezpieczenie: played_ms nie może przekraczać duration_ms
        if duration_ms and duration_ms > 0 and played_ms > duration_ms:
            played_ms = duration_ms
            logger.warning(f"Przycięto played_ms do duration_ms dla track_id={track_id}")

        # Odczytać flagę, czy utwór był wstrzymany
        was_paused = data.get('was_paused', False)

        # Ustal status
        if duration_ms and duration_ms > 0:
            ratio = played_ms / duration_ms
            if was_paused:
                status = "FULL"   # dokańczanie po pauzie
            elif ratio >= 0.1:    # >= 10% utworu
                status = "FULL"
            else:
                status = "SKIPPED"
        else:
            # Brak duration – tylko czas bezwzględny
            status = "FULL" if played_ms > 30000 else "SKIPPED"

        # Zapisz do bazy
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO plays (track_id, played_at, played_ms, status)
                    VALUES (?, ?, ?, ?)
                ''', (track_id, datetime.now(), played_ms, status))
                conn.commit()
            logger.info(f"⏹ Zakończono sesję: {status} ({played_ms/1000:.1f}s)")
        except Exception as e:
            logger.error(f"Błąd zapisu sesji: {e}")

    # --------------------------------------------------
    # ROZPOCZNIJ NOWĄ SESJĘ (w pamięci)
    # --------------------------------------------------
    try:
        track_id = get_or_create_track(
            data['uri'],
            data['name'],
            data['artist'],
            data.get('album'),
            data.get('duration_ms') or 0
        )
    except Exception as e:
        logger.error(f"Błąd get_or_create_track: {e}")
        return jsonify({'status': 'error', 'message': 'Błąd bazy'}), 500

    current_track_cache = {
        'image_url': data.get('image_url'),
        'title': data['name'],
        'artist': data['artist'],
        'album': data.get('album'),
        'uri': data['uri'],
        'duration_ms': data.get('duration_ms') or 0,
        'progress_ms': 0,
        'playing': True,
        'track_id': track_id,
        'last_update': time.time()
    }

    logger.info(f"▶ Start: {data['name']} - {data['artist']} (duration_ms={data.get('duration_ms') or 0})")
    return jsonify({'status': 'session_started'})

@app.route('/progress', methods=['POST'])
def progress():
    """
    Odbiera postęp odtwarzania od listenera.
    Aktualizuje TYLKO pamięć, NIE BAZĘ.
    """
    data = request.get_json()
    if not data or 'uri' not in data or 'progress_ms' not in data:
        return jsonify({'status': 'error'}), 400

    global current_track_cache

    # Aktualizuj tylko jeśli to ten sam utwór
    if current_track_cache.get('uri') == data['uri']:
        current_track_cache['progress_ms'] = data['progress_ms']
        current_track_cache['playing'] = True
        current_track_cache['last_update'] = time.time()

    return jsonify({'status': 'progress_updated'})

@app.route('/stats/current', methods=['GET'])
def current_playing():
    """
    Zwraca aktualnie odtwarzany utwór z pamięci podręcznej.
    """
    global current_track_cache

    # Sprawdź, czy sesja nie wygasła (brak aktualizacji przez > 30s)
    if current_track_cache.get('playing') and current_track_cache.get('last_update'):
        if time.time() - current_track_cache['last_update'] > 30:
            current_track_cache['playing'] = False

    if not current_track_cache.get('playing') or not current_track_cache.get('title'):
        return jsonify({'playing': False})

    track = current_track_cache
    duration_ms = track.get('duration_ms', 0)
    progress_ms = track.get('progress_ms', 0)
    percentage = (progress_ms / duration_ms * 100) if duration_ms > 0 else 0

    return jsonify({
        'playing': True,
        'track': {
            'id': track.get('uri'),
            'title': track.get('title'),
            'artist': track.get('artist'),
            'album': track.get('album'),
            'image_url': track.get('image_url'),
            'duration_ms': duration_ms,
            'progress_ms': progress_ms,
            'percentage': percentage,
            'context_uri': track.get('context_uri')
        }
    })

@app.route('/stats/genres', methods=['GET'])
def stats_genres():
    period = request.args.get('period', 'all')
    with get_db_connection() as conn:
        cursor = conn.cursor()
        query = """
            SELECT g.genre,
                   SUM(p.played_ms)/1000.0 as total_seconds
            FROM plays p
            JOIN tracks t ON p.track_id = t.id
            JOIN artist_genres g ON g.artist = t.artist
        """
        query, params = apply_period_to_query(query, period, has_where=False)
        query += " GROUP BY g.genre ORDER BY total_seconds DESC"
        cursor.execute(query, params)
        rows = cursor.fetchall()
    return jsonify([{'genre': row[0], 'seconds': row[1]} for row in rows])

# --------------------------------------------------
# ENDPOINT: Strona główna
# --------------------------------------------------
@app.route('/')
def dashboard():
    return render_template('index.html')

# --------------------------------------------------
# INICJALIZACJA BAZY
# --------------------------------------------------
def init_database():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # Tworzymy tabele jeśli nie istnieją
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                spotify_id TEXT UNIQUE,
                title TEXT NOT NULL,
                artist TEXT NOT NULL,
                album TEXT,
                duration_ms INTEGER,
                genre TEXT,
                image_url TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS plays (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                track_id INTEGER NOT NULL,
                played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                played_ms INTEGER,
                status TEXT CHECK(status IN ('FULL','SKIPPED')),
                FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE
            )
        ''')
        # Usuwamy tabelę sessions jeśli istnieje
        cursor.execute("DROP TABLE IF EXISTS sessions")
        conn.commit()
        logger.info("Baza danych zainicjalizowana (tylko FULL i SKIPPED).")

# --------------------------------------------------
# URUCHOMIENIE
# --------------------------------------------------
if __name__ == "__main__":
    init_database()
    app.run(host="127.0.0.1", port=5000, debug=False)