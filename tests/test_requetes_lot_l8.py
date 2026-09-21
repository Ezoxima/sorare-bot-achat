"""Requête en lot (alias GraphQL) pour l'historique de prix — voir
DECISIONS.md (2026-09-22). Le réseau lui-même n'est pas testé (comme le
reste de `sorare.requetes` — CLAUDE.md), seulement la construction de la
requête et le remappage des résultats, avec un faux client."""

from __future__ import annotations

from acheteur.sorare.requetes import (
    _requete_historique_prix_lot,
    historique_prix_joueurs_lot,
)


class TestConstruireRequeteLot:
    def test_un_alias_par_demande(self):
        requete = _requete_historique_prix_lot(3, premieres=20)
        for i in range(3):
            assert f"a{i}: tokenPrices(playerSlug: $slug{i}" in requete
            assert f"$slug{i}: String!" in requete
            assert f"$rarity{i}: Rarity!" in requete
            assert f"$season{i}: SeasonEligibility" in requete

    def test_premieres_est_un_literal_partage(self):
        requete = _requete_historique_prix_lot(2, premieres=20)
        assert requete.count("first: 20") == 2


class _ClientFactice:
    """Fixe une réponse canned, comme `SorareClient.execute`."""

    def __init__(self, reponse: dict) -> None:
        self._reponse = reponse
        self.derniere_requete = None
        self.dernieres_variables = None

    def execute(self, query: str, variables: dict | None = None) -> dict:
        self.derniere_requete = query
        self.dernieres_variables = variables
        return self._reponse


class TestHistoriquePrixJoueursLot:
    def test_liste_vide_ne_fait_aucun_appel(self):
        client = _ClientFactice({})
        assert historique_prix_joueurs_lot(client, []) == []
        assert client.derniere_requete is None

    def test_remappe_dans_l_ordre_des_demandes(self):
        reponse = {
            "tokens": {
                "a0": [{"amounts": {"eurCents": 100, "wei": None}, "date": "2026-09-01T00:00:00Z"}],
                "a1": [{"amounts": {"eurCents": 200, "wei": None}, "date": "2026-09-02T00:00:00Z"}],
            }
        }
        client = _ClientFactice(reponse)
        demandes = [
            {"joueur_slug": "messi", "rarete": "limited", "season_eligibility": "IN_SEASON"},
            {"joueur_slug": "mbappe", "rarete": "rare", "season_eligibility": "CLASSIC"},
        ]
        resultats = historique_prix_joueurs_lot(client, demandes)
        assert resultats[0][0]["amounts"]["eurCents"] == 100
        assert resultats[1][0]["amounts"]["eurCents"] == 200
        assert client.dernieres_variables["slug0"] == "messi"
        assert client.dernieres_variables["rarity1"] == "rare"

    def test_alias_absent_de_la_reponse_rend_liste_vide(self):
        """Un alias en échec (lot partiellement retourné par l'API) ne doit
        pas faire planter tout le traitement — l'appelant voit « aucune
        vente » pour ce joueur, pas une exception."""
        client = _ClientFactice({"tokens": {"a0": None}})
        demandes = [{"joueur_slug": "messi", "rarete": "limited", "season_eligibility": None}]
        assert historique_prix_joueurs_lot(client, demandes) == [[]]
