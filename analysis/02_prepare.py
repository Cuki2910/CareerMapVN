"""Step 2: merge VietJobs + crawled TopCV jobs into one clean posting-level table.

Output data/analysis/jobs.parquet: one row per unique (job_title, description),
with parsed salary (million VND/month), experience years, provinces and regions.
"""
import hashlib
import re
import sys
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/analysis"
# Crawl rows included in the analysis. The crawler keeps appending to its CSV, so the
# analysis is pinned to this committed id list; `make snapshot` refreshes it deliberately.
SNAPSHOT = OUT / "crawl_snapshot_ids.txt"

# Old/new Vietnamese tone placement ("hoà" vs "hòa") must compare equal.
TONE_PAIRS = {"oà": "òa", "oá": "óa", "oả": "ỏa", "oã": "õa", "oạ": "ọa", "oè": "òe", "oé": "óe",
              "oẻ": "ỏe", "oẽ": "õe", "oẹ": "ọe", "uỳ": "ùy", "uý": "úy", "uỷ": "ủy", "uỹ": "ũy", "uỵ": "ụy"}

NORTH = {"Hải Phòng", "Quảng Ninh", "Bắc Ninh", "Hưng Yên", "Ninh Bình", "Phú Thọ", "Thái Nguyên", "Tuyên Quang",
         "Lào Cai", "Cao Bằng", "Lạng Sơn", "Điện Biên", "Lai Châu", "Sơn La"}
CENTRAL = {"Thanh Hóa", "Nghệ An", "Hà Tĩnh", "Quảng Trị", "Huế", "Đà Nẵng", "Quảng Ngãi", "Gia Lai", "Đắk Lắk",
           "Khánh Hòa", "Lâm Đồng"}
SOUTH = {"Đồng Nai", "Tây Ninh", "Cần Thơ", "Vĩnh Long", "Đồng Tháp", "An Giang", "Cà Mau"}


def clean(s):
    if not isinstance(s, str):
        return np.nan
    s = re.sub(r"\s+", " ", unicodedata.normalize("NFC", s)).strip()
    return s or np.nan


def fold(s):
    s = unicodedata.normalize("NFC", s.lower())
    for a, b in TONE_PAIRS.items():
        s = s.replace(a, b)
    return s


ALIASES = {fold(a): p for a, p in pd.read_csv(ROOT / "analysis/locations.csv").itertuples(index=False)}
LONG_ALIASES = sorted((a for a in ALIASES if len(a) >= 5), key=len, reverse=True)


def province(token):
    t = fold(token).strip(" []'\".-")
    if m := re.search(r"thuộc (.+?) cũ", t):
        t = m.group(1)
    t = re.sub(r"^(?:tp\.?|thành phố|tỉnh|phường|xã|huyện|thị xã|thị trấn|quận(?= \D))\s+", "", t)
    if t in ALIASES:
        return ALIASES[t]
    # ponytail: substring fallback on aliases >= 5 chars; unknown places stay unmapped.
    return next((ALIASES[a] for a in LONG_ALIASES if re.search(rf"(?<!\w){re.escape(a)}(?!\w)", t)), None)


def region(p):
    if p in ("Hà Nội", "Hồ Chí Minh", "Nước ngoài"):
        return p
    return "Miền Bắc" if p in NORTH else "Miền Trung" if p in CENTRAL else "Miền Nam" if p in SOUTH else None


def locations(text):
    provs = set()
    for part in re.split(r"[;\n]", str(text)):
        # "Tỉnh: street address" (TopCV) -> the province is before the colon.
        toks = [part.split(":")[0]] if ":" in part else part.split(",")
        provs |= {p for tok in toks if (p := province(tok))}
    provs = sorted(provs)
    return provs, sorted({region(p) for p in provs})


def parse_vj_salary(s):
    """VietJobs: 'A - B triệu' or 'A triệu'; '0.0 triệu' means negotiable."""
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", str(s))]
    if not nums or max(nums) == 0:
        return np.nan, np.nan
    return (nums[0], nums[-1])


