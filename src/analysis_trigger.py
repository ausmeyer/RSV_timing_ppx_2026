"""
Trigger-based RSV season labeling and prophylaxis-window evaluation.

Default method: a simple prospective anomaly rule based only on each
state-season healthcare time series:
  - baseline: first valid preseason weeks in the observed series
  - onset: sustained smoothed activity above a robust baseline threshold, with
    current-week activity also above a small absolute floor
  - peak: running maximum trailing-smoothed value after onset
  - offset: sustained post-peak low activity, with a hard spring cap once reached
"""

import logging
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import yaml

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Project root directory
PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"


def load_config() -> dict:
    """Load configuration from config.yaml."""
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def _min_activity_value(values: pd.Series, baseline_median: float) -> float:
    """
    Pick a small absolute floor that works for NSSP percentages and NHSN counts.

    NSSP values are percentages generally below 10. NHSN values are weekly
    admission counts and can be much larger.
    """
    if values.dropna().quantile(0.95) < 10 and baseline_median < 10:
        return load_config()["trigger"].get("onset_min_abs_percent", 0.10)
    return load_config()["trigger"].get("onset_min_abs_count", 3.0)


def _season_cap(season: str) -> pd.Timestamp:
    config = load_config()
    trig = config["trigger"]
    end_year = int(season.split("-")[1])
    return pd.Timestamp(
        year=end_year,
        month=trig.get("latest_end_month", 5),
        day=trig.get("latest_end_day", 31)
    )


def _empty_label(reason: str, onset_threshold: float = np.nan) -> dict:
    return {
        "onset_week": None,
        "peak_week": None,
        "offset_week": None,
        "label_value_col": None,
        "onset_threshold": onset_threshold,
        "offset_threshold": np.nan,
        "peak_value": np.nan,
        "offset_reason": reason
    }


def label_season_peak_fraction(
    df_state_season: pd.DataFrame,
    label_col: str = "rsv_0to4",
    smoothing: int = 3,
    consecutive_weeks: int = 2,
    peak_fraction: float = 0.20,
    offset_min_weeks_after_peak: int = 2
) -> dict:
    """
    Label RSV season using a peak-relative material activity rule.

    This is a retrospective state-season label: start is the first sustained
    period at or above a fixed fraction of that state-season's peak, and end is
    the first sustained post-peak period below that same level. It avoids the
    fragile preseason-baseline assumption when early-season NHSN values are
    missing or already elevated.
    """
    df = (
        df_state_season
        .sort_values("week_end")
        .loc[:, ["season", "week_end", label_col]]
        .dropna(subset=[label_col])
        .copy()
    )

    if len(df) < consecutive_weeks + 1:
        return _empty_label("insufficient_data")

    season = df["season"].iloc[0]
    cap = min(_season_cap(season), df["week_end"].max())

    df["smoothed"] = (
        df[label_col]
        .rolling(window=smoothing, min_periods=1, center=False)
        .mean()
    )

    peak_idx = df["smoothed"].idxmax()
    peak_week = pd.Timestamp(df.loc[peak_idx, "week_end"])
    peak_value = df.loc[peak_idx, "smoothed"]
    if not np.isfinite(peak_value) or peak_value <= 0:
        return _empty_label("no_activity")

    activity_threshold = peak_fraction * peak_value
    df["is_material"] = df["smoothed"] >= activity_threshold

    onset_week = None
    weeks = df["week_end"].values
    material = df["is_material"].values
    for i in range(len(material) - consecutive_weeks + 1):
        if all(material[i:i + consecutive_weeks]):
            onset_week = pd.Timestamp(weeks[i])
            break

    if onset_week is None:
        return _empty_label("no_onset", onset_threshold=activity_threshold)

    earliest_offset = peak_week + pd.Timedelta(weeks=offset_min_weeks_after_peak)
    after_peak = df[df["week_end"] >= earliest_offset].copy()
    after_peak["is_low"] = after_peak["smoothed"] < activity_threshold

    offset_week = None
    offset_reason = "low_activity"
    low = after_peak["is_low"].values
    low_weeks = after_peak["week_end"].values
    for i in range(len(low) - consecutive_weeks + 1):
        if all(low[i:i + consecutive_weeks]):
            offset_week = pd.Timestamp(low_weeks[i])
            break

    if offset_week is None or offset_week > cap:
        offset_week = cap
        offset_reason = "spring_cap"

    if offset_week < onset_week:
        offset_week = onset_week
        offset_reason = "onset_floor"

    return {
        "onset_week": onset_week,
        "peak_week": peak_week,
        "offset_week": offset_week,
        "label_value_col": label_col,
        "onset_threshold": activity_threshold,
        "offset_threshold": activity_threshold,
        "peak_value": peak_value,
        "offset_reason": offset_reason
    }


