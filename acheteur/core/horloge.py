"""Horloge injectable.

Une annonce doit être comparée au marché à sa date de pose, pas à l'instant
présent — sinon on compare un prix d'hier à des ventes d'aujourd'hui. Tout
code qui raisonne sur le temps reçoit une `Horloge`, jamais `datetime.now()`
en dur.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol


class Horloge(Protocol):
    def maintenant(self) -> datetime: ...


class HorlogeSysteme:
    """Horloge réelle, en UTC."""

    def maintenant(self) -> datetime:
        return datetime.now(UTC)


class HorlogeFigee:
    """Horloge de test : renvoie un instant fixe, avançable à la main."""

    def __init__(self, instant: datetime) -> None:
        if instant.tzinfo is None:
            raise ValueError("HorlogeFigee exige un datetime avec fuseau (UTC de préférence).")
        self._instant = instant

    def maintenant(self) -> datetime:
        return self._instant

    def avancer(self, delta: timedelta) -> None:
        self._instant += delta
