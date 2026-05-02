import sqlite3
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import DB_PATH

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

DOWNLOADS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS downloads (
    complete_url TEXT PRIMARY KEY,
    institution TEXT,
    type TEXT,
    year TEXT,
    class TEXT,
    subject TEXT,
    md5 TEXT,
    size INTEGER,
    path TEXT,
    content_type TEXT,
    etag TEXT,
    last_modified TEXT,
    pdfs_json TEXT,
    ts TEXT
);
"""

MD5_MAP_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS md5_map (
    md5 TEXT PRIMARY KEY,
    path TEXT,
    size INTEGER,
    ts TEXT
);
"""


def _get_existing_columns(conn: sqlite3.Connection, table_name: str) -> set:
    try:
        cur = conn.cursor()
        cur.execute(f"PRAGMA table_info({table_name})")
        return {row[1] for row in cur.fetchall()}
    except sqlite3.OperationalError:
        return set()


def migrate(conn: sqlite3.Connection):
    cur = conn.cursor()

    expected_downloads = {
        "complete_url", "institution", "type", "year", "class", "subject",
        "md5", "size", "path", "content_type", "etag", "last_modified",
        "pdfs_json", "ts",
    }

    downloads_cols = _get_existing_columns(conn, "downloads")
    if not downloads_cols:
        logging.info("DB migration: creating downloads table")
        cur.execute(DOWNLOADS_TABLE_SQL)
        conn.commit()
        downloads_cols = _get_existing_columns(conn, "downloads")

    missing = expected_downloads - downloads_cols
    for col in missing:
        typ = "INTEGER" if col == "size" else "TEXT"
        logging.info(f"DB migration: adding column '{col}' to downloads (type {typ})")
        cur.execute(f"ALTER TABLE downloads ADD COLUMN {col} {typ}")

    expected_md5map = {"md5", "path", "size", "ts"}
    md5map_cols = _get_existing_columns(conn, "md5_map")
    if not md5map_cols:
        logging.info("DB migration: creating md5_map table")
        cur.execute(MD5_MAP_TABLE_SQL)
    else:
        missing2 = expected_md5map - md5map_cols
        for col in missing2:
            typ = "INTEGER" if col == "size" else "TEXT"
            logging.info(f"DB migration: adding column '{col}' to md5_map (type {typ})")
            cur.execute(f"ALTER TABLE md5_map ADD COLUMN {col} {typ}")

    conn.commit()


def init_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    migrate(conn)
    return conn


