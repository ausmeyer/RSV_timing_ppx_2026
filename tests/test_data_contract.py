import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src import data_contract


class FrozenInputContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.frozen = self.root / "data" / "manuscript"
        self.raw = self.root / "data" / "raw"
        self.frozen.mkdir(parents=True)

        self.config = {
            "socrata": {
                "dataset_id": "nssp-id",
                "base_url": "https://example.test/resource",
            },
            "nhsn": {
                "dataset_id": "nhsn-id",
                "base_url": "https://example.test/resource",
            },
            "analysis_data": {
                "start_date": "2023-07-01",
                "end_date": "2026-06-20",
                "nssp": {"filename": "nssp.parquet"},
                "nhsn": {"filename": "nhsn.parquet"},
                "census": {
                    "filename": "census.csv",
                    "url": "https://example.test/census.csv",
                },
                "state_geometry": {
                    "source_filename": "states.zip",
                    "filename": "states.rds",
                    "url": "https://example.test/states.zip",
                },
            },
        }
        payloads = {
            "nssp": ("nssp.parquet", b"exact nssp snapshot"),
            "nhsn": ("nhsn.parquet", b"exact nhsn snapshot"),
            "census": ("census.csv", b"state,population\n01,1\n"),
            "state_geometry_source": ("states.zip", b"exact geometry archive"),
            "state_geometry_prepared": ("states.rds", b"exact prepared geometry"),
        }
        files = {}
        for key, (filename, payload) in payloads.items():
            (self.frozen / filename).write_bytes(payload)
            if key == "nssp":
                provenance = {
                    "source_url": "https://example.test/resource/nssp-id.json",
                    "dataset_id": "nssp-id",
                    "query": {
                        "start_date": "2023-07-01",
                        "end_date": "2026-06-20",
                    },
                }
            elif key == "nhsn":
                provenance = {
                    "source_url": "https://example.test/resource/nhsn-id.json",
                    "dataset_id": "nhsn-id",
                    "query": (
                        "week_end >= '2023-07-01' AND "
                        "week_end <= '2026-06-20'"
                    ),
                }
            elif key == "census":
                provenance = {"source_url": "https://example.test/census.csv"}
            else:
                provenance = {"source_url": "https://example.test/states.zip"}
            files[key] = {
                "filename": filename,
                "target": f"data/raw/{filename}",
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
                "provenance": provenance,
            }

        self.manifest = {
            "schema_version": 1,
            "analysis_start_date": "2023-07-01",
            "analysis_end_date": "2026-06-20",
            "files": files,
        }
        self.manifest_path = self.frozen / "input_manifest.json"
        self._write_manifest()

    def _write_manifest(self):
        self.manifest_path.write_text(
            json.dumps(self.manifest), encoding="utf-8"
        )

    def test_materializes_all_five_verified_inputs(self):
        with mock.patch.object(data_contract, "DATA_RAW", self.raw), mock.patch.object(
            data_contract, "load_config", return_value=self.config
        ):
            materialized = data_contract.materialize_frozen_inputs(
                self.manifest_path
            )

        self.assertEqual(set(materialized), set(self.manifest["files"]))
        for key, record in self.manifest["files"].items():
            self.assertEqual(
                (self.raw / record["filename"]).read_bytes(),
                (self.frozen / record["filename"]).read_bytes(),
                key,
            )

    def test_hash_failure_happens_before_any_raw_input_is_overwritten(self):
        sentinel = b"existing live cache"
        self.raw.mkdir(parents=True)
        (self.raw / "nssp.parquet").write_bytes(sentinel)
        nhsn_path = self.frozen / "nhsn.parquet"
        nhsn_path.write_bytes(b"x" * nhsn_path.stat().st_size)

        with mock.patch.object(data_contract, "DATA_RAW", self.raw), mock.patch.object(
            data_contract, "load_config", return_value=self.config
        ):
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                data_contract.materialize_frozen_inputs(self.manifest_path)

        self.assertEqual((self.raw / "nssp.parquet").read_bytes(), sentinel)
        self.assertFalse((self.raw / "nhsn.parquet").exists())

    def test_rejects_snapshot_and_target_path_traversal(self):
        self.manifest["files"]["nssp"]["filename"] = "../nssp.parquet"
        self.manifest["files"]["nssp"]["target"] = "../outside.parquet"
        self._write_manifest()

        with mock.patch.object(data_contract, "DATA_RAW", self.raw), mock.patch.object(
            data_contract, "load_config", return_value=self.config
        ):
            with self.assertRaisesRegex(ValueError, "safe filename"):
                data_contract.verify_frozen_manifest(self.manifest_path)

        self.assertFalse(self.raw.exists())

    def test_rejects_configured_target_that_escapes_data_raw(self):
        config = copy.deepcopy(self.config)
        config["analysis_data"]["nssp"]["filename"] = "../outside.parquet"

        with mock.patch.object(
            data_contract, "load_config", return_value=config
        ):
            with self.assertRaisesRegex(ValueError, "safe filename"):
                data_contract.verify_frozen_manifest(self.manifest_path)

    def test_rejects_manifest_metadata_that_differs_from_config(self):
        self.manifest["analysis_end_date"] = "2026-06-13"
        self._write_manifest()

        with mock.patch.object(
            data_contract, "load_config", return_value=self.config
        ):
            with self.assertRaisesRegex(ValueError, "analysis_end_date"):
                data_contract.verify_frozen_manifest(self.manifest_path)

    def test_rejects_unexpected_manifest_file(self):
        self.manifest["files"]["unreviewed_extra"] = copy.deepcopy(
            self.manifest["files"]["census"]
        )
        self._write_manifest()

        with mock.patch.object(
            data_contract, "load_config", return_value=self.config
        ):
            with self.assertRaisesRegex(ValueError, "unexpected files"):
                data_contract.verify_frozen_manifest(self.manifest_path)

    def test_rejects_unexpected_snapshot_directory_file(self):
        (self.frozen / "private_notes.docx").write_bytes(b"not for release")

        with mock.patch.object(
            data_contract, "load_config", return_value=self.config
        ):
            with self.assertRaisesRegex(ValueError, "directory contains unexpected"):
                data_contract.verify_frozen_manifest(self.manifest_path)

    def test_rejects_cdc_query_with_different_cutoff(self):
        self.manifest["files"]["nssp"]["provenance"]["query"][
            "end_date"
        ] = "2026-06-13"
        self._write_manifest()

        with mock.patch.object(
            data_contract, "load_config", return_value=self.config
        ):
            with self.assertRaisesRegex(ValueError, "query dates"):
                data_contract.verify_frozen_manifest(self.manifest_path)


if __name__ == "__main__":
    unittest.main()
