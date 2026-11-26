# CareerMapVN data pipeline

This document explains how CareerMapVN turns raw Vietnamese job ads into the table
the analysis and dashboard use. Part A describes the method: what each step does, why,
and what it produces. Part B is a practical guide for teammates: how to run the
pipeline, which file to read, and what to watch for.

All numbers below come from the current pinned snapshot. Re-running the pipeline
reproduces them exactly (`data/analysis/export/data_quality.md` is regenerated each run).

---

# Part A - Method

## Goal

The research questions concern **data skills in the Vietnamese labour market**: which
skills employers ask for, in which provinces and industries, and how they relate to
advertised salary. That needs one table in which every row is a unique job posting that
is either:

- **Tier A, a data role.** The job itself is a data job: data/BI analyst, data scientist
  or ML/AI engineer, data engineer, business analyst, DBA or data governance, quant or
  risk modelling.
- **Tier B, a data-skill job.** Another occupation (marketing, accounting, software,
  operations…) whose ad names at least one *concrete* data skill: SQL, Python/R,
  Power BI/Tableau, Google Analytics, statistics, advanced Excel, ML frameworks, ETL, or
  practical use of GenAI tools.

Ads that only mention office software ("tin học văn phòng"), data entry ("nhập liệu"),
or sales leads ("data có sẵn") are not data-related.

## Overview

```
 VietJobs (HuggingFace, 2025)      TopCV crawl (2026)
         48,092 ads                   3,076 ads (pinned)
              \                        /
               ▼                      ▼
  1 fetch ── 2 prepare: clean, parse, map provinces, merge reposts
                         │  38,516 unique postings
                         ▼
             3 candidates: broad keyword + skill rules
                         │  3,117 candidates  (+300 random non-candidates for audit)
                         ▼
             4 label: one LLM assigns tier / role / company industry
                         │  539 tier A  +  1,655 tier B
                         ▼
             5 skills: 55-skill dictionary → 0/1 matrix
                         ▼
             6 export: CSVs, data-quality report, dashboard data
                         ▼
             5' validate: two people re-label 150 blind rows (agreement, precision/recall)
```

| Step | Script | Output (`data/analysis/`) | Rows |
|---|---|---|---|
| 1 Fetch | `analysis/01_fetch.py` | `data/raw/VietJobs.csv` | 48,092 |
| 2 Prepare | `analysis/02_prepare.py` | `jobs.parquet` | 38,516 |
| 3 Candidates | `analysis/03_candidates.py` | `candidates.parquet` | 3,117 + 300 |
| 4 Label | `analysis/04_llm_label.py` | `llm_labels.jsonl`, `labels.parquet` | 3,417 |
| 5 Skills | `analysis/06_skills.py` | `data_jobs.parquet` | 2,194 |
| 6 Export | `analysis/export.py` | `export/`, `dashboard/` | 2,194 / 38,516 |
| Validate | `analysis/05_validate.py` | `validation/` | 150 |

## Step 1 - Fetch the base dataset

**What.** Downloads `VietJobs.csv` from the HuggingFace dataset `dinhieufam/VietJobs`
at a fixed revision (`ea14051`) and checks its SHA-256.

**Why.** A dataset hosted online can change without notice. Pinning the revision and
checking the checksum guarantees that everyone works on byte-identical data. If the
upstream file changes, the step stops instead of silently producing different results.

## Step 2 - Prepare: one clean row per posting

**Merge sources.** VietJobs (Jul-Oct 2025) and our own TopCV crawl (Nov 2026) share
the same column schema. Each row keeps a `source` and `period` column, so analyses can
control for the one-year gap and the different portal.

**Freeze the crawl.** The crawler keeps adding rows to `data/CareerMapVN_jobs.csv`. The
analysis therefore uses only the 3,076 posting ids listed in
`data/analysis/crawl_snapshot_ids.txt`. New rows are ignored until someone deliberately
re-pins the snapshot.

**Clean text.** All text is Unicode-normalised (NFC) and whitespace is collapsed.
Vietnamese text can encode the same letter in two byte forms. Without normalisation,
identical words, and identical ads, would not match.

**Parse salary.** Salary becomes `salary_min`, `salary_max` and the midpoint
`salary_avg`, all in million VND per month. Three problems were found and fixed:

- VietJobs' numeric columns truncate decimals (8.5 → 8), so salary is re-parsed from the
  original text.
- A few crawled ads give salary in VND ("15,000,000"); these are converted to millions.
- "0.0 triệu" and "Thoả thuận" mean *negotiable*. They become missing, never zero.
  No salary is ever imputed.

**Parse experience.** "2 năm" → 2, "6 tháng" → 0.5, "Không yêu cầu" → 0.

