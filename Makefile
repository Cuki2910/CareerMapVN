PY ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
A := data/analysis

# Data-engineering deliverable: the analysis-ready table data/analysis/data_jobs.parquet.
all: $(A)/data_jobs.parquet

data/raw/VietJobs.csv: analysis/01_fetch.py
	$(PY) analysis/01_fetch.py

$(A)/jobs.parquet: analysis/02_prepare.py analysis/locations.csv data/raw/VietJobs.csv data/CareerMapVN_jobs.csv
	$(PY) analysis/02_prepare.py

$(A)/candidates.parquet: analysis/03_candidates.py analysis/skills.tsv $(A)/jobs.parquet
	$(PY) analysis/03_candidates.py

# Calls the LLM API only for rows missing from the committed cache llm_labels.jsonl.
$(A)/labels.parquet: analysis/04_llm_label.py $(A)/candidates.parquet
	$(PY) analysis/04_llm_label.py

$(A)/data_jobs.parquet: analysis/06_skills.py analysis/skills.tsv $(A)/labels.parquet
	$(PY) analysis/06_skills.py

export: $(A)/data_jobs.parquet
	$(PY) analysis/export.py

# Starter analysis (owned by the DA team; optional for the data layer).
analysis: $(A)/data_jobs.parquet
	$(PY) analysis/07_analyze.py
	$(PY) analysis/08_salary.py

# Human validation: `make validation-sheets`, fill both CSVs, then `make validation-report`.
validation-sheets: $(A)/labels.parquet
	$(PY) analysis/05_validate.py sample

validation-report:
	$(PY) analysis/05_validate.py score

# Deliberately re-pin the crawl snapshot to the current crawler CSV (new rows then need LLM labels).
snapshot:
	$(PY) analysis/02_prepare.py --refresh-snapshot

test:
	$(PY) analysis/test_analysis.py

docker:
	docker build -t careermapvn . && docker run --rm -v "$$(pwd)/$(A)/export:/app/$(A)/export" careermapvn

.PHONY: all export analysis test validation-sheets validation-report snapshot docker
