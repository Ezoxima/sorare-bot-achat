"""Passe marché en lecture seule (`cli/scan_marche.py`) — fonctions pures
uniquement (formatage, filtrage) ; le reste (requêtes réseau) est déjà
couvert par les tests de L6/L7 sur les mêmes primitives partagées."""

from __future__ import annotations

from datetime import UTC, datetime

from acheteur.cli.scan_marche import (
    Candidate,
    _bonnes_affaires,
    _construire_propositions,
    formatter_rapport,
    repartir_selon_budget,
)
from acheteur.marche.devises import Devise, Montant
from acheteur.marche.types import Annonce, Joueur, Rareté

BASE = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)


def _annonce(joueur_slug: str, prix_cents: int, vendeur_slug: str = "vendeur1") -> Annonce:
    return Annonce(
        joueur=Joueur(slug=joueur_slug, nom=joueur_slug.title(), rareté=Rareté("Limited", 2)),
        vendeur_slug=vendeur_slug,
        prix_demande=Montant(prix_cents, Devise.EUR),
        accepte_eth=False,
        accepte_eur=True,
        date_pose=BASE,
        asset_id=f"asset-{joueur_slug}",
        in_season=False,
    )


class TestBonnesAffaires:
    def test_filtre_sous_le_seuil(self):
        candidates = [
            Candidate(_annonce("a", 80), Montant(100, Devise.EUR), nb_ventes=3),  # 80% : passe
            Candidate(_annonce("b", 95), Montant(100, Devise.EUR), nb_ventes=3),  # 95% : recalé
        ]
        retenues = _bonnes_affaires(candidates, seuil_pourcent=90)
        assert [c.annonce.joueur.slug for c in retenues] == ["a"]


class TestConstruirePropositions:
    def test_une_seule_annonce_par_vendeur_devient_proposition_simple(self):
        candidates = [Candidate(_annonce("a", 700), Montant(1000, Devise.EUR), nb_ventes=3)]
        propositions, references = _construire_propositions(candidates)
        assert len(propositions) == 1
        assert propositions[0].annonce.joueur.slug == "a"
        assert references["a"].valeur == 1000

    def test_deux_annonces_meme_vendeur_deviennent_proposition_groupe(self):
        candidates = [
            Candidate(_annonce("a", 700, "vendeur1"), Montant(1000, Devise.EUR), nb_ventes=3),
            Candidate(_annonce("b", 500, "vendeur1"), Montant(800, Devise.EUR), nb_ventes=3),
        ]
        propositions, _ = _construire_propositions(candidates)
        assert len(propositions) == 1
        assert len(propositions[0].annonces) == 2

    def test_vendeurs_differents_restent_separes(self):
        candidates = [
            Candidate(_annonce("a", 700, "vendeur1"), Montant(1000, Devise.EUR), nb_ventes=3),
            Candidate(_annonce("b", 500, "vendeur2"), Montant(800, Devise.EUR), nb_ventes=3),
        ]
        propositions, _ = _construire_propositions(candidates)
        assert len(propositions) == 2


class TestRepartirSelonBudget:
    """Régression (signalé par l'utilisateur, 2026-09-21) : le solde renvoyé
    par Sorare a déjà déduit les offres réelles ouvertes (vérifié contre le
    compte réel : `totalBalance - availableBalance` colle exactement à leur
    somme) — `repartir_selon_budget` ne doit donc jamais les soustraire une
    seconde fois, sous peine de sous-estimer le budget réel."""

    def test_tout_tient_dans_le_budget(self):
        candidates = [Candidate(_annonce("a", 700), Montant(1000, Devise.EUR), nb_ventes=3)]
        propositions, _ = _construire_propositions(candidates)
        dans_le_budget, hors_budget = repartir_selon_budget(
            propositions, {Devise.EUR: Montant(10000, Devise.EUR)}
        )
        assert len(dans_le_budget) == 1
        assert hors_budget == []

    def test_le_solde_n_est_pas_deduit_une_seconde_fois(self):
        """Le solde (100 centimes) suffit exactement à l'offre (70% de 100 =
        70) — il ne doit PAS être diminué par des offres déjà ouvertes
        ailleurs, puisque Sorare l'a déjà fait."""
        candidates = [Candidate(_annonce("a", 100), Montant(200, Devise.EUR), nb_ventes=3)]
        propositions, _ = _construire_propositions(candidates)
        dans_le_budget, hors_budget = repartir_selon_budget(
            propositions, {Devise.EUR: Montant(100, Devise.EUR)}
        )
        assert len(dans_le_budget) == 1
        assert hors_budget == []

    def test_meilleure_affaire_prioritaire_quand_budget_serre(self):
        """Deux propositions, budget ne couvrant que la moins chère — elle
        doit être retenue même si elle n'est pas la première rencontrée."""
        chere = Candidate(_annonce("chere", 1000, "v1"), Montant(1200, Devise.EUR), nb_ventes=3)
        pas_chere = Candidate(_annonce("pas-chere", 100, "v2"), Montant(200, Devise.EUR), nb_ventes=3)
        propositions, _ = _construire_propositions([chere, pas_chere])
        # 70% de 1000 = 700 ; 70% de 100 = 70 ; budget = 100 : ne couvre que la petite.
        dans_le_budget, hors_budget = repartir_selon_budget(
            propositions, {Devise.EUR: Montant(100, Devise.EUR)}
        )
        assert len(dans_le_budget) == 1
        assert dans_le_budget[0][0].annonce.joueur.slug == "pas-chere"
        assert len(hors_budget) == 1

    def test_plus_petite_encore_testee_apres_un_rejet(self):
        """Rejeter une proposition faute de budget ne doit pas empêcher
        d'examiner les suivantes (pas un arrêt au premier dépassement)."""
        grosse = Candidate(_annonce("grosse", 1000, "v1"), Montant(2000, Devise.EUR), nb_ventes=3)
        petite = Candidate(_annonce("petite", 50, "v2"), Montant(100, Devise.EUR), nb_ventes=3)
        propositions, _ = _construire_propositions([grosse, petite])
        # 70% de 1000 = 700, 70% de 50 = 35. Budget = 40 : ne couvre que "petite".
        dans_le_budget, hors_budget = repartir_selon_budget(
            propositions, {Devise.EUR: Montant(40, Devise.EUR)}
        )
        assert [p.annonce.joueur.slug for p, _ in dans_le_budget] == ["petite"]
        assert [p.annonce.joueur.slug for p in hors_budget] == ["grosse"]


class TestFormatterRapport:
    def test_aucune_proposition(self):
        rapport = formatter_rapport(
            [],
            {Devise.EUR: Montant(1000, Devise.EUR)},
            {},
            nb_annonces_examinees=10,
            nb_sans_reference=5,
            nb_sous_le_seuil=5,
            seuil_pourcent=90,
        )
        assert "Aucune bonne affaire" in rapport
        assert "10" in rapport

    def test_proposition_simple_affiche_solde_restant(self):
        candidates = [Candidate(_annonce("a", 700), Montant(1000, Devise.EUR), nb_ventes=3)]
        propositions, _ = _construire_propositions(candidates)
        rapport = formatter_rapport(
            propositions,
            {Devise.EUR: Montant(10000, Devise.EUR)},
            {Devise.EUR: 0},
            nb_annonces_examinees=1,
            nb_sans_reference=0,
            nb_sous_le_seuil=0,
            seuil_pourcent=90,
        )
        assert "vendeur1" in rapport
        assert "TOTAL EUR proposé" in rapport
        assert "Solde restant" in rapport
