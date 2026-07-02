"""
Data extraction from CDC NSSP Emergency Department RSV Visit dataset.

Handles paginated extraction with exponential backoff, schema validation,
and caching to parquet files.
"""

import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
import yaml

# Configure logging
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Project root directory
PROJECT_ROOT = Path(__file__).parent.parent
DATA_RAW = PROJECT_ROOT / "data" / "raw"
CONFIG_PATH = PROJECT_ROOT / "config.yaml"


def load_config() -> dict:
    """Load configuration from config.yaml."""
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def fetch_schema(dataset_id: str, base_url: str, timeout: int = 30) -> dict:
    """
    Fetch Socrata dataset metadata and validate required fields exist.

    Args:
        dataset_id: Socrata dataset identifier
        base_url: Base URL for Socrata API
        timeout: Request timeout in seconds

    Returns:
        Dictionary with column names and types
    """
    # Socrata metadata endpoint
    metadata_url = f"https://data.cdc.gov/api/views/{dataset_id}.json"

    logger.info(f"Fetching schema from {metadata_url}")

    response = requests.get(metadata_url, timeout=timeout)
    response.raise_for_status()

    metadata = response.json()

    # Extract column information
    columns = {}
    for col in metadata.get("columns", []):
        columns[col["fieldName"]] = {
            "name": col.get("name", ""),
            "dataTypeName": col.get("dataTypeName", ""),
            "description": col.get("description", "")
        }

    schema = {
        "dataset_id": dataset_id,
        "name": metadata.get("name", ""),
        "description": metadata.get("description", ""),
        "columns": columns,
        "row_count": metadata.get("rowCount", 0),
        "fetched_at": datetime.now().isoformat()
    }

    return schema


def validate_schema(schema: dict, required_fields: dict) -> bool:
    """
    Validate that required fields exist in the schema.

    Args:
        schema: Schema dictionary from fetch_schema
        required_fields: Dictionary mapping field names to expected Socrata field names

    Returns:
        True if all required fields present

    Raises:
        ValueError: If required fields are missing
    """
    available = set(schema["columns"].keys())
    missing = []

    for field_name, socrata_name in required_fields.items():
        if socrata_name not in available:
            missing.append(f"{field_name} ({socrata_name})")

    if missing:
        raise ValueError(
            f"Missing required fields in dataset: {', '.join(missing)}\n"
            f"Available fields: {sorted(available)}"
        )

    logger.info(f"Schema validation passed. All {len(required_fields)} required fields present.")
    return True


def fetch_nssp_page(
    dataset_id: str,
    base_url: str,
    fields: list[str],
    start_date: str,
    end_date: str,
    date_field: str,
    limit: int,
    offset: int,
    timeout: int
) -> list[dict]:
    """Fetch a single page of data from Socrata."""

    # Build query - filter to state-level data only using trend_source
    select = ",".join(fields)
    where = (
        f"{date_field} >= '{start_date}' AND {date_field} <= '{end_date}' "
        f"AND trend_source = 'State'"
    )

    url = f"{base_url}/{dataset_id}.json"
    params = {
        "$select": select,
        "$where": where,
        "$limit": limit,
        "$offset": offset,
        "$order": f"{date_field} ASC"
    }

    response = requests.get(url, params=params, timeout=timeout)
    response.raise_for_status()

    return response.json()


