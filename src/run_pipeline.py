"""
Main pipeline orchestration - 2025-26 season extension.

Components:
 1. Data extraction: CDC NSSP (3 seasons) and NHSN (2-3 seasons)
 2. Season building and jurisdiction filtering
 3. Burden analysis: outside fraction, material activity, extended windows
 4. Age-stratified NHSN burden analysis (0-4, all pediatric, all ages)
 5. Bootstrap confidence intervals for national medians
 6. Longitudinal consistency metrics (CV, Spearman rank correlations)
 7. Figure generation (R/ggplot2 + ggridges)
 8. Table output (CSV)

Usage:
    python -m src.run_pipeline [--force-refresh] [--use-cache] [--figures-only]
"""

import logging
import subprocess
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

# Full detail goes to pipeline.log; only warnings and errors reach the console.
_console = logging.StreamHandler(sys.stdout)
_console.setLevel(logging.WARNING)
_logfile = logging.FileHandler("pipeline.log")
_logfile.setLevel(logging.INFO)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[_console, _logfile],
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
DATA_PROCESSED = PROJECT_ROOT / "data" / "processed"
RESULTS_TABLES = PROJECT_ROOT / "results" / "tables"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def save_table(df: pd.DataFrame, name: str) -> Path:
    RESULTS_TABLES.mkdir(parents=True, exist_ok=True)
    filepath = RESULTS_TABLES / f"{name}.csv"
    df.to_csv(filepath, index=False)
    logger.info(f"Saved table: {filepath}")
    return filepath


def remove_stale_data_driven_outputs() -> None:
    """Remove generated trigger-window tables from older pipeline runs."""
    stale_tables = [
        "nssp_table_trigger_comparison",
        "nssp_trigger_coverage_by_state",
        "nhsn_table_trigger_comparison",
        "nhsn_trigger_coverage_by_state",
        "nhsn_trigger_coverage_rsvped04",
        "nhsn_trigger_coverage_rsvpedtotal",
        "nhsn_trigger_coverage_rsvtotal",
        "nssp_infant_ppx_state_summary",
        "nssp_infant_ppx_birth_month_summary",
        "nhsn_infant_ppx_state_summary",
        "nhsn_infant_ppx_birth_month_summary",
        "nssp_infant_ppx_9mo_state_summary",
        "nssp_infant_ppx_9mo_birth_month_summary",
        "nhsn_infant_ppx_9mo_state_summary",
        "nhsn_infant_ppx_9mo_birth_month_summary",
        "nssp_infant_ppx_efficacy_state_summary",
        "nssp_infant_ppx_efficacy_birth_month_summary",
        "nhsn_infant_ppx_efficacy_state_summary",
        "nhsn_infant_ppx_efficacy_birth_month_summary",
        "nssp_infant_ppx_censor8mo_state_summary",
        "nssp_infant_ppx_censor8mo_birth_month_summary",
        "nhsn_infant_ppx_censor8mo_state_summary",
        "nhsn_infant_ppx_censor8mo_birth_month_summary",
    ]
    for name in stale_tables:
        path = RESULTS_TABLES / f"{name}.csv"
        if path.exists():
            path.unlink()
            logger.info(f"Removed stale data-driven table: {path}")


def run_r_figures() -> None:
    script_path = PROJECT_ROOT / "src" / "figures.R"
    if not script_path.exists():
        logger.error(f"R figure script not found at {script_path}")
        return

    logger.info("Generating figures with R/ggplot2...")
    try:
        subprocess.run(
            ["Rscript", str(script_path)],
            check=True,
            cwd=PROJECT_ROOT
        )
    except FileNotFoundError:
        logger.error("Rscript not found. Install R and ensure Rscript is on PATH.")
    except subprocess.CalledProcessError as exc:
        logger.error(f"R figure script failed with exit code {exc.returncode}")


def attach_metric_label(df: pd.DataFrame, metric_label: str) -> pd.DataFrame:
    labeled = df.copy()
    labeled["metric_label"] = metric_label
    return labeled


# ---------------------------------------------------------------------------
# Table builders
# ---------------------------------------------------------------------------

def create_table1(
    df_outside: pd.DataFrame,
    df_national: pd.DataFrame,
    df_regional: pd.DataFrame,
    total_label: str = "Total Metric (sum over weeks)"
) -> pd.DataFrame:
    rows = []
    for _, row in df_national.iterrows():
        rows.append({
            "Group": "National (weighted)",
            "Season": row["season"],
            "N": row["n_states"],
            "Median Outside Fraction": row["national_outside_fraction_weighted"],
            "Q25": None,
            "Q75": None,
            total_label: row.get("total_national_burden", None)
        })
    for _, row in df_regional.iterrows():
        rows.append({
            "Group": f"HHS Region {int(row['hhs_region'])}",
            "Season": row["season"],
            "N": row["n_states"],
            "Median Outside Fraction": row["median_outside_fraction"],
            "Q25": row["q25_outside_fraction"],
            "Q75": row["q75_outside_fraction"],
            total_label: None
        })
    return pd.DataFrame(rows).sort_values(["Season", "Group"])

