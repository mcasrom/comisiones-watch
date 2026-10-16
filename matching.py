#!/usr/bin/env python3
"""Emparejado de nombres de órgano del opendata con nuestras comisiones.

Los ficheros masivos del Congreso (`ProyectosDeLey`, `Intervenciones…`) usan
nombres abreviados y a veces truncados ("Eco. Social", "S.Social", "Parlam.",
"Com.Investig."). Nuestra tabla `commissions` guarda el nombre oficial completo.
Este módulo casa ambos:

1. **Normalización**: minúsculas, sin acentos, sin prefijos `(152/1)`, con un
   pequeño diccionario de abreviaturas oficiales, y sin puntuación.
2. **Exacto** sobre el nombre normalizado.
3. **Difuso** por solapamiento de palabras significativas (contención), útil
   para las comisiones de investigación, cuyo nombre del opendata es solo una
   pista ("...interrup. suminis. eléctrico el 28 abril de 2025").

Nunca adivina en silencio: si dos candidatas empatan, marca `ambiguo`. Si nada
supera el umbral, devuelve un motivo para que el fallo quede visible.
"""
import re
import unicodedata

# Abreviaturas usadas por el opendata -> forma normalizada de nuestro nombre.
# Se aplican EN minúsculas y sin acentos, antes de quitar la puntuación.
_ABBREVIATIONS = (
    ("com.investig.", "comision investigacion"),
    ("investig.", "investigacion"),
    ("s.social", "seguridad social"),
    ("segsoc", "seguridad social"),
    ("eco.", "economia"),
    ("parlam.", "parlamentario"),
    ("segto.", "seguimiento"),
    ("eval.", "evaluacion"),
    ("reform.", "reformas"),
    ("inst.", "institucionales"),
    ("leg.", "legales"),
    ("suminis.", "suministro"),
    ("interrup.", "interrupcion"),
)

# Palabras que no discriminan entre comisiones.
_STOPWORDS = frozenset(
    {
        "comision",
        "de",
        "del",
        "la",
        "el",
        "los",
        "las",
        "y",
        "e",
        "o",
        "u",
        "para",
        "sobre",
        "en",
        "a",
        "con",
        "por",
        "al",
    }
)

_PREFIX_RE = re.compile(r"\(\s*\d+\s*/\s*\d+\s*\)")
_NON_WORD_RE = re.compile(r"[^a-z0-9 ]")
_WS_RE = re.compile(r"\s+")

MIN_INTERSECTION = 2
MIN_CONTAINMENT = 0.5


def strip_accents(text):
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize(name):
    """Devuelve la forma canónica comparable de un nombre de órgano."""
    text = strip_accents((name or "").replace("\n", " ")).lower()
    text = _PREFIX_RE.sub(" ", text)
    for needle, replacement in _ABBREVIATIONS:
        text = text.replace(needle, replacement)
    text = _NON_WORD_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


def content_tokens(name):
    """Palabras significativas (sin ruido), como conjunto."""
    return {token for token in normalize(name).split() if token not in _STOPWORDS}


def build_index(commissions):
    """`commissions` es una lista de dicts con `source_id` y `name`."""
    by_id = {item["source_id"]: item for item in commissions}
    by_norm = {}
    for item in commissions:
        by_norm.setdefault(normalize(item["name"]), item["source_id"])
    tokens = {item["source_id"]: content_tokens(item["name"]) for item in commissions}
    return {"by_id": by_id, "by_norm": by_norm, "tokens": tokens}


def match_organ(name, index):
    """Casa un nombre del opendata con una comisión.

    Devuelve un dict con `source_id` (o `None`), `how` (`exacto`, `difuso`,
    `ambiguo`, `sin_mapear`) y `score`.
    """
    norm = normalize(name)
    exact = index["by_norm"].get(norm)
    if exact:
        return {"source_id": exact, "how": "exacto", "score": 1.0}
    organ_tokens = content_tokens(name)
    if len(organ_tokens) < MIN_INTERSECTION:
        return {"source_id": None, "how": "sin_mapear", "score": 0.0}
    scored = []
    for source_id, commission_tokens in index["tokens"].items():
        if not commission_tokens:
            continue
        inter = len(organ_tokens & commission_tokens)
        if not inter:
            continue
        containment = inter / min(len(organ_tokens), len(commission_tokens))
        if inter >= MIN_INTERSECTION and containment >= MIN_CONTAINMENT:
            scored.append((containment, inter, source_id))
    if not scored:
        return {"source_id": None, "how": "sin_mapear", "score": 0.0}
    scored.sort(reverse=True)
    best_containment, best_inter, best_id = scored[0]
    ties = [row[2] for row in scored if row[0] == best_containment and row[1] == best_inter]
    if len(ties) > 1:
        return {
            "source_id": min(ties),
            "how": "ambiguo",
            "score": round(best_containment, 3),
            "candidatos": sorted(ties),
        }
    return {"source_id": best_id, "how": "difuso", "score": round(best_containment, 3)}
