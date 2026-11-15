import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.watch_senado import candidates

class WatchSenadoTest(unittest.TestCase):
    def test_detecta_composicion(self):
        html = '<h1>Composición de las comisiones</h1><p>Miembros y cargos</p>'
        self.assertTrue(candidates(html))
    def test_no_dispara_con_generico(self):
        self.assertEqual(candidates('<h1>Datos abiertos</h1>'), [])
    def test_no_dispara_sin_estructura(self):
        self.assertEqual(candidates('Composición de órganos'), [])
