"""Lot L6 : traduction des nœuds bruts Sorare (marché, historique de prix)
vers les types du domaine. Fonctions pures, cas figés (CLAUDE.md)."""

from __future__ import annotations

from acheteur.marche.devises import Devise
from acheteur.marche.traduction import (
    annonce_depuis_noeud_marche,
    annonces_depuis_noeuds_marche,
    rarete_depuis_sorare,
    vente_depuis_noeud_prix,
    ventes_depuis_noeuds_prix,
)
from acheteur.marche.types import Joueur, Rareté


def _noeud_marche(
    *,
    type_="SINGLE_SALE_OFFER",
    carte_cote="senderSide",
    eur_cents=500,
    wei=None,
    joueur_slug="messi",
    asset_id="asset-123",
    rarity="limited",
    in_season_eligible=False,
    vendeur_slug="vendeur1",
    created_at="2026-09-15T10:00:00+00:00",
):
    cote_carte = {
        "amounts": None,
        "anyCards": [
            {
                "assetId": asset_id,
                "rarityTyped": rarity,
                "inSeasonEligible": in_season_eligible,
                "anyPlayer": {"slug": joueur_slug, "displayName": "Lionel Messi"},
            }
        ],
    }
    cote_prix = {
        "amounts": {"eurCents": eur_cents, "wei": wei},
        "anyCards": [],
    }
    noeud = {
        "id": "offer-1",
        "status": "OPEN",
        "type": type_,
        "createdAt": created_at,
        "userSeller": {"slug": vendeur_slug},
    }
    autre_cote = "receiverSide" if carte_cote == "senderSide" else "senderSide"
    noeud[carte_cote] = cote_carte
    noeud[autre_cote] = cote_prix
    return noeud


class TestRareteDepuisSorare:
    def test_toutes_les_raretes_connues_du_schema(self):
        for brute in ("common", "limited", "rare", "super_rare", "unique", "custom_series"):
            rarete = rarete_depuis_sorare(brute)
            assert isinstance(rarete, Rareté)

    def test_rarete_inconnue_leve(self):
        import pytest

        with pytest.raises(ValueError, match="inconnue"):
            rarete_depuis_sorare("legendary")


