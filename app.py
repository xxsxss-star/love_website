from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
DB_PATH = DATA_DIR / "love.db"
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="Our Love", version="1.0.0")


@contextmanager
def db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS couple (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            person1 TEXT NOT NULL,
            person2 TEXT NOT NULL,
            start_date TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS anniversaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            event_date TEXT NOT NULL,
            yearly INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS wishes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            completed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS moods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            person TEXT NOT NULL,
            mood_date TEXT NOT NULL,
            emoji TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(person, mood_date)
        );
        """)


@app.on_event("startup")
def startup():
    init_db()


class CoupleIn(BaseModel):
    person1: str = Field(min_length=1, max_length=30)
    person2: str = Field(min_length=1, max_length=30)
    start_date: date


class AnniversaryIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    event_date: date
    yearly: bool = True


class MessageIn(BaseModel):
    sender: str = Field(min_length=1, max_length=30)
    content: str = Field(min_length=1, max_length=300)


class WishIn(BaseModel):
    content: str = Field(min_length=1, max_length=200)


class WishStatus(BaseModel):
    completed: bool


class MoodIn(BaseModel):
    person: str = Field(min_length=1, max_length=30)
    mood_date: date
    emoji: Literal["🥰", "😊", "😌", "😢", "😤", "🥱"]
    note: str = Field(default="", max_length=100)


def row_dict(row):
    return dict(row) if row else None


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/couple")
def get_couple():
    with db() as conn:
        row = conn.execute("SELECT * FROM couple WHERE id=1").fetchone()
    return row_dict(row)


@app.put("/api/couple")
def save_couple(payload: CoupleIn):
    with db() as conn:
        conn.execute("""INSERT INTO couple(id, person1, person2, start_date) VALUES(1,?,?,?)
            ON CONFLICT(id) DO UPDATE SET person1=excluded.person1, person2=excluded.person2, start_date=excluded.start_date""",
            (payload.person1.strip(), payload.person2.strip(), payload.start_date.isoformat()))
    return get_couple()


@app.get("/api/anniversaries")
def list_anniversaries():
    with db() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM anniversaries ORDER BY event_date, id")]


@app.post("/api/anniversaries", status_code=201)
def add_anniversary(payload: AnniversaryIn):
    with db() as conn:
        cur = conn.execute("INSERT INTO anniversaries(name,event_date,yearly) VALUES(?,?,?)",
                           (payload.name.strip(), payload.event_date.isoformat(), int(payload.yearly)))
        row = conn.execute("SELECT * FROM anniversaries WHERE id=?", (cur.lastrowid,)).fetchone()
    return dict(row)


@app.delete("/api/anniversaries/{item_id}", status_code=204)
def delete_anniversary(item_id: int):
    with db() as conn:
        cur = conn.execute("DELETE FROM anniversaries WHERE id=?", (item_id,))
        if not cur.rowcount:
            raise HTTPException(404, "纪念日不存在")


@app.get("/api/messages")
def list_messages():
    with db() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM messages ORDER BY id DESC LIMIT 100")]


@app.post("/api/messages", status_code=201)
def add_message(payload: MessageIn):
    with db() as conn:
        cur = conn.execute("INSERT INTO messages(sender,content) VALUES(?,?)", (payload.sender.strip(), payload.content.strip()))
        row = conn.execute("SELECT * FROM messages WHERE id=?", (cur.lastrowid,)).fetchone()
    return dict(row)


@app.delete("/api/messages/{item_id}", status_code=204)
def delete_message(item_id: int):
    with db() as conn:
        conn.execute("DELETE FROM messages WHERE id=?", (item_id,))


@app.get("/api/wishes")
def list_wishes():
    with db() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM wishes ORDER BY completed, id DESC")]


@app.post("/api/wishes", status_code=201)
def add_wish(payload: WishIn):
    with db() as conn:
        cur = conn.execute("INSERT INTO wishes(content) VALUES(?)", (payload.content.strip(),))
        row = conn.execute("SELECT * FROM wishes WHERE id=?", (cur.lastrowid,)).fetchone()
    return dict(row)


@app.patch("/api/wishes/{item_id}")
def update_wish(item_id: int, payload: WishStatus):
    completed_at = datetime.now().isoformat(timespec="seconds") if payload.completed else None
    with db() as conn:
        cur = conn.execute("UPDATE wishes SET completed=?, completed_at=? WHERE id=?", (int(payload.completed), completed_at, item_id))
        if not cur.rowcount:
            raise HTTPException(404, "愿望不存在")
        row = conn.execute("SELECT * FROM wishes WHERE id=?", (item_id,)).fetchone()
    return dict(row)


@app.delete("/api/wishes/{item_id}", status_code=204)
def delete_wish(item_id: int):
    with db() as conn:
        conn.execute("DELETE FROM wishes WHERE id=?", (item_id,))


@app.get("/api/moods")
def list_moods(mood_date: date | None = None):
    with db() as conn:
        if mood_date:
            rows = conn.execute("SELECT * FROM moods WHERE mood_date=? ORDER BY person", (mood_date.isoformat(),))
        else:
            rows = conn.execute("SELECT * FROM moods ORDER BY mood_date DESC, person LIMIT 60")
        return [dict(r) for r in rows]


@app.put("/api/moods")
def save_mood(payload: MoodIn):
    with db() as conn:
        conn.execute("""INSERT INTO moods(person,mood_date,emoji,note) VALUES(?,?,?,?)
            ON CONFLICT(person,mood_date) DO UPDATE SET emoji=excluded.emoji,note=excluded.note,updated_at=CURRENT_TIMESTAMP""",
            (payload.person.strip(), payload.mood_date.isoformat(), payload.emoji, payload.note.strip()))
        row = conn.execute("SELECT * FROM moods WHERE person=? AND mood_date=?", (payload.person.strip(), payload.mood_date.isoformat())).fetchone()
    return dict(row)


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")

