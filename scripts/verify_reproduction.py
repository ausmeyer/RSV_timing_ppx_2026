#!/usr/bin/env python3
"""Verify the small set of outputs used by the accepted manuscript."""

from pathlib import Path

import pandas as pd
import yaml


ROOT = Path(__file__).resolve().parents[1]
TABLES = ROOT / "results" / "tables"
FIGURES = ROOT / "results" / "figures"

EXPECTED_TABLES = {
    "bootstrap_ci_summary.csv",
    "infant_ppx_hospitalizations_averted.csv",
    "infant_ppx_hospitalizations_averted_summary.csv",
    "infant_ppx_stress_test_ranking.csv",
    "infant_ppx_stress_test_window_summary.csv",
    "longitudinal_consistency.csv",
    "nhsn_extended_windows_evaluation.csv",
    "nhsn_outside_fraction_all_strata.csv",
    "nhsn_outside_fraction_by_state.csv",
    "nssp_extended_windows_evaluation.csv",
    "nssp_out_of_window_early_late_split.csv",
    "nssp_outside_fraction_by_state.csv",
}

FIGURE_STUBS = {
    "fig1_choropleth_grid",
    "fig2_ridgeline_nssp_seasons",
    "fig3_infant_ppx_early_start_advantage_forest",
    "fig4_infant_ppx_hospitalizations_averted_by_window",
    "fig5_infant_ppx_hospitalizations_averted_primary_vs_full_uptake",
    "nhsn_fig_supp_timeseries",
    "nssp_fig_supp_timeseries",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    observed_tables = {path.name for path in TABLES.glob("*.csv")}
    require(observed_tables == EXPECTED_TABLES, (
        f"Output-table contract mismatch. Missing={sorted(EXPECTED_TABLES - observed_tables)}; "
        f"unexpected={sorted(observed_tables - EXPECTED_TABLES)}"
    ))

    observed_figures = {path.name for path in FIGURES.glob("*") if path.is_file()}
    expected_figures = {
        f"{stub}.{extension}"
        for stub in FIGURE_STUBS
        for extension in ("png", "pdf")
    }
    require(observed_figures == expected_figures, (
        f"Figure contract mismatch. Missing={sorted(expected_figures - observed_figures)}; "
        f"unexpected={sorted(observed_figures - expected_figures)}"
    ))

    config = yaml.safe_load((ROOT / "config.yaml").read_text())
    model = config["infant_ppx_model"]
    require(model["uptake"] == 0.185, "Primary uptake must be encoded as 18.5%.")
    require(model["efficacy_profile"] == "piecewise_linear", "Primary efficacy profile mismatch.")
    require(model["protection_duration_days"] == 210, "Primary protection duration mismatch.")

    nssp = pd.read_csv(TABLES / "nssp_outside_fraction_by_state.csv")
    nhsn = pd.read_csv(TABLES / "nhsn_outside_fraction_by_state.csv")
    nssp_2526 = nssp[nssp["season"] == "2025-2026"]
    nhsn_2526 = nhsn[nhsn["season"] == "2025-2026"]
    require(nssp_2526["jurisdiction"].nunique() == 51, "NSSP 2025-26 must contain 51 jurisdictions.")
    require(nhsn_2526["jurisdiction"].nunique() == 51, "NHSN 2025-26 must contain 51 jurisdictions.")
    require(0.14 < nssp_2526["outside_fraction"].median() < 0.19, "NSSP headline is out of range.")
    require(0.11 < nhsn_2526["outside_fraction"].median() < 0.17, "NHSN headline is out of range.")

    stress = pd.read_csv(TABLES / "infant_ppx_stress_test_window_summary.csv")
    prohibited = {"bootstrap_pr_delta_gt_zero", "delta_ci_lower", "delta_ci_upper"}
    require(not prohibited.intersection(stress.columns), "Stress table contains inferential columns.")
    primary = stress[stress["scenario_id"] == "reference_12mo"]
    require(set(primary["uptake"]) == {0.185}, "Primary rows do not use 18.5% uptake.")
    year_round = primary[primary["window_name"] == "year_round"]
    require(
        (year_round["median_share_receiving_ppx"] == year_round["uptake"]).all(),
        "Year-round receipt must use the steady-state value.",
    )

    hospitalizations = pd.read_csv(TABLES / "infant_ppx_hospitalizations_averted.csv")
    require(
        "comparison_population_activity_weighted_protection" in hospitalizations.columns,
        "Hospitalization table must use comparison-neutral column names.",
    )
    require(
        not any("early_vs_baseline" in column for column in hospitalizations.columns),
        "Hospitalization table contains stale early-window column names.",
    )
    require((ROOT / "results" / "manuscript_stats.txt").is_file(), "Missing manuscript statistics summary.")
    print("Reproduction verified.")


if __name__ == "__main__":
    main()
