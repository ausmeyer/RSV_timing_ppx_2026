#!/usr/bin/env python3
"""
Generate manuscript statistics summary for RSV timing 2025-26 extension.

Covers 3 NSSP seasons (2023-24, 2024-25, 2025-26) and up to 3 NHSN seasons,
with bootstrap 95% CIs and longitudinal consistency metrics.
"""

import pandas as pd
import numpy as np
from pathlib import Path


def generate_manuscript_stats(output_path: str = "results/manuscript_stats.txt"):
    root = Path(__file__).parent.parent
    tables = root / "results" / "tables"

    # -----------------------------------------------------------------------
    # Load tables (tolerate missing files gracefully)
    # -----------------------------------------------------------------------
    def _read(name: str) -> pd.DataFrame:
        path = tables / f"{name}.csv"
        if path.exists():
            return pd.read_csv(path)
        return pd.DataFrame()

    nssp_outside  = _read("nssp_outside_fraction_by_state")
    nhsn_outside  = _read("nhsn_outside_fraction_by_state")
    nssp_extended = _read("nssp_extended_windows_evaluation")
    nhsn_extended = _read("nhsn_extended_windows_evaluation")
    bootstrap_ci  = _read("bootstrap_ci_summary")
    longitudinal  = _read("longitudinal_consistency")
    nhsn_strata   = _read("nhsn_outside_fraction_all_strata")
    nssp_split = _read("nssp_out_of_window_early_late_split")
    infant_stress_window = _read("infant_ppx_stress_test_window_summary")
    infant_stress_ranking = _read("infant_ppx_stress_test_ranking")
    infant_hosp_averted_summary = _read("infant_ppx_hospitalizations_averted_summary")

    lines = []

    def add(text=""):
        lines.append(text)

    def first_nonmissing(series) -> float:
        values = series.dropna()
        return values.iloc[0] if len(values) else np.nan

    add("=" * 80)
    add("    MANUSCRIPT DATA SUMMARY: RSV Activity Outside October-March Window")
    add("    2025-26 Season Extension (3 NSSP Seasons, Up to 3 NHSN Seasons)")
    add("=" * 80)
    add()

    # -----------------------------------------------------------------------
    # Helper: summarise outside fraction for one season / data source
    # -----------------------------------------------------------------------
    def summarize_outside(df, season, label, datasource: str = ""):
        if df.empty:
            add(f"\n  {label}: [data not available]")
            return None, None, None, None, None

        data = df[df["season"] == season].dropna(subset=["outside_fraction"])
        if len(data) == 0:
            add(f"\n  {label}: [no data for season {season}]")
            return None, None, None, None, None

        median = data["outside_fraction"].median() * 100
        q25    = data["outside_fraction"].quantile(0.25) * 100
        q75    = data["outside_fraction"].quantile(0.75) * 100
        mn     = data["outside_fraction"].min() * 100
        mx     = data["outside_fraction"].max() * 100
        n      = len(data)

        add(f"\n  {label}:")
        add(f"    - Median: {median:.1f}%")
        add(f"    - IQR: {q25:.1f}% - {q75:.1f}%")
        add(f"    - Range: {mn:.1f}% - {mx:.1f}%")
        add(f"    - N = {n} jurisdictions")

        top5 = data.nlargest(5, "outside_fraction")[["jurisdiction", "outside_fraction"]]
        add("    - Top 5: " + ", ".join(
            f"{r.jurisdiction} ({r.outside_fraction*100:.1f}%)" for _, r in top5.iterrows()
        ))

        # Bootstrap CI if available - filter by datasource to avoid cross-source lookup
        if not bootstrap_ci.empty:
            ci_mask = (
                (bootstrap_ci.get("season", pd.Series(dtype=str)) == season) &
                (bootstrap_ci["metric"] == "median_outside_fraction")
            )
            if datasource and "datasource" in bootstrap_ci.columns:
                ci_mask &= bootstrap_ci["datasource"] == datasource
            ci_row = bootstrap_ci[ci_mask]
            if len(ci_row) > 0:
                lo = ci_row["ci_lower"].iloc[0] * 100
                hi = ci_row["ci_upper"].iloc[0] * 100
                add(f"    - Bootstrap 95% CI for median: [{lo:.1f}%, {hi:.1f}%]")

        return median, q25, q75, mn, mx

    # -----------------------------------------------------------------------
    # SECTION 1: Out-of-window fractions
    # -----------------------------------------------------------------------
    add("PARAGRAPH 1 - National and State-Level Findings")
    add("-" * 80)
    add()
    add("Out-of-Window Fractions:")

    nssp_seasons = sorted(nssp_outside["season"].unique()) if not nssp_outside.empty else []
    nhsn_seasons_avail = sorted(nhsn_outside["season"].unique()) if not nhsn_outside.empty else []

    for s in nssp_seasons:
        summarize_outside(nssp_outside, s, f"NSSP {s}", datasource="nssp")

    for s in nhsn_seasons_avail:
        summarize_outside(nhsn_outside, s, f"NHSN {s}", datasource="nhsn")

    add()

    # -----------------------------------------------------------------------
    # SECTION 1b: Out-of-window early vs late split (Figure 1 legend)
    # Mean per-state share of total seasonal NSSP RSV activity falling in the
    # early out-of-window period (Jul-Sep, before the October window start) and
    # the late out-of-window period (Apr-Jun, after the March window end).
    # Written both to the stats text and to a durable results table so the
    # Figure 1 legend percentages are reproducible from the pipeline.
    # -----------------------------------------------------------------------
    add("PARAGRAPH 1b - Out-of-Window Early vs Late Split, NSSP (Figure 1 legend)")
    add("-" * 80)
    add()
    if not nssp_split.empty:
        for _, row in nssp_split.sort_values("season").iterrows():
            add(
                f"  NSSP {row['season']}: mean early-season (Jul-Sep) = "
                f"{row['mean_early_out_of_window_pct']:.1f}% "
                f"of total seasonal RSV activity; mean late-season (Apr-Jun) = "
                f"{row['mean_late_out_of_window_pct']:.1f}% "
                f"(N = {int(row['n_states'])} jurisdictions)"
            )
    else:
        add("  [early/late split table not available; run the pipeline first]")

    add()

    # -----------------------------------------------------------------------
    # SECTION 2: Window coverage comparison
    # -----------------------------------------------------------------------
    add("PARAGRAPH 2 - Alternative Window Scenarios")
    add("-" * 80)
    add()

    def get_coverage(ext_df, season, window):
        if ext_df.empty:
            return np.nan
        data = ext_df[
            (ext_df["season"] == season) & (ext_df["window_name"] == window)
        ]
        return data["coverage"].median() * 100 if len(data) > 0 else np.nan

    def get_ci(ds, ag, metric):
        if bootstrap_ci.empty:
            return "", ""
        row = bootstrap_ci[
            (bootstrap_ci.get("datasource", pd.Series(dtype=str)) == ds) &
            (bootstrap_ci.get("metric", pd.Series(dtype=str)) == metric)
        ]
        if len(row) == 0:
            return "", ""
        lo = row["ci_lower"].iloc[0] * 100
        hi = row["ci_upper"].iloc[0] * 100
        return f"{lo:.1f}", f"{hi:.1f}"

    windows = [
        ("baseline_oct_mar", "Baseline (Oct-Mar)"),
        ("early_sep_mar",    "Early (Sep-Mar)"),
        ("late_oct_apr",     "Late (Oct-Apr)"),
    ]

    # Build header row
    all_cols = (
        [f"NSSP {s}" for s in nssp_seasons] +
        [f"NHSN {s}" for s in nhsn_seasons_avail]
    )
    header = f"  {'Window':<28}" + "".join(f" {c:>16}" for c in all_cols)
    add(header)
    add("  " + "-" * (28 + 17 * len(all_cols)))

    for wk, wlabel in windows:
        vals = []
        for s in nssp_seasons:
            v = get_coverage(nssp_extended, s, wk)
            vals.append(f"{'--' if np.isnan(v) else f'{v:.1f}%':>16}")
        for s in nhsn_seasons_avail:
            v = get_coverage(nhsn_extended, s, wk)
            vals.append(f"{'--' if np.isnan(v) else f'{v:.1f}%':>16}")
        add(f"  {wlabel:<28}" + "".join(vals))

    add()
    add("Coverage Improvement vs Baseline (percentage points):")

    for s in nssp_seasons:
        baseline = get_coverage(nssp_extended, s, "baseline_oct_mar")
        early    = get_coverage(nssp_extended, s, "early_sep_mar")
        late     = get_coverage(nssp_extended, s, "late_oct_apr")
        add(f"\n  NSSP {s}:")
        if not np.isnan(baseline):
            add(f"    - Early:    +{early - baseline:.1f} pp")
            add(f"    - Late:     +{late  - baseline:.1f} pp")

    for s in nhsn_seasons_avail:
        baseline = get_coverage(nhsn_extended, s, "baseline_oct_mar")
        early    = get_coverage(nhsn_extended, s, "early_sep_mar")
        late     = get_coverage(nhsn_extended, s, "late_oct_apr")
        add(f"\n  NHSN {s}:")
        if not np.isnan(baseline):
            add(f"    - Early:    +{early - baseline:.1f} pp")
            add(f"    - Late:     +{late  - baseline:.1f} pp")

    add()

    # -----------------------------------------------------------------------
    # SECTION 3: Age-stratified NHSN analysis
    # -----------------------------------------------------------------------
    add("PARAGRAPH 3 - NHSN Age-Stratified Analysis")
    add("-" * 80)
    add()

    if not nhsn_strata.empty and "age_group_label" in nhsn_strata.columns:
        for ag_label in nhsn_strata["age_group_label"].unique():
            ag_data = nhsn_strata[nhsn_strata["age_group_label"] == ag_label]
            add(f"  Age stratum: {ag_label}")
            for s in sorted(ag_data["season"].unique()):
                sdata = ag_data[ag_data["season"] == s].dropna(subset=["outside_fraction"])
                if len(sdata) == 0:
                    continue
                median = sdata["outside_fraction"].median() * 100
                q25    = sdata["outside_fraction"].quantile(0.25) * 100
                q75    = sdata["outside_fraction"].quantile(0.75) * 100
                add(f"    {s}: median={median:.1f}% (IQR {q25:.1f}-{q75:.1f}%)")
            add()
    else:
        add("  [Age-strata table not yet available - run pipeline first]")
        add()

    # -----------------------------------------------------------------------
    # SECTION 4: Longitudinal consistency
    # -----------------------------------------------------------------------
    add("PARAGRAPH 4 - Longitudinal Consistency Across Seasons")
    add("-" * 80)
    add()

    if not longitudinal.empty:
        for ds in longitudinal["datasource"].unique() if "datasource" in longitudinal.columns else ["all"]:
            if "datasource" in longitudinal.columns:
                sub = longitudinal[longitudinal["datasource"] == ds]
            else:
                sub = longitudinal

            add(f"  {ds.upper()}:")
            cv_median = sub["cv_outside_fraction"].median()
            add(f"    - Median state-level CV: {cv_median:.3f}")

            if "rank_corr_2324_vs_2425" in sub.columns:
                rho = first_nonmissing(sub["rank_corr_2324_vs_2425"])
                rho_label = "not available" if np.isnan(rho) else f"{rho:.3f}"
                add(f"    - Spearman rho (2023-24 vs 2024-25): {rho_label}")

            if "rank_corr_2425_vs_2526" in sub.columns:
                rho = first_nonmissing(sub["rank_corr_2425_vs_2526"])
                rho_label = "not available" if np.isnan(rho) else f"{rho:.3f}"
                add(f"    - Spearman rho (2024-25 vs 2025-26): {rho_label}")

            add()
    else:
        add("  [Longitudinal consistency table not yet available - run pipeline first]")
        add()

    # -----------------------------------------------------------------------
    # SECTION 5: Infant prophylaxis protection model
    # -----------------------------------------------------------------------
    add("PARAGRAPH 5 - Infant Prophylaxis Protection Model, Realistic Delivery Priors")
    add("-" * 80)
    add()

    def summarize_infant_ppx(datasource, scenario_id, label):
        df = infant_stress_window[
            (infant_stress_window.get("datasource") == datasource)
            & (infant_stress_window.get("scenario_id") == scenario_id)
        ] if not infant_stress_window.empty else pd.DataFrame()
        if df.empty:
            add(f"  {label}: [infant PPX model table not available]")
            return

        add(f"  {label}:")
        for wk, wlabel in windows:
            data = df[df["window_name"] == wk]
            if len(data) == 0:
                continue
            row = data.iloc[0]
            median_protection = row["median_population_activity_weighted_protection"] * 100
            q25 = row["q25_population_activity_weighted_protection"] * 100
            q75 = row["q75_population_activity_weighted_protection"] * 100
            first_receipt_share = row["median_share_receiving_ppx"] * 100
            add(
                f"    - {wlabel}: median activity-weighted protection={median_protection:.1f}% "
                f"(state IQR {q25:.1f}-{q75:.1f}%); "
                f"expected first-receipt share={first_receipt_share:.1f}%"
            )
        add()

    summarize_infant_ppx(
        "nssp", "reference_12mo",
        "NSSP curve-weighted model, realistic delivery priors, 12-month censor",
    )
    summarize_infant_ppx(
        "nhsn", "reference_12mo",
        "NHSN ages 0-4 curve-weighted model, realistic delivery priors, 12-month censor",
    )

    add("PARAGRAPH 6 - Infant Prophylaxis Protection Model, 8-Month Exposure Censor")
    add("-" * 80)
    add()
    summarize_infant_ppx(
        "nssp", "censor_8mo",
        "NSSP curve-weighted model, realistic delivery priors, 8-month censor",
    )
    summarize_infant_ppx(
        "nhsn", "censor_8mo",
        "NHSN ages 0-4 curve-weighted model, realistic delivery priors, 8-month censor",
    )

    add("PARAGRAPH 7 - Infant Prophylaxis Protection Model Robustness")
    add("-" * 80)
    add()
    if infant_stress_ranking.empty:
        add("  [stress-test ranking table not available]")
        add()
    else:
        for datasource, label in [("nssp", "NSSP"), ("nhsn", "NHSN ages 0-4")]:
            sub = infant_stress_ranking[infant_stress_ranking["datasource"] == datasource]
            sub = sub[~sub["scenario_id"].astype(str).str.startswith("efficacy_binary_")]
            if sub.empty:
                continue
            n = len(sub)
            early_gt_late = (sub["early_minus_late"] > 0).sum()
            early_gt_baseline = (sub["early_minus_baseline"] > 0).sum()
            year_round_gt_baseline = (sub["year_round_minus_baseline"] > 0).sum()
            add(f"  {label}:")
            add("    - Metric: population activity-weighted protection.")
            add(f"    - Early Sep-Mar exceeded late Oct-Apr in {early_gt_late}/{n} stress scenarios.")
            add(f"    - Early Sep-Mar exceeded Oct-Mar baseline in {early_gt_baseline}/{n} stress scenarios.")
            add(f"    - Year-round exceeded Oct-Mar baseline in {year_round_gt_baseline}/{n} stress scenarios.")
            add(
                "    - Median early-minus-baseline change across scenarios: "
                f"{sub['early_minus_baseline'].median() * 100:.2f} percentage points."
            )
            add(
                "    - Median early-minus-late change across scenarios: "
                f"{sub['early_minus_late'].median() * 100:.2f} percentage points."
            )
            add()

    add("PARAGRAPH 8 - Hospitalization Translation (50% uptake scenario)")
    add("-" * 80)
    add()
    hosp_summary = infant_hosp_averted_summary
    total_col = "total_hospitalizations_averted_vs_baseline"
    if hosp_summary.empty:
        add("  [hospitalization translation table not available]")
        add()
    else:
        comparison_order = {
            "early_sep_mar": 1,
            "late_oct_apr": 2,
            "year_round": 3,
        }
        hosp_summary = hosp_summary[hosp_summary["scenario_id"] == "uptake_50"].copy()
        hosp_summary["_comparison_order"] = (
            hosp_summary["comparison_window_name"].map(comparison_order).fillna(99)
        )
        for _, row in hosp_summary.sort_values(["_comparison_order", "season"]).iterrows():
            add(
                f"  {row['season']}: {row['comparison']} averted an estimated "
                f"{row[total_col]:.0f} RSV hospitalizations "
                f"nationally under the 50% uptake, otherwise-primary scenario "
                f"(median state={row['median_state_hospitalizations_averted']:.1f}; "
                f"IQR={row['q25_state_hospitalizations_averted']:.1f}-"
                f"{row['q75_state_hospitalizations_averted']:.1f})."
            )
        rate = hosp_summary[
            "baseline_hospitalization_risk_per_1000_infants"
        ].dropna()
        if len(rate):
            add(
                f"  Translation uses a baseline untreated infant RSV hospitalization risk of "
                f"{rate.iloc[0]:.2f} per 1,000 infant-seasons."
            )
        add()

    # -----------------------------------------------------------------------
    # SECTION 9: Suggested manuscript text
    # -----------------------------------------------------------------------
    add("=" * 80)
    add()
    add("                     SUGGESTED TEXT FOR MANUSCRIPT")
    add("=" * 80)
    add()

    # Build values for suggested text
    season_medians = {}
    for s in nssp_seasons:
        d = nssp_outside[nssp_outside["season"] == s].dropna(subset=["outside_fraction"]) \
            if not nssp_outside.empty else pd.DataFrame()
        season_medians[f"nssp_{s}"] = {
            "median": d["outside_fraction"].median() * 100 if len(d) else np.nan,
            "q25":    d["outside_fraction"].quantile(0.25) * 100 if len(d) else np.nan,
            "q75":    d["outside_fraction"].quantile(0.75) * 100 if len(d) else np.nan,
        }
    for s in nhsn_seasons_avail:
        d = nhsn_outside[nhsn_outside["season"] == s].dropna(subset=["outside_fraction"]) \
            if not nhsn_outside.empty else pd.DataFrame()
        season_medians[f"nhsn_{s}"] = {
            "median": d["outside_fraction"].median() * 100 if len(d) else np.nan,
            "q25":    d["outside_fraction"].quantile(0.25) * 100 if len(d) else np.nan,
            "q75":    d["outside_fraction"].quantile(0.75) * 100 if len(d) else np.nan,
        }

    add("RESULTS PARAGRAPH 1 (NSSP):")
    add("-" * 80)
    nssp_texts = []
    for s in nssp_seasons:
        d = season_medians.get(f"nssp_{s}", {})
        m, q25, q75 = d.get("median", np.nan), d.get("q25", np.nan), d.get("q75", np.nan)
        if not np.isnan(m):
            nssp_texts.append(
                f"{m:.1f}% (IQR: {q25:.1f}-{q75:.1f}%) in {s}"
            )
    if nssp_texts:
        add("Across states, the median fraction of RSV-associated ED visits (NSSP) occurring "
            "outside the October-March window was " + "; and ".join(nssp_texts) + ".")
    add()

    add("RESULTS PARAGRAPH 2 (NHSN):")
    add("-" * 80)
    nhsn_texts = []
    for s in nhsn_seasons_avail:
        d = season_medians.get(f"nhsn_{s}", {})
        m, q25, q75 = d.get("median", np.nan), d.get("q25", np.nan), d.get("q75", np.nan)
        if not np.isnan(m):
            nhsn_texts.append(
                f"{m:.1f}% (IQR: {q25:.1f}-{q75:.1f}%) in {s}"
            )
    if nhsn_texts:
        add("For laboratory-confirmed RSV-associated pediatric hospitalizations (NHSN, ages 0-4), "
            "the median out-of-window fraction was " + "; and ".join(nhsn_texts) + ".")
    add()

    add("DISCUSSION PARAGRAPH:")
    add("-" * 80)
    all_medians = [v["median"] for v in season_medians.values() if not np.isnan(v.get("median", np.nan))]
    all_maxes   = [
        (nssp_outside["outside_fraction"].max() * 100 if not nssp_outside.empty else np.nan),
        (nhsn_outside["outside_fraction"].max() * 100 if not nhsn_outside.empty else np.nan)
    ]
    all_maxes = [v for v in all_maxes if not np.isnan(v)]

    if all_medians and all_maxes:
        overall_median = np.median(all_medians)
        max_outside    = max(all_maxes)
        add(f"Across {len(nssp_seasons)} NSSP seasons and {len(nhsn_seasons_avail)} NHSN season(s), "
            f"approximately {overall_median:.0f}% of RSV activity nationally - "
            f"and up to {max_outside:.0f}% in some states - "
            f"occurred outside the current recommended October-March nirsevimab administration window. "
            f"This pattern was consistent across seasons, suggesting that year-over-year variability "
            f"does not eliminate out-of-window burden.")
    add()

    add("=" * 80)
    add()
    add("METHODOLOGICAL DETAILS")
    add("=" * 80)
    add()
    add("DATA SOURCES")
    add("-" * 80)
    add()
    add("NSSP:")
    add("  - Dataset: CDC NSSP Emergency Department Visit Trajectories")
    add("  - Socrata API dataset ID: rdmq-nq56")
    add("  - Field: percent_visits_rsv (% of ED visits with RSV-related code, all ages)")
    add(f"  - Seasons: {', '.join(nssp_seasons) if nssp_seasons else 'N/A'}")
    add("  - Geographic scope: all available states plus District of Columbia; aggregate rows and territories excluded")
    add()
    add("NHSN:")
    add("  - Dataset: CDC NHSN Weekly Hospital Respiratory Data (HRD)")
    add("  - Socrata API dataset ID: ua7e-t2fy")
    add("  - Primary field: numconfrsvnewadmped0to4 (lab-confirmed RSV admissions, ages 0-4)")
    add("  - Additional strata: totalconfrsvnewadmped (all pediatric), totalconfrsvnewadm (all ages)")
    add(f"  - Seasons included: {', '.join(nhsn_seasons_avail) if nhsn_seasons_avail else 'determined at runtime'}")
    add("  - Completeness criterion: >=45 states reporting for 2023-24, >=40 for later seasons")
    add()
    add("BOOTSTRAP CONFIDENCE INTERVALS")
    add("-" * 80)
    add("  - Nonparametric bootstrap, 10,000 replicates")
    add("  - Resample states with replacement (n = number of states per season)")
    add("  - Point estimate: median outside fraction")
    add("  - 95% CI: 2.5th and 97.5th percentiles of bootstrap distribution")
    add()
    add("LONGITUDINAL CONSISTENCY")
    add("-" * 80)
    add("  - State-level coefficient of variation (CV) = SD / mean across seasons")
    add("  - Spearman rank correlation of state outside-fractions between season pairs")
    add("  - Assesses whether states that are high in one season remain high in the next")
    add()
    add("INFANT PROPHYLAXIS PROTECTION MODEL")
    add("-" * 80)
    add("  - Daily birth cohorts with births uniformly distributed across calendar days")
    add(
        "  - The cohort grid uses a full 12-month at-risk lookback before the "
        "earliest scenario window and extends through season end, including "
        "infants too old for dosing who can still accrue exposure before age 12 months"
    )
    add("  - In each annual window, uptake is the probability of receipt among previously untreated infants with an eligible opportunity; recipients are dosed at the first such visit")
    add("  - Untreated infants may receive prophylaxis in a later annual window only if still younger than 8 months; prior recipients are not redosed")
    add("  - Reference assumptions: 18.5% seasonal nirsevimab uptake, 38.1% newborn/first-week dosing among recipients, eligibility for receipt before age 8 months, and follow-up censored at age 12 months")
    add("  - Protection assumptions: 6-day rise to peak concentration and smoothed time-varying effectiveness through day 210")
    add("  - Primary metrics: cohort-weighted median population-level fractional protection and population activity-weighted protection")
    add("  - Main hospitalization translation display uses the 50% uptake scenario")
    add("  - State-season RSV exposure weights come from the observed NSSP or NHSN epidemic curve")
    add()
    add("=" * 80)

    # -----------------------------------------------------------------------
    # Write output
    # -----------------------------------------------------------------------
    output_file = root / output_path
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text("\n".join(lines))
    return output_file


if __name__ == "__main__":
    generate_manuscript_stats()
