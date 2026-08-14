"""Fetch the public inputs for the manuscript's fixed analysis date range."""

from __future__ import annotations

import argparse
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

import pandas as pd
import requests
import yaml


PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
DATA_RAW = PROJECT_ROOT / "data" / "raw"


def load_config() -> dict:
    with CONFIG_PATH.open() as handle:
        return yaml.safe_load(handle)


def _cache_path(source: str, config: dict) -> Path:
    return DATA_RAW / config["analysis_data"][source]["filename"]


def _validate(frame: pd.DataFrame, source: str, config: dict) -> None:
    contract = config["analysis_data"]
    expected_columns = contract[source]["columns"]
    missing = [column for column in expected_columns if column not in frame.columns]
    if missing:
        raise ValueError(f"{source.upper()} input is missing columns: {missing}")
    observed_end = pd.to_datetime(frame["week_end"]).max().strftime("%Y-%m-%d")
    if observed_end != contract["end_date"]:
        raise ValueError(
            f"{source.upper()} input ends {observed_end}; expected "
            f"{contract['end_date']}. Refusing to run on incomplete data."
        )


def load_cdc(source: str, *, offline: bool = False, refresh: bool = False) -> pd.DataFrame:
    """Load one explicit fixed-cutoff cache, fetching it when needed."""
    config = load_config()
    contract = config["analysis_data"]
    path = _cache_path(source, config)
    if path.exists() and not refresh:
        frame = pd.read_parquet(path)
        _validate(frame, source, config)
        return frame
    if offline:
        raise FileNotFoundError(f"Missing fixed-cutoff cache: {path}. Run `make data` first.")

    if source == "nssp":
        from src.pull_nssp import fetch_nssp

        source_config = config["socrata"]
        frame = fetch_nssp(
            source_config["dataset_id"], source_config["base_url"], config["fields"],
            contract["start_date"], contract["end_date"], source_config["timeout"],
            source_config["max_retries"], source_config["page_size"],
        )
    elif source == "nhsn":
        from src.pull_nhsn import fetch_nhsn

        source_config = config["nhsn"]
        frame = fetch_nhsn(
            source_config["dataset_id"], source_config["base_url"], config["nhsn_fields"],
            contract["start_date"], contract["end_date"], source_config["timeout"],
            source_config["max_retries"], source_config["page_size"],
        )
    else:
        raise ValueError(f"Unknown CDC source: {source}")

    _validate(frame, source, config)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return frame


def load_census(*, offline: bool = False, refresh: bool = False) -> pd.DataFrame:
    config = load_config()
    contract = config["analysis_data"]["census"]
    path = DATA_RAW / contract["filename"]
    if path.exists() and not refresh:
        return pd.read_csv(path, dtype={"state_fips": str})
    if offline:
        raise FileNotFoundError(f"Missing Census input: {path}. Run `make data` first.")

    response = requests.get(contract["url"], timeout=120)
    response.raise_for_status()
    raw = pd.read_csv(BytesIO(response.content), dtype={"STATE": str})
    raw = raw.loc[
        (raw["SUMLEV"] == 40)
        & (raw["SEX"] == 0)
        & (raw["ORIGIN"] == 0)
        & (raw["AGE"] == 0)
    ]
    raw = (
        raw.groupby(["STATE", "NAME"], as_index=False)["POPESTIMATE2023"]
        .sum()
        .sort_values("STATE")
    )
    if len(raw) != 51:
        raise ValueError(f"Expected 51 Census jurisdictions; received {len(raw)}")
    frame = pd.DataFrame({
        "jurisdiction": raw["NAME"],
        "infant_population_under1": pd.to_numeric(
            raw["POPESTIMATE2023"], errors="raise"
        ),
        "age_desc": "Age under 1 year",
        "population_year": 2023,
        "state_fips": raw["STATE"].astype(str).str.zfill(2),
        "source": (
            "U.S. Census Bureau Population Estimates Program, Vintage 2023 Annual "
            "Resident Population Estimates by Single Year of Age and Sex"
        ),
        "source_url": contract["url"],
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return frame


def _validate_state_geometry(path: Path) -> None:
    """Confirm that the cached Census archive contains a complete shapefile."""
    required_suffixes = {".shp", ".shx", ".dbf", ".prj"}
    try:
        with ZipFile(path) as archive:
            suffixes = {Path(name).suffix.lower() for name in archive.namelist()}
    except BadZipFile as exc:
        raise ValueError(f"Invalid Census state-geometry archive: {path}") from exc
    missing = sorted(required_suffixes - suffixes)
    if missing:
        raise ValueError(
            f"Census state-geometry archive is missing components: {missing}"
        )


def load_state_geometry(*, offline: bool = False, refresh: bool = False) -> Path:
    """Load the Census archive used to prepare Figure 1 state geometry."""
    config = load_config()
    contract = config["analysis_data"]["state_geometry"]
    path = DATA_RAW / contract["source_filename"]
    if path.exists() and not refresh:
        _validate_state_geometry(path)
        return path
    if offline:
        raise FileNotFoundError(
            f"Missing Census state geometry: {path}. Run `make data` first."
        )

    response = requests.get(contract["url"], timeout=120)
    response.raise_for_status()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    try:
        _validate_state_geometry(path)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


def require_prepared_state_geometry() -> Path:
    """Require the fully prepared geometry used by offline figure generation."""
    config = load_config()
    contract = config["analysis_data"]["state_geometry"]
    path = DATA_RAW / contract["filename"]
    if not path.is_file():
        raise FileNotFoundError(
            f"Missing prepared Census state geometry: {path}. Run `make data` first."
        )
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    load_cdc("nssp", offline=args.offline, refresh=args.refresh)
    load_cdc("nhsn", offline=args.offline, refresh=args.refresh)
    load_census(offline=args.offline, refresh=args.refresh)
    load_state_geometry(offline=args.offline, refresh=args.refresh)
    print("Analysis inputs are ready.")


if __name__ == "__main__":
    main()