def label_season_anomaly(
    df_state_season: pd.DataFrame,
    label_col: str = "rsv_0to4",
    smoothing: int = 3,
    consecutive_weeks: int = 2,
    baseline_weeks: int = 8,
    onset_z_threshold: float = 3.0,
    offset_peak_fraction: float = 0.20,
    offset_min_weeks_after_peak: int = 2
) -> dict:
    """
    Label onset, peak, and offset using an online robust anomaly detector.

    The scan proceeds week by week. Start is assigned only when the current week
    completes a sustained run above the preseason baseline threshold. End is
    assigned only when the current week completes a sustained post-peak low
    activity run, using the running peak observed so far. No final season peak or
    future values are used.
    """
    df = (
        df_state_season
        .sort_values("week_end")
        .loc[:, ["season", "week_end", label_col]]
        .dropna(subset=[label_col])
        .copy()
    )

    if len(df) < baseline_weeks + consecutive_weeks + 1:
        return _empty_label("insufficient_data")

    season = df["season"].iloc[0]
    cap = _season_cap(season)

    df["smoothed"] = (
        df[label_col]
        .rolling(window=smoothing, min_periods=1, center=False)
        .mean()
    )

    baseline = df["smoothed"].head(baseline_weeks)
    baseline_median = baseline.median()
    mad = (baseline - baseline_median).abs().median()
    robust_sd = 1.4826 * mad
    if not np.isfinite(robust_sd) or robust_sd == 0:
        robust_sd = baseline.std(ddof=0)
    if not np.isfinite(robust_sd):
        robust_sd = 0.0

    min_value = _min_activity_value(df[label_col], baseline_median)
    onset_threshold = max(
        baseline_median + onset_z_threshold * robust_sd,
        min_value
    )

    onset_week = None
    offset_week = None
    peak_week = None
    peak_value = np.nan
    onset_run = 0
    low_run = 0
    offset_reason = "low_activity"
    offset_threshold = np.nan

    # Begin scanning after the baseline period is available. Each decision uses
    # only data through the current row.
    for _, row in df.iloc[baseline_weeks:].iterrows():
        week = pd.Timestamp(row["week_end"])
        value = row["smoothed"]
        current_value = row[label_col]

        if onset_week is None:
            is_onset_week = value >= onset_threshold and current_value >= min_value
            onset_run = onset_run + 1 if is_onset_week else 0
            if onset_run >= consecutive_weeks:
                # Operational start: the week when the sustained rule is met.
                onset_week = week
                peak_week = week
                peak_value = value
            continue

        if value > peak_value:
            peak_value = value
            peak_week = week
            low_run = 0

        offset_threshold = max(offset_peak_fraction * peak_value, onset_threshold)
        far_enough_after_peak = week >= peak_week + pd.Timedelta(weeks=offset_min_weeks_after_peak)
        if far_enough_after_peak and value <= offset_threshold:
            low_run += 1
        else:
            low_run = 0

        if low_run >= consecutive_weeks:
            # Operational end: the week when the sustained low-activity rule is met.
            offset_week = week
            break

        if week >= cap:
            offset_week = week
            offset_reason = "spring_cap"
            break

    if onset_week is None:
        return _empty_label("no_onset", onset_threshold=onset_threshold)

    if offset_week is None:
        if df["week_end"].max() >= cap:
            offset_week = cap
            offset_reason = "spring_cap"
        else:
            offset_reason = "ongoing"

    return {
        "onset_week": onset_week,
        "peak_week": peak_week,
        "offset_week": offset_week,
        "label_value_col": label_col,
        "onset_threshold": onset_threshold,
        "offset_threshold": offset_threshold,
        "peak_value": peak_value,
        "offset_reason": offset_reason
    }


