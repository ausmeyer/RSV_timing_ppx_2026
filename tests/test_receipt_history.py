import unittest

import pandas as pd

from src.analysis_infant_ppx import (
    _apply_year_round_steady_state,
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

    def test_year_round_summary_exposes_only_supported_steady_state_fields(self):
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
        person_fields = (
            "median_person_activity_fractional_protection",
            "mean_person_activity_fractional_protection",
            "q25_person_activity_fractional_protection",
            "q75_person_activity_fractional_protection",
            "median_person_calendar_fractional_protection",
            "mean_person_calendar_fractional_protection",
        )
        summary = pd.DataFrame(
            [
                {
                    "window_name": "baseline_oct_mar",
                    "population_activity_weighted_protection": 0.11,
                    "share_receiving_ppx": 0.45,
                    **{field: 0.12 for field in person_fields},
                },
                {
                    "window_name": "year_round",
                    "population_activity_weighted_protection": 0.99,
                    "share_receiving_ppx": 0.99,
                    **{field: 0.99 for field in person_fields},
                },
            ]
        )

        expected_protection, expected_receipt = year_round_steady_state_metrics(
            model
        )
        result = _apply_year_round_steady_state(summary, model)
        baseline = result[result["window_name"] == "baseline_oct_mar"].iloc[0]
        year_round = result[result["window_name"] == "year_round"].iloc[0]

        self.assertAlmostEqual(
            year_round["population_activity_weighted_protection"],
            expected_protection,
        )
        self.assertAlmostEqual(
            year_round["share_receiving_ppx"],
            expected_receipt,
        )
        self.assertTrue(year_round[list(person_fields)].isna().all())
        self.assertAlmostEqual(
            baseline["population_activity_weighted_protection"],
            0.11,
        )
        self.assertAlmostEqual(baseline["share_receiving_ppx"], 0.45)
        self.assertTrue((baseline[list(person_fields)] == 0.12).all())

        birth_month_summary = pd.DataFrame(
            [
                {
                    "window_name": "year_round",
                    "share_receiving_ppx": 0.99,
                    "median_person_activity_fractional_protection": 0.99,
                    "mean_person_activity_fractional_protection": 0.99,
                }
            ]
        )
        birth_month_result = _apply_year_round_steady_state(
            birth_month_summary,
            model,
        ).iloc[0]
        self.assertAlmostEqual(
            birth_month_result["share_receiving_ppx"],
            expected_receipt,
        )
        self.assertTrue(
            pd.isna(
                birth_month_result[
                    "median_person_activity_fractional_protection"
                ]
            )
        )
        self.assertTrue(
            pd.isna(
                birth_month_result[
                    "mean_person_activity_fractional_protection"
                ]
            )
        )


if __name__ == "__main__":
    unittest.main()
