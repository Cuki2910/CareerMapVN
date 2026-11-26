"""Step 4: LLM labels (tier, role, domain) for candidates + recall-audit rows.

Uses the crawler's provider client restricted to LABEL_PROVIDER (.env keys). Results are appended to
data/analysis/llm_labels.jsonl keyed by (id, prompt_version), so reruns only call
the API for missing rows; editing PROMPT changes the version and relabels.
"""
import argparse
import asyncio
import hashlib
import json
import random
import sys
import time
from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import BaseModel, model_validator

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/analysis"
CACHE = DATA / "llm_labels.jsonl"
sys.path.insert(0, str(ROOT / "crawling"))

A_ROLES = ("da_bi", "ds_ml_ai", "de", "ba", "dba_governance", "quant_risk")
B_ROLES = ("software_it", "marketing_digital", "finance_accounting", "operations_supply_chain", "sales_business",
           "hr_admin", "research_education", "engineering_manufacturing", "ai_applied", "other")
DOMAINS = ("banking_finance_insurance", "ecommerce_retail_fmcg", "tech_software_telecom", "manufacturing_industrial",
           "logistics_transport", "real_estate_construction", "healthcare_pharma", "education", "media_marketing_agency",
           "consulting_outsourcing_services", "energy_agriculture", "hospitality_tourism", "public_sector", "other",
           "unknown")

PROMPT = f"""You label Vietnamese job postings for a labour-market study of data skills.
For EACH posting return: tier, role, domain, reason.

tier:
- "A" = the job itself is a data role. Roles (use the closest):
  da_bi (data/BI/reporting/insight analyst, MIS, data visualization),
  ds_ml_ai (data scientist, ML/AI engineer, NLP/CV engineer, AI researcher),
  de (data engineer, ETL, data platform/warehouse),
  ba (business analyst / phân tích nghiệp vụ),
  dba_governance (database administrator, data governance, data quality, master data),
  quant_risk (quantitative/credit/market risk modelling, actuarial, pricing analytics).
- "B" = the main occupation is NOT a data role, but the posting explicitly requires or describes
  at least one concrete data skill: SQL (any use, including software developers/testers),
  Python/R for data, BI tools (Power BI, Tableau, Looker), web/product analytics (Google Analytics,
  A/B testing), statistics/SPSS/econometrics, advanced Excel (Pivot, VLOOKUP/XLOOKUP, Power Query,
  VBA/macros), ML/AI frameworks, ETL/data warehouse, or practical use of AI/GenAI tools (ChatGPT,
  Midjourney, prompt engineering, AI trainer / AI output evaluation, AI content).
  Role = main occupation: {", ".join(B_ROLES)}. Use ai_applied when the AI-tool usage is the core of the job.
- "none" = no concrete data skill. Plain office Excel/"tin học văn phòng", typing/data entry (nhập liệu),
  telesales "có sẵn data" (data = customer leads), or vague "khả năng phân tích" do NOT count.
  role must be "none".
domain = industry of the HIRING COMPANY (not the job function); "unknown" if not inferable:
  {", ".join(DOMAINS)}.
reason = at most 15 words, quoting the decisive skill/phrase.

Return ONLY JSON: {{"labels": [{{"id": "...", "tier": "...", "role": "...", "domain": "...", "reason": "..."}}]}}
with exactly one entry per posting id given below."""
# One labeller for every row: mixing models made tier B depend on which provider answered.
LABEL_PROVIDER = "openai"
PROMPT_VERSION = hashlib.sha1(PROMPT.encode()).hexdigest()[:8]


class Label(BaseModel):
    id: str
    tier: Literal["A", "B", "none"]
    role: Literal[A_ROLES + B_ROLES + ("none",)]
    domain: Literal[DOMAINS]
    reason: str

    @model_validator(mode="after")
    def role_matches_tier(self):
        allowed = {"A": A_ROLES, "B": B_ROLES, "none": ("none",)}[self.tier]
        if self.role not in allowed:
            raise ValueError(f"role {self.role} invalid for tier {self.tier}")
        return self


def cut(s, n):
    s = "" if s is None or s != s else str(s)
    return s if len(s) <= n else s[:n] + "…"


def render(row):
    return (f"### id: {row.id}\nTitle: {row.job_title}\nPortal category: {cut(row.category, 80) or '-'}\n"
            f"Listed skills: {cut(row.technical_skills, 400) or '-'}\nDescription: {cut(row.description, 2500)}\n"
            f"Requirements: {cut(row.requirements_text, 2000)}")


