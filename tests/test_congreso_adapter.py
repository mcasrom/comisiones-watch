import json
import unittest
from pathlib import Path

from adapters.congreso import (
    canonical_role,
    composition_metadata,
    detail_signals,
    discover_commissions,
    parse_composition_payload,
    parse_organ_export,
    validate_discovery,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "congreso_comisiones.html"
DETAIL_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "comision_301.html"
COMPOSITION_FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "composicion_301.json"
)


class CongresoAdapterTest(unittest.TestCase):
    def test_discovers_real_commissions_with_stable_ids(self):
        records = discover_commissions(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(50, validate_discovery(records))
        by_id = {record["source_id"]: record for record in records}
        self.assertEqual(by_id["301"]["name"], "Comisión Constitucional")
        self.assertEqual(by_id["301"]["kind"], "legislativa")
        self.assertEqual(by_id["150"]["kind"], "permanente")
        self.assertTrue(
            by_id["301"]["url"].startswith("https://www.congreso.es/comisiones?")
        )
        self.assertTrue(
            all(record["chamber"] == "congreso" for record in records)
        )

    def test_normalises_export_payload(self):
        payload = {
            "datosOrganos": [
                {
                    "indexOrgano": 301,
                    "descOrgano": "Comisión Constitucional",
                    "urlExport": "/mesa?_organos_statusOpenData=true",
                }
            ]
        }
        (record,) = parse_organ_export(payload)
        self.assertEqual(record["source_id"], "301")
        self.assertTrue(record["export_url"].startswith("https://www.congreso.es/"))

    def test_builds_official_detail_and_composition_urls(self):
        signals = detail_signals(DETAIL_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(signals["source_id"], "301")
        self.assertEqual(signals["name"], "Comisión Constitucional")
        self.assertIn("_organos_selectedSuborgano=301", signals["composition_url"])

    def test_normalises_real_composition_sample(self):
        payload = json.loads(COMPOSITION_FIXTURE.read_text(encoding="utf-8"))
        metadata = composition_metadata(payload)
        records = parse_composition_payload(payload, commission_id=301)
        president = next(
            record
            for record in records
            if record["role"] == "presidente"
        )
        self.assertEqual(len(records), 85)
        self.assertEqual(metadata["constituted_on"], "2023-12-04")
        self.assertEqual(president["full_name"], "Zaragoza Alonso, José")
        self.assertEqual(president["start_date"], "2023-12-04")
        self.assertEqual(president["end_date"], "2026-10-06")
        self.assertFalse(president["needs_role_dictionary"])
        self.assertTrue(
            any(
                record["role"] is None
                for record in records
                if record["role_raw"]["label"] in {"Adscritos", "Letrados"}
            )
        )

    def test_holds_back_unknown_roles_and_dates(self):
        (record,) = parse_composition_payload(
            {
                "data": [
                    {
                        "apellidosNombre": "Nombre de Prueba",
                        "siglas": "GP",
                        "idCargo": "999",
                        "descCargo": "Cargo no documentado",
                        "fechaAltaFormat": "04/12/2023",
                        "fechaBajaFormat": None,
                        "urlFichaDiputado": "https://www.congreso.es/ficha",
                    }
                ]
            },
            commission_id=301,
        )
        self.assertIsNone(record["role"])
        self.assertTrue(record["needs_role_dictionary"])
        self.assertEqual(canonical_role("Presidenta"), "presidente")

    def test_rejects_unexpected_shapes(self):
        with self.assertRaises(ValueError):
            parse_organ_export({"otra": []})
        with self.assertRaises(ValueError):
            parse_organ_export({"datosOrganos": [{"indexOrgano": 301}]})
        with self.assertRaises(ValueError):
            parse_composition_payload({"otro": []}, commission_id=301)
        with self.assertRaises(ValueError):
            parse_composition_payload({"data": [{"apellidosNombre": "X"}]}, commission_id=301)
        with self.assertRaises(ValueError):
            parse_composition_payload(
                {
                    "data": [
                        {
                            "apellidosNombre": "Nombre de Prueba",
                            "idCargo": "2",
                            "descCargo": "Presidente",
                            "fechaAltaFormat": "fecha no válida",
                        }
                    ]
                },
                commission_id=301,
            )
        with self.assertRaises(ValueError):
            validate_discovery([], minimum=35)


if __name__ == "__main__":
    unittest.main()
