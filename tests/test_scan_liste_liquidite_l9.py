"""Passe rapide L9 (`cli/scan_liste_liquidite.py`) — seul le filtrage par
couple exact (`_annonces_du_couple`) est testé ici avec un faux client
(pas de réseau réel) ; le reste du pipeline est déjà couvert par les tests
de L8 (`test_scan_marche_l7.py`, `test_offre_groupee_reactive_l8.py`),
réutilisé tel quel."""

from __future__ import annotations

from datetime import UTC, datetime

from acheteur.cli.scan_liste_liquidite import _annonces_du_couple
from acheteur.marche.liste_liquidite import JoueurLiquide

BASE = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)


def _noeud_marche(joueur_slug: str, eur_cents: int, rarity: str, in_season: bool) -> dict:
    return {
        "id": f"offer-{joueur_slug}-{rarity}-{in_season}",
        "status": "OPEN",
        "type": "SINGLE_SALE_OFFER",
        "createdAt": "2026-09-15T10:00:00+00:00",
        "userSeller": {"slug": "vendeur1"},
        "senderSide": {
            "amounts": None,
            "anyCards": [
                {
                    "assetId": f"asset-{joueur_slug}-{rarity}",
                    "rarityTyped": rarity,
                    "inSeasonEligible": in_season,
                    "anyPlayer": {"slug": joueur_slug, "displayName": joueur_slug.title()},
                }
            ],
        },
        "receiverSide": {"amounts": {"eurCents": eur_cents, "wei": None}, "anyCards": []},
    }


class _ClientFactice:
    def __init__(self, noeuds: list[dict]) -> None:
        self._noeuds = noeuds

    def execute(self, query: str, variables: dict | None = None) -> dict:
        assert "liveSingleSaleOffers" in query
        return {"tokens": {"liveSingleSaleOffers": {"nodes": self._noeuds}}}


def _couple(rarete: str, season_eligibility: str) -> JoueurLiquide:
    return JoueurLiquide(
        joueur_slug="messi", rarete=rarete, season_eligibility=season_eligibility,
        n30=15, n7=3, semaines_actives=4, maj_le=BASE,
    )


class TestAnnoncesDuCouple:
    def test_garde_seulement_le_couple_exact(self):
        noeuds = [
            _noeud_marche("messi", 100, "limited", in_season=True),
            _noeud_marche("messi", 200, "limited", in_season=False),
            _noeud_marche("messi", 300, "rare", in_season=True),
        ]
        client = _ClientFactice(noeuds)
        couple = _couple("limited", "IN_SEASON")

        annonces = _annonces_du_couple(client, couple)

        assert len(annonces) == 1
        assert annonces[0].prix_demande.valeur == 100

    def test_aucune_annonce_ne_correspond(self):
        noeuds = [_noeud_marche("messi", 100, "rare", in_season=True)]
        client = _ClientFactice(noeuds)
        couple = _couple("limited", "IN_SEASON")

        assert _annonces_du_couple(client, couple) == []
