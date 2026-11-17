"""SQLite 任务、来源、证据与可续传事件存储。"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

from .config import Settings
from .ranking import analysis_stats, rank_key


def uid() -> str:
    return uuid.uuid4().hex


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def active_elapsed(run: dict) -> float:
    started = run.get("clock_started_at")
    return run["active_seconds"] + (max(0, time.time() - started) if started else 0)


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, created_at REAL NOT NULL, data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS run_events (
                    run_id TEXT NOT NULL REFERENCES runs(id), sequence INTEGER NOT NULL,
                    data TEXT NOT NULL, PRIMARY KEY(run_id, sequence)
                );
                CREATE TABLE IF NOT EXISTS queries (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
                    number INTEGER NOT NULL, data TEXT NOT NULL, UNIQUE(run_id, number)
                );
                CREATE TABLE IF NOT EXISTS sources (
                    id TEXT PRIMARY KEY, data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS search_hits (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
                    source_id TEXT NOT NULL REFERENCES sources(id), data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cases (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS evidence (
                    id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(id),
                    hit_id TEXT NOT NULL REFERENCES search_hits(id), data TEXT NOT NULL
                );
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
        finally:
            db.close()

    def create(self, question: str, settings: Settings) -> dict:
        now = time.time()
        run = {
            "id": uid(), "question": question, "created_at": now, "updated_at": now,
            "status": "running", "result_status": None, "stop_reason": None,
            "profile": None, "profile_version": 0, "clarification": None,
            "queries": [], "hits": [], "cases": [], "coverage": [], "gaps": [],
            "workflow_version": 2, "analyses": {},
            "model_calls": {}, "tokens_used": 0, "tokens_estimated": False, "has_estimated_usage": False,
            "active_seconds": 0.0, "clock_started_at": None, "request_count": 0,
            "last_event_sequence": 0, "report": None, "error": None,
            "limits": {
                "requests": settings.max_requests, "results_per_query": settings.results_per_query,
                "query_counts": list(settings.query_counts),
                "seconds": settings.active_seconds, "tokens": settings.token_budget,
                "reserve_seconds": settings.finalization_seconds,
            },
        }
        with self.connection() as db:
            db.execute("INSERT INTO runs VALUES (?, ?, ?)", (run["id"], now, encode(run)))
            db.commit()
        return run

    def get(self, run_id: str) -> dict:
        with self.connection() as db:
            row = db.execute("SELECT data FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return json.loads(row[0])

    def snapshot(self, run_id: str) -> dict:
        run = self.get(run_id)
        calls = run.pop("model_calls", {})
        reserved = sum(call.get("reserved_tokens", 0) for call in calls.values() if call.get("status") == "running")
        run["tokens_used"] = max(0, run["tokens_used"] - reserved)
        run["tokens_estimated"] = run.get("has_estimated_usage", False) or any(
            call.get("estimated", False) for call in calls.values() if call.get("status") != "running"
        )
        run["elapsed_seconds"] = round(active_elapsed(run), 2)
        run["cases"] = sorted(run["cases"], key=rank_key)
        run["analysis_stats"] = analysis_stats(run) if run.get("workflow_version") == 2 else None
        return run

    def list(self) -> list[dict]:
        with self.connection() as db:
            rows = db.execute("SELECT data FROM runs ORDER BY created_at DESC LIMIT 100").fetchall()
        keys = ["id", "question", "created_at", "updated_at", "status", "result_status", "stop_reason"]
        return [{key: run.get(key) for key in keys} for run in (json.loads(row[0]) for row in rows)]

    def mutate(self, run_id: str, action: Callable, *, event_type: str | None = None,
               node: str = "", title: str = "", payload: dict | None = None,
               span_id: str | None = None, query_id: str | None = None):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            run = json.loads(row[0])
            now = time.time()
            if run.get("clock_started_at"):
                run["active_seconds"] = active_elapsed(run)
                run["clock_started_at"] = now
            result = action(run, db)
            run["updated_at"] = now
            if event_type:
                run["last_event_sequence"] += 1
                event = {
                    "schema_version": 1, "run_id": run_id, "sequence": run["last_event_sequence"],
                    "event_type": event_type, "agent": "retrieval", "node": node,
                    "span_id": span_id, "parent_span_id": run_id, "query_id": query_id,
                    "occurred_at": now, "title": title, "payload": payload or {},
                }
                db.execute("INSERT INTO run_events VALUES (?, ?, ?)",
                           (run_id, event["sequence"], encode(event)))
            db.execute("UPDATE runs SET data=? WHERE id=?", (encode(run), run_id))
            db.commit()
        return result

    def change(self, run_id: str, changes: dict, **event):
        self.mutate(run_id, lambda run, db: run.update(changes), **event)

    def emit(self, run_id: str, event_type: str, node: str, title: str, payload=None, **extra):
        self.mutate(run_id, lambda run, db: None, event_type=event_type, node=node,
                    title=title, payload=payload, **extra)

    def events(self, run_id: str, after: int = 0) -> list[dict]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT data FROM run_events WHERE run_id=? AND sequence>? ORDER BY sequence LIMIT 200",
                (run_id, after),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def reserve_query(self, run_id: str, plan: dict, retry_of: str | None = None) -> dict | None:
        def reserve(run, db):
            if run["request_count"] >= run["limits"]["requests"]:
                return None
            run["request_count"] += 1
            query = {
                **plan, "id": uid(), "number": run["request_count"],
                "label": f"Q{plan.get('query_index', run['request_count']):02d}", "status": "running",
                "started_at": time.time(), "retry_of": retry_of, "result_count": 0,
                "duration_ms": None, "error": None,
            }
            run["queries"].append(query)
            db.execute("INSERT INTO queries VALUES (?, ?, ?, ?)",
                       (query["id"], run_id, query["number"], encode(query)))
            return query
        query = self.mutate(run_id, reserve)
        if query:
            self.emit(run_id, "search.started", "search", f"{query['label']} 正在检索知乎",
                      {"query": query}, span_id=query["id"], query_id=query["id"])
        return query

    def complete_query(self, run_id: str, query_id: str, hits: list[dict], error: str | None,
                       duration_ms: int, request_hash: str = ""):
        def save(run, db):
            query = next(item for item in run["queries"] if item["id"] == query_id)
            query.update(status="failed" if error else "completed", error=error,
                         duration_ms=duration_ms, result_count=len(hits), search_hash=request_hash)
            db.execute("UPDATE queries SET data=? WHERE id=?", (encode(query), query_id))
            existing = {hit["id"] for hit in run["hits"]}
            for hit in hits:
                db.execute("INSERT OR IGNORE INTO sources VALUES (?, ?)",
                           (hit["source_id"], encode(hit["source"])))
                db.execute("INSERT OR IGNORE INTO search_hits VALUES (?, ?, ?, ?)",
                           (hit["id"], run_id, hit["source_id"], encode(hit)))
                if hit["id"] not in existing:
                    run["hits"].append(hit)
                    existing.add(hit["id"])
        self.mutate(run_id, save, event_type="search.failed" if error else "search.completed",
                    node="search", title="检索请求失败" if error else "知乎检索已返回",
                    payload={"result_count": len(hits), "duration_ms": duration_ms, "error": error},
                    query_id=query_id, span_id=query_id)

    def save_cases(self, run_id: str, candidates: list[dict]) -> int:
        def save(run, db):
            changed = 0
            existing = {case["id"]: case for case in run["cases"]}
            for candidate in candidates:
                case = existing.get(candidate["id"])
                if case:
                    for name, fact in candidate["facts"].items():
                        if name not in case["facts"]:
                            case["facts"][name] = fact
                            changed += 1
                        elif fact["quote"] != case["facts"][name]["quote"]:
                            additional = {"field": name, **case["facts"][name]}
                            alternatives = case.setdefault("additional_evidence", [])
                            if additional not in alternatives:
                                alternatives.append(additional)
                                changed += int(fact["value"] != case["facts"][name]["value"])
                            case["facts"][name] = fact
                else:
                    case = candidate
                    run["cases"].append(case)
                    existing[case["id"]] = case
                    changed += 1
                for name in ("matching", "background_match", "background_differences", "applicability"):
                    if name in candidate:
                        case[name] = candidate[name]
                db.execute("INSERT INTO cases VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                           (case["id"], run_id, encode(case)))
                evidence = [{"field": name, **fact} for name, fact in case["facts"].items()]
                evidence.extend(case.get("additional_evidence", []))
                for fact in evidence:
                    evidence_id = hashlib.sha256(encode([case["id"], fact]).encode()).hexdigest()
                    db.execute("INSERT OR IGNORE INTO evidence VALUES (?, ?, ?, ?)",
                               (evidence_id, case["id"], fact["hit_id"], encode(fact)))
            return changed
        return self.mutate(run_id, save, event_type="case.extracted", node="extract",
                           title="案例与字段证据已保存", payload={"validated_candidates": len(candidates)})

    def recover(self, run_id: str):
        saved_seconds = self.get(run_id)["active_seconds"]
        def reset(run, db):
            run["active_seconds"] = saved_seconds
            run["clock_started_at"] = None
            for query in run["queries"]:
                if query["status"] == "running":
                    query.update(status="unknown", error="服务中断，该请求结果未确认，已计入预算")
                    db.execute("UPDATE queries SET data=? WHERE id=?", (encode(query), query["id"]))
            for call in run["model_calls"].values():
                if call.get("status") == "running":
                    call.update(status="unknown", estimated=True)
                    run["has_estimated_usage"] = True
        self.mutate(run_id, reset, event_type="run.recovered", node="recovery",
                    title="正在从已保存进度恢复任务")

    def settle_pending(self, run_id: str, reason: str):
        def settle(run, db):
            for query in run["queries"]:
                if query["status"] == "running":
                    query.update(status="cancelled" if reason == "cancelled" else "unknown",
                                 error="任务已结束，该请求结果未确认，已计入预算")
                    db.execute("UPDATE queries SET data=? WHERE id=?", (encode(query), query["id"]))
            for call in run["model_calls"].values():
                if call.get("status") == "running":
                    call.update(status="unknown", estimated=True)
                    run["has_estimated_usage"] = True
        self.mutate(run_id, settle)