def create_cross_source_comparison(
    nssp_burden: dict,
    nhsn_burden: dict,
    season: str = "2024-2025",
    nssp_metric_label: str = "RSV ED visit percentage of total ED visits, all ages",
    nhsn_metric_label: str = "Pediatric RSV hospital admissions, ages 0-4"
) -> pd.DataFrame:
    rows = []

    def build_row(source_label, metric_label, burden):
        outside = burden["outside_fraction"]
        national = burden["national_summary"]
        season_outside = outside[outside["season"] == season]
        season_national = national[national["season"] == season]

        median_outside = season_outside["outside_fraction"].median() if len(season_outside) else None
        unweighted = weighted = total_metric = None
        if len(season_national) > 0:
            r = season_national.iloc[0]
            unweighted = r.get("national_outside_fraction_unweighted")
            weighted = r.get("national_outside_fraction_weighted")
            total_metric = r.get("total_national_burden")

        rows.append({
            "Data Source": source_label,
            "Metric": metric_label,
            "Season": season,
            "N States": len(season_outside),
            "Median Outside Fraction": median_outside,
            "Unweighted Outside Fraction": unweighted,
            "Weighted Outside Fraction": weighted,
            "Total Metric (sum over weeks)": total_metric
        })

    build_row("NSSP", nssp_metric_label, nssp_burden)
    build_row("NHSN", nhsn_metric_label, nhsn_burden)
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["Data Source", "Season"])
    return df


def create_monthly_metric_comparison(
    df_nssp: pd.DataFrame,
    df_nhsn: pd.DataFrame,
    nssp_value_col: str,
    nhsn_value_col: str,
    season: str = "2024-2025",
    nssp_metric_label: str = "RSV ED visit percentage of total ED visits, all ages",
    nhsn_metric_label: str = "Pediatric RSV hospital admissions, ages 0-4"
) -> pd.DataFrame:
    rows = []

    def add_rows(df, value_col, source_label, metric_label):
        season_df = df[df["season"] == season].copy()
        if len(season_df) == 0:
            return
        season_df["month"] = season_df["week_end"].dt.to_period("M").astype(str)
        monthly = season_df.groupby("month")[value_col].sum()
        total = monthly.sum()
        for month, val in monthly.items():
            rows.append({
                "Data Source": source_label,
                "Metric": metric_label,
                "Season": season,
                "Month": month,
                "Month Metric Total": val,
                "Month Metric Fraction": val / total if total > 0 else None
            })

    add_rows(df_nssp, nssp_value_col, "NSSP", nssp_metric_label)
    add_rows(df_nhsn, nhsn_value_col, "NHSN", nhsn_metric_label)
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["Data Source", "Month"])
    return df


def create_infant_stress_window_summary(
    state_summary: pd.DataFrame,
    bootstrap_replicates: int = 2000,
    bootstrap_seed: int = 42,
) -> pd.DataFrame:
    if state_summary.empty:
        return pd.DataFrame()

    rows = []
    group_cols = [
        "datasource",
        "metric_label",
        "scenario_id",
        "scenario_family",
        "scenario_label",
        "scenario_order",
        "window_name",
        "window_label",
    ]
    for keys, group in state_summary.groupby(group_cols, dropna=False):
        row = dict(zip(group_cols, keys))
        person_values = group["median_person_activity_fractional_protection"].dropna()
        activity_values = group["population_activity_weighted_protection"].dropna()
        dose_values = group["share_receiving_ppx"].dropna()
        row.update({
            "n_state_seasons": len(group),
            "metric_used": "population_activity_weighted_protection",
            "median_population_activity_weighted_protection": (
                activity_values.median() if len(activity_values) else None
            ),
            "q25_population_activity_weighted_protection": (
                activity_values.quantile(0.25) if len(activity_values) else None
            ),
            "q75_population_activity_weighted_protection": (
                activity_values.quantile(0.75) if len(activity_values) else None
            ),
            "median_person_activity_fractional_protection": (
                person_values.median() if len(person_values) else None
            ),
            "q25_person_activity_fractional_protection": (
                person_values.quantile(0.25) if len(person_values) else None
            ),
            "q75_person_activity_fractional_protection": (
                person_values.quantile(0.75) if len(person_values) else None
            ),
            "median_share_receiving_ppx": dose_values.median() if len(dose_values) else None,
            "uptake": group["uptake"].iloc[0] if "uptake" in group else None,
            "efficacy_profile": group["efficacy_profile"].iloc[0] if "efficacy_profile" in group else None,
            "protection_duration_days": (
                group["protection_duration_days"].iloc[0]
                if "protection_duration_days" in group else None
            ),
            "exposure_censor_age_days": (
                group["exposure_censor_age_days"].iloc[0]
                if "exposure_censor_age_days" in group else None
            ),
            "birth_weight_scheme": (
                group["birth_weight_scheme"].iloc[0]
                if "birth_weight_scheme" in group else None
            ),
        })
        rows.append(row)

    summary = pd.DataFrame(rows)
    baseline = (
        summary[summary["window_name"] == "baseline_oct_mar"]
        [["datasource", "scenario_id", "median_population_activity_weighted_protection"]]
        .rename(columns={
            "median_population_activity_weighted_protection": "baseline_oct_mar_protection"
        })
    )
    summary = summary.merge(baseline, on=["datasource", "scenario_id"], how="left")

    delta_rows = []
    rng = np.random.default_rng(bootstrap_seed)
    for (datasource, scenario_id), group in state_summary.groupby(["datasource", "scenario_id"]):
        unit_cols = ["season", "jurisdiction"]
        pivot = (
            group.pivot_table(
                index=unit_cols,
                columns="window_name",
                values="population_activity_weighted_protection",
                aggfunc="first",
            )
            .dropna(subset=["baseline_oct_mar"])
        )
        if pivot.empty:
            continue
        for window_name in pivot.columns:
            if window_name == "baseline_oct_mar":
                delta_rows.append({
                    "datasource": datasource,
                    "scenario_id": scenario_id,
                    "window_name": window_name,
                    "delta_vs_baseline_oct_mar": 0.0,
                    "q25_delta_vs_baseline_oct_mar": 0.0,
                    "q75_delta_vs_baseline_oct_mar": 0.0,
                    "delta_ci_lower": 0.0,
                    "delta_ci_upper": 0.0,
                    "bootstrap_pr_delta_gt_zero": None,
                })
                continue
            valid = pivot[["baseline_oct_mar", window_name]].dropna()
            if valid.empty:
                continue
            sample_n = len(valid)
            observed_delta = (
                valid[window_name].to_numpy(dtype=float)
                - valid["baseline_oct_mar"].to_numpy(dtype=float)
            )
            bootstrap_deltas = np.empty(bootstrap_replicates, dtype=float)
            values = valid.to_numpy(dtype=float)
            for i in range(bootstrap_replicates):
                idx = rng.integers(0, sample_n, sample_n)
                sample = values[idx, :]
                bootstrap_deltas[i] = np.median(sample[:, 1] - sample[:, 0])
            delta_rows.append({
                "datasource": datasource,
                "scenario_id": scenario_id,
                "window_name": window_name,
                "delta_vs_baseline_oct_mar": float(np.median(observed_delta)),
                "q25_delta_vs_baseline_oct_mar": float(np.quantile(observed_delta, 0.25)),
                "q75_delta_vs_baseline_oct_mar": float(np.quantile(observed_delta, 0.75)),
                "delta_ci_lower": float(np.quantile(bootstrap_deltas, 0.025)),
                "delta_ci_upper": float(np.quantile(bootstrap_deltas, 0.975)),
                "bootstrap_pr_delta_gt_zero": float(np.mean(bootstrap_deltas > 0)),
            })

    if delta_rows:
        summary = summary.merge(
            pd.DataFrame(delta_rows),
            on=["datasource", "scenario_id", "window_name"],
            how="left",
        )
    return summary.sort_values(["scenario_order", "datasource", "window_name"])


