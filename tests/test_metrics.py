import csv
import unittest
from pathlib import Path

from metrics import (
    approved_rate,
    commission_metrics,
    cost_for_role,
)

SEED = Path(__file__).resolve().parent.parent / "rates_seed.csv"


class MetricsTest(unittest.TestCase):
    def test_seed_contains_official_2026_values_and_stays_pending(self):
        with open(SEED, newline="", encoding="utf-8") as fh:
            rates = list(csv.DictReader(fh))
        by_key = {(rate["chamber"], rate["role"]): rate for rate in rates}
        self.assertEqual(float(by_key[("congreso", "presidente")]["monthly_eur"]), 1712.50)
        self.assertEqual(float(by_key[("senado", "presidente")]["monthly_eur"]), 1738.36)
        self.assertTrue(all(rate["status"] == "pendiente_validacion" for rate in rates))
        self.assertTrue(all(rate["source_url"].startswith("https://") for rate in rates))

    def test_pending_rates_are_never_used(self):
        pending = {
            "chamber": "congreso",
            "role": "presidente",
            "status": "pendiente_validacion",
            "valid_from": "2026-01-01",
            "valid_to": "",
        }
        approved = dict(pending, status="aprobada", monthly_eur=1712.50)
        self.assertIsNone(
            approved_rate([pending], chamber="congreso", role="presidente", day=__import__("datetime").date(2026, 6, 1))
        )
        self.assertEqual(
            approved_rate([pending, approved], chamber="congreso", role="presidente", day=__import__("datetime").date(2026, 6, 1))["monthly_eur"],
            1712.50,
        )

    def test_cost_reports_nominal_and_annualized_estimate(self):
        cost = cost_for_role(1712.50, "2023-12-04", "2024-12-04", payments_per_year=14)
        self.assertGreater(cost["annualized_eur"], cost["nominal_eur"])
        self.assertEqual(cost["payments_per_year"], 14)

    def test_grace_low_and_empty_states(self):
        self.assertEqual(
            commission_metrics(
                constituted_on="2026-09-20", sessions=[], today="2026-10-12"
            )["status"],
            "periodo_gracia",
        )
        self.assertEqual(
            commission_metrics(
                constituted_on="2023-12-04", sessions=[], today="2026-10-12"
            )["status"],
            "sin_actividad",
        )
        low = commission_metrics(
            constituted_on="2023-12-04",
            sessions=[{"session_date": "2024-01-10", "kind": "comparecencia"}],
            today="2026-10-12",
            peer_median_per_month=0.2,
        )
        self.assertEqual(low["status"], "actividad_baja")
        self.assertEqual(low["sessions_substantive"], 1)

    def test_rejects_invalid_dates(self):
        with self.assertRaises(ValueError):
            commission_metrics(
                constituted_on="4/12/2023", sessions=[], today="2026-10-12"
            )


if __name__ == "__main__":
    unittest.main()
