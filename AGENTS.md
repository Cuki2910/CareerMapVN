# Dataset Output Rules

- The canonical crawler dataset is `data/CareerMapVN_jobs.csv`. Keep all collected
  jobs in this single CSV; do not create separate CSVs per job, batch, or timestamp.
- Match the column names and order in `data/VietJobs_sample.csv`. Preserve UTF-8
  text, Python-list string formatting, and empty cells for missing values. Never
  invent category labels or missing salary values to fill the sample schema.
- JSON records under `data/continuous/jobs/` are resumable crawler state and source
  records, not the final dataset deliverable. Keep them for recovery and auditing.
- After collecting or changing job records, run `python3 crawling/export_csv.py`
  to refresh the canonical CSV before reporting completion or committing/pushing
  dataset changes. Check that its row count matches the source job records.
- Never include `.env`, API credentials, runtime lock files, or raw HTML containing
  embedded keys in published output.
