import asyncio
import json
import re
import statistics
import subprocess
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path('/Volumes/CuKi/VinUni/Fall 2026/DSProg/DATA2010-Fall2026/CareerMapVN')


async def baseline(url, folder):
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig

    started = time.monotonic()
    result = {'engine': 'crawl4ai'}
    try:
        options = {}
        if '/tim-viec-lam-' in url:
            options = {'wait_for': "js:() => document.querySelectorAll('.job-list-main .job-item-search-result h3.title a[href]').length > 0", 'wait_for_timeout': 20000}
        async with AsyncWebCrawler(config=BrowserConfig(headless=True, verbose=False)) as browser:
            response = await asyncio.wait_for(browser.arun(
                url=url, config=CrawlerRunConfig(cache_mode=CacheMode.BYPASS, page_timeout=60000, **options),
            ), 100)
        result.update(status=response.status_code, error=response.error_message,
                      transport_ok=bool(response.success and (not response.status_code or response.status_code < 400)))
        (folder / 'crawl4ai.html').write_text(response.html or '')
        (folder / 'crawl4ai.markdown').write_text(getattr(response.markdown, 'raw_markdown', response.markdown) or '')
    except Exception as error:
        result.update(transport_ok=False, error=type(error).__name__ + ': ' + str(error)[:1200])
    result['seconds'] = round(time.monotonic() - started, 3)
    (folder / 'crawl4ai.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))


if len(sys.argv) > 1 and sys.argv[1] == '--baseline':
    asyncio.run(baseline(sys.argv[2], Path(sys.argv[3])))
    sys.exit()


sys.path.insert(0, str(ROOT / 'crawling'))
sys.path.append(str(ROOT / '.venv/lib/python3.12/site-packages'))
from lxml import html
from markdownify import markdownify
from scrapling.fetchers import AsyncStealthySession
from models.source_fields import folded, job_markdown, normalize_job, source_sections
from models.schemas import JobAdSchema
from run_continuous import listing_data


ANALYZE = len(sys.argv) > 1 and sys.argv[1] == '--analyze'
OUTPUT = Path(sys.argv[2]) if ANALYZE else ROOT / 'data/continuous' / ('scrapling_benchmark_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
OUTPUT.mkdir(exist_ok=True)
REPORT = json.loads((OUTPUT / 'report.json').read_text()) if ANALYZE else {
    'started_at': datetime.now(timezone.utc).isoformat(),
    'request_interval_seconds': 15,
    'gate': 'All 12 pages valid, exact source title, schema-valid job records, source sections preserved, no field differences versus successful baseline, and either fewer failures or at least 20% lower median fetch latency.',
    'results': [], 'llm_calls': 0, 'worker_modified': False,
}
LAST_START = 0


def save():
    (OUTPUT / 'report.json').write_text(json.dumps(REPORT, ensure_ascii=False, indent=2))


def canonical(value):
    if isinstance(value, list):
        return [canonical(item) for item in value]
    if isinstance(value, str):
        return folded(re.sub(r'(?m)^\s*(?:[-*+\u2022]|\d+[.)])\s+', '', value))
    return value


def validate(folder, engine, url, kind):
    result = json.loads((folder / (engine + '.json')).read_text())
    result.update(url=url, kind=kind, valid=False)
    if not result.get('transport_ok'):
        return result
    document = html.fromstring((folder / (engine + '.html')).read_text())
    if kind == 'listing':
        data = listing_data(html.tostring(document, encoding='unicode'), url)
        result.update(job_count=len(data['urls']), job_urls=sorted(data['urls']), valid=bool(data['urls']))
        return result
    markdown = (folder / (engine + '.markdown')).read_text()
    focused = job_markdown(markdown, url)
    sections = source_sections(focused)
    normalized = normalize_job({'url': url}, focused)
    try:
        JobAdSchema.model_validate(normalized)
        schema_valid = True
    except ValueError as error:
        schema_valid = False
        result['schema_error'] = str(error)[:1000]
    headings = document.xpath('//h1')
    title = ' '.join(headings[0].text_content().split()) if headings else ''
    exact_title = bool(title) and folded(normalized.get('job_title', '')) == folded(title)
    source_preserved = {}
    for heading in document.xpath('//h2|//h3'):
        label = folded(heading.text_content())
        field = {'motacongviec': 'description', 'jobdescription': 'description',
                 'yeucauungvien': 'requirements_text', 'candidaterequirements': 'requirements_text',
                 'quyenloi': 'benefits', 'quyenloiungvien': 'benefits', 'benefits': 'benefits',
                 'thoigianlamviec': 'working_hours', 'workschedule': 'working_hours'}.get(label)
        if field is None:
            continue
        parent = heading.getparent()
        content = parent.xpath('./*[contains(@class,"content") or contains(@class,"__text")]')
        if not content:
            parent = parent.getparent()
            content = parent.xpath('./*[contains(@class,"content") or contains(@class,"__text")]')
        if content:
            source = ''.join(character for character in folded(' '.join(element.text_content() for element in content)) if character.isalnum())
            if source:
                extracted = ''.join(character for character in folded(sections.get(field, '')) if character.isalnum())
                source_preserved[field] = source in extracted
    result.update(
        title=title, title_exact=exact_title, schema_valid=schema_valid,
        source_preserved=source_preserved,
        section_lengths={key: len(value) for key, value in sections.items()},
        fields={key: normalized.get(key) for key in ('job_title', 'qualifications', 'salary', 'salary_min', 'salary_max', 'description', 'requirements_text', 'benefits', 'working_hours')},
        valid=bool(exact_title and schema_valid and sections.get('description')
                   and sections.get('requirements_text') and all(source_preserved.values())),
    )
    return result


async def main():
    global LAST_START
    root = ROOT / 'data/continuous'
    state = json.loads((root / 'status.json').read_text())
    pending = json.loads((root / 'pending.json').read_text())
    jobs = [json.loads(path.read_text()) for path in sorted((root / 'jobs').glob('*.json')) if not path.name.startswith('._')]
    urls = list(dict.fromkeys([state['current_url']] + pending[:4]
           + [job['url'] for job in jobs if '/brand/' in job['url']][:2]
           + [job['url'] for job in jobs if '/brand/' not in job['url']][:3]))
    tasks = [(url, 'job') for url in urls[:10]] + [
        ('https://www.topcv.vn/tim-viec-lam-data-analyst', 'listing'),
        ('https://www.topcv.vn/tim-viec-lam-san-xuat-cr417', 'listing'),
    ]
    REPORT['tasks'] = tasks
    save()
    async with AsyncStealthySession(headless=True, solve_cloudflare=True, timeout=60000,
                                    wait=2000, google_search=False, max_pages=1) as session:
        for index, (url, kind) in enumerate(tasks):
            folder = OUTPUT / str(index + 1).zfill(2)
            folder.mkdir()
            engines = ('crawl4ai', 'scrapling') if index % 2 == 0 else ('scrapling', 'crawl4ai')
            for engine in engines:
                await asyncio.sleep(max(0, 15 - (time.monotonic() - LAST_START)))
                LAST_START = time.monotonic()
                print('START', index + 1, engine, url, flush=True)
                if engine == 'crawl4ai':
                    with (folder / 'crawl4ai.log').open('w') as log:
                        process = await asyncio.create_subprocess_exec(
                            str(ROOT / '.venv/bin/python'), str(Path(__file__)), '--baseline', url, str(folder),
                            stdout=log, stderr=subprocess.STDOUT, cwd=ROOT,
                        )
                        await process.wait()
                    if not (folder / 'crawl4ai.json').exists():
                        (folder / 'crawl4ai.json').write_text(json.dumps({'engine': engine, 'transport_ok': False, 'error': 'Baseline subprocess failed; see log', 'seconds': 100}))
                else:
                    started = time.monotonic()
                    result = {'engine': engine}
                    try:
                        response = await asyncio.wait_for(session.fetch(url), 100)
                        result.update(status=response.status, transport_ok=response.status == 200)
                        (folder / 'scrapling.html').write_text(response.html_content)
                        (folder / 'scrapling.markdown').write_text(markdownify(response.html_content, heading_style='ATX'))
                    except Exception as error:
                        result.update(transport_ok=False, error=type(error).__name__ + ': ' + str(error)[:1200])
                    result['seconds'] = round(time.monotonic() - started, 3)
                    (folder / 'scrapling.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
                try:
                    result = validate(folder, engine, url, kind)
                except Exception as error:
                    result = {'engine': engine, 'url': url, 'kind': kind, 'valid': False, 'error': 'Validation: ' + str(error)[:1000]}
                REPORT['results'].append(result)
                save()
                print('RESULT', json.dumps({key: value for key, value in result.items() if key not in ('fields', 'job_urls')}, ensure_ascii=False), flush=True)
            if all(not result.get('transport_ok') for result in REPORT['results'][-2:]):
                REPORT['stopped_early'] = 'Both engines failed on the same URL; stopping further requests.'
                break
    summarize(tasks)


def summarize(tasks):
    by_engine = {engine: [result for result in REPORT['results'] if result['engine'] == engine] for engine in ('crawl4ai', 'scrapling')}
    summary = {engine: {'attempts': len(results), 'valid': sum(result['valid'] for result in results),
                       'median_seconds': round(statistics.median(result.get('seconds', 100) for result in results), 3)}
               for engine, results in by_engine.items()}
    differences = []
    for url, kind in tasks:
        pair = {result['engine']: result for result in REPORT['results'] if result['url'] == url}
        if len(pair) < 2 or not all(result['valid'] for result in pair.values()):
            continue
        keys = set(pair['scrapling'].get('fields', {})) if kind == 'job' else {'job_urls'}
        for key in keys:
            values = [result['fields'][key] if kind == 'job' else result[key] for result in (pair['scrapling'], pair['crawl4ai'])]
            if canonical(values[0]) != canonical(values[1]):
                differences.append({'url': url, 'field': key})
    healthy = summary['scrapling']['valid'] == len(tasks) and not differences
    better = (summary['scrapling']['valid'] > summary['crawl4ai']['valid']
              or summary['scrapling']['median_seconds'] <= summary['crawl4ai']['median_seconds'] * 0.8)
    REPORT.update(summary=summary, field_differences=differences, replacement_gate_passed=healthy and better,
                  finished_at=datetime.now(timezone.utc).isoformat())
    save()
    print('SUMMARY', json.dumps({key: REPORT[key] for key in ('summary', 'field_differences', 'replacement_gate_passed')}, ensure_ascii=False), flush=True)
    print('REPORT', OUTPUT / 'report.json', flush=True)


if __name__ == '__main__':
    if ANALYZE:
        REPORT['results'] = [
            validate(OUTPUT / str(index + 1).zfill(2), engine, url, kind)
            for index, (url, kind) in enumerate(REPORT['tasks'])
            for engine in ('crawl4ai', 'scrapling')
            if (OUTPUT / str(index + 1).zfill(2) / (engine + '.json')).exists()
        ]
        summarize(REPORT['tasks'])
    else:
        asyncio.run(main())
