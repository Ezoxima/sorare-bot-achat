"""Tests du lot L3 : population, référence, paliers, sélection."""

from datetime import datetime, timedelta

import pytest

from acheteur.decision import (
    Palier,
    est_bonne_affaire,
    grouper_par_vendeur,
    montant_offre,
    montants_offre_groupe,
    palier_suivant,
    proposer_groupe,
    proposer_simple,
)
from acheteur.marche import (
    Annonce,
    Devise,
    Joueur,
    Montant,
    Rareté,
    Vente,
    population_liquide,
    reference_prix_joueur,
)


class TestPopulation:
    """Population liquide : au moins 5 ventes en 30 jours."""

    def test_population_vide_sans_ventes(self):
        joueurs = [
            Joueur("messi", "Messi", Rareté("Limited", 2)),
            Joueur("haaland", "Haaland", Rareté("Limited", 2)),
        ]
        population = population_liquide(joueurs, [], datetime(2026, 9, 20))
        assert population == []

    def test_population_filtre_par_ventes_recentes(self):
        joueurs = [
            Joueur("messi", "Messi", Rareté("Limited", 2)),
            Joueur("haaland", "Haaland", Rareté("Limited", 2)),
        ]
        base = datetime(2026, 9, 20)
        ventes = [
            Vente(joueurs[0], Montant(1000, Devise.EUR), base - timedelta(days=10)),
            Vente(joueurs[0], Montant(1100, Devise.EUR), base - timedelta(days=8)),
            Vente(joueurs[0], Montant(950, Devise.EUR), base - timedelta(days=5)),
            Vente(joueurs[0], Montant(1050, Devise.EUR), base - timedelta(days=2)),
            Vente(joueurs[0], Montant(1020, Devise.EUR), base - timedelta(days=1)),
            # Haaland : 4 ventes (< 5, pas liquide)
            Vente(joueurs[1], Montant(2000, Devise.EUR), base - timedelta(days=10)),
            Vente(joueurs[1], Montant(2100, Devise.EUR), base - timedelta(days=8)),
            Vente(joueurs[1], Montant(1950, Devise.EUR), base - timedelta(days=5)),
            Vente(joueurs[1], Montant(2050, Devise.EUR), base - timedelta(days=2)),
        ]
        population = population_liquide(joueurs, ventes, base)
        assert len(population) == 1
        assert population[0].slug == "messi"


class TestReferencePrix:
    """Référence de prix : médiane sur 7 jours, min 3 ventes."""

    def test_reference_insuffisante(self):
        joueur = Joueur("messi", "Messi", Rareté("Limited", 2))
        base = datetime(2026, 9, 20)
        ventes = [
            Vente(joueur, Montant(1000, Devise.EUR), base - timedelta(days=5)),
            Vente(joueur, Montant(1100, Devise.EUR), base - timedelta(days=3)),
        ]
        ref = reference_prix_joueur(joueur, ventes, base)
        assert ref is None

    def test_reference_mediane(self):
        joueur = Joueur("messi", "Messi", Rareté("Limited", 2))
        base = datetime(2026, 9, 20)
        ventes = [
            Vente(joueur, Montant(1000, Devise.EUR), base - timedelta(days=5)),
            Vente(joueur, Montant(1100, Devise.EUR), base - timedelta(days=3)),
            Vente(joueur, Montant(950, Devise.EUR), base - timedelta(days=1)),
        ]
        ref = reference_prix_joueur(joueur, ventes, base)
        assert ref is not None
        assert ref.valeur == 1000  # Médiane de [950, 1000, 1100]

    def test_reference_mediane_nombre_pair_de_ventes(self):
        """4 ventes : pas de valeur centrale unique, moyenne entière des deux du milieu."""
        joueur = Joueur("messi", "Messi", Rareté("Limited", 2))
        base = datetime(2026, 9, 20)
        ventes = [
            Vente(joueur, Montant(1000, Devise.EUR), base - timedelta(days=6)),
            Vente(joueur, Montant(1100, Devise.EUR), base - timedelta(days=4)),
            Vente(joueur, Montant(951, Devise.EUR), base - timedelta(days=2)),
            Vente(joueur, Montant(1050, Devise.EUR), base - timedelta(days=1)),
        ]
        ref = reference_prix_joueur(joueur, ventes, base)
        assert ref is not None
        # Triées : [951, 1000, 1050, 1100] -> milieu (1000+1050)//2 = 1025, entier.
        assert ref.valeur == 1025
        assert isinstance(ref.valeur, int)

    def test_reference_devises_melangees_leve_une_erreur(self):
        joueur = Joueur("messi", "Messi", Rareté("Limited", 2))
        base = datetime(2026, 9, 20)
        ventes = [
            Vente(joueur, Montant(1000, Devise.EUR), base - timedelta(days=5)),
            Vente(joueur, Montant(1, Devise.ETH), base - timedelta(days=3)),
            Vente(joueur, Montant(950, Devise.EUR), base - timedelta(days=1)),
        ]
        with pytest.raises(ValueError):
            reference_prix_joueur(joueur, ventes, base)