def detect_onset_growth(
    df_state_season: pd.DataFrame,
    value_col: str = "rsv_0to4",
    smoothing: int = 3,
    consecutive_weeks: int = 2,
    baseline_weeks: int = 4
) -> Optional[pd.Timestamp]:
    """
    Detect RSV season onset using growth rate method (more sensitive).

    Onset = first week where smoothed values show sustained week-over-week
    growth (>10% increase) for N consecutive weeks, AND values are
    meaningfully above baseline.

    This method detects the early upswing of the epidemic curve rather than
    waiting for an absolute threshold to be crossed.

    Args:
        df_state_season: DataFrame for a single state-season
        value_col: Column containing RSV values
        smoothing: Rolling window size for smoothing
        consecutive_weeks: Required consecutive weeks of growth
        baseline_weeks: Number of initial weeks to compute baseline

    Returns:
        Onset week (Timestamp) or None if no clear onset detected
    """
    # Sort by week
    df = df_state_season.sort_values("week_end").copy()

    # Filter to valid values
    df = df[df[value_col].notna()]

    if len(df) < baseline_weeks + consecutive_weeks + 1:
        return None

    # Apply smoothing
    df["smoothed"] = (
        df[value_col]
        .rolling(window=smoothing, min_periods=1, center=False)
        .mean()
    )

    # Compute baseline from first few weeks
    baseline_values = df["smoothed"].head(baseline_weeks)
    baseline_median = baseline_values.median()
    baseline_std = baseline_values.std() if len(baseline_values) > 1 else 0

    # Minimum value threshold to avoid triggering on noise
    is_percent_data = baseline_median < 10
    min_value = 0.08 if is_percent_data else 2.0

    # Threshold for "meaningfully above baseline"
    # Lower bar than old method: baseline + 1 std OR 30% above baseline
    if baseline_median > 0.01:
        above_baseline_threshold = max(
            baseline_median + baseline_std,
            baseline_median * 1.3,
            min_value
        )
    else:
        above_baseline_threshold = min_value

    # Compute week-over-week growth rate
    df["prev_smoothed"] = df["smoothed"].shift(1)
    df["growth_rate"] = df["smoothed"] / df["prev_smoothed"].replace(0, np.nan)
    df["growth_rate"] = df["growth_rate"].replace([np.inf, -np.inf], np.nan)

    # "Growing" = >10% week-over-week increase AND above minimum value
    growth_threshold = 1.10
    df["is_growing"] = (
        (df["growth_rate"] > growth_threshold) &
        (df["smoothed"] >= min_value)
    )

    # Also track when above baseline threshold
    df["above_baseline"] = df["smoothed"] >= above_baseline_threshold

    weeks = df["week_end"].values
    growing = df["is_growing"].values
    above_bl = df["above_baseline"].values
    growth_rates = df["growth_rate"].fillna(1.0).values

    for i in range(len(growing) - consecutive_weeks + 1):
        # Primary criterion: sustained >10% growth
        if all(growing[i:i + consecutive_weeks]):
            return pd.Timestamp(weeks[i])

        # Secondary criterion: above baseline with any positive growth
        if all(above_bl[i:i + consecutive_weeks]):
            rates_slice = growth_rates[i:i + consecutive_weeks]
            if all(r >= 1.0 for r in rates_slice):
                return pd.Timestamp(weeks[i])

    return None


def detect_onset_threshold(
    df_state_season: pd.DataFrame,
    value_col: str = "rsv_0to4",
    smoothing: int = 3,
    consecutive_weeks: int = 2,
    baseline_weeks: int = 4
) -> Optional[pd.Timestamp]:
    """
    Wrapper that uses growth-based detection (more sensitive).
    Kept for backwards compatibility.
    """
    return detect_onset_growth(
        df_state_season, value_col, smoothing, consecutive_weeks, baseline_weeks
    )


