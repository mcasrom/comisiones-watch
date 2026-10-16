import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ingest_csv import IngestError, run

ROOT = Path(__file__).resolve().parent.parent
REAL_CSV = ROOT / "tests" / "fixtures" / "composicion_301.csv"


class IngestCsvTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "csv").mkdir()
        self.db = self.tmp / "comisiones.db"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_ingiere_csv_real_sin_duplicar(self):
        shutil.copy(REAL_CSV, self.tmp / "csv" / REAL_CSV.name)
        first = run(self.tmp / "csv", self.db, cutoff="2026-10-12")
        second = run(self.tmp / "csv", self.db, cutoff="2026-10-12")
        self.assertEqual(first["errores"], [])
        self.assertEqual(first["ficheros"][0]["filas"], 85)
        self.assertEqual(first["ficheros"][0]["codigo"], "301")
        con = sqlite3.connect(self.db)
        self.assertEqual(
            con.execute("SELECT COUNT(*) FROM composition_raw").fetchone()[0], 85
        )
        self.assertEqual(
            con.execute("SELECT COUNT(*) FROM commissions").fetchone()[0], 1
        )
        self.assertEqual(second["errores"], [])
        manifest = (self.tmp / "ingest_manifest.json").read_text(encoding="utf-8")
        self.assertIn("2026-10-12", manifest)

    def test_fallo_visible_en_cabecera_organo_y_fecha(self):
        bad_header = self.tmp / "csv" / "mal.csv"
        bad_header.write_text("A;B\n1;2\n", encoding="utf-8")
        manifest = run(self.tmp / "csv", self.db, cutoff="2026-10-12")
        self.assertEqual(len(manifest["errores"]), 1)
        self.assertIn("cabecera", manifest["errores"][0])

        shutil.copy(REAL_CSV, self.tmp / "csv" / "otro.csv")
        content = (self.tmp / "csv" / "otro.csv").read_text(encoding="utf-8")
        (self.tmp / "csv" / "otro.csv").write_text(
            content.replace("Comisión Constitucional", "Comisión Inexistente"),
            encoding="utf-8",
        )
        manifest = run(self.tmp / "csv", self.db, cutoff="2026-10-12")
        self.assertTrue(any("desconocido" in e for e in manifest["errores"]))

    def test_ingiere_por_codigo_con_nombre_completo(self):
        nombre_completo = (
            "Comisión Mixta para la Coordinación y Seguimiento de la Estrategia "
            "Española para alcanzar los Objetivos de Desarrollo Sostenible (ODS)"
        )
        content = REAL_CSV.read_text(encoding="utf-8").replace(
            "Comisión Constitucional", nombre_completo
        )
        (self.tmp / "csv" / "301.csv").write_text(content, encoding="utf-8")
        manifest = run(self.tmp / "csv", self.db, cutoff="2026-10-12")
        self.assertEqual(manifest["errores"], [])
        self.assertEqual(manifest["ficheros"][0]["codigo"], "301")
        self.assertEqual(manifest["ficheros"][0]["resuelto_por"], "codigo")
        con = sqlite3.connect(self.db)
        self.assertEqual(
            con.execute("SELECT name FROM commissions WHERE source_id='301'").fetchone()[0],
            nombre_completo,
        )

    def test_sin_csv_falla(self):
        with self.assertRaises(IngestError):
            run(self.tmp / "csv", self.db, cutoff="2026-10-12")


if __name__ == "__main__":
    unittest.main()
