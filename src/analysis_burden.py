"""
Burden analysis module — 2025-26 season extension.

Computes:
1. Outside fraction (burden outside Oct-Mar window)
2. Material activity (significant activity outside window)
3. Alternative fixed-window evaluation (counterfactual analysis)
4. Population-weighted national summary
5. Regional summary by HHS region
6. Bootstrap confidence intervals for national medians (10,000 replicates)
7. Longitudinal consistency metrics (CV, Spearman rank correlations across seasons)
"""

import logging
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import yaml

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Outside fraction
# ---------------------------------------------------------------------------

def compute_outside_fraction(
    df: pd.DataFrame,
    value_col: str = "rsv_pct",
    group_cols: Optional[list[str]] = None
) -> pd.DataFrame:
    """
    Compute fraction of RSV burden outside the fixed Oct-Mar window.

    Args:
        df: Processed DataFrame with in_fixed_window column
        value_col: Column containing RSV admissions / percentages
        group_cols: Columns to group by (default: ['season', 'jurisdiction'])

    Returns:
        DataFrame with total_burden, inside_burden, outside_burden, outside_fraction
    """
    if group_cols is None:
        group_cols = ["season", "jurisdiction"]

    df_valid = df[df[value_col].notna()].copy()

    results = []
    for group_keys, group_df in df_valid.groupby(group_cols):
        if len(group_cols) == 1:
            group_keys = (group_keys,)

        total = group_df[value_col].sum()
        inside = group_df.loc[group_df["in_fixed_window"], value_col].sum()
        outside = group_df.loc[~group_df["in_fixed_window"], value_col].sum()
        outside_frac = outside / total if total > 0 else np.nan

        row = dict(zip(group_cols, group_keys))
        row.update({
            "total_burden": total,
            "inside_burden": inside,
            "outside_burden": outside,
            "outside_fraction": outside_frac
        })
        results.append(row)

    df_result = pd.DataFrame(results)

    logger.info("=" * 50)
    logger.info("OUTSIDE FRACTION ANALYSIS")
    logger.info("=" * 50)
    logger.info(f"Computed for {len(df_result)} state-season combinations")
    logger.info(f"Median outside fraction: {df_result['outside_fraction'].median():.3f}")
    logger.info(f"Range: {df_result['outside_fraction'].min():.3f} – {df_result['outside_fraction'].max():.3f}")

    return df_result


# ---------------------------------------------------------------------------
# Material activity
# ---------------------------------------------------------------------------

def compute_material_activity(
    df: pd.DataFrame,
    value_col: str = "rsv_pct",
    smoothing: int = 3,
    threshold: float = 0.20
) -> pd.DataFrame:
    """
    Compute material activity outside the fixed window.

    Material activity = weeks where smoothed value >= threshold * season peak.
    """
    df_valid = df[df[value_col].notna()].copy()
    results = []

    for (season, jurisdiction), group_df in df_valid.groupby(["season", "jurisdiction"]):
        group_df = group_df.sort_values("week_end").copy()
        group_df["smoothed"] = (
            group_df[value_col]
            .rolling(window=smoothing, min_periods=1, center=True)
            .mean()
        )

        peak_idx = group_df["smoothed"].idxmax()
        peak_week = group_df.loc[peak_idx, "week_end"]
        peak_value = group_df["smoothed"].max()
        material_threshold = threshold * peak_value

        group_df["is_material"] = group_df["smoothed"] >= material_threshold

        material_weeks_total = group_df["is_material"].sum()
        material_weeks_outside = (
            group_df["is_material"] & ~group_df["in_fixed_window"]
        ).sum()

        total_burden = group_df[value_col].sum()
        material_burden_total = group_df.loc[group_df["is_material"], value_col].sum()
        material_burden_outside = group_df.loc[
            group_df["is_material"] & ~group_df["in_fixed_window"], value_col
        ].sum()
        material_burden_outside_frac = (
            material_burden_outside / total_burden if total_burden > 0 else np.nan
        )

        results.append({
            "season": season,
            "jurisdiction": jurisdiction,
            "peak_week": peak_week,
            "peak_value": peak_value,
            "material_weeks_total": material_weeks_total,
            "material_weeks_outside": material_weeks_outside,
            "material_burden_total": material_burden_total,
            "material_burden_outside": material_burden_outside,
            "material_burden_outside_frac": material_burden_outside_frac
        })

    df_result = pd.DataFrame(results)

    logger.info("=" * 50)
    logger.info(f"MATERIAL ACTIVITY ANALYSIS (threshold={threshold})")
    logger.info("=" * 50)
    logger.info(f"Median material weeks outside: {df_result['material_weeks_outside'].median():.1f}")
    logger.info(
        f"Median material burden outside fraction: "
        f"{df_result['material_burden_outside_frac'].median():.3f}"
    )

    return df_result


