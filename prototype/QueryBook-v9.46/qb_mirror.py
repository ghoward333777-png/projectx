#!/usr/bin/env python3
"""
qb_mirror.py — parallel internal→external drive offload for QueryBook (stdlib only).

Harvesting runs against a FAST internal drive; this mirror copies the store to a
(slower) external/USB drive IN THE BACKGROUND, in parallel, so the external copy
fills without ever blocking the harvest. Design:

  * Fact blocks (blocks/*.jsonl.gz / *.pack.gz) are copied with a thread pool — many
    files at once — since they are the bulk of the data and are append-only/immutable
    once rotated. Changed files (by size+mtime) are re-copied; a growing active block
    is re-copied each pass and completes on the final pass.
  * manifest.json is copied every pass (it is tiny) so the external counters track.
  * index.sqlite is copied with SQLite's ONLINE BACKUP API (consistent even while the
    harvester writes) periodically and on stop, so the external store is directly usable.

Everything is best-effort and caught: a full or unplugged external drive pauses the
mirror and reports an error; it never crashes or slows the harvester.
"""
import os, shutil, sqlite3, threading, time
from concurrent.futures import ThreadPoolExecutor


class Mirror:
    def __init__(self):
        self.lock = threading.Lock()
        self.state = {
            "running": False, "source": None, "dest": None,
            "files_copied": 0, "bytes_copied": 0, "blocks_total": 0, "blocks_copied": 0,
            "pending_files": 0, "last_sync": None, "last_error": None,
            "index_synced_at": None, "mbps": 0.0, "dest_free_gb": None, "passes": 0,
        }
        self.stop = False
        self.thread = None
        self.workers = int(os.environ.get("QB_MIRROR_WORKERS", "4") or "4")

    def status(self):
        with self.lock:
            s = dict(self.state)
        # live free space on the destination
        try:
            if s.get("dest") and os.path.isdir(s["dest"]):
                du = shutil.disk_usage(s["dest"])
                s["dest_free_gb"] = round(du.free / 1e9, 2)
        except Exception:
            pass
        return s

    def start(self, source, dest, interval=5):
        with self.lock:
            if self.state["running"]:
                return self.state
            self.stop = False
            os.makedirs(dest, exist_ok=True)
            self.state.update(running=True, source=os.path.abspath(source),
                              dest=os.path.abspath(dest), last_error=None)
        self.thread = threading.Thread(target=self._loop, args=(interval,), daemon=True)
        self.thread.start()
        return self.status()

    def stop_mirror(self):
        self.stop = True
        return {"stopping": True}

    # ---------------- internals ----------------
    def _copy_one(self, src, dst):
        tmp = dst + ".part"
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, tmp)
        os.replace(tmp, dst)                       # atomic on the destination
        return os.path.getsize(src)

    def _needs_copy(self, src, dst):
        try:
            ss = os.stat(src)
        except OSError:
            return False
        try:
            ds = os.stat(dst)
        except OSError:
            return True
        # re-copy if size differs or source is newer (append-only blocks grow)
        return (ss.st_size != ds.st_size) or (ss.st_mtime > ds.st_mtime + 1)

    def _sync_blocks(self, source, dest):
        sblocks = os.path.join(source, "blocks")
        dblocks = os.path.join(dest, "blocks")
        if not os.path.isdir(sblocks):
            return
        os.makedirs(dblocks, exist_ok=True)
        files = [f for f in os.listdir(sblocks) if not f.endswith(".part")]
        todo = [(os.path.join(sblocks, f), os.path.join(dblocks, f))
                for f in files if self._needs_copy(os.path.join(sblocks, f), os.path.join(dblocks, f))]
        with self.lock:
            self.state["blocks_total"] = len(files)
            self.state["pending_files"] = len(todo)
        if not todo:
            return
        t0 = time.time(); copied_bytes = 0
        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            futs = {ex.submit(self._copy_one, s, d): (s, d) for s, d in todo}
            for fu in futs:
                if self.stop:
                    break
                try:
                    b = fu.result()
                    copied_bytes += b
                    with self.lock:
                        self.state["files_copied"] += 1
                        self.state["blocks_copied"] += 1
                        self.state["bytes_copied"] += b
                        self.state["pending_files"] = max(0, self.state["pending_files"] - 1)
                except Exception as e:
                    with self.lock:
                        self.state["last_error"] = "block copy: " + str(e)
        dt = max(1e-6, time.time() - t0)
        with self.lock:
            self.state["mbps"] = round(copied_bytes / 1e6 / dt, 1)

    def _sync_file(self, source, dest, name):
        s = os.path.join(source, name); d = os.path.join(dest, name)
        if os.path.exists(s) and self._needs_copy(s, d):
            try:
                b = self._copy_one(s, d)
                with self.lock:
                    self.state["files_copied"] += 1; self.state["bytes_copied"] += b
            except Exception as e:
                with self.lock:
                    self.state["last_error"] = name + " copy: " + str(e)

    def _sync_index(self, source, dest):
        """Consistent copy of the SQLite index via the online backup API (safe during writes)."""
        src = os.path.join(source, "index.sqlite")
        if not os.path.exists(src):
            return
        dst = os.path.join(dest, "index.sqlite")
        tmp = dst + ".part"
        try:
            s = sqlite3.connect(src, timeout=30)
            d = sqlite3.connect(tmp, timeout=30)
            with d:
                s.backup(d)          # online, consistent snapshot
            s.close(); d.close()
            os.replace(tmp, dst)
            with self.lock:
                self.state["index_synced_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        except Exception as e:
            with self.lock:
                self.state["last_error"] = "index backup: " + str(e)
            try: os.remove(tmp)
            except OSError: pass

    def _loop(self, interval):
        source = self.state["source"]; dest = self.state["dest"]
        try:
            while not self.stop:
                p = self.state["passes"]
                try:
                    self._sync_blocks(source, dest)
                    self._sync_file(source, dest, "manifest.json")
                    self._sync_file(source, dest, "language_model.json")
                    self._sync_file(source, dest, "agents.json")
                    if p % 6 == 0:          # index is heavier — every ~6 passes
                        self._sync_index(source, dest)
                    with self.lock:
                        self.state["passes"] += 1
                        self.state["last_sync"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                        self.state["last_error"] = self.state["last_error"]  # keep last
                except Exception as e:
                    with self.lock:
                        self.state["last_error"] = str(e)
                for _ in range(max(1, int(interval))):
                    if self.stop:
                        break
                    time.sleep(1)
            # final consistent index copy on stop
            self._sync_index(source, dest)
        finally:
            with self.lock:
                self.state["running"] = False


MIRROR = Mirror()


def main():
    import sys
    if len(sys.argv) < 3:
        print("usage: python qb_mirror.py <internal_store> <external_dest> [--once]"); return
    src, dst = sys.argv[1], sys.argv[2]
    m = Mirror()
    if "--once" in sys.argv:
        m.state.update(source=src, dest=dst)
        m._sync_blocks(src, dst); m._sync_file(src, dst, "manifest.json"); m._sync_index(src, dst)
        import json; print(json.dumps(m.status(), indent=2)); return
    m.start(src, dst)
    try:
        while True:
            time.sleep(3)
            s = m.status()
            print("mirror: %d blocks, %.2f GB copied, %.1f MB/s, pending %d%s"
                  % (s["blocks_copied"], s["bytes_copied"]/1e9, s["mbps"], s["pending_files"],
                     "  ERR:" + s["last_error"] if s["last_error"] else ""))
    except KeyboardInterrupt:
        m.stop_mirror()


if __name__ == "__main__":
    main()
