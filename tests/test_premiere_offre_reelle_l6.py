"""Lot L6 : script de premier envoi réel (`cli/premiere_offre_reelle.py`).

Les fonctions d'orchestration réseau (`trouver_meilleure_candidate`) sont
testées avec un faux client GraphQL (pas de réseau réel — CLAUDE.md, revue
bancaire) ; les fonctions de calcul restent pures.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from acheteur.cli.premiere_offre_reelle import (
    _offres_ouvertes_reelles,
    _rarity_brute,
    _soldes_reels,
    trouver_meilleure_candidate,
)
from acheteur.core.db import Base
from acheteur.core.horloge import HorlogeFigee
from acheteur.marche.devises import Devise, Montant
from acheteur.marche.traduction import rarete_depuis_sorare
from acheteur.marche.types import Annonce, Joueur
from acheteur.negociation.journal import EtatOffre, OffreJournal

BASE = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)


def test_rarity_brute_fait_l_aller_retour_avec_rarete_depuis_sorare():
    """`_rarity_brute` doit reconstruire exactement la valeur d'enum Sorare
    dont `annonce_depuis_noeud_marche` était parti (voir traduction.py)."""
    for brute in ("common", "limited", "rare", "super_rare"):
        joueur = Joueur(slug="x", nom="X", rareté=rarete_depuis_sorare(brute))
        annonce = Annonce(
            joueur=joueur,
            vendeur_slug="v",
            prix_demande=Montant(100, Devise.EUR),
            accepte_eth=False,
            accepte_eur=True,
            date_pose=BASE,
            asset_id="asset-x",
        )
        assert _rarity_brute(annonce) == brute


class TestSoldesReels:
    def test_lit_eur_et_wei(self):
        compte = {
            "availableBalances": {
                "eurCents": {"eurCents": 3556, "referenceCurrency": "EUR"},
                "wei": {"wei": 8209290000000000, "referenceCurrency": "EUR"},
            }
        }
        soldes = _soldes_reels(compte)
        assert soldes[Devise.EUR].valeur == 3556
        assert soldes[Devise.ETH].valeur == 8209290000000000

    def test_champs_absents_valent_zero(self):
        soldes = _soldes_reels({})
        assert soldes[Devise.EUR].valeur == 0
        assert soldes[Devise.ETH].valeur == 0


@pytest.fixture
def session():
    moteur = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(moteur)
    fabrique = sessionmaker(bind=moteur)
    s = fabrique()
    yield s
    s.close()


class TestOffresOuvertesReelles:
    def test_ignore_les_lignes_simulees(self, session):
        session.add(
            OffreJournal(
                joueur_slug="messi",
                vendeur_slug="alice",
                montant_offre_valeur=500,
                montant_offre_devise=Devise.EUR,
                etat=EtatOffre.SIMULEE,
                mode_simulation=True,
                cree_le=BASE,
                maj_le=BASE,
            )
        )
        session.add(
            OffreJournal(
                joueur_slug="haaland",
                vendeur_slug="bob",
                montant_offre_valeur=700,
                montant_offre_devise=Devise.EUR,
                etat=EtatOffre.ENVOYEE,
                mode_simulation=False,
                cree_le=BASE,
                maj_le=BASE,
            )
        )
        session.flush()

        par_devise, par_vendeur = _offres_ouvertes_reelles(session)

        assert par_devise == {Devise.EUR: 700}
        assert par_vendeur == {"bob": 1}


# === trouver_meilleure_candidate : faux client GraphQL, pas de réseau ===


class _ClientFactice:
    """Renvoie une réponse canned selon la requête (mots-clés dans le texte),
    comme `SorareClient.execute` sans passer par le réseau."""

    def __init__(self, marche: dict, prix_par_joueur: dict[str, dict]):
        self._marche = marche
        self._prix_par_joueur = prix_par_joueur

    def execute(self, query: str, variables: dict | None = None) -> dict:
        if "liveSingleSaleOffers" in query:
            return self._marche
        if "tokenPrices" in query:
            slug = (variables or {}).get("playerSlug")
            return self._prix_par_joueur.get(slug, {"tokens": {"tokenPrices": []}})
        raise AssertionError(f"Requête inattendue : {query[:50]}")


def _noeud_marche(joueur_slug: str, eur_cents: int, vendeur_slug: str = "vendeur1") -> dict:
    return {
        "id": f"offer-{joueur_slug}",
        "status": "OPEN",
        "type": "SINGLE_SALE_OFFER",
        "createdAt": "2026-09-15T10:00:00+00:00",
        "userSeller": {"slug": vendeur_slug},
        "senderSide": {
            "amounts": None,
            "anyCards": [
                {
                    "assetId": f"asset-{joueur_slug}",
                    "rarityTyped": "limited",
                    "inSeasonEligible": False,
                    "anyPlayer": {"slug": joueur_slug, "displayName": joueur_slug.title()},
                }
            ],
        },
        "receiverSide": {"amounts": {"eurCents": eur_cents, "wei": None}, "anyCards": []},
    }


def _prix(*eur_cents_ventes: int) -> dict:
    return {
        "tokens": {
            "tokenPrices": [
                {"amounts": {"eurCents": v, "wei": None}, "date": "2026-09-16T10:00:00+00:00"}
                for v in eur_cents_ventes
            ]
        }
    }


class TestTrouverMeilleureCandidate:
    def test_saute_la_moins_chere_sans_reference_suffisante(self):
        """La moins chère (haaland, 1.00€) n'a que 2 ventes récentes (< 3
        exigées) : on passe à la suivante (messi, 2.00€) qui en a 3."""
        client = _ClientFactice(
            marche={
                "tokens": {
                    "liveSingleSaleOffers": {
                        "nodes": [
                            _noeud_marche("haaland", 100),
                            _noeud_marche("messi", 200),
                        ]
                    }
                }
            },
            prix_par_joueur={
                "haaland": _prix(90, 95),  # 2 ventes seulement
                "messi": _prix(180, 190, 200),  # 3 ventes
            },
        )
        horloge = HorlogeFigee(BASE)

        resultat = trouver_meilleure_candidate(client, horloge)

        assert resultat is not None
        annonce, reference = resultat
        assert annonce.joueur.slug == "messi"
        assert reference.valeur == 190  # médiane de 180/190/200

    def test_aucune_candidate_si_rien_n_a_de_reference(self):
        client = _ClientFactice(
            marche={
                "tokens": {"liveSingleSaleOffers": {"nodes": [_noeud_marche("haaland", 100)]}}
            },
            prix_par_joueur={"haaland": _prix(90)},
        )
        horloge = HorlogeFigee(BASE)

        assert trouver_meilleure_candidate(client, horloge) is None