**Map locations to provinces.** Free-text locations ("Hà Đông", "Quận 7",
"Phường Sài Gòn (thuộc Quận 1 cũ)", "Đà Nẵng: 73 Bùi Trang Chước…") are mapped to
Vietnam's **34 provinces after the July 2025 merger**, then to six regions (Hà Nội,
Hồ Chí Minh, North, Central, South, abroad). The mapping table
`analysis/locations.csv` (225 aliases) handles districts, old province names merged
in 2025, and both tone spellings ("Khánh Hoà" / "Khánh Hòa"). 99.6% of postings get a
province. The rest are "Toàn quốc" (nationwide), foreign cities, or rare place names.

**Merge reposts.** Employers repost the same ad, sometimes once per city. Rows with the
same title and description are merged into one posting: locations are unioned and
salaries take the median. This removed 12,686 duplicate rows (24% of postings had
reposts). Without this step, one employer posting 58 copies would dominate the counts.
Each posting gets a stable `id` (hash of title and description).

**Result.** 51,202 raw rows → **38,516 unique postings**. Salary is known for 69%.

## Step 3 - Candidate filter (high recall)

**What.** A posting becomes a *candidate* if **either**

- its title matches a broad data-related pattern (data, dữ liệu, BI, analyst, phân tích,
  AI, thống kê, rủi ro, báo cáo, kế hoạch, BA, …), **or**
- its text mentions any high-signal skill from the skill dictionary (SQL, Python,
  Power BI, GA4, statistics, ETL, advanced Excel, GenAI tools, …).

Lead-selling patterns ("data có sẵn", telesales, "nhập liệu") are *flagged* but not
removed. The LLM makes the final decision.

**Why.** Rules alone cannot tell "phân tích dữ liệu" (data analysis) from "phân tích tài
chính" (financial analysis), or "data có sẵn" (customer leads) from real data work. The
rules are therefore deliberately loose: they only shrink 38,516 postings to 3,117 so
that the more expensive LLM step is affordable. Precision is left to step 4.

**Recall audit.** 300 postings that did **not** pass the filter are drawn at random
(fixed seed) and labelled too. The share of data-related postings among them estimates
what the filter misses (see Limitations).

## Step 4 - LLM labelling

**What.** Each candidate (and audit row) is sent to one LLM, 8 postings per request,
with a fixed prompt (`PROMPT` in `analysis/04_llm_label.py`). It returns, per posting:

| Field | Values |
|---|---|
| `tier` | `A`, `B`, `none` (definitions as in *Goal*) |
| `role` | Tier A: `da_bi`, `ds_ml_ai`, `de`, `ba`, `dba_governance`, `quant_risk`. Tier B: the main occupation, e.g. `marketing_digital`, `software_it`, `finance_accounting`, `ai_applied` |
| `domain` | industry of the **hiring company** (14 categories, including `other` and `unknown`), not the job function |
| `reason` | ≤15 words quoting the decisive phrase, for auditing |

**Safeguards.**

- Every response is validated against a strict schema (pydantic). Unknown labels, a role
  that does not belong to its tier, or a missing posting id are rejected and retried.
- **One model labels every row.** An early run rotated between four providers. One of
  them put 17% of its tier B rows on ads with no concrete data skill, versus 3.5% for
  another, so the tier B count depended on which provider happened to answer. All rows
  were relabelled with a single model.
- **Cache.** Labels are stored in `data/analysis/llm_labels.jsonl` (committed), keyed by
  posting id and a hash of the prompt. Re-running needs no API key and gives identical
  labels. Changing the prompt automatically triggers relabelling.

**Result.** Of 3,117 candidates: 538 tier A, 1,640 tier B, 939 none. Most title-matched
"analysts" in finance turned out to be tier A `quant_risk` or tier B. 107 of the 115
lead-selling ads flagged in step 3 were correctly rejected.

## Step 5 - Skill matrix

**What.** For each tier A/B posting, the title, description, requirements and listed
skills are scanned with the 55 regular expressions in `analysis/skills.tsv`. The output
is one 0/1 column per skill (`sk_SQL`, `sk_Power BI`, …), one per skill group
(`grp_database`, `grp_bi_viz`, `grp_ml_ai`, …) and `skill_count`.

**Why a dictionary, not the LLM.** Skill detection must be identical across runs,
transparent, and easy to extend. Each pattern includes Vietnamese synonyms
("trực quan hóa dữ liệu" = data visualisation, "học máy" = machine learning) and
context guards. For example, **R** only matches next to other analytics tools or in
"ngôn ngữ R", so the letter R in ordinary text does not count. Generic entries (plain
Excel, "data analysis") are kept in the matrix but hidden from skill rankings by default.

## Step 6 - Export