def detect_offset_baseline(
    df_state_season: pd.DataFrame,
    value_col: str = "rsv_0to4",
    smoothing: int = 3,
    consecutive_weeks: int = 2,
    baseline_weeks: int = 4,
    onset_week: Optional[pd.Timestamp] = None
) -> Optional[pd.Timestamp]:
    """
    Detect RSV season offset (end) - CONSERVATIVE approach.

    Offset = first week AFTER the peak where smoothed values have returned
    to near-baseline levels for N consecutive weeks. This is conservative
    because it waits until the season is truly over, not just declining.

    Args:
        df_state_season: DataFrame for a single state-season
        value_col: Column containing RSV values
        smoothing: Rolling window size for smoothing
        consecutive_weeks: Required consecutive weeks at baseline
        baseline_weeks: Number of initial weeks to compute baseline
        onset_week: Optional detected onset week (offset must be after this)

    Returns:
        Offset week (Timestamp) or None if no clear offset detected
    """
    # Sort by week
    df = df_state_season.sort_values("week_end").copy()

    # Filter to valid values
    df = df[df[value_col].notna()]

    if len(df) < baseline_weeks + consecutive_weeks + 1:
        return None

    # Apply smoothing
    df["smoothed"] = (
        df[value_col]
        .rolling(window=smoothing, min_periods=1, center=False)
        .mean()
    )

    # Compute baseline from first few weeks (pre-season)
    baseline_values = df["smoothed"].head(baseline_weeks)
    baseline_median = baseline_values.median()
    baseline_std = baseline_values.std() if len(baseline_values) > 1 else 0

    # "Returned to baseline" threshold - conservative, allow some margin above baseline
    # Use 3x baseline or baseline + 3*std to ensure season is truly over
    is_percent_data = baseline_median < 10
    min_value = 0.15 if is_percent_data else 5.0

    baseline_threshold = max(
        baseline_median + 3 * baseline_std,
        baseline_median * 3,
        min_value
    )

    # Find the peak week
    peak_idx = df["smoothed"].idxmax()
    peak_week = df.loc[peak_idx, "week_end"]
    peak_value = df.loc[peak_idx, "smoothed"]

    # If onset provided, peak must be after onset
    if onset_week is not None:
        df_after_onset = df[df["week_end"] >= onset_week]
        if len(df_after_onset) > 0:
            peak_idx = df_after_onset["smoothed"].idxmax()
            peak_week = df.loc[peak_idx, "week_end"]
            peak_value = df.loc[peak_idx, "smoothed"]

    # Look for offset after the peak
    df_after_peak = df[df["week_end"] > peak_week].copy()

    if len(df_after_peak) < consecutive_weeks:
        return None

    # Track when values have returned to baseline level
    df_after_peak["at_baseline"] = df_after_peak["smoothed"] <= baseline_threshold

    weeks = df_after_peak["week_end"].values
    at_baseline = df_after_peak["at_baseline"].values

    # Find first week where values are at baseline for N consecutive weeks
    for i in range(len(at_baseline) - consecutive_weeks + 1):
        if all(at_baseline[i:i + consecutive_weeks]):
            return pd.Timestamp(weeks[i])

    return None


def detect_offset_threshold(
    df_state_season: pd.DataFrame,
    value_col: str = "rsv_0to4",
    smoothing: int = 3,
    consecutive_weeks: int = 2,
    baseline_weeks: int = 4,
    onset_week: Optional[pd.Timestamp] = None
) -> Optional[pd.Timestamp]:
    """
    Wrapper that uses baseline-based detection (conservative - waits for season end).
    Kept for backwards compatibility.
    """
    return detect_offset_baseline(
        df_state_season, value_col, smoothing, consecutive_weeks, baseline_weeks, onset_week
    )


