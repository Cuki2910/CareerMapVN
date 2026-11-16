import json
import os
import subprocess
import sys
import tempfile
import unittest
import unicodedata
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import llm_extract as crawler
from models.schemas import JobAdSchema
from models.source_fields import job_markdown, normalize_job, salary_fields


SOURCE = """### Quyền lợi
Overview only
## Mô tả công việc
**Build reports.**
### Responsibilities
Keep all source bullets.
## Yêu cầu ứng viên
SQL and Excel.
### Kỹ năng nên có
Python
## Quyền lợi ứng viên
• Thu nhập: Up to 2x triệu đồng Gross/tháng, thỏa thuận theo năng lực.
• BHXH, BHYT, BHTN; nghỉ phép, nghỉ lễ theo quy định.
### Hỗ trợ
Được cấp Máy tính
## Địa điểm và thời gian
### Thời gian làm việc
* Thứ 2 - Thứ 7 (08:00 - 17:00)
* 5,5 ngày/tuần, thứ Bảy chỉ làm buổi sáng.
### Cách thức ứng tuyển
Apply here.
"""


class CrawlerChecks(unittest.IsolatedAsyncioTestCase):
    def test_website_retry_after_numeric_date_and_invalid_values(self):
        for header, expected in (("120", 1120), ("Thu, 01 Jan 1970 00:30:00 GMT", 1800), ("-1", 1000), ("invalid", 0), ("inf", 0), ("nan", 0)):
            with self.subTest(header=header), patch.object(crawler.time, "time", return_value=1000):
                error = crawler.WebsiteBlocked("HTTP 429", 429, header)
                self.assertEqual(error.retry_at, expected)

    async def test_detail_rate_limit_keeps_server_retry_after(self):
        result = SimpleNamespace(success=False, status_code=429, error_message="Rate limited", html="", response_headers={"Retry-After": "3600"})
        with patch("crawl4ai.AsyncWebCrawler") as constructor:
            constructor.return_value.__aenter__.return_value.arun.return_value = result
            with self.assertRaises(crawler.WebsiteBlocked) as blocked:
                await crawler.crawl_markdown("https://example.com/job")
        self.assertGreater(blocked.exception.retry_at - crawler.time.time(), 3590)

    async def test_challenge_with_retry_after_waits_before_fallback(self):
        result = SimpleNamespace(success=False, status_code=403, error_message="Cloudflare JS challenge", html="", response_headers={"retry-after": "3600"})
        with patch("crawl4ai.AsyncWebCrawler") as constructor, patch.object(crawler, "scrapling_markdown", AsyncMock()) as fallback:
            constructor.return_value.__aenter__.return_value.arun.return_value = result
            with self.assertRaises(crawler.WebsiteBlocked) as blocked:
                await crawler.crawl_markdown("https://example.com/job")
            self.assertGreater(blocked.exception.retry_at - crawler.time.time(), 3590)
            fallback.assert_not_awaited()

    async def test_healthy_page_does_not_use_scrapling(self):
        result = SimpleNamespace(success=True, status_code=200, error_message="", html="<h1>Analyst</h1>", markdown=SOURCE)
        with patch("crawl4ai.AsyncWebCrawler") as constructor, patch.object(crawler, "scrapling_markdown", AsyncMock()) as fallback:
            constructor.return_value.__aenter__.return_value.arun.return_value = result
            self.assertEqual(await crawler.crawl_markdown("https://example.com/job"), SOURCE)
        fallback.assert_not_awaited()

    async def test_challenge_tries_fallback_once_and_logs_recovery(self):
        for status, success, html, error in (
            (307, False, "", "Blocked by anti-bot protection: Cloudflare JS challenge"),
            (200, True, "<title>Just a moment...</title>", ""),
        ):
            events = []
            result = SimpleNamespace(success=success, status_code=status, error_message=error, html=html)
            with self.subTest(status=status), patch("crawl4ai.AsyncWebCrawler") as constructor, patch.object(crawler, "scrapling_markdown", AsyncMock(return_value=SOURCE)) as fallback:
                constructor.return_value.__aenter__.return_value.arun.return_value = result
                output = await crawler.crawl_markdown("https://example.com/job", on_event=lambda name, **details: events.append(name))
                self.assertEqual(output, SOURCE)
                fallback.assert_awaited_once_with("https://example.com/job")
                self.assertEqual(events, ["crawl_fallback_started", "crawl_fallback_succeeded"])

    async def test_rate_limits_auth_and_ordinary_forbidden_do_not_use_fallback(self):
        for status, error in ((429, "Cloudflare rate limit"), (None, "Cloudflare HTTP 429"), (401, "Cloudflare authentication required"), (403, "Forbidden"), (500, "Server error")):
            result = SimpleNamespace(success=False, status_code=status, error_message=error, html="")
            with self.subTest(status=status), patch("crawl4ai.AsyncWebCrawler") as constructor, patch.object(crawler, "scrapling_markdown", AsyncMock()) as fallback:
                constructor.return_value.__aenter__.return_value.arun.return_value = result
                with self.assertRaises(RuntimeError):
                    await crawler.crawl_markdown("https://example.com/job")
                fallback.assert_not_awaited()

    async def test_fallback_failure_remains_a_website_block(self):
        result = SimpleNamespace(success=False, status_code=307, error_message="Cloudflare JS challenge", html="")
        events = []
        with patch("crawl4ai.AsyncWebCrawler") as constructor, patch.object(crawler, "scrapling_markdown", AsyncMock(side_effect=TimeoutError("timeout"))) as fallback:
            constructor.return_value.__aenter__.return_value.arun.return_value = result
            with self.assertRaisesRegex(RuntimeError, "Blocked by website challenge"):
                await crawler.crawl_markdown("https://example.com/job", on_event=lambda name, **details: events.append(name))
            fallback.assert_awaited_once()
        self.assertEqual(events, ["crawl_fallback_started", "crawl_fallback_failed"])

    async def test_scrapling_uses_existing_converter_and_preserves_degree(self):
        html = "<html><body><h1>Senior Analyst - Finance</h1><h2>Job Description</h2><p>Analyze reports.</p><h2>Requirements</h2><p>Bachelor's degree in Finance or Accounting.</p><p>CPA preferred.</p></body></html>"
        response = SimpleNamespace(status=200, html_content=html)
        with patch("scrapling.fetchers.StealthyFetcher.async_fetch", AsyncMock(return_value=response)) as fetch:
            markdown = await crawler.scrapling_markdown("https://www.topcv.vn/viec-lam/analyst/123.html")
        data = normalize_job({"url": "https://www.topcv.vn/viec-lam/analyst/123.html"}, markdown)
        self.assertEqual(data["job_title"], "Senior Analyst - Finance")
        self.assertEqual(data["qualifications"], ["Bachelor's degree in Finance or Accounting.", "CPA preferred."])
        self.assertEqual(data["description"], "Analyze reports.")
        fetch.assert_awaited_once()

    async def test_scrapling_rejects_errors_and_challenge_content(self):
        for response in (
            SimpleNamespace(status=429, html_content=""),
            SimpleNamespace(status=200, html_content="<html><h1>Just a moment</h1><p>Verify you are human</p></html>"),
        ):
            with self.subTest(status=response.status), patch("scrapling.fetchers.StealthyFetcher.async_fetch", AsyncMock(return_value=response)):
                with self.assertRaises((RuntimeError, ValueError)):
                    await crawler.scrapling_markdown("https://example.com/job")

    def test_decomposed_education_and_separate_majors(self):
        education = unicodedata.normalize("NFD", "Tốt nghiệp Cao đẳng trở lên.")
        majors = "Ưu tiên các chuyên ngành: Khoa học Dữ liệu, Toán học."
        markdown = f"## Mô tả công việc\nAnalyze\n## Yêu cầu ứng viên\n* {education}\n* {majors}"
        data = normalize_job({"job_title": "Analyst", "url": "https://example.com/job"}, markdown)
        self.assertEqual(data["qualifications"], [education, majors])

    def test_english_topcv_sections(self):
        markdown = "## Job Description\nAnalyze app data.\n### Requirements:\nDegree\n## Candidate Requirements\nSQL and Python/R.\n## Benefits\nMacBook\n## Address and Time work\n### Work Schedule\nMonday-Friday, 09:00-18:00\n### How to Apply\nApply now"
        data = normalize_job({"job_title": "Analyst", "url": "https://example.com/job"}, markdown)
        self.assertEqual(data["requirements_text"], "SQL and Python/R.")
        self.assertEqual(data["working_hours"], "Monday-Friday, 09:00-18:00")

    def test_qualifications_exclude_age_experience_and_availability(self):
        markdown = "# Support\n## Mô tả công việc\nHỗ trợ khách hàng.\n## Yêu cầu ứng viên\nKhông còn vướng lịch học.\nCó kinh nghiệm CSKH là lợi thế.\n## Thông tin chung\nHọc vấn\nTrung cấp trở lên"
        values = ["Tuổi 18 - 40", "Không còn vướng lịch học.", "Có kinh nghiệm CSKH là lợi thế.", "Đại học chuyên ngành không có trong nguồn"]
        for qualifications in (None, [], values + ["Trung cấp trở lên"]):
            with self.subTest(qualifications=qualifications):
                data = normalize_job({"qualifications": qualifications}, markdown)
                self.assertEqual(data["qualifications"], ["Trung cấp trở lên"])
        self.assertIsNone(normalize_job({"qualifications": values}, "## Job Description\nAnalyze\n## Requirements\nSQL")["qualifications"])
        for invalid in ("Trung cấp trở lên", [123]):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "Qualifications"):
                normalize_job({"qualifications": invalid}, markdown)

    def test_qualifications_preserve_detailed_degrees_and_certificates(self):
        requirements = ["Tốt nghiệp Đại học chuyên ngành Kế toán, Kiểm toán hoặc Tài chính.", "Ưu tiên chứng chỉ CPA."]
        markdown = "## Mô tả công việc\nAnalyze\n## Yêu cầu ứng viên\n" + "\n".join(requirements) + "\nCó từ 02 năm kinh nghiệm.\n## Thông tin chung\nHọc vấn\nĐại Học trở lên"
        data = normalize_job({"qualifications": ["Đại Học trở lên", "Có từ 02 năm kinh nghiệm."]}, markdown)
        self.assertEqual(data["qualifications"], requirements)
        english = ["Bachelor's degree in Computer Science or Statistics.", "AWS certification preferred."]
        data = normalize_job({"qualifications": ["3 years of experience"]}, "## Job Description\nAnalyze\n## Requirements\n" + "\n".join(english))
        self.assertEqual(data["qualifications"], english)

    def test_topcv_salary_is_recovered_from_source_not_model(self):
        url = "https://www.topcv.vn/viec-lam/analyst/123.html"
        for salary in (None, "Negotiable", "30 - 40 triệu"):
            with self.subTest(salary=salary):
                data = normalize_job({"url": url, "salary": salary}, "# Analyst\nThoả thuận\n## Job Description\nAnalyze")
                self.assertEqual(data["salary"], "Thoả thuận")
                self.assertIsNone(data["salary_max"])
        data = normalize_job({"url": url, "salary": None}, "# Analyst\nTới 12 triệu\n## Job Description\nAnalyze")
        self.assertEqual(data["salary"], "Tới 12 triệu")
        data = normalize_job({"url": url, "salary": "15 triệu"}, "# Analyst\n7.6 - 9.2 triệu\n## Job Description\nAnalyze\n## Benefits\n* Thu nhập: 7.600.000 - 9.200.000 VNĐ (LCB + KPI)")
        self.assertEqual(data["salary"], "7.600.000 - 9.200.000 VNĐ (LCB + KPI)")
        data = normalize_job({"url": url}, "# Analyst lương 99 triệu\n## Job Description\nAnalyze")
        self.assertIsNone(data.get("salary"))

    def test_topcv_title_education_and_prompt_scope(self):
        markdown = "Navigation and unrelated jobs\n# [Data Analyst](https://example.com) - Hà Nội\n" + SOURCE.replace(
            "SQL and Excel.", "* Tốt nghiệp Đại học trở lên chuyên ngành Tài chính, Thống kê.\nSQL and Excel."
        ) + "\n## Thông tin chung\nToàn thời gian\nDanh mục Nghề liên quan\nUnrelated salaries and footer"
        url = "https://www.topcv.vn/viec-lam/example/123.html"
        focused = job_markdown(markdown, url)
        self.assertNotIn("Navigation", focused)
        self.assertNotIn("Unrelated salaries", focused)
        self.assertIn("Thông tin chung", focused)
        self.assertEqual(job_markdown(markdown, "https://example.com/job"), markdown)
        data = normalize_job({"url": url, "job_title": "Data Analyst", "qualifications": ["Đại Học trở lên"]}, markdown)
        self.assertEqual(data["job_title"], "Data Analyst - Hà Nội")
        self.assertEqual(data["qualifications"], ["Tốt nghiệp Đại học trở lên chuyên ngành Tài chính, Thống kê."])
        data = normalize_job({"url": url, "job_title": "Data Analyst", "qualifications": ["Đại học chuyên ngành không có trong nguồn", "Chứng chỉ SQL"]}, markdown.replace("SQL and Excel.", "Chứng chỉ SQL.\nSQL and Excel."))
        self.assertEqual(data["qualifications"], ["Tốt nghiệp Đại học trở lên chuyên ngành Tài chính, Thống kê.", "Chứng chỉ SQL."])
        data = normalize_job({"url": url, "job_title": "Analyst", "qualifications": ["Đại Học trở lên"]}, "# Analyst\n## Overview\nĐại Học trở lên\n## Mô tả công việc\nAnalyze data\n## Yêu cầu ứng viên\nƯu tiên có chứng chỉ CDMP, DGSP.")
        self.assertEqual(data["qualifications"], ["Ưu tiên có chứng chỉ CDMP, DGSP.", "Đại Học trở lên"])

    def test_branded_job_keeps_employer_and_excludes_other_jobs(self):
        url = "https://www.topcv.vn/brand/company/tuyen-dung/analyst-j123.html"
        markdown = "Navigation\n[Employer](https://www.topcv.vn/brand/company) Company Ltd\n# [Analyst](https://example.com) - Ha Noi\n## Job Description\nAnalyze data\n## Requirements\nSQL\n## Thông tin chung\nFull-time\n## Việc làm cùng công ty\nOther jobs and salaries"
        focused = job_markdown(markdown, url)
        self.assertIn("Company Ltd", focused)
        self.assertIn("Full-time", focused)
        self.assertNotIn("Navigation", focused)
        self.assertNotIn("Other jobs", focused)
        self.assertEqual(job_markdown(focused, url), focused)
        data = normalize_job({"url": url, "job_title": "Analyst"}, focused)
        self.assertEqual(data["job_title"], "Analyst - Ha Noi")
        self.assertEqual(data["description"], "Analyze data")
        self.assertTrue(job_markdown("# Analyst\n## Job Description\nAnalyze data", url).startswith("# Analyst"))

    def test_json_formats(self):
        for content in ('{"job_title":"Analyst"}', '```json\n{"job_title":"Analyst"}\n```', '```\r\n{"job_title":"Analyst"}\r\n```'):
            self.assertEqual(crawler.extract_json_from_codeblock(content), {"job_title": "Analyst"})
        for content in ("invalid", "[]", "null", None, []):
            self.assertIsNone(crawler.extract_json_from_codeblock(content))

    def test_missing_credentials(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "GEMINI_API_KEY"):
                crawler.initialize_chat_model()

    def test_gemini_configuration(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": " test-key "}, clear=True):
            model = crawler.initialize_chat_model()
            self.assertEqual(model.model_name, "gemini-3.5-flash-lite")
            self.assertEqual(model.providers[0][1].openai_api_base, "https://generativelanguage.googleapis.com/v1beta/openai/")
            self.assertEqual(model.providers[0][1].openai_api_key.get_secret_value(), "test-key")
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key", "GEMINI_MODEL": "custom-model"}, clear=True):
            self.assertEqual(crawler.initialize_chat_model().model_name, "custom-model")

    async def test_gemini_request_and_extraction(self):
        import httpx
        from langchain_openai import ChatOpenAI

        def respond(request):
            self.assertEqual(str(request.url), "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions")
            self.assertEqual(request.headers["authorization"], "Bearer test-key")
            self.assertEqual(json.loads(request.content)["model"], "gemini-3.5-flash-lite")
            return httpx.Response(200, json={
                "id": "test-completion", "object": "chat.completion", "created": 1,
                "model": "gemini-3.5-flash-lite",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": '{"job_title":"Analyst","description":"Analyze data"}'}, "finish_reason": "stop"}],
            })

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True), patch(
                "langchain_openai.ChatOpenAI", side_effect=lambda **options: ChatOpenAI(**options, http_async_client=client)
            ), patch.object(crawler, "crawl_markdown", AsyncMock(return_value="## Job description\nAnalyze data")):
                data = await crawler.process_url("https://example.com/job", "Extract", crawler.initialize_chat_model())
        self.assertEqual(data["job_title"], "Analyst")
        self.assertEqual(data["url"], "https://example.com/job")

    def test_cli_from_other_directory(self):
        script = crawler.BASE_DIR / "llm_extract.sh"
        environment = {**os.environ, "PYTHON": sys.executable}
        result = subprocess.run(["bash", str(script), "--help"], cwd="/tmp", env=environment, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--crawl-only", result.stdout)
        result = subprocess.run(["bash", str(script)], cwd="/tmp", env=environment, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Finished processing", result.stdout)
        result = subprocess.run(["bash", str(script), "--url", "file:///etc/passwd", "--crawl-only"], env=environment, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Invalid HTTP(S) URL", result.stderr)

    async def test_schema_validation(self):
        model = SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(content='{"job_title":"Analyst","description":"Analyze data"}')))
        with patch.object(crawler, "crawl_markdown", AsyncMock(return_value="## Job description\nAnalyze data")):
            data = await crawler.process_url("https://example.com", "Extract", model)
            self.assertEqual(data["url"], "https://example.com")
            self.assertEqual(data["job_title"], "Analyst")
            model.ainvoke.return_value.content = '{"job_title":""}'
            with self.assertRaises(ValueError):
                await crawler.process_url("https://example.com", "Extract", model)

    def test_source_sections_are_complete(self):
        data = normalize_job({"job_title": "Analyst", "url": "https://example.com/job", "country": "Vietnam", "contract_type": "full-time"}, SOURCE)
        job = JobAdSchema.model_validate(data)
        self.assertIn("Responsibilities\nKeep all source bullets.", job.description)
        self.assertIn("Kỹ năng nên có\nPython", job.requirements_text)
        self.assertIn("5,5 ngày/tuần", job.working_hours)
        self.assertNotIn("Apply here", job.working_hours)
        self.assertTrue(any("BHXH, BHYT, BHTN; nghỉ phép, nghỉ lễ" in item for item in job.benefits))
        self.assertIn("Được cấp Máy tính", job.benefits)
        self.assertNotIn("Overview only", job.benefits)
        self.assertIn("2x triệu", job.salary)
        self.assertEqual((job.salary_min, job.salary_max, job.salary_avg), (None, None, None))
        self.assertEqual(job.country, "Việt Nam")
        self.assertEqual(job.contract_type, "Toàn thời gian")
        self.assertIsNone(job.category)

    def test_salary_normalization(self):
        examples = [
            ("15.0 - 22.0 triệu", (15, 22, "18.5 triệu")),
            ("9,4 – 12 triệu/tháng", (9.4, 12, "10.7 triệu")),
            ("15.000.000 - 22.000.000 VND/tháng", (15, 22, "18.5 triệu")),
            ("15 triệu - 22000000 VND/tháng", (15, 22, "18.5 triệu")),
            ("20 triệu", (20, 20, "20 triệu")),
            ("13 - 25 triệu VND", (13, 25, "19 triệu")),
            ("Từ 15 triệu", (15, None, None)),
            ("Up to 20 triệu", (None, 20, None)),
            ("Thoả thuận (Up to 2x triệu đồng Gross/tháng)", (None, None, None)),
            ("1500 - 2000 USD", (None, None, None)),
            ("20 triệu/năm", (None, None, None)),
            ("22 - 15 triệu", (None, None, None)),
            (None, (None, None, None)),
        ]
        for raw, expected in examples:
            with self.subTest(salary=raw):
                values = salary_fields(raw)
                self.assertEqual(tuple(values.values()), expected)

    def test_dates_and_explicit_category(self):
        data = normalize_job({"job_title": "Analyst", "url": "https://example.com/job", "deadline": "09/12/2026", "category": "guessed"}, SOURCE, "operator_label")
        self.assertEqual(data["deadline"], "2026-12-09")
        self.assertEqual(data["category"], "operator_label")
        with self.assertRaises(ValueError):
            normalize_job({"deadline": "31/02/2026"}, SOURCE)

    def test_salary_must_be_grounded_in_source(self):
        source = "## Job description\nAnalyze data.\nSalary: 15 - 20 triệu/tháng"
        valid = normalize_job({"job_title": "Analyst", "url": "https://example.com/job", "salary": "15 - 20 triệu/tháng"}, source)
        self.assertEqual(valid["salary_avg"], "17.5 triệu")
        for invented in ("30 - 40 triệu/tháng", 20000000):
            with self.subTest(salary=invented), self.assertRaises(ValueError):
                normalize_job({"salary": invented}, source)

    def test_schema_rejects_invalid_or_invented_values(self):
        base = normalize_job({"job_title": "Analyst", "url": "https://example.com/job"}, SOURCE)
        for invalid in ({"unknown": "value"}, {"job_title": " "}, {"experience_required": -1}, {"experience_required": float("nan")}, {"salary_max": 29}, {"deadline": "09/12/2026"}, {"posting_date": "2026-12-10", "deadline": "2026-12-09"}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                JobAdSchema.model_validate({**base, **invalid})

    async def test_unrecognized_source_is_not_marked_complete(self):
        model = SimpleNamespace(ainvoke=AsyncMock())
        with patch.object(crawler, "crawl_markdown", AsyncMock(return_value="Login or CAPTCHA page")):
            with self.assertRaisesRegex(ValueError, "No recognizable"):
                await crawler.process_url("https://example.com/job", "Extract", model)
        model.ainvoke.assert_not_awaited()

    async def test_old_records_are_upgraded_before_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "results.json"
            url = "https://example.com/job"
            output.write_text(json.dumps([{"job_title": "Analyst", "description": "Old summary", "url": url}]))
            model = SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(content='{"job_title":"Analyst"}')))
            with patch.object(crawler, "crawl_markdown", AsyncMock(return_value=SOURCE)):
                self.assertEqual(await crawler.process_urls([url], "Extract", output, model), 0)
                self.assertEqual(await crawler.process_urls([url], "Extract", output, model), 0)
            self.assertEqual(model.ainvoke.await_count, 1)
            record = json.loads(output.read_text())[0]
            self.assertEqual(set(record), set(JobAdSchema.model_fields))
            self.assertIn("5,5 ngày/tuần", record["working_hours"])

    async def test_resume_preserves_existing_category(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "results.json"
            url = "https://example.com/job"
            job = JobAdSchema.model_validate(normalize_job({"job_title": "Analyst", "url": url}, SOURCE, "known_label"))
            output.write_text(json.dumps([job.model_dump(mode="json")]))
            model = SimpleNamespace(ainvoke=AsyncMock())
            self.assertEqual(await crawler.process_urls([url], "Extract", output, model), 0)
            model.ainvoke.assert_not_awaited()
            self.assertEqual(json.loads(output.read_text())[0]["category"], "known_label")

    async def test_resume_uses_urls_not_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "results.json"
            output.write_text(json.dumps([{"url": "https://example.com/old", "markdown": "Old"}]))
            fetch = AsyncMock(return_value="New job")
            with patch.object(crawler, "crawl_markdown", fetch):
                self.assertEqual(await crawler.process_urls(["https://example.com/new"], "", output, crawl_only=True), 0)
                self.assertEqual(await crawler.process_urls(["https://example.com/new"], "", output, crawl_only=True), 0)
            self.assertEqual(fetch.await_count, 1)
            self.assertEqual(len(json.loads(output.read_text())), 2)

    async def test_failed_model_response_is_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "results.json"
            output.write_text('[{"url":"https://example.com/job","raw_response":"old invalid response"}]')
            original = output.read_bytes()
            model = SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(content="not json")))
            with patch.object(crawler, "crawl_markdown", AsyncMock(return_value="## Job description\nJob")), patch.object(crawler.asyncio, "sleep", AsyncMock()):
                status = await crawler.process_urls(["https://example.com/job"], "Extract", output, model)
            self.assertEqual(status, 1)
            self.assertEqual(model.ainvoke.await_count, 3)
            self.assertEqual(output.read_bytes(), original)

    async def test_malformed_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "results.json"
            for content in ("broken json", "{}", '[{"markdown":"missing URL"}]'):
                output.write_text(content)
                with self.assertRaises(ValueError):
                    await crawler.process_urls(["https://example.com/job"], "", output, crawl_only=True)
                self.assertEqual(output.read_text(), content)

    async def test_failed_save_preserves_previous_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "results.json"
            output.write_text("[]")
            with patch.object(crawler, "crawl_markdown", AsyncMock(return_value="Job")), patch.object(crawler.os, "replace", side_effect=OSError("disk error")):
                with self.assertRaises(OSError):
                    await crawler.process_urls(["https://example.com/job"], "", output, crawl_only=True)
            self.assertEqual(output.read_text(), "[]")
            self.assertEqual(list(Path(directory).iterdir()), [output])

    async def test_crawl_failure_does_not_stop_other_urls(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "results.json"
            fetch = AsyncMock(side_effect=[RuntimeError("HTTP 403")] * 3 + ["Job content"])
            with patch.object(crawler, "crawl_markdown", fetch), patch.object(crawler.asyncio, "sleep", AsyncMock()):
                status = await crawler.process_urls(["https://example.com/blocked", "https://example.com/job"], "", output, crawl_only=True)
            self.assertEqual(status, 1)
            self.assertEqual(json.loads(output.read_text()), [{"url": "https://example.com/job", "markdown": "Job content"}])


if __name__ == "__main__":
    unittest.main()
