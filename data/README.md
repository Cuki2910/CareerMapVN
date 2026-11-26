# CareerMapVN data

This folder holds every dataset used by CareerMapVN: where each one comes from, how
it is processed, and what the analysis team receives. Everything under
`data/analysis/` can be rebuilt from a fresh clone with `make all export`, or with
`make docker`. No API key is needed for this.

## 1. Sources

| | VietJobs | CareerMapVN crawl (TopCV) |
|---|---|---|
| What | 48,092 Vietnamese job ads in 16 occupational categories | Job ads collected by `crawling/` from topcv.vn |
| Period | July–October 2025 | November 2026 |
| Access | Public HuggingFace dataset [`dinhieufam/VietJobs`](https://huggingface.co/datasets/dinhieufam/VietJobs), not gated | Public job pages, structured with an LLM (`crawling/llm_extract.py`) |
| Pinning | Revision `ea140511b77935704e93d21c2973b72f46d48902`, file `VietJobs.csv`, sha256 `85862b06…d49d477`, checked by `analysis/01_fetch.py` | The canonical CSV `data/CareerMapVN_jobs.csv`. The analysis only uses the posting ids listed in `data/analysis/crawl_snapshot_ids.txt` (3,347) |
| Licence / terms | The dataset card states no licence. The companion code repo is MIT. Cite: Pham-Dinh, Nguyen Huy & El-Haj, *VietJobs*, LREC 2026. Use for non-commercial academic research only | TopCV content belongs to TopCV and the employers. Used here for non-commercial coursework only. Crawled at a low rate (one page every ≥10 s, backoff when blocked). No personal data of candidates. Raw HTML is not published |
| In git? | No: downloaded to `data/raw/` (gitignored) | Yes |

`data/VietJobs_sample.csv` holds 5 sample rows. It fixes the column schema that the
crawler output must match (see `AGENTS.md`).

## 2. Pipeline

| Step | Script | Input → output | What it does |
|---|---|---|---|
| 1 | `analysis/01_fetch.py` | HF → `raw/VietJobs.csv` | Downloads the pinned revision and verifies its sha256 |
| 2 | `analysis/02_prepare.py` | raw + crawl CSV → `analysis/jobs.parquet` | Unicode NFC and whitespace cleaning. Parses salary to million VND/month (VietJobs `salary_min`/`salary_max` are truncated, so it re-parses the `salary` text; TopCV values given in VND are converted; `0` means unknown). Parses experience to years. Maps location → province (34 provinces after the 2025 merger) → region (`analysis/locations.csv`). Merges reposts that share (title, description): keeps one row, unions their locations, takes the median salary. Builds a stable `id` = sha1(title, description)[:12] |
| 3 | `analysis/03_candidates.py` | → `candidates.parquet` | Recall-oriented regex on title and skills (`analysis/skills.tsv`). Adds 300 seeded random non-candidates for a recall audit |
| 4 | `analysis/04_llm_label.py` | → `llm_labels.jsonl`, `labels.parquet` | One LLM labels each candidate's `tier`, `role` and `domain`, validated against a pydantic schema. Labels are cached by (id, prompt hash), so a rerun makes no API calls |
| 5 | `analysis/05_validate.py` | → `validation/` | Two annotators label 150 blind rows. Reports Cohen's κ and LLM precision/recall |
| 6 | `analysis/06_skills.py` | → `data_jobs.parquet` | Builds the 0/1 skill matrix for the tier A+B postings |
| – | `analysis/export.py` | → `export/` | Writes flat CSVs and `data_quality.md` for the analysis team |

Steps 7–8 (`07_analyze.py`, `08_salary.py`, run with `make analysis`) are starter
analyses for the DA team.

## 3. Outputs for analysis (`data/analysis/`)

| File | Rows | In git? | Description |
|---|---|---|---|
| `export/data_jobs.csv` | 2,222 | no (rebuild) | **Main analysis table**: data-related postings (tier A + B) |
| `export/all_jobs.csv` | 38,787 | no (rebuild) | All deduplicated postings with labels. Use it for "share of the market" denominators |
| `export/data_quality.md` | – | no (rebuild) | Row counts at each stage, missingness by source, label provenance |
| `*.parquet` | – | no (rebuild) | Same tables with full text and list columns |
| `llm_labels.jsonl` | 3,465+ | **yes** | LLM label cache. It is the only non-deterministic input, so it is committed |
| `crawl_snapshot_ids.txt` | 3,347 | **yes** | Freezes which crawl rows are analysed (the crawler keeps appending) |
| `validation/annotator_{1,2}.csv` | 150 | **yes** | Human validation sheets |

### Data dictionary: `data_jobs.csv`

| Column | Type | Meaning |
|---|---|---|
| `id` | str | Stable posting id (sha1 of title + description) |
| `source`, `period` | str | `vietjobs` (2025-07/10) or `topcv_crawl` (2026-11) |
| `job_title`, `location`, `salary`, `experience_required`, `contract_type`, `qualifications`, `technical_skills`, `soft_skills`, `languages_required`, `working_hours`, `benefits`, `country` | str | Original fields, NFC-normalised |
| `category` | str | VietJobs occupational category (16 labels). Empty for the crawl |
| `salary_min`, `salary_max`, `salary_avg` | float | Million VND/month. `salary_avg` is the midpoint, empty unless both bounds are known ("Thoả thuận" ⇒ empty) |
| `experience_years` | float | Required years ("Không yêu cầu" = 0, months / 12) |
| `provinces`, `regions` | `;`-list | Province names. Regions: `Hà Nội`, `Hồ Chí Minh`, `Miền Bắc`, `Miền Trung`, `Miền Nam`, `Nước ngoài` |
| `n_reposts` | int | Number of raw rows merged into this posting |
| `tier` | str | `A` = data role. `B` = other occupation that names a concrete data skill |
| `role` | str | A: `da_bi`, `ds_ml_ai`, `de`, `ba`, `dba_governance`, `quant_risk`. B: `software_it`, `marketing_digital`, `finance_accounting`, `operations_supply_chain`, `sales_business`, `hr_admin`, `research_education`, `engineering_manufacturing`, `ai_applied`, `other` |
| `domain` | str | Industry of the hiring company (15 values, including `unknown`) |
| `sk_<skill>` | 0/1 | Skill named in the title, description, requirements or skills list. Regexes in `analysis/skills.tsv` (55 skills, with Vietnamese synonyms) |
| `grp_<group>` | 0/1 | Any skill in the group: `programming`, `database`, `bi_viz`, `spreadsheet`, `web_product_analytics`, `statistics`, `ml_ai`, `big_data`, `data_engineering`, `cloud`, `quant_risk` |
| `skill_count` | int | Number of distinct dictionary skills |

## 4. Known limitations

- **Salary**: these are advertised ranges. About 29% of VietJobs postings and 53% of
  crawl postings say "Thoả thuận" (negotiable), so salary is missing not at random.
- **Tier B is a lower bound**: the rule filter misses some postings. The recall
  audit estimates how many (`export/data_quality.md`). Tier A is close to complete.
- **Labels** come from one LLM (`labels.parquet: provider, model`). They are checked
  against two human annotators in `validation/report.md`.
- **The two sources** differ in period (2025 vs 2026) and portal. Keep `source` as
  a control variable.
- **Region** analyses count a multi-location posting once per region.

## 5. Re-crawling / refreshing

`make snapshot` re-pins the analysis to the current crawl CSV. The next `make all`
then calls the LLM only for the new rows; this needs `OPENAI_API_KEY` in `.env`.
Commit both the updated `crawl_snapshot_ids.txt` and `llm_labels.jsonl`.

## 6. Other files

- `continuous/`: resumable crawler state and source records (see `AGENTS.md`).
- `upstream/data/`: placeholders of the upstream VietJobs
  fine-tuning code. They are not used by CareerMapVN.