def parse_experience(s):
    s = str(s).lower()
    if "không yêu cầu" in s:
        return 0.0
    m = re.search(r"(\d+(?:\.\d+)?)\s*(năm|tháng)", s)
    return (float(m.group(1)) / (12 if m.group(2) == "tháng" else 1)) if m else np.nan


def load():
    text_cols = ["job_title", "location", "qualifications", "technical_skills", "experience_required", "salary",
                 "contract_type", "description", "requirements_text", "category"]
    vj = pd.read_csv(ROOT / "data/raw/VietJobs.csv", dtype=str, keep_default_na=False)
    vj["source"], vj["period"] = "vietjobs", "2025-07/2025-10"
    vj[["salary_min", "salary_max"]] = vj.salary.map(parse_vj_salary).tolist()

    cr = pd.read_csv(ROOT / "data/CareerMapVN_jobs.csv", dtype=str, keep_default_na=False)
    cr["source"], cr["period"] = "topcv_crawl", "2026-11"
    for c in ("salary_min", "salary_max"):
        cr[c] = pd.to_numeric(cr[c].replace("", np.nan))

    df = pd.concat([vj, cr], ignore_index=True)
    for c in text_cols:
        df[c] = df[c].map(clean)
    for c in ("salary_min", "salary_max"):
        df[c] = df[c].where(df[c] < 1e4, df[c] / 1e6).replace(0, np.nan)  # raw VND -> million; 0 = unknown
    df["salary_avg"] = (df.salary_min + df.salary_max) / 2  # NaN unless both bounds known
    df["experience_years"] = df.experience_required.map(parse_experience)
    locs = df.location.map(locations)
    df["provinces"], df["regions"] = locs.str[0], locs.str[1]
    return df


def main():
    df = load()
    n_raw = len(df)
    key = ["job_title", "description"]
    df = df.dropna(subset=key)
    # Reposts of the same ad: keep one row, union its locations, median its salaries.
    agg = {c: "first" for c in df.columns if c not in key}
    agg.update({c: "median" for c in ("salary_min", "salary_max", "salary_avg")})
    agg.update(provinces=lambda s: sorted(set().union(*s)), regions=lambda s: sorted(set().union(*s)),
               location="first")
    out = df.groupby(key, sort=False, as_index=False).agg(agg)
    out["n_reposts"] = df.groupby(key, sort=False).size().values
    out.insert(0, "id", [hashlib.sha1(f"{t}\x1f{d}".encode()).hexdigest()[:12]
                         for t, d in zip(out.job_title, out.description)])
    assert out.id.is_unique
    crawl = out.source == "topcv_crawl"
    if SNAPSHOT.exists() and "--refresh-snapshot" not in sys.argv:
        pinned = set(SNAPSHOT.read_text().split())
        missing = pinned - set(out.id[crawl])
        if missing:
            sys.exit(f"{len(missing)} pinned crawl rows are gone from data/CareerMapVN_jobs.csv; "
                     "restore them or run `make snapshot`")
        print(f"crawl snapshot: using {len(pinned)} pinned rows, ignoring {crawl.sum() - len(pinned)} newer")
        out = out[~crawl | out.id.isin(pinned)].reset_index(drop=True)
    else:
        OUT.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text("\n".join(sorted(out.id[crawl])) + "\n")
        print(f"crawl snapshot: pinned {crawl.sum()} rows to {SNAPSHOT.name}")
    out["text"] = out[["job_title", "description", "requirements_text", "technical_skills"]] \
        .fillna("").agg(" \n ".join, axis=1).str.lower()

    OUT.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUT / "jobs.parquet", index=False)
    unmapped = out[out.provinces.str.len() == 0].location.value_counts()
    print(f"raw {n_raw} -> unique {len(out)}  by source: {out.source.value_counts().to_dict()}")
    print(f"salary known {out.salary_avg.notna().mean():.1%}  experience known {out.experience_years.notna().mean():.1%}")
    print(f"no province: {len(unmapped)} distinct / {unmapped.sum()} rows; top: {unmapped.head(8).to_dict()}")


if __name__ == "__main__":
    main()
