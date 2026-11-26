"""Step 8 (RQ4): what drives advertised salary for data-related postings?

Sample: tier A+B postings with both salary bounds, Vietnam only. Target: log(midpoint,
million VND/month). Models compared by 5-fold CV MAE (in million VND, back-transformed):
  baseline  - experience + region + source (the "no NLP" model)
  ols       - baseline + tier/role + domain + skill groups + skill_count
  gbm       - HistGradientBoosting on the same features
The OLS fit on all rows (HC3 robust SE) is reported for interpretation; permutation
importance is computed for the GBM. ~30% of postings hide salary ("Thoả thuận"):
results describe advertised salaries only.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import KFold, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/analysis"
OUT = DATA / "results"
SEED = 2010
MIN_N = 30


def prepare():
    df = pd.read_parquet(DATA / "data_jobs.parquet")
    df = df[df.salary_avg.notna() & df.experience_years.notna()].copy()
    df["region"] = df.regions.map(lambda r: "Hà Nội" if "Hà Nội" in r else "Hồ Chí Minh" if "Hồ Chí Minh" in r
                                  else "Nước ngoài" if list(r) == ["Nước ngoài"] else "Other Vietnam")
    df = df[(df.region != "Nước ngoài") & df.salary_avg.between(1, 200)]  # drop stipends/commission outliers
    df["log_salary"] = np.log(df.salary_avg)
    df["exp"] = df.experience_years.clip(upper=10)
    df["role_t"] = df.tier + ":" + df.role
    for c in ("role_t", "domain"):
        df[c] = df[c].where(df[c].map(df[c].value_counts()) >= MIN_N, "other")
    return df


def main():
    df = prepare()
    groups = [c for c in df.columns if c.startswith("grp_")]
    base_cat, full_cat = ["region", "source"], ["region", "source", "role_t", "domain"]
    num_base, num_full = ["exp"], ["exp", "skill_count"] + groups
    cv = KFold(5, shuffle=True, random_state=SEED)
    y = df.log_salary.values

    def model(cat, num, est):
        ct = ColumnTransformer([("cat", OneHotEncoder(handle_unknown="ignore", drop="first"), cat)],
                               remainder="passthrough")
        return make_pipeline(ct, est), cat + num

    results, lines = {}, []
    for name, (pipe, cols) in {
        "baseline OLS": model(base_cat, num_base, LinearRegression()),
        "full OLS": model(full_cat, num_full, LinearRegression()),
        "full GBM": model(full_cat, num_full, HistGradientBoostingRegressor(max_depth=3, learning_rate=0.05,
                                                                           max_iter=300, random_state=SEED)),
    }.items():
        pred = cross_val_predict(pipe, df[cols], y, cv=cv)
        mae = np.mean(np.abs(np.exp(pred) - df.salary_avg))
        r2 = 1 - np.sum((y - pred) ** 2) / np.sum((y - y.mean()) ** 2)
        results[name] = (pipe, cols, mae, r2)
        lines.append(f"| {name} | {mae:.2f} | {r2:.3f} |")

    formula = ("log_salary ~ exp + C(region, Treatment('Hà Nội')) + C(source) + C(role_t) + C(domain) + skill_count + "
               + " + ".join(groups))
    ols = smf.ols(formula, df).fit(cov_type="HC3")

    pipe, cols, *_ = results["full GBM"]
    pipe.fit(df[cols], y)
    imp = permutation_importance(pipe, df[cols], y, n_repeats=10, random_state=SEED)
    importance = pd.Series(imp.importances_mean, cols).sort_values(ascending=False)

    coefs = pd.DataFrame({"coef": ols.params, "ci_low": ols.conf_int()[0], "ci_high": ols.conf_int()[1],
                          "p": ols.pvalues})
    coefs["pct_effect"] = np.expm1(coefs.coef) * 100
    coefs.to_csv(OUT / "salary_ols_coefs.csv")
    importance.to_csv(OUT / "salary_gbm_importance.csv", header=["importance"])

    report = ["# RQ4 - advertised salary model", "",
              f"n = {len(df)} data-related postings with a disclosed salary range (Vietnam, 1-200 million VND/month); "
              f"tier {df.tier.value_counts().to_dict()}, source {df.source.value_counts().to_dict()}.",
              "Postings with 'Thoả thuận' are excluded, so results describe *advertised* salaries only.", "",
              "| model (5-fold CV) | MAE (million VND) | R² (log scale) |", "|---|---|---|", *lines, "",
              f"OLS on all rows: R² {ols.rsquared:.3f}, adj. R² {ols.rsquared_adj:.3f} (HC3 robust SE).", "",
              "Significant OLS terms (p < 0.05), effect = % change in salary:", "", "```",
              coefs[(coefs.p < 0.05) & (coefs.index != "Intercept")]
              .sort_values("pct_effect")[["pct_effect", "p"]].round(3).to_string(), "```", "",
              "GBM permutation importance (drop in R² when a feature is shuffled):", "", "```",
              importance.round(4).to_string(), "```"]
    (OUT / "salary_report.md").write_text("\n".join(report), encoding="utf-8")
    print("\n".join(report))


if __name__ == "__main__":
    main()