class TestSeuil:
    """Seuil : sélection des annonces sous 90% de la référence."""

    def test_bonne_affaire(self):
        joueur = Joueur("messi", "Messi", Rareté("Limited", 2))
        annonce = Annonce(
            joueur=joueur,
            vendeur_slug="vendeur_1",
            prix_demande=Montant(1000, Devise.EUR),
            accepte_eth=True,
            accepte_eur=True,
            date_pose=datetime.now(),
        )
        # Référence : 1200 EUR. Prix demandé 1000 EUR < 90% * 1200 = 1080.
        assert est_bonne_affaire(annonce, Montant(1200, Devise.EUR))

    def test_mauvaise_affaire(self):
        joueur = Joueur("messi", "Messi", Rareté("Limited", 2))
        annonce = Annonce(
            joueur=joueur,
            vendeur_slug="vendeur_1",
            prix_demande=Montant(1100, Devise.EUR),
            accepte_eth=True,
            accepte_eur=True,
            date_pose=datetime.now(),
        )
        # Référence : 1200 EUR. Prix demandé 1100 EUR > 90% * 1200 = 1080.
        assert not est_bonne_affaire(annonce, Montant(1200, Devise.EUR))

    def test_devise_incoherente_leve_une_erreur(self):
        joueur = Joueur("messi", "Messi", Rareté("Limited", 2))
        annonce = Annonce(
            joueur=joueur,
            vendeur_slug="vendeur_1",
            prix_demande=Montant(1000, Devise.EUR),
            accepte_eth=True,
            accepte_eur=True,
            date_pose=datetime.now(),
        )
        # Référence en ETH, annonce en EUR : comparer les deux serait absurde.
        with pytest.raises(ValueError):
            est_bonne_affaire(annonce, Montant(1, Devise.ETH))


class TestPaliers:
    """Paliers : 70%, 75%, 80%."""

    def test_montant_premier_palier(self):
        assert montant_offre(1000, Palier.PREMIER) == 700

    def test_montant_deuxieme_palier(self):
        assert montant_offre(1000, Palier.DEUXIEME) == 750

    def test_montant_troisieme_palier(self):
        assert montant_offre(1000, Palier.TROISIEME) == 800

    def test_escalade(self):
        assert palier_suivant(None) == Palier.PREMIER
        assert palier_suivant(Palier.PREMIER) == Palier.DEUXIEME
        assert palier_suivant(Palier.DEUXIEME) == Palier.TROISIEME
        assert palier_suivant(Palier.TROISIEME) is None


