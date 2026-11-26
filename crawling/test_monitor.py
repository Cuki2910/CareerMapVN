import csv
import json
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import monitor


class MonitorTests(unittest.TestCase):
    def test_live_data_search_download_and_safe_routes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "data/continuous"
            (data / "events").mkdir(parents=True)
            dataset = root / "data/CareerMapVN_jobs.csv"
            with dataset.open("w", encoding="utf-8", newline="") as saved:
                writer = csv.writer(saved)
                writer.writerows([["job_title", "description"], ["Analyst", 'SQL, "BI"\nPython'], ["Engineer", "Build"]])
            state = data / "status.json"
            state.write_text(json.dumps({"status": "extracting", "pid": 99, "pending_total": 3, "secret": "must-not-leak"}))
            (data / "events/today.jsonl").write_text(json.dumps({"event": "api_request", "provider": "groq", "secret": "must-not-leak"}) + '\n{"incomplete":')
            with patch.object(monitor, "ROOT", root), patch.object(monitor, "DATASET", dataset), patch.object(monitor, "STATE", state), patch.object(monitor.os, "kill", side_effect=ProcessLookupError):
                with monitor.ThreadingHTTPServer(("127.0.0.1", 0), monitor.Handler) as server:
                    thread = Thread(target=server.serve_forever, daemon=True)
                    thread.start()
                    base = f"http://127.0.0.1:{server.server_port}"
                    try:
                        with urlopen(base + "/api/status") as response:
                            status = json.load(response)
                        self.assertEqual(status["csv_records"], 2)
                        self.assertFalse(status["worker_alive"])
                        self.assertNotIn("must-not-leak", json.dumps(status))
                        with urlopen(base + "/api/jobs?q=sql&page=99&size=10") as response:
                            jobs = json.load(response)
                        self.assertEqual((jobs["total"], jobs["page"]), (1, 1))
                        self.assertEqual(jobs["rows"][0]["description"], 'SQL, "BI"\nPython')
                        with urlopen(base + "/download.csv") as response:
                            self.assertEqual(response.read(), dataset.read_bytes())
                            self.assertIn("attachment", response.headers["Content-Disposition"])
                        for route, code in (("/.env", 404), ("/../.env", 404), ("/api/jobs?size=999", 400), ("/api/jobs?page=no", 400)):
                            with self.assertRaises(HTTPError) as error:
                                urlopen(base + route)
                            self.assertEqual(error.exception.code, code)
                        with self.assertRaises(HTTPError) as error:
                            urlopen(Request(base + "/api/status", headers={"Host": "evil.example"}))
                        self.assertEqual(error.exception.code, 403)
                    finally:
                        server.shutdown()
                        thread.join()


if __name__ == "__main__":
    unittest.main()
