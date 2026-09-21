"""Second signal de sélection (`SOUS_VENTE_MINI`) et offre groupée réactive
(`cli/scan_marche.py`) — fonctions pures uniquement, voir DECISIONS.md
(2026-09-22). Le réseau (`stock_vendeur`, `vitrine_vendeur`,
`_completer_par_vitrines_vendeurs`) n'est pas testé ici, comme le reste des
fonctions réseau du projet (CLAUDE.md : le réseau reste fin, la logique
testable vit dans des fonctions pures)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from acheteur.cli.scan_marche import (
    Candidate,
    _bonnes_affaires,
    _filtrer_par_stock_vendeur,
    _necessite_verification_stock,
    _petits_vendeurs,
)
from acheteur.marche.devises import Devise, Montant
from acheteur.marche.types import Annonce, Joueur, Rareté, Vente

BASE = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
JOUEUR = Joueur("messi", "Messi", Rareté("Limited", 2))


def _annonce(prix_cents: int, vendeur_slug: str = "vendeur1") -> Annonce:
    return Annonce(
        joueur=JOUEUR,
        vendeur_slug=vendeur_slug,
        prix_demande=Montant(prix_cents, Devise.EUR),
        accepte_eth=False,
        accepte_eur=True,
        date_pose=BASE,
    )


def _vente_avant(prix_cents: int, jours_avant: int = 1) -> Vente:
    return Vente(joueur=JOUEUR, prix=Montant(prix_cents, Devise.EUR),
                 date_vente=BASE - timedelta(days=jours_avant))


class TestBonnesAffairesAvecSousVenteMinimum:
    def test_retient_via_sous_vente_minimum_seul(self):
        """Une annonce qui échoue `est_bonne_affaire` (référence 50, nette
        de taxe 47, seuil 90% = 42 ; prix 70 > 42) mais qui est postée sous
        80% du plancher des ventes antérieures (70 <= 80% * 100 = 80) doit
        être retenue."""
        candidate = Candidate(
            _annonce(70), Montant(50, Devise.EUR), nb_ventes=3,
            ventes=[_vente_avant(100)],
        )
        retenues = _bonnes_affaires([candidate], seuil_pourcent=90)
        assert retenues == [candidate]

    def test_rejette_si_aucun_des_deux_signaux(self):
        candidate = Candidate(
            _annonce(95), Montant(100, Devise.EUR), nb_ventes=3,
            ventes=[_vente_avant(100)],
        )
        assert _bonnes_affaires([candidate], seuil_pourcent=90) == []


class TestNecessiteVerificationStock:
    def test_vrai_si_retenue_uniquement_par_sous_vente_min(self):
        # Référence basse (50, net 47, seuil90 42) : 70 échoue est_bonne_affaire.
        # Plancher des ventes antérieures (100, seuil80 80) : 70 passe sous_vente_min.
        candidate = Candidate(
            _annonce(70), Montant(50, Devise.EUR), nb_ventes=3,
            ventes=[_vente_avant(100)],
        )
        assert _necessite_verification_stock(candidate, 90, 80)

    def test_faux_si_deja_bonne_affaire(self):
        """Une candidate qui passe déjà `est_bonne_affaire` n'a pas besoin
        de la vérification de stock, même si elle passe aussi le second
        signal."""
        candidate = Candidate(
            _annonce(50), Montant(100, Devise.EUR), nb_ventes=3,
            ventes=[_vente_avant(100)],
        )
        assert not _necessite_verification_stock(candidate, 90, 80)


class TestFiltrerParStockVendeur:
    def test_garde_petit_vendeur(self):
        candidate = Candidate(
            _annonce(70, "petit"), Montant(50, Devise.EUR), nb_ventes=3,
            ventes=[_vente_avant(100)],
        )
        retenues = _filtrer_par_stock_vendeur(
            [candidate], {"petit": 5}, seuil_pourcent=90,
            seuil_sous_vente_min_pourcent=80, stock_max_vendeur=20,
        )
        assert retenues == [candidate]

    def test_ecarte_gros_vendeur(self):
        candidate = Candidate(
            _annonce(70, "gros"), Montant(50, Devise.EUR), nb_ventes=3,
            ventes=[_vente_avant(100)],
        )
        retenues = _filtrer_par_stock_vendeur(
            [candidate], {"gros": 500}, seuil_pourcent=90,
            seuil_sous_vente_min_pourcent=80, stock_max_vendeur=20,
        )
        assert retenues == []

    def test_ecarte_vendeur_non_mesure(self):
        candidate = Candidate(
            _annonce(70, "inconnu"), Montant(50, Devise.EUR), nb_ventes=3,
            ventes=[_vente_avant(100)],
        )
        retenues = _filtrer_par_stock_vendeur(
            [candidate], {}, seuil_pourcent=90,
            seuil_sous_vente_min_pourcent=80, stock_max_vendeur=20,
        )
        assert retenues == []

    def test_ne_touche_pas_aux_bonnes_affaires_classiques(self):
        """Une candidate retenue via `est_bonne_affaire` n'est jamais
        écartée par ce filtre, quelle que soit la taille du vendeur."""
        candidate = Candidate(
            _annonce(50, "gros"), Montant(100, Devise.EUR), nb_ventes=3,
        )
        retenues = _filtrer_par_stock_vendeur(
            [candidate], {"gros": 99999}, seuil_pourcent=90,
            seuil_sous_vente_min_pourcent=80, stock_max_vendeur=20,
        )
        assert retenues == [candidate]


class TestPetitsVendeurs:
    def test_retient_seulement_les_petits_mesures(self):
        candidates = [
            Candidate(_annonce(50, "petit"), Montant(100, Devise.EUR), nb_ventes=3),
            Candidate(_annonce(50, "gros"), Montant(100, Devise.EUR), nb_ventes=3),
            Candidate(_annonce(50, "inconnu"), Montant(100, Devise.EUR), nb_ventes=3),
        ]
        stocks = {"petit": 5, "gros": 500}
        assert _petits_vendeurs(candidates, stocks, stock_max_vendeur=20, vendeurs_max=6) == ["petit"]

    def test_plafonne_a_vendeurs_max(self):
        candidates = [
            Candidate(_annonce(50, f"v{i}"), Montant(100, Devise.EUR), nb_ventes=3)
            for i in range(5)
        ]
        stocks = {f"v{i}": 1 for i in range(5)}
        assert len(_petits_vendeurs(candidates, stocks, stock_max_vendeur=20, vendeurs_max=2)) == 2
