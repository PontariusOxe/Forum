import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from contextlib import closing
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs
from html import escape


DB_PATH = Path(__file__).with_name("forum.db")
PASSWORD_ITERATIONS = 310_000
SESSION_LIFETIME = 60 * 60 * 24 * 7
MAX_REQUEST_SIZE = 12_000


def connect_db(database_path=None):
    if database_path is None:
        database_path = DB_PATH
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db(database_path=None):
    with closing(connect_db(database_path)) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                body TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                csrf_token TEXT NOT NULL,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                expires_at INTEGER NOT NULL
            );
            """
        )
        db.commit()


def hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    password_hash = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
    )
    return f"{salt.hex()}:{password_hash.hex()}"


def verify_password(password, stored_hash):
    salt_hex, expected_hash = stored_hash.split(":", 1)
    actual_hash = hash_password(password, bytes.fromhex(salt_hex)).split(":", 1)[1]
    return hmac.compare_digest(actual_hash, expected_hash)


def create_session(db, user_id=None):
    session_id = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    db.execute(
        "INSERT INTO sessions (session_id, csrf_token, user_id, expires_at) "
        "VALUES (?, ?, ?, ?)",
        (session_id, csrf_token, user_id, int(time.time()) + SESSION_LIFETIME),
    )
    return session_id, csrf_token


def page(title, content):
    return f"""<!doctype html>
<html lang="sv">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{escape(title)} | Fårforum</title>
    <link rel="stylesheet" href="/style.css">
</head>
<body>
    <header class="site-header">
        <a class="brand" href="/">Fårforum</a>
    </header>
    <main>{content}</main>