# ---------------------------------------------------------------------------
# Alternative fixed windows
# ---------------------------------------------------------------------------

def evaluate_extended_windows(
    df: pd.DataFrame,
    value_col: str = "rsv_pct"
) -> pd.DataFrame:
    """
    Evaluate coverage under different window definitions.

    Windows:
    - baseline_oct_mar: Oct 1 – Mar 31
    - early_sep_mar:    Sep 1 – Mar 31
    - late_oct_apr:     Oct 1 – Apr 30
    - extended_sep_apr: Sep 1 – Apr 30
    """
    windows = {
        "baseline_oct_mar": {"start_month": 10, "start_day": 1, "end_month": 3, "end_day": 31},
        "early_sep_mar":    {"start_month": 9,  "start_day": 1, "end_month": 3, "end_day": 31},
        "late_oct_apr":     {"start_month": 10, "start_day": 1, "end_month": 4, "end_day": 30},
        "extended_sep_apr": {"start_month": 9,  "start_day": 1, "end_month": 4, "end_day": 30},
    }

    df_valid = df[df[value_col].notna()].copy()
    results = []

    for (season, jurisdiction), group_df in df_valid.groupby(["season", "jurisdiction"]):
        years = season.split("-")
        start_year = int(years[0])
        end_year = int(years[1])
        total_burden = group_df[value_col].sum()

        for window_name, wc in windows.items():
            window_start = pd.Timestamp(year=start_year, month=wc["start_month"], day=wc["start_day"])
            window_end   = pd.Timestamp(year=end_year,   month=wc["end_month"],   day=wc["end_day"])

            in_window = (
                (group_df["week_end"] >= window_start) &
                (group_df["week_end"] <= window_end)
            )
            inside_burden = group_df.loc[in_window, value_col].sum()
            coverage = inside_burden / total_burden if total_burden > 0 else np.nan

            results.append({
                "window_name": window_name,
                "season": season,
                "jurisdiction": jurisdiction,
                "total_burden": total_burden,
                "inside_burden": inside_burden,
                "coverage": coverage,
                "missed_fraction": 1 - coverage if not np.isnan(coverage) else np.nan
            })

    df_result = pd.DataFrame(results)

    logger.info("=" * 50)
    logger.info("EXTENDED WINDOW EVALUATION")
    logger.info("=" * 50)
    for window_name in windows:
        subset = df_result[df_result["window_name"] == window_name]
        logger.info(
            f"  {window_name}: median coverage={subset['coverage'].median():.3f}, "
            f"median missed={subset['missed_fraction'].median():.3f}"
        )

    return df_result


# ---------------------------------------------------------------------------
# National summary
# ---------------------------------------------------------------------------

def compute_national_summary(
    df_outside: pd.DataFrame,
    weight_col: str = "total_burden"
) -> pd.DataFrame:
    """
    Compute population-weighted national summary of outside fractions.
    """
    results = []

    for season, group_df in df_outside.groupby("season"):
        valid = group_df[
            group_df["outside_fraction"].notna() &
            group_df[weight_col].notna() &
            (group_df[weight_col] > 0)
        ]
        if len(valid) == 0:
            continue

        unweighted = valid["outside_fraction"].mean()
        weights = valid[weight_col]
        weighted = (valid["outside_fraction"] * weights).sum() / weights.sum()
        total_burden = valid["total_burden"].sum()
        total_outside = valid["outside_burden"].sum()

        results.append({
            "season": season,
            "national_outside_fraction_unweighted": unweighted,
            "national_outside_fraction_weighted": weighted,
            "national_outside_burden_direct": (
                total_outside / total_burden if total_burden > 0 else np.nan
            ),
            "n_states": len(valid),
            "total_national_burden": total_burden,
            "total_national_outside": total_outside
        })

    df_result = pd.DataFrame(results)

    logger.info("=" * 50)
    logger.info("NATIONAL SUMMARY")
    logger.info("=" * 50)
    for _, row in df_result.iterrows():
        logger.info(
            f"  {row['season']}: weighted outside={row['national_outside_fraction_weighted']:.3f}, "
            f"n_states={row['n_states']}, total_burden={row['total_national_burden']:,.0f}"
        )

    return df_result


# ---------------------------------------------------------------------------
# Regional summary
# ---------------------------------------------------------------------------

