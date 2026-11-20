"""Local SQLite identity, bearer sessions, account state, and audit records."""

import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager


class IdentityStore:
    def __init__(self, path=None):
        if path is None:
            data_root = Path(
                os.getenv("LOCALAPPDATA", str(Path.home()))
            ) / "AITradingBot"
            data_root.mkdir(parents=True, exist_ok=True)
            path = data_root / "trading.sqlite3"
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self):
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    password_salt BLOB NOT NULL,
                    password_hash BLOB NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    suspended INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id),
                    expires_at REAL NOT NULL,
                    revoked INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS login_attempts (
                    email TEXT PRIMARY KEY,
                    failed_count INTEGER NOT NULL,
                    locked_until REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS account_state (
                    user_id TEXT PRIMARY KEY REFERENCES users(id),
                    portfolio_json TEXT NOT NULL DEFAULT '{}',
                    settings_json TEXT NOT NULL DEFAULT '{}',
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT REFERENCES users(id),
                    action TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS paper_orders (
                    user_id TEXT NOT NULL REFERENCES users(id),
                    idempotency_key TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(user_id, idempotency_key)
                );
            """)

    @staticmethod
    def _password_hash(password, salt):
        return hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=16384,
            r=8,
            p=1,
            dklen=32,
        )

    @staticmethod
    def _normalize_email(email):
        email = str(email or "").strip().lower()
        if (
            len(email) > 254
            or email.count("@") != 1
            or "." not in email.rsplit("@", 1)[-1]
        ):
            raise ValueError("A valid email address is required.")
        return email

    @staticmethod
    def _new_session(connection, user_id):
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
        now = time.time()
        connection.execute(
            "INSERT INTO sessions(token_hash, user_id, expires_at, created_at) "
            "VALUES (?, ?, ?, ?)",
            (token_hash, user_id, now + 60 * 60 * 12, now),
        )
        return token

    def register(self, email, password):
        normalized_email = self._normalize_email(email)
        if not isinstance(password, str) or not 12 <= len(password) <= 128:
            raise ValueError(
                "Password must contain between 12 and 128 characters."
            )
        salt = secrets.token_bytes(16)
        password_hash = self._password_hash(password, salt)
        user_id = str(uuid.uuid4())
        now = time.time()
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO users(id, email, password_salt, password_hash, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (user_id, normalized_email, salt, password_hash, now),
                )
                connection.execute(
                    "INSERT INTO account_state(user_id, updated_at) VALUES (?, ?)",
                    (user_id, now),
                )
                token = self._new_session(connection, user_id)
                self._audit(connection, user_id, "account.register", {})
        except sqlite3.IntegrityError as error:
            raise ValueError("An account with this email already exists.") from error
        return {"user_id": user_id, "email": normalized_email, "role": "user", "token": token}

    def login(self, email, password):
        normalized_email = self._normalize_email(email)
        if not isinstance(password, str) or len(password) > 128:
            password = ""
        failure = False
        with self._connect() as connection:
            now = time.time()
            attempt = connection.execute(
                "SELECT failed_count, locked_until FROM login_attempts WHERE email = ?",
                (normalized_email,),
            ).fetchone()
            if attempt and attempt["locked_until"] > now:
                self._audit(connection, None, "auth.login_throttled", {})
                failure = True
                user = None
            else:
                user = connection.execute(
                    "SELECT id, email, password_salt, password_hash, role, suspended "
                    "FROM users WHERE email = ?",
                    (normalized_email,),
                ).fetchone()
            if failure:
                token = None
            elif user is None:
                self._password_hash(str(password or ""), b"\x00" * 16)
                self._record_login_failure(connection, normalized_email, now)
                self._audit(connection, None, "auth.login_failed", {})
                failure = True
                token = None
            else:
                actual_hash = self._password_hash(
                    str(password or ""),
                    user["password_salt"],
                )
                if (
                    not hmac.compare_digest(actual_hash, user["password_hash"])
                    or user["suspended"]
                ):
                    self._record_login_failure(connection, normalized_email, now)
                    self._audit(connection, user["id"], "auth.login_failed", {})
                    failure = True
                    token = None
                else:
                    token = self._new_session(connection, user["id"])
                    connection.execute(
                        "DELETE FROM login_attempts WHERE email = ?",
                        (normalized_email,),
                    )
                    self._audit(connection, user["id"], "auth.login", {})
        if failure:
            raise ValueError("Invalid email or password, or login temporarily locked.")
        return {
            "user_id": user["id"],
            "email": user["email"],
            "role": user["role"],
            "token": token,
        }

    @staticmethod
    def _record_login_failure(connection, email, now):
        row = connection.execute(
            "SELECT failed_count FROM login_attempts WHERE email = ?",
            (email,),
        ).fetchone()
        failures = (row["failed_count"] if row else 0) + 1
        delay = 15 * 60 if failures >= 5 else 0
        connection.execute(
            "INSERT INTO login_attempts(email, failed_count, locked_until) "
            "VALUES (?, ?, ?) ON CONFLICT(email) DO UPDATE SET "
            "failed_count = excluded.failed_count, locked_until = excluded.locked_until",
            (email, failures, now + delay),
        )

    def authenticate(self, token):
        if not token or len(token) > 256:
            return None
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT u.id, u.email, u.role FROM sessions s "
                "JOIN users u ON u.id = s.user_id "
                "WHERE s.token_hash = ? AND s.revoked = 0 "
                "AND s.expires_at > ? AND u.suspended = 0",
                (token_hash, time.time()),
            ).fetchone()
            return dict(row) if row else None

    def revoke(self, token):
        if not token:
            return
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT user_id FROM sessions WHERE token_hash = ?",
                (token_hash,),
            ).fetchone()
            connection.execute(
                "UPDATE sessions SET revoked = 1 WHERE token_hash = ?",
                (token_hash,),
            )
            self._audit(
                connection,
                row["user_id"] if row else None,
                "auth.logout",
                {},
            )

    @staticmethod
    def _audit(connection, user_id, action, details):
        connection.execute(
            "INSERT INTO audit_log(user_id, action, details_json, created_at) "
            "VALUES (?, ?, ?, ?)",
            (user_id, action, json.dumps(details), time.time()),
        )

    def read_account_state(self, user_id):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT portfolio_json, settings_json FROM account_state "
                "WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if row is None:
                raise KeyError("Account state not found.")
            return json.loads(row["portfolio_json"]), json.loads(row["settings_json"])

    def save_account_state(self, user_id, portfolio_state, settings):
        with self._connect() as connection:
            connection.execute(
                "UPDATE account_state SET portfolio_json = ?, settings_json = ?, "
                "updated_at = ? WHERE user_id = ?",
                (
                    json.dumps(portfolio_state, allow_nan=False),
                    json.dumps(settings, allow_nan=False),
                    time.time(),
                    user_id,
                ),
            )

    def audit(self, user_id, action, details=None):
        with self._connect() as connection:
            self._audit(connection, user_id, action, details or {})

    def begin_paper_order(self, user_id, idempotency_key):
        if not idempotency_key or len(idempotency_key) > 128:
            raise ValueError("A valid idempotency key is required.")
        now = time.time()
        with self._connect() as connection:
            inserted = connection.execute(
                "INSERT OR IGNORE INTO paper_orders"
                "(user_id, idempotency_key, status, created_at, updated_at) "
                "VALUES (?, ?, 'pending', ?, ?)",
                (user_id, idempotency_key, now, now),
            )
            if inserted.rowcount == 1:
                return {"new": True, "status": "pending", "result": None}
            row = connection.execute(
                "SELECT status, result_json FROM paper_orders "
                "WHERE user_id = ? AND idempotency_key = ?",
                (user_id, idempotency_key),
            ).fetchone()
            return {
                "new": False,
                "status": row["status"],
                "result": (
                    json.loads(row["result_json"])
                    if row["result_json"] else None
                ),
            }

    def complete_paper_order(self, user_id, idempotency_key, result):
        with self._connect() as connection:
            connection.execute(
                "UPDATE paper_orders SET status = ?, result_json = ?, "
                "updated_at = ? WHERE user_id = ? AND idempotency_key = ?",
                (
                    str(result.get("status", "unknown")),
                    json.dumps(result, allow_nan=False),
                    time.time(),
                    user_id,
                    idempotency_key,
                ),
            )