class DBManager:
    def __init__(self, db_path: str = "downloads.db"):
        self.db_path = Path(db_path)
        self.conn = self._init_db()
        if self.conn:
            self.conn.row_factory = self._dict_factory

    def _dict_factory(self, cursor, row):
        fields = [column[0] for column in cursor.description]
        return {key: value for key, value in zip(fields, row)}

    def _init_db(self):
        try:
            conn = sqlite3.connect(str(self.db_path))
            migrate(conn)
            return conn
        except sqlite3.Error as e:
            logging.error(f"Database connection failed: {e}")
            return None

    def close(self):
        if self.conn:
            self.conn.close()
            logging.info("Database connection closed.")

    # --- Crawler-style helpers ---

    def get_download(self, url: str) -> Optional[dict]:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT complete_url, institution, type, year, class, subject, md5, size, path, content_type, etag, last_modified, pdfs_json, ts FROM downloads WHERE complete_url = ?",
            (url,),
        )
        row = cur.fetchone()
        if row:
            keys = [
                "complete_url", "institution", "type", "year", "class", "subject",
                "md5", "size", "path", "content_type", "etag", "last_modified",
                "pdfs_json", "ts",
            ]
            res = dict(zip(keys, row))
            if res.get("pdfs_json"):
                try:
                    res["pdfs"] = json.loads(res["pdfs_json"])
                except Exception:
                    res["pdfs"] = []
            else:
                res["pdfs"] = []
            return res
        return None

    def insert_download(self, complete_url: str, institution: str, typ: str, year: str, cls: str,
                        subject: str, md5: str, size: int, path: str, content_type: str,
                        pdfs: list, etag: Optional[str] = None, last_modified: Optional[str] = None):
        cur = self.conn.cursor()
        pdfs_json = json.dumps(pdfs or [])
        cur.execute(
            """
            INSERT OR REPLACE INTO downloads(complete_url, institution, type, year, class, subject, md5, size, path, content_type, etag, last_modified, pdfs_json, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                complete_url, institution or "", typ or "", year or "", cls or "", subject or "",
                md5 or "", size or 0, path or "", content_type or "", etag or "", last_modified or "",
                pdfs_json, datetime.utcnow().isoformat(),
            ),
        )
        self.conn.commit()

    def get_md5_map(self, md5: str) -> Optional[dict]:
        cur = self.conn.cursor()
        cur.execute("SELECT md5, path, size, ts FROM md5_map WHERE md5 = ?", (md5,))
        row = cur.fetchone()
        if row:
            keys = ["md5", "path", "size", "ts"]
            return dict(zip(keys, row))
        return None

    def insert_md5_map(self, md5: str, path: str, size: int):
        cur = self.conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO md5_map(md5, path, size, ts) VALUES (?, ?, ?, ?)",
            (md5, path, size, datetime.utcnow().isoformat()),
        )
        self.conn.commit()

    # --- Manager-style helpers ---

    def add_or_update_download(self, **kwargs):
        if "complete_url" not in kwargs:
            raise ValueError("'complete_url' is a required argument.")

        fields = [
            "complete_url", "institution", "type", "year", "class", "subject",
            "md5", "size", "path", "content_type", "etag", "last_modified",
            "pdfs_json", "ts",
        ]

        kwargs["ts"] = datetime.utcnow().isoformat()
        if "pdfs_json" in kwargs and isinstance(kwargs["pdfs_json"], list):
            kwargs["pdfs_json"] = json.dumps(kwargs["pdfs_json"])

        values = [kwargs.get(field) for field in fields]

        sql = f"""
            INSERT OR REPLACE INTO downloads ({', '.join(fields)})
            VALUES ({', '.join(['?'] * len(fields))})
        """

        try:
            cur = self.conn.cursor()
            cur.execute(sql, values)
            self.conn.commit()
            return cur.lastrowid
        except sqlite3.Error as e:
            logging.error(f"Failed to add/update record for {kwargs['complete_url']}: {e}")
            return None

    def get_download_by_url(self, url: str) -> Optional[dict]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM downloads WHERE complete_url = ?", (url,))
        return cur.fetchone()

    def update_record(self, url: str, updates: dict) -> bool:
        if not updates or not isinstance(updates, dict):
            logging.warning("Update called with no fields to update.")
            return False

        updates["ts"] = datetime.utcnow().isoformat()
        set_clause = ", ".join([f"{key} = ?" for key in updates.keys()])
        values = list(updates.values()) + [url]

        sql = f"UPDATE downloads SET {set_clause} WHERE complete_url = ?"

        try:
            cur = self.conn.cursor()
            cur.execute(sql, values)
            self.conn.commit()
            return cur.rowcount > 0
        except sqlite3.Error as e:
            logging.error(f"Failed to update record for {url}: {e}")
            return False

    def search(self, limit=None, offset=None, **kwargs):
        where_clauses = []
        params = []

        for key, value in kwargs.items():
            if isinstance(value, str) and "%" in value:
                where_clauses.append(f"LOWER({key}) LIKE ?")
                params.append(value.lower())
            else:
                where_clauses.append(f"{key} = ?")
                params.append(value)

        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
        query = f"SELECT * FROM downloads WHERE {where_sql}"

        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        if offset is not None:
            query += " OFFSET ?"
            params.append(offset)

        try:
            cur = self.conn.cursor()
            cur.execute(query, params)
            return cur.fetchall()
        except sqlite3.Error as e:
            logging.error(f"Search failed: {e}")
            return []