def compute_regional_summary(
    df: pd.DataFrame,
    df_outside: pd.DataFrame
) -> pd.DataFrame:
    """
    Compute summary statistics by HHS region.
    """
    region_map = df[["jurisdiction", "hhs_region"]].drop_duplicates()
    df_merged = df_outside.merge(region_map, on="jurisdiction", how="left")

    results = []
    for (season, region), group_df in df_merged.groupby(["season", "hhs_region"]):
        if pd.isna(region):
            continue
        outside_fracs = group_df["outside_fraction"].dropna()
        if len(outside_fracs) == 0:
            continue
        results.append({
            "season": season,
            "hhs_region": int(region),
            "n_states": len(outside_fracs),
            "median_outside_fraction": outside_fracs.median(),
            "q25_outside_fraction": outside_fracs.quantile(0.25),
            "q75_outside_fraction": outside_fracs.quantile(0.75),
            "min_outside_fraction": outside_fracs.min(),
            "max_outside_fraction": outside_fracs.max()
        })

    return pd.DataFrame(results)


# ---------------------------------------------------------------------------
# Bootstrap confidence intervals
# ---------------------------------------------------------------------------

def compute_bootstrap_ci(
    df_outside: pd.DataFrame,
    df_extended: pd.DataFrame,
    n_replicates: int = 10000,
    seed: int = 42,
    age_group: str = "rsv_ped_0_4",
    datasource: str = "nhsn"
) -> pd.DataFrame:
    """
    Nonparametric bootstrap confidence intervals for national median statistics.

    For each season/datasource combination, resamples states with replacement
    (n = number of states) and computes median outside fraction.
    Uses 10,000 replicates; reports 95% percentile-based CIs.

    Returns DataFrame with columns:
        season, datasource, age_group, metric, point_estimate, ci_lower, ci_upper
    """
    rng = np.random.default_rng(seed)
    rows = []

    # --- Outside fraction medians ---
    for season, group in df_outside.groupby("season"):
        values = group["outside_fraction"].dropna().values
        n = len(values)
        if n < 3:
            continue

        point = np.median(values)
        boot = [np.median(rng.choice(values, size=n, replace=True))
                for _ in range(n_replicates)]
        ci_lo, ci_hi = np.percentile(boot, [2.5, 97.5])

        rows.append({
            "season": season,
            "datasource": datasource,
            "age_group": age_group,
            "metric": "median_outside_fraction",
            "point_estimate": point,
            "ci_lower": ci_lo,
            "ci_upper": ci_hi,
            "n_states": n
        })

    # --- Extended window coverage medians ---
    for (season, window_name), group in df_extended.groupby(["season", "window_name"]):
        values = group["coverage"].dropna().values
        n = len(values)
        if n < 3:
            continue

        point = np.median(values)
        boot = [np.median(rng.choice(values, size=n, replace=True))
                for _ in range(n_replicates)]
        ci_lo, ci_hi = np.percentile(boot, [2.5, 97.5])

        rows.append({
            "season": season,
            "datasource": datasource,
            "age_group": age_group,
            "metric": f"median_coverage_{window_name}",
            "point_estimate": point,
            "ci_lower": ci_lo,
            "ci_upper": ci_hi,
            "n_states": n
        })

    df_ci = pd.DataFrame(rows)

    logger.info(f"Bootstrap CI computed: {len(df_ci)} rows ({n_replicates:,} replicates each)")

    return df_ci


# ---------------------------------------------------------------------------
# Longitudinal consistency
# ---------------------------------------------------------------------------

def compute_longitudinal_consistency(
    df_outside: pd.DataFrame
) -> pd.DataFrame:
    """
    Compute year-over-year consistency of outside fractions at the state level.

    For each jurisdiction:
    - Coefficient of variation (CV) across all available seasons
    - Spearman rank correlation between each pair of consecutive seasons

    Returns DataFrame with columns:
        jurisdiction, cv_outside_fraction,
        rank_corr_2324_vs_2425, rank_corr_2425_vs_2526,
        n_seasons_available
    """
    from scipy import stats as sp_stats

    # Pivot to wide format: rows = jurisdiction, columns = season
    pivot = df_outside.pivot_table(
        index="jurisdiction",
        columns="season",
        values="outside_fraction"
    )

    results = []

    for jur, row in pivot.iterrows():
        vals = row.dropna()
        n_seasons = len(vals)

        # CV across available seasons
        if n_seasons >= 2 and vals.mean() > 0:
            cv = vals.std() / vals.mean()
        else:
            cv = np.nan

        # Spearman rank correlations between consecutive season pairs
        # We need the full cross-jurisdiction vector for each pair
        results.append({
            "jurisdiction": jur,
            "n_seasons_available": n_seasons,
            "cv_outside_fraction": cv,
            # Season values stored for later cross-jurisdiction correlation
            "outside_fraction_2324": row.get("2023-2024", np.nan),
            "outside_fraction_2425": row.get("2024-2025", np.nan),
            "outside_fraction_2526": row.get("2025-2026", np.nan),
        })

    df_jur = pd.DataFrame(results)

    # Compute Spearman correlations across all jurisdictions
    seasons_available = df_outside["season"].unique()
    corr_cols = {}

    pair_labels = [
        ("2023-2024", "2024-2025", "rank_corr_2324_vs_2425"),
        ("2024-2025", "2025-2026", "rank_corr_2425_vs_2526"),
    ]
    for s1, s2, col in pair_labels:
        if s1 in seasons_available and s2 in seasons_available:
            merged = (
                df_outside[df_outside["season"] == s1][["jurisdiction", "outside_fraction"]]
                .rename(columns={"outside_fraction": "v1"})
                .merge(
                    df_outside[df_outside["season"] == s2][["jurisdiction", "outside_fraction"]]
                    .rename(columns={"outside_fraction": "v2"}),
                    on="jurisdiction"
                )
                .dropna()
            )
            if len(merged) >= 3:
                rho, _ = sp_stats.spearmanr(merged["v1"], merged["v2"])
                corr_cols[col] = rho
                logger.info(f"Spearman {s1} vs {s2}: rho={rho:.3f} (n={len(merged)})")
            else:
                corr_cols[col] = np.nan
        else:
            corr_cols[col] = np.nan

    # Attach correlation columns to all rows (same scalar for each jurisdiction)
    for col, val in corr_cols.items():
        df_jur[col] = val

    logger.info("=" * 50)
    logger.info("LONGITUDINAL CONSISTENCY")
    logger.info("=" * 50)
    logger.info(f"Jurisdictions assessed: {len(df_jur)}")
    logger.info(f"Median CV: {df_jur['cv_outside_fraction'].median():.3f}")

    return df_jur


