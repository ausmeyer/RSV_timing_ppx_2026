"""
Data extraction from CDC NHSN Weekly Hospital Respiratory Data (HRD).

Handles paginated extraction with exponential backoff, schema validation,
and caching to parquet files.
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
import yaml

# Configure logging
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s - %(levelname)s - %(message)s"
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
    metadata_url = f"https://data.cdc.gov/api/views/{dataset_id}.json"

    logger.info(f"Fetching schema from {metadata_url}")

    response = requests.get(metadata_url, timeout=timeout)
    response.raise_for_status()

    metadata = response.json()

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


def fetch_nhsn_page(
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
    select = ",".join(fields)
    where = f"{date_field} >= '{start_date}' AND {date_field} <= '{end_date}'"

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


def fetch_nhsn(
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
    Fetch NHSN HRD data from Socrata with pagination and retry logic.

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
    socrata_fields = list(fields.values())
    date_field = fields["week_end"]

    all_records = []
    offset = 0

    logger.info(f"Fetching NHSN HRD data from {start_date} to {end_date}")

    while True:
        for attempt in range(max_retries):
            try:
                records = fetch_nhsn_page(
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

    df = pd.DataFrame(all_records)

    reverse_mapping = {v: k for k, v in fields.items()}
    df = df.rename(columns=reverse_mapping)

    df["week_end"] = pd.to_datetime(df["week_end"])

    numeric_cols = ["rsv_ped_0_4", "rsv_ped_total", "rsv_total"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

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

    filename = f"nhsn_raw_{pull_date.strftime('%Y%m%d')}.parquet"
    filepath = DATA_RAW / filename

    df.to_parquet(filepath, index=False)
    logger.info(f"Cached raw data to {filepath}")

    return filepath


def cache_schema(schema: dict) -> Path:
    """Save schema to JSON file."""
    DATA_RAW.mkdir(parents=True, exist_ok=True)

    filepath = DATA_RAW / "nhsn_schema.json"
    with open(filepath, "w") as f:
        json.dump(schema, f, indent=2)

    logger.info(f"Cached schema to {filepath}")
    return filepath


def log_row_counts(df: pd.DataFrame) -> None:
    """Log summary statistics about the data."""
    logger.info("NHSN DATA SUMMARY")

    logger.info(f"Total rows: {len(df):,}")
    logger.info(f"Date range: {df['week_end'].min()} to {df['week_end'].max()}")
    logger.info(f"Jurisdictions: {df['jurisdiction'].nunique()}")

    jurisdiction_counts = df.groupby("jurisdiction").size().sort_values(ascending=False)
    logger.info("\nRows by jurisdiction (top 10):")
    for jur, count in jurisdiction_counts.head(10).items():
        logger.info(f"  {jur}: {count:,}")

    value_cols = ["rsv_ped_0_4", "rsv_ped_total", "rsv_total"]
    missing = df[value_cols].isnull().sum()
    logger.info("\nMissing values:")
    for col, count in missing.items():
        pct = 100 * count / len(df)
        logger.info(f"  {col}: {count:,} ({pct:.1f}%)")



def main():
    """Validate or download the accepted-manuscript NHSN snapshot."""
    from src.data_contract import load_cdc

    logger.info("Loading publication NHSN snapshot...")
    df = load_cdc("nhsn")
    log_row_counts(df)
    logger.info("Publication NHSN snapshot validated.")
    return df


if __name__ == "__main__":
    main()
