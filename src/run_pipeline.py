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
    python -m src.run_pipeline [--offline] [--figures-only]
"""

import logging
import shutil
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


def reset_generated_outputs() -> None:
    """Start each full run with only the publication output contract."""
    for path in (
        DATA_PROCESSED,
        PROJECT_ROOT / "results" / "tables",
        PROJECT_ROOT / "results" / "figures",
    ):
        if path.exists():
            shutil.rmtree(path)
    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    RESULTS_TABLES.mkdir(parents=True, exist_ok=True)


def run_r_figures() -> None:
    script_path = PROJECT_ROOT / "src" / "figures.R"
    if not script_path.exists():
        raise FileNotFoundError(f"R figure script not found at {script_path}")

    logger.info("Generating figures with R/ggplot2...")
    subprocess.run(
        ["Rscript", str(script_path)],
        check=True,
        cwd=PROJECT_ROOT,
    )


def attach_metric_label(df: pd.DataFrame, metric_label: str) -> pd.DataFrame:
    labeled = df.copy()
    labeled["metric_label"] = metric_label
    return labeled


def create_out_of_window_split(df: pd.DataFrame, value_col: str) -> pd.DataFrame:
    """Mean state share of seasonal activity before October and after March."""
    weekly = df.dropna(subset=["season", "jurisdiction", value_col]).copy()
    weekly["month"] = pd.to_datetime(weekly["week_end"]).dt.month
    rows = []
    for season, season_group in weekly.groupby("season"):
        shares = []
        for _, state_group in season_group.groupby("jurisdiction"):
            total = state_group[value_col].sum()
            if total <= 0:
                continue
            shares.append({
                "early": state_group.loc[
                    state_group["month"].isin([7, 8, 9]), value_col
                ].sum() / total,
                "late": state_group.loc[
                    state_group["month"].isin([4, 5, 6]), value_col
                ].sum() / total,
            })
        rows.append({
            "season": season,
            "n_states": len(shares),
            "mean_early_out_of_window_pct": 100 * np.mean([x["early"] for x in shares]),
            "mean_late_out_of_window_pct": 100 * np.mean([x["late"] for x in shares]),
        })
    return pd.DataFrame(rows).sort_values("season")


def create_infant_stress_window_summary(
    state_summary: pd.DataFrame,
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
                })
                continue
            valid = pivot[["baseline_oct_mar", window_name]].dropna()
            if valid.empty:
                continue
            observed_delta = (
                valid[window_name].to_numpy(dtype=float)
                - valid["baseline_oct_mar"].to_numpy(dtype=float)
            )
            delta_rows.append({
                "datasource": datasource,
                "scenario_id": scenario_id,
                "window_name": window_name,
                "delta_vs_baseline_oct_mar": float(np.median(observed_delta)),
                "q25_delta_vs_baseline_oct_mar": float(np.quantile(observed_delta, 0.25)),
                "q75_delta_vs_baseline_oct_mar": float(np.quantile(observed_delta, 0.75)),
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
    untreated infant hospitalization risk to estimate an alternative window's
    absolute gain relative to the October-March baseline.
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
        comparison_window: "comparison_population_activity_weighted_protection",
        "source": "population_source",
        "source_url": "population_source_url",
    })
    translated["incremental_population_activity_weighted_protection"] = (
        translated["comparison_population_activity_weighted_protection"]
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
    translated["hospitalizations_averted_vs_baseline"] = (
        translated["infant_population_under1"]
        * translated["baseline_hospitalization_risk_per_infant_season"]
        * translated["incremental_population_activity_weighted_protection"]
    )
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
    summary["comparison"] = f"{comparison_window_label} vs baseline Oct-Mar"
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

def run_pipeline(offline: bool = False, refresh_data: bool = False) -> dict:
    """Run the accepted-manuscript analysis using the configured data cutoff."""
    logger.info("RSV TIMING 2025-26 EXTENSION PIPELINE")
    logger.info(f"Started at: {datetime.now().isoformat()}")

    from src.data_contract import (
        load_cdc,
        load_census,
        require_prepared_state_geometry,
    )
    from src.pull_nssp import log_row_counts as log_nssp_rows
    from src.pull_nhsn import log_row_counts as log_nhsn_rows
    from src.build_seasons import build_seasons, save_processed
    from src.analysis_burden import run_burden_analysis
    from src.analysis_infant_ppx import (
        create_primary_parameter_table,
        run_infant_ppx_analysis,
    )
    config = load_config()
    # Figure 1 must use the explicit local 51-jurisdiction geometry cache. In
    # offline mode, fail before clearing any existing generated outputs.
    require_prepared_state_geometry()
    reset_generated_outputs()
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
    # ------------------------------------------------------------------
    # NSSP
    # ------------------------------------------------------------------
    logger.info("\nStep 1: Extracting NSSP data...")
    df_nssp_raw = load_cdc("nssp", offline=offline, refresh=refresh_data)
    log_nssp_rows(df_nssp_raw)

    logger.info("\nStep 2: Building NSSP seasons...")
    df_nssp = build_seasons(df_nssp_raw)
    save_processed(df_nssp, filename="nssp_processed.csv")

    logger.info("\nStep 3: NSSP burden analysis...")
    nssp_value_col = config.get("primary_outcome", "rsv_pct")
    nssp_burden = run_burden_analysis(
        df_nssp, value_col=nssp_value_col,
        datasource="nssp", age_group_label="all_ages",
        run_bootstrap=True, run_longitudinal=True
    )

    logger.info("\nStep 4: Saving NSSP tables...")
    save_table(
        attach_metric_label(nssp_burden["outside_fraction"], nssp_metric_label),
        "nssp_outside_fraction_by_state"
    )
    save_table(
        attach_metric_label(nssp_burden["extended_windows"], nssp_metric_label),
        "nssp_extended_windows_evaluation"
    )
    save_table(
        create_out_of_window_split(df_nssp, nssp_value_col),
        "nssp_out_of_window_early_late_split",
    )

    log_summary_stats(nssp_burden["outside_fraction"], "NSSP")

    # ------------------------------------------------------------------
    # NHSN - primary age stratum (rsv_ped_0_4)
    # ------------------------------------------------------------------
    logger.info("\nStep 5: Extracting NHSN data...")
    df_nhsn_raw = load_cdc("nhsn", offline=offline, refresh=refresh_data)
    log_nhsn_rows(df_nhsn_raw)

    logger.info("\nStep 6: Building NHSN seasons (with completeness check)...")
    df_nhsn_all = build_seasons(df_nhsn_raw)
    df_nhsn_all = filter_nhsn_by_completeness(df_nhsn_all, config)
    save_processed(df_nhsn_all, filename="nhsn_processed.csv")

    nhsn_primary_col = config.get("nhsn_primary_outcome", "rsv_ped_0_4")

    logger.info("\nStep 7: NHSN primary burden analysis (ages 0-4)...")
    nhsn_burden = run_burden_analysis(
        df_nhsn_all, value_col=nhsn_primary_col,
        datasource="nhsn", age_group_label=nhsn_primary_col,
        run_bootstrap=True, run_longitudinal=True
    )

    logger.info("\nStep 8: Saving NHSN primary tables...")
    save_table(
        attach_metric_label(nhsn_burden["outside_fraction"], nhsn_metric_label),
        "nhsn_outside_fraction_by_state"
    )
    save_table(
        attach_metric_label(nhsn_burden["extended_windows"], nhsn_metric_label),
        "nhsn_extended_windows_evaluation"
    )

    log_summary_stats(nhsn_burden["outside_fraction"], "NHSN (ages 0-4)")

    # ------------------------------------------------------------------
    # NHSN - additional age strata
    # ------------------------------------------------------------------
    logger.info("\nStep 9: NHSN burden analysis by age stratum...")

    all_strata_outside = []   # for ridgeline plot input

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

    # Combined age-strata outside fraction table (for ridgeline figures)
    if all_strata_outside:
        combined_strata = pd.concat(all_strata_outside, ignore_index=True)
        save_table(combined_strata, "nhsn_outside_fraction_all_strata")

    load_census(offline=offline, refresh=refresh_data)

    # ------------------------------------------------------------------
    # Infant prophylaxis model
    # ------------------------------------------------------------------
    logger.info("\nStep 10: Infant prophylaxis protection model...")
    if config.get("infant_ppx_model", {}).get("enabled", True):
        def run_model_pair(model_config: dict) -> list[pd.DataFrame]:
            nssp_infant = run_infant_ppx_analysis(
                df_nssp,
                value_col=nssp_value_col,
                datasource="nssp",
                metric_label=nssp_metric_label,
                config=model_config,
                include_birth_month_summary=False,
            )
            nhsn_infant = run_infant_ppx_analysis(
                df_nhsn_all,
                value_col=nhsn_primary_col,
                datasource="nhsn",
                metric_label=nhsn_metric_label,
                config=model_config,
                include_birth_month_summary=False,
            )
            return [nssp_infant["state_summary"], nhsn_infant["state_summary"]]

        def primary_config(exposure_censor_age_months: int, label: str) -> dict:
            scenario_config = deepcopy(config)
            infant_cfg = scenario_config["infant_ppx_model"]
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

        config_primary = primary_config(12, "Primary model")
        save_table(
            create_primary_parameter_table(config_primary),
            "infant_ppx_model_parameters",
        )
        logger.info("  Primary model, 12-month exposure censor")
        primary_parts = run_model_pair(config_primary)
        stress_state_parts.extend(tag_stress_state(
            primary_parts,
            scenario_id="reference_12mo",
            scenario_family="Reference",
            scenario_label="Primary model",
            scenario_order=1,
        ))

        # Uptake is a direct multiplier in the deterministic model. Derive these
        # sensitivities exactly from the primary state summaries instead of
        # rerunning every birth cohort three times.
        uptake_scaled_columns = [
            "share_receiving_ppx",
            "median_person_activity_fractional_protection",
            "q25_person_activity_fractional_protection",
            "q75_person_activity_fractional_protection",
            "mean_person_activity_fractional_protection",
            "population_activity_weighted_protection",
            "median_person_calendar_fractional_protection",
            "mean_person_calendar_fractional_protection",
        ]
        primary_uptake = float(config["infant_ppx_model"]["uptake"])
        for uptake, order in ((0.50, 10), (0.75, 11), (1.00, 12)):
            scaled_parts = []
            for part in primary_parts:
                scaled = part.copy()
                for column in uptake_scaled_columns:
                    scaled[column] = scaled[column] * uptake / primary_uptake
                scaled["uptake"] = uptake
                scaled_parts.append(scaled)
            stress_state_parts.extend(tag_stress_state(
                scaled_parts,
                scenario_id=f"uptake_{int(uptake * 100)}",
                scenario_family="Uptake",
                scenario_label=f"Uptake {int(uptake * 100)}%; otherwise primary",
                scenario_order=order,
            ))

        config_8mo = primary_config(8, "8-month exposure censor; otherwise primary")
        logger.info("  Sensitivity model, 8-month exposure censor")
        censor_8mo_parts = run_model_pair(config_8mo)
        stress_state_parts.extend(tag_stress_state(
            censor_8mo_parts,
            scenario_id="censor_8mo",
            scenario_family="Censoring",
            scenario_label="8-month exposure censor; otherwise primary",
            scenario_order=2,
        ))

        def run_stress_scenario(scenario_id: str, family: str, label: str, order: int, edits: dict) -> None:
            scenario_config = primary_config(12, label)
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
            (
                "newborn_first_week_20",
                "Newborn dosing",
                "First-week dosing 20%; otherwise primary",
                20,
                {"newborn_first_week_dose_probability": 0.20},
            ),
            (
                "newborn_first_week_60",
                "Newborn dosing",
                "First-week dosing 60%; otherwise primary",
                21,
                {"newborn_first_week_dose_probability": 0.60},
            ),
            ("visit_delay_0", "Visit delay", "No routine-visit delay; otherwise primary", 30, {"routine_visit_delay_days": 0}),
            ("visit_delay_30", "Visit delay", "30-day routine-visit delay; otherwise primary", 31, {"routine_visit_delay_days": 30}),
            (
                "waning_rapid",
                "Waning",
                "Rapid waning: 130-210 day effectiveness at the lower 95% CI (42%); otherwise primary",
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
            hospitalization_rows = []
            hospitalization_summaries = []
            for scenario_id in ("reference_12mo", "uptake_100"):
                for comparison_window in ("early_sep_mar", "late_oct_apr", "year_round"):
                    translation_config = deepcopy(config)
                    translation = translation_config.setdefault(
                        "infant_hospitalization_translation", {}
                    )
                    translation["scenario_id"] = scenario_id
                    translation["comparison_window"] = comparison_window
                    rows, summary = create_infant_hospitalizations_averted(
                        stress_state, translation_config
                    )
                    if not rows.empty:
                        hospitalization_rows.append(rows)
                    if not summary.empty:
                        hospitalization_summaries.append(summary)

            save_table(stress_window_summary, "infant_ppx_stress_test_window_summary")
            save_table(stress_ranking, "infant_ppx_stress_test_ranking")
            if hospitalization_rows:
                save_table(
                    pd.concat(hospitalization_rows, ignore_index=True),
                    "infant_ppx_hospitalizations_averted",
                )
            if hospitalization_summaries:
                save_table(
                    pd.concat(hospitalization_summaries, ignore_index=True),
                    "infant_ppx_hospitalizations_averted_summary",
                )
    else:
        logger.info("Infant prophylaxis protection model disabled in config.")

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
    parser.add_argument("--offline", action="store_true",
                        help="Use only the explicit fixed-cutoff local cache")
    parser.add_argument("--refresh-data", action="store_true",
                        help="Re-fetch public inputs through the configured cutoff")
    parser.add_argument("--figures-only", action="store_true",
                        help="Only regenerate figures using existing processed data")
    args = parser.parse_args()

    if args.figures_only:
        generate_figures_only()
    else:
        run_pipeline(offline=args.offline, refresh_data=args.refresh_data)


if __name__ == "__main__":
    main()
