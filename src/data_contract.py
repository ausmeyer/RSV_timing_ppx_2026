"""Fetch live inputs or materialize the frozen manuscript input snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

import pandas as pd
import requests
import yaml


PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
DATA_RAW = PROJECT_ROOT / "data" / "raw"
FROZEN_DATA = PROJECT_ROOT / "data" / "manuscript"
FROZEN_MANIFEST = FROZEN_DATA / "input_manifest.json"

FROZEN_SCHEMA_VERSION = 1
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def load_config() -> dict:
    with CONFIG_PATH.open() as handle:
        return yaml.safe_load(handle)


def _cache_path(source: str, config: dict) -> Path:
    return DATA_RAW / config["analysis_data"][source]["filename"]


def _frozen_targets(config: dict) -> dict[str, str]:
    """Map required manifest keys to their existing ``data/raw`` filenames."""
    contract = config["analysis_data"]
    return {
        "nssp": contract["nssp"]["filename"],
        "nhsn": contract["nhsn"]["filename"],
        "census": contract["census"]["filename"],
        "state_geometry_source": contract["state_geometry"]["source_filename"],
        "state_geometry_prepared": contract["state_geometry"]["filename"],
    }


def _expected_source_url(key: str, config: dict) -> str:
    if key in {"nssp", "nhsn"}:
        source = config["socrata"] if key == "nssp" else config["nhsn"]
        return f"{source['base_url'].rstrip('/')}/{source['dataset_id']}.json"
    if key == "census":
        return config["analysis_data"]["census"]["url"]
    return config["analysis_data"]["state_geometry"]["url"]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_snapshot_name(value: object, *, key: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"Frozen input {key!r} has no filename")
    path = Path(value)
    if path.is_absolute() or len(path.parts) != 1 or value in {".", ".."}:
        raise ValueError(
            f"Frozen input {key!r} filename must be a single safe filename: {value!r}"
        )
    if "\\" in value:
        raise ValueError(f"Frozen input {key!r} filename contains a path separator")
    return value


def _validate_provenance(key: str, provenance: object, config: dict) -> None:
    if not isinstance(provenance, dict):
        raise ValueError(f"Frozen input {key!r} provenance must be an object")
    source_url = provenance.get("source_url")
    if not isinstance(source_url, str) or not source_url:
        raise ValueError(f"Frozen input {key!r} provenance requires source_url")
    expected_url = _expected_source_url(key, config)
    if source_url.rstrip("/") != expected_url.rstrip("/"):
        raise ValueError(
            f"Frozen input {key!r} source_url is {source_url!r}; "
            f"expected {expected_url!r}"
        )

    if key not in {"nssp", "nhsn"}:
        return

    source = config["socrata"] if key == "nssp" else config["nhsn"]
    if provenance.get("dataset_id") != source["dataset_id"]:
        raise ValueError(
            f"Frozen input {key!r} dataset_id does not match config.yaml"
        )
    query = provenance.get("query")
    if not isinstance(query, (dict, str)) or not query:
        raise ValueError(f"Frozen input {key!r} provenance requires a query")
    start_date = config["analysis_data"]["start_date"]
    end_date = config["analysis_data"]["end_date"]
    if isinstance(query, dict):
        if query.get("start_date") != start_date or query.get("end_date") != end_date:
            raise ValueError(
                f"Frozen input {key!r} query dates do not match config.yaml"
            )
    elif start_date not in query or end_date not in query:
        raise ValueError(
            f"Frozen input {key!r} query must record both analysis cutoff dates"
        )


def verify_frozen_manifest(
    manifest_path: Path = FROZEN_MANIFEST,
) -> dict[str, tuple[Path, Path]]:
    """Verify the frozen input manifest and every snapshot before any writes.

    Returns a mapping from the five required logical input names to verified
    ``(snapshot, data/raw target)`` paths.  Manifest targets are required to
    exactly match the filenames already consumed by the offline pipeline.
    """
    config = load_config()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"Missing frozen-input manifest: {manifest_path}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid frozen-input manifest JSON: {manifest_path}") from exc

    if not isinstance(manifest, dict):
        raise ValueError("Frozen-input manifest must be a JSON object")
    if manifest.get("schema_version") != FROZEN_SCHEMA_VERSION:
        raise ValueError(
            "Frozen-input manifest schema_version must be "
            f"{FROZEN_SCHEMA_VERSION}"
        )

    contract = config["analysis_data"]
    if manifest.get("analysis_start_date") != contract["start_date"]:
        raise ValueError("Frozen-input manifest analysis_start_date does not match config.yaml")
    if manifest.get("analysis_end_date") != contract["end_date"]:
        raise ValueError("Frozen-input manifest analysis_end_date does not match config.yaml")

    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ValueError("Frozen-input manifest files must be an object")

    expected_targets = {
        key: _safe_snapshot_name(filename, key=f"{key} target")
        for key, filename in _frozen_targets(config).items()
    }
    approved_directory_files = {
        "README.md",
        manifest_path.name,
        *expected_targets.values(),
    }
    unexpected_directory_files = sorted(
        path.name
        for path in manifest_path.parent.iterdir()
        if path.is_file() and path.name not in approved_directory_files
    )
    if unexpected_directory_files:
        raise ValueError(
            "Frozen-input directory contains unexpected files: "
            f"{unexpected_directory_files}"
        )

    missing = sorted(set(expected_targets) - set(files))
    if missing:
        raise ValueError(f"Frozen-input manifest is missing required files: {missing}")
    unexpected = sorted(set(files) - set(expected_targets))
    if unexpected:
        raise ValueError(
            f"Frozen-input manifest contains unexpected files: {unexpected}"
        )

    verified: dict[str, tuple[Path, Path]] = {}
    for key, target_filename in expected_targets.items():
        record = files[key]
        if not isinstance(record, dict):
            raise ValueError(f"Frozen input {key!r} metadata must be an object")

        filename = _safe_snapshot_name(record.get("filename"), key=key)
        if filename != target_filename:
            raise ValueError(
                f"Frozen input {key!r} filename is {filename!r}; "
                f"expected {target_filename!r}"
            )

        expected_target = f"data/raw/{target_filename}"
        if record.get("target") != expected_target:
            raise ValueError(
                f"Frozen input {key!r} target must be {expected_target!r}"
            )

        expected_hash = record.get("sha256")
        if not isinstance(expected_hash, str) or not _SHA256_RE.fullmatch(expected_hash):
            raise ValueError(f"Frozen input {key!r} has an invalid sha256")
        expected_bytes = record.get("bytes")
        if (
            not isinstance(expected_bytes, int)
            or isinstance(expected_bytes, bool)
            or expected_bytes < 1
        ):
            raise ValueError(f"Frozen input {key!r} has an invalid byte count")

        _validate_provenance(key, record.get("provenance"), config)

        snapshot = manifest_path.parent / filename
        if not snapshot.is_file():
            raise FileNotFoundError(f"Missing frozen input {key!r}: {snapshot}")
        observed_bytes = snapshot.stat().st_size
        if observed_bytes != expected_bytes:
            raise ValueError(
                f"Frozen input {key!r} is {observed_bytes} bytes; "
                f"expected {expected_bytes}"
            )
        observed_hash = _sha256(snapshot)
        if observed_hash != expected_hash:
            raise ValueError(
                f"Frozen input {key!r} SHA-256 is {observed_hash}; "
                f"expected {expected_hash}"
            )
        verified[key] = (snapshot, DATA_RAW / target_filename)

    return verified


def materialize_frozen_inputs(
    manifest_path: Path = FROZEN_MANIFEST,
) -> dict[str, Path]:
    """Atomically copy verified manuscript snapshots to pipeline cache paths."""
    verified = verify_frozen_manifest(manifest_path)
    DATA_RAW.mkdir(parents=True, exist_ok=True)

    staged: list[tuple[Path, Path]] = []
    try:
        for snapshot, target in verified.values():
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{target.name}.", suffix=".tmp", dir=DATA_RAW
            )
            os.close(descriptor)
            temporary = Path(temporary_name)
            shutil.copyfile(snapshot, temporary)
            staged.append((temporary, target))

        for temporary, target in staged:
            os.replace(temporary, target)
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)

    return {key: target for key, (_, target) in verified.items()}


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
        raise FileNotFoundError(
            f"Missing fixed-cutoff cache: {path}. Run `make frozen-data` for "
            "manuscript inputs or `make data` for the current live view."
        )

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
        raise FileNotFoundError(
            f"Missing Census input: {path}. Run `make frozen-data` for manuscript "
            "inputs or `make data` for the current live view."
        )

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
            f"Missing Census state geometry: {path}. Run `make frozen-data` for "
            "manuscript inputs or `make data` for the current live view."
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
            f"Missing prepared Census state geometry: {path}. Run `make "
            "frozen-data` for manuscript inputs or `make data` for the current "
            "live view."
        )
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument(
        "--materialize-frozen",
        action="store_true",
        help=(
            "verify data/manuscript/input_manifest.json and copy its exact "
            "snapshots to the data/raw paths used by the offline pipeline"
        ),
    )
    args = parser.parse_args()
    if args.materialize_frozen:
        if args.refresh:
            parser.error("--materialize-frozen cannot be combined with --refresh")
        materialized = materialize_frozen_inputs()
        print(f"Verified and materialized {len(materialized)} frozen inputs.")
        return
    load_cdc("nssp", offline=args.offline, refresh=args.refresh)
    load_cdc("nhsn", offline=args.offline, refresh=args.refresh)
    load_census(offline=args.offline, refresh=args.refresh)
    load_state_geometry(offline=args.offline, refresh=args.refresh)
    print("Analysis inputs are ready.")


if __name__ == "__main__":
    main()