async def label_batch(router, batch, out):
    from llm_extract import extract_json_from_codeblock

    ids = list(batch.id)
    used = {}

    def validate(response):
        data = extract_json_from_codeblock(response.content)
        labels = [Label.model_validate(x) for x in (data or {}).get("labels", [])]
        if sorted(x.id for x in labels) != sorted(ids):
            raise ValueError("labels do not cover the batch ids exactly")
        return labels

    def on_event(event, **kw):
        if event == "api_response":
            used.update(provider=kw["provider"], model=kw["model"])

    prompt = PROMPT + "\n\n" + "\n\n".join(render(r) for r in batch.itertuples())
    for lab in validate(await router.ainvoke(prompt, validate=validate, on_event=on_event)):
        out.write(json.dumps({**lab.model_dump(), "prompt_version": PROMPT_VERSION, **used,
                              "labelled_at": time.strftime("%Y-%m-%dT%H:%M:%S")}, ensure_ascii=False) + "\n")
    out.flush()


def cached():
    if not CACHE.exists():
        return pd.DataFrame(columns=["id", "prompt_version"])
    return pd.read_json(CACHE, lines=True, dtype={"id": str})


async def run(args):
    cand = pd.read_parquet(DATA / "candidates.parquet")
    done = set(cached().query("prompt_version == @PROMPT_VERSION and provider == @LABEL_PROVIDER").id)
    todo = cand[~cand.id.isin(done)].sample(frac=1, random_state=2010)
    if todo.empty:
        print(f"prompt {PROMPT_VERSION}: all {len(cand)} rows cached; no API calls needed")
        return
    from dotenv import load_dotenv  # only needed when the API is actually called
    from llm_extract import ProvidersUnavailable, initialize_chat_model

    load_dotenv(ROOT / ".env")
    router = initialize_chat_model()
    router.providers = [p for p in router.providers if p[0] == LABEL_PROVIDER]
    if not router.providers:
        sys.exit(f"{len(todo)} rows need labels but {LABEL_PROVIDER.upper()}_API_KEY is not configured")
    if args.limit:
        todo = todo.head(args.limit)
    batches = [todo.iloc[i:i + args.batch_size] for i in range(0, len(todo), args.batch_size)]
    print(f"prompt {PROMPT_VERSION}: {len(done)} cached, {len(todo)} to label in {len(batches)} batches")

    sem, failed = asyncio.Semaphore(args.concurrency), []
    with open(CACHE, "a", encoding="utf-8") as out:
        async def worker(i, batch):
            async with sem:
                for attempt in range(5):
                    try:
                        await label_batch(router, batch, out)
                        print(f"  batch {i + 1}/{len(batches)} ok", flush=True)
                        return
                    except ProvidersUnavailable as e:
                        await asyncio.sleep(max(1, e.args[0] - time.time()))
                    except ValueError as e:
                        print(f"  batch {i + 1} invalid output ({e}); retry {attempt + 1}", flush=True)
                failed.append(i)

        await asyncio.gather(*(worker(i, b) for i, b in enumerate(batches)))
    if failed:
        sys.exit(f"{len(failed)} batches failed; rerun to retry them")


def export():
    lab = cached().query("prompt_version == @PROMPT_VERSION and provider == @LABEL_PROVIDER")
    lab = lab.drop_duplicates("id", keep="last")
    cand = pd.read_parquet(DATA / "candidates.parquet")
    merged = cand.merge(lab[["id", "tier", "role", "domain", "reason", "provider", "model"]], on="id", how="left")
    merged.to_parquet(DATA / "labels.parquet", index=False)
    print(f"labelled {merged.tier.notna().sum()}/{len(merged)}")
    for name, part in [("candidates", merged[merged.is_candidate]), ("recall audit", merged[merged.recall_audit])]:
        print(f"{name}: {part.tier.value_counts().to_dict()}")
    print(merged.groupby("tier").role.value_counts().to_string())


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, help="label at most N new rows (smoke test)")
    p.add_argument("--batch-size", type=int, default=8)
    p.add_argument("--concurrency", type=int, default=3)
    p.add_argument("--export-only", action="store_true")
    a = p.parse_args()
    if not a.export_only:
        asyncio.run(run(a))
    export()
