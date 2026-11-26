# CareerMapVN

Which data skills do Vietnamese employers ask for, where, in which industries, and how
do they relate to advertised salary? CareerMapVN builds an analysis-ready dataset of
**data roles** (tier A: data/BI analyst, data scientist/ML/AI, data engineer, business
analyst, DBA/data governance, quant/risk) and **data-skill jobs** (tier B: other
occupations whose postings name concrete data skills such as SQL, Power BI, Python,
Google Analytics, statistics or advanced Excel) from Vietnamese job advertisements.

DATA2010 Data Science Programming project, VinUniversity, Fall 2026.

## Repository layout

| Path | Contents |
|---|---|
| `crawling/` | TopCV crawler with LLM structured extraction → `data/CareerMapVN_jobs.csv` |
| `analysis/` | Data pipeline: fetch → clean → filter → LLM labels → skill matrix → export |
| `docs/data_pipeline.md` | **How the data pipeline works**: method, decisions, numbers, limitations, usage |
| `data/` | Datasets and pipeline outputs; see [`data/README.md`](data/README.md) |
| `upstream/` | Original VietJobs fine-tuning code (LoRA, GPU); not used by CareerMapVN |
| `Makefile`, `Dockerfile` | One-command reproduction |

## Quickstart

```bash
git clone https://github.com/Cuki2910/CareerMapVN.git && cd CareerMapVN
make docker                    # or: pip install -r analysis/requirements.txt && make test all export
```

Outputs land in `data/analysis/export/` (`data_jobs.csv`, `all_jobs.csv`, `data_quality.md`).
No API key is needed: LLM labels are read from the committed cache.

## Crawler

The crawler accepts existing job URLs; it does not discover job links automatically.
Use Python 3.11+ and the crawler-only dependencies.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r crawling/requirements.txt
python -m playwright install chromium
python -m patchright install chromium

