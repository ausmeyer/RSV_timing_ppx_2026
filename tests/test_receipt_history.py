import unittest

import pandas as pd

from src.analysis_infant_ppx import (
    _administration_date_probabilities,
    _longitudinal_administration_paths,
    year_round_steady_state_metrics,
)


class ReceiptHistoryTests(unittest.TestCase):
    def setUp(self):
        self.model = {
            "program_start_season_year": 2023,
            "newborn_first_week_dose_probability": 0.381,
            "newborn_dose_day": 0,
            "catchup_if_no_routine_visit": False,
        }

    def paths(self, birth_date: str, *, catchup: bool = False):
        model = {**self.model, "catchup_if_no_routine_visit": catchup}
        return _longitudinal_administration_paths(
            birth_date=pd.Timestamp(birth_date),
            visit_days=[7, 30, 61, 122, 183],
            window_name="early_sep_mar",
            eligibility_max_age_days=244,
            model_cfg=model,
            routine_pathway="on_time",
        )

    def test_program_launch_prevents_prelaunch_receipt(self):
        paths = self.paths("2023-03-15")
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0]["primary_date"], pd.Timestamp("2023-09-14"))
        self.assertEqual(
            paths[0]["seasonal_first_dates"],
            [pd.Timestamp("2023-09-14")],
        )

    def test_receipt_opportunities_are_carried_across_annual_windows(self):
        paths = self.paths("2024-03-15")
        newborn = next(
            path for path in paths
            if path["administration_pathway"] == "newborn_first_week"
        )
        routine = next(
            path for path in paths
            if path["administration_pathway"] == "on_time"
        )
        self.assertEqual(
            newborn["seasonal_first_dates"],
            [pd.Timestamp("2024-03-15"), pd.Timestamp("2024-09-14")],
        )
        self.assertEqual(
            routine["seasonal_first_dates"],
            [pd.Timestamp("2024-03-22"), pd.Timestamp("2024-09-14")],
        )

    def test_only_first_visit_in_an_annual_window_is_an_opportunity(self):
        paths = self.paths("2024-10-15")
        routine = next(
            path for path in paths
            if path["administration_pathway"] == "on_time"
        )
        self.assertEqual(
            routine["seasonal_first_dates"],
            [pd.Timestamp("2024-10-22")],
        )

    def test_catchup_applies_only_when_no_routine_visit_remains(self):
        no_visit_paths = self.paths("2024-02-15", catchup=True)
        no_visit_routine = next(
            path for path in no_visit_paths
            if path["administration_pathway"] == "on_time"
        )
        self.assertEqual(
            no_visit_routine["seasonal_first_dates"],
            [pd.Timestamp("2024-02-22"), pd.Timestamp("2024-09-01")],
        )

        scheduled_visit_paths = self.paths("2024-03-15", catchup=True)
        scheduled_visit_routine = next(
            path for path in scheduled_visit_paths
            if path["administration_pathway"] == "on_time"
        )
        self.assertEqual(
            scheduled_visit_routine["seasonal_first_dates"],
            [pd.Timestamp("2024-03-22"), pd.Timestamp("2024-09-14")],
        )

    def test_first_receipt_probabilities_follow_seasonal_uptake(self):
        route = {
            "primary_date": pd.Timestamp("2024-03-22"),
            "seasonal_first_dates": [
                pd.Timestamp("2024-03-22"),
                pd.Timestamp("2024-09-14"),
            ],
        }
        probabilities = _administration_date_probabilities(route, uptake=0.185)
        self.assertEqual(
            [date for date, _ in probabilities],
            [pd.Timestamp("2024-03-22"), pd.Timestamp("2024-09-14")],
        )
        self.assertAlmostEqual(probabilities[0][1], 0.185)
        self.assertAlmostEqual(probabilities[1][1], (1 - 0.185) * 0.185)
        self.assertAlmostEqual(
            sum(value for _, value in probabilities),
            1 - (1 - 0.185) ** 2,
        )

    def test_same_rule_applies_to_every_uptake_tier(self):
        route = {
            "primary_date": pd.Timestamp("2024-03-22"),
            "seasonal_first_dates": [
                pd.Timestamp("2024-03-22"),
                pd.Timestamp("2024-09-14"),
            ],
        }
        for uptake in (0.185, 0.5, 0.75, 1.0):
            with self.subTest(uptake=uptake):
                probabilities = _administration_date_probabilities(
                    route, uptake=uptake
                )
                self.assertAlmostEqual(probabilities[0][1], uptake)
                if uptake < 1:
                    self.assertAlmostEqual(
                        probabilities[1][1],
                        (1 - uptake) * uptake,
                    )
                else:
                    self.assertEqual(len(probabilities), 1)

    def test_year_round_receipt_equals_total_uptake(self):
        model = {
            **self.model,
            "uptake": 0.5,
            "eligibility_max_age_months": 8,
            "exposure_censor_age_months": 12,
            "receipt_history_mode": "seasonal_coverage_first_visit",
            "protection_delay_days": 0,
            "protection_duration_days": 210,
            "efficacy_profile": "binary",
        }
        protection, receipt = year_round_steady_state_metrics(model)
        self.assertGreater(protection, 0)
        self.assertAlmostEqual(receipt, 0.5)


if __name__ == "__main__":
    unittest.main()
