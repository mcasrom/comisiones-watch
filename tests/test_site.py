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
        self.assertIn("50 comisiones descubiertas", self.pages["index.html"])
        self.assertIn("dato no disponible", self.pages["index.html"])
        self.assertIn("Sin sesiones cargadas", self.pages["comision-301.html"])
        self.assertIn("SELECT COUNT(*) FROM commissions;", self.pages["metodologia.html"])
        self.assertIn("pendiente_validacion", self.pages["metodologia.html"])


if __name__ == "__main__":
    unittest.main()