# Replace the example with an actual job advertisement URL.
bash crawling/llm_extract.sh --url 'https://example.com/job' --crawl-only
```

`--crawl-only` saves page markdown to `data/job.markdown.json` without API credentials.
For structured extraction, create a Gemini API key in Google AI Studio, copy
`.env.example` to `.env`, and set `GEMINI_API_KEY`. The default model is
`gemini-3.5-flash-lite`; optionally change `GEMINI_MODEL` to a model available to your
project. Requests use Google's OpenAI-compatible endpoint through the existing
`langchain-openai` dependency; no Azure resource or OpenAI API key is needed.
Free-tier quotas depend on your project and model; this script does not enforce
a free-only billing limit. Avoid sending sensitive data on the free tier.
You can instead configure `GROQ_API_KEY` and/or `OPENROUTER_API_KEY` in `.env`.
Configured providers rotate Gemini -> Groq -> OpenRouter; missing keys are skipped.
Errors and invalid extraction output fall back to the next available provider.
Each provider gets its own cooldown; `Retry-After` is respected, and the worker
waits when all providers are unavailable. Successful calls do not introduce a
provider cooldown. Restarting the continuous worker preserves error cooldowns
and its queue; website-block backoff and the crawl interval remain in effect.
OpenRouter defaults to `particle-ai/particle-1:free` and accepts only `:free` models
or `openrouter/free`; optional `GROQ_MODEL`/`OPENROUTER_MODEL` override the defaults.
Rotation does not remove account/project quotas or guarantee uninterrupted service.
Continuous logs record each attempt's provider, model, usage and errors, without keys.
Then run:

```bash
bash crawling/llm_extract.sh --url 'https://example.com/job'
# Or supply a UTF-8 text file containing one HTTP(S) URL per line:
bash crawling/llm_extract.sh path/to/links.txt
```

Structured output is validated against `JobAdSchema` and saved to `data/job.json`
or `data/<input-filename>.json`. Use `--output-dir PATH` to choose another directory.
Description, requirements, benefits and working hours are taken from complete source
sections, not the model's summaries. Recognized headings cover TopCV-style Vietnamese
sections. TopCV navigation and unrelated footer links are excluded from the model
input; the full main title and explicit graduation/certification requirements are retained.
English job description/requirements/benefits/working-hours headings are also recognized.
Pages without a recognizable job-description section fail instead of being accepted.
Output has 25 fields, ISO dates, and normalized Vietnamese country/contract labels.
`salary_min` and `salary_max` use millions of VND per month. `salary_avg` is the exact
midpoint formatted as `X triệu`, not the rounded value in the sample CSV. Ambiguous
salary text, foreign currencies and unsupported pay periods keep numeric fields null;
one-sided salaries do not invent an average. Original wording remains in `salary`.
The repo does not include the full category taxonomy: pass `--category EXACT_LABEL`
only when that dataset label is known for all input URLs; otherwise `category` is null.
The JSON includes the sample CSV's fields but is not itself a training CSV. Missing
labels or salary targets must be reviewed/filtered, never fabricated to fill columns.
These checks guarantee structural consistency and preserve recognized source sections;
they do not establish 100% semantic accuracy of all AI-extracted metadata.
Paths passed on the command line are relative to your current directory; defaults
and prompt paths are relative to the project. The launcher uses the project's `.venv`
when present; set `PYTHON=/path/to/python` to override it.
Without arguments, the shell script processes `crawling/links/*.txt` and errors if none exist.
Completed URLs are skipped on reruns; failed URLs are retried up to three times and
cause a nonzero exit code. Invalid model responses are not marked as completed.
Existing malformed output files are left untouched, and updates use atomic replacement.
Sites that block browser automation or require login may still fail.

Run the focused checks with `python -m unittest discover -s crawling -p 'test_*.py'`.

### Continuous crawl and report logs

```bash
.venv/bin/python -u crawling/run_continuous.py
```

This worker discovers TopCV Data Analyst jobs by following the public next-page
button in one browser session, up to five pages. It includes branded job URLs,
ignores recommendation links outside the main results, and rejects repeated or
empty result pages. By default it refreshes every 15 minutes and processes at most
one new job per minute, deduplicating by job ID across restarts. It runs until stopped.
Detail pages with a detected Cloudflare/browser challenge try Scrapling once before
pausing. Healthy pages still use Crawl4AI; fallback HTML uses the same Crawl4AI
cleaning and Markdown conversion and must contain a recognizable job description.
Fallback start/success/failure events are recorded in the report logs. This does not
guarantee challenge resolution and does not change listing pagination or use proxies.
Website HTTP 403/429 responses, including AJAX pagination and detail responses, pause
requests for 5 minutes on the first unrecovered block, then 10, 20 and at most
30 minutes on consecutive blocks. A valid website `Retry-After` can extend the wait.
Website cooldowns and consecutive-block counts survive restarts. Discovery retries
immediately after cooldown instead of adding another full refresh interval.
HTTP 429, login failures, and ordinary HTTP 403 responses do not trigger fallback.
API quota errors use the earliest available provider retry deadline; other failures get at most three attempts per URL
across restarts. Authentication errors stop the worker. Only one worker may own
an output directory. Use `--output-dir PATH` to choose another directory.
The default search covers Data Analyst only. Repeat `--search-url` with public
TopCV search URLs to explicitly include additional keywords. For a larger,
multi-industry dataset:

```bash
.venv/bin/python -u crawling/run_continuous.py --all-categories --pages 1 --interval 10
```

`--all-categories` adds actual public career-category links from rendered pages,
prioritizing broad industries before specialties. It does not invent pagination
URLs, repeatedly retry blocked pagination, or infer dataset category labels from this taxonomy.
The worker drains its saved queue before advancing to the next search; an empty
search does not force a 15-minute wait before trying the next category. After a
full search sweep, it waits at least 15 minutes before refreshing. Search position,
discovered categories, pending URLs, and quota cooldowns survive restarts.
`--pages 1` intentionally excludes deeper pagination when it is blocked.
`--interval 10` allows at most six jobs/minute, not a promised throughput or free
quota: network latency, extraction, provider limits and website access can reduce it.
No concurrent browser/API requests are added. Keep the default interval for a more
conservative crawl. Broader coverage is not a representative sample: first-page
ranking, overlapping categories and unavailable pages still create sampling bias.

The canonical dataset output is `data/CareerMapVN_jobs.csv`: one UTF-8 CSV with
the same 18 columns and column order as `data/VietJobs_sample.csv`. List values use
Python-list strings; missing values remain empty, including unknown category labels.
After each crawl or job-record change, refresh this file before publishing output:

```bash
python3 crawling/export_csv.py
```

The continuous worker also refreshes the CSV at startup when saved jobs exist and
after every successful job. With an explicit `--output-dir`, its CSV is saved as
`CareerMapVN_jobs.csv` inside that directory rather than overwriting the main dataset.

Keep all collected jobs in this single CSV rather than separate batch exports.
`data/continuous/` contains the supporting crawler state and source snapshots.
Raw benchmark HTML (which may include embedded third-party keys) and the runtime
`worker.lock` file remain ignored. Smoke-test and soak-test outputs are also committed
under `data/smoke_verified/` and `data/soak_15min_*/`.

The continuous output includes:

- `jobs/*.json`: one validated 25-field record per URL, atomically saved.
- `sources/`: original page markdown and model response/usage for source review.
- `pending.json`: atomically saved remaining job URLs, resumed without redoing completed jobs.
- `events/YYYY-MM-DD.jsonl`: UTC-timestamped discovery, API, completion and error events.
- `status.json`: PID, current status, counters, pending count, search cursor, token totals and next scheduled wakeup.

For a background launch, redirect stdout/stderr to `data/continuous/console.log`.
Read the PID from `status.json` and send `kill -TERM PID` for a graceful stop.
The worker needs the host awake and online; it does not install a login service,
prevent sleep, restart after reboot, or guarantee free-tier billing. Requests
continue at the configured pace until stopped or rejected by the provider.

### Local crawler monitor

```bash
python3 crawling/monitor.py
```

Open `http://127.0.0.1:8765` to see the crawler process state, actual CSV record
count, pending jobs, recent events, and a searchable, paginated view of all CSV
columns. Select a job title to read the full record or download the canonical CSV.
The page refreshes every five seconds. This read-only monitor uses only Python's
standard library, listens on localhost, and does not start or stop the crawler.
Use `--port 8766` if the default port is occupied.

## Data-skills pipeline (CareerMapVN)

Merges VietJobs (pinned HuggingFace revision) with the crawled TopCV CSV, keeps
postings that are data roles (tier A) or other jobs that require concrete data skills
(tier B), and exports an analysis-ready table with role, company domain, region,
salary and a 0/1 skill matrix. Full provenance, data dictionary and limitations:
[`data/README.md`](data/README.md).

```bash
# Option 1: Docker (no Python setup, no API key)
make docker                      # -> data/analysis/export/

# Option 2: local
pip install -r analysis/requirements.txt
make test all export             # -> data/analysis/export/{data_jobs.csv, all_jobs.csv, data_quality.md}
make analysis                    # optional starter analysis -> data/analysis/results/
```

LLM labels come from the committed cache `data/analysis/llm_labels.jsonl` and the crawl
rows are frozen by `data/analysis/crawl_snapshot_ids.txt`, so a fresh clone reproduces
the same tables without API calls. `make snapshot` deliberately adds newly crawled rows
(the new rows then need `OPENAI_API_KEY`). Human label validation:
`make validation-sheets`, two annotators fill `data/analysis/validation/annotator_{1,2}.csv`,
then `make validation-report`.

## Dashboard

Interactive Streamlit dashboard built around a map of Vietnam's 34 provinces (2025
boundaries, including Hoàng Sa and Trường Sa). Provinces are coloured by the share of all
job ads that are data-related, the number of postings, the share requiring a chosen skill,
or median salary; clicking a province focuses every tab on it. Other filters: posting
type, role, company industry, source, experience and required skills; skill demand with
95% CIs and group comparisons; salary by role, experience and region; a salary
estimator (log-salary OLS, cross-validated error shown); and a searchable,
downloadable posting table.

```bash
pip install -r dashboard/requirements.txt
make dashboard                   # http://localhost:8501
```

Deploy on [Streamlit Community Cloud](https://share.streamlit.io): New app → repository
`Cuki2910/CareerMapVN`, branch `main`, main file `dashboard/app.py`. It needs no
secrets; the data it reads (`dashboard/data_jobs.csv.gz`, `market_by_province.csv`,
`vn_provinces.geojson`) is
committed and refreshed by `make export`.

## Credits and license

Province boundaries: simplified from
[thanglequoc/vietnamese-provinces-database](https://github.com/thanglequoc/vietnamese-provinces-database) (MIT).

The base dataset is **VietJobs** (Hieu Pham-Dinh, Hung Nguyen Huy, Mo El-Haj, LREC 2026;
[HuggingFace](https://huggingface.co/datasets/dinhieufam/VietJobs),
[GitHub](https://github.com/dinhieufam/vietjobs)). This repository started as a fork of
it; the original README and code are kept in [`upstream/`](upstream/README.md).
Code is licensed under the MIT License; see [LICENSE](LICENSE).
