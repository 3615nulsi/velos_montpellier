"""Tests de la lecture des fichiers open data."""

from datetime import date

from custom_components.velos_montpellier.api import parse_daily


def _record(day: str, intensity: str) -> str:
    return (
        f'{{"intensity":{intensity},"laneId":188609530,'
        f'"dateObserved":"{day}T00:00:00/{day}T00:00:00","location":{{'
        '"coordinates":[3.87,43.61],"type":"Point"},"id":"MMM_EcoCompt_XTH19101158",'
        '"type":"TrafficFlowObserved","vehicleType":"bicycle","reversedLane":false}'
    )


def test_parse_daily_tolerates_damaged_files() -> None:
    """Défauts rencontrés dans les vrais fichiers de la Métropole."""
    text = "\n".join(
        [
            _record("2026-09-14", "3003") + " ",
            # Deux objets collés sur une même ligne.
            _record("2026-09-15", "3476") + _record("2026-09-16", "3205") + " ",
            # Ligne tronquée en cours d'objet.
            _record("2026-09-17", "3266")[:120],
            # Jour sans total.
            _record("2026-09-18", "null") + " ",
            # Doublon parasite : la première valeur fait foi.
            _record("2026-09-16", "454") + " ",
            "",
        ]
    )
    assert parse_daily(text) == {
        date(2026, 9, 14): 3003,
        date(2026, 9, 15): 3476,
        date(2026, 9, 16): 3205,
        date(2026, 9, 17): 3266,
    }


def test_parse_daily_empty_file() -> None:
    """Fichier en cours de réécriture : aucun jour."""
    assert parse_daily("") == {}
