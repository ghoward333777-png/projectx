"""Background jobs with status polling (the COL's queue)."""
from __future__ import annotations

import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor


class JobManager:
    def __init__(self, workers=2, keep=200):
        self.pool = ThreadPoolExecutor(workers)
        self.jobs, self.keep, self.lock = {}, keep, threading.Lock()

    def submit(self, kind, fn, *args, **kw):
        jid = uuid.uuid4().hex[:12]
        job = {"job_id": jid, "kind": kind, "status": "queued", "created": time.time(), "result": None, "error": None}
        with self.lock:
            self.jobs[jid] = job
            for old in sorted(self.jobs.values(), key=lambda j: j["created"])[:-self.keep]:
                self.jobs.pop(old["job_id"], None)

        def run():
            job["status"] = "running"
            try:
                job["result"] = fn(*args, **kw)
                job["status"] = "completed"
            except Exception as e:
                job["status"], job["error"] = "failed", "%s: %s" % (type(e).__name__, e)
                job["trace"] = traceback.format_exc()[-2000:]
            job["finished"] = time.time()
        self.pool.submit(run)
        return {"job_id": jid, "status": "queued"}

    def status(self, jid):
        return self.jobs.get(jid)