# ---------------------------------------------------------------------------
# Full run
# ---------------------------------------------------------------------------

def run_burden_analysis(
    df: pd.DataFrame,
    value_col: str = None,
    datasource: str = "nssp",
    age_group_label: str = None,
    run_bootstrap: bool = True,
    run_longitudinal: bool = True
) -> dict:
    """
    Run all burden analyses for a given processed DataFrame and outcome column.

    Args:
        df: Processed DataFrame from build_seasons
        value_col: Column containing RSV metric (default: from config)
        datasource: Label for output tables ("nssp" or "nhsn")
        age_group_label: NHSN age stratum label (e.g. "rsv_ped_0_4")
        run_bootstrap: Whether to compute bootstrap CIs (slow, ~10s per call)
        run_longitudinal: Whether to compute longitudinal consistency

    Returns:
        Dictionary with all analysis results
    """
    config = load_config()
    smoothing = config["analysis"]["smoothing_window"]
    threshold = config["analysis"]["material_activity_threshold"]
    n_bootstrap = config["analysis"].get("bootstrap_replicates", 10000)
    bootstrap_seed = config["analysis"].get("bootstrap_seed", 42)

    if value_col is None:
        value_col = config.get("primary_outcome", "rsv_pct")

    if age_group_label is None:
        age_group_label = value_col

    logger.info("\n" + "=" * 60)
    logger.info("RUNNING BURDEN ANALYSIS")
    logger.info(f"Datasource: {datasource} | Outcome: {value_col}")
    logger.info("=" * 60 + "\n")

    outside_fraction = compute_outside_fraction(df, value_col=value_col)
    material_activity = compute_material_activity(df, value_col=value_col,
                                                   smoothing=smoothing, threshold=threshold)
    extended_windows = evaluate_extended_windows(df, value_col=value_col)
    national_summary = compute_national_summary(outside_fraction)
    regional_summary = compute_regional_summary(df, outside_fraction)

    results = {
        "outside_fraction": outside_fraction,
        "material_activity": material_activity,
        "extended_windows": extended_windows,
        "national_summary": national_summary,
        "regional_summary": regional_summary,
        "bootstrap_ci": None,
        "longitudinal": None,
    }

    if run_bootstrap:
        logger.info(f"\nComputing bootstrap CIs ({n_bootstrap:,} replicates)...")
        results["bootstrap_ci"] = compute_bootstrap_ci(
            outside_fraction,
            extended_windows,
            n_replicates=n_bootstrap,
            seed=bootstrap_seed,
            age_group=age_group_label,
            datasource=datasource
        )

    if run_longitudinal:
        logger.info("\nComputing longitudinal consistency...")
        results["longitudinal"] = compute_longitudinal_consistency(outside_fraction)

    return results


def main():
    """Main entry point for standalone burden analysis."""
    from src.build_seasons import build_seasons
    from src.pull_nssp import load_cached_or_fetch

    df_raw = load_cached_or_fetch()
    df = build_seasons(df_raw)
    results = run_burden_analysis(df)

    national = results["national_summary"]
    for _, row in national.iterrows():
        print(f"\n{row['season']}:")
        print(f"  Weighted outside fraction: {row['national_outside_fraction_weighted']:.1%}")

    return results


if __name__ == "__main__":
    main()
