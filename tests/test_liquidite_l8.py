"""Liquidité (`marche/liquidite.py`) — pré-filtre avant toute référence de
prix ou décision d'achat. Voir DECISIONS.md (2026-09-22)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from acheteur.marche.devises import Devise, Montant
from acheteur.marche.liquidite import Liquidite, est_liquide, mesurer_liquidite
from acheteur.marche.types import Joueur, Rareté, Vente

MAINTENANT = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
JOUEUR = Joueur("messi", "Messi", Rareté("Limited", 2))


def _vente(jours_avant: float) -> Vente:
    return Vente(
        joueur=JOUEUR,
        prix=Montant(100, Devise.EUR),
        date_vente=MAINTENANT - timedelta(days=jours_avant),
    )


class TestMesurerLiquidite:
    def test_compte_n30_et_n7(self):
        ventes = [_vente(1), _vente(5), _vente(10), _vente(29)]
        liquidite = mesurer_liquidite(ventes, MAINTENANT)
        assert liquidite.n30 == 4
        assert liquidite.n7 == 2  # 1 et 5 jours

    def test_ignore_les_ventes_hors_fenetre(self):
        ventes = [_vente(1), _vente(31)]
        liquidite = mesurer_liquidite(ventes, MAINTENANT)
        assert liquidite.n30 == 1

    def test_ignore_les_ventes_futures(self):
        """Une vente « future » (horloge figée dans un test, ou décalage
        d'horloge) ne doit pas gonfler artificiellement le compte."""
        ventes = [_vente(-1)]
        liquidite = mesurer_liquidite(ventes, MAINTENANT)
        assert liquidite.n30 == 0

    def test_semaines_actives_toutes_les_quatre(self):
        # Une vente dans chacune des 4 semaines de la fenêtre de 30 jours.
        ventes = [_vente(1), _vente(8), _vente(15), _vente(22)]
        liquidite = mesurer_liquidite(ventes, MAINTENANT)
        assert liquidite.semaines_actives == 4

    def test_semaines_actives_pic_ponctuel(self):
        # Toutes les ventes concentrées dans la même semaine récente.
        ventes = [_vente(1), _vente(2), _vente(3), _vente(4), _vente(5)]
        liquidite = mesurer_liquidite(ventes, MAINTENANT)
        assert liquidite.n30 == 5
        assert liquidite.semaines_actives == 1


class TestEstLiquide:
    def test_passe_les_trois_seuils(self):
        liquidite = Liquidite(n30=15, n7=3, semaines_actives=4)
        assert est_liquide(liquidite)

    def test_echoue_sur_n30(self):
        liquidite = Liquidite(n30=14, n7=3, semaines_actives=4)
        assert not est_liquide(liquidite)

    def test_echoue_sur_n7(self):
        liquidite = Liquidite(n30=15, n7=2, semaines_actives=4)
        assert not est_liquide(liquidite)

    def test_echoue_sur_semaines(self):
        liquidite = Liquidite(n30=15, n7=3, semaines_actives=3)
        assert not est_liquide(liquidite)

    def test_seuils_personnalises(self):
        liquidite = Liquidite(n30=10, n7=2, semaines_actives=2)
        assert est_liquide(liquidite, ventes_30_mini=10, ventes_7_mini=2, semaines_mini=2)
