"""Métricas mínimas de actividad y coste estimado.

Todo es cálculo puro sobre datos ya normalizados. No accede a la red, no
inventa tarifas y nunca mezcla tarifas pendientes de validación con el coste
publicado. El coste es siempre una ESTIMACIÓN.
"""
from datetime import date

SUBSTANTIVE_KINDS = ("comparecencia", "debate")
DAYS_PER_MONTH = 30.4375
GRACE_DAYS = 90


def parse_day(value, *, field):
    """Acepta únicamente fechas ISO completas; lo demás es fallo visible."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        year, month, day = str(value).split("-")
        return date(int(year), int(month), int(day))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"fecha inválida en {field}: {value!r}") from exc


def months_between(start, end):
    if end < start:
        raise ValueError("el fin no puede ser anterior al inicio")
    return (end - start).days / DAYS_PER_MONTH


def approved_rate(rates, *, chamber, role, day):
    """Devuelve la tarifa aprobada vigente en una fecha concreta."""
    candidates = [
        rate
        for rate in rates
        if rate.get("status") == "aprobada"
        and rate.get("chamber") == chamber
        and rate.get("role") == role
        and parse_day(rate.get("valid_from"), field="valid_from") <= day
        and (
            rate.get("valid_to") in (None, "")
            or parse_day(rate.get("valid_to"), field="valid_to") >= day
        )
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda rate: str(rate.get("valid_from")))


def cost_for_role(monthly_eur, start, end, *, payments_per_year=14):
    """Coste estimado: mensualidad nominal × meses, más equivalente anualizado.

    Las fuentes oficiales parlamentarias usan 14 pagas para estas
    retribuciones. Se devuelven ambas cifras para no ocultar el supuesto.
    """
    months = months_between(parse_day(start, field="start"), parse_day(end, field="end"))
    nominal = monthly_eur * months
    return {
        "months": round(months, 3),
        "nominal_eur": round(nominal, 2),
        "annualized_eur": round(nominal * payments_per_year / 12, 2),
        "payments_per_year": payments_per_year,
    }


def commission_metrics(
    *,
    constituted_on,
    sessions,
    today,
    peer_median_per_month=None,
    low_fraction=0.5,
    grace_days=GRACE_DAYS,
):
    """Calcula actividad mínima y clasificación conservadora."""
    constituted = parse_day(constituted_on, field="constituted_on")
    today = parse_day(today, field="today")
    if constituted is None or today is None:
        raise ValueError("la constitución y la fecha de corte son obligatorias")
    substantive = [
        session
        for session in sessions
        if session.get("kind") in SUBSTANTIVE_KINDS
        and parse_day(session.get("session_date"), field="session_date") is not None
    ]
    days_active = (today - constituted).days
    months_active = max(days_active / DAYS_PER_MONTH, 1 / DAYS_PER_MONTH)
    per_month = len(substantive) / months_active
    sessions_per_month = len(sessions) / months_active
    last = max(
        (parse_day(session["session_date"], field="session_date") for session in substantive),
        default=None,
    )
    if days_active < grace_days:
        status = "periodo_gracia"
    elif not substantive:
        # Hay reuniones, pero ninguna clasificada como comparecencia/debate:
        # no es "sin actividad", es actividad no clasificable con el opendata.
        status = "sin_clasificar" if sessions else "sin_actividad"
    elif (
        peer_median_per_month is not None
        and peer_median_per_month > 0
        and per_month < low_fraction * peer_median_per_month
    ):
        status = "actividad_baja"
    else:
        status = "actividad_normal"
    return {
        "sessions_total": len(sessions),
        "sessions_substantive": len(substantive),
        "sessions_per_month": round(sessions_per_month, 3),
        "substantive_per_month": round(per_month, 3),
        "days_since_last_substantive": (today - last).days if last else None,
        "status": status,
    }
