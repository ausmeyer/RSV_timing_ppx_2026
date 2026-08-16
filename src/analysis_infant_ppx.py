"""
Infant RSV prophylaxis protection model.

This module estimates how much of each infant cohort's RSV exposure would occur
while protected under recurring fixed prophylaxis windows.

Model intent:
- Explainable, visit-opportunity based mechanics.
- State-season specific epidemic curves from NSSP or NHSN.
- Daily birth cohorts with uniform births.
- Protection assigned only at routine outpatient well-child visit opportunities
  during the prophylaxis window.
"""

from __future__ import annotations

import calendar
import logging
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import yaml

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"

WINDOWS = {
    "baseline_oct_mar": {"start_month": 10, "start_day": 1, "end_month": 3, "end_day": 31},
    "early_sep_mar": {"start_month": 9, "start_day": 1, "end_month": 3, "end_day": 31},
    "late_oct_apr": {"start_month": 10, "start_day": 1, "end_month": 4, "end_day": 30},
    # Year-round administration (dosing at any time of year). NOTE: this entry is
    # load-bearing beyond year-round itself. Its July 1 start is the earliest window
    # start and therefore anchors the daily birth-cohort grid for ALL windows (see
    # `earliest_window_start` in _cohort_rows_for_group); do not remove it. The
    # single-season protection it produces for the year_round window is replaced with
    # the steady-state value in run_infant_ppx_analysis (see
    # year_round_steady_state_protection), because a continuously running program must
    # be evaluated at steady state rather than as one modeled season.
    "year_round": {"start_month": 7, "start_day": 1, "end_month": 6, "end_day": 30},
}

WINDOW_LABELS = {
    "baseline_oct_mar": "Baseline Oct-Mar",
    "early_sep_mar": "Early Sep-Mar",
    "late_oct_apr": "Late Oct-Apr",
    "year_round": "Year-round",
}

PARAMETER_SOURCE_ROWS = {
    "uptake": (
        "The primary model uses 18.5% empirical 2023-24 nirsevimab uptake from "
        "Boundy et al. MMWR 2025 as seasonal coverage among previously untreated "
        "infants with an eligible opportunity. Recipients receive prophylaxis at "
        "their first eligible visit in that annual window."
    ),
    "eligibility_max_age_months": (
        "CDC/ACIP infant RSV antibody guidance recommends protection for eligible "
        "infants younger than 8 months who are born during or entering their first "
        "RSV season."
    ),
    "exposure_censor_age_months": (
        "Analysis target is first-year infant protection. CDC and Moline et al. "
        "JAMA Pediatrics 2026 identify the highest RSV burden and prevention "
        "impact in infants, especially ages 0-11 months and 0-2 months."
    ),
    "protection_delay_days": (
        "DailyMed Beyfortus label: median nirsevimab time to maximum concentration "
        "is 6 days."
    ),
    "protection_duration_days": (
        "CDC and the Beyfortus label state protection extends through at least "
        "5 months; pivotal efficacy endpoints were evaluated through 150 days. "
        "The primary model uses the published effectiveness curve through 210 days."
    ),
    "efficacy_profile": (
        "The primary piecewise-linear profile uses a smoothed Moline et al. "
        "JAMA Pediatrics 2026 time-since-dose hospitalization effectiveness curve."
    ),
    "efficacy_curve_points": (
        "Scenario curve. Day 6 uses the Moline et al. JAMA Pediatrics 2026 "
        "<30-day hospitalization effectiveness bin after the Beyfortus PK delay; "
        "day 45 uses the midpoint of the 30-59 day bin; day 210 uses the end of "
        "the observed 130-210 day bin. The curve smooths over non-monotone "
        "intermediate bins rather than forcing the 90-129 day point estimate "
        "below the later 130-210 day estimate."
    ),
    "first_outpatient_visit_days": (
        "Scenario parameter. AAP Bright Futures recommends a first-week newborn "
        "visit at 3-5 days and routine infancy visits thereafter; 7/14 days are "
        "conservative outpatient timing assumptions because CDC notes newborns "
        "born during October-March should ideally receive antibody during birth "
        "hospitalization or within 1 week after birth."
    ),
    "first_outpatient_visit_probabilities": (
        "Scenario parameter splitting newborns across the modeled first outpatient "
        "visit timings. Boundy et al. MMWR 2025 reports 38% of infants receiving "
        "nirsevimab in 2023-24 received it within the first week of life, which "
        "can inform sensitivity analyses."
    ),
    "well_child_visit_days": (
        "AAP Bright Futures/AAP Periodicity Schedule recommends infancy preventive "
        "visits in the first week, 1 month, 2 months, 4 months, 6 months, 9 months, "
        "and 12 months."
    ),
    "routine_visit_on_time_probability": (
        "Realistic-delivery scenario parameter. CMS/NCQA HEDIS W30 well-child "
        "visit completion in the first 15 months provides a pragmatic anchor for "
        "the share following an on-schedule routine-visit pathway."
    ),
    "routine_visit_delay_days": (
        "Realistic-delivery scenario parameter. A 14-day delayed pathway is a "
        "transparent sensitivity paired with CMS/NCQA W30 visit-completion data; "
        "it is not treated as a directly observed national delay distribution."
    ),
    "newborn_first_week_dose_probability": (
        "Realistic-delivery scenario parameter. Boundy et al. MMWR 2025 reports "
        "38.1% of infants receiving nirsevimab in 2023-24 received it at age 0-6 "
        "days, used as a first-week newborn dosing proxy."
    ),
    "birth_weight_scheme": (
        "The primary model assumes uniform daily births."
    ),
    "birth_month_weight_multipliers": (
        "Scenario multipliers for the seasonal-national birth sensitivity. Use "
        "CDC WONDER/NCHS Natality state-month births for a future fully empirical "
        "state-specific birth-seasonality analysis."
    ),
    "catchup_if_no_routine_visit": (
        "Scenario parameter. For a previously untreated infant who is age-eligible "
        "at the start of an annual administration window but has no routine "
        "well-child visit in that window before aging out, setting this true adds "
        "one fallback opportunity at window start. This approximates administration "
        "during another healthcare encounter without accelerating infants who have "
        "a modeled routine visit."
    ),
    "receipt_history_mode": (
        "The primary model carries each birth cohort's administration history "
        "forward from the 2023-24 program launch. In each annual window, uptake is "
        "the probability of receipt among previously untreated infants with an "
        "eligible opportunity; recipients are dosed at the first such visit and "
        "are not redosed."
    ),
}

