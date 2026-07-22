import sqlite3

conn = sqlite3.connect('staty.db')
cursor = conn.cursor()

try:
    cursor.execute("ALTER TABLE sessions ADD COLUMN context_uri TEXT")
    conn.commit()
    print("✅ Kolumna context_uri dodana do tabeli sessions.")
except sqlite3.OperationalError as e:
    if "duplicate column name" in str(e).lower():
        print("ℹ️ Kolumna już istnieje – nic nie robię.")
    else:
        print("❌ Błąd:", e)

conn.close()