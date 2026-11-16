import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path('/Volumes/CuKi/VinUni/Fall 2026/DSProg/DATA2010-Fall2026/CareerMapVN')
sys.path.insert(0, str(ROOT / 'crawling'))
import llm_extract as crawler
from models.schemas import JobAdSchema
from models.source_fields import job_markdown, normalize_job


async def main():
    folder = ROOT / 'data/continuous' / ('scrapling_fallback_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    folder.mkdir()
    benchmark = ROOT / 'data/continuous/scrapling_benchmark_20261115T082707Z'
    report = json.loads((benchmark / 'report.json').read_text())
    results = []
    for index, (url, kind) in enumerate(report['tasks']):
        if kind != 'job':
            continue
        source = (benchmark / str(index + 1).zfill(2) / 'scrapling.html').read_text()
        with patch('scrapling.fetchers.StealthyFetcher.async_fetch', AsyncMock(return_value=SimpleNamespace(status=200, html_content=source))):
            markdown = await crawler.scrapling_markdown(url)
        data = normalize_job({'url': url}, job_markdown(markdown, url))
        JobAdSchema.model_validate(data)
        baseline = next(result['fields'] for result in report['results'] if result['engine'] == 'crawl4ai' and result['url'] == url)
        fields = ('job_title', 'qualifications', 'salary', 'salary_min', 'salary_max', 'description', 'requirements_text', 'benefits', 'working_hours')
        differences = [field for field in fields if data.get(field) != baseline[field]]
        results.append({'url': url, 'differences': differences, 'passed': not differences})
    url = report['tasks'][0][0]
    events = []
    primary = SimpleNamespace(success=False, status_code=307, error_message='Synthetic test: Cloudflare JS challenge', html='')
    with patch('crawl4ai.AsyncWebCrawler') as constructor:
        constructor.return_value.__aenter__.return_value.arun.return_value = primary
        markdown = await crawler.crawl_markdown(url, on_event=lambda name, **details: events.append({'event': name, **details}))
    (folder / 'live_fallback.markdown').write_text(markdown)
    data = normalize_job({'url': url}, job_markdown(markdown, url))
    JobAdSchema.model_validate(data)
    final = {
        'offline_replay': results, 'events': events,
        'live_title': data['job_title'], 'live_qualifications': data['qualifications'],
        'live_schema_valid': True, 'primary_block_was_synthetic': True,
        'real_scrapling_request': True, 'active_cloudflare_solving_proven': False,
        'llm_calls': 0,
    }
    (folder / 'report.json').write_text(json.dumps(final, ensure_ascii=False, indent=2))
    print(json.dumps(final, ensure_ascii=False, indent=2))
    print('REPORT', folder / 'report.json')
    assert all(result['passed'] for result in results), 'Source field regression in fallback replay'
    assert [event['event'] for event in events] == ['crawl_fallback_started', 'crawl_fallback_succeeded']


asyncio.run(main())
