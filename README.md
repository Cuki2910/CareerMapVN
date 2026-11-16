# VietJobs: A Vietnamese Job Advertisement Dataset

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Dataset](https://img.shields.io/badge/VietJobs%20Data-🤗%20HuggingFace%20Dataset-blue)](https://huggingface.co/datasets/dinhieufam/VietJobs)
[![GitHub](https://img.shields.io/badge/⭐%20Star-VietJobs-green)](https://github.com/dinhieufam/vietjobs)

---

⭐ **If you find this project helpful, please consider giving it a [star on GitHub](https://github.com/dinhieufam/vietjobs)!**

---

<p align="center">
  <a href="https://www.linkedin.com/in/dinhieufam/" target="_blank"><strong>Hieu Pham-Dinh</strong></a>,
  <a href="https://github.com/whistle-hikhi" target="_blank"><strong>Hung Nguyen Huy</strong></a>,
  <a href="https://elhaj.uk/" target="_blank"><strong>Mo El-Haj</strong></a>,
</p>

<p align="center">
  <em>College of Engineering and Computer Science, VinUniversity</em><br>
</p>

<details>
  <summary><strong>📚 Table of Contents</strong> (click to expand)</summary>

- [🔍 What is VietJobs?](#-what-is-vietjobs)
- [📊 Dataset Statistics](#-dataset-statistics)
- [🗂 Repo Layout](#-repo-layout)
- [I. Quickstart](#i-quickstart)
  - [1. 📥 Clone & Setup](#1--clone--setup)
  - [2. 📦 Install Dependencies](#2--install-dependencies)
  - [3. Run Format, Fine-tune & Evaluation](#3-run-format-fine-tune--evaluation)
- [📄 License](#-license)

</details>

## 📣 News

- **[Feb 2026]** Released experiment scripts and dataset
- **[Feb 2026]** The paper has been accepted at LREC 2026

---

## 🔍 What is VietJobs?

VietJobs is a comprehensive dataset designed for **Vietnamese Natural Language Processing** research, particularly focused on job advertisement analysis. The dataset supports multiple downstream tasks:

- **Job Classification** — Categorizing job postings into industry sectors
- **Salary Estimation** — Predicting salary ranges from job descriptions
- **Information Extraction** — Structured extraction of job attributes

### Key Features

- 🌏 **Comprehensive Coverage**: All 34 Vietnamese provinces and municipalities
- 📊 **Large Scale**: 48,092 job postings with 15+ million words
- 🏷️ **Multi-task Ready**: Pre-processed for classification and regression tasks
- 🔧 **Research Ready**: Includes training, evaluation, and fine-tuning scripts
- 🤖 **LLM Compatible**: Formatted for modern language model training

### Data Distribution

- **Job Categories**: Technology, Finance, Healthcare, Education, Manufacturing, etc.
- **Experience Levels**: Entry-level to Senior (0–10+ years)
- **Contract Types**: Full-time, Part-time, Internship, Freelance
- **Salary Ranges**: 1–500 million VND

---

## 📊 Dataset Statistics

| Metric | Value |
|--------|-------|
| Total Job Postings | 48,092 |
| Total Words | 15,000,000+ |
| Geographic Coverage | 34 provinces/municipalities |
| Average Posting Length | ~321 words |
| Job Categories | 16 categories |
| Time Period | July – October 2025 |

---

## 🗂 Repo Layout

- `data/` — dataset samples and directory conventions (full dataset on HuggingFace)
- `run_format_prompt.sh` — format prompts and prepare data for training
- `run_finetune_lora.sh` — fine-tune the model using LoRA
- `run_evaluation.sh` — run evaluation pipelines
- `requirements.txt` — Python dependencies

---

## I. Quickstart

### 1. 📥 Clone & Setup

```bash
git clone https://github.com/dinhieufam/vietjobs.git
cd VietJobs
```

### 2. 📦 Install Dependencies

**Create a virtual environment**

```bash
python -m venv venv
source venv/bin/activate   # On Windows: venv\Scripts\activate
```

**Install dependencies**

```bash
pip install -r requirements.txt
```

**Dataset**: The dataset is available on HuggingFace and you can download it via:

```bash
huggingface-cli download dinhieufam/VietJobs
```

### 3. Run Format, Fine-tune & Evaluation

**Step 1 — Format prompts and prepare data**

```bash
bash run_format_prompt.sh
```

**Step 2 — Fine-tune the model using LoRA**

```bash
bash run_finetune_lora.sh
```

**Step 3 — Run evaluation**

```bash
bash run_evaluation.sh
```

---

## Crawler

The crawler accepts existing job URLs; it does not discover job links automatically.
Use Python 3.11+ and the crawler-only dependencies (the root requirements also include GPU training packages).

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

`data/continuous/` is ignored by git and contains:

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

## 📄 License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

---

<p align="center">
  <strong>Made with ❤️ for the Vietnamese NLP community</strong>
</p>
