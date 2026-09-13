"""Gunicorn settings for FaceID Attendance.

Why these numbers and not the defaults:

* Face recognition is CPU-bound and holds the interpreter for seconds at a
  time. The default 30-second timeout kills a worker in the middle of a scan
  of a large class photo, so the teacher sees a blank error instead of the
  roster. 300 seconds is generous but finite.
* dlib and numpy already use several threads internally. Running many
  gunicorn workers on top of that makes them fight for the same cores and
  everything gets slower. Two workers is a sane default for a small VM.
* SQLite is a single file. Workers share it fine for this workload (one
  teacher taking one class at a time) because db.connect() enables WAL,
  but hundreds of workers writing at once would not be fine.

Everything here can be overridden with the usual gunicorn environment
variables, e.g. WEB_CONCURRENCY=4.
"""

import multiprocessing
import os


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


bind = f"{os.environ.get('HOST', '0.0.0.0')}:{os.environ.get('PORT', '8000')}"

# Two workers, or fewer if the machine is tiny. Never more than 4 by default:
# each worker loads its own copy of the face encodings.
_cpus = multiprocessing.cpu_count()
workers = _int("WEB_CONCURRENCY", max(1, min(4, _cpus // 2 or 1)))

# Threads, not extra processes, for the cheap requests (pages, Excel export)
# that happen while a scan is running.
threads = _int("GUNICORN_THREADS", 4)
worker_class = os.environ.get("GUNICORN_WORKER_CLASS", "gthread")

# A big class photo can take a while to decode, detect and encode.
timeout = _int("GUNICORN_TIMEOUT", 300)
graceful_timeout = 30
keepalive = 5

# Recycle workers occasionally: numpy/dlib allocations fragment memory over
# a long semester of uploads.
max_requests = _int("GUNICORN_MAX_REQUESTS", 400)
max_requests_jitter = 50

# Multi-megabyte photo uploads arrive in long request bodies.
limit_request_line = 8190
limit_request_field_size = 16380

accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")

# Honour X-Forwarded-Proto from the platform's load balancer so that
# url_for(..., _external=True) and secure cookies behave behind HTTPS.
forwarded_allow_ips = os.environ.get("FORWARDED_ALLOW_IPS", "*")

# Keep the temp directory in memory where possible; some containers have a
# read-only /tmp mount.
worker_tmp_dir = os.environ.get("WORKER_TMP_DIR") or None


def on_starting(server):
    server.log.info(
        "FaceID Attendance starting: %s worker(s), %s thread(s), %ss timeout",
        workers,
        threads,
        timeout,
    )
    if not os.environ.get("SECRET_KEY"):
        server.log.warning(
            "SECRET_KEY is not set. Every restart will log all teachers out."
        )
