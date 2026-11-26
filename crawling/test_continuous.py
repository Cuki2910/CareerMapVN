import asyncio
from contextlib import redirect_stdout
import csv
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import run_continuous as worker


URL = "https://www.topcv.vn/viec-lam/analyst/123.html"
SOURCE = "# Analyst\n## Mô tả công việc\nAnalyze data\n## Yêu cầu ứng viên\nSQL"
SEARCH = "https://www.topcv.vn/tim-viec-lam-data-analyst"
BRAND = "https://www.topcv.vn/brand/company/tuyen-dung/analyst-j456.html"


def listing_html(url=URL, next_url=None):
    link = f'<div class="box-pagination"><a rel="next" data-href="{next_url}">Next</a></div>' if next_url else ""
    return f'<div class="job-list-main"><div class="job-item-search-result"><h3 class="title"><a href="{url}">Job</a></h3></div>{link}</div>'


async def fake_pages(url, max_pages, stop):
    yield {"url": url, "page": 1, "urls": [URL], "next_url": None}


class ContinuousChecks(unittest.IsolatedAsyncioTestCase):
    async def check_discovery_backoff(self, blocks, expected_waits, previous_streak=0):
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(output_dir=Path(directory), interval=10, refresh_seconds=900, pages=1)
            (args.output_dir / "status.json").write_text(json.dumps({"website_block_streak": previous_streak}))
            stop = asyncio.Event()
            clock = [0]
            waits = []
            calls = []

            async def listing(url, pages, signal):
                calls.append(clock[0])
                if len(calls) <= len(blocks):
                    raise worker.crawler.WebsiteBlocked("Listing blocked (HTTP 429)", 429, blocks[len(calls) - 1])
                stop.set()
                yield {"url": url, "page": 1, "urls": [], "next_url": None}

            async def advance(awaitable, timeout):
                awaitable.close()
                waits.append(timeout)
                clock[0] += timeout
                raise TimeoutError

            model = SimpleNamespace(model_name="test", ainvoke=AsyncMock())
            with patch.object(worker.crawler, "initialize_chat_model", return_value=model), patch.object(
                worker, "listing_pages", listing
            ), patch.object(worker.asyncio, "wait_for", side_effect=advance), patch.object(
                worker.time, "monotonic", side_effect=lambda: clock[0]
            ), patch.object(worker.time, "time", side_effect=lambda: 1000000 + clock[0]), redirect_stdout(io.StringIO()):
                await worker.run(args, stop)
            self.assertEqual(waits[:len(blocks)], expected_waits)
            self.assertEqual(calls, [sum(expected_waits[:index]) for index in range(len(blocks) + 1)])
            state = json.loads((args.output_dir / "status.json").read_text())
            self.assertEqual(state["website_block_streak"], 0)
            self.assertIsNone(state["discovery_resume_at"])
            model.ainvoke.assert_not_awaited()

    async def test_discovery_retries_after_backoff_without_extra_refresh(self):
        await self.check_discovery_backoff([None] * 5, [300, 600, 1200, 1800, 1800])

    async def test_discovery_respects_retry_after(self):
        await self.check_discovery_backoff(["3600"], [3600])

    async def test_discovery_restores_consecutive_blocks(self):
        await self.check_discovery_backoff([None], [1200], previous_streak=2)

    async def test_router_logs_each_attempt_and_invalid_output_usage(self):
        from test_provider_router import provider

        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(output_dir=Path(directory), interval=15, refresh_seconds=900, pages=1)
            stop = asyncio.Event()
            primary, backup = provider("gemini", "not json"), provider("groq")

            async def response(prompt):
                stop.set()
                return SimpleNamespace(content='{"job_title":"Analyst"}', usage_metadata={"input_tokens": 7, "output_tokens": 2})

            backup[1].ainvoke.side_effect = response
            router = worker.crawler.ProviderRouter([primary, backup])
            with patch.object(worker.crawler, "initialize_chat_model", return_value=router), patch.object(
                worker.crawler, "crawl_markdown", AsyncMock(return_value=SOURCE)
            ) as fetch, patch.object(worker, "listing_pages", fake_pages), redirect_stdout(io.StringIO()):
                await worker.run(args, stop)
            state = json.loads((args.output_dir / "status.json").read_text())
            self.assertEqual((state["requests_total"], state["input_tokens"], state["output_tokens"]), (2, 12, 5))
            self.assertEqual(state["completed_total"], 1)
            self.assertEqual(state["provider_resume_at"]["groq"], 0)
            events = [json.loads(line) for line in next((args.output_dir / "events").glob("*.jsonl")).read_text().splitlines()]
            self.assertEqual([event["provider"] for event in events if event["event"] == "api_request"], ["gemini", "groq"])
            self.assertIn("api_invalid_output", [event["event"] for event in events])
            self.assertEqual(len(list((args.output_dir / "sources").glob("*.response.json"))), 3)
            fetch.assert_awaited_once()

    async def test_router_migrates_legacy_gemini_cooldown_without_pausing_backups(self):
        from test_provider_router import provider

        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(output_dir=Path(directory), interval=15, refresh_seconds=900, pages=1)
            resume_at = worker.datetime.fromtimestamp(worker.time.time() + 1800, worker.timezone.utc).isoformat()
            (args.output_dir / "status.json").write_text(json.dumps({"api_resume_at": resume_at}))
            stop = asyncio.Event()
            primary, backup = provider("gemini"), provider("groq")

            async def response(prompt):
                stop.set()
                return SimpleNamespace(content='{"job_title":"Analyst"}', usage_metadata={})

            backup[1].ainvoke.side_effect = response
            router = worker.crawler.ProviderRouter([primary, backup])
            with patch.object(worker.crawler, "initialize_chat_model", return_value=router), patch.object(
                worker.crawler, "crawl_markdown", AsyncMock(return_value=SOURCE)
            ), patch.object(worker, "listing_pages", fake_pages), redirect_stdout(io.StringIO()):
                await worker.run(args, stop)
            primary[1].ainvoke.assert_not_awaited()
            backup[1].ainvoke.assert_awaited_once()
            self.assertEqual(router.cooldowns["gemini"], worker.datetime.fromisoformat(resume_at).timestamp())

    async def test_router_restores_all_cooldowns_before_fetching(self):
        from test_provider_router import provider

        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(output_dir=Path(directory), interval=15, refresh_seconds=900, pages=1)
            cooldowns = {"gemini": worker.time.time() + 3600, "groq": worker.time.time() + 1800}
            (args.output_dir / "status.json").write_text(json.dumps({"provider_resume_at": cooldowns, "provider_index": 1, "requests_total": 11}))
            stop = asyncio.Event()
            router = worker.crawler.ProviderRouter([provider("gemini"), provider("groq")])

            async def stop_wait(awaitable, timeout):
                awaitable.close()
                self.assertGreater(timeout, 1700)
                stop.set()

            with patch.object(worker.crawler, "initialize_chat_model", return_value=router), patch.object(
                worker, "listing_pages"
            ) as discover, patch.object(worker.asyncio, "wait_for", side_effect=stop_wait), redirect_stdout(io.StringIO()):
                await worker.run(args, stop)
            discover.assert_not_called()
            self.assertEqual((router.cooldowns, router.next_index), (cooldowns, 1))
            state = json.loads((args.output_dir / "status.json").read_text())
            self.assertEqual(state["requests_total"], 11)

    async def test_router_all_errors_preserve_pending_job(self):
        from test_provider_router import api_error, provider

        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(output_dir=Path(directory), interval=15, refresh_seconds=900, pages=1)
            stop = asyncio.Event()
            primary, backup = provider("gemini"), provider("groq")
            primary[1].ainvoke.side_effect = api_error(429)

            async def fail(prompt):
                stop.set()
                raise api_error(429, message="tokens per minute (TPM)")

            backup[1].ainvoke.side_effect = fail
            router = worker.crawler.ProviderRouter([primary, backup])
            with patch.object(worker.crawler, "initialize_chat_model", return_value=router), patch.object(
                worker.crawler, "crawl_markdown", AsyncMock(return_value=SOURCE)
            ), patch.object(worker, "listing_pages", fake_pages), redirect_stdout(io.StringIO()):
                await worker.run(args, stop)
            state = json.loads((args.output_dir / "status.json").read_text())
            self.assertEqual((state["failures"], state["requests_total"]), ({}, 2))
            self.assertEqual(json.loads((args.output_dir / "pending.json").read_text()), [URL])
            remaining = worker.datetime.fromisoformat(state["api_resume_at"]).timestamp() - worker.time.time()
            self.assertGreater(remaining, 60)
            self.assertLessEqual(remaining, 65)

    def test_category_expansion_uses_only_public_topcv_category_links(self):
        category = "https://www.topcv.vn/tim-viec-lam-cong-nghe-thong-tin-cr257"
        specialty = "https://www.topcv.vn/tim-viec-lam-data-analyst-cr257cb261cl145"
        html = "".join(f'<a href="{url}">Search</a>' for url in (
            specialty, category, category, "/tim-viec-lam-marketing-cr92", SEARCH,
            "https://example.com/tim-viec-lam-other-cr123", category + "?page=2",
        ))
        links = worker.category_search_urls(html, SEARCH)
        self.assertEqual(links, [category, "https://www.topcv.vn/tim-viec-lam-marketing-cr92", specialty])

    def test_main_results_brands_and_real_pagination(self):
        html = listing_html(BRAND, SEARCH + "?page=2") + f'<footer><a href="{URL}">Recommendation</a></footer>'
        self.assertEqual(worker.listing_data(html, SEARCH), {"urls": [BRAND], "next_url": SEARCH + "?page=2"})
        self.assertEqual(worker.job_id(BRAND), "456")
        self.assertEqual(worker.job_id("https://www.topcv.vn/viec-lam/analyst/456.html"), "456")
        self.assertEqual(worker.job_urls(BRAND), [BRAND])
        with self.assertRaisesRegex(ValueError, "No main"):
            worker.listing_data(f'<footer><a href="{URL}">Recommendation</a></footer>', SEARCH)
        with self.assertRaisesRegex(ValueError, "Unexpected pagination"):
            worker.listing_data(listing_html(URL, "https://example.com/page=2"), SEARCH)

    async def test_pagination_clicks_next_in_same_session_and_stops(self):
        responses = [
            SimpleNamespace(success=True, status_code=200, html=listing_html(URL, SEARCH + "?page=2")),
            SimpleNamespace(success=True, status_code=200, html=listing_html(BRAND)),
        ]
        browser = MagicMock()
        browser.__aenter__ = AsyncMock(return_value=browser)
        browser.__aexit__ = AsyncMock(return_value=False)
        browser.arun = AsyncMock(side_effect=responses)
        stop = SimpleNamespace(is_set=lambda: False, wait=AsyncMock(side_effect=TimeoutError))
        with patch("crawl4ai.AsyncWebCrawler", return_value=browser):
            pages = [page async for page in worker.listing_pages(SEARCH, 5, stop)]
        self.assertEqual(len(pages), 2)
        first, second = browser.arun.await_args_list
        self.assertFalse(first.kwargs["config"].js_only)
        self.assertTrue(second.kwargs["config"].js_only)
        self.assertEqual(first.kwargs["config"].session_id, second.kwargs["config"].session_id)
        self.assertIn(".click()", second.kwargs["config"].js_code_before_wait)
        self.assertIsNone(second.kwargs["config"].js_code)
        self.assertEqual(pages[1]["urls"], [BRAND])

    async def test_duplicate_and_blocked_pages_are_not_new_results(self):
        browser = MagicMock()
        browser.__aenter__ = AsyncMock(return_value=browser)
        browser.__aexit__ = AsyncMock(return_value=False)
        response = SimpleNamespace(success=True, status_code=200, html=listing_html(URL, SEARCH + "?page=2"))
        browser.arun = AsyncMock(side_effect=[response, response])
        stop = SimpleNamespace(is_set=lambda: False, wait=AsyncMock(side_effect=TimeoutError))
        with patch("crawl4ai.AsyncWebCrawler", return_value=browser):
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                _ = [page async for page in worker.listing_pages(SEARCH, 5, stop)]
        browser.arun = AsyncMock(return_value=SimpleNamespace(success=False, status_code=403, error_message="Blocked"))
        with patch("crawl4ai.AsyncWebCrawler", return_value=browser):
            with self.assertRaisesRegex(RuntimeError, "403"):
                _ = [page async for page in worker.listing_pages(SEARCH, 5, stop)]
        self.assertEqual(browser.arun.await_count, 1)

    async def test_ajax_block_is_detected_even_when_document_status_is_200(self):
        browser = MagicMock()
        browser.__aenter__ = AsyncMock(return_value=browser)
        browser.__aexit__ = AsyncMock(return_value=False)

        async def navigate(**kwargs):
            hook = browser.crawler_strategy.set_hook.call_args.args[1]
            page = MagicMock()
            await hook(page, None)
            listener = page.on.call_args.args[1]
            listener(SimpleNamespace(url="https://ads.example.com/blocked", status=403))
            listener(SimpleNamespace(url=SEARCH + "?page=2", status=429, headers={"retry-after": "3600"}))
            return SimpleNamespace(success=True, status_code=200, html=listing_html(URL))

        browser.arun = AsyncMock(side_effect=navigate)
        with patch("crawl4ai.AsyncWebCrawler", return_value=browser):
            with self.assertRaisesRegex(worker.crawler.WebsiteBlocked, "HTTP 429") as blocked:
                _ = [page async for page in worker.listing_pages(SEARCH, 5, asyncio.Event())]
            self.assertGreater(blocked.exception.retry_at - worker.time.time(), 3590)
        self.assertEqual(browser.arun.await_count, 1)

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
            async def fetched(url, on_event=None):
                on_event("crawl_fallback_started", engine="scrapling")
                on_event("crawl_fallback_succeeded", engine="scrapling", markdown_characters=len(SOURCE))
                return SOURCE

            fetch = AsyncMock(side_effect=fetched)
            with patch.object(worker.crawler, "initialize_chat_model", return_value=model), patch.object(
                worker.crawler, "crawl_markdown", fetch
            ), patch.object(worker, "listing_pages", fake_pages), redirect_stdout(io.StringIO()):
                await worker.run(args, stop)
            job = json.loads(next(path for path in (args.output_dir / "jobs").glob("*.json") if not path.name.startswith("._")).read_text())
            self.assertEqual(job["job_title"], "Analyst")
            self.assertEqual(job["description"], "Analyze data")
            self.assertEqual(job["url"], URL)
            csv_output = args.output_dir / "CareerMapVN_jobs.csv"
            with csv_output.open(encoding="utf-8", newline="") as saved:
                rows = list(csv.DictReader(saved))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["job_title"], "Analyst")
            self.assertEqual(rows[0]["description"], "Analyze data")
            self.assertEqual(rows[0]["category"], "")
            state = json.loads((args.output_dir / "status.json").read_text())
            self.assertEqual((state["status"], state["completed_total"], state["input_tokens"]), ("stopped", 1, 5))
            events = [json.loads(line) for line in next((args.output_dir / "events").glob("*.jsonl")).read_text().splitlines()]
            self.assertIn("job_completed", [event["event"] for event in events])
            completion = next(event for event in events if event["event"] == "job_completed")
            self.assertEqual(completion["output"], str(csv_output))
            fallback = [event for event in events if event["event"].startswith("crawl_fallback_")]
            self.assertEqual([event["event"] for event in fallback], ["crawl_fallback_started", "crawl_fallback_succeeded"])
            self.assertTrue(all(event["url"] == URL for event in fallback))
            self.assertTrue(list((args.output_dir / "sources").glob("*.markdown")))
            stop = asyncio.Event()

            async def listing(url, max_pages, stop):
                stop.set()
                yield {"url": url, "page": 1, "urls": ["https://www.topcv.vn/brand/company/tuyen-dung/analyst-j123.html"], "next_url": None}

            model.ainvoke.reset_mock()
            with patch.object(worker.crawler, "initialize_chat_model", return_value=model), patch.object(
                worker, "listing_pages", listing
            ), redirect_stdout(io.StringIO()):
                await worker.run(args, stop)
            model.ainvoke.assert_not_awaited()
            with csv_output.open(encoding="utf-8", newline="") as saved:
                self.assertEqual(len(list(csv.DictReader(saved))), 1)

    async def test_discovery_block_cooldown_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(output_dir=Path(directory), interval=60, refresh_seconds=900, pages=5)
            stop = asyncio.Event()
            model = SimpleNamespace(model_name="test", ainvoke=AsyncMock())

            async def blocked_pages(*args):
                raise RuntimeError("Listing navigation blocked (HTTP 403)")
                yield

            async def stop_wait(awaitable, timeout):
                awaitable.close()
                self.assertGreater(timeout, 290)
                self.assertLessEqual(timeout, 300)
                stop.set()

            with patch.object(worker.crawler, "initialize_chat_model", return_value=model), patch.object(
                worker, "listing_pages", blocked_pages
            ), patch.object(worker.asyncio, "wait_for", side_effect=stop_wait), redirect_stdout(io.StringIO()):
                await worker.run(args, stop)
                state = json.loads((args.output_dir / "status.json").read_text())
                self.assertIsNotNone(state["discovery_resume_at"])
                stop.clear()
                with patch.object(worker, "listing_pages") as discover:
                    await worker.run(args, stop)
                    discover.assert_not_called()
            model.ainvoke.assert_not_awaited()

    async def test_queue_survives_restart_and_is_drained_before_discovery(self):
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(output_dir=Path(directory), interval=60, refresh_seconds=900, pages=1)
            (args.output_dir / "pending.json").write_text(json.dumps([URL, URL]))
            stop = asyncio.Event()

            async def response(prompt):
                stop.set()
                return SimpleNamespace(content='{"job_title":"Analyst"}', usage_metadata={})

            model = SimpleNamespace(model_name="test", ainvoke=AsyncMock(side_effect=response))
            with patch.object(worker.crawler, "initialize_chat_model", return_value=model), patch.object(
                worker.crawler, "crawl_markdown", AsyncMock(return_value=SOURCE)
            ), patch.object(worker, "listing_pages") as discover, redirect_stdout(io.StringIO()):
                await worker.run(args, stop)
            discover.assert_not_called()
            self.assertEqual(model.ainvoke.await_count, 1)
            self.assertEqual(json.loads((args.output_dir / "pending.json").read_text()), [])
            state = json.loads((args.output_dir / "status.json").read_text())
            self.assertEqual((state["pending_total"], state["completed_total"]), (0, 1))

    async def test_invalid_saved_queue_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(output_dir=Path(directory), interval=60, refresh_seconds=900, pages=1)
            queue = args.output_dir / "pending.json"
            original = '["file:///etc/passwd"]'
            queue.write_text(original)
            with patch.object(worker.crawler, "initialize_chat_model"):
                with self.assertRaisesRegex(ValueError, "Invalid saved queue"):
                    await worker.run(args, asyncio.Event())
            self.assertEqual(queue.read_text(), original)

    async def test_categories_rotate_when_current_search_has_no_new_jobs(self):
        with tempfile.TemporaryDirectory() as directory:
            category = "https://www.topcv.vn/tim-viec-lam-cong-nghe-thong-tin-cr257"
            args = SimpleNamespace(output_dir=Path(directory), interval=60, refresh_seconds=900, pages=1, all_categories=True)
            (args.output_dir / "jobs").mkdir()
            (args.output_dir / "jobs/seed.json").write_text(json.dumps({"url": URL, "job_title": "Existing", "description": "Existing"}))
            stop = asyncio.Event()
            visited = []

            async def listing(url, pages, signal):
                visited.append(url)
                yield {"url": url, "page": 1, "urls": [URL if url == SEARCH else BRAND], "next_url": None, "category_search_urls": [category]}

            async def response(prompt):
                stop.set()
                return SimpleNamespace(content='{"job_title":"Analyst"}', usage_metadata={})

            model = SimpleNamespace(model_name="test", ainvoke=AsyncMock(side_effect=response))
            with patch.object(worker.crawler, "initialize_chat_model", return_value=model), patch.object(
                worker.crawler, "crawl_markdown", AsyncMock(return_value=SOURCE)
            ), patch.object(worker, "listing_pages", listing), redirect_stdout(io.StringIO()):
                await worker.run(args, stop)
            self.assertEqual(visited, [SEARCH, category])
            state = json.loads((args.output_dir / "status.json").read_text())
            self.assertEqual((state["completed_total"], state["search_index"]), (2, 0))
            self.assertEqual(state["search_urls"], [SEARCH, category])

    async def test_website_403_pauses_crawling_without_blame_on_api_key(self):
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(output_dir=Path(directory), interval=60, refresh_seconds=900, pages=1)
            stop = asyncio.Event()
            model = SimpleNamespace(model_name="test", ainvoke=AsyncMock())

            async def fetch(url, **options):
                stop.set()
                raise RuntimeError("Crawl failed (HTTP 403): Forbidden")

            with patch.object(worker.crawler, "initialize_chat_model", return_value=model), patch.object(
                worker, "listing_pages", fake_pages
            ), patch.object(worker.crawler, "crawl_markdown", fetch), redirect_stdout(io.StringIO()):
                await worker.run(args, stop)
            model.ainvoke.assert_not_awaited()
            state = json.loads((args.output_dir / "status.json").read_text())
            self.assertIsNotNone(state["discovery_resume_at"])
            self.assertEqual(state["failures"], {})
            self.assertEqual(json.loads((args.output_dir / "pending.json").read_text()), [URL])

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
            ), patch.object(worker, "listing_pages", fake_pages), patch.object(worker.crawler, "crawl_markdown", AsyncMock(return_value=SOURCE)), redirect_stdout(io.StringIO()):
                await worker.run(args, stop)
            state = json.loads((args.output_dir / "status.json").read_text())
            self.assertEqual(state["failures"], {})
            self.assertEqual(state["requests_total"], 1)
            self.assertIsNotNone(state["api_resume_at"])
            self.assertEqual(json.loads((args.output_dir / "pending.json").read_text()), [URL])
            events = next((args.output_dir / "events").glob("*.jsonl")).read_text()
            self.assertNotIn("test-secret", events)
            self.assertIn('"quota": true', events)


if __name__ == "__main__":
    unittest.main()
