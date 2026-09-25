"""Tests du calcul du dernier jour complet."""

from datetime import UTC, date, datetime

from custom_components.velos_montpellier.api import Counter, parse_observed_at
from custom_components.velos_montpellier.coordinator import CounterData

COUNTER = Counter("urn:ngsi-ld:EcoCounter:ZLT26063736", "Delmas 1", *[None] * 5)


def _data(values: dict[str, int]) -> CounterData:
    """CounterData à partir d'horodatages bruts de l'API ("…Z" = heure de Paris)."""
    hourly: dict[datetime, int] = {}
    for observed_at, value in values.items():
        ts = parse_observed_at(observed_at).astimezone(UTC)
        hourly[ts] = hourly.get(ts, 0) + value
    return CounterData(COUNTER, hourly)


def _day(day: str, value: int = 1, hours: range = range(24)) -> dict[str, int]:
    return {f"{day}T{h:02d}:00:00Z": value for h in hours}


def test_day_with_only_last_hours_is_not_complete() -> None:
    """Envoi du 22/09 22h au 23/09 21h perdu (cas réel de Delmas 1)."""
    data = _data(
        _day("2026-09-21", 50)
        | _day("2026-09-22", 60, range(22))
        | _day("2026-09-23", 4, range(22, 24))
    )
    assert data.last_complete_day == (date(2026, 9, 21), 1200)


def test_day_missing_first_hours_is_not_complete() -> None:
    """Heures 00h-04h perdues (cas réel de Tanneurs)."""
    data = _data(_day("2026-09-21", 10) | _day("2026-09-23", 10, range(5, 24)))
    assert data.last_complete_day == (date(2026, 9, 21), 240)


def test_no_complete_day() -> None:
    assert _data(_day("2026-09-23", 1, range(22))).last_complete_day is None


def test_dst_days_are_complete() -> None:
    """La source publie 24 valeurs même les jours de changement d'heure."""
    spring = _data(_day("2026-03-29"))
    assert spring.last_complete_day == (date(2026, 3, 29), 24)

    autumn = _data(_day("2026-10-25"))
    assert autumn.last_complete_day == (date(2026, 10, 25), 24)
