from datetime import UTC, datetime, timedelta

import pytest

from acheteur.core.horloge import HorlogeFigee, HorlogeSysteme


def test_horloge_systeme_renvoie_un_datetime_avec_fuseau() -> None:
    instant = HorlogeSysteme().maintenant()
    assert instant.tzinfo is not None


def test_horloge_figee_ne_bouge_pas_toute_seule() -> None:
    instant = datetime(2026, 1, 1, tzinfo=UTC)
    horloge = HorlogeFigee(instant)
    assert horloge.maintenant() == instant
    assert horloge.maintenant() == instant


def test_horloge_figee_avance_seulement_sur_demande() -> None:
    instant = datetime(2026, 1, 1, tzinfo=UTC)
    horloge = HorlogeFigee(instant)
    horloge.avancer(timedelta(days=1))
    assert horloge.maintenant() == instant + timedelta(days=1)


def test_horloge_figee_refuse_un_datetime_naif() -> None:
    with pytest.raises(ValueError):
        HorlogeFigee(datetime(2026, 1, 1))
