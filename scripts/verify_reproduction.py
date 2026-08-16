#!/usr/bin/env python3
"""Run automated consistency checks for the current pipeline outputs."""

import argparse
import re
from pathlib import Path
import sys
from zipfile import ZipFile

import pandas as pd
import yaml


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data_contract import verify_frozen_manifest


TABLES = ROOT / "results" / "tables"
FIGURES = ROOT / "results" / "figures"
FINAL_FIGURES = ROOT / "results" / "final_figures"

EXPECTED_TABLES = {
    "bootstrap_ci_summary.csv",
    "infant_ppx_hospitalizations_averted.csv",
    "infant_ppx_hospitalizations_averted_summary.csv",
    "infant_ppx_model_parameters.csv",
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
    "fig5_infant_ppx_hospitalizations_averted_primary_vs_50pct_uptake",
    "nhsn_fig_supp_timeseries",
    "nssp_fig_supp_timeseries",
}

FINAL_FIGURE_STUBS = {
    "fig1_choropleth_grid",
    "fig2_ridgeline_nssp_seasons",
    "fig3_infant_ppx_early_start_advantage_forest",
    "fig4_infant_ppx_hospitalizations_averted_by_window",
    "fig5_infant_ppx_hospitalizations_averted_primary_vs_50pct_uptake",
}

# These unrounded values are the manuscript NSSP totals for the
# September-March versus October-March comparison. Keeping the unrounded
# contract prevents a materially different result from passing merely because
# it happens to round to the same displayed integer.
MANUSCRIPT_EARLY_HOSPITALIZATION_TOTALS = {
    ("reference_12mo", "2023-2024"): (712.5977945808723, 713),
    ("reference_12mo", "2024-2025"): (408.3669792288585, 408),
    ("reference_12mo", "2025-2026"): (243.48905681612166, 243),
    ("uptake_50", "2023-2024"): (1925.9399853537088, 1926),
    ("uptake_50", "2024-2025"): (808.3814845083957, 808),
    ("uptake_50", "2025-2026"): (413.77679903305, 414),
    ("uptake_100", "2023-2024"): (3851.8799707074177, 3852),
    ("uptake_100", "2024-2025"): (679.2612104517825, 679),
    ("uptake_100", "2025-2026"): (51.992541233041216, 52),
}

# Median percentage-point gains for September-March versus October-March in
# the no-routine-visit catch-up sensitivity. Values are stored on the
# fractional scale in the output table.
MANUSCRIPT_CATCHUP_EARLY_DELTAS = {
    "nssp": (0.0047836682368414, 0.48),
    "nhsn": (0.0020601422873407, 0.21),
}

