import asyncio
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import run_continuous as worker


URL = "https://www.topcv.vn/viec-lam/analyst/123.html"
SOURCE = "# Analyst\n## Mô tả công việc\nAnalyze data\n## Yêu cầu ứng viên\nSQL"


class ContinuousChecks(unittest.IsolatedAsyncioTestCase):
    def test_url_discovery_and_redaction(self):
        markdown = f"[Job]({URL}?ref=search) [Again]({URL}) https://example.com/job.html"
        self.assertEqual(worker.job_urls(markdown), [URL])
        with patch.dict(os.environ, {"GEMINI_API_KEY": "real-test-secret"}):
            self.assertEqual(worker.safe_error(ValueError("real-test-secret AIzaOTHERKEY")), "[REDACTED] [REDACTED]")

    async def test_live_loop_logging_and_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(output_dir=Path(directory), interval=60, refresh_seconds=900, pages=1)
            (args.output_dir / "jobs").mkdir()
            (args.output_dir / "jobs/._resource.json").write_bytes(b"\x00\xb0")
            stop = asyncio.Event()
            model = SimpleNamespace(model_name="test", ainvoke=AsyncMock())

            async def response(prompt):
                stop.set()
                return SimpleNamespace(content='{"job_title":"Analyst"}', usage_metadata={"input_tokens": 5, "output_tokens": 3})

            model.ainvoke.side_effect = response
            fetch = AsyncMock(side_effect=[f"[Job]({URL})", SOURCE])
            with patch.object(worker.crawler, "initialize_chat_model", return_value=model), patch.object(
                worker.crawler, "crawl_markdown", fetch
            ), redirect_stdout(io.StringIO()):
                await worker.run(args, stop)
            job = json.loads(next(path for path in (args.output_dir / "jobs").glob("*.json") if not path.name.startswith("._")).read_text())
            self.assertEqual(job["job_title"], "Analyst")
            self.assertEqual(job["description"], "Analyze data")
            self.assertEqual(job["url"], URL)
            state = json.loads((args.output_dir / "status.json").read_text())
            self.assertEqual((state["status"], state["completed_total"], state["input_tokens"]), ("stopped", 1, 5))
            events = [json.loads(line) for line in next((args.output_dir / "events").glob("*.jsonl")).read_text().splitlines()]
            self.assertIn("job_completed", [event["event"] for event in events])
            self.assertTrue(list((args.output_dir / "sources").glob("*.markdown")))
            stop = asyncio.Event()

            async def listing(url):
                stop.set()
                return f"[Job]({URL})"

            model.ainvoke.reset_mock()
            with patch.object(worker.crawler, "initialize_chat_model", return_value=model), patch.object(
                worker.crawler, "crawl_markdown", side_effect=listing
            ), redirect_stdout(io.StringIO()):
                await worker.run(args, stop)
            model.ainvoke.assert_not_awaited()

    async def test_quota_error_is_logged_without_spinning(self):
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(output_dir=Path(directory), interval=60, refresh_seconds=900, pages=1)
            stop = asyncio.Event()
            model = SimpleNamespace(model_name="test", ainvoke=AsyncMock())

            async def response(prompt):
                stop.set()
                error = RuntimeError("429 quota test-secret")
                error.status_code = 429
                raise error

            model.ainvoke.side_effect = response
            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-secret"}), patch.object(
                worker.crawler, "initialize_chat_model", return_value=model
            ), patch.object(worker.crawler, "crawl_markdown", AsyncMock(side_effect=[f"[Job]({URL})", SOURCE])), redirect_stdout(io.StringIO()):
                await worker.run(args, stop)
            state = json.loads((args.output_dir / "status.json").read_text())
            self.assertEqual(state["failures"], {})
            self.assertEqual(state["requests_total"], 1)
            events = next((args.output_dir / "events").glob("*.jsonl")).read_text()
            self.assertNotIn("test-secret", events)
            self.assertIn('"quota": true', events)


if __name__ == "__main__":
    unittest.main()
