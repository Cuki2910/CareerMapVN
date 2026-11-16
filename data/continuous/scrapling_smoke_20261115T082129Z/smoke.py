import asyncio
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from markdownify import markdownify
from scrapling.fetchers import AsyncStealthySession


ROOT = Path('/Volumes/CuKi/VinUni/Fall 2026/DSProg/DATA2010-Fall2026/CareerMapVN')
STAMP = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
OUTPUT = ROOT / 'data' / 'continuous' / ('scrapling_smoke_' + STAMP)
OUTPUT.mkdir()
STATE = json.loads((ROOT / 'data/continuous/status.json').read_text())
REPORT = {
    'started_at': datetime.now(timezone.utc).isoformat(),
    'library': 'scrapling 0.5.1',
    'headless': True,
    'solve_cloudflare': True,
    'worker_modified': False,
    'llm_calls': 0,
    'results': [],
}


def save_report():
    (OUTPUT / 'report.json').write_text(json.dumps(REPORT, ensure_ascii=False, indent=2))


async def check(session, url, name, control=False):
    started = time.monotonic()
    result = {'url': url, 'name': name}
    print('START', name, url, flush=True)
    try:
        response = await asyncio.wait_for(session.fetch(url), timeout=100)
        html = response.html_content
        body = markdownify(html, heading_style='ATX')
        (OUTPUT / (name + '.html')).write_text(html)
        (OUTPUT / (name + '.markdown')).write_text(body)
        headings = response.css('h1').getall()
        requirements = bool(re.search(r'Yêu cầu (?:ứng viên|công việc)', body, re.I))
        description = bool(re.search(r'Mô tả công việc', body, re.I))
        challenge = bool(re.search(r'just a moment|performing security verification|verify you are human|checking your browser', body, re.I))
        result.update(
            status=response.status,
            final_url=response.url,
            h1=headings,
            markdown_characters=len(body),
            requirements_present=requirements,
            description_present=description,
            challenge_present=challenge,
            passed=(response.status == 200 and not challenge
                    and ((control and 'Example Domain' in body)
                         or bool(headings) and requirements and description)),
        )
    except Exception as error:
        result.update(passed=False, error=type(error).__name__ + ': ' + str(error)[:1500])
    result['elapsed_seconds'] = round(time.monotonic() - started, 3)
    REPORT['results'].append(result)
    save_report()
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result['passed']


async def main():
    save_report()
    try:
        async with AsyncStealthySession(
            headless=True, solve_cloudflare=True, timeout=60000,
            wait=2000, google_search=False, max_pages=1,
        ) as session:
            if not await check(session, 'https://example.com', 'control', control=True):
                return
            if not await check(session, STATE['current_url'], 'blocked_job'):
                return
            await asyncio.sleep(20)
            await check(session, 'https://www.topcv.vn/viec-lam/ky-su-dien-tu-dong-hoa/2351897.html', 'second_job')
    finally:
        REPORT['finished_at'] = datetime.now(timezone.utc).isoformat()
        save_report()
        print('REPORT', OUTPUT / 'report.json', flush=True)


if __name__ == '__main__':
    asyncio.run(main())
    assert len(REPORT['results']) == 3 and all(result['passed'] for result in REPORT['results']), 'Smoke test did not pass all three checks; see report'
