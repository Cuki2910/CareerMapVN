"""Step 3: recall-oriented rule filter -> candidates for LLM labelling.

A posting is a candidate if its title looks like a data role OR its text mentions
any high-signal data skill (skills.tsv recall=1). Noise patterns are only flagged,
never dropped: the LLM + human audit decide. A seeded random sample of
non-candidates is added to estimate what the rules miss (recall audit).
"""
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/analysis"
SEED, N_AUDIT = 2010, 300

TITLE = re.compile(
    r"\bdata\b|dữ liệu|\bbi\b|business intelligence|analy[st]|phân tích|scien|khoa học dữ liệu|\bai\b|trí tuệ nhân tạo"
    r"|machine learning|học máy|\bml\b|\bmlops\b|\betl\b|database|\bdba\b|cơ sở dữ liệu|thống kê|statistic|quant"
    r"|định lượng|rủi ro|\brisk\b|insight|báo cáo|\breport|\bmis\b|\bcrm\b|kế hoạch|planning|forecast|dự báo"
    r"|nghiên cứu thị trường|market research|\bba\b|nghiệp vụ|pricing|định giá|actuar|thẩm định|kiểm soát nội bộ"
)
NOISE = re.compile(r"có sẵn|sẵn data|data nóng|data khách|cung cấp data|100% data|nhập liệu|data entry|gán nhãn"
                   r"|dán nhãn|telesale|telemarketing|tư vấn tuyển sinh")


def main():
    jobs = pd.read_parquet(DATA / "jobs.parquet")
    skills = pd.read_csv(ROOT / "analysis/skills.tsv", sep="\t")
    strong = skills[skills.recall == 1]
    title = jobs.job_title.str.lower()

    hits = pd.DataFrame({s: jobs.text.str.contains(p, regex=True) for s, p in zip(strong.skill, strong.pattern)})
    jobs["title_hit"] = title.str.contains(TITLE)
    jobs["skill_hits"] = [list(hits.columns[r]) for r in hits.to_numpy()]
    jobs["noise_flag"] = title.str.contains(NOISE)
    jobs["is_candidate"] = jobs.title_hit | (jobs.skill_hits.str.len() > 0)

    outside = jobs[~jobs.is_candidate]
    audit_ids = set(outside.sample(min(N_AUDIT, len(outside)), random_state=SEED).id)
    jobs["recall_audit"] = jobs.id.isin(audit_ids)

    keep = jobs[jobs.is_candidate | jobs.recall_audit]
    keep.drop(columns="text").to_parquet(DATA / "candidates.parquet", index=False)

    print(f"jobs {len(jobs)}  candidates {jobs.is_candidate.sum()} "
          f"(title {jobs.title_hit.sum()}, skill-only {(jobs.is_candidate & ~jobs.title_hit).sum()}, "
          f"noise-flagged {(jobs.is_candidate & jobs.noise_flag).sum()})  + recall audit {len(audit_ids)}")
    print(keep.groupby("source").size().to_dict())
    print(hits.sum().sort_values(ascending=False).head(15).to_dict())


if __name__ == "__main__":
    main()