def create_infant_stress_ranking(window_summary: pd.DataFrame) -> pd.DataFrame:
    if window_summary.empty:
        return pd.DataFrame()

    rows = []
    for keys, group in window_summary.groupby(
        ["datasource", "metric_label", "scenario_id", "scenario_family", "scenario_label", "scenario_order"],
        dropna=False,
    ):
        row = dict(zip(
            ["datasource", "metric_label", "scenario_id", "scenario_family", "scenario_label", "scenario_order"],
            keys,
        ))
        indexed = group.set_index("window_name")
        protection = indexed["median_population_activity_weighted_protection"]
        deltas = indexed["delta_vs_baseline_oct_mar"]
        best_window = deltas.idxmax() if len(deltas.dropna()) else None
        row.update({
            "metric_used": "population_activity_weighted_protection",
            "best_window_name": best_window,
            "best_window_label": (
                group.loc[group["window_name"] == best_window, "window_label"].iloc[0]
                if best_window is not None and (group["window_name"] == best_window).any()
                else None
            ),
            "baseline_oct_mar": protection.get("baseline_oct_mar"),
            "early_sep_mar": protection.get("early_sep_mar"),
            "late_oct_apr": protection.get("late_oct_apr"),
            "year_round": protection.get("year_round"),
            "early_minus_baseline": deltas.get("early_sep_mar"),
            "late_minus_baseline": deltas.get("late_oct_apr"),
            "year_round_minus_baseline": deltas.get("year_round"),
            "early_minus_late": deltas.get("early_sep_mar") - deltas.get("late_oct_apr"),
            "early_minus_year_round": deltas.get("early_sep_mar") - deltas.get("year_round"),
        })
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["scenario_order", "datasource"])


