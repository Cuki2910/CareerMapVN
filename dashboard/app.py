"""CareerMapVN dashboard: data roles and data skills in Vietnamese job ads.

Run locally:  streamlit run dashboard/app.py
Data: dashboard/data_jobs.csv.gz + market_by_region.csv, written by `make export`.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import statsmodels.formula.api as smf
import streamlit as st

HERE = Path(__file__).parent
REPO = "https://github.com/Cuki2910/CareerMapVN"
MIN_N = 30          # smallest group shown in comparisons / kept as its own model level
SEED = 2010

ROLE = {
    "da_bi": "Data / BI analyst", "ds_ml_ai": "Data scientist / ML-AI engineer", "de": "Data engineer",
    "ba": "Business analyst", "dba_governance": "DBA / data governance", "quant_risk": "Quant / risk modelling",
    "software_it": "Software & IT", "marketing_digital": "Marketing & digital", "finance_accounting": "Finance & accounting",
    "operations_supply_chain": "Operations & supply chain", "sales_business": "Sales & business",
    "hr_admin": "HR & admin", "research_education": "Research & education",
    "engineering_manufacturing": "Engineering & manufacturing", "ai_applied": "Applied AI (content, AI trainer)",
    "other": "Other",
}
DOMAIN = {
    "banking_finance_insurance": "Banking, finance & insurance", "ecommerce_retail_fmcg": "E-commerce, retail & FMCG",
    "tech_software_telecom": "Tech, software & telecom", "manufacturing_industrial": "Manufacturing & industrial",
    "logistics_transport": "Logistics & transport", "real_estate_construction": "Real estate & construction",
    "healthcare_pharma": "Healthcare & pharma", "education": "Education", "media_marketing_agency": "Media & agencies",
    "consulting_outsourcing_services": "Consulting & outsourcing", "energy_agriculture": "Energy & agriculture",
    "hospitality_tourism": "Hospitality & tourism", "public_sector": "Public sector", "other": "Other",
    "unknown": "Unknown",
}
GROUP = {
    "grp_database": "Databases (SQL, NoSQL, data modelling)", "grp_programming": "Programming (Python, R, Scala)",
    "grp_bi_viz": "BI & dashboards (Power BI, Tableau, Looker)", "grp_spreadsheet": "Spreadsheets (Excel, VBA)",
    "grp_web_product_analytics": "Web/product analytics (GA4, A/B tests)",
    "grp_statistics": "Statistics (SPSS, regression, forecasting)", "grp_ml_ai": "ML / AI (scikit-learn, PyTorch, LLMs)",
    "grp_big_data": "Big data (Spark, Hadoop, Kafka)", "grp_data_engineering": "Data engineering (ETL, Airflow, DWH)",
    "grp_cloud": "Cloud (AWS, GCP, Azure)", "grp_quant_risk": "Quant & risk models",
}
TIER = {"A": "Data role", "B": "Data-skill job"}
TIER_COLOR = {"Data role": "#2a78d6", "Data-skill job": "#eb6834"}
SEQ = ["#f4f8fd", "#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"]
REGIONS = ["Hà Nội", "Hồ Chí Minh", "Miền Bắc", "Miền Trung", "Miền Nam", "Nước ngoài"]
SOURCES = {"vietjobs": "VietJobs (Jul–Oct 2025)", "topcv_crawl": "TopCV crawl (Nov 2026)"}
NOT_CONCRETE = {"sk_Excel", "sk_Google Sheets", "sk_Data analysis (generic)"}
GRID = "#e6e5e0"

st.set_page_config(page_title="CareerMapVN", page_icon="📊", layout="wide")


# ---------- data ----------
@st.cache_data
def load():
    df = pd.read_csv(HERE / "data_jobs.csv.gz", dtype={"id": str})
    skills = [c for c in df.columns if c.startswith("sk_")]
    df["region_list"] = df.regions.fillna("").map(lambda s: [r for r in s.split("; ") if r])
    df["tier_label"] = df.tier.map(TIER)
    df["role_label"] = df.role.map(ROLE).fillna(df.role)
    df["domain_label"] = df.domain.map(DOMAIN).fillna(df.domain)
    df["source_label"] = df.source.map(SOURCES)
    # VietJobs writes negotiable pay as "0.0 triệu"; show it as the portal does.
    df["salary"] = df.salary.where(df.salary_avg.notna() | ~df.salary.fillna("").str.match(r"^0(\.0)? triệu$"),
                                   "Thoả thuận")
    names = np.array([s[3:] for s in skills])
    df["skill_list"] = [", ".join(names[row == 1]) for row in df[skills].to_numpy()]
    market = pd.read_csv(HERE / "market_by_region.csv")
    return df, market, skills


def region3(regions):
    vn = [r for r in regions if r != "Nước ngoài"]
    if not vn:
        return None
    return "Hà Nội" if "Hà Nội" in vn else "Hồ Chí Minh" if "Hồ Chí Minh" in vn else "Other Vietnam"


def wilson(k, n, z=1.96):
    p = k / n
    centre = (p + z**2 / (2 * n)) / (1 + z**2 / n)
    half = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / (1 + z**2 / n)
    return centre - half, centre + half


def salary_rows(df):
    """Disclosed, plausible monthly salaries for jobs in Vietnam."""
    out = df[df.salary_avg.between(1, 200)].copy()
    out["region3"] = out.region_list.map(region3)
    return out[out.region3.notna()]


@st.cache_resource
def salary_model(_df):
    """Log-salary OLS on all disclosed salaries; returns fit, training rows, 5-fold CV MAE."""
    d = salary_rows(_df)
    d["exp"] = d.experience_years.clip(upper=10)
    d["role_m"] = d.role.where(d.role.map(d.role.value_counts()) >= MIN_N, "other")
    d["domain_m"] = d.domain.where(d.domain.map(d.domain.value_counts()) >= MIN_N, "other")
    d["y"] = np.log(d.salary_avg)
    groups = [g for g in GROUP if g in d.columns]
    formula = ("y ~ C(role_m) + C(region3) + exp + I(exp ** 2) + C(domain_m) + C(source) + " + " + ".join(groups))
    folds = np.random.default_rng(SEED).integers(0, 5, len(d))
    errors = []
    for k in range(5):
        part = smf.ols(formula, d[folds != k]).fit()
        test = d[folds == k]
        errors.append(np.abs(np.exp(part.predict(test)) - test.salary_avg))
    return smf.ols(formula, d).fit(), d, groups, float(pd.concat(errors).mean())


# ---------- chart helpers ----------
def style(fig, height=None):
    fig.update_layout(margin=dict(l=8, r=8, t=56, b=8), font=dict(size=13), legend_title_text="",
                      plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", hoverlabel=dict(font_size=13),
                      title_font_size=16, **({"height": height} if height else {}))
    fig.update_xaxes(gridcolor=GRID, zeroline=False)
    fig.update_yaxes(gridcolor=GRID, zeroline=False)
    return fig


def show(fig, table, key, height=None):
    st.plotly_chart(style(fig, height), width="stretch", key=key)
    with st.expander("Table view"):
        st.dataframe(table, hide_index=True, width="stretch")


def million(x):
    return f"{x:,.1f}M ₫"


# ---------- filters ----------
df, market, SKILLS = load()
st.title("CareerMapVN: data skills in Vietnamese job ads")
st.caption(f"{len(df):,} postings that are data roles or require concrete data skills, from "
           f"{df.source.eq('vietjobs').sum():,} VietJobs ads (2025) and {df.source.eq('topcv_crawl').sum():,} "
           f"TopCV ads (2026). Filters in the sidebar apply to every tab. [Code & data]({REPO})")

with st.sidebar:
    st.header("Filters")
    tiers = st.multiselect("Posting type", list(TIER.values()), default=list(TIER.values()),
                           help="Data role = the job is a data job. Data-skill job = another occupation whose "
                                "ad names a concrete data skill (SQL, Power BI, GA4, statistics, advanced Excel…).")
    role_opts = sorted(df[df.tier_label.isin(tiers)].role_label.unique())
    roles = st.multiselect("Role", role_opts, placeholder="All roles")
    regions = st.multiselect("Region", REGIONS, placeholder="All regions")
    domains = st.multiselect("Company industry", sorted(df.domain_label.unique()), placeholder="All industries")
    sources = st.multiselect("Source", list(SOURCES.values()), default=list(SOURCES.values()))
    exp_range = st.slider("Required experience (years)", 0, 10, (0, 10), help="10 means 10 or more.")
    must = st.multiselect("Must require all of these skills", sorted(s[3:] for s in SKILLS), placeholder="Any skills")

f = df[df.tier_label.isin(tiers) & df.source_label.isin(sources)
       & df.experience_years.fillna(0).clip(upper=10).between(*exp_range)]
if roles:
    f = f[f.role_label.isin(roles)]
if regions:
    f = f[f.region_list.map(lambda r: bool(set(r) & set(regions)))]
if domains:
    f = f[f.domain_label.isin(domains)]
for s in must:
    f = f[f[f"sk_{s}"] == 1]

if f.empty:
    st.warning("No postings match these filters. Remove a filter in the sidebar.")
    st.stop()

sal = salary_rows(f)
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Postings", f"{len(f):,}")
c2.metric("Data roles", f"{(f.tier == 'A').sum():,}")
c3.metric("Median advertised salary", million(sal.salary_avg.median()) if len(sal) else "–",
          help="Midpoint of the advertised range, million VND per month.")
c4.metric("Salary disclosed", f"{len(sal) / len(f):.0%}", help="Others say 'Thoả thuận' (negotiable).")
c5.metric("Median skills per ad", f"{f.skill_count.median():.0f}")

overview, skills_tab, salary_tab, estimator, explore, about = st.tabs(
    ["Overview", "Skills", "Salary", "Salary estimator", "Explore postings", "About the data"])

# ---------- overview ----------
with overview:
    left, right = st.columns(2)
    roles_t = f.groupby(["tier_label", "role_label"]).size().rename("postings").reset_index() \
        .sort_values("postings")
    fig = px.bar(roles_t, x="postings", y="role_label", color="tier_label", orientation="h", text="postings",
                 color_discrete_map=TIER_COLOR, title="Postings by role",
                 labels={"role_label": "", "postings": "Postings", "tier_label": "Type"})
    fig.update_traces(textposition="outside", cliponaxis=False)
    with left:
        show(fig, roles_t.rename(columns={"tier_label": "type", "role_label": "role"}), "roles",
             height=max(360, 28 * len(roles_t) + 120))

    by_reg = f.explode("region_list").groupby("region_list").size().rename("postings")
    denom = market[market.source.isin([k for k, v in SOURCES.items() if v in sources])] \
        .groupby("regions").n_postings.sum()
    # Abroad has too few ads overall for a meaningful share.
    reg_t = pd.DataFrame({"postings": by_reg, "all_ads": denom}).reindex(REGIONS[:-1]).dropna()
    reg_t["share"] = reg_t.postings / reg_t.all_ads
    reg_t = reg_t.reset_index(names="region")
    fig = px.bar(reg_t, x="region", y="share", text=reg_t.share.map("{:.1%}".format),
                 hover_data={"postings": True, "all_ads": True, "share": ":.2%"},
                 title="Share of all job ads in each region that match the filters",
                 labels={"share": "Share of all ads", "region": "", "all_ads": "All ads in region"})
    fig.update_traces(marker_color="#2a78d6", textposition="outside", cliponaxis=False)
    fig.update_yaxes(tickformat=".0%")
    with right:
        show(fig, reg_t, "regions")
        st.caption("A posting listing several regions counts in each. Denominator: every deduplicated ad "
                   "in that region from the selected sources. Ads abroad are excluded.")

    dom_t = f.groupby(["domain_label", "tier_label"]).size().rename("postings").reset_index()
    order = dom_t.groupby("domain_label").postings.sum().sort_values().index
    fig = px.bar(dom_t, x="postings", y="domain_label", color="tier_label", orientation="h",
                 category_orders={"domain_label": list(order)}, color_discrete_map=TIER_COLOR,
                 title="Postings by hiring company's industry", labels={"domain_label": "", "postings": "Postings"})
    show(fig, dom_t.rename(columns={"domain_label": "industry", "tier_label": "type"}), "domains",
         height=max(360, 26 * len(order) + 120))

# ---------- skills ----------
with skills_tab:
    concrete = st.toggle("Hide generic skills (plain Excel, Google Sheets, 'data analysis')", value=True)
    pool = [s for s in SKILLS if not (concrete and s in NOT_CONCRETE)]
    top_n = st.slider("Number of skills", 5, 30, 15)
    k = f[pool].sum().sort_values(ascending=False).head(top_n)
    lo, hi = wilson(k.values, len(f))
    sk_t = pd.DataFrame({"skill": [s[3:] for s in k.index], "postings": k.values, "share": k.values / len(f),
                         "ci_low": lo, "ci_high": hi}).iloc[::-1]
    fig = px.bar(sk_t, x="share", y="skill", orientation="h", text=sk_t.share.map("{:.0%}".format),
                 error_x=sk_t.ci_high - sk_t.share, error_x_minus=sk_t.share - sk_t.ci_low,
                 hover_data={"postings": True, "share": ":.1%"},
                 title=f"Most requested skills ({len(f):,} postings, 95% CI)", labels={"share": "Share of postings",
                                                                                         "skill": ""})
    fig.update_traces(marker_color="#2a78d6", textposition="inside", insidetextanchor="start",
                      textfont_color="#ffffff", error_x_color="#52514e", error_x_thickness=1)
    fig.update_xaxes(tickformat=".0%")
    show(fig, sk_t.iloc[::-1].round(3), "top_skills", height=28 * top_n + 140)

    st.subheader("Compare skill demand across groups")
    dims = {"Region": "region3", "Posting type": "tier_label", "Role": "role_label",
            "Company industry": "domain_label", "Source": "source_label"}
    dim = st.selectbox("Compare by", list(dims), index=0)
    g = f.copy()
    if dim == "Region":
        g = g.explode("region_list")
        g["region3"] = g.region_list.where(g.region_list.isin(["Hà Nội", "Hồ Chí Minh"]), "Other Vietnam")
        g = g[g.region_list.notna() & (g.region_list != "Nước ngoài")]
    col = dims[dim]
    sizes = g.groupby(col).size()
    keep = sizes[sizes >= MIN_N].index
    if len(keep) < 2:
        st.info(f"Need at least two groups with {MIN_N}+ postings to compare. Loosen the filters.")
    else:
        g = g[g[col].isin(keep)]
        top = g[pool].mean().sort_values(ascending=False).head(15).index
        heat = g.groupby(col)[list(top)].mean().T
        heat.index = [s[3:] for s in heat.index]
        heat.columns = [f"{c} (n={sizes[c]})" for c in heat.columns]
        fig = px.imshow(heat, text_auto=".0%", aspect="auto", color_continuous_scale=SEQ, zmin=0,
                        title=f"Share of postings requiring each skill, by {dim.lower()}",
                        labels=dict(color="Share", x="", y=""))
        fig.update_coloraxes(colorbar_tickformat=".0%")
        fig.update_xaxes(side="top", tickangle=0 if len(keep) <= 4 else -30)
        show(fig, heat.reset_index(names="skill").round(3), "heat", height=40 * len(top) + 160)
        st.caption(f"Groups with fewer than {MIN_N} postings are hidden. Shares are descriptive; "
                   "differences between small groups can be noise.")

# ---------- salary ----------
with salary_tab:
    if len(sal) < 10:
        st.info("Fewer than 10 postings with a disclosed salary match the filters.")
    else:
        st.caption(f"{len(sal):,} postings with a disclosed salary range in Vietnam. Salary = midpoint of the "
                   "advertised range, million VND per month. Ads saying 'Thoả thuận' are not included.")
        counts = sal.role_label.value_counts()
        rs = sal[sal.role_label.isin(counts[counts >= 10].index)]
        order = rs.groupby("role_label").salary_avg.median().sort_values(ascending=False).index
        fig = px.box(rs, x="salary_avg", y="role_label", color="tier_label", points=False,
                     category_orders={"role_label": list(order)}, color_discrete_map=TIER_COLOR,
                     title="Advertised salary by role (roles with 10+ disclosed salaries)",
                     labels={"salary_avg": "Million VND / month", "role_label": ""})
        fig.update_xaxes(range=[0, min(100, rs.salary_avg.quantile(0.98) * 1.1)])
        tbl = rs.groupby(["tier_label", "role_label"]).salary_avg.describe()[["count", "25%", "50%", "75%"]] \
            .round(1).reset_index()
        show(fig, tbl, "sal_role", height=34 * len(order) + 140)

        left, right = st.columns(2)
        sal["exp_bucket"] = pd.cut(sal.experience_years.clip(upper=10), [-0.1, 0.5, 1, 2, 3, 5, 10],
                                   labels=["<6 mo", "1 yr", "2 yrs", "3 yrs", "4–5 yrs", "6+ yrs"])
        ex = sal.groupby(["exp_bucket", "tier_label"], observed=True).salary_avg.agg(["median", "count"]) \
            .reset_index()
        ex = ex[ex["count"] >= 5]
        fig = px.line(ex, x="exp_bucket", y="median", color="tier_label", markers=True,
                      color_discrete_map=TIER_COLOR, hover_data={"count": True},
                      title="Median salary by required experience",
                      labels={"median": "Million VND / month", "exp_bucket": "Required experience"})
        fig.update_traces(line_width=2, marker_size=8)
        with left:
            show(fig, ex.round(1), "sal_exp")
        rg = sal.groupby("region3").salary_avg.agg(["median", "count"]).reset_index()
        fig = px.bar(rg, x="region3", y="median", text=rg["median"].map("{:.1f}".format),
                     hover_data={"count": True}, title="Median salary by region",
                     labels={"median": "Million VND / month", "region3": ""})
        fig.update_traces(marker_color="#2a78d6", textposition="outside", cliponaxis=False)
        with right:
            show(fig, rg.round(1), "sal_region")

        rows = []
        for s in (s for s in SKILLS if s not in NOT_CONCRETE):
            has = sal[s] == 1
            if has.sum() >= 15:
                rows.append({"skill": s[3:], "with skill": sal.salary_avg[has].median(),
                             "without": sal.salary_avg[~has].median(), "n with skill": int(has.sum())})
        if rows:
            prem = pd.DataFrame(rows)
            prem["difference"] = prem["with skill"] - prem["without"]
            prem = prem.sort_values("difference")
            fig = px.bar(prem, x="difference", y="skill", orientation="h",
                         hover_data={"with skill": ":.1f", "without": ":.1f", "n with skill": True},
                         title="Median salary of ads that require a skill minus ads that do not (raw, uncontrolled)",
                         labels={"difference": "Million VND / month", "skill": ""})
            fig.update_traces(marker_color=np.where(prem.difference >= 0, "#2a78d6", "#a3a29c"))
            show(fig, prem.round(1), "sal_skill", height=26 * len(prem) + 140)
            st.caption("Raw differences mix the effect of the skill with role, seniority and location. "
                       "The Salary estimator tab controls for those.")

# ---------- estimator ----------
with estimator:
    fit, train, groups, mae = salary_model(df)
    st.write("Estimate a typical advertised salary from role, location, experience, industry and skills. "
             f"Linear model on log salary, trained on {len(train):,} disclosed salaries "
             f"(R² {fit.rsquared:.2f}, 5-fold cross-validated mean error ±{mae:.1f}M ₫).")
    role_levels = sorted(train.role_m.unique(), key=lambda r: ROLE.get(r, r))
    dom_levels = sorted(train.domain_m.unique(), key=lambda d: DOMAIN.get(d, d))
    a, b = st.columns(2)
    with a:
        role_in = st.selectbox("Role", role_levels, format_func=lambda r: ROLE.get(r, r),
                               index=role_levels.index("da_bi") if "da_bi" in role_levels else 0)
        region_in = st.selectbox("Location", ["Hà Nội", "Hồ Chí Minh", "Other Vietnam"])
        exp_in = st.slider("Years of experience required", 0.0, 10.0, 2.0, 0.5)
    with b:
        dom_in = st.selectbox("Company industry", dom_levels, format_func=lambda d: DOMAIN.get(d, d),
                              index=dom_levels.index("unknown") if "unknown" in dom_levels else 0)
        skills_in = st.multiselect("Skill areas the job requires", groups, format_func=GROUP.get,
                                   default=[g for g in ("grp_database", "grp_bi_viz") if g in groups])
    row = pd.DataFrame([{"role_m": role_in, "region3": region_in, "exp": exp_in, "domain_m": dom_in,
                         "source": "topcv_crawl", **{g: int(g in skills_in) for g in groups}}])
    pred = fit.get_prediction(row).summary_frame(alpha=0.2).iloc[0]
    m1, m2 = st.columns(2)
    m1.metric("Typical advertised salary (2026 market)", million(np.exp(pred["mean"])))
    m2.metric("80% of similar ads fall between",
              f"{np.exp(pred.obs_ci_lower):,.0f} – {np.exp(pred.obs_ci_upper):,.0f}M ₫")

    ci = fit.conf_int()
    eff = pd.DataFrame({"skill area": [GROUP[g] for g in groups], "effect": np.expm1(fit.params[groups]).values,
                        "low": np.expm1(ci.loc[groups, 0]).values, "high": np.expm1(ci.loc[groups, 1]).values,
                        "p_value": fit.pvalues[groups].values}).sort_values("effect")
    eff["significant"] = np.where(eff.p_value < 0.05, "p < 0.05", "not significant")
    fig = px.scatter(eff, x="effect", y="skill area", color="significant",
                     error_x=eff.high - eff.effect, error_x_minus=eff.effect - eff.low,
                     color_discrete_map={"p < 0.05": "#2a78d6", "not significant": "#a3a29c"},
                     title="Salary difference linked to each skill area, holding role, location, experience "
                           "and industry fixed (95% CI)",
                     labels={"effect": "Change in advertised salary", "skill area": ""})
    fig.add_vline(x=0, line_color="#8a8984", line_width=1)
    fig.update_traces(marker_size=10)
    fig.update_xaxes(tickformat="+.0%")
    show(fig, eff.round(3), "effects", height=40 * len(groups) + 140)
    st.caption("Associations in advertised salaries, not causal effects. Ads that hide their salary are not "
               "in the model, and 2026 TopCV is used as the reference market.")

# ---------- explore ----------
with explore:
    q = st.text_input("Search job titles", placeholder="e.g. data analyst, kế toán, marketing")
    view = f[f.job_title.str.contains(q, case=False, regex=False, na=False)] if q else f
    cols = {"job_title": "Job title", "tier_label": "Type", "role_label": "Role", "regions": "Region",
            "domain_label": "Industry", "salary": "Salary (as advertised)", "salary_avg": "Salary midpoint (M ₫)",
            "experience_years": "Experience (yrs)", "skill_list": "Skills detected", "source_label": "Source"}
    out = view[list(cols)].rename(columns=cols)
    st.caption(f"{len(out):,} postings")
    st.dataframe(out, hide_index=True, width="stretch", height=520,
                 column_config={"Salary midpoint (M ₫)": st.column_config.NumberColumn(format="%.1f"),
                                "Experience (yrs)": st.column_config.NumberColumn(format="%.1f")})
    st.download_button("Download these postings (CSV)", out.to_csv(index=False).encode("utf-8-sig"),
                       "careermapvn_postings.csv", "text/csv")

# ---------- about ----------
with about:
    st.markdown(f"""
**What is counted.** Each Vietnamese job ad is classified as a **data role** (data/BI analyst, data scientist/ML-AI,
data engineer, business analyst, DBA/data governance, quant/risk) or a **data-skill job** (any other occupation whose
ad names a concrete data skill such as SQL, Power BI, Python, Google Analytics, statistics or advanced Excel).
Ads that only mention office software or "data entry" are excluded.

**Sources.** [VietJobs](https://huggingface.co/datasets/dinhieufam/VietJobs) (48,092 ads, Jul–Oct 2025, pinned
revision) and ads crawled from TopCV in Nov 2026. Reposted ads are merged, so each posting counts once.

**Method.** A broad keyword filter finds candidate ads. One LLM labels type, role and company industry, and two
people check a blind sample. Skills come from a 55-entry dictionary with Vietnamese synonyms.

**Limits.** Salaries are advertised ranges; about 30–50% of ads hide them. The keyword filter misses some
data-skill jobs, so their counts are a lower bound. The two sources differ by year and job portal.

Full provenance, data dictionary and code: [{REPO}]({REPO}) (see `data/README.md`).
""")
