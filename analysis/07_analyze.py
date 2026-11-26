"""Step 7: descriptive answers to RQ1-RQ3 (who hires, which skills, where, in which industry).

Writes data/analysis/results/: tables (CSV) + figures (PNG) + summary.md.
Scopes: "A" (data roles) and "A+B" (all data-related postings).
Region analysis counts a multi-region posting once per region; regions are
collapsed to Hà Nội / Hồ Chí Minh / Other Vietnam because other cells are small.
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap
from scipy.stats import chi2_contingency

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/analysis"
OUT = DATA / "results"
MIN_N = 30          # cells below this are folded into "other" / not reported
TOP_SKILLS = 20
NOT_CONCRETE = {"sk_Excel", "sk_Google Sheets", "sk_Data analysis (generic)"}  # kept in matrix, not ranked
Z = 1.96

BLUE = LinearSegmentedColormap.from_list("seq", ["#fcfcfb", "#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"])
INK, MUTED = "#0b0b0b", "#52514e"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": MUTED, "axes.labelcolor": INK,
                     "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False, "axes.spines.right": False})


def wilson(k, n):
    """95% Wilson interval for a proportion k/n."""
    p = k / n
    centre = (p + Z**2 / (2 * n)) / (1 + Z**2 / n)
    half = Z * np.sqrt(p * (1 - p) / n + Z**2 / (4 * n**2)) / (1 + Z**2 / n)
    return centre - half, centre + half


def skill_by_group(df, group, skills):
    """Share of postings requiring each skill per group, Wilson CI, chi-square test across groups."""
    rows = []
    sizes = df.groupby(group).size()
    for s in skills:
        k = df.groupby(group)[s].sum()
        table = np.array([k.values, (sizes - k).values])
        p = chi2_contingency(table)[1] if (table.sum(axis=1) > 0).all() else np.nan
        for g in sizes.index:
            lo, hi = wilson(k[g], sizes[g])
            rows.append({"skill": s[3:], group: g, "n": sizes[g], "count": k[g], "share": k[g] / sizes[g],
                         "ci_low": lo, "ci_high": hi, "chi2_p": p})
    out = pd.DataFrame(rows)
    # Benjamini-Hochberg over skills so many tests do not inflate false positives.
    p = out.drop_duplicates("skill").set_index("skill").chi2_p.dropna().sort_values()
    q = (p * len(p) / np.arange(1, len(p) + 1))[::-1].cummin()[::-1].clip(upper=1)
    return out.assign(chi2_q=out.skill.map(q))


def heatmap(table, title, path, note):
    fig, ax = plt.subplots(figsize=(max(6.5, 2.2 + 1.1 * table.shape[1]), 0.32 * table.shape[0] + 1.8))
    ax.imshow(table.values, cmap=BLUE, vmin=0, vmax=max(0.6, table.values.max()), aspect="auto")
    ax.set_xticks(range(table.shape[1]), table.columns, rotation=30, ha="right")
    ax.set_yticks(range(table.shape[0]), table.index)
    for (i, j), v in np.ndenumerate(table.values):
        ax.text(j, i, f"{v:.0%}", ha="center", va="center", fontsize=7.5, color="#fcfcfb" if v > 0.35 else INK)
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    fig.suptitle(title, x=0.01, ha="left", color=INK, fontsize=10)
    fig.text(0.01, 0.005, note, color=MUTED, fontsize=7)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(path, dpi=200)
    plt.close(fig)


def bars(series, title, path):
    s = series.sort_values()
    fig, ax = plt.subplots(figsize=(6, 0.3 * len(s) + 1))
    ax.barh(s.index, s.values, color="#2a78d6", height=0.6)
    for y, v in enumerate(s.values):
        ax.text(v, y, f" {v}", va="center", color=INK, fontsize=8)
    ax.set_title(title, loc="left", color=INK, fontsize=10)
    ax.xaxis.grid(True, color="#e6e5e0", linewidth=0.6)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    df = pd.read_parquet(DATA / "data_jobs.parquet")
    sk = [c for c in df.columns if c.startswith("sk_") and c not in NOT_CONCRETE]
    md = ["# CareerMapVN - descriptive results", "",
          f"Data-related postings: {len(df)} (tier A {int((df.tier == 'A').sum())}, tier B {int((df.tier == 'B').sum())}); "
          f"sources {df.source.value_counts().to_dict()}", ""]

    # RQ1: who is hiring - roles by tier, source and region.
    roles = df.groupby(["tier", "role"]).size().rename("n").reset_index()
    roles.to_csv(OUT / "roles.csv", index=False)
    bars(df[df.tier == "A"].role.value_counts(), "Tier A postings by data role", OUT / "roles_tier_a.png")
    bars(df[df.tier == "B"].role.value_counts(), "Tier B postings by main occupation", OUT / "roles_tier_b.png")
    md += ["## RQ1 roles", "", "```", df.groupby(["tier", "role"]).size().to_string(), "```", ""]

    reg = df.explode("regions").dropna(subset=["regions"])
    reg = reg[reg.regions != "Nước ngoài"]
    reg["region3"] = reg.regions.where(reg.regions.isin(["Hà Nội", "Hồ Chí Minh"]), "Other Vietnam")
    md += ["Postings by region (multi-region postings counted once per region):", "", "```",
           pd.crosstab(reg.region3, reg.tier, margins=True).to_string(), "```", ""]

    for scope, cond in [("A", df.tier == "A"), ("A+B", df.tier.isin(["A", "B"]))]:
        part = df[cond]
        top = part[sk].mean().sort_values(ascending=False).head(TOP_SKILLS).index.tolist()
        tag = scope.replace("+", "")

        # RQ2: skills by region.
        r = reg[reg.id.isin(part.id)]
        by_region = skill_by_group(r, "region3", top)
        by_region.to_csv(OUT / f"skills_by_region_{tag}.csv", index=False)
        table = by_region.pivot(index="skill", columns="region3", values="share").loc[[s[3:] for s in top]]
        n = r.groupby("region3").size()
        table.columns = [f"{c}\n(n={n[c]})" for c in table.columns]
        heatmap(table, f"Tier {scope}: share of postings\nrequiring each skill, by region",
                OUT / f"skills_by_region_{tag}.png", "95% Wilson CIs + BH-adjusted\nchi-square tests in the CSV.")
        sig = by_region.drop_duplicates("skill").query("chi2_q < 0.05").skill.tolist()
        md += [f"## RQ2 skills by region - tier {scope}", "", f"Region sizes: {n.to_dict()}",
               f"Skills whose share differs by region (BH q < 0.05): {sig or 'none'}", ""]

        # RQ3: skills by hiring-company domain (domains with < MIN_N postings folded into 'other').
        d = part.assign(domain=part.domain.where(part.domain.map(part.domain.value_counts()) >= MIN_N, "other"))
        d = d[d.domain != "unknown"]
        by_domain = skill_by_group(d, "domain", top)
        by_domain.to_csv(OUT / f"skills_by_domain_{tag}.csv", index=False)
        table = by_domain.pivot(index="skill", columns="domain", values="share").loc[[s[3:] for s in top]]
        n = d.groupby("domain").size()
        table.columns = [f"{c}\n(n={n[c]})" for c in table.columns]
        heatmap(table, f"Tier {scope}: share of postings\nrequiring each skill, by company domain",
                OUT / f"skills_by_domain_{tag}.png",
                f"Domains < {MIN_N} postings -> 'other';\n'unknown' excluded.")
        sig = by_domain.drop_duplicates("skill").query("chi2_q < 0.05").skill.tolist()
        md += [f"## RQ3 skills by domain - tier {scope}", "", f"Domain sizes: {n.to_dict()}",
               f"Skills whose share differs by domain (BH q < 0.05): {sig or 'none'}", ""]

    (OUT / "summary.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