GENERAL_SOURCE_ROWS = [
    (
        "seasonal_window_source",
        "CDC/ACIP recommends October-March infant RSV antibody administration in "
        "most of the U.S.; early, late, and year-round windows are policy scenario "
        "sensitivities around that baseline."
    ),
    (
        "state_epidemic_curve_source",
        "Protection is weighted against observed state RSV activity curves from "
        "the selected healthcare signal, not against a parametric epidemic curve."
    ),
    (
        "uniform_births_source",
        "Uniform daily births are the primary model's simplifying birth-distribution "
        "assumption."
    ),
    (
        "routine_visit_source",
        "CDC guidance permits RSV antibody administration during any healthcare "
        "visit, including well-child visits; AAP Bright Futures provides the "
        "routine preventive visit schedule."
    ),
]

def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def _season_bounds(season: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    start_year, end_year = [int(x) for x in season.split("-")]
    return (
        pd.Timestamp(year=start_year, month=7, day=1),
        pd.Timestamp(year=end_year, month=6, day=30),
    )


def _window_bounds(season: str, window_name: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    start_year, end_year = [int(x) for x in season.split("-")]
    spec = WINDOWS[window_name]
    end_day = min(
        spec["end_day"],
        calendar.monthrange(end_year, spec["end_month"])[1],
    )
    return (
        pd.Timestamp(year=start_year, month=spec["start_month"], day=spec["start_day"]),
        pd.Timestamp(year=end_year, month=spec["end_month"], day=end_day),
    )


def _normalise_probabilities(values: Iterable[float]) -> list[float]:
    probs = np.asarray(list(values), dtype=float)
    total = probs.sum()
    if total <= 0:
        raise ValueError("Visit timing probabilities must sum to a positive value.")
    return (probs / total).tolist()


def _weighted_quantile(values: np.ndarray, weights: np.ndarray, quantile: float) -> float:
    valid = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    values = values[valid]
    weights = weights[valid]
    if len(values) == 0:
        return np.nan

    order = np.argsort(values)
    values = values[order]
    weights = weights[order]
    cumulative = np.cumsum(weights)
    cutoff = quantile * cumulative[-1]
    return float(values[np.searchsorted(cumulative, cutoff, side="left")])


def _birth_weights(birth_dates: pd.DatetimeIndex, model_cfg: dict) -> np.ndarray:
    """Return cohort weights for the modeled birth-date grid."""
    if len(birth_dates) == 0:
        return np.array([], dtype=float)

    scheme = model_cfg.get("birth_weight_scheme", "uniform")
    if scheme in (None, "", "uniform"):
        return np.repeat(1.0 / len(birth_dates), len(birth_dates))

    if scheme not in {"seasonal_national", "monthly_multipliers"}:
        raise ValueError(
            f"Unsupported birth_weight_scheme={scheme!r}; use 'uniform' or 'seasonal_national'."
        )

    raw_multipliers = model_cfg.get("birth_month_weight_multipliers", {})
    if not raw_multipliers:
        raw_multipliers = {
            1: 0.97,
            2: 0.91,
            3: 0.99,
            4: 0.97,
            5: 1.00,
            6: 1.00,
            7: 1.04,
            8: 1.07,
            9: 1.06,
            10: 1.03,
            11: 0.98,
            12: 0.98,
        }

    multipliers = {
        int(month): float(value)
        for month, value in raw_multipliers.items()
    }
    raw_weights = np.array(
        [multipliers.get(date.month, 1.0) for date in birth_dates],
        dtype=float,
    )
    if np.any(raw_weights < 0) or raw_weights.sum() <= 0:
        raise ValueError("birth_month_weight_multipliers must be nonnegative and sum positive.")
    return raw_weights / raw_weights.sum()


def _build_visit_schedules(model_cfg: dict) -> list[dict]:
    first_days = model_cfg.get("first_outpatient_visit_days", [7, 14])
    first_probs = model_cfg.get("first_outpatient_visit_probabilities", [0.5, 0.5])
    well_child_days = model_cfg.get(
        "well_child_visit_days",
        [7, 14, 30.4375, 60.875, 121.75, 182.625],
    )
    first_probs = _normalise_probabilities(first_probs)
    on_time_probability = model_cfg.get("routine_visit_on_time_probability")
    delay_days = int(round(model_cfg.get("routine_visit_delay_days", 0)))

    if len(first_days) != len(first_probs):
        raise ValueError("first_outpatient_visit_days and probabilities must have equal length.")

    other_first_day_set = {int(round(d)) for d in first_days}
    schedules = []
    for first_day, prob in zip(first_days, first_probs):
        first_rounded = int(round(first_day))
        # Each pathway has exactly ONE early-life first visit. A newborn
        # assigned to the 14-day pathway should not also pick up the 7-day
        # opportunity, and the 7-day pathway should not pick up the 14-day
        # opportunity. After that single first visit, routine well-child
        # opportunities apply. We therefore exclude every other configured
        # first-visit day from the routine list for this pathway.
        excluded_first_days = other_first_day_set - {first_rounded}
        days = sorted({
            int(round(day))
            for day in well_child_days
            if day >= first_day and int(round(day)) not in excluded_first_days
        })
        if first_rounded not in days:
            days = sorted([first_rounded] + days)
        schedules.append({
            "first_outpatient_visit_day": first_rounded,
            "schedule_probability": float(prob),
            "visit_timing_pathway": "on_time",
            "visit_days": days,
        })

        if on_time_probability is not None and delay_days > 0:
            on_time_probability = float(on_time_probability)
            if not 0 <= on_time_probability <= 1:
                raise ValueError("routine_visit_on_time_probability must be between 0 and 1.")
            schedules[-1]["schedule_probability"] = float(prob) * on_time_probability
            delayed_days = sorted({day + delay_days for day in days})
            schedules.append({
                "first_outpatient_visit_day": first_rounded + delay_days,
                "schedule_probability": float(prob) * (1.0 - on_time_probability),
                "visit_timing_pathway": "delayed",
                "visit_days": delayed_days,
            })

    return schedules


def _expand_weekly_curve_to_daily(
    group_df: pd.DataFrame,
    value_col: str,
    season_start: pd.Timestamp,
    season_end: pd.Timestamp,
) -> pd.DataFrame:
    days = pd.date_range(season_start, season_end, freq="D")
    daily = pd.DataFrame({
        "date": days,
        "activity_weight": np.zeros(len(days), dtype=float),
        "observed": np.zeros(len(days), dtype=bool),
    })
    day_index = pd.Series(np.arange(len(days)), index=days)

    weekly = (
        group_df[["week_end", value_col]]
        .dropna(subset=["week_end"])
        .copy()
    )
    weekly["week_end"] = pd.to_datetime(weekly["week_end"])
    weekly[value_col] = pd.to_numeric(weekly[value_col], errors="coerce").fillna(0.0)

    for _, row in weekly.iterrows():
        week_end = row["week_end"].normalize()
        week_start = week_end - pd.Timedelta(days=6)
        active_days = pd.date_range(max(week_start, season_start), min(week_end, season_end), freq="D")
        idx = day_index.reindex(active_days).dropna().astype(int).to_numpy()
        if len(idx) == 0:
            continue
        daily.loc[idx, "activity_weight"] = float(row[value_col])
        daily.loc[idx, "observed"] = True

    return daily


def _eligible_routine_administration_dates(
    birth_date: pd.Timestamp,
    visit_days: list[int],
    window_start: pd.Timestamp,
    window_end: pd.Timestamp,
    eligibility_max_age_days: int,
) -> list[pd.Timestamp]:
    """Return every age-eligible routine visit inside one policy window."""
    dates = {
        birth_date + pd.Timedelta(days=int(visit_day))
        for visit_day in visit_days
        if 0 <= int(visit_day) < eligibility_max_age_days
        and window_start
        <= birth_date + pd.Timedelta(days=int(visit_day))
        <= window_end
    }
    return sorted(dates)


RECEIPT_HISTORY_MODE = "seasonal_coverage_first_visit"


def _window_bounds_for_start_year(
    start_year: int,
    window_name: str,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Return one annual policy window identified by its starting year."""
    spec = WINDOWS[window_name]
    end_year = start_year + 1
    end_day = min(
        spec["end_day"],
        calendar.monthrange(end_year, spec["end_month"])[1],
    )
    return (
        pd.Timestamp(
            year=start_year,
            month=spec["start_month"],
            day=spec["start_day"],
        ),
        pd.Timestamp(
            year=end_year,
            month=spec["end_month"],
            day=end_day,
        ),
    )


def _longitudinal_administration_paths(
    birth_date: pd.Timestamp,
    visit_days: list[int],
    window_name: str,
    eligibility_max_age_days: int,
    model_cfg: dict,
    routine_pathway: str,
) -> list[dict]:
    """Build mutually exclusive administration paths across recurring windows.

    The first annual window with a modeled administration opportunity defines the
    infant's initial opportunity. If birth occurs inside that window, the
    newborn/first-week and routine routes remain mutually exclusive. The returned
    ``seasonal_first_dates`` identify the first eligible visit in each annual
    window while the infant remains age-eligible.
    """
    program_start_year = int(model_cfg.get("program_start_season_year", 2023))
    catchup_if_no_routine_visit = bool(
        model_cfg.get("catchup_if_no_routine_visit", False)
    )
    newborn_share = float(
        model_cfg.get("newborn_first_week_dose_probability", 0.0)
    )
    newborn_day = int(round(model_cfg.get("newborn_dose_day", 0)))
    annual_opportunities = []
    eligibility_end = birth_date + pd.Timedelta(days=eligibility_max_age_days - 1)
    first_possible_start_year = max(program_start_year, birth_date.year - 1)
    # Enumerate the infant's complete age-eligible opportunity history even when a
    # visit falls after the season currently being evaluated. This keeps the
    # probability assigned to a past visit invariant across analysis horizons.
    for start_year in range(first_possible_start_year, eligibility_end.year + 1):
        window_start, window_end = _window_bounds_for_start_year(
            start_year, window_name
        )
        if window_start > eligibility_end or window_end < birth_date:
            continue

        routine_dates = _eligible_routine_administration_dates(
            birth_date,
            visit_days,
            window_start,
            window_end,
            eligibility_max_age_days,
        )
        add_window_start = catchup_if_no_routine_visit and not routine_dates
        if add_window_start:
            age_at_window_start = (window_start - birth_date).days
            if 0 <= age_at_window_start < eligibility_max_age_days:
                routine_dates = sorted(set(routine_dates + [window_start]))

        newborn_date = birth_date + pd.Timedelta(days=newborn_day)
        newborn_possible = (
            newborn_share > 0
            and newborn_day < eligibility_max_age_days
            and window_start <= newborn_date <= window_end
        )
        if newborn_possible or routine_dates:
            annual_opportunities.append({
                "start_year": start_year,
                "newborn_date": newborn_date if newborn_possible else None,
                "routine_dates": routine_dates,
            })

    if not annual_opportunities:
        return [{
            "administration_pathway": routine_pathway,
            "route_share": 1.0,
            "primary_date": None,
            "seasonal_first_dates": [],
        }]

    first = annual_opportunities[0]
    routine_seasonal_first_dates = [
        opportunity["routine_dates"][0]
        for opportunity in annual_opportunities
        if opportunity["routine_dates"]
    ]
    primary_routine_date = (
        routine_seasonal_first_dates[0]
        if routine_seasonal_first_dates else None
    )

    if first["newborn_date"] is not None:
        newborn_seasonal_first_dates = [first["newborn_date"]] + [
            opportunity["routine_dates"][0]
            for opportunity in annual_opportunities[1:]
            if opportunity["routine_dates"]
        ]
        return [
            {
                "administration_pathway": "newborn_first_week",
                "route_share": newborn_share,
                "primary_date": first["newborn_date"],
                "seasonal_first_dates": newborn_seasonal_first_dates,
            },
            {
                "administration_pathway": routine_pathway,
                "route_share": 1.0 - newborn_share,
                "primary_date": primary_routine_date,
                "seasonal_first_dates": routine_seasonal_first_dates,
            },
        ]

    return [{
        "administration_pathway": routine_pathway,
        "route_share": 1.0,
        "primary_date": primary_routine_date,
        "seasonal_first_dates": routine_seasonal_first_dates,
    }]


def _administration_date_probabilities(
    route_spec: dict,
    uptake: float,
) -> list[tuple[pd.Timestamp, float]]:
    """Return mutually exclusive probabilities for first receipt dates.

    ``uptake`` is the probability that a previously untreated infant receives
    prophylaxis in an annual window. Recipients are dosed at that window's first
    eligible visit. If still untreated and eligible in a later annual window, the
    infant has the same receipt probability there, producing mutually exclusive
    first-receipt probabilities ``u, (1-u)u, ...``. Later visits within the same
    annual window do not create additional modeled opportunities.
    """
    if not 0 <= uptake <= 1:
        raise ValueError("uptake must be between 0 and 1.")
    primary_date = route_spec.get("primary_date")
    seasonal_dates = route_spec.get("seasonal_first_dates")
    if seasonal_dates is None:
        # Year-round is evaluated as one continuous steady-state program,
        # not as repeated artificial July-June seasons.
        seasonal_dates = [primary_date] if primary_date is not None else []
    seasonal_dates = sorted(set(seasonal_dates))
    return [
        (
            administration_date,
            uptake * ((1.0 - uptake) ** season_index),
        )
        for season_index, administration_date in enumerate(seasonal_dates)
        if uptake * ((1.0 - uptake) ** season_index) > 0
    ]


def _efficacy_values(
    dates: np.ndarray,
    admin_date: pd.Timestamp | None,
    model_cfg: dict,
    protection_delay_days: int,
    protection_duration_days: int,
) -> np.ndarray:
    """Return daily efficacy weights between 0 and 1 for a dose date."""
    if admin_date is None:
        return np.zeros(len(dates), dtype=float)

    admin_np = np.datetime64(admin_date.date())
    days_since = (dates - admin_np).astype("timedelta64[D]").astype(int)
    in_duration = (days_since >= 0) & (days_since < protection_duration_days)

    profile = model_cfg.get("efficacy_profile", "binary")
    if profile == "binary":
        protected = (
            (days_since >= protection_delay_days) &
            (days_since < protection_duration_days)
        )
        return protected.astype(float)

    if profile != "piecewise_linear":
        raise ValueError(
            f"Unsupported efficacy_profile={profile!r}; use 'binary' or 'piecewise_linear'."
        )

    points = model_cfg.get("efficacy_curve_points", [])
    curve = []
    for point in points:
        curve.append((float(point["day"]), float(point["efficacy"])))
    if not curve:
        curve = [
            (0.0, 0.0),
            (float(protection_delay_days), 0.936),
            (45.0, 0.807),
            (float(protection_duration_days), 0.77),
        ]

    curve.append((0.0, 0.0))
    curve_df = (
        pd.DataFrame(curve, columns=["day", "efficacy"])
        .groupby("day", as_index=False)["efficacy"]
        .last()
        .sort_values("day")
    )

    efficacy = np.zeros(len(dates), dtype=float)
    efficacy[in_duration] = np.interp(
        days_since[in_duration],
        curve_df["day"].to_numpy(dtype=float),
        curve_df["efficacy"].to_numpy(dtype=float),
        left=0.0,
        right=0.0,
    )
    return np.clip(efficacy, 0.0, 1.0)


def year_round_steady_state_metrics(model_cfg: dict) -> tuple[float, float]:
    """Return protection and receipt for a year-round program at steady state.

    A year-round policy is a continuously running program, so it must be evaluated
    as an established (stationary) program rather than a single modeled season.
    Under uniform daily births and a periodic annual epidemic, the population is
    stationary: on every calendar day the same age-mix (and therefore the same
    protected fraction) is present. Seasonal coverage is assigned once and
    recipients are dosed at their first eligible visit; later visits do not create
    additional annual receipt opportunities. The resulting protection is independent of the
    epidemic curve's timing or width. Computing
    year-round within a single modeled season instead produces a startup artifact
    (the window effectively opens July 1 and doses a backlog of already-born
    infants), which spuriously favors early-onset seasons and penalizes late ones.
    """
    censor_days = int(round(
        model_cfg.get("exposure_censor_age_months", 12) * 365.25 / 12
    ))
    eligibility_max_age_days = int(round(
        model_cfg.get("eligibility_max_age_months", model_cfg.get("max_age_months", 8)) *
        365.25 / 12
    ))
    protection_delay_days = int(round(model_cfg.get("protection_delay_days", 6)))
    protection_duration_days = int(round(model_cfg.get("protection_duration_days", 180)))
    uptake = float(model_cfg.get("uptake", 1.0))
    newborn_share = float(model_cfg.get("newborn_first_week_dose_probability", 0.0))
    newborn_dose_day = int(round(model_cfg.get("newborn_dose_day", 0)))

    schedules = _build_visit_schedules(model_cfg)
    ref = pd.Timestamp("2001-01-01")
    dates = (ref.to_datetime64() +
             np.arange(censor_days).astype("timedelta64[D]"))

    def eff_by_age(dose_age: int) -> np.ndarray:
        if dose_age is None or dose_age >= eligibility_max_age_days:
            return np.zeros(censor_days, dtype=float)
        admin = ref + pd.Timedelta(days=int(dose_age))
        return _efficacy_values(
            dates, admin, model_cfg, protection_delay_days, protection_duration_days
        )

    eff_age = np.zeros(censor_days, dtype=float)
    receipt_probability = 0.0
    total_path_weight = 0.0
    for schedule in schedules:
        routine_days = sorted({
            int(day)
            for day in schedule["visit_days"]
            if 0 <= int(day) < eligibility_max_age_days
        })
        routine_dates = [ref + pd.Timedelta(days=day) for day in routine_days]
        route_specs = []
        if newborn_share > 0 and newborn_dose_day < eligibility_max_age_days:
            newborn_date = ref + pd.Timedelta(days=newborn_dose_day)
            route_specs.append({
                "route_share": newborn_share,
                "primary_date": newborn_date,
            })
            routine_share = 1.0 - newborn_share
        else:
            routine_share = 1.0
        route_specs.append({
            "route_share": routine_share,
            "primary_date": routine_dates[0] if routine_dates else None,
        })

        for route_spec in route_specs:
            path_weight = (
                float(schedule["schedule_probability"])
                * float(route_spec["route_share"])
            )
            if path_weight <= 0:
                continue
            date_probabilities = _administration_date_probabilities(
                route_spec,
                uptake,
            )
            total_path_weight += path_weight
            receipt_probability += path_weight * sum(
                probability for _, probability in date_probabilities
            )
            for administration_date, probability in date_probabilities:
                dose_age = int((administration_date - ref).days)
                eff_age += path_weight * probability * eff_by_age(dose_age)

    if total_path_weight > 0:
        eff_age /= total_path_weight
        receipt_probability /= total_path_weight
    return float(eff_age.mean()), float(receipt_probability)


def year_round_steady_state_protection(model_cfg: dict) -> float:
    """Backward-compatible scalar wrapper for steady-state protection."""
    protection, _ = year_round_steady_state_metrics(model_cfg)
    return protection


def _cohort_rows_for_group(
    group_df: pd.DataFrame,
    value_col: str,
    datasource: str,
    metric_label: str,
    model_cfg: dict,
    schedules: list[dict],
) -> pd.DataFrame:
    season = group_df["season"].iloc[0]
    jurisdiction = group_df["jurisdiction"].iloc[0]
    season_start, season_end = _season_bounds(season)

    eligibility_max_age_days = int(round(
        model_cfg.get("eligibility_max_age_months", model_cfg.get("max_age_months", 8)) *
        365.25 / 12
    ))
    exposure_censor_age_days = int(round(
        model_cfg.get("exposure_censor_age_months", 12) * 365.25 / 12
    ))
    protection_delay_days = int(round(model_cfg.get("protection_delay_days", 6)))
    protection_duration_days = int(round(model_cfg.get("protection_duration_days", 180)))
    efficacy_profile = model_cfg.get("efficacy_profile", "binary")
    uptake = float(model_cfg.get("uptake", 1.0))
    receipt_history_mode = model_cfg.get("receipt_history_mode", RECEIPT_HISTORY_MODE)
    if receipt_history_mode != RECEIPT_HISTORY_MODE:
        raise ValueError(
            f"Unsupported receipt_history_mode={receipt_history_mode!r}; "
            f"the publication pipeline requires {RECEIPT_HISTORY_MODE!r}."
        )
    catchup_if_no_routine_visit = bool(
        model_cfg.get("catchup_if_no_routine_visit", False)
    )
    newborn_first_week_dose_probability = float(
        model_cfg.get("newborn_first_week_dose_probability", 0.0)
    )
    if not 0 <= newborn_first_week_dose_probability <= 1:
        raise ValueError("newborn_first_week_dose_probability must be between 0 and 1.")

    daily = _expand_weekly_curve_to_daily(group_df, value_col, season_start, season_end)
    dates = daily["date"].to_numpy(dtype="datetime64[D]")
    activity = daily["activity_weight"].to_numpy(dtype=float)
    observed = daily["observed"].to_numpy(dtype=bool)

    window_bounds = {
        window_name: _window_bounds(season, window_name)
        for window_name in WINDOWS
    }
    earliest_window_start = min(bounds[0] for bounds in window_bounds.values())
    # Start the birth-cohort grid from the exposure-censor age (not the dosing
    # eligibility age) so that the protection denominator includes every infant who
    # can accrue at-risk RSV exposure during the season, including those born early
    # enough to be past the dosing-eligibility age but still within the at-risk
    # window. Using the eligibility age would omit these older-but-still-at-risk
    # infants and slightly overstate protection in states with early-onset (summer)
    # RSV activity. The omitted exposure is unprotected under every window, so this
    # affects absolute protection more than the between-window contrasts.
    birth_start = earliest_window_start - pd.Timedelta(days=exposure_censor_age_days - 1)
    birth_dates = pd.date_range(birth_start, season_end, freq="D")
    birth_weights = _birth_weights(birth_dates, model_cfg)
    birth_weight_scheme = model_cfg.get("birth_weight_scheme", "uniform")
    efficacy_cache: dict[str | None, np.ndarray] = {}

    rows = []
    for birth_date, birth_weight in zip(birth_dates, birth_weights):
        birth_np = np.datetime64(birth_date.date())
        age_days = (dates - birth_np).astype("timedelta64[D]").astype(int)
        at_risk = observed & (age_days >= 0) & (age_days < exposure_censor_age_days)

        activity_denominator = float(activity[at_risk].sum())
        calendar_denominator = int(at_risk.sum())

        if calendar_denominator == 0:
            continue

        birth_month = birth_date.strftime("%Y-%m")
        for schedule in schedules:
            visit_days = schedule["visit_days"]
            schedule_probability = schedule["schedule_probability"]

            for window_name in window_bounds:
                routine_pathway = schedule.get(
                    "visit_timing_pathway", "routine"
                )
                route_specs = _longitudinal_administration_paths(
                    birth_date=birth_date,
                    visit_days=visit_days,
                    window_name=window_name,
                    eligibility_max_age_days=eligibility_max_age_days,
                    model_cfg=model_cfg,
                    routine_pathway=routine_pathway,
                )

                for route_spec in route_specs:
                    administration_pathway = route_spec["administration_pathway"]
                    route_share = float(route_spec["route_share"])
                    row_weight = birth_weight * schedule_probability * route_share
                    if row_weight <= 0:
                        continue

                    date_probabilities = _administration_date_probabilities(
                        route_spec,
                        uptake,
                    )
                    activity_numerator = 0.0
                    calendar_numerator = 0.0
                    for admin_date, dose_probability in date_probabilities:
                        efficacy_key = admin_date.date().isoformat()
                        if efficacy_key not in efficacy_cache:
                            efficacy_cache[efficacy_key] = _efficacy_values(
                                dates,
                                admin_date,
                                model_cfg,
                                protection_delay_days,
                                protection_duration_days,
                            )
                        efficacy = efficacy_cache[efficacy_key]
                        activity_numerator += (
                            float((activity[at_risk] * efficacy[at_risk]).sum())
                            * dose_probability
                        )
                        calendar_numerator += (
                            float(efficacy[at_risk].sum()) * dose_probability
                        )

                    received_ppx = bool(date_probabilities)
                    receipt_probability = float(
                        sum(probability for _, probability in date_probabilities)
                    )
                    prior_season_receipt_probability = float(sum(
                        probability
                        for administration_date, probability in date_probabilities
                        if administration_date < season_start
                    ))
                    current_season_receipt_probability = float(sum(
                        probability
                        for administration_date, probability in date_probabilities
                        if season_start <= administration_date <= season_end
                    ))
                    administration_dates = ";".join(
                        administration_date.date().isoformat()
                        for administration_date, _ in date_probabilities
                    )

                    if activity_denominator > 0:
                        activity_fraction = activity_numerator / activity_denominator
                    else:
                        activity_fraction = np.nan

                    calendar_fraction = calendar_numerator / calendar_denominator

                    rows.append({
                        "datasource": datasource,
                        "metric_label": metric_label,
                        "season": season,
                        "jurisdiction": jurisdiction,
                        "window_name": window_name,
                        "window_label": WINDOW_LABELS[window_name],
                        "birth_date": birth_date.date().isoformat(),
                        "birth_month": birth_month,
                        "first_outpatient_visit_day": schedule["first_outpatient_visit_day"],
                        "schedule_probability": schedule_probability,
                        "visit_timing_pathway": schedule.get("visit_timing_pathway", "routine"),
                        "administration_pathway": administration_pathway,
                        "route_share": route_share,
                        "cohort_weight": row_weight,
                        "received_ppx": received_ppx,
                        "administration_date": administration_dates or None,
                        "receipt_probability": receipt_probability,
                        "prior_season_receipt_probability": prior_season_receipt_probability,
                        "current_season_receipt_probability": current_season_receipt_probability,
                        "n_administration_opportunities": len(date_probabilities),
                        "activity_denominator": activity_denominator,
                        "activity_numerator": activity_numerator,
                        "activity_fractional_protection": activity_fraction,
                        "calendar_denominator_days": calendar_denominator,
                        "calendar_numerator_days": calendar_numerator,
                        "calendar_fractional_protection": calendar_fraction,
                        "uptake": uptake,
                        "efficacy_profile": efficacy_profile,
                        "protection_delay_days": protection_delay_days,
                        "protection_duration_days": protection_duration_days,
                        "eligibility_max_age_days": eligibility_max_age_days,
                        "exposure_censor_age_days": exposure_censor_age_days,
                        "birth_weight_scheme": birth_weight_scheme,
                        "catchup_if_no_routine_visit": (
                            catchup_if_no_routine_visit
                        ),
                        "receipt_history_mode": receipt_history_mode,
                        "program_start_season_year": int(
                            model_cfg.get("program_start_season_year", 2023)
                        ),
                    })

    return pd.DataFrame(rows)


def _summarise_state(cohort_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    group_cols = ["datasource", "metric_label", "season", "jurisdiction", "window_name", "window_label"]

    for keys, group in cohort_df.groupby(group_cols):
        weights = group["cohort_weight"].to_numpy(dtype=float)
        activity_frac = group["activity_fractional_protection"].to_numpy(dtype=float)
        calendar_frac = group["calendar_fractional_protection"].to_numpy(dtype=float)

        activity_valid = np.isfinite(activity_frac)
        calendar_valid = np.isfinite(calendar_frac)

        activity_exposure = group["activity_denominator"].to_numpy(dtype=float) * weights
        total_activity_exposure = float(np.nansum(activity_exposure))
        population_activity_numerator = float(np.nansum(group["activity_numerator"].to_numpy(dtype=float) * weights))
        if "receipt_probability" in group:
            actual_receipt = group["receipt_probability"].to_numpy(dtype=float)
        else:
            actual_receipt = (
                group["received_ppx"].astype(float).to_numpy(dtype=float)
                * group["uptake"].to_numpy(dtype=float)
            )

        row = dict(zip(group_cols, keys))
        row.update({
            "n_birth_cohorts": group["birth_date"].nunique(),
            "n_cohort_schedule_rows": len(group),
            "share_receiving_ppx": float(np.sum(actual_receipt * weights) / np.sum(weights)),
            "median_person_activity_fractional_protection": _weighted_quantile(activity_frac, weights, 0.50),
            "q25_person_activity_fractional_protection": _weighted_quantile(activity_frac, weights, 0.25),
            "q75_person_activity_fractional_protection": _weighted_quantile(activity_frac, weights, 0.75),
            "mean_person_activity_fractional_protection": (
                float(np.average(activity_frac[activity_valid], weights=weights[activity_valid]))
                if activity_valid.any() else np.nan
            ),
            "population_activity_weighted_protection": (
                population_activity_numerator / total_activity_exposure
                if total_activity_exposure > 0 else np.nan
            ),
            "median_person_calendar_fractional_protection": _weighted_quantile(calendar_frac, weights, 0.50),
            "mean_person_calendar_fractional_protection": (
                float(np.average(calendar_frac[calendar_valid], weights=weights[calendar_valid]))
                if calendar_valid.any() else np.nan
            ),
            "total_activity_exposure_weight": total_activity_exposure,
            "uptake": float(group["uptake"].iloc[0]),
            "efficacy_profile": group["efficacy_profile"].iloc[0],
            "protection_delay_days": int(group["protection_delay_days"].iloc[0]),
            "protection_duration_days": int(group["protection_duration_days"].iloc[0]),
            "eligibility_max_age_days": int(group["eligibility_max_age_days"].iloc[0]),
            "exposure_censor_age_days": int(group["exposure_censor_age_days"].iloc[0]),
            "birth_weight_scheme": group["birth_weight_scheme"].iloc[0],
            "catchup_if_no_routine_visit": bool(
                group["catchup_if_no_routine_visit"].iloc[0]
            ),
            "receipt_history_mode": group["receipt_history_mode"].iloc[0],
            "program_start_season_year": int(
                group["program_start_season_year"].iloc[0]
            ),
        })
        rows.append(row)

    return pd.DataFrame(rows)


def _summarise_birth_month(cohort_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    group_cols = [
        "datasource", "season", "jurisdiction", "window_name", "window_label", "birth_month"
    ]

    for keys, group in cohort_df.groupby(group_cols):
        weights = group["cohort_weight"].to_numpy(dtype=float)
        activity_frac = group["activity_fractional_protection"].to_numpy(dtype=float)
        if "receipt_probability" in group:
            actual_receipt = group["receipt_probability"].to_numpy(dtype=float)
        else:
            actual_receipt = (
                group["received_ppx"].astype(float).to_numpy(dtype=float)
                * group["uptake"].to_numpy(dtype=float)
            )
        rows.append({
            **dict(zip(group_cols, keys)),
            "median_person_activity_fractional_protection": _weighted_quantile(activity_frac, weights, 0.50),
            "mean_person_activity_fractional_protection": (
                float(np.average(activity_frac[np.isfinite(activity_frac)], weights=weights[np.isfinite(activity_frac)]))
                if np.isfinite(activity_frac).any() else np.nan
            ),
            "share_receiving_ppx": float(np.sum(actual_receipt * weights) / np.sum(weights)),
            "total_activity_exposure_weight": float(np.nansum(group["activity_denominator"].to_numpy(dtype=float) * weights)),
        })

    return pd.DataFrame(rows)


def _apply_year_round_steady_state(
    state_summary: pd.DataFrame,
    model_cfg: dict,
) -> pd.DataFrame:
    """Replace supported year-round fields with analytic steady-state values."""
    if state_summary.empty or "window_name" not in state_summary.columns:
        return state_summary

    yr_mask = state_summary["window_name"] == "year_round"
    if not yr_mask.any():
        return state_summary

    yr_ss, yr_receipt = year_round_steady_state_metrics(model_cfg)
    if "population_activity_weighted_protection" in state_summary.columns:
        state_summary.loc[
            yr_mask, "population_activity_weighted_protection"
        ] = yr_ss
    if "share_receiving_ppx" in state_summary.columns:
        state_summary.loc[yr_mask, "share_receiving_ppx"] = yr_receipt

    unsupported_person_fields = (
        "median_person_activity_fractional_protection",
        "mean_person_activity_fractional_protection",
        "q25_person_activity_fractional_protection",
        "q75_person_activity_fractional_protection",
        "median_person_calendar_fractional_protection",
        "mean_person_calendar_fractional_protection",
    )
    for column in unsupported_person_fields:
        if column in state_summary.columns:
            state_summary.loc[yr_mask, column] = np.nan

    return state_summary


def create_primary_parameter_table(config: dict) -> pd.DataFrame:
    """Build the datasource-independent provenance table behind manuscript Table 2."""
    model = config["infant_ppx_model"]
    translation = config["infant_hospitalization_translation"]
    general_sources = dict(GENERAL_SOURCE_ROWS)
    uptake_pct = 100 * float(model["uptake"])
    newborn_pct = 100 * float(model["newborn_first_week_dose_probability"])
    on_time_pct = 100 * float(model["routine_visit_on_time_probability"])
    delayed_pct = 100 - on_time_pct
    risk_per_1000 = float(
        translation["baseline_hospitalization_risk_per_1000_infants"]
    )

    rows = [
        {
            "parameter": "Prophylaxis windows compared",
            "value": (
                "October-March (baseline); September-March; October-April; "
                "year-round"
            ),
            "source": "Current CDC/ACIP guidance",
            "rationale": "Operationally simple, calendar-defined alternatives",
            "source_detail": general_sources["seasonal_window_source"],
        },
        {
            "parameter": "Primary timing curve",
            "value": "NSSP RSV-associated ED activity",
            "source": "CDC National Syndromic Surveillance Program",
            "rationale": (
                "ED activity proxies community infection risk more closely than "
                "admissions"
            ),
            "source_detail": general_sources["state_epidemic_curve_source"],
        },
        {
            "parameter": "Birth distribution",
            "value": "Uniform across days",
            "source": "Modeling assumption",
            "rationale": "First-order assumption",
            "source_detail": general_sources["uniform_births_source"],
        },
        {
            "parameter": "Eligibility",
            "value": f"Age <{model['eligibility_max_age_months']} months",
            "source": "CDC/ACIP infant RSV antibody guidance",
            "rationale": "First RSV season per current recommendations",
            "source_detail": PARAMETER_SOURCE_ROWS["eligibility_max_age_months"],
        },
        {
            "parameter": "Receipt history",
            "value": "Prior recipients not redosed",
            "source": "Modeling implementation",
            "rationale": (
                "Untreated infants may receive in a later annual window if "
                "age-eligible and a modeled opportunity exists"
            ),
            "source_detail": PARAMETER_SOURCE_ROWS["receipt_history_mode"],
        },
        {
            "parameter": "Exposure censor",
            "value": (
                f"{model['exposure_censor_age_months']} months (primary); "
                "8 months (sensitivity)"
            ),
            "source": "Modeling definition",
            "rationale": (
                "Captures first-year infant risk; 8-month variant aligns with "
                "eligibility-age framing"
            ),
            "source_detail": PARAMETER_SOURCE_ROWS["exposure_censor_age_months"],
        },
        {
            "parameter": "Uptake",
            "value": (
                f"{uptake_pct:g}% (primary); "
                "50%, 75%, 100% (sensitivity)"
            ),
            "source": "Boundy et al., MMWR 2025",
            "rationale": (
                "Seasonal coverage among previously untreated infants with an "
                "eligible visit"
            ),
            "source_detail": PARAMETER_SOURCE_ROWS["uptake"],
        },
        {
            "parameter": "Newborn/first-week dosing pathway",
            "value": f"{newborn_pct:g}% of recipients",
            "source": "Boundy et al., MMWR 2025",
            "rationale": (
                "2023-2024 birth-hospitalization and first-week delivery share"
            ),
            "source_detail": PARAMETER_SOURCE_ROWS[
                "newborn_first_week_dose_probability"
            ],
        },
        {
            "parameter": "Routine well-child visits",
            "value": "Newborn, 1, 2, 4, 6 months",
            "source": "AAP periodicity schedule",
            "rationale": "Standard preventive-care opportunities",
            "source_detail": PARAMETER_SOURCE_ROWS["well_child_visit_days"],
        },
        {
            "parameter": "Visit timing distribution",
            "value": (
                f"{on_time_pct:g}% on schedule; {delayed_pct:g}% delayed by "
                f"{model['routine_visit_delay_days']} days"
            ),
            "source": "NCQA HEDIS W30",
            "rationale": (
                "Adherence anchor for imperfect routine-care timing in 2023 "
                "Medicaid cohort"
            ),
            "source_detail": (
                PARAMETER_SOURCE_ROWS["routine_visit_on_time_probability"]
                + " "
                + PARAMETER_SOURCE_ROWS["routine_visit_delay_days"]
            ),
        },
        {
            "parameter": "Time to protection onset",
            "value": f"{model['protection_delay_days']} days post-receipt",
            "source": "Beyfortus prescribing information",
            "rationale": "Median time to maximum nirsevimab concentration",
            "source_detail": PARAMETER_SOURCE_ROWS["protection_delay_days"],
        },
        {
            "parameter": "Effectiveness curve",
            "value": (
                "Smoothed time-varying effectiveness through day "
                f"{model['protection_duration_days']}"
            ),
            "source": "Moline et al., JAMA Pediatrics 2026",
            "rationale": "Post-licensure effectiveness against RSV hospitalization",
            "source_detail": PARAMETER_SOURCE_ROWS["efficacy_curve_points"],
        },
        {
            "parameter": "Untreated infant RSV hospitalization risk",
            "value": f"{risk_per_1000:.2f} per 1000 infant-seasons",
            "source": "Pelletier et al., JAMA Network Open 2025",
            "rationale": "Denominator for expected hospitalizations averted",
            "source_detail": translation["burden_source"],
        },
        {
            "parameter": "Infant population denominator",
            "value": (
                "State age-under-1 resident population, "
                f"{translation['infant_population_year']}"
            ),
            "source": "U.S. Census Bureau Population Estimates Program",
            "rationale": "State-specific scaling",
            "source_detail": translation["population_source"],
        },
    ]
    return pd.DataFrame(rows)


def run_infant_ppx_analysis(
    df: pd.DataFrame,
    value_col: str,
    datasource: str,
    metric_label: str,
    config: dict | None = None,
    include_birth_month_summary: bool = True,
) -> dict:
    """
    Run infant prophylaxis protection analysis for one data source.

    Returns:
        Dictionary with state_summary and birth_month_summary.
    """
    if config is None:
        config = load_config()
    model_cfg = config.get("infant_ppx_model", {})
    schedules = _build_visit_schedules(model_cfg)

    logger.info("INFANT PPX PROTECTION MODEL")
    logger.info(f"Datasource: {datasource} | Outcome: {value_col}")

    df_valid = df[df[value_col].notna()].copy()
    if df_valid.empty:
        logger.warning("No non-missing rows for infant PPX model.")
        empty = pd.DataFrame()
        return {
            "state_summary": empty,
            "birth_month_summary": empty,
        }

    cohort_parts = []
    for (_, _), group_df in df_valid.groupby(["season", "jurisdiction"]):
        cohort = _cohort_rows_for_group(
            group_df=group_df,
            value_col=value_col,
            datasource=datasource,
            metric_label=metric_label,
            model_cfg=model_cfg,
            schedules=schedules,
        )
        if not cohort.empty:
            cohort_parts.append(cohort)

    if not cohort_parts:
        empty = pd.DataFrame()
        return {
            "state_summary": empty,
            "birth_month_summary": empty,
        }

    cohort_df = pd.concat(cohort_parts, ignore_index=True)
    state_summary = _summarise_state(cohort_df)

    # Year-round is a continuously running (any-time-of-year) birth-dose program and
    # must be evaluated as an established program. Replace its supported aggregate
    # fields with steady-state values, which removes a startup artifact and is
    # independent of the epidemic curve (see year_round_steady_state_protection).
    # Person-level distribution summaries are not identified by this analytic
    # steady-state calculation and are set to missing. Windowed policies are left
    # unchanged.
    if "year_round" in set(WINDOWS):
        state_summary = _apply_year_round_steady_state(
            state_summary,
            model_cfg,
        )

    birth_month_summary = (
        _summarise_birth_month(cohort_df)
        if include_birth_month_summary else pd.DataFrame()
    )
    if "year_round" in set(WINDOWS):
        birth_month_summary = _apply_year_round_steady_state(
            birth_month_summary,
            model_cfg,
        )

    logger.info(
        "Infant PPX model complete: %s state-season-window rows",
        f"{len(state_summary):,}",
    )
    for window_name in WINDOWS:
        subset = state_summary[state_summary["window_name"] == window_name]
        logger.info(
            "  %s: median state median person protection=%.3f",
            window_name,
            subset["median_person_activity_fractional_protection"].median(),
        )

    return {
        "state_summary": state_summary,
        "birth_month_summary": birth_month_summary,
    }
