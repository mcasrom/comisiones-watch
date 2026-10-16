import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

import ingest_opendata
from ingest_opendata import IngestOpenDataError, run

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "tests" / "fixtures" / "opendata"

SEED = [
    ("301", "Comisión Constitucional"),
    ("372", "Comisión de Trabajo, Economía Social, Inclusión, Seguridad Social y Migraciones"),
    ("379", "Comisión de Sanidad"),
]


def _seed_db(db_path):
    con = sqlite3.connect(db_path)
    con.executescript(ingest_opendata.DDL)
    con.execute("CREATE TABLE IF NOT EXISTS commissions(source_id TEXT PRIMARY KEY, name TEXT)")
    con.executemany("INSERT INTO commissions VALUES (?,?)", SEED)
    con.commit()
    con.close()


class IngestOpenDataTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.db = self.tmp / "comisiones.db"
        self.src = self.tmp / "opendata"
        shutil.copytree(SRC, self.src)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _counts(self):
        con = sqlite3.connect(self.db)
        try:
            return {
                "iniciativas": con.execute("SELECT COUNT(*) FROM iniciativas").fetchone()[0],
                "leyes": con.execute("SELECT COUNT(*) FROM leyes_aprobadas").fetchone()[0],
                "intervenciones": con.execute("SELECT COUNT(*) FROM intervenciones").fetchone()[0],
            }
        finally:
            con.close()

    def test_ingiere_todo_sin_duplicar(self):
        _seed_db(self.db)
        first = run(self.src, self.db)
        self.assertEqual(first["iniciativas"]["filas"], 4)
        self.assertEqual(first["leyes_aprobadas"]["filas"], 2)
        self.assertEqual(first["intervenciones"]["filas"], 5)
        self.assertEqual(self._counts(), {"iniciativas": 4, "leyes": 2, "intervenciones": 5})
        second = run(self.src, self.db)
        self.assertEqual(self._counts(), {"iniciativas": 4, "leyes": 2, "intervenciones": 5})
        self.assertEqual(second["intervenciones"]["filas"], 5)
        manifest = (self.tmp / "opendata_manifest.json").read_text(encoding="utf-8")
        self.assertIn("Leg.15", manifest)

    def test_casa_comisiones_y_deja_visible_lo_que_no(self):
        _seed_db(self.db)
        manifest = run(self.src, self.db)
        self.assertIn("Pleno", manifest["organos_sin_mapear"])
        con = sqlite3.connect(self.db)
        try:
            sesiones_379 = con.execute(
                "SELECT COUNT(DISTINCT sesion) FROM intervenciones"
                " WHERE commission_source_id='379'"
            ).fetchone()[0]
            self.assertEqual(sesiones_379, 2)
            comp_379 = con.execute(
                "SELECT COUNT(*) FROM intervenciones WHERE commission_source_id='379'"
                " AND lower(fase) LIKE '%comparecencia%'"
            ).fetchone()[0]
            self.assertEqual(comp_379, 2)
            linked = con.execute(
                "SELECT COUNT(*) FROM iniciativas WHERE comision_source_id IS NOT NULL"
            ).fetchone()[0]
            self.assertEqual(linked, 3)
            aprobadas = con.execute(
                "SELECT COUNT(*) FROM iniciativas WHERE comision_source_id='372'"
                " AND lower(resultado_tramitacion) LIKE '%aprobado%'"
            ).fetchone()[0]
            self.assertEqual(aprobadas, 1)
        finally:
            con.close()

    def test_ponentes_con_salto_de_linea(self):
        _seed_db(self.db)
        run(self.src, self.db)
        con = sqlite3.connect(self.db)
        try:
            ponentes = con.execute(
                "SELECT ponentes FROM iniciativas WHERE num_expediente='121/1'"
            ).fetchone()[0]
            self.assertEqual(ponentes, 2)
        finally:
            con.close()

    def test_sin_commissions_falla(self):
        con = sqlite3.connect(self.db)
        con.executescript(ingest_opendata.DDL)
        con.execute("CREATE TABLE IF NOT EXISTS commissions(source_id TEXT PRIMARY KEY, name TEXT)")
        con.commit()
        con.close()
        with self.assertRaises(IngestOpenDataError):
            run(self.src, self.db)

    def test_cabecera_inesperada_falla(self):
        _seed_db(self.db)
        (self.src / "ProyectosDeLey.csv").write_text("A;B\n1;2\n", encoding="utf-8")
        with self.assertRaises(IngestOpenDataError):
            run(self.src, self.db)


if __name__ == "__main__":
    unittest.main()
