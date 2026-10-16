import unittest

from matching import build_index, content_tokens, match_organ, normalize

COMMISSIONS = [
    {"source_id": "301", "name": "Comisión Constitucional"},
    {"source_id": "372", "name": "Comisión de Trabajo, Economía Social, Inclusión, Seguridad Social y Migraciones"},
    {"source_id": "338", "name": "Comisión de seguimiento y evaluación de los acuerdos del Pacto de Estado en materia de violencia de género"},
    {"source_id": "343", "name": "Comisión de seguimiento y evaluación de los acuerdos del Pacto de Toledo"},
    {"source_id": "362", "name": "Comisión de Investigación de la interrupción del suministro eléctrico el 28 de abril de 2025"},
    {"source_id": "363", "name": "Comisión de Investigación sobre la interrupción del suministro eléctrico el 28 de abril de 2025 y las telecomunicaciones"},
]
INDEX = build_index(COMMISSIONS)


class NormalizeTest(unittest.TestCase):
    def test_sin_acentos_ni_prefijo(self):
        self.assertEqual(normalize("(152/1) Comisión"), "comision")
        self.assertNotIn("á", normalize("Educación"))

    def test_abreviaturas_opendata(self):
        norm = normalize("Comisión de Trabajo, Eco. Social, Inclusión, S.Social")
        self.assertIn("economia", norm)
        self.assertIn("seguridad social", norm)
        self.assertIn("investigacion", normalize("Com.Investig. algo"))

    def test_content_tokens_sin_ruido(self):
        tokens = content_tokens("Comisión de Justicia")
        self.assertEqual(tokens, {"justicia"})


class MatchTest(unittest.TestCase):
    def test_exacto(self):
        result = match_organ("Comisión Constitucional", INDEX)
        self.assertEqual((result["source_id"], result["how"]), ("301", "exacto"))

    def test_abreviado_casa_exacto(self):
        result = match_organ(
            "Comisión de Trabajo, Eco. Social, Inclusión, S.Social y Migraciones",
            INDEX,
        )
        self.assertEqual((result["source_id"], result["how"]), ("372", "exacto"))

    def test_difuso_pactos_no_se_confunden(self):
        toledo = match_organ(
            "Comisión de seguimiento y evaluación de los acuerdos Pacto de Toledo",
            INDEX,
        )
        genero = match_organ(
            "Comisión de segto. y eval. acuerdos Pacto de Estado Violencia de Género",
            INDEX,
        )
        self.assertEqual(toledo["source_id"], "343")
        self.assertEqual(genero["source_id"], "338")

    def test_ambiguo_deja_candidatos(self):
        result = match_organ(
            "(152/8) Com.Investig. interrup. suminis. eléctrico el 28 abril de 2025",
            INDEX,
        )
        self.assertEqual(result["how"], "ambiguo")
        self.assertEqual(result["source_id"], "362")
        self.assertEqual(result["candidatos"], ["362", "363"])

    def test_no_comisiones_sin_mapear(self):
        for name in ("Pleno", "Diputación Permanente", "Sesión Conjunta", ""):
            result = match_organ(name, INDEX)
            self.assertIsNone(result["source_id"])
            self.assertEqual(result["how"], "sin_mapear")


if __name__ == "__main__":
    unittest.main()
