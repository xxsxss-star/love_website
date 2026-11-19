from __future__ import annotations

import os
import hashlib
import hmac
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import Cookie, Depends, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
DB_PATH = DATA_DIR / "love.db"
STATIC_DIR = BASE_DIR / "static"
SESSION_COOKIE = "love_session"
SESSION_DAYS = 30

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
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            expires_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """)
        for username, password in (
            ("admin1", os.getenv("ADMIN1_PASSWORD", "admin1")),
            ("admin2", os.getenv("ADMIN2_PASSWORD", "admin2")),
        ):
            conn.execute("""INSERT INTO users(username,password_hash) VALUES(?,?)
                ON CONFLICT(username) DO UPDATE SET password_hash=excluded.password_hash""",
                (username, hash_password(password)))
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (utc_now().isoformat(),))


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


class LoginIn(BaseModel):
    username: Literal["admin1", "admin2"]
    password: str = Field(min_length=1, max_length=128)


def utc_now():
    return datetime.now(timezone.utc)


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return f"{salt.hex()}:{digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    salt_hex, expected = stored.split(":", 1)
    actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 200_000).hex()
    return hmac.compare_digest(actual, expected)


def current_user(love_session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    if not love_session:
        return None
    with db() as conn:
        row = conn.execute("""SELECT users.username, sessions.expires_at FROM sessions
            JOIN users ON users.id=sessions.user_id WHERE sessions.token=?""", (love_session,)).fetchone()
        if not row or datetime.fromisoformat(row["expires_at"]) <= utc_now():
            if row:
                conn.execute("DELETE FROM sessions WHERE token=?", (love_session,))
            return None
    return row["username"]


def require_user(username: str | None = Depends(current_user)):
    if not username:
        raise HTTPException(status_code=401, detail="请先登录后再操作")
    return username


def row_dict(row):
    return dict(row) if row else None


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/auth/me")
def auth_me(username: str | None = Depends(current_user)):
    return {"authenticated": bool(username), "username": username}


@app.post("/api/auth/login")
def login(payload: LoginIn, response: Response):
    with db() as conn:
        user = conn.execute("SELECT * FROM users WHERE username=?", (payload.username,)).fetchone()
        if not user or not verify_password(payload.password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        token = secrets.token_urlsafe(32)
        expires = utc_now() + timedelta(days=SESSION_DAYS)
        conn.execute("INSERT INTO sessions(token,user_id,expires_at) VALUES(?,?,?)",
                     (token, user["id"], expires.isoformat()))
    response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_DAYS * 86400,
                        httponly=True, samesite="strict", secure=False)
    return {"authenticated": True, "username": payload.username}


@app.post("/api/auth/logout", status_code=204)
def logout(response: Response, love_session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    if love_session:
        with db() as conn:
            conn.execute("DELETE FROM sessions WHERE token=?", (love_session,))
    response.delete_cookie(SESSION_COOKIE)


@app.get("/api/couple")
def get_couple():
    with db() as conn:
        row = conn.execute("SELECT * FROM couple WHERE id=1").fetchone()
    return row_dict(row)


@app.put("/api/couple")
def save_couple(payload: CoupleIn, _=Depends(require_user)):
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
def add_anniversary(payload: AnniversaryIn, _=Depends(require_user)):
    with db() as conn:
        cur = conn.execute("INSERT INTO anniversaries(name,event_date,yearly) VALUES(?,?,?)",
                           (payload.name.strip(), payload.event_date.isoformat(), int(payload.yearly)))
        row = conn.execute("SELECT * FROM anniversaries WHERE id=?", (cur.lastrowid,)).fetchone()
    return dict(row)


@app.delete("/api/anniversaries/{item_id}", status_code=204)
def delete_anniversary(item_id: int, _=Depends(require_user)):
    with db() as conn:
        cur = conn.execute("DELETE FROM anniversaries WHERE id=?", (item_id,))
        if not cur.rowcount:
            raise HTTPException(404, "纪念日不存在")


@app.get("/api/messages")
def list_messages():
    with db() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM messages ORDER BY id DESC LIMIT 100")]


@app.post("/api/messages", status_code=201)
def add_message(payload: MessageIn, _=Depends(require_user)):
    with db() as conn:
        cur = conn.execute("INSERT INTO messages(sender,content) VALUES(?,?)", (payload.sender.strip(), payload.content.strip()))
        row = conn.execute("SELECT * FROM messages WHERE id=?", (cur.lastrowid,)).fetchone()
    return dict(row)


@app.delete("/api/messages/{item_id}", status_code=204)
def delete_message(item_id: int, _=Depends(require_user)):
    with db() as conn:
        conn.execute("DELETE FROM messages WHERE id=?", (item_id,))


@app.get("/api/wishes")
def list_wishes():
    with db() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM wishes ORDER BY completed, id DESC")]


@app.post("/api/wishes", status_code=201)
def add_wish(payload: WishIn, _=Depends(require_user)):
    with db() as conn:
        cur = conn.execute("INSERT INTO wishes(content) VALUES(?)", (payload.content.strip(),))
        row = conn.execute("SELECT * FROM wishes WHERE id=?", (cur.lastrowid,)).fetchone()
    return dict(row)


@app.patch("/api/wishes/{item_id}")
def update_wish(item_id: int, payload: WishStatus, _=Depends(require_user)):
    completed_at = datetime.now().isoformat(timespec="seconds") if payload.completed else None
    with db() as conn:
        cur = conn.execute("UPDATE wishes SET completed=?, completed_at=? WHERE id=?", (int(payload.completed), completed_at, item_id))
        if not cur.rowcount:
            raise HTTPException(404, "愿望不存在")
        row = conn.execute("SELECT * FROM wishes WHERE id=?", (item_id,)).fetchone()
    return dict(row)


@app.delete("/api/wishes/{item_id}", status_code=204)
def delete_wish(item_id: int, _=Depends(require_user)):
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
def save_mood(payload: MoodIn, _=Depends(require_user)):
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
