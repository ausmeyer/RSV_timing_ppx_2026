"""
Season building and data processing.

Handles season assignment, fixed window flagging, jurisdiction filtering,
and HHS region mapping.
"""

import logging
from pathlib import Path
from typing import Optional

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
DATA_PROCESSED = PROJECT_ROOT / "data" / "processed"

# State name to abbreviation mapping
STATE_ABBREVS = {
    'Alabama': 'AL', 'Alaska': 'AK', 'Arizona': 'AZ', 'Arkansas': 'AR',
    'California': 'CA', 'Colorado': 'CO', 'Connecticut': 'CT', 'Delaware': 'DE',
    'District of Columbia': 'DC', 'Florida': 'FL', 'Georgia': 'GA', 'Hawaii': 'HI',
    'Idaho': 'ID', 'Illinois': 'IL', 'Indiana': 'IN', 'Iowa': 'IA',
    'Kansas': 'KS', 'Kentucky': 'KY', 'Louisiana': 'LA', 'Maine': 'ME',
    'Maryland': 'MD', 'Massachusetts': 'MA', 'Michigan': 'MI', 'Minnesota': 'MN',
    'Mississippi': 'MS', 'Missouri': 'MO', 'Montana': 'MT', 'Nebraska': 'NE',
    'Nevada': 'NV', 'New Hampshire': 'NH', 'New Jersey': 'NJ', 'New Mexico': 'NM',
    'New York': 'NY', 'North Carolina': 'NC', 'North Dakota': 'ND', 'Ohio': 'OH',
    'Oklahoma': 'OK', 'Oregon': 'OR', 'Pennsylvania': 'PA', 'Rhode Island': 'RI',
    'South Carolina': 'SC', 'South Dakota': 'SD', 'Tennessee': 'TN', 'Texas': 'TX',
    'Utah': 'UT', 'Vermont': 'VT', 'Virginia': 'VA', 'Washington': 'WA',
    'West Virginia': 'WV', 'Wisconsin': 'WI', 'Wyoming': 'WY'
}

ABBREV_TO_STATE = {abbr: name for name, abbr in STATE_ABBREVS.items()}


def load_config() -> dict:
    """Load configuration from config.yaml."""
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def normalize_jurisdiction_names(
    df: pd.DataFrame,
    jurisdiction_col: str = "jurisdiction"
) -> pd.DataFrame:
    """
    Normalize jurisdiction names by expanding state abbreviations when detected.

    Some sources (e.g., NHSN) use two-letter abbreviations; others use full names.
    """
    df = df.copy()
    values = df[jurisdiction_col].dropna().astype(str)
    if values.empty:
        return df

    abbrev_share = (values.str.fullmatch(r"[A-Z]{2}")).mean()

    if abbrev_share >= 0.6:
        df[jurisdiction_col] = df[jurisdiction_col].map(ABBREV_TO_STATE).fillna(df[jurisdiction_col])
        logger.info(
            f"Expanded {abbrev_share:.0%} abbreviated jurisdictions to full names."
        )

    return df


def assign_season(df: pd.DataFrame, week_col: str = "week_end") -> pd.DataFrame:
    """
    Add 'season' column based on configured date ranges.

    Args:
        df: DataFrame with week_end column
        week_col: Name of the week-ending date column

    Returns:
        DataFrame with 'season' column added
    """
    config = load_config()
    seasons = config["seasons"]

    df = df.copy()
    df["season"] = None

    for season_def in seasons:
        name = season_def["name"]
        start = pd.to_datetime(season_def["start"])
        end = pd.to_datetime(season_def["end"])

        mask = (df[week_col] >= start) & (df[week_col] <= end)
        df.loc[mask, "season"] = name

    # Count assignments
    assigned = df["season"].notna().sum()
    total = len(df)
    logger.info(f"Season assignment: {assigned:,}/{total:,} rows ({100*assigned/total:.1f}%)")

    # Log season breakdown
    season_counts = df.groupby("season").size()
    for season, count in season_counts.items():
        logger.info(f"  {season}: {count:,} rows")

    return df


