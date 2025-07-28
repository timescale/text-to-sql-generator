import atexit
from pathlib import Path
import sqlite3


rootdir = Path(__file__).resolve().parent.parent
db_path = rootdir / "data.sqlite"
initialized = db_path.exists()
con = sqlite3.connect(db_path)

atexit.register(lambda: con.close())

if not initialized:
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            complexity TEXT NOT NULL CHECK (complexity IN ('easy', 'intermediate', 'hard')),
            question TEXT NOT NULL
        );
    """)
    cur.execute("""
        CREATE TABLE answers (
            id INTEGER NOT NULL PRIMARY KEY,
            answer TEXT NOT NULL,
            results TEXT, -- Using text type for json data
            error TEXT,  -- Using text type for jsonb data
            FOREIGN KEY (id) REFERENCES questions (id) ON DELETE CASCADE
        );
    """)
    cur.execute("""
        CREATE TABLE adequate (
            id INTEGER NOT NULL PRIMARY KEY,
            adequate INTEGER NOT NULL, -- SQLite uses integer 0 (false) and 1 (true) for boolean
            reason TEXT,
            FOREIGN KEY (id) REFERENCES questions (id) ON DELETE CASCADE
        );
    """)
    con.commit()
    initialized = True


def load_questions() -> list[tuple[str, str]]:
    cur = con.cursor()
    cur.execute("SELECT question, complexity FROM questions")
    return [(row[0], row[1]) for row in cur.fetchall()]


def save_question(question: str, complexity: str) -> None:
    cur = con.cursor()
    cur.execute(
        "INSERT INTO questions (question, complexity) VALUES (%s, %s)",
        (question, complexity),
    )
    con.commit()
