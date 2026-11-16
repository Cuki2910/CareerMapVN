import os
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import llm_extract as crawler


def provider(name, content='{"job_title":"Analyst"}'):
    return name, SimpleNamespace(model_name=name + "-model", ainvoke=AsyncMock(return_value=SimpleNamespace(
        content=content, usage_metadata={"input_tokens": 5, "output_tokens": 3},
    )))


def api_error(status, retry_after=None, message="API failure"):
    error = RuntimeError(message)
    error.status_code = status
    error.response = SimpleNamespace(headers={"retry-after": retry_after} if retry_after else {})
    return error


class RouterChecks(unittest.IsolatedAsyncioTestCase):
    def test_optional_keys_and_free_only_openrouter(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": "test-groq", "OPENROUTER_API_KEY": "test-router"}, clear=True):
            router = crawler.initialize_chat_model()
            self.assertEqual([name for name, _ in router.providers], ["groq", "openrouter"])
            self.assertEqual(router.providers[0][1].model_name, "openai/gpt-oss-120b")
            self.assertEqual(router.providers[1][1].model_name, "particle-ai/particle-1:free")
            with patch.dict(os.environ, {"OPENROUTER_MODEL": "paid-model"}):
                with self.assertRaisesRegex(ValueError, "free"):
                    crawler.initialize_chat_model()

    async def test_rotation_does_not_pause_after_successful_calls(self):
        gemini, groq, openrouter = provider("gemini"), provider("groq"), provider("openrouter")
        router = crawler.ProviderRouter([gemini, groq, openrouter])
        events = []
        with patch.object(crawler.time, "time", return_value=100):
            for _ in range(6):
                await router.ainvoke("test", on_event=lambda event, **details: events.append((event, details)))
        requests = [details["provider"] for event, details in events if event == "api_request"]
        self.assertEqual(requests, ["gemini", "groq", "openrouter", "gemini", "groq", "openrouter"])
        self.assertEqual(router.cooldowns, {"gemini": 0, "groq": 0, "openrouter": 0})

    async def test_errors_fall_back_and_never_log_keys(self):
        for status in (400, 401, 402, 403, 404, 429, 500, 503):
            with self.subTest(status=status):
                primary, backup = provider("gemini"), provider("groq")
                primary[1].ainvoke.side_effect = api_error(status, message="gemini-secret groq-secret router-secret")
                router = crawler.ProviderRouter([primary, backup])
                events = []
                with patch.dict(os.environ, {"GEMINI_API_KEY": "gemini-secret", "GROQ_API_KEY": "groq-secret", "OPENROUTER_API_KEY": "router-secret"}):
                    await router.ainvoke("test", on_event=lambda event, **details: events.append((event, details)))
                errors = [details for event, details in events if event == "api_error"]
                self.assertEqual(errors[0]["error"], "[REDACTED] [REDACTED] [REDACTED]")
                self.assertEqual(backup[1].ainvoke.await_count, 1)

    async def test_timeouts_and_network_errors_fall_back(self):
        import httpx
        from openai import APIConnectionError

        for error in (TimeoutError(), APIConnectionError(request=httpx.Request("POST", "https://example.com"))):
            primary, backup = provider("gemini"), provider("openrouter")
            primary[1].ainvoke.side_effect = error
            router = crawler.ProviderRouter([primary, backup])
            await router.ainvoke("test")
            backup[1].ainvoke.assert_awaited_once()

    async def test_retry_after_and_all_providers_unavailable(self):
        gemini, groq = provider("gemini"), provider("groq")
        gemini[1].ainvoke.side_effect = api_error(429, retry_after="3600")
        groq[1].ainvoke.side_effect = api_error(429, message="tokens per minute (TPM)")
        router = crawler.ProviderRouter([gemini, groq])
        with patch.object(crawler.time, "time", return_value=100):
            with self.assertRaises(crawler.ProvidersUnavailable) as context:
                await router.ainvoke("test")
            self.assertEqual(context.exception.retry_at, 165)
            self.assertEqual(router.cooldowns["gemini"], 3700)
            with self.assertRaises(crawler.ProvidersUnavailable):
                await router.ainvoke("test")
        gemini[1].ainvoke.assert_awaited_once()
        groq[1].ainvoke.assert_awaited_once()
        with patch.object(crawler.time, "time", return_value=170):
            groq[1].ainvoke.side_effect = None
            await router.ainvoke("test")
        self.assertEqual(groq[1].ainvoke.await_count, 2)

    async def test_retry_after_http_date_is_respected(self):
        primary = provider("openrouter")
        primary[1].ainvoke.side_effect = api_error(503, retry_after="Thu, 01 Jan 1970 01:00:00 GMT")
        router = crawler.ProviderRouter([primary])
        with patch.object(crawler.time, "time", return_value=100):
            with self.assertRaises(crawler.ProvidersUnavailable) as context:
                await router.ainvoke("test")
        self.assertEqual(context.exception.retry_at, 3600)

    async def test_invalid_json_and_schema_use_next_provider(self):
        for content in ("not json", '{"job_title":"Analyst","experience_required":-1}', '{"job_title":"Analyst","unknown":"value"}'):
            primary, backup = provider("gemini", content), provider("openrouter")
            router = crawler.ProviderRouter([primary, backup])
            data = await crawler.extract_job("https://example.com/job", "Extract", router, "## Job Description\nAnalyze")
            self.assertEqual((data["job_title"], data["description"]), ("Analyst", "Analyze"))
            backup[1].ainvoke.assert_awaited_once()
            self.assertGreater(router.cooldowns["gemini"], 0)

    async def test_unexpected_local_errors_are_not_hidden(self):
        primary, backup = provider("gemini"), provider("groq")
        primary[1].ainvoke.side_effect = OSError("disk error")
        with self.assertRaisesRegex(OSError, "disk error"):
            await crawler.ProviderRouter([primary, backup]).ainvoke("test")
        backup[1].ainvoke.assert_not_awaited()

    async def test_all_invalid_outputs_are_job_errors_not_quota(self):
        router = crawler.ProviderRouter([provider("gemini", "invalid"), provider("groq", "invalid")])
        with self.assertRaisesRegex(ValueError, "invalid extraction"):
            await crawler.extract_job("https://example.com/job", "Extract", router, "## Job Description\nAnalyze")


if __name__ == "__main__":
    unittest.main()