Writes the hand-off files (Part B) and `data_quality.md`, which reports row counts at
each stage, missingness by source, and label provenance. It also writes two compact
files for the dashboard, `dashboard/data_jobs.csv.gz` and
`dashboard/market_by_province.csv`, which hold the total ads per province and serve as
the denominator for "share of all ads".

## Validation

`analysis/05_validate.py sample` draws 150 rows, stratified (40 tier A, 50 tier B,
30 none, 30 recall-audit). It writes two identical sheets with the LLM labels hidden.
Two team members label them independently. `analysis/05_validate.py score` then reports:

- Cohen's κ between the two humans (how well-defined the categories are),
- κ between the LLM and each human,
- LLM precision and recall for "data-related" (A or B) on rows where both humans agree,
- the estimated number of data-related postings the step-3 filter missed.

## Reproducibility

- Pinned inputs: VietJobs revision + SHA-256, crawl id snapshot, LLM label cache.
- Fixed random seed (2010) for every sample.
- Pinned package versions (`analysis/requirements.txt`).
- `make docker` rebuilds everything from a fresh clone in a container, without API keys.
- `make test` checks the parsers (salary, experience, locations) and the dashboard.

## Limitations

- **Advertised salary only.** 31% of postings say "Thoả thuận" (29% of VietJobs, 52% of
  TopCV). Salary results describe ads that disclose pay, which may differ systematically
  from those that do not.
- **Tier B is a lower bound.** In the recall audit, 16 of 300 random non-candidates were
  data-related (5.3%). Almost all are tier B marketing jobs that measure campaign KPIs.
  Tier A misses are negligible (1 of 300).
- **LLM labels are not ground truth.** Precision and recall are reported once the human
  validation is complete.
- **Two sources, two periods.** VietJobs (2025) and TopCV (2026) differ in time and
  portal. Keep `source` as a control variable.
- **Multi-location ads** count once in each listed province. The listed location is
  where the ad says the job is, not necessarily where the person will work.
- **Company domain** is inferred from the ad text and is `unknown` for about a third of
  data-related postings.

---

# Part B - Using the data

## Run it

```bash
pip install -r analysis/requirements.txt
make all export        # steps 1-6; no API key needed (labels come from the cache)
make test              # parser + dashboard checks
make docker            # same, inside Docker
make analysis          # optional starter analysis -> data/analysis/results/
```

To include newly crawled TopCV ads, run `make snapshot` and then `make all export`.
The new rows need LLM labels, so `OPENAI_API_KEY` must be set in `.env`. Commit the
updated `crawl_snapshot_ids.txt` and `llm_labels.jsonl` afterwards.

## Which file to use

| You want… | Use |
|---|---|
| Data-related postings with skills (main analysis table) | `data/analysis/export/data_jobs.csv` (2,194 rows) |
| Every posting, for "share of the market" denominators | `data/analysis/export/all_jobs.csv` (38,516 rows) |
| Full text (description, requirements) or list columns | the matching `.parquet` file in `data/analysis/` |
| Row counts and missingness to quote in the report | `data/analysis/export/data_quality.md` |

The full column dictionary is in [`data/README.md`](../data/README.md#data-dictionary-data_jobscsv).
The most used columns:

| Column | Meaning |
|---|---|
| `tier` | `A` data role, `B` data-skill job |
| `role` | data role (tier A) or main occupation (tier B) |
| `domain` | hiring company's industry (`unknown` if not stated) |
| `provinces`, `regions` | `;`-separated lists (an ad can list several) |
| `salary_avg` | million VND/month; empty = not disclosed |
| `experience_years` | required experience, 0 = none required |
| `source` | `vietjobs` (2025) or `topcv_crawl` (2026) |
| `sk_*`, `grp_*`, `skill_count` | skill flags, group flags, count of distinct skills |

## Analysis checklist

- **Compare tiers separately.** Tier A has 539 rows, tier B has 1,655. Pooled results are
  mostly driven by tier B (half of it is marketing).
- **Explode list columns** (`provinces`, `regions`) before grouping by place, and say that
  multi-location ads count in each.
- **Small groups.** Within Vietnam, only Hà Nội, Hồ Chí Minh and Đà Nẵng have more than 30
  data-related postings. For regional comparisons, use Hà Nội / Hồ Chí Minh / other, and show
  confidence intervals.
- **Salary.** Filter `salary_avg` to 1-200 million VND to drop stipends and commission-only
  outliers, and state that "Thoả thuận" ads are excluded.
- **Control for `source`** in any model that pools both datasets.
- **Do not edit** `data/CareerMapVN_jobs.csv` or anything in `data/analysis/` by hand.
  Change the code or the reference tables (`locations.csv`, `skills.tsv`) and re-run.