class TestGroupage:
    """Groupage par vendeur."""

    def test_grouper_par_vendeur(self):
        messi = Joueur("messi", "Messi", Rareté("Limited", 2))
        haaland = Joueur("haaland", "Haaland", Rareté("Limited", 2))
        annonces = [
            Annonce(messi, "alice", Montant(1000, Devise.EUR), True, True, datetime.now()),
            Annonce(haaland, "alice", Montant(2000, Devise.EUR), True, True, datetime.now()),
            Annonce(messi, "bob", Montant(1100, Devise.EUR), True, True, datetime.now()),
        ]
        groupes = grouper_par_vendeur(annonces)
        assert len(groupes) == 2
        assert len(groupes["alice"]) == 2
        assert len(groupes["bob"]) == 1

    def test_montants_offre_groupe_decote_si_plus_d_une_annonce(self):
        """Même règle que proposer_groupe : décote 65% seulement si le groupe a >1 annonce."""
        messi = Joueur("messi", "Messi", Rareté("Limited", 2))
        haaland = Joueur("haaland", "Haaland", Rareté("Limited", 2))
        annonces = [
            Annonce(messi, "alice", Montant(1000, Devise.EUR), True, True, datetime.now()),
            Annonce(haaland, "alice", Montant(2000, Devise.EUR), True, True, datetime.now()),
        ]
        montants = montants_offre_groupe(annonces, Palier.PREMIER)
        assert montants["messi"] == 650  # 65% * 1000
        assert montants["haaland"] == 1300  # 65% * 2000

    def test_montants_offre_groupe_sans_decote_si_une_seule_annonce(self):
        messi = Joueur("messi", "Messi", Rareté("Limited", 2))
        annonces = [Annonce(messi, "alice", Montant(1000, Devise.EUR), True, True, datetime.now())]
        montants = montants_offre_groupe(annonces, Palier.PREMIER)
        assert montants["messi"] == 700  # 70%, pas de décote sur une annonce seule

    def test_montants_offre_groupe_coherent_avec_proposer_groupe(self):
        """Les deux fonctions calculent la même décote pour le même groupe."""
        messi = Joueur("messi", "Messi", Rareté("Limited", 2))
        haaland = Joueur("haaland", "Haaland", Rareté("Limited", 2))
        annonces = [
            Annonce(messi, "alice", Montant(1000, Devise.EUR), True, True, datetime.now()),
            Annonce(haaland, "alice", Montant(2000, Devise.EUR), True, True, datetime.now()),
        ]
        references = {"messi": 1200, "haaland": 2400}
        via_groupage = montants_offre_groupe(annonces, Palier.PREMIER)
        via_proposition = proposer_groupe(annonces, references, Palier.PREMIER)
        assert via_groupage == via_proposition.montants_offre


class TestProposition:
    """Propositions : simple et groupée."""

    def test_proposition_simple(self):
        joueur = Joueur("messi", "Messi", Rareté("Limited", 2))
        annonce = Annonce(
            joueur=joueur,
            vendeur_slug="alice",
            prix_demande=Montant(1000, Devise.EUR),
            accepte_eth=True,
            accepte_eur=True,
            date_pose=datetime.now(),
        )
        prop = proposer_simple(annonce, 1200, Palier.PREMIER)
        assert prop.montant_offre == 700
        assert prop.pourcent_demande == 70.0

    def test_proposition_groupe_avec_decote(self):
        messi = Joueur("messi", "Messi", Rareté("Limited", 2))
        haaland = Joueur("haaland", "Haaland", Rareté("Limited", 2))
        annonces = [
            Annonce(messi, "alice", Montant(1000, Devise.EUR), True, True, datetime.now()),
            Annonce(haaland, "alice", Montant(2000, Devise.EUR), True, True, datetime.now()),
        ]
        references = {
            "messi": 1200,
            "haaland": 2400,
        }
        prop = proposer_groupe(annonces, references, Palier.PREMIER)
        # Décote appliquée au premier palier : 65% au lieu de 70%
        assert prop.montants_offre["messi"] == 650  # 65% * 1000
        assert prop.montants_offre["haaland"] == 1300  # 65% * 2000
        assert prop.montant_total == 1950
        assert prop.decote_appliquee

    def test_proposition_groupe_deuxieme_palier(self):
        messi = Joueur("messi", "Messi", Rareté("Limited", 2))
        haaland = Joueur("haaland", "Haaland", Rareté("Limited", 2))
        annonces = [
            Annonce(messi, "alice", Montant(1000, Devise.EUR), True, True, datetime.now()),
            Annonce(haaland, "alice", Montant(2000, Devise.EUR), True, True, datetime.now()),
        ]
        references = {
            "messi": 1200,
            "haaland": 2400,
        }
        prop = proposer_groupe(annonces, references, Palier.DEUXIEME)
        # Pas de décote au deuxième palier
        assert prop.montants_offre["messi"] == 750  # 75% * 1000
        assert prop.montants_offre["haaland"] == 1500  # 75% * 2000
        assert not prop.decote_appliquee
