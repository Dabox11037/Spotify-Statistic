import sqlite3

DB_PATH = "staty.db"

def main():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. Całkowite statystyki
    cursor.execute("SELECT COUNT(*), SUM(played_ms)/1000.0 FROM plays")
    total_plays, total_seconds = cursor.fetchone()
    total_hours = total_seconds / 3600.0 if total_seconds else 0

    # 2. Statystyki dla artystów BEZ gatunków
    cursor.execute("""
        SELECT COUNT(*), SUM(p.played_ms)/1000.0
        FROM plays p
        JOIN tracks t ON p.track_id = t.id
        WHERE t.artist NOT IN (
            SELECT DISTINCT artist FROM artist_genres
        )
        AND t.artist IS NOT NULL AND t.artist != ''
    """)
    missing_plays, missing_seconds = cursor.fetchone()
    missing_plays = missing_plays or 0
    missing_seconds = missing_seconds or 0
    missing_hours = missing_seconds / 3600.0

    # 3. Liczba unikalnych artystów bez gatunków
    cursor.execute("""
        SELECT COUNT(DISTINCT t.artist)
        FROM tracks t
        WHERE t.artist NOT IN (
            SELECT DISTINCT artist FROM artist_genres
        )
        AND t.artist IS NOT NULL AND t.artist != ''
    """)
    missing_artists_count = cursor.fetchone()[0] or 0

    conn.close()

    # 4. Procenty
    plays_pct = (missing_plays / total_plays * 100) if total_plays else 0
    time_pct = (missing_hours / total_hours * 100) if total_hours else 0

    # 5. Wyświetlenie
    print("=" * 55)
    print("📊 STATYSTYKI DLA ARTYSTÓW BEZ GATUNKÓW")
    print("=" * 55)
    print(f"👥 Liczba artystów bez gatunków: {missing_artists_count}")
    print()
    print(f"🎵 Wszystkie odsłuchania: {total_plays}")
    print(f"🎵 Odsłuchania tych artystów: {missing_plays}")
    print(f"   → {plays_pct:.2f}% wszystkich odsłuchań")
    print()
    print(f"⏱️  Całkowity czas słuchania: {total_hours:.2f} h")
    print(f"⏱️  Czas tych artystów: {missing_hours:.2f} h")
    print(f"   → {time_pct:.2f}% całkowitego czasu")
    print("=" * 55)

    if time_pct < 5:
        print("✅ Udział jest bardzo mały – możesz zignorować te gatunki.")
    elif time_pct < 20:
        print("⚠️ Udział jest znaczący – warto uzupełnić gatunki dla najpopularniejszych z nich.")
    else:
        print("🔥 Udział jest duży – zdecydowanie warto uzupełnić gatunki.")

if __name__ == "__main__":
    main()