import json
import os
from datetime import datetime, timezone
from typing import Any

import httpx
import psycopg
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

KIT_BASE_URL = os.getenv("KIT_BASE_URL", "http://10.34.21.100:8011/smartfarm").rstrip("/")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "30"))

app = FastAPI(title="Smart Farm Service", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS planning_runs (
    run_id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    source TEXT NOT NULL,
    current_day INTEGER,
    recommended_blueprint_id TEXT,
    payload JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS applied_blueprints (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    blueprint_id TEXT NOT NULL,
    payload JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS sensor_snapshots (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    twin_day INTEGER,
    payload JSONB NOT NULL
);
"""


def _db_conn():
    if not DATABASE_URL:
        return None
    return psycopg.connect(DATABASE_URL, autocommit=True, connect_timeout=3)


def _init_db() -> None:
    conn = _db_conn()
    if conn is None:
        return
    with conn:
        with conn.cursor() as cur:
            cur.execute(_SCHEMA)


@app.on_event("startup")
def startup() -> None:
    try:
        _init_db()
    except Exception as exc:  # DB may still be starting; keep proxy API alive.
        print(f"[smartfarm-service] DB init skipped: {type(exc).__name__}: {exc}", flush=True)


async def _kit(method: str, path: str, payload: Any | None = None) -> Any:
    url = f"{KIT_BASE_URL}{path}"
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        try:
            res = await client.request(method, url, json=payload)
            res.raise_for_status()
            return res.json()
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Kit API error: {exc}") from exc


def _persist_planning_run(state: dict[str, Any]) -> None:
    _init_db()
    run = state.get("planningRun")
    if not run:
        return
    conn = _db_conn()
    if conn is None:
        return
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO planning_runs (run_id, created_at, source, current_day, recommended_blueprint_id, payload)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (run_id) DO UPDATE SET
                    created_at = EXCLUDED.created_at,
                    source = EXCLUDED.source,
                    current_day = EXCLUDED.current_day,
                    recommended_blueprint_id = EXCLUDED.recommended_blueprint_id,
                    payload = EXCLUDED.payload
                """,
                (
                    run.get("runId"),
                    datetime.now(timezone.utc),
                    run.get("source", "unknown"),
                    run.get("currentDay"),
                    run.get("recommendedBlueprintId"),
                    json.dumps(run),
                ),
            )
    _persist_sensor_snapshot(state)


def _persist_sensor_snapshot(state: dict[str, Any]) -> None:
    _init_db()
    sensor = state.get("sensorState")
    if not sensor:
        return
    conn = _db_conn()
    if conn is None:
        return
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sensor_snapshots (twin_day, payload) VALUES (%s, %s)",
                (sensor.get("twinDay"), json.dumps(sensor)),
            )


def _persist_applied(state: dict[str, Any], blueprint_id: str) -> None:
    _init_db()
    conn = _db_conn()
    if conn is None:
        return
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO applied_blueprints (blueprint_id, payload) VALUES (%s, %s)",
                (blueprint_id, json.dumps(state)),
            )
    _persist_sensor_snapshot(state)


def _latest_planning_from_db() -> dict[str, Any] | None:
    _init_db()
    conn = _db_conn()
    if conn is None:
        return None
    with conn:
        with conn.cursor() as cur:
            cur.execute("SELECT payload FROM planning_runs ORDER BY created_at DESC LIMIT 1")
            row = cur.fetchone()
            if not row:
                return None
            payload = row[0]
            return payload if isinstance(payload, dict) else json.loads(payload)


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    db = "disabled"
    if DATABASE_URL:
        try:
            conn = _db_conn()
            assert conn is not None
            with conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
            db = "ok"
        except Exception as exc:  # noqa: BLE001 - health endpoint should report compact failure
            db = f"error:{type(exc).__name__}"
    return {"ok": True, "service": "smartfarm-service", "kitBaseUrl": KIT_BASE_URL, "db": db}


@app.api_route("/smartfarm/{path:path}", methods=["GET", "POST"])
async def smartfarm_proxy(path: str, request: Request, payload: dict[str, Any] = Body(default_factory=dict)):
    normalized = f"/{path}"
    if request.method == "GET" and normalized == "/planning/latest":
        try:
            latest = _latest_planning_from_db()
            if latest is not None:
                return {"ok": True, "message": "Latest planning run loaded from DB.", "planningRun": latest}
        except Exception as exc:
            print(f"[smartfarm-service] latest DB read skipped: {type(exc).__name__}: {exc}", flush=True)

    state = await _kit(request.method, normalized, payload if request.method != "GET" else None)

    try:
        if request.method == "GET" and normalized == "/state":
            _persist_sensor_snapshot(state)
        elif request.method == "POST" and normalized == "/planning/run":
            _persist_planning_run(state)
        elif request.method == "POST" and normalized == "/blueprint/generate":
            _persist_planning_run(state)
        elif request.method == "POST" and normalized == "/blueprint/apply":
            _persist_applied(state, payload.get("blueprintId") or payload.get("blueprint_id") or "unknown")
    except Exception as exc:  # Persistence must not break the POC control path.
        print(f"[smartfarm-service] persistence skipped: {type(exc).__name__}: {exc}", flush=True)

    return state
