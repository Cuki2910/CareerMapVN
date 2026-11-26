import argparse
import csv
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data/CareerMapVN_jobs.csv"
STATE = ROOT / "data/continuous/status.json"


def read_dataset():
    with DATASET.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        return reader.fieldnames or [], list(reader)


def snapshot():
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    pid = state.get("pid")
    alive = False
    if isinstance(pid, int) and pid > 0:
        try:
            os.kill(pid, 0)
            alive = True
        except ProcessLookupError:
            pass
        except PermissionError:
            alive = True
    fields, rows = read_dataset()
    result = {key: state.get(key) for key in (
        "pid", "status", "completed_total", "pending_total", "updated_at",
        "resume_at", "current_url", "requests_total", "input_tokens", "output_tokens",
    )}
    result.update(worker_alive=alive, csv_records=len(rows), csv_columns=len(fields),
                  csv_bytes=DATASET.stat().st_size, csv_path="data/CareerMapVN_jobs.csv",
                  server_time=datetime.now(timezone.utc).isoformat())
    event_fields = ("timestamp", "event", "provider", "model", "elapsed_seconds", "completed_total")
    events = []
    paths = sorted(path for path in (ROOT / "data/continuous/events").glob("*.jsonl")
                   if not path.name.startswith("._"))
    for path in paths[-2:]:
        with path.open("rb") as source:
            size = source.seek(0, 2)
            source.seek(max(0, size - 65536))
            if size > 65536:
                source.readline()
            for line in source:
                try:
                    event = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    continue
                events.append({key: event[key] for key in event_fields if key in event})
    result["events"] = events[-16:][::-1]
    return result


def page_of_jobs(query):
    page = int(query.get("page", ["1"])[0])
    size = int(query.get("size", ["25"])[0])
    term = query.get("q", [""])[0]
    if page < 1 or size not in (10, 25, 50, 100) or len(term) > 200:
        raise ValueError("Invalid page, size or search query")
    fields, rows = read_dataset()
    if term:
        rows = [row for row in rows if any(term.casefold() in value.casefold() for value in row.values() if value)]
    pages = max(1, math.ceil(len(rows) / size))
    page = min(page, pages)
    return dict(columns=fields, rows=rows[(page - 1) * size:page * size],
                total=len(rows), page=page, pages=pages)


class Handler(BaseHTTPRequestHandler):
    def send_content(self, content, content_type, status=200, download=False):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'")
        if download:
            self.send_header("Content-Disposition", 'attachment; filename="CareerMapVN_jobs.csv"')
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        if urlsplit("//" + self.headers.get("Host", "")).hostname not in ("127.0.0.1", "localhost"):
            self.send_content(b"Local access only", "text/plain", 403)
            return
        route = urlsplit(self.path)
        try:
            if route.path == "/":
                self.send_content(Path(__file__).with_name("monitor.html").read_bytes(), "text/html; charset=utf-8")
            elif route.path == "/download.csv":
                self.send_content(DATASET.read_bytes(), "text/csv; charset=utf-8", download=True)
            elif route.path in ("/api/status", "/api/jobs"):
                payload = snapshot() if route.path == "/api/status" else page_of_jobs(parse_qs(route.query))
                self.send_content(json.dumps(payload, ensure_ascii=False).encode(), "application/json; charset=utf-8")
            else:
                self.send_content(b"Not found", "text/plain", 404)
        except (ValueError, OverflowError):
            self.send_content(b"Invalid request or unreadable data; retry shortly", "text/plain", 400)
        except OSError:
            self.send_content(b"Dataset unavailable; retry shortly", "text/plain", 503)

    def log_message(self, format, *args):
        pass


def main():
    parser = argparse.ArgumentParser(description="Read-only local crawler monitor")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535")
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print(f"Crawler monitor: http://127.0.0.1:{args.port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