def flag_fixed_window(
    df: pd.DataFrame,
    week_col: str = "week_end",
    season_col: str = "season"
) -> pd.DataFrame:
    """
    Add 'in_fixed_window' boolean based on Oct 1 - Mar 31 window.

    For each season (e.g., "2022-2023"), the fixed window is:
    - Start: Oct 1 of the first year (2022)
    - End: Mar 31 of the second year (2023)

    Args:
        df: DataFrame with week_end and season columns
        week_col: Name of the week-ending date column
        season_col: Name of the season column

    Returns:
        DataFrame with 'in_fixed_window' column added
    """
    config = load_config()
    window_config = config["fixed_window"]

    start_month = window_config["start_month"]
    start_day = window_config["start_day"]
    end_month = window_config["end_month"]
    end_day = window_config["end_day"]

    df = df.copy()
    df["in_fixed_window"] = False

    for season in df[season_col].dropna().unique():
        # Parse season years (e.g., "2022-2023" -> 2022, 2023)
        years = season.split("-")
        start_year = int(years[0])
        end_year = int(years[1])

        # Build window dates
        window_start = pd.Timestamp(year=start_year, month=start_month, day=start_day)
        window_end = pd.Timestamp(year=end_year, month=end_month, day=end_day)

        # Flag rows within window
        mask = (
            (df[season_col] == season) &
            (df[week_col] >= window_start) &
            (df[week_col] <= window_end)
        )
        df.loc[mask, "in_fixed_window"] = True

        # Log
        in_window = mask.sum()
        total_season = (df[season_col] == season).sum()
        if total_season > 0:
            logger.info(
                f"  {season}: {in_window:,}/{total_season:,} rows in Oct-Mar window "
                f"({100*in_window/total_season:.1f}%)"
            )

    return df


def filter_jurisdictions(
    df: pd.DataFrame,
    jurisdiction_col: str = "jurisdiction",
    exclude_list: Optional[list[str]] = None
) -> pd.DataFrame:
    """
    Remove specified jurisdictions from the dataset.

    Args:
        df: DataFrame with jurisdiction column
        jurisdiction_col: Name of the jurisdiction column
        exclude_list: List of jurisdiction names to exclude (uses config if None)

    Returns:
        Filtered DataFrame
    """
    if exclude_list is None:
        config = load_config()
        exclude_list = config["geography"]["exclude_jurisdictions"]

    df = df.copy()
    original_count = len(df)

    # Filter out excluded jurisdictions
    mask = ~df[jurisdiction_col].isin(exclude_list)
    df = df[mask]

    removed = original_count - len(df)
    logger.info(
        f"Jurisdiction filter: removed {removed:,} rows "
        f"(excluded: {', '.join(exclude_list[:5])}{'...' if len(exclude_list) > 5 else ''})"
    )
    logger.info(f"Remaining jurisdictions: {df[jurisdiction_col].nunique()}")

    return df


def add_state_abbreviation(
    df: pd.DataFrame,
    jurisdiction_col: str = "jurisdiction"
) -> pd.DataFrame:
    """
    Add state abbreviation column.

    Args:
        df: DataFrame with jurisdiction column (full state names)
        jurisdiction_col: Name of the jurisdiction column

    Returns:
        DataFrame with 'state_abbrev' column added
    """
    df = df.copy()
    df["state_abbrev"] = df[jurisdiction_col].map(STATE_ABBREVS)

    # Log unmapped
    unmapped = df[df["state_abbrev"].isna()][jurisdiction_col].unique()
    if len(unmapped) > 0:
        logger.warning(f"Unmapped jurisdictions (no abbreviation): {list(unmapped)}")

    return df


def add_hhs_region(
    df: pd.DataFrame,
    jurisdiction_col: str = "jurisdiction"
) -> pd.DataFrame:
    """
    Map jurisdictions to HHS regions.

    Args:
        df: DataFrame with jurisdiction column
        jurisdiction_col: Name of the jurisdiction column

    Returns:
        DataFrame with 'hhs_region' column added
    """
    config = load_config()
    hhs_regions = config["hhs_regions"]

    # Build reverse mapping (state -> region)
    state_to_region = {}
    for region, states in hhs_regions.items():
        for state in states:
            state_to_region[state] = int(region)

    df = df.copy()
    df["hhs_region"] = df[jurisdiction_col].map(state_to_region)

    # Log coverage
    mapped = df["hhs_region"].notna().sum()
    total = len(df)
    logger.info(f"HHS region mapping: {mapped:,}/{total:,} rows mapped ({100*mapped/total:.1f}%)")

    # Log unmapped jurisdictions
    unmapped_jurisdictions = df.loc[df["hhs_region"].isna(), jurisdiction_col].unique()
    if len(unmapped_jurisdictions) > 0:
        logger.warning(f"Unmapped jurisdictions: {list(unmapped_jurisdictions)}")

    return df


