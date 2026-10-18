"""JSON-backed job queue. Every job is one JSON file under workspace/jobs/."""

import json
import os
import queue
import threading
import time
import uuid

from .engine import sanitize


class JobStore:
    def __init__(self, settings, presets):
        self.settings = settings
        self.presets = presets
        self.dir = os.path.join(settings["workspace"], "jobs")
        os.makedirs(self.dir, exist_ok=True)
        self.jobs = {}
        self.lock = threading.Lock()
        self.queue = queue.Queue()
        self._load()
        self.worker = threading.Thread(target=self._run, daemon=True)
        self.worker.start()

    def _load(self):
        for name in sorted(os.listdir(self.dir)):
            if not name.endswith(".json"):
                continue
            with open(os.path.join(self.dir, name), encoding="utf-8") as fh:
                job = json.load(fh)
            if job["status"] in ("queued", "running"):
                job["status"], job["error"] = "interrupted", "Server stopped before this job finished."
                self._save(job)
            self.jobs[job["id"]] = job

    def _save(self, job):
        path = os.path.join(self.dir, job["id"] + ".json")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(job, fh, indent=2)
        os.replace(tmp, path)

    def _update(self, job, **changes):
        with self.lock:
            job.update(changes)
            self._save(job)

    def submit(self, input_path, preset, output_dir=None):
        if preset not in self.presets:
            raise ValueError(f"Unknown preset '{preset}'")
        job = {
            "id": uuid.uuid4().hex[:12],
            "input": input_path,
            "preset": preset,
            "output_dir": output_dir or self.settings["default_output_dir"],
            "status": "queued",
            "progress": 0,
            "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "error": None,
            "report": None,
        }
        with self.lock:
            self.jobs[job["id"]] = job
            self._save(job)
        self.queue.put(job["id"])
        return job

    def list(self):
        with self.lock:
            return sorted((dict(j) for j in self.jobs.values()), key=lambda j: j["created"], reverse=True)

    def get(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            return dict(job) if job else None

    def clear_finished(self):
        with self.lock:
            done = [j for j in self.jobs.values() if j["status"] not in ("queued", "running")]
            for job in done:
                del self.jobs[job["id"]]
                os.remove(os.path.join(self.dir, job["id"] + ".json"))
        return len(done)

    def _run(self):
        while True:
            job = self.jobs[self.queue.get()]
            self._update(job, status="running")
            try:
                report = sanitize(job["input"], job["output_dir"], job["preset"], self.presets,
                                  self.settings, on_progress=lambda p: job.update(progress=p))
                self._update(job, status="done", progress=100, report=report)
            except Exception as exc:  # report every failure on the job, keep the worker alive
                self._update(job, status="failed", error=str(exc))
