"""Adaptador mínimo y solo lectura para el Congreso.

Solo analiza HTML/XML ya descargado. No realiza peticiones de red, no inventa
selectores y conserva el identificador oficial de cada comisión.
"""
import re
from html import unescape
from urllib.parse import parse_qsl, urljoin, urlparse

BASE_URL = "https://www.congreso.es"
LISTING_PATH = "/es/comisiones"
RESOURCE_PATH = "/es/opendata/organos"
RESOURCE_ID = "resourceIDOrganos"
COMPOSITION_PATH = "/es/organos/composicion-en-la-legislatura"
COMPOSITION_RESOURCE_ID = "searchOrgano"
EXPORT_RESOURCE_ID = "opendataExport"

SECTION_KINDS = (
    ("permanentes legislativas", "legislativa"),
    ("permanentes no legislativas", "permanente"),
    ("investigación", "investigacion"),
    ("investigacion", "investigacion"),
    ("mixtas", "mixta"),
    ("subcomision", "subcomision"),
    ("ponencia", "ponencia"),
)

_ANCHOR_RE = re.compile(
    r'<a[^>]+href="([^"]*_organos_codComision=(\d+)[^"]*)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_HEADING_RE = re.compile(r"<h([1-4])[^>]*>(.*?)</h\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text):
    return re.sub(r"\s+", " ", unescape(_TAG_RE.sub(" ", text))).strip()


def _kind_for(section):
    normalized = _clean(section).lower()
    for marker, kind in SECTION_KINDS:
        if marker in normalized:
            return kind
    return "permanente"


def discover_commissions(html, base_url=BASE_URL, legislatura="XV"):
    """Devuelve comisiones del listado público del Congreso.

    Cada registro conserva el código oficial `_organos_codComision`, el nombre
    visible, la URL absoluta del detalle y la sección que permite clasificarla.
    """
    headings = [
        (match.start(), _clean(match.group(2)))
        for match in _HEADING_RE.finditer(html)
    ]
    commissions = {}
    for match in _ANCHOR_RE.finditer(html):
        raw_url, source_id, inner = match.groups()
        url = unescape(raw_url)
        query = dict(parse_qsl(urlparse(url).query))
        if query.get("_organos_selectedLegislatura", legislatura) != legislatura:
            continue
        section = next(
            (text for position, text in reversed(headings) if position < match.start()),
            "",
        )
        record = {
            "chamber": "congreso",
            "source_id": source_id,
            "name": _clean(inner),
            "section": section,
            "kind": _kind_for(section),
            "legislatura": legislatura,
            "url": urljoin(base_url, url),
        }
        commissions.setdefault(source_id, record)
    return list(commissions.values())


def parse_organ_export(payload, chamber="congreso", legislatura="XV"):
    """Normaliza la respuesta JSON del recurso `resourceIDOrganos`.

    No se llama en los tests con red: recibe un objeto ya descargado y rechaza
    explícitamente cualquier forma inesperada.
    """
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("datosOrganos"), list)
    ):
        raise ValueError("respuesta resourceIDOrganos inesperada")
    records = []
    for row in payload["datosOrganos"]:
        if not isinstance(row, dict):
            raise ValueError("fila de órgano inesperada")
        try:
            source_id = str(row["indexOrgano"])
            name = str(row["descOrgano"]).strip()
            export_url = str(row["urlExport"])
        except KeyError as exc:
            raise ValueError(f"fila de órgano incompleta: {exc}") from exc
        if not source_id or not name or not export_url:
            raise ValueError("fila de órgano incompleta")
        records.append(
            {
                "chamber": chamber,
                "source_id": source_id,
                "name": name,
                "legislatura": legislatura,
                "export_url": export_url
                if export_url.startswith(("http://", "https://"))
                else urljoin(BASE_URL, export_url),
            }
        )
    return records


def validate_discovery(records, minimum=35):
    """Puerta mínima contra un listado roto o vaciado por un cambio web."""
    if len(records) < minimum:
        raise ValueError(
            f"solo se descubrieron {len(records)} comisiones; mínimo esperado: {minimum}"
        )
    return len(records)


