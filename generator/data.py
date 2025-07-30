import atexit
from dataclasses import dataclass
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
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            complexity TEXT NOT NULL CHECK (complexity IN ('easy', 'intermediate', 'hard'))
        );
    """)
    con.commit()
    initialized = True


@dataclass
class Question:
    id: int
    question: str
    answer: str
    complexity: str


def load_questions() -> list[Question]:
    cur = con.cursor()
    cur.execute("""
        SELECT * FROM questions ORDER BY id
    """)
    ret = [Question(*row) for row in cur.fetchall()]
    cur.close()
    return ret


def save_question(question: str, answer: str, complexity: str) -> None:
    cur = con.cursor()
    cur.execute(
        "INSERT INTO questions (question, answer, complexity) VALUES (?, ?, ?)",
        (question, answer, complexity),
    )
    con.commit()
    cur.close()
