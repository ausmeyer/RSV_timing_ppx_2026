import unittest
from pathlib import Path

import pandas as pd
import yaml

from src.run_pipeline import create_infant_stress_window_summary


ROOT = Path(__file__).resolve().parents[1]


class PublicationContractTests(unittest.TestCase):
    def test_primary_model_is_in_config(self):
        config = yaml.safe_load((ROOT / "config.yaml").read_text())
        model = config["infant_ppx_model"]
        self.assertEqual(model["uptake"], 0.185)
        self.assertEqual(model["efficacy_profile"], "piecewise_linear")
        self.assertEqual(model["protection_duration_days"], 210)
        self.assertEqual(model["newborn_first_week_dose_probability"], 0.381)
        self.assertEqual(model["routine_visit_on_time_probability"], 0.59)
        self.assertEqual(model["routine_visit_delay_days"], 14)

    def test_stress_summary_is_descriptive_only(self):
        rows = []
        for jurisdiction, baseline, early in (
            ("A", 0.10, 0.13),
            ("B", 0.20, 0.22),
        ):
            for window_name, value in (
                ("baseline_oct_mar", baseline),
                ("early_sep_mar", early),
            ):
                rows.append({
                    "datasource": "nssp",
                    "metric_label": "metric",
                    "scenario_id": "reference_12mo",
                    "scenario_family": "Reference",
                    "scenario_label": "Primary model",
                    "scenario_order": 1,
                    "window_name": window_name,
                    "window_label": window_name,
                    "season": "2025-2026",
                    "jurisdiction": jurisdiction,
                    "median_person_activity_fractional_protection": value,
                    "population_activity_weighted_protection": value,
                    "share_receiving_ppx": 0.185,
                    "uptake": 0.185,
                    "efficacy_profile": "piecewise_linear",
                    "protection_duration_days": 210,
                    "exposure_censor_age_days": 365,
                    "birth_weight_scheme": "uniform",
                })
        summary = create_infant_stress_window_summary(pd.DataFrame(rows))
        self.assertNotIn("bootstrap_pr_delta_gt_zero", summary.columns)
        self.assertNotIn("delta_ci_lower", summary.columns)
        self.assertNotIn("delta_ci_upper", summary.columns)
        early = summary[summary["window_name"] == "early_sep_mar"].iloc[0]
        self.assertAlmostEqual(early["delta_vs_baseline_oct_mar"], 0.025)


if __name__ == "__main__":
    unittest.main()
