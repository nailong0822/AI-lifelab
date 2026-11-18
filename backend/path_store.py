"""与检索任务关联的路径状态、版本和事件，写入采用 SQLite 事务。"""

import copy
import json
import time

from .store import Store, encode, uid


class PathConflict(Exception):
    pass


class PathStore:
    def __init__(self, store: Store):
        self.store = store
        with self.store.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS path_runs (
                    id TEXT PRIMARY KEY,
                    retrieval_run_id TEXT NOT NULL UNIQUE REFERENCES runs(id),
                    data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS path_events (
                    run_id TEXT NOT NULL REFERENCES path_runs(id), sequence INTEGER NOT NULL,
                    data TEXT NOT NULL, PRIMARY KEY(run_id, sequence)
                );
                CREATE TABLE IF NOT EXISTS path_versions (
                    run_id TEXT NOT NULL REFERENCES path_runs(id), version INTEGER NOT NULL,
                    data TEXT NOT NULL, PRIMARY KEY(run_id, version)
                );
            """)

    def get(self, run_id: str) -> dict:
        with self.store.connection() as db:
            row = db.execute("SELECT data FROM path_runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return json.loads(row[0])

    def for_retrieval(self, retrieval_id: str) -> dict | None:
        with self.store.connection() as db:
            row = db.execute("SELECT data FROM path_runs WHERE retrieval_run_id=?", (retrieval_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def create(self, source: dict, catalog: dict, cases: list[dict]) -> tuple[dict, bool]:
        now = time.time()
        run = {
            "id": uid(), "retrieval_run_id": source["id"], "created_at": now, "updated_at": now,
            "status": "running", "question": source["question"], "profile": source["profile"],
            "profile_version": source.get("profile_version", 0),
            "retrieval_clarification": source.get("clarification"),
            "source_cases": cases, "evidence_catalog": catalog, "source_gaps": source.get("gaps", []),
            "answers": {}, "clarified": False, "candidates": [], "selection": None,
            "input_request": None, "submissions": {}, "last_submission": None,
            "plan": None, "pending_revision": None, "version": 0, "versions": [],
            "current_stage_id": None, "progress": {}, "progress_revision": 0,
            "journey_status": "active", "operation": None, "operation_history": [],
            "model_calls": {}, "last_event_sequence": 0, "error": None, "stop_reason": None,
        }
        with self.store.connection() as db:
            cursor = db.execute("INSERT OR IGNORE INTO path_runs VALUES (?, ?, ?)",
                                (run["id"], source["id"], encode(run)))
            created = cursor.rowcount == 1
            db.commit()
        return (run if created else self.for_retrieval(source["id"])), created

    def mutate(self, run_id: str, action, *, event_type=None, title="", node="path", payload=None):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM path_runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            run = json.loads(row[0])
            now = time.time()
            operation = run.get("operation")
            if operation and operation.get("clock_started_at"):
                operation["active_seconds"] += max(0, now - operation["clock_started_at"])
                operation["clock_started_at"] = now
            result = action(run, db)
            run["updated_at"] = now
            if event_type:
                run["last_event_sequence"] += 1
                event = {"schema_version": 1, "run_id": run_id, "sequence": run["last_event_sequence"],
                         "event_type": event_type, "agent": "path_planner", "node": node,
                         "occurred_at": now, "title": title, "payload": payload or {}}
                db.execute("INSERT INTO path_events VALUES (?, ?, ?)", (run_id, event["sequence"], encode(event)))
            db.execute("UPDATE path_runs SET data=? WHERE id=?", (encode(run), run_id))
            db.commit()
        return result

    def change(self, run_id: str, changes: dict, **event):
        return self.mutate(run_id, lambda run, db: run.update(changes), **event)

    def emit(self, run_id: str, event_type: str, title: str, payload=None, node="path"):
        self.mutate(run_id, lambda run, db: None, event_type=event_type, title=title,
                    payload=payload, node=node)

    def events(self, run_id: str, after=0):
        with self.store.connection() as db:
            rows = db.execute("SELECT data FROM path_events WHERE run_id=? AND sequence>? ORDER BY sequence LIMIT 200",
                              (run_id, after)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def list_active(self):
        with self.store.connection() as db:
            rows = db.execute("SELECT data FROM path_runs").fetchall()
        return [run for row in rows if (run := json.loads(row[0]))["status"] == "running"]

    def snapshot(self, run_id: str):
        run = self.get(run_id)
        calls = run.pop("model_calls")
        run.pop("submissions")
        run.pop("last_submission")
        run["completed_work"] = self.completed_work(run_id)
        operation = run.get("operation")
        if operation:
            operation["elapsed_seconds"] = operation["active_seconds"] + (
                max(0, time.time() - operation["clock_started_at"]) if operation.get("clock_started_at") else 0)
            reserved = sum(call.get("reservation", 0) for call in calls.values()
                           if call.get("status") == "running" and call.get("operation_id") == operation["id"])
            operation["tokens_used"] = max(0, operation["tokens_used"] - reserved)
        return run

    def completed_work(self, run_id: str):
        run = self.get(run_id)
        with self.store.connection() as db:
            rows = db.execute("SELECT data FROM path_versions WHERE run_id=? ORDER BY version DESC", (run_id,)).fetchall()
        work = {}
        for row in rows:
            plan = json.loads(row[0])
            for stage in plan["stages"]:
                for task in stage.get("tasks", []):
                    key = stage["id"] + ":" + task["id"]
                    progress = run["progress"].get(key, {})
                    if progress.get("status") == "completed" and key not in work:
                        work[key] = {"id": key, "title": task["title"], "output": task["output"],
                                     "skills": task["skills"], "note": progress.get("note", ""),
                                     "updated_at": progress["updated_at"]}
        return sorted(work.values(), key=lambda item: -item["updated_at"])[:30]

    def version(self, run_id: str, version: int):
        with self.store.connection() as db:
            row = db.execute("SELECT data FROM path_versions WHERE run_id=? AND version=?", (run_id, version)).fetchone()
        if not row:
            raise KeyError(version)
        return json.loads(row[0])

    @staticmethod
    def check_version(run: dict, version: int):
        if run["version"] != version:
            raise PathConflict("计划版本已更新，请刷新后继续")

    def commit_plan(self, run_id: str, plan: dict, reason: str):
        def commit(run, db):
            if run["plan"] and run["plan"].get("operation_id") == run["operation"]["id"]:
                return
            run["version"] += 1
            saved = copy.deepcopy(plan)
            saved.update(version=run["version"], created_at=time.time(), reason=reason,
                         operation_id=run["operation"]["id"])
            db.execute("INSERT INTO path_versions VALUES (?, ?, ?)", (run_id, run["version"], encode(saved)))
            run["plan"] = saved
            run["versions"].append({"version": run["version"], "created_at": saved["created_at"],
                                    "title": saved["title"], "reason": reason})
            stage_ids = {stage["id"] for stage in saved["stages"]}
            if run["current_stage_id"] not in stage_ids:
                run["current_stage_id"] = next((stage["id"] for stage in saved["stages"]
                                                if not stage.get("already_completed")), saved["stages"][-1]["id"])
            run.update(status="ready", pending_revision=None, input_request=None, error=None, stop_reason=None)
        self.mutate(run_id, commit, event_type="plan.saved", title="路径计划与版本已保存")

    def update_progress(self, run_id: str, body):
        def update(run, db):
            self.check_version(run, body.version)
            if run["status"] != "ready":
                raise PathConflict("请在当前规划操作完成后更新任务")
            if run["journey_status"] == "paused":
                raise PathConflict("请先继续这段探索")
            stages = run["plan"]["stages"]
            stage = next((item for item in stages if item["id"] == body.stage_id), None)
            task = next((item for item in stage.get("tasks", []) if item["id"] == body.task_id), None) if stage else None
            if not task:
                raise PathConflict("任务不存在或该阶段尚未展开")
            position = next(index for index, item in enumerate(stages) if item["id"] == stage["id"])
            current = next(index for index, item in enumerate(stages) if item["id"] == run["current_stage_id"])
            if position > current:
                raise PathConflict("先完成当前阶段，再进入后续任务")
            key = stage["id"] + ":" + task["id"]
            if body.status in ("in_progress", "completed"):
                for dependency in task["depends_on"]:
                    status = run["progress"].get(stage["id"] + ":" + dependency, {}).get("status")
                    if status not in ("completed", "skipped"):
                        raise PathConflict("请先完成或跳过这个任务的前置步骤")
            previous = run["progress"].get(key, {})
            if previous.get("status") == body.status and previous.get("note", "") == body.note:
                return
            run["progress"][key] = {"status": body.status, "note": body.note,
                                    "updated_at": time.time(), "basis": "user_report", "task_title": task["title"]}
            run["progress_revision"] += 1
        self.mutate(run_id, update, event_type="progress.updated", title="任务进度已更新",
                    payload={"stage_id": body.stage_id, "task_id": body.task_id, "status": body.status, "note": body.note})