MANUSCRIPT_VALUE_ABS_TOLERANCE = 1e-6


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def verify_headline_rows(
    nssp_2526: pd.DataFrame,
    nhsn_2526: pd.DataFrame,
    *,
    allow_live_inputs: bool,
) -> None:
    """Apply structural checks always and manuscript-value checks when frozen."""
    require(
        nssp_2526["jurisdiction"].nunique() == 51,
        "NSSP 2025-26 must contain 51 jurisdictions.",
    )
    require(
        nhsn_2526["jurisdiction"].nunique() == 51,
        "NHSN 2025-26 must contain 51 jurisdictions.",
    )
    if not allow_live_inputs:
        require(
            0.14 < nssp_2526["outside_fraction"].median() < 0.19,
            "NSSP headline is out of range.",
        )
        require(
            0.11 < nhsn_2526["outside_fraction"].median() < 0.17,
            "NHSN headline is out of range.",
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-live-inputs",
        action="store_true",
        help=(
            "run structural and model-contract checks without requiring the "
            "materialized frozen inputs or manuscript data-dependent values"
        ),
    )
    args = parser.parse_args()

    verified_inputs = verify_frozen_manifest()
    if not args.allow_live_inputs:
        for key, (snapshot, materialized) in verified_inputs.items():
            require(
                materialized.is_file()
                and materialized.read_bytes() == snapshot.read_bytes(),
                f"Materialized input {key!r} does not match the frozen manuscript "
                "snapshot. Run `make frozen-data` before manuscript verification.",
            )

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

    observed_final_figures = {
        path.name for path in FINAL_FIGURES.glob("*") if path.is_file()
    }
    expected_final_figures = {
        f"{stub}.{extension}"
        for stub in FINAL_FIGURE_STUBS
        for extension in ("png", "pdf")
    }
    require(observed_final_figures == expected_final_figures, (
        "Final-figure contract mismatch. "
        f"Missing={sorted(expected_final_figures - observed_final_figures)}; "
        f"unexpected={sorted(observed_final_figures - expected_final_figures)}"
    ))
    for name in sorted(expected_final_figures):
        require(
            (FIGURES / name).read_bytes() == (FINAL_FIGURES / name).read_bytes(),
            f"Final figure is not byte-identical to generated source: {name}",
        )

    config = yaml.safe_load((ROOT / "config.yaml").read_text())
    model = config["infant_ppx_model"]
    require(model["uptake"] == 0.185, "Primary uptake must be encoded as 18.5%.")
    require(model["efficacy_profile"] == "piecewise_linear", "Primary efficacy profile mismatch.")
    require(model["protection_duration_days"] == 210, "Primary protection duration mismatch.")
    require(
        model["receipt_history_mode"] == "seasonal_coverage_first_visit",
        "Primary model must use seasonal uptake at the first eligible visit.",
    )
    require(
        model["program_start_season_year"] == 2023,
        "Receipt history must begin with the actual 2023-24 program launch.",
    )
    require(
        model["catchup_if_no_routine_visit"] is False,
        "The no-routine-visit catch-up option must be off in the primary model.",
    )

    parameters = pd.read_csv(TABLES / "infant_ppx_model_parameters.csv")
    expected_parameters = {
        "Prophylaxis windows compared",
        "Primary timing curve",
        "Birth distribution",
        "Eligibility",
        "Receipt history",
        "Exposure censor",
        "Uptake",
        "Newborn/first-week dosing pathway",
        "Routine well-child visits",
        "Visit timing distribution",
        "Time to protection onset",
        "Effectiveness curve",
        "Untreated infant RSV hospitalization risk",
        "Infant population denominator",
    }
    require(
        set(parameters["parameter"]) == expected_parameters,
        "Parameter provenance table does not match manuscript Table 2.",
    )
    require(
        parameters[["value", "source", "rationale", "source_detail"]]
        .notna()
        .all()
        .all(),
        "Parameter provenance table contains missing values.",
    )
    parameter_values = parameters.set_index("parameter")["value"].to_dict()
    require("18.5%" in parameter_values["Uptake"], "Parameter table uptake mismatch.")
    require(
        parameter_values["Receipt history"] == "Prior recipients not redosed",
        "Parameter table receipt-history wording does not match manuscript Table 2.",
    )
    require(
        not parameters.astype(str).apply(
            lambda column: column.str.contains("cor" + "rected", case=False).any()
        ).any(),
        "Parameter provenance table contains revision-history wording.",
    )
    require("210" in parameter_values["Effectiveness curve"], "Parameter table duration mismatch.")
    require("38.1%" in parameter_values["Newborn/first-week dosing pathway"], "Parameter table newborn pathway mismatch.")
    require("59%" in parameter_values["Visit timing distribution"], "Parameter table visit-timing mismatch.")

    geometry_cfg = config["analysis_data"]["state_geometry"]
    geometry_path = ROOT / "data" / "raw" / geometry_cfg["filename"]
    require(geometry_path.is_file(), "Missing prepared Census state geometry.")
    geometry_source = ROOT / "data" / "raw" / geometry_cfg["source_filename"]
    require(geometry_source.is_file(), "Missing cached Census state-geometry source.")
    with ZipFile(geometry_source) as archive:
        suffixes = {Path(name).suffix.lower() for name in archive.namelist()}
    require(
        {".shp", ".shx", ".dbf", ".prj"}.issubset(suffixes),
        "Cached Census state geometry is incomplete.",
    )

    nssp = pd.read_csv(TABLES / "nssp_outside_fraction_by_state.csv")
    nhsn = pd.read_csv(TABLES / "nhsn_outside_fraction_by_state.csv")
    nssp_2526 = nssp[nssp["season"] == "2025-2026"]
    nhsn_2526 = nhsn[nhsn["season"] == "2025-2026"]
    verify_headline_rows(
        nssp_2526,
        nhsn_2526,
        allow_live_inputs=args.allow_live_inputs,
    )

    stress = pd.read_csv(TABLES / "infant_ppx_stress_test_window_summary.csv")
    prohibited = {"bootstrap_pr_delta_gt_zero", "delta_ci_lower", "delta_ci_upper"}
    require(not prohibited.intersection(stress.columns), "Stress table contains inferential columns.")
    expected_scenarios = {
        "reference_12mo",
        "censor_8mo",
        "uptake_50",
        "uptake_75",
        "uptake_100",
        "newborn_first_week_20",
        "newborn_first_week_60",
        "visit_delay_0",
        "visit_delay_30",
        "waning_rapid",
        "catchup_no_routine_visit",
    }
    require(
        set(stress["scenario_id"]) == expected_scenarios,
        "Stress table does not contain exactly the 11 retained scenarios.",
    )
    primary = stress[stress["scenario_id"] == "reference_12mo"]
    require(set(primary["uptake"]) == {0.185}, "Primary rows do not use 18.5% uptake.")
    require(
        set(primary["receipt_history_mode"]) == {"seasonal_coverage_first_visit"},
        "Primary rows do not use the configured longitudinal receipt history.",
    )
    require(
        set(stress["receipt_history_mode"]) == {"seasonal_coverage_first_visit"},
        "Stress rows contain an unsupported receipt-history comparator.",
    )
    catchup = stress[stress["scenario_id"] == "catchup_no_routine_visit"]
    require(
        set(catchup["catchup_if_no_routine_visit"]) == {True},
        "Catch-up sensitivity does not enable its targeted receipt opportunity.",
    )
    noncatchup = stress[stress["scenario_id"] != "catchup_no_routine_visit"]
    require(
        set(noncatchup["catchup_if_no_routine_visit"]) == {False},
        "Catch-up opportunity leaked into another sensitivity scenario.",
    )
    # Eligibility ends before 8 months, so a cohort can encounter at most two
    # annual seasonal windows before aging out.
    max_eligible_windows = 2
    maximum_first_receipt_probability = 1 - (
        (1 - stress["uptake"]) ** max_eligible_windows
    )
    require(
        (
            stress["median_share_receiving_ppx"]
            <= maximum_first_receipt_probability + 1e-12
        ).all(),
        "Modeled receipt exceeds the bound from one opportunity per annual window.",
    )
    year_round = primary[primary["window_name"] == "year_round"]
    require(
        (
            (year_round["median_share_receiving_ppx"] - year_round["uptake"])
            .abs()
            < 1e-12
        ).all(),
        "Year-round receipt must equal total uptake at steady state.",
    )

    expected_year_round_keys = {
        (datasource, scenario_id)
        for datasource in ("nssp", "nhsn")
        for scenario_id in expected_scenarios
    }
    all_year_round = stress[stress["window_name"] == "year_round"]
    observed_year_round_keys = set(
        zip(all_year_round["datasource"], all_year_round["scenario_id"])
    )
    require(
        observed_year_round_keys == expected_year_round_keys
        and not all_year_round.duplicated(["datasource", "scenario_id"]).any(),
        "Year-round stress rows must contain one row per datasource and scenario.",
    )
    unsupported_person_fields = [
        column
        for column in (
            "median_person_activity_fractional_protection",
            "mean_person_activity_fractional_protection",
            "q25_person_activity_fractional_protection",
            "q75_person_activity_fractional_protection",
            "median_person_calendar_fractional_protection",
            "mean_person_calendar_fractional_protection",
        )
        if column in stress.columns
    ]
    require(
        {
            "median_person_activity_fractional_protection",
            "q25_person_activity_fractional_protection",
            "q75_person_activity_fractional_protection",
        }.issubset(unsupported_person_fields),
        "Stress table is missing the expected person-level summary fields.",
    )
    nonmissing_year_round = all_year_round[
        unsupported_person_fields
    ].notna()
    require(
        not nonmissing_year_round.any().any(),
        "Year-round rows contain unsupported person-level distribution summaries: "
        f"{sorted(nonmissing_year_round.columns[nonmissing_year_round.any()].tolist())}",
    )

    if not args.allow_live_inputs:
        for datasource, (expected_delta, displayed_pp) in (
            MANUSCRIPT_CATCHUP_EARLY_DELTAS.items()
        ):
            row = stress[
                (stress["datasource"] == datasource)
                & (stress["scenario_id"] == "catchup_no_routine_visit")
                & (stress["window_name"] == "early_sep_mar")
            ]
            require(
                len(row) == 1,
                f"Expected exactly one {datasource.upper()} catch-up early-window row.",
            )
            observed_delta = float(row.iloc[0]["delta_vs_baseline_oct_mar"])
            require(
                abs(observed_delta - expected_delta) <= MANUSCRIPT_VALUE_ABS_TOLERANCE,
                f"{datasource.upper()} catch-up median gain changed: "
                f"expected {expected_delta * 100:.6f} percentage points "
                f"(reported as {displayed_pp:.2f}), observed "
                f"{observed_delta * 100:.6f}.",
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

    hospitalization_summary = pd.read_csv(
        TABLES / "infant_ppx_hospitalizations_averted_summary.csv"
    )
    summary_keys = [
        "datasource",
        "season",
        "scenario_id",
        "comparison_window_name",
    ]
    detail_totals = hospitalizations.groupby(summary_keys, dropna=False)[
        "hospitalizations_averted_vs_baseline"
    ].sum().sort_index()
    summary_totals = hospitalization_summary.set_index(summary_keys)[
        "total_hospitalizations_averted_vs_baseline"
    ].sort_index()
    require(
        summary_totals.index.is_unique,
        "Hospitalization summary contains duplicate grouping keys.",
    )
    require(
        detail_totals.index.equals(summary_totals.index),
        "Hospitalization summary groups do not match hospitalization detail groups.",
    )
    require(
        ((detail_totals - summary_totals).abs() <= 1e-9).all(),
        "Hospitalization summary totals do not equal the corresponding summed state detail rows.",
    )

    if not args.allow_live_inputs:
        for (
            scenario_id,
            season,
        ), (expected_total, displayed_total) in (
            MANUSCRIPT_EARLY_HOSPITALIZATION_TOTALS.items()
        ):
            row = hospitalization_summary[
                (hospitalization_summary["datasource"] == "nssp")
                & (hospitalization_summary["scenario_id"] == scenario_id)
                & (hospitalization_summary["season"] == season)
                & (
                    hospitalization_summary["comparison_window_name"]
                    == "early_sep_mar"
                )
            ]
            require(
                len(row) == 1,
                "Expected exactly one manuscript NSSP early-window hospitalization row "
                f"for {scenario_id}, {season}.",
            )
            observed_total = float(
                row.iloc[0]["total_hospitalizations_averted_vs_baseline"]
            )
            require(
                abs(observed_total - expected_total) <= MANUSCRIPT_VALUE_ABS_TOLERANCE,
                "Manuscript NSSP early-window hospitalization total changed for "
                f"{scenario_id}, {season}: expected {expected_total:.6f} "
                f"(reported as {displayed_total:,}), observed {observed_total:.6f}.",
            )

    figure_source = (ROOT / "src" / "figures.R").read_text()
    fig4_start = figure_source.find(
        "plot_infant_hospitalizations_averted <- function"
    )
    fig5_start = figure_source.find(
        "plot_infant_hospitalizations_averted_ab <- function"
    )
    require(
        0 <= fig4_start < fig5_start,
        "Could not locate the Figure 4 and Figure 5 plotting functions.",
    )
    fig4_source = figure_source[fig4_start:fig5_start]
    require(
        re.search(
            r'filter\s*\(\s*datasource\s*==\s*"nssp"\s*,\s*'
            r'scenario_id\s*==\s*"uptake_50"',
            fig4_source,
        )
        is not None,
        "Figure 4 must select the NSSP uptake_50 scenario.",
    )

    fig5_end = figure_source.find("plot_timeseries <- function", fig5_start)
    require(fig5_end > fig5_start, "Could not isolate the Figure 5 plotting function.")
    fig5_source = figure_source[fig5_start:fig5_end]
    fig5_panel_scenarios = dict(
        re.findall(
            r'^\s*p_([ab])\s*<-\s*averted_panel\s*\(\s*"([^"]+)"',
            fig5_source,
            flags=re.MULTILINE,
        )
    )
    require(
        fig5_panel_scenarios
        == {"a": "reference_12mo", "b": "uptake_50"},
        "Figure 5 panels must select reference_12mo for panel A and "
        f"uptake_50 for panel B; observed {fig5_panel_scenarios}.",
    )
    require((ROOT / "results" / "manuscript_stats.txt").is_file(), "Missing manuscript statistics summary.")

    public_files = [
        ROOT / "README.md",
        ROOT / "config.yaml",
        ROOT / "src" / "analysis_infant_ppx.py",
        ROOT / "src" / "figures.R",
        ROOT / "src" / "manuscript_stats.py",
        ROOT / "src" / "run_pipeline.py",
    ]
    prohibited_phrases = (
        "cor" + "rected primary model",
        "seasonal_" + "cold_start",
        "first_" + "opportunity_only",
        "eligible_" + "until_receipt",
        "allow_" + "window_start_catchup",
    )
    for path in public_files:
        text = path.read_text().lower()
        for phrase in prohibited_phrases:
            require(
                phrase.lower() not in text,
                f"Obsolete or revision-history wording remains in {path.name}: {phrase}",
            )
    print("Pipeline checks passed.")


if __name__ == "__main__":
    main()