</body>
</html>"""


class ForumHandler(BaseHTTPRequestHandler):
    server_version = "Farforum/1.0"

    def _session(self, db):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except CookieError:
            pass

        session_id = cookie["forum_session"].value if "forum_session" in cookie else ""
        row = db.execute(
            "SELECT session_id, csrf_token, user_id FROM sessions "
            "WHERE session_id = ? AND expires_at > ?",
            (session_id, int(time.time())),
        ).fetchone()

        if row is None:
            session_id, csrf_token = create_session(db)
            db.commit()
            return csrf_token, None, session_id

        user = None
        if row["user_id"] is not None:
            user = db.execute(
                "SELECT id, username FROM users WHERE id = ?", (row["user_id"],)
            ).fetchone()
        return row["csrf_token"], user, session_id

    def _set_session_cookie(self, session_id):
        self.send_header(
            "Set-Cookie",
            f"forum_session={session_id}; Path=/; HttpOnly; SameSite=Lax",
        )

    def _send(self, status, body, session_id=None, content_type="text/html; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'")
        if session_id is not None:
            self._set_session_cookie(session_id)
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def _redirect(self, location, session_id=None):
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        if session_id is not None:
            self._set_session_cookie(session_id)
        self.end_headers()

    def _context(self):
        db = connect_db()
        csrf_token, user, session_id = self._session(db)
        return db, csrf_token, user, session_id

    def do_GET(self):
        if self.path == "/style.css":
            css = Path(__file__).with_name("style.css").read_text(encoding="utf-8")
            self._send(HTTPStatus.OK, css, content_type="text/css; charset=utf-8")
            return

        with closing(connect_db()) as db:
            csrf_token, user, session_id = self._session(db)

            if self.path == "/":
                posts = db.execute(
                    "SELECT posts.body, posts.created_at, users.username "
                    "FROM posts JOIN users ON users.id = posts.user_id "
                    "ORDER BY posts.id DESC"
                ).fetchall()
                self._send(
                    HTTPStatus.OK,
                    self._home_page(posts, user, csrf_token),
                    session_id,
                )
            elif self.path == "/login":
                self._send(
                    HTTPStatus.OK,
                    self._auth_page("Logga in", "/login", csrf_token, "login"),
                    session_id,
                )
            elif self.path == "/register":
                self._send(
                    HTTPStatus.OK,
                    self._auth_page("Skapa konto", "/register", csrf_token, "register"),
                    session_id,
                )
            else:
                self._send(
                    HTTPStatus.NOT_FOUND,
                    page("Sidan hittades inte", "<h1>Sidan hittades inte</h1>"),
                    session_id,
                )

    def do_POST(self):
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send(HTTPStatus.BAD_REQUEST, page("Fel", "<h1>Felaktig förfrågan</h1>"))
            return
        if content_length < 0 or content_length > MAX_REQUEST_SIZE:
            self._send(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, page("Fel", "<h1>Formuläret är för stort</h1>"))
            return

        form = parse_qs(
            self.rfile.read(content_length).decode("utf-8", errors="replace"),
            keep_blank_values=True,
        )
        with closing(connect_db()) as db:
            csrf_token, user, session_id = self._session(db)
            submitted_csrf = form.get("csrf_token", [""])[0]
            if not hmac.compare_digest(submitted_csrf, csrf_token):
                self._send(
                    HTTPStatus.FORBIDDEN,
                    page("Fel", "<h1>Formuläret har gått ut. Ladda om sidan och försök igen.</h1>"),
                    session_id,
                )
                return

            if self.path == "/register":
                self._register(db, form, session_id)
            elif self.path == "/login":
                self._login(db, form, session_id)
            elif self.path == "/post":
                self._create_post(db, form, user, session_id)
            elif self.path == "/logout":
                db.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
                new_session, _ = create_session(db)
                db.commit()
                self._redirect("/", new_session)
            else:
                self._send(HTTPStatus.NOT_FOUND, page("Sidan hittades inte", "<h1>Sidan hittades inte</h1>"))

    def _register(self, db, form, session_id):
        username = form.get("username", [""])[0].strip()
        password = form.get("password", [""])[0]
        if not 3 <= len(username) <= 30 or not username.replace("_", "").isalnum():
            self._send(
                HTTPStatus.BAD_REQUEST,
                self._auth_page(
                    "Skapa konto", "/register", self._csrf_for(db, session_id),
                    "register", "Användarnamnet måste vara 3–30 tecken och bara innehålla bokstäver, siffror eller _.",
                ),
                session_id,
            )
            return
        if not 8 <= len(password) <= 128:
            self._send(
                HTTPStatus.BAD_REQUEST,
                self._auth_page(
                    "Skapa konto", "/register", self._csrf_for(db, session_id),
                    "register", "Lösenordet måste vara minst 8 tecken.",
                ),
                session_id,
            )
            return
        try:
            cursor = db.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, hash_password(password)),
            )
        except sqlite3.IntegrityError:
            self._send(
                HTTPStatus.CONFLICT,
                self._auth_page(
                    "Skapa konto", "/register", self._csrf_for(db, session_id),
                    "register", "Användarnamnet används redan.",
                ),
                session_id,
            )
            return

        db.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        new_session, _ = create_session(db, cursor.lastrowid)
        db.commit()
        self._redirect("/", new_session)

    def _login(self, db, form, session_id):
        username = form.get("username", [""])[0].strip()
        password = form.get("password", [""])[0]
        user = db.execute(
            "SELECT id, password_hash FROM users WHERE username = ?", (username,)
        ).fetchone()
        if user is None or not verify_password(password, user["password_hash"]):
            self._send(
                HTTPStatus.UNAUTHORIZED,
                self._auth_page(
                    "Logga in", "/login", self._csrf_for(db, session_id),
                    "login", "Fel användarnamn eller lösenord.",
                ),
                session_id,
            )
            return

        db.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        new_session, _ = create_session(db, user["id"])
        db.commit()
        self._redirect("/", new_session)

    def _create_post(self, db, form, user, session_id):
        if user is None:
            self._send(HTTPStatus.UNAUTHORIZED, page("Logga in", '<h1>Du behöver <a href="/login">logga in</a>.</h1>'), session_id)
            return
        body = form.get("body", [""])[0].strip()
        if not body or len(body) > 2_000:
            self._send(
                HTTPStatus.BAD_REQUEST,
                page("Fel", '<h1>Inlägget måste innehålla 1–2 000 tecken.</h1><p><a href="/">Till forumet</a></p>'),
                session_id,
            )
            return
        db.execute("INSERT INTO posts (user_id, body) VALUES (?, ?)", (user["id"], body))
        db.commit()
        self._redirect("/")

    @staticmethod
    def _csrf_for(db, session_id):
        row = db.execute(
            "SELECT csrf_token FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        return row["csrf_token"]

    def _home_page(self, posts, user, csrf_token):
        if user:
            composer = f"""
                <section class="panel">
                    <p>Inloggad som <strong>{escape(user["username"])}</strong></p>
                    <form action="/post" method="post">
                        <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
                        <label for="body">Skriv ett inlägg</label>
                        <textarea id="body" name="body" maxlength="2000" required></textarea>
                        <button type="submit">Publicera</button>
                    </form>
                    <form action="/logout" method="post">
                        <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
                        <button class="secondary" type="submit">Logga ut</button>
                    </form>
                </section>"""
        else:
            composer = """
                <section class="panel">
                    <p>Logga in eller skapa ett konto för att skriva i forumet.</p>
                    <a class="button" href="/login">Logga in</a>
                    <a class="button secondary" href="/register">Skapa konto</a>
                </section>"""

        if posts:
            post_html = "".join(
                f"""<article class="post">
                    <div class="post-meta">
                        <span class="post-author">Skrivet av <strong>{escape(post["username"])}</strong></span>
                        <time>{escape(post["created_at"])}</time>
                    </div>
                    <p>{escape(post["body"])}</p>
                </article>"""
                for post in posts
            )
        else:
            post_html = '<p class="empty">Inga inlägg ännu. Bli den första att skriva!</p>'

        return page(
            "Forum",
            f"""<h1>Välkommen till Fårforum</h1>
            {composer}
            <section>
                <h2>Senaste inläggen</h2>
                {post_html}
            </section>""",
        )

    def _auth_page(self, title, action, csrf_token, kind, error=None):
        error_html = f'<p class="error">{escape(error)}</p>' if error else ""
        content = f"""<h1>{escape(title)}</h1>
            {error_html}
            <section class="panel">
                <form action="{action}" method="post">
                    <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
                    <label for="username">Användarnamn</label>
                    <input id="username" name="username" type="text" minlength="3" maxlength="30" required autocomplete="username">
                    <label for="password">Lösenord</label>
                    <input id="password" name="password" type="password" required autocomplete="{'new-password' if kind == 'register' else 'current-password'}">
                    <button type="submit">{escape(title)}</button>
                </form>
            </section>
            <p><a href="/">Till forumet</a></p>
            <p>{"Har du redan ett konto? <a href='/login'>Logga in</a>." if kind == "register" else "Nytt här? <a href='/register'>Skapa konto</a>."}</p>"""
        return page(title, content)

    def log_message(self, format_string, *args):
        print(f"{self.address_string()} - {format_string % args}")


def main():
    init_db()
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), ForumHandler)
    print(f"Fårforum körs på http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServern stoppas.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
