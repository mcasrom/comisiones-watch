import unittest
from pathlib import Path

from build_site import build

ROOT = Path(__file__).resolve().parent.parent


class SiteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.web = build(ROOT)
        cls.pages = {
            name: (cls.web / name).read_text(encoding="utf-8")
            for name in ("index.html", "comision-301.html", "metodologia.html")
        }

    def test_pages_are_light_accessible_and_honest(self):
        for name, html in self.pages.items():
            with self.subTest(page=name):
                self.assertLessEqual(len(html.encode("utf-8")), 300 * 1024)
                self.assertIn('<html lang="es">', html)
                self.assertIn('href="#contenido"', html)
        index = self.pages["index.html"]
        self.assertIn("Con composición", index)
        self.assertIn("Sesiones (XV)", index)
        self.assertIn("no se estima", index)
        ficha = self.pages["comision-301.html"]
        for section in ("Reuniones", "Trabajos", "Resultados", "Coste", "Composición oficial"):
            self.assertIn(section, ficha)
        self.assertIn("Sin reuniones cargadas", ficha)
        self.assertIn("dato no disponible", ficha)
        self.assertIn("SELECT COUNT(*) FROM commissions;", self.pages["metodologia.html"])
        self.assertIn("pendiente_validacion", self.pages["metodologia.html"])
        self.assertIn("emparej", self.pages["metodologia.html"])

    def test_ficha_por_comision_cargada(self):
        import sqlite3

        con = sqlite3.connect(ROOT / "data" / "comisiones.db")
        codes = [
            row[0]
            for row in con.execute(
                "SELECT DISTINCT commission_source_id FROM composition_raw"
            ).fetchall()
        ]
        self.assertGreaterEqual(len(codes), 1)
        for code in codes:
            page = self.web / f"comision-{code}.html"
            self.assertTrue(page.exists(), f"falta ficha de {code}")
            self.assertLessEqual(len(page.read_bytes()), 300 * 1024)


if __name__ == "__main__":
    unittest.main()