_ROLE_LABELS = {
    "presidente": "presidente",
    "presidenta": "presidente",
    "vicepresidente": "vicepresidente",
    "vicepresidenta": "vicepresidente",
    "secretario": "secretario",
    "secretaria": "secretario",
    "portavoz": "portavoz",
    "portavoz adjunto": "portavoz_adjunto",
    "portavoz adjunta": "portavoz_adjunto",
    "vocal": "vocal",
}


def canonical_role(label):
    """Traduce solo etiquetas oficiales conocidas; lo demás queda pendiente."""
    normalized = _clean(label or "").lower()
    if normalized.startswith("president"):
        return "presidente"
    if normalized.startswith("vicepresident"):
        return "vicepresidente"
    if normalized.startswith("secretari"):
        return "secretario"
    if normalized.startswith("portavoz adjunt"):
        return "portavoz_adjunto"
    if normalized.startswith("portavoz"):
        return "portavoz"
    if normalized.startswith("vocal"):
        return "vocal"
    return None


def _iso_date(value):
    """Convierte únicamente fechas completas DD/MM/AAAA; si no, falla visible."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    match = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", str(value).strip())
    if not match:
        raise ValueError(f"fecha oficial inesperada: {value!r}")
    day, month, year = match.groups()
    return f"{year}-{month}-{day}"


def detail_signals(html, base_url=BASE_URL, legislatura="XV"):
    """Extrae los identificadores y endpoints oficiales de una ficha real."""
    title_match = re.search(r'decodeURI\("([^"]+)"\)', html)
    code_match = re.search(r'var\s+codigoOrgano\s*=\s*"(\d+)"', html)
    sup_match = re.search(r'var\s+codigoOrganoSup\s*=\s*"(\d+)"', html)
    if not (title_match and code_match and sup_match):
        raise ValueError("ficha de comisión sin identificadores oficiales")
    code = code_match.group(1)
    sup = sup_match.group(1)
    query = (
        f"?p_p_id=organos&p_p_lifecycle=0&p_p_state=normal&p_p_mode=view"
        f"&_organos_selectedLegislatura={legislatura}"
        f"&_organos_selectedOrganoSup={sup}&_organos_selectedSuborgano={code}"
    )
    return {
        "name": _clean(unescape(title_match.group(1))),
        "source_id": code,
        "sup_id": sup,
        "legislatura": legislatura,
        "composition_url": urljoin(
            base_url, COMPOSITION_PATH + query
        ),
    }


def composition_metadata(payload):
    """Extrae constitución y disolución con el formato oficial DD/MM/AAAA."""
    if not isinstance(payload, dict):
        raise ValueError("respuesta searchOrgano inesperada")
    try:
        constituted = payload["fechaConstitucion"]["fechaConstitucion"]
        dissolved = payload["fechaDisolucion"]["fechaDisolucion"]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"metadatos de composición incompletos: {exc}") from exc
    return {
        "constituted_on": _iso_date(constituted),
        "closed_on": _iso_date(dissolved),
    }


def parse_composition_payload(payload, commission_id):
    """Valida la forma exacta usada por el Congreso para la composición.

    Convierte solo fechas completas DD/MM/AAAA y deja pendiente cualquier cargo
    cuya etiqueta oficial no esté en el diccionario.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("respuesta searchOrgano inesperada")
    records = []
    for row in payload["data"]:
        if not isinstance(row, dict):
            raise ValueError("fila de composición inesperada")
        try:
            name = str(row["apellidosNombre"]).strip()
            cargo_id = str(row["idCargo"])
            cargo_label = str(row["descCargo"]).strip()
        except KeyError as exc:
            raise ValueError(f"fila de composición incompleta: {exc}") from exc
        if not name or not cargo_id or not cargo_label:
            raise ValueError("fila de composición incompleta")
        role = canonical_role(cargo_label)
        records.append(
            {
                "commission_id": commission_id,
                "full_name": name,
                "party": str(row.get("siglas") or "").strip() or None,
                "role_raw": {"id": cargo_id, "label": cargo_label},
                "role": role,
                "start_date": _iso_date(row.get("fechaAltaFormat")),
                "end_date": _iso_date(row.get("fechaBajaFormat")),
                "profile_url": row.get("urlFichaDiputado"),
                "needs_role_dictionary": role is None,
            }
        )
    return records
