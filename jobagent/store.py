"""SQLite-backed state for the autopilot agent.

status flow: new -> scored -> sent -> (auto) generated -> applied
             a selected job can branch to 'needs_attention' (LLM quota/API error or a
             manual external portal) until you Retry or Apply it; or 'skipped' if dismissed.

`agent_runs` records each autonomous run for the monitoring console. The `applications`
table is the imported/editable tracker history, separate from the `jobs` pipeline.
"""
import json
import sqlite3
from pathlib import Path
from typing import Iterable

from .models import Job

ROOT = Path(__file__).resolve().parent.parent

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id      TEXT PRIMARY KEY,
    source      TEXT,
    title       TEXT,
    company     TEXT,
    url         TEXT,
    location    TEXT,
    description TEXT,
    posted      TEXT,
    score       INTEGER,
    reasons     TEXT,
    gaps        TEXT,
    status      TEXT DEFAULT 'new',
    docs        TEXT,                 -- json: paths of generated files
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS applications (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    dedupe_key   TEXT UNIQUE,         -- url, else company|role (lowercased) — for upsert
    role         TEXT,
    company      TEXT,
    applied_date TEXT,
    stage        TEXT,
    location     TEXT,
    notes        TEXT,
    url          TEXT,
    source       TEXT DEFAULT 'import',
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at     TIMESTAMP,
    scanned         INTEGER DEFAULT 0,
    scored          INTEGER DEFAULT 0,
    matched         INTEGER DEFAULT 0,
    generated       INTEGER DEFAULT 0,
    needs_attention INTEGER DEFAULT 0,
    error           TEXT,
    status          TEXT DEFAULT 'running'
);
"""


class Store:
    def __init__(self, db_path: str):
        # check_same_thread=False + WAL: the web app creates a Store per request across
        # uvicorn's threadpool and a scheduler thread; WAL keeps reads/writes from blocking.
        self.conn = sqlite3.connect(ROOT / db_path, check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self):
        """Add V2 columns to an existing jobs table (no-op on a fresh DB)."""
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(jobs)")}
        if "applied_at" not in cols:
            self.conn.execute("ALTER TABLE jobs ADD COLUMN applied_at TIMESTAMP")
        if "flag_reason" not in cols:
            self.conn.execute("ALTER TABLE jobs ADD COLUMN flag_reason TEXT")

    def close(self):
        self.conn.close()

    # ---- jobs (agent pipeline) ----
    def upsert_job(self, job: Job) -> bool:
        """Insert if new. Returns True if it was newly inserted (so we don't re-score)."""
        cur = self.conn.execute("SELECT 1 FROM jobs WHERE job_id = ?", (job.job_id,))
        if cur.fetchone():
            return False
        self.conn.execute(
            """INSERT INTO jobs (job_id, source, title, company, url, location,
                                 description, posted)
               VALUES (?,?,?,?,?,?,?,?)""",
            (job.job_id, job.source, job.title, job.company, job.url,
             job.location, job.description, job.posted),
        )
        self.conn.commit()
        return True

    def save_score(self, job: Job):
        self.conn.execute(
            "UPDATE jobs SET score=?, reasons=?, gaps=?, status='scored' WHERE job_id=?",
            (job.score, job.reasons, job.gaps, job.job_id),
        )
        self.conn.commit()

    def get(self, job_id: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()

    def by_status(self, status: str) -> list[sqlite3.Row]:
        # Stable order so the digest's 1..N numbering is deterministic across calls.
        return self.conn.execute(
            "SELECT * FROM jobs WHERE status=? "
            "ORDER BY score DESC, created_at ASC, job_id ASC", (status,)
        ).fetchall()

    def top_unscored(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM jobs WHERE status='new'").fetchall()

    def all_docs(self) -> list[sqlite3.Row]:
        """Jobs that have generated documents, newest first (for the docs library)."""
        return self.conn.execute(
            "SELECT * FROM jobs WHERE docs IS NOT NULL AND docs != '' "
            "ORDER BY created_at DESC"
        ).fetchall()

    def set_status(self, job_id: str, status: str):
        self.conn.execute("UPDATE jobs SET status=? WHERE job_id=?", (status, job_id))
        self.conn.commit()

    def record_docs(self, job_id: str, paths: Iterable[str]):
        self.conn.execute(
            "UPDATE jobs SET docs=?, status='generated' WHERE job_id=?",
            (json.dumps(list(paths)), job_id),
        )
        self.conn.commit()

    # ---- autopilot: apply / triage / runs ----
    def ready_to_apply(self) -> list[sqlite3.Row]:
        """Agent-prepared jobs awaiting your action (have docs, not yet applied)."""
        return self.conn.execute(
            "SELECT * FROM jobs WHERE status='generated' AND applied_at IS NULL "
            "ORDER BY score DESC, created_at DESC"
        ).fetchall()

    def mark_applied(self, job_id: str):
        self.conn.execute(
            "UPDATE jobs SET applied_at=CURRENT_TIMESTAMP, status='applied' WHERE job_id=?",
            (job_id,))
        self.conn.commit()

    def unmark_applied(self, job_id: str):
        self.conn.execute(
            "UPDATE jobs SET applied_at=NULL, status='generated' WHERE job_id=?", (job_id,))
        self.conn.commit()

    def flag_job(self, job_id: str, reason: str):
        """Move a job into the triage queue with a human-readable reason."""
        self.conn.execute(
            "UPDATE jobs SET status='needs_attention', flag_reason=? WHERE job_id=?",
            (reason, job_id))
        self.conn.commit()

    def needs_attention(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM jobs WHERE status='needs_attention' "
            "ORDER BY score DESC, created_at ASC"
        ).fetchall()

    def retry_job(self, job_id: str):
        """Clear a triage flag so the job is eligible for the next run / manual generate."""
        self.conn.execute(
            "UPDATE jobs SET status='sent', flag_reason=NULL WHERE job_id=?", (job_id,))
        self.conn.commit()

    def start_run(self) -> int:
        cur = self.conn.execute("INSERT INTO agent_runs (status) VALUES ('running')")
        self.conn.commit()
        return cur.lastrowid

    def finish_run(self, run_id: int, *, status: str, scanned=0, scored=0, matched=0,
                   generated=0, needs_attention=0, error=None):
        self.conn.execute(
            """UPDATE agent_runs SET finished_at=CURRENT_TIMESTAMP, status=?, scanned=?,
                   scored=?, matched=?, generated=?, needs_attention=?, error=? WHERE id=?""",
            (status, scanned, scored, matched, generated, needs_attention, error, run_id))
        self.conn.commit()

    def list_runs(self, limit: int = 10) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM agent_runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    def today_stats(self) -> dict:
        r = self.conn.execute(
            "SELECT COALESCE(SUM(scanned),0) s, COALESCE(SUM(matched),0) m, "
            "COALESCE(SUM(generated),0) g FROM agent_runs WHERE date(started_at)=date('now')"
        ).fetchone()
        applied = self.conn.execute(
            "SELECT COUNT(*) c FROM jobs WHERE applied_at IS NOT NULL "
            "AND date(applied_at)=date('now')").fetchone()["c"]
        attention = self.conn.execute(
            "SELECT COUNT(*) c FROM jobs WHERE status='needs_attention'").fetchone()["c"]
        return {"scanned": r["s"], "matched": r["m"], "generated": r["g"],
                "applied": applied, "attention": attention}

    # ---- applications (editable tracker) ----
    def upsert_application(self, app: dict) -> str:
        """Insert or update by dedupe_key. Returns 'inserted' or 'updated'."""
        cur = self.conn.execute(
            "SELECT 1 FROM applications WHERE dedupe_key=?", (app.get("dedupe_key"),)
        )
        exists = cur.fetchone() is not None
        self.conn.execute(
            """INSERT INTO applications
                   (dedupe_key, role, company, applied_date, stage, location, notes, url, source)
               VALUES (:dedupe_key,:role,:company,:applied_date,:stage,:location,:notes,:url,:source)
               ON CONFLICT(dedupe_key) DO UPDATE SET
                   role=excluded.role, company=excluded.company,
                   applied_date=excluded.applied_date, stage=excluded.stage,
                   location=excluded.location, notes=excluded.notes, url=excluded.url""",
            {"dedupe_key": app.get("dedupe_key"), "role": app.get("role"),
             "company": app.get("company"), "applied_date": app.get("applied_date"),
             "stage": app.get("stage"), "location": app.get("location"),
             "notes": app.get("notes"), "url": app.get("url"),
             "source": app.get("source", "import")},
        )
        self.conn.commit()
        return "updated" if exists else "inserted"

    def list_applications(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM applications ORDER BY applied_date DESC, company ASC"
        ).fetchall()

    def get_application(self, app_id) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM applications WHERE id=?", (app_id,)).fetchone()

    def update_application(self, app_id, fields: dict):
        self.conn.execute(
            """UPDATE applications SET role=:role, company=:company,
                   applied_date=:applied_date, stage=:stage, location=:location,
                   notes=:notes WHERE id=:id""",
            {**fields, "id": app_id})
        self.conn.commit()

    def delete_application(self, app_id):
        self.conn.execute("DELETE FROM applications WHERE id=?", (app_id,))
        self.conn.commit()

    def set_application_stage(self, app_id, stage: str):
        self.conn.execute("UPDATE applications SET stage=? WHERE id=?", (stage, app_id))
        self.conn.commit()

    def add_application(self, fields: dict):
        """Insert a manually-added application (dedupe_key keeps re-imports tidy)."""
        key = (fields.get("url") or "").strip().lower() or \
            f"{(fields.get('company') or '').strip().lower()}|{(fields.get('role') or '').strip().lower()}"
        self.conn.execute(
            """INSERT OR IGNORE INTO applications
                   (dedupe_key, role, company, applied_date, stage, location, notes, source)
               VALUES (:dedupe_key,:role,:company,:applied_date,:stage,:location,:notes,'manual')""",
            {"dedupe_key": key or None,
             "role": fields.get("role", ""), "company": fields.get("company", ""),
             "applied_date": fields.get("applied_date", ""), "stage": fields.get("stage", ""),
             "location": fields.get("location", ""), "notes": fields.get("notes", "")})
        self.conn.commit()
