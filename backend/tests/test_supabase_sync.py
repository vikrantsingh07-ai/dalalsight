import json
import logging

from helpers import make_env

from cc.services.supabase_sync import SupabaseSync, convert, supabase_headers
from cc.storage.db import Database
from cc.storage.log_store import DatabaseLogHandler

URL = "https://project.supabase.co"
KEY = "test-supabase-secret"
TS = "2026-09-15T10:00:00+05:30"


class Reply:
    def __init__(self, status: int, text: str = ""):
        self.status_code = status
        self.text = text


class FakeSession:
    def __init__(self, status: int = 201):
        self.status = status
        self.calls: list[dict] = []

    def post(self, url, params=None, data=None, headers=None, timeout=None):
        self.calls.append({"method": "POST", "url": url, "params": params, "rows": json.loads(data), "headers": headers})
        return Reply(self.status, "" if self.status < 300 else "server error")

    def delete(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"method": "DELETE", "url": url, "params": params, "headers": headers})
        return Reply(204 if self.status < 300 else self.status)


def configured(db: Database, session: FakeSession) -> SupabaseSync:
    return SupabaseSync(make_env(supabase_url=URL, supabase_secret_key=KEY), db, session)


def queued(db: Database) -> list[tuple[str, str]]:
    return [(row["tbl"], row["pk"]) for row in db.query("SELECT tbl, pk FROM sync_outbox ORDER BY seq")]


def test_triggers_queue_inserts_updates_and_deletes():
    db = Database(":memory:")
    row_id = db.execute("INSERT INTO timeline(ts, kind, symbol, message, payload) VALUES (?, 'system', NULL, 'hi', '{}')", (TS,))
    db.execute("UPDATE timeline SET message = 'hello' WHERE id = ?", (row_id,))
    db.execute("DELETE FROM timeline WHERE id = ?", (row_id,))
    assert row_id == 1
    assert queued(db) == [("timeline", "1")] * 3


def test_sync_sends_current_rows_with_json_and_booleans_then_clears_the_queue():
    db = Database(":memory:")
    db.execute("INSERT INTO commentary(ts, symbol, timeframe, priority, text, text_source, speak, mode, payload) "
               "VALUES (?, 'NIFTY', '5m', 'HIGH', 'Breakout', 'engine', 1, 'live', ?)", (TS, '{"level": 23400}'))
    session = FakeSession()
    sync = configured(db, session)
    sync.drain()
    (call,) = session.calls
    assert call["url"] == f"{URL}/rest/v1/commentary" and call["params"] == {"on_conflict": "id"}
    assert call["rows"][0]["payload"] == {"level": 23400} and call["rows"][0]["speak"] is True
    assert call["headers"]["apikey"] == KEY and "Authorization" not in call["headers"]
    status = sync.status()
    assert queued(db) == [] and status["last_success"] and status["rows_sent"] == 1 and status["last_error"] is None


def test_each_changed_row_is_sent_once_with_its_latest_values():
    db = Database(":memory:")
    db.execute("INSERT INTO llm_usage(day, calls, errors) VALUES ('2026-09-15', 1, 0)")
    db.execute("UPDATE llm_usage SET calls = 2 WHERE day = '2026-09-15'")
    session = FakeSession()
    configured(db, session).drain()
    (call,) = session.calls
    assert call["params"] == {"on_conflict": "day"} and call["rows"] == [{"day": "2026-09-15", "calls": 2, "errors": 0}]


def test_rows_deleted_locally_are_deleted_in_supabase():
    db = Database(":memory:")
    alert_id = db.execute("INSERT INTO alerts(name, rule, channels, enabled, cooldown_seconds, created_at) VALUES ('x', '{}', '[]', 1, 900, ?)", (TS,))
    db.execute("DELETE FROM alerts WHERE id = ?", (alert_id,))
    session = FakeSession()
    configured(db, session).drain()
    assert [call["method"] for call in session.calls] == ["DELETE"]
    assert session.calls[0]["params"] == {"id": f'in.("{alert_id}")'}
    assert queued(db) == []


def test_a_failed_request_keeps_the_queue_and_reports_the_error():
    db = Database(":memory:")
    db.execute("INSERT INTO errors(ts, level, source, message, detail) VALUES (?, 'ERROR', 'test', 'boom', '')", (TS,))
    sync = configured(db, FakeSession(status=500))
    sync.drain()
    status = sync.status()
    assert status["pending"] == 1 and "HTTP 500" in status["last_error"] and status["last_success"] is None


def test_nothing_is_sent_without_supabase_settings():
    db = Database(":memory:")
    db.execute("INSERT INTO errors(ts, level, source, message, detail) VALUES (?, 'ERROR', 'test', 'boom', '')", (TS,))
    session = FakeSession()
    sync = SupabaseSync(make_env(), db, session)
    sync.drain()
    assert not sync.configured and session.calls == [] and sync.pending() == 1


def test_headers_and_conversion():
    assert "Authorization" not in supabase_headers(KEY)
    legacy = supabase_headers("eyJhbGciOiJIUzI1NiJ9.test", "return=minimal")
    assert legacy["Authorization"] == "Bearer eyJhbGciOiJIUzI1NiJ9.test" and legacy["Prefer"] == "return=minimal"
    assert convert("timeline", {"id": 1, "payload": "not json"}) == {"id": 1, "payload": "not json"}
    assert convert("alerts", {"enabled": 0, "rule": '{"kind": "price"}'}) == {"enabled": False, "rule": {"kind": "price"}}


def test_log_handler_keeps_own_info_and_other_warnings():
    db = Database(":memory:")
    handler = DatabaseLogHandler(db)

    def record(name: str, level: int, message: str) -> logging.LogRecord:
        return logging.LogRecord(name, level, __file__, 1, message, None, None)

    handler.handle(record("cc.monitor", logging.INFO, "cycle done"))
    handler.handle(record("yfinance", logging.INFO, "noise"))
    handler.handle(record("yfinance", logging.WARNING, "rate limited"))
    handler.handle(record("uvicorn.access", logging.WARNING, "GET /api/status"))
    rows = db.query("SELECT logger, message FROM app_logs ORDER BY id")
    assert [(row["logger"], row["message"]) for row in rows] == [("cc.monitor", "cycle done"), ("yfinance", "rate limited")]
    assert ("app_logs", "1") in queued(db)