def fetch_nssp(
    dataset_id: str,
    base_url: str,
    fields: dict,
    start_date: str,
    end_date: str,
    timeout: int = 30,
    max_retries: int = 3,
    page_size: int = 50000
) -> pd.DataFrame:
    """
    Fetch NSSP data from Socrata with pagination and retry logic.

    Args:
        dataset_id: Socrata dataset identifier
        base_url: Base URL for Socrata API
        fields: Dictionary mapping logical names to Socrata field names
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        timeout: Request timeout in seconds
        max_retries: Maximum retry attempts per page
        page_size: Number of records per page

    Returns:
        DataFrame with extracted data
    """
    # Get list of Socrata field names to select
    socrata_fields = list(fields.values())
    date_field = fields["week_end"]

    all_records = []
    offset = 0

    logger.info(f"Fetching NSSP data from {start_date} to {end_date}")

    while True:
        # Retry logic with exponential backoff
        for attempt in range(max_retries):
            try:
                records = fetch_nssp_page(
                    dataset_id=dataset_id,
                    base_url=base_url,
                    fields=socrata_fields,
                    start_date=start_date,
                    end_date=end_date,
                    date_field=date_field,
                    limit=page_size,
                    offset=offset,
                    timeout=timeout
                )
                break
            except requests.exceptions.RequestException as e:
                wait_time = 2 ** attempt
                logger.warning(
                    f"Request failed (attempt {attempt + 1}/{max_retries}): {e}. "
                    f"Retrying in {wait_time}s..."
                )
                if attempt == max_retries - 1:
                    raise
                time.sleep(wait_time)

        if not records:
            break

        all_records.extend(records)
        logger.info(f"Fetched {len(all_records)} records so far...")

        if len(records) < page_size:
            break

        offset += page_size

    logger.info(f"Total records fetched: {len(all_records)}")

    # Convert to DataFrame
    df = pd.DataFrame(all_records)

    # Rename columns from Socrata names to logical names
    reverse_mapping = {v: k for k, v in fields.items()}
    df = df.rename(columns=reverse_mapping)

    # Convert date column
    df["week_end"] = pd.to_datetime(df["week_end"])

    # Convert numeric columns
    numeric_cols = ["rsv_pct", "rsv_pct_smoothed", "covid_pct", "flu_pct", "combined_pct"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Rename geography to jurisdiction for consistency with rest of pipeline
    if "geography" in df.columns:
        df = df.rename(columns={"geography": "jurisdiction"})

    return df


def cache_raw_data(df: pd.DataFrame, pull_date: Optional[datetime] = None) -> Path:
    """
    Save raw data to parquet with timestamp.

    Args:
        df: DataFrame to cache
        pull_date: Date of pull (defaults to now)

    Returns:
        Path to cached file
    """
    if pull_date is None:
        pull_date = datetime.now()

    DATA_RAW.mkdir(parents=True, exist_ok=True)

    filename = f"nssp_raw_{pull_date.strftime('%Y%m%d')}.parquet"
    filepath = DATA_RAW / filename

    df.to_parquet(filepath, index=False)
    logger.info(f"Cached raw data to {filepath}")

    return filepath


def cache_schema(schema: dict) -> Path:
    """Save schema to JSON file."""
    DATA_RAW.mkdir(parents=True, exist_ok=True)

    filepath = DATA_RAW / "schema.json"
    with open(filepath, "w") as f:
        json.dump(schema, f, indent=2)

    logger.info(f"Cached schema to {filepath}")
    return filepath


def get_cached_file(max_age_days: Optional[int] = 1) -> Optional[Path]:
    """
    Find most recent cached data file within age limit.

    Args:
        max_age_days: Maximum age of cache in days. If None, use the most
            recent cache file regardless of age.

    Returns:
        Path to cached file if found and fresh, None otherwise
    """
    if not DATA_RAW.exists():
        return None

    parquet_files = list(DATA_RAW.glob("nssp_raw_*.parquet"))

    if not parquet_files:
        return None

    # Sort by modification time, most recent first
    parquet_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    most_recent = parquet_files[0]
    mtime = datetime.fromtimestamp(most_recent.stat().st_mtime)
    age = datetime.now() - mtime

    if max_age_days is None:
        logger.info(f"Using cached data from {most_recent} (age: {age}; age check disabled)")
        return most_recent

    if age <= timedelta(days=max_age_days):
        logger.info(f"Using cached data from {most_recent} (age: {age})")
        return most_recent

    logger.info(f"Cache too old ({age}), will fetch fresh data")
    return None


def load_cached_or_fetch(
    max_age_days: Optional[int] = 1,
    force_refresh: bool = False
) -> pd.DataFrame:
    """
    Load cached data if fresh enough, otherwise fetch from Socrata.

    Args:
        max_age_days: Maximum age of cache in days. If None, use the most
            recent cache file regardless of age.
        force_refresh: If True, always fetch fresh data

    Returns:
        DataFrame with NSSP data
    """
    config = load_config()
    socrata_config = config["socrata"]
    fields = config["fields"]
    seasons = config["seasons"]

    # Determine date range from seasons
    start_date = min(s["start"] for s in seasons)
    end_date = max(s["end"] for s in seasons)

    # Check cache first
    if not force_refresh:
        cached_file = get_cached_file(max_age_days)
        if cached_file:
            return pd.read_parquet(cached_file)

    # Fetch schema and validate
    schema = fetch_schema(
        dataset_id=socrata_config["dataset_id"],
        base_url=socrata_config["base_url"],
        timeout=socrata_config["timeout"]
    )
    validate_schema(schema, fields)
    cache_schema(schema)

    # Fetch data
    df = fetch_nssp(
        dataset_id=socrata_config["dataset_id"],
        base_url=socrata_config["base_url"],
        fields=fields,
        start_date=start_date,
        end_date=end_date,
        timeout=socrata_config["timeout"],
        max_retries=socrata_config["max_retries"],
        page_size=socrata_config["page_size"]
    )

    # Cache and return
    cache_raw_data(df)

    return df


def log_row_counts(df: pd.DataFrame) -> None:
    """Log summary statistics about the data."""
    logger.info("DATA SUMMARY")

    logger.info(f"Total rows: {len(df):,}")
    logger.info(f"Date range: {df['week_end'].min()} to {df['week_end'].max()}")
    logger.info(f"Jurisdictions: {df['jurisdiction'].nunique()}")

    # Row counts by jurisdiction
    jurisdiction_counts = df.groupby("jurisdiction").size().sort_values(ascending=False)
    logger.info("\nRows by jurisdiction (top 10):")
    for jur, count in jurisdiction_counts.head(10).items():
        logger.info(f"  {jur}: {count:,}")

    # Missing values
    missing = df[["rsv_pct", "rsv_pct_smoothed"]].isnull().sum()
    logger.info("\nMissing values:")
    for col, count in missing.items():
        pct = 100 * count / len(df)
        logger.info(f"  {col}: {count:,} ({pct:.1f}%)")

    # RSV percentage summary
    logger.info("\nRSV visit percentage summary:")
    logger.info(f"  Mean: {df['rsv_pct'].mean():.2f}%")
    logger.info(f"  Median: {df['rsv_pct'].median():.2f}%")
    logger.info(f"  Max: {df['rsv_pct'].max():.2f}%")



def main():
    """Main entry point for data extraction."""
    logger.info("Starting NSSP data extraction...")

    df = load_cached_or_fetch(max_age_days=1)
    log_row_counts(df)

    logger.info("Data extraction complete.")
    return df


if __name__ == "__main__":
    main()