def create_infant_hospitalizations_averted(
    state_summary: pd.DataFrame,
    config: dict,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Translate protection gains into expected hospitalizations averted.

    The core protection model already encodes state-season timing and efficacy.
    This function joins a real state infant denominator and a published
    untreated infant hospitalization risk to estimate the absolute gain from
    moving the administration window earlier by one month.
    """
    translation_cfg = config.get("infant_hospitalization_translation", {})
    if not translation_cfg.get("enabled", False) or state_summary.empty:
        return pd.DataFrame(), pd.DataFrame()

    population_path = PROJECT_ROOT / translation_cfg.get(
        "infant_population_file",
        "data/raw/us_state_infant_population_2023_census_pep.csv",
    )
    if not population_path.exists():
        logger.warning("Infant population file missing: %s", population_path)
        return pd.DataFrame(), pd.DataFrame()

    population = pd.read_csv(population_path)
    population["infant_population_under1"] = pd.to_numeric(
        population["infant_population_under1"], errors="coerce"
    )

    datasource = translation_cfg.get("datasource", "nssp")
    scenario_id = translation_cfg.get("scenario_id", "uptake_100")
    baseline_window = translation_cfg.get("baseline_window", "baseline_oct_mar")
    comparison_window = translation_cfg.get("comparison_window", "early_sep_mar")
    comparison_window_label = {
        "early_sep_mar": "Early Sep-Mar",
        "late_oct_apr": "Late Oct-Apr",
        "year_round": "Year-round",
    }.get(comparison_window, comparison_window)
    risk = float(translation_cfg["baseline_hospitalization_risk_per_infant_season"])

    model_rows = state_summary[
        (state_summary["datasource"] == datasource)
        & (state_summary["scenario_id"] == scenario_id)
        & (state_summary["window_name"].isin([baseline_window, comparison_window]))
    ].copy()
    if model_rows.empty:
        logger.warning(
            "No infant PPX state-summary rows found for hospitalization translation "
            "(datasource=%s, scenario_id=%s).",
            datasource,
            scenario_id,
        )
        return pd.DataFrame(), pd.DataFrame()

    pivot = model_rows.pivot_table(
        index=[
            "datasource",
            "metric_label",
            "season",
            "jurisdiction",
            "scenario_id",
            "scenario_label",
        ],
        columns="window_name",
        values="population_activity_weighted_protection",
        aggfunc="first",
    ).reset_index()
    pivot = pivot.dropna(subset=[baseline_window, comparison_window])
    if pivot.empty:
        return pd.DataFrame(), pd.DataFrame()

    translated = pivot.merge(
        population[
            [
                "jurisdiction",
                "infant_population_under1",
                "age_desc",
                "population_year",
                "source",
                "source_url",
            ]
        ],
        on="jurisdiction",
        how="left",
    )
    missing = translated[translated["infant_population_under1"].isna()]["jurisdiction"].unique()
    if len(missing):
        logger.warning(
            "Missing infant population denominators for hospitalization translation: %s",
            ", ".join(sorted(missing)),
        )

    translated = translated.rename(columns={
        baseline_window: "baseline_population_activity_weighted_protection",
        comparison_window: "early_population_activity_weighted_protection",
        "source": "population_source",
        "source_url": "population_source_url",
    })
    translated["incremental_population_activity_weighted_protection"] = (
        translated["early_population_activity_weighted_protection"]
        - translated["baseline_population_activity_weighted_protection"]
    )
    translated["baseline_hospitalization_risk_per_infant_season"] = risk
    translated["baseline_hospitalization_risk_per_1000_infants"] = risk * 1000
    translated["comparison_window_name"] = comparison_window
    translated["comparison_window_label"] = comparison_window_label
    translated["baseline_window_name"] = baseline_window
    translated["baseline_window_label"] = "Baseline Oct-Mar"
    translated["hospitalization_burden_source"] = translation_cfg.get("burden_source")
    translated["population_source_note"] = translation_cfg.get("population_source")
    translated["hospitalizations_averted_early_vs_baseline"] = (
        translated["infant_population_under1"]
        * translated["baseline_hospitalization_risk_per_infant_season"]
        * translated["incremental_population_activity_weighted_protection"]
    )
    translated["hospitalizations_averted_vs_baseline"] = translated[
        "hospitalizations_averted_early_vs_baseline"
    ]
    translated["hospitalizations_averted_per_100k_infants"] = (
        100000
        * translated["baseline_hospitalization_risk_per_infant_season"]
        * translated["incremental_population_activity_weighted_protection"]
    )

    summary = (
        translated.groupby(["datasource", "season"], dropna=False)
        .agg(
            n_states=("jurisdiction", "nunique"),
            total_infant_population_under1=("infant_population_under1", "sum"),
            total_hospitalizations_averted_vs_baseline=(
                "hospitalizations_averted_vs_baseline",
                "sum",
            ),
            median_state_hospitalizations_averted=(
                "hospitalizations_averted_vs_baseline",
                "median",
            ),
            q25_state_hospitalizations_averted=(
                "hospitalizations_averted_vs_baseline",
                lambda x: x.quantile(0.25),
            ),
            q75_state_hospitalizations_averted=(
                "hospitalizations_averted_vs_baseline",
                lambda x: x.quantile(0.75),
            ),
            median_hospitalizations_averted_per_100k_infants=(
                "hospitalizations_averted_per_100k_infants",
                "median",
            ),
        )
        .reset_index()
    )
    summary["comparison"] = "Early Sep-Mar vs baseline Oct-Mar"
    summary["comparison"] = f"{comparison_window_label} vs baseline Oct-Mar"
    summary["total_hospitalizations_averted_early_vs_baseline"] = summary[
        "total_hospitalizations_averted_vs_baseline"
    ]
    summary["comparison_window_name"] = comparison_window
    summary["comparison_window_label"] = comparison_window_label
    summary["scenario_id"] = scenario_id
    summary["baseline_hospitalization_risk_per_1000_infants"] = risk * 1000
    summary["hospitalization_burden_source"] = translation_cfg.get("burden_source")
    summary["population_source"] = translation_cfg.get("population_source")

    return translated.sort_values(["season", "jurisdiction"]), summary


def log_summary_stats(df_outside, label):
    logger.info(f"{label} SUMMARY")
    for season in sorted(df_outside["season"].unique()):
        data = df_outside[df_outside["season"] == season]
        median = data["outside_fraction"].median()
        q25 = data["outside_fraction"].quantile(0.25)
        q75 = data["outside_fraction"].quantile(0.75)
        logger.info(f"  {season}: median={median:.1%} (IQR: {q25:.1%}-{q75:.1%})")


# ---------------------------------------------------------------------------
# NHSN season filtering
# ---------------------------------------------------------------------------

def filter_nhsn_by_completeness(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """
    Check each NHSN season for reporting completeness.
    Drops seasons where fewer than min_reporting_states jurisdictions report data.
    """
    nhsn_seasons = config.get("nhsn_seasons", config["seasons"])
    exclude_jur = config["geography"]["exclude_jurisdictions"]

    kept_seasons = []
    for season_def in nhsn_seasons:
        season_name = season_def["name"]
        min_states = season_def.get("min_reporting_states", 40)

        season_data = df[df["season"] == season_name].copy()
        season_data = season_data[~season_data["jurisdiction"].isin(exclude_jur)]

        # Count jurisdictions with at least 4 non-null weeks of primary outcome
        reporting = (
            season_data.groupby("jurisdiction")["rsv_ped_0_4"]
            .apply(lambda x: x.notna().sum())
        )
        n_reporting = (reporting >= 4).sum()

        if n_reporting >= min_states:
            kept_seasons.append(season_name)
            logger.info(
                f"NHSN {season_name}: {n_reporting} reporting states - INCLUDED"
            )
        else:
            logger.warning(
                f"NHSN {season_name}: only {n_reporting} reporting states "
                f"(minimum {min_states}) - EXCLUDED for completeness"
            )

    return df[df["season"].isin(kept_seasons)].copy()


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_pipeline(force_refresh: bool = False, max_cache_age_days: int | None = 1) -> dict:
    """
    Run the complete analysis pipeline.

    Args:
        force_refresh: If True, re-fetch data from Socrata even if cache exists
        max_cache_age_days: Maximum raw-data cache age. If None, use the most
            recent cached raw data regardless of age.

    Returns:
        Dictionary with all results
    """
    logger.info("RSV TIMING 2025-26 EXTENSION PIPELINE")
    logger.info(f"Started at: {datetime.now().isoformat()}")

    from src.pull_nssp import load_cached_or_fetch as load_nssp, log_row_counts as log_nssp_rows
    from src.pull_nhsn import load_cached_or_fetch as load_nhsn, log_row_counts as log_nhsn_rows
    from src.build_seasons import build_seasons, save_processed
    from src.analysis_burden import run_burden_analysis
    from src.analysis_infant_ppx import realistic_prior_table, run_infant_ppx_analysis
    config = load_config()
    remove_stale_data_driven_outputs()
    labels_cfg = config.get("labels", {})
    nssp_metric_label = labels_cfg.get(
        "nssp_metric", "RSV ED visit percentage of total ED visits, all ages"
    )
    nhsn_metric_label = labels_cfg.get(
        "nhsn_metric", "Pediatric RSV hospital admissions, ages 0-4"
    )
    nhsn_age_strata = config.get("nhsn_age_strata", [
        {"col": "rsv_ped_0_4", "label": nhsn_metric_label, "short_label": "Ages 0-4"}
    ])

    logger.info(f"Seasons: {[s['name'] for s in config['seasons']]}")
    logger.info(f"Primary outcome: {config['primary_outcome']}")
    if max_cache_age_days is None and not force_refresh:
        logger.info("Raw-data cache age check disabled; using latest cached raw files.")

    # ------------------------------------------------------------------
    # NSSP
    # ------------------------------------------------------------------
    logger.info("\nStep 1: Extracting NSSP data...")
    df_nssp_raw = load_nssp(max_age_days=max_cache_age_days, force_refresh=force_refresh)
    log_nssp_rows(df_nssp_raw)

    logger.info("\nStep 2: Building NSSP seasons...")
    df_nssp = build_seasons(df_nssp_raw)
    save_processed(df_nssp, filename="nssp_processed.parquet", also_csv=True)

    logger.info("\nStep 3: NSSP burden analysis...")
    nssp_value_col = config.get("primary_outcome", "rsv_pct")
    nssp_burden = run_burden_analysis(
        df_nssp, value_col=nssp_value_col,
        datasource="nssp", age_group_label="all_ages",
        run_bootstrap=True, run_longitudinal=True
    )

    logger.info("\nStep 4: Saving NSSP tables...")
    table1_nssp = create_table1(
        nssp_burden["outside_fraction"],
        nssp_burden["national_summary"],
        nssp_burden["regional_summary"],
        total_label=f"Total {nssp_metric_label} (sum of weekly values)"
    )
    save_table(table1_nssp, "nssp_table1_outside_fraction_summary")
    save_table(nssp_burden["regional_summary"], "nssp_regional_summary")
    save_table(
        attach_metric_label(nssp_burden["outside_fraction"], nssp_metric_label),
        "nssp_outside_fraction_by_state"
    )
    save_table(
        attach_metric_label(nssp_burden["material_activity"], nssp_metric_label),
        "nssp_material_activity_by_state"
    )
    save_table(
        attach_metric_label(nssp_burden["extended_windows"], nssp_metric_label),
        "nssp_extended_windows_evaluation"
    )
    if nssp_burden["bootstrap_ci"] is not None:
        save_table(nssp_burden["bootstrap_ci"], "nssp_bootstrap_ci_summary")
    if nssp_burden["longitudinal"] is not None:
        save_table(nssp_burden["longitudinal"], "nssp_longitudinal_consistency")

    log_summary_stats(nssp_burden["outside_fraction"], "NSSP")

    # ------------------------------------------------------------------
    # NHSN - primary age stratum (rsv_ped_0_4)
    # ------------------------------------------------------------------
    logger.info("\nStep 5: Extracting NHSN data...")
    df_nhsn_raw = load_nhsn(max_age_days=max_cache_age_days, force_refresh=force_refresh)
    log_nhsn_rows(df_nhsn_raw)

    logger.info("\nStep 6: Building NHSN seasons (with completeness check)...")
    df_nhsn_all = build_seasons(df_nhsn_raw)
    df_nhsn_all = filter_nhsn_by_completeness(df_nhsn_all, config)
    save_processed(df_nhsn_all, filename="nhsn_processed.parquet", also_csv=True)

    nhsn_primary_col = config.get("nhsn_primary_outcome", "rsv_ped_0_4")

    logger.info("\nStep 7: NHSN primary burden analysis (ages 0-4)...")
    nhsn_burden = run_burden_analysis(
        df_nhsn_all, value_col=nhsn_primary_col,
        datasource="nhsn", age_group_label=nhsn_primary_col,
        run_bootstrap=True, run_longitudinal=True
    )

    logger.info("\nStep 8: Saving NHSN primary tables...")
    table1_nhsn = create_table1(
        nhsn_burden["outside_fraction"],
        nhsn_burden["national_summary"],
        nhsn_burden["regional_summary"],
        total_label="Total pediatric RSV admissions, ages 0-4"
    )
    save_table(table1_nhsn, "nhsn_table1_outside_fraction_summary")
    save_table(nhsn_burden["regional_summary"], "nhsn_regional_summary")
    save_table(
        attach_metric_label(nhsn_burden["outside_fraction"], nhsn_metric_label),
        "nhsn_outside_fraction_by_state"
    )
    save_table(
        attach_metric_label(nhsn_burden["material_activity"], nhsn_metric_label),
        "nhsn_material_activity_by_state"
    )
    save_table(
        attach_metric_label(nhsn_burden["extended_windows"], nhsn_metric_label),
        "nhsn_extended_windows_evaluation"
    )
    if nhsn_burden["bootstrap_ci"] is not None:
        save_table(nhsn_burden["bootstrap_ci"], "nhsn_bootstrap_ci_summary")
    if nhsn_burden["longitudinal"] is not None:
        save_table(nhsn_burden["longitudinal"], "nhsn_longitudinal_consistency")

    log_summary_stats(nhsn_burden["outside_fraction"], "NHSN (ages 0-4)")

    # ------------------------------------------------------------------
    # NHSN - additional age strata
    # ------------------------------------------------------------------
    logger.info("\nStep 9: NHSN burden analysis by age stratum...")

    all_strata_outside = []   # for ridgeline plot input
    all_strata_bootstrap = []

    for stratum in nhsn_age_strata:
        col = stratum["col"]
        label = stratum["label"]
        short = stratum["short_label"]

        logger.info(f"  Running stratum: {col} ({short})")
        strat_burden = run_burden_analysis(
            df_nhsn_all, value_col=col,
            datasource="nhsn", age_group_label=col,
            run_bootstrap=True, run_longitudinal=False
        )

        outside_tagged = strat_burden["outside_fraction"].copy()
        outside_tagged["age_group"] = col
        outside_tagged["age_group_label"] = short
        outside_tagged["metric_label"] = label
        all_strata_outside.append(outside_tagged)

        if strat_burden["bootstrap_ci"] is not None:
            all_strata_bootstrap.append(strat_burden["bootstrap_ci"])

        safe_col = col.replace("_", "")
        save_table(
            attach_metric_label(strat_burden["outside_fraction"], label),
            f"nhsn_outside_fraction_by_state_{safe_col}"
        )
        save_table(
            attach_metric_label(strat_burden["extended_windows"], label),
            f"nhsn_extended_windows_{safe_col}"
        )

    # Combined age-strata outside fraction table (for ridgeline figures)
    if all_strata_outside:
        combined_strata = pd.concat(all_strata_outside, ignore_index=True)
        save_table(combined_strata, "nhsn_outside_fraction_all_strata")

    # Combined bootstrap CI table
    if all_strata_bootstrap:
        combined_bootstrap = pd.concat(
            [nhsn_burden["bootstrap_ci"]] + all_strata_bootstrap,
            ignore_index=True
        )
        save_table(combined_bootstrap, "nhsn_bootstrap_ci_all_strata")

    # ------------------------------------------------------------------
    # Cross-source comparison tables
    # ------------------------------------------------------------------
    logger.info("\nStep 10: Infant prophylaxis protection model...")
    infant_parameters = []
    if config.get("infant_ppx_model", {}).get("enabled", True):
        save_table(realistic_prior_table(), "infant_ppx_realistic_priors")

        def run_and_save_infant_model(model_config: dict, suffix: str = "") -> list[pd.DataFrame]:
            name_suffix = f"_{suffix}" if suffix else ""
            nssp_infant = run_infant_ppx_analysis(
                df_nssp,
                value_col=nssp_value_col,
                datasource="nssp",
                metric_label=nssp_metric_label,
                config=model_config,
            )
            save_table(nssp_infant["state_summary"], f"nssp_infant_ppx{name_suffix}_state_summary")
            save_table(nssp_infant["birth_month_summary"], f"nssp_infant_ppx{name_suffix}_birth_month_summary")
            infant_parameters.append(nssp_infant["parameters"])

            nhsn_infant = run_infant_ppx_analysis(
                df_nhsn_all,
                value_col=nhsn_primary_col,
                datasource="nhsn",
                metric_label=nhsn_metric_label,
                config=model_config,
            )
            save_table(nhsn_infant["state_summary"], f"nhsn_infant_ppx{name_suffix}_state_summary")
            save_table(nhsn_infant["birth_month_summary"], f"nhsn_infant_ppx{name_suffix}_birth_month_summary")
            infant_parameters.append(nhsn_infant["parameters"])
            return [nssp_infant["state_summary"], nhsn_infant["state_summary"]]

        realistic_priors = config.get("infant_ppx_realistic_priors", {})

        def realistic_delivery_config(exposure_censor_age_months: int, label: str) -> dict:
            scenario_config = deepcopy(config)
            infant_cfg = scenario_config["infant_ppx_model"]
            infant_cfg["uptake"] = float(
                realistic_priors.get("nirsevimab_uptake_2023_24", infant_cfg.get("uptake", 1.0))
            )
            infant_cfg["efficacy_profile"] = "piecewise_linear"
            infant_cfg["protection_duration_days"] = 210
            infant_cfg["newborn_first_week_dose_probability"] = float(
                realistic_priors.get("newborn_first_week_nirsevimab_receipt", 0.0)
            )
            infant_cfg["routine_visit_on_time_probability"] = float(
                realistic_priors.get("routine_visit_completion_first_15_months", 1.0)
            )
            infant_cfg["routine_visit_delay_days"] = int(
                round(realistic_priors.get("routine_visit_delay_days", 0))
            )
            infant_cfg["exposure_censor_age_months"] = exposure_censor_age_months
            infant_cfg["scenario_label"] = label
            return scenario_config

        def tag_stress_state(parts: list[pd.DataFrame], **meta) -> list[pd.DataFrame]:
            tagged = []
            for part in parts:
                if part is None or part.empty:
                    continue
                df = part.copy()
                for key, value in meta.items():
                    df[key] = value
                tagged.append(df)
            return tagged

        stress_state_parts = []

        config_realistic12mo = realistic_delivery_config(
            12, "Realistic delivery priors, 12-month exposure censor"
        )
        logger.info("  Figure 3 model: realistic delivery priors, 12-month censor")
        realistic12mo_parts = run_and_save_infant_model(config_realistic12mo, suffix="realistic12mo")
        stress_state_parts.extend(tag_stress_state(
            realistic12mo_parts,
            scenario_id="reference_12mo",
            scenario_family="Reference",
            scenario_label="Reference: 18.5% uptake; 38.1% first-week dosing; 14-day visit delay; Moline et al. 210-day efficacy; 12-month exposure censor",
            scenario_order=1,
        ))

        config_realistic8mo = realistic_delivery_config(
            8, "Realistic delivery priors, 8-month exposure censor"
        )
        logger.info("  Figure 4 model: realistic delivery priors, 8-month censor")
        realistic8mo_parts = run_and_save_infant_model(config_realistic8mo, suffix="realistic8mo")
        stress_state_parts.extend(tag_stress_state(
            realistic8mo_parts,
            scenario_id="censor_8mo",
            scenario_family="Censoring",
            scenario_label="8-month exposure censor; otherwise reference",
            scenario_order=2,
        ))

        def run_stress_scenario(scenario_id: str, family: str, label: str, order: int, edits: dict) -> None:
            scenario_config = realistic_delivery_config(12, label)
            infant_cfg = scenario_config["infant_ppx_model"]
            infant_cfg.update(edits)
            logger.info("  Stress test: %s", label)

            nssp_infant = run_infant_ppx_analysis(
                df_nssp,
                value_col=nssp_value_col,
                datasource="nssp",
                metric_label=nssp_metric_label,
                config=scenario_config,
                include_birth_month_summary=False,
            )
            nhsn_infant = run_infant_ppx_analysis(
                df_nhsn_all,
                value_col=nhsn_primary_col,
                datasource="nhsn",
                metric_label=nhsn_metric_label,
                config=scenario_config,
                include_birth_month_summary=False,
            )
            stress_state_parts.extend(tag_stress_state(
                [nssp_infant["state_summary"], nhsn_infant["state_summary"]],
                scenario_id=scenario_id,
                scenario_family=family,
                scenario_label=label,
                scenario_order=order,
            ))

        stress_specs = [
            ("uptake_50", "Uptake", "Uptake 50%; otherwise reference", 10, {"uptake": 0.50}),
            ("uptake_75", "Uptake", "Uptake 75%; otherwise reference", 11, {"uptake": 0.75}),
            ("uptake_100", "Uptake", "Uptake 100%; otherwise reference", 12, {"uptake": 1.00}),
            (
                "newborn_first_week_20",
                "Newborn dosing",
                "First-week dosing 20%; otherwise reference",
                20,
                {"newborn_first_week_dose_probability": 0.20},
            ),
            (
                "newborn_first_week_60",
                "Newborn dosing",
                "First-week dosing 60%; otherwise reference",
                21,
                {"newborn_first_week_dose_probability": 0.60},
            ),
            ("visit_delay_0", "Visit delay", "No routine-visit delay; otherwise reference", 30, {"routine_visit_delay_days": 0}),
            ("visit_delay_30", "Visit delay", "30-day routine-visit delay; otherwise reference", 31, {"routine_visit_delay_days": 30}),
            (
                "waning_rapid",
                "Waning",
                "Rapid waning: 130-210 day effectiveness at the lower 95% CI (42%); otherwise reference",
                40,
                {"efficacy_curve_points": [
                    {"day": 0.0, "efficacy": 0.0},
                    {"day": 6.0, "efficacy": 0.936},
                    {"day": 45.0, "efficacy": 0.807},
                    {"day": 210.0, "efficacy": 0.42},
                ]},
            ),
        ]
        for scenario_id, family, label, order, edits in stress_specs:
            run_stress_scenario(scenario_id, family, label, order, edits)

        if stress_state_parts:
            stress_state = pd.concat(stress_state_parts, ignore_index=True)
            stress_window_summary = create_infant_stress_window_summary(stress_state)
            stress_ranking = create_infant_stress_ranking(stress_window_summary)
            hosp_parts = []
            hosp_summary_parts = []
            comparison_outputs = {
                "early_sep_mar": "early",
                "late_oct_apr": "late",
                "year_round": "year_round",
            }
            for comparison_window, slug in comparison_outputs.items():
                comparison_config = deepcopy(config)
                comparison_config.setdefault("infant_hospitalization_translation", {})
                comparison_config["infant_hospitalization_translation"][
                    "comparison_window"
                ] = comparison_window
                hosp_averted, hosp_averted_summary = create_infant_hospitalizations_averted(
                    stress_state,
                    comparison_config,
                )
                if not hosp_averted.empty:
                    save_table(
                        hosp_averted,
                        f"infant_ppx_hospitalizations_averted_{slug}_vs_baseline",
                    )
                    hosp_parts.append(hosp_averted)
                if not hosp_averted_summary.empty:
                    save_table(
                        hosp_averted_summary,
                        f"infant_ppx_hospitalizations_averted_{slug}_vs_baseline_summary",
                    )
                    hosp_summary_parts.append(hosp_averted_summary)

            # Primary-model (reference scenario, realistic uptake) averted for the
            # A/B hospitalizations-averted figure. Mirrors the 100% uptake outputs
            # above but uses scenario_id=reference_12mo so the figure can contrast
            # realistic-uptake impact (panel A) with the 100% uptake idealization
            # (panel B).
            for primary_window, primary_slug in {
                "early_sep_mar": "early",
                "late_oct_apr": "late",
                "year_round": "year_round",
            }.items():
                primary_config = deepcopy(config)
                primary_tcfg = primary_config.setdefault(
                    "infant_hospitalization_translation", {}
                )
                primary_tcfg["comparison_window"] = primary_window
                primary_tcfg["scenario_id"] = "reference_12mo"
                primary_averted, primary_averted_summary = create_infant_hospitalizations_averted(
                    stress_state,
                    primary_config,
                )
                if not primary_averted.empty:
                    save_table(
                        primary_averted,
                        f"infant_ppx_hospitalizations_averted_{primary_slug}_vs_baseline_primary",
                    )
                if not primary_averted_summary.empty:
                    save_table(
                        primary_averted_summary,
                        f"infant_ppx_hospitalizations_averted_{primary_slug}_vs_baseline_primary_summary",
                    )

            save_table(stress_state, "infant_ppx_stress_test_state_summary")
            save_table(stress_window_summary, "infant_ppx_stress_test_window_summary")
            save_table(stress_ranking, "infant_ppx_stress_test_ranking")
            if hosp_parts:
                save_table(
                    pd.concat(hosp_parts, ignore_index=True),
                    "infant_ppx_hospitalizations_averted_vs_baseline",
                )
            if hosp_summary_parts:
                save_table(
                    pd.concat(hosp_summary_parts, ignore_index=True),
                    "infant_ppx_hospitalizations_averted_vs_baseline_summary",
                )

        if infant_parameters:
            save_table(
                pd.concat(infant_parameters, ignore_index=True),
                "infant_ppx_model_parameters"
            )
    else:
        logger.info("Infant prophylaxis protection model disabled in config.")

    # ------------------------------------------------------------------
    # Cross-source comparison tables
    # ------------------------------------------------------------------
    logger.info("\nStep 11: Cross-source comparison tables...")
    for season_name in ["2024-2025", "2025-2026"]:
        cross = create_cross_source_comparison(
            nssp_burden, nhsn_burden, season=season_name,
            nssp_metric_label=nssp_metric_label,
            nhsn_metric_label=nhsn_metric_label
        )
        safe = season_name.replace("-", "_")
        save_table(cross, f"comparison_outside_fraction_{safe}")

        monthly = create_monthly_metric_comparison(
            df_nssp, df_nhsn_all,
            nssp_value_col, nhsn_primary_col, season=season_name,
            nssp_metric_label=nssp_metric_label,
            nhsn_metric_label=nhsn_metric_label
        )
        save_table(monthly, f"comparison_monthly_metric_{safe}")

    # Combined bootstrap CI summary (NSSP + NHSN primary)
    bootstrap_parts = []
    if nssp_burden["bootstrap_ci"] is not None:
        bootstrap_parts.append(nssp_burden["bootstrap_ci"])
    if nhsn_burden["bootstrap_ci"] is not None:
        bootstrap_parts.append(nhsn_burden["bootstrap_ci"])
    if bootstrap_parts:
        save_table(
            pd.concat(bootstrap_parts, ignore_index=True),
            "bootstrap_ci_summary"
        )

    # Longitudinal consistency combined
    long_parts = []
    if nssp_burden["longitudinal"] is not None:
        nssp_long = nssp_burden["longitudinal"].copy()
        nssp_long["datasource"] = "nssp"
        long_parts.append(nssp_long)
    if nhsn_burden["longitudinal"] is not None:
        nhsn_long = nhsn_burden["longitudinal"].copy()
        nhsn_long["datasource"] = "nhsn"
        nhsn_long["age_group"] = nhsn_primary_col
        long_parts.append(nhsn_long)
    if long_parts:
        save_table(pd.concat(long_parts, ignore_index=True), "longitudinal_consistency")

    # ------------------------------------------------------------------
    # Figures
    # ------------------------------------------------------------------
    logger.info("\nStep 12: Generating figures with R...")
    run_r_figures()

    logger.info(f"\nPipeline completed at: {datetime.now().isoformat()}")

    return {
        "nssp": {
            "df": df_nssp,
            "burden_results": nssp_burden,
        },
        "nhsn": {
            "df": df_nhsn_all,
            "burden_results": nhsn_burden,
        }
    }

def generate_figures_only() -> dict:
    run_r_figures()
    return {}


def main():
    import argparse

    parser = argparse.ArgumentParser(description="RSV Timing 2025-26 Extension Pipeline")
    parser.add_argument("--force-refresh", action="store_true",
                        help="Force re-fetch data from Socrata even if cache exists")
    parser.add_argument("--use-cache", action="store_true",
                        help="Use the latest cached raw data regardless of file age")
    parser.add_argument("--max-cache-age-days", type=int, default=1,
                        help="Maximum raw-data cache age before fetching fresh data (default: 1)")
    parser.add_argument("--figures-only", action="store_true",
                        help="Only regenerate figures using existing processed data")
    args = parser.parse_args()

    if args.figures_only:
        generate_figures_only()
    else:
        max_cache_age_days = None if args.use_cache else args.max_cache_age_days
        run_pipeline(
            force_refresh=args.force_refresh,
            max_cache_age_days=max_cache_age_days
        )


if __name__ == "__main__":
    main()