def build_trigger_window(
    onset_week: pd.Timestamp,
    lead_weeks: int = 2,
    duration_weeks: int = 24
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """
    Build prophylaxis window based on detected onset.

    Args:
        onset_week: Detected onset week
        lead_weeks: Start window this many weeks before onset
        duration_weeks: Total window duration

    Returns:
        Tuple of (window_start, window_end) as Timestamps
    """
    window_start = onset_week - pd.Timedelta(weeks=lead_weeks)
    window_end = window_start + pd.Timedelta(weeks=duration_weeks)

    return window_start, window_end


def evaluate_trigger_coverage(
    df: pd.DataFrame,
    onset_results: dict[tuple[str, str], Optional[pd.Timestamp]],
    offset_results: dict[tuple[str, str], Optional[pd.Timestamp]],
    season_labels: Optional[dict[tuple[str, str], dict]] = None,
    value_col: str = "rsv_0to4",
    lead_weeks: int = 2
) -> pd.DataFrame:
    """
    Evaluate coverage of trigger-based windows vs fixed windows.

    Uses detected onset and offset to define the trigger window, rather than
    a fixed duration. This captures the actual RSV season.

    Args:
        df: Processed DataFrame
        onset_results: Dictionary mapping (season, jurisdiction) to onset week
        offset_results: Dictionary mapping (season, jurisdiction) to offset week
        value_col: Column containing RSV admissions
        lead_weeks: Start window this many weeks before onset

    Returns:
        DataFrame with columns:
        - season, jurisdiction
        - onset_week, offset_week: detected season bounds
        - trigger_start, trigger_end: trigger window bounds
        - fixed_coverage: fraction of burden in Oct-Mar
        - trigger_coverage: fraction of burden in trigger window
        - improvement: trigger_coverage - fixed_coverage
        - trigger_better_by_5pct: improvement >= 0.05
    """
    df_valid = df[df[value_col].notna()].copy()

    results = []

    for (season, jurisdiction), group_df in df_valid.groupby(["season", "jurisdiction"]):
        total_burden = group_df[value_col].sum()

        if total_burden == 0:
            continue

        # Fixed window coverage
        fixed_inside = group_df.loc[group_df["in_fixed_window"], value_col].sum()
        fixed_coverage = fixed_inside / total_burden

        # Trigger window coverage - use detected onset and offset
        onset_week = onset_results.get((season, jurisdiction))
        offset_week = offset_results.get((season, jurisdiction))
        label = season_labels.get((season, jurisdiction), {}) if season_labels else {}

        if onset_week is not None and offset_week is not None:
            # Start window lead_weeks before onset, end at detected offset
            trigger_start = onset_week - pd.Timedelta(weeks=lead_weeks)
            trigger_end = offset_week

            in_trigger = (
                (group_df["week_end"] >= trigger_start) &
                (group_df["week_end"] <= trigger_end)
            )
            trigger_inside = group_df.loc[in_trigger, value_col].sum()
            trigger_coverage = trigger_inside / total_burden
        else:
            trigger_start = None
            trigger_end = None
            trigger_coverage = np.nan

        improvement = trigger_coverage - fixed_coverage if not np.isnan(trigger_coverage) else np.nan

        results.append({
            "season": season,
            "jurisdiction": jurisdiction,
            "onset_week": onset_week,
            "peak_week": label.get("peak_week"),
            "offset_week": offset_week,
            "trigger_start": trigger_start,
            "trigger_end": trigger_end,
            "trigger_duration_weeks": (
                (trigger_end - trigger_start).days / 7
                if trigger_start is not None and trigger_end is not None else np.nan
            ),
            "label_value_col": label.get("label_value_col"),
            "coverage_value_col": value_col,
            "onset_threshold": label.get("onset_threshold", np.nan),
            "offset_threshold": label.get("offset_threshold", np.nan),
            "peak_value": label.get("peak_value", np.nan),
            "offset_reason": label.get("offset_reason"),
            "total_burden": total_burden,
            "fixed_coverage": fixed_coverage,
            "trigger_coverage": trigger_coverage,
            "improvement": improvement,
            "trigger_better_by_5pct": improvement >= 0.05 if not np.isnan(improvement) else False
        })

    df_result = pd.DataFrame(results)

    # Log summary
    logger.info("=" * 50)
    logger.info("TRIGGER COVERAGE EVALUATION")
    logger.info("=" * 50)

    valid_results = df_result[df_result["trigger_coverage"].notna()]
    logger.info(f"State-seasons with detected onset: {len(valid_results)}/{len(df_result)}")

    if len(valid_results) > 0:
        logger.info(f"Median fixed coverage: {valid_results['fixed_coverage'].median():.3f}")
        logger.info(f"Median trigger coverage: {valid_results['trigger_coverage'].median():.3f}")
        logger.info(f"Median improvement: {valid_results['improvement'].median():.3f}")

        better_5pct = valid_results["trigger_better_by_5pct"].sum()
        pct_better = 100 * better_5pct / len(valid_results)
        logger.info(f"State-seasons where trigger improves by >=5%: {better_5pct} ({pct_better:.1f}%)")

    return df_result


def run_trigger_analysis(
    df: pd.DataFrame,
    value_col: str = None,
    label_value_col: str = None
) -> dict:
    """
    Run full trigger-based analysis.

    Args:
        df: Processed DataFrame from build_seasons
        value_col: Column containing RSV admissions or percentages for coverage
            evaluation (default: from config)
        label_value_col: Column used to label onset/peak/offset. If omitted,
            labels are learned from value_col.

    Returns:
        Dictionary with:
        - onset_results: mapping of (season, jurisdiction) to onset week
        - trigger_coverage: coverage comparison DataFrame
    """
    config = load_config()
    trigger_config = config["trigger"]
    smoothing = config["analysis"]["smoothing_window"]

    method = trigger_config.get("method", "anomaly")
    consecutive_weeks = trigger_config["consecutive_weeks"]
    lead_weeks = trigger_config["lead_weeks"]
    baseline_weeks = trigger_config.get("baseline_weeks", 8)

    # Use primary outcome from config if not specified
    if value_col is None:
        value_col = config.get("primary_outcome", "rsv_ped_total")
    if label_value_col is None:
        label_value_col = value_col

    logger.info("\n" + "=" * 60)
    logger.info("RUNNING TRIGGER ANALYSIS")
    logger.info(f"Using coverage outcome variable: {value_col}")
    logger.info(f"Using labeling signal variable: {label_value_col}")
    logger.info(f"Trigger method: {method}")
    logger.info("=" * 60 + "\n")

    # Detect onset and offset for each state-season
    onset_results = {}
    offset_results = {}
    season_labels = {}
    onset_count = 0
    offset_count = 0
    peak_count = 0

    for (season, jurisdiction), group_df in df.groupby(["season", "jurisdiction"]):
        if method == "peak_fraction":
            label = label_season_peak_fraction(
                group_df,
                label_col=label_value_col,
                smoothing=smoothing,
                consecutive_weeks=consecutive_weeks,
                peak_fraction=trigger_config.get("peak_fraction", 0.20),
                offset_min_weeks_after_peak=trigger_config.get("offset_min_weeks_after_peak", 2)
            )
            onset = label["onset_week"]
            offset = label["offset_week"]
        elif method == "anomaly":
            label = label_season_anomaly(
                group_df,
                label_col=label_value_col,
                smoothing=smoothing,
                consecutive_weeks=consecutive_weeks,
                baseline_weeks=baseline_weeks,
                onset_z_threshold=trigger_config.get("onset_z_threshold", 3.0),
                offset_peak_fraction=trigger_config.get("offset_peak_fraction", 0.20),
                offset_min_weeks_after_peak=trigger_config.get("offset_min_weeks_after_peak", 2)
            )
            onset = label["onset_week"]
            offset = label["offset_week"]
        else:
            onset = detect_onset_threshold(
                group_df,
                value_col=label_value_col,
                smoothing=smoothing,
                consecutive_weeks=consecutive_weeks,
                baseline_weeks=baseline_weeks
            )
            if onset is not None:
                offset = detect_offset_threshold(
                    group_df,
                    value_col=label_value_col,
                    smoothing=smoothing,
                    consecutive_weeks=consecutive_weeks,
                    baseline_weeks=baseline_weeks,
                    onset_week=onset
                )
            else:
                offset = None
            label = {
                "onset_week": onset,
                "peak_week": None,
                "offset_week": offset,
                "onset_threshold": np.nan,
                "offset_threshold": np.nan,
                "peak_value": np.nan,
                "offset_reason": "legacy"
            }

        onset_results[(season, jurisdiction)] = onset
        offset_results[(season, jurisdiction)] = offset
        season_labels[(season, jurisdiction)] = label

        if onset is not None:
            onset_count += 1
        if label.get("peak_week") is not None:
            peak_count += 1
        if offset is not None:
            offset_count += 1

    total = len(onset_results)
    logger.info(f"Onset detection: {onset_count}/{total} state-seasons ({100*onset_count/total:.1f}%)")
    logger.info(f"Peak labeling: {peak_count}/{total} state-seasons ({100*peak_count/total:.1f}%)")
    logger.info(f"Offset detection: {offset_count}/{total} state-seasons ({100*offset_count/total:.1f}%)")

    # Evaluate coverage using detected onset and offset
    trigger_coverage = evaluate_trigger_coverage(
        df,
        onset_results,
        offset_results,
        season_labels=season_labels,
        value_col=value_col,
        lead_weeks=lead_weeks
    )

    return {
        "onset_results": onset_results,
        "offset_results": offset_results,
        "season_labels": season_labels,
        "label_value_col": label_value_col,
        "coverage_value_col": value_col,
        "trigger_coverage": trigger_coverage
    }


def summarize_trigger_by_season(df_trigger: pd.DataFrame) -> pd.DataFrame:
    """
    Summarize trigger analysis results by season.

    Args:
        df_trigger: Output from evaluate_trigger_coverage

    Returns:
        Summary DataFrame by season
    """
    results = []

    for season, group_df in df_trigger.groupby("season"):
        valid = group_df[group_df["trigger_coverage"].notna()]

        if len(valid) == 0:
            continue

        results.append({
            "season": season,
            "n_states": len(group_df),
            "n_onset_detected": len(valid),
            "median_trigger_duration_weeks": valid["trigger_duration_weeks"].median(),
            "median_fixed_coverage": valid["fixed_coverage"].median(),
            "median_trigger_coverage": valid["trigger_coverage"].median(),
            "median_improvement": valid["improvement"].median(),
            "mean_improvement": valid["improvement"].mean(),
            "n_trigger_better_5pct": valid["trigger_better_by_5pct"].sum(),
            "pct_trigger_better_5pct": 100 * valid["trigger_better_by_5pct"].mean()
        })

    return pd.DataFrame(results)


def main():
    """Main entry point for trigger analysis."""
    from src.build_seasons import build_seasons
    from src.pull_nssp import load_cached_or_fetch

    logger.info("Loading and processing data...")
    df_raw = load_cached_or_fetch()
    df = build_seasons(df_raw)

    logger.info("Running trigger analysis...")
    results = run_trigger_analysis(df)

    # Print key findings
    print("\n" + "=" * 60)
    print("KEY FINDINGS - TRIGGER ANALYSIS")
    print("=" * 60)

    summary = summarize_trigger_by_season(results["trigger_coverage"])
    for _, row in summary.iterrows():
        print(f"\n{row['season']}:")
        print(f"  Onset detected: {row['n_onset_detected']}/{row['n_states']} states")
        print(f"  Median fixed coverage: {row['median_fixed_coverage']:.1%}")
        print(f"  Median trigger coverage: {row['median_trigger_coverage']:.1%}")
        print(f"  Median improvement: {row['median_improvement']:.1%}")
        print(f"  States where trigger better by >=5%: {row['n_trigger_better_5pct']:.0f} ({row['pct_trigger_better_5pct']:.1f}%)")

    return results


if __name__ == "__main__":
    main()