def add_state_flags(
    df: pd.DataFrame,
    jurisdiction_col: str = "jurisdiction"
) -> pd.DataFrame:
    """
    Add boolean flags for Southeast and comparator states.

    Args:
        df: DataFrame with jurisdiction column
        jurisdiction_col: Name of the jurisdiction column

    Returns:
        DataFrame with 'is_southeast' and 'is_comparator' columns added
    """
    config = load_config()
    geography = config["geography"]

    southeast_states = geography["southeast_states"]
    comparator_states = geography["comparator_states"]

    df = df.copy()
    df["is_southeast"] = df[jurisdiction_col].isin(southeast_states)
    df["is_comparator"] = df[jurisdiction_col].isin(comparator_states)

    # Log counts
    se_count = df["is_southeast"].sum()
    comp_count = df["is_comparator"].sum()
    logger.info(f"Southeast state rows: {se_count:,}")
    logger.info(f"Comparator state rows: {comp_count:,}")

    return df


def save_processed(
    df: pd.DataFrame,
    filename: str = "nssp_processed.parquet",
    also_csv: bool = False
) -> Path:
    """
    Save processed DataFrame to parquet.

    Args:
        df: Processed DataFrame
        filename: Output filename
        also_csv: If True, also save a CSV copy for R plotting

    Returns:
        Path to saved file
    """
    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)

    filepath = DATA_PROCESSED / filename
    df.to_parquet(filepath, index=False)

    logger.info(f"Saved processed data to {filepath}")
    logger.info(f"  Shape: {df.shape}")
    logger.info(f"  Columns: {list(df.columns)}")

    if also_csv:
        csv_path = filepath.with_suffix(".csv")
        df.to_csv(csv_path, index=False)
        logger.info(f"Saved processed CSV to {csv_path}")

    return filepath


def build_seasons(df: pd.DataFrame) -> pd.DataFrame:
    """
    Full season building pipeline.

    Applies all transformations:
    1. Normalize jurisdiction names
    2. Assign seasons
    3. Flag fixed window
    4. Filter jurisdictions
    5. Add state abbreviations
    6. Add HHS regions
    7. Add state flags

    Args:
        df: Raw DataFrame from data extraction

    Returns:
        Fully processed DataFrame
    """
    logger.info("=" * 50)
    logger.info("BUILDING SEASONS")
    logger.info("=" * 50)

    # Step 1: Assign seasons
    logger.info("\n1. Normalizing jurisdiction names...")
    df = normalize_jurisdiction_names(df)

    # Step 2: Assign seasons
    logger.info("\n2. Assigning seasons...")
    df = assign_season(df)

    # Drop rows without season assignment
    before = len(df)
    df = df[df["season"].notna()].copy()
    after = len(df)
    logger.info(f"Dropped {before - after:,} rows outside season ranges")

    # Step 3: Flag fixed window
    logger.info("\n3. Flagging fixed prophylaxis window (Oct 1 - Mar 31)...")
    df = flag_fixed_window(df)

    # Step 4: Filter jurisdictions
    logger.info("\n4. Filtering jurisdictions...")
    df = filter_jurisdictions(df)

    # Step 5: Add state abbreviations
    logger.info("\n5. Adding state abbreviations...")
    df = add_state_abbreviation(df)

    # Step 6: Add HHS regions
    logger.info("\n6. Adding HHS region mapping...")
    df = add_hhs_region(df)

    # Step 7: Add state flags
    logger.info("\n7. Adding state flags (Southeast, comparator)...")
    df = add_state_flags(df)

    logger.info("=" * 50)
    logger.info("SEASON BUILDING COMPLETE")
    logger.info(f"Final shape: {df.shape}")
    logger.info("=" * 50)

    return df


def main():
    """Main entry point for season building."""
    from src.pull_nssp import load_cached_or_fetch

    logger.info("Loading raw data...")
    df_raw = load_cached_or_fetch()

    logger.info("Building seasons...")
    df = build_seasons(df_raw)

    logger.info("Saving processed data...")
    save_processed(df)

    return df


if __name__ == "__main__":
    main()