class TestAnnonceDepuisNoeudMarche:
    def test_carte_cote_sender_prix_cote_receiver(self):
        annonce = annonce_depuis_noeud_marche(_noeud_marche(carte_cote="senderSide"))
        assert annonce is not None
        assert annonce.joueur.slug == "messi"
        assert annonce.asset_id == "asset-123"
        assert annonce.vendeur_slug == "vendeur1"
        assert annonce.prix_demande.valeur == 500
        assert annonce.prix_demande.devise == Devise.EUR
        assert annonce.accepte_eur is True
        assert annonce.accepte_eth is False
        assert annonce.in_season is False

    def test_carte_in_season(self):
        annonce = annonce_depuis_noeud_marche(_noeud_marche(in_season_eligible=True))
        assert annonce is not None
        assert annonce.in_season is True

    def test_in_season_absent_ignore(self):
        """Sans `inSeasonEligible`, impossible de savoir sur quelle
        population de ventes caler la référence (classic vs in-season) —
        mieux vaut ignorer l'annonce que deviner (voir MESURES.md)."""
        noeud = _noeud_marche()
        del noeud["senderSide"]["anyCards"][0]["inSeasonEligible"]
        assert annonce_depuis_noeud_marche(noeud) is None

    def test_carte_cote_receiver_prix_cote_sender(self):
        """Le mapping n'est pas figé : la carte peut être de l'un ou
        l'autre côté (ambiguïté non vérifiée, voir sorare/requetes.py)."""
        annonce = annonce_depuis_noeud_marche(_noeud_marche(carte_cote="receiverSide"))
        assert annonce is not None
        assert annonce.joueur.slug == "messi"
        assert annonce.prix_demande.valeur == 500

    def test_prix_en_wei(self):
        noeud = _noeud_marche(eur_cents=None, wei=2_000_000_000_000_000)
        annonce = annonce_depuis_noeud_marche(noeud)
        assert annonce is not None
        assert annonce.prix_demande.devise == Devise.ETH
        assert annonce.prix_demande.valeur == 2_000_000_000_000_000
        assert annonce.accepte_eth is True
        assert annonce.accepte_eur is False

    def test_type_auction_ignore(self):
        noeud = _noeud_marche(type_="AUCTION")
        assert annonce_depuis_noeud_marche(noeud) is None

    def test_offre_groupee_ignoree(self):
        """Plusieurs cartes d'un côté : hors périmètre L6 (une seule carte)."""
        noeud = _noeud_marche()
        noeud["senderSide"]["anyCards"].append(
            {
                "assetId": "asset-456",
                "rarityTyped": "limited",
                "anyPlayer": {"slug": "haaland", "displayName": "Erling Haaland"},
            }
        )
        assert annonce_depuis_noeud_marche(noeud) is None

    def test_aucune_carte_des_deux_cotes_ignoree(self):
        noeud = _noeud_marche()
        noeud["senderSide"]["anyCards"] = []
        assert annonce_depuis_noeud_marche(noeud) is None

    def test_prix_nul_ignore(self):
        noeud = _noeud_marche(eur_cents=0)
        assert annonce_depuis_noeud_marche(noeud) is None

    def test_prix_absent_des_deux_devises_ignore(self):
        noeud = _noeud_marche(eur_cents=None, wei=None)
        assert annonce_depuis_noeud_marche(noeud) is None

    def test_joueur_manquant_ignore(self):
        noeud = _noeud_marche()
        noeud["senderSide"]["anyCards"][0]["anyPlayer"] = None
        assert annonce_depuis_noeud_marche(noeud) is None

    def test_vendeur_manquant_ignore(self):
        noeud = _noeud_marche()
        noeud["userSeller"] = None
        assert annonce_depuis_noeud_marche(noeud) is None

    def test_liste_filtre_silencieusement_les_noeuds_invalides(self):
        valides = [_noeud_marche(joueur_slug="messi"), _noeud_marche(type_="AUCTION")]
        annonces = annonces_depuis_noeuds_marche(valides)
        assert len(annonces) == 1
        assert annonces[0].joueur.slug == "messi"


class TestVenteDepuisNoeudPrix:
    def _joueur(self):
        return Joueur(slug="messi", nom="Messi", rareté=Rareté("Limited", 2))

    def test_vente_eur(self):
        noeud = {"amounts": {"eurCents": 450, "wei": None}, "date": "2026-09-10T08:00:00+00:00"}
        vente = vente_depuis_noeud_prix(noeud, self._joueur())
        assert vente is not None
        assert vente.prix.valeur == 450
        assert vente.prix.devise == Devise.EUR
        assert vente.joueur.slug == "messi"

    def test_montant_nul_ignore(self):
        noeud = {"amounts": {"eurCents": 0}, "date": "2026-09-10T08:00:00+00:00"}
        assert vente_depuis_noeud_prix(noeud, self._joueur()) is None

    def test_date_manquante_ignoree(self):
        noeud = {"amounts": {"eurCents": 450}, "date": None}
        assert vente_depuis_noeud_prix(noeud, self._joueur()) is None

    def test_liste_filtre_silencieusement(self):
        joueur = self._joueur()
        noeuds = [
            {"amounts": {"eurCents": 400}, "date": "2026-09-01T00:00:00+00:00"},
            {"amounts": {"eurCents": 0}, "date": "2026-09-02T00:00:00+00:00"},
            {"amounts": {"eurCents": 420}, "date": "2026-09-03T00:00:00+00:00"},
        ]
        ventes = ventes_depuis_noeuds_prix(noeuds, joueur)
        assert len(ventes) == 2
        assert [v.prix.valeur for v in ventes] == [400, 420]
