"""Lot L7 : la machine à états d'une négociation (`negociation/etats.py`).

Chaque cas reprend une ligne de la table PLAN.md § « Ce qui déclenche quoi »
ou § « On n'annule jamais pour reposter plus haut » — fonctions pures,
aucun réseau, aucune base (voir docstring du module testé).
"""

from __future__ import annotations

import pytest

from acheteur.decision.paliers import Palier, montant_offre
from acheteur.marche.devises import Devise
from acheteur.negociation.etats import ActionNegociation, reagir_a_contre_offre, reagir_a_expiration, reagir_a_refus, reagir_a_veille
from acheteur.negociation.journal import MotifRefus


class TestReagirARefus:
    @pytest.mark.parametrize("motif", [MotifRefus.OFFRE_TROP_BASSE, MotifRefus.SANS_MOTIF])
    def test_escalade_immediate(self, motif):
        decision = reagir_a_refus(motif, Palier.PREMIER)
        assert decision.action == ActionNegociation.ESCALADER
        assert decision.palier_suivant == Palier.DEUXIEME

    @pytest.mark.parametrize("motif", [MotifRefus.OFFRE_TROP_BASSE, MotifRefus.SANS_MOTIF])
    def test_escalade_impossible_au_dernier_palier_abandonne(self, motif):
        decision = reagir_a_refus(motif, Palier.TROISIEME)
        assert decision.action == ActionNegociation.ABANDONNER

    @pytest.mark.parametrize("motif", [MotifRefus.NE_VEND_PAS, MotifRefus.CARTE_NON_DESIREE])
    def test_abandon_definitif(self, motif):
        decision = reagir_a_refus(motif, Palier.PREMIER)
        assert decision.action == ActionNegociation.ABANDONNER

    def test_uniquement_cash_rejoue_au_meme_palier(self):
        decision = reagir_a_refus(MotifRefus.UNIQUEMENT_CASH, Palier.DEUXIEME)
        assert decision.action == ActionNegociation.REJOUER_MEME_PALIER
        assert decision.palier_suivant == Palier.DEUXIEME

    def test_ajoute_cash_escalade(self):
        decision = reagir_a_refus(MotifRefus.AJOUTE_CASH, Palier.PREMIER)
        assert decision.action == ActionNegociation.ESCALADER
        assert decision.palier_suivant == Palier.DEUXIEME

    def test_ajoute_cash_au_dernier_palier_abandonne(self):
        decision = reagir_a_refus(MotifRefus.AJOUTE_CASH, Palier.TROISIEME)
        assert decision.action == ActionNegociation.ABANDONNER

    def test_dans_composition_sommeil(self):
        decision = reagir_a_refus(MotifRefus.DANS_COMPOSITION, Palier.PREMIER)
        assert decision.action == ActionNegociation.SOMMEIL


class TestReagirAExpiration:
    def test_un_seul_reessai_si_vivante_et_meme_prix(self):
        decision = reagir_a_expiration(
            annonce_toujours_vivante=True,
            prix_inchange=True,
            reessai_deja_fait=False,
            palier_courant=Palier.PREMIER,
        )
        assert decision.action == ActionNegociation.ESCALADER
        assert decision.palier_suivant == Palier.DEUXIEME

    def test_pas_de_second_reessai(self):
        decision = reagir_a_expiration(
            annonce_toujours_vivante=True,
            prix_inchange=True,
            reessai_deja_fait=True,
            palier_courant=Palier.PREMIER,
        )
        assert decision.action == ActionNegociation.ABANDONNER

    def test_pas_de_reessai_si_annonce_disparue(self):
        decision = reagir_a_expiration(
            annonce_toujours_vivante=False,
            prix_inchange=True,
            reessai_deja_fait=False,
            palier_courant=Palier.PREMIER,
        )
        assert decision.action == ActionNegociation.ABANDONNER

    def test_pas_de_reessai_si_prix_change(self):
        decision = reagir_a_expiration(
            annonce_toujours_vivante=True,
            prix_inchange=False,
            reessai_deja_fait=False,
            palier_courant=Palier.PREMIER,
        )
        assert decision.action == ActionNegociation.ABANDONNER

    def test_pas_de_reessai_au_dernier_palier(self):
        decision = reagir_a_expiration(
            annonce_toujours_vivante=True,
            prix_inchange=True,
            reessai_deja_fait=False,
            palier_courant=Palier.TROISIEME,
        )
        assert decision.action == ActionNegociation.ABANDONNER


class TestReagirAContreOffre:
    def test_sous_le_plafond_accepte(self):
        plafond = montant_offre(1000, Palier.TROISIEME)  # 800
        decision = reagir_a_contre_offre(montant_contre_offre=750, plafond_valeur=plafond)
        assert decision.action == ActionNegociation.ACCEPTER_CONTRE_OFFRE

    def test_egal_au_plafond_accepte(self):
        plafond = montant_offre(1000, Palier.TROISIEME)
        decision = reagir_a_contre_offre(montant_contre_offre=plafond, plafond_valeur=plafond)
        assert decision.action == ActionNegociation.ACCEPTER_CONTRE_OFFRE

    def test_au_dessus_du_plafond_abandonne(self):
        plafond = montant_offre(1000, Palier.TROISIEME)
        decision = reagir_a_contre_offre(montant_contre_offre=plafond + 1, plafond_valeur=plafond)
        assert decision.action == ActionNegociation.ABANDONNER


class TestReagirAVeille:
    def test_annonce_disparue_annule(self):
        decision = reagir_a_veille(
            annonce_disparue=True,
            prix_demande_actuel=None,
            devise_prix_demande_actuel=None,
            notre_offre_montant=500,
            notre_offre_devise=Devise.EUR,
        )
        assert decision.action == ActionNegociation.ANNULER

    def test_prix_descendu_sous_notre_offre_annule(self):
        decision = reagir_a_veille(
            annonce_disparue=False,
            prix_demande_actuel=400,
            devise_prix_demande_actuel=Devise.EUR,
            notre_offre_montant=500,
            notre_offre_devise=Devise.EUR,
        )
        assert decision.action == ActionNegociation.ANNULER

    def test_prix_egal_a_notre_offre_ne_annule_pas(self):
        """Un prix affiché égal à notre offre reste payable — ce n'est que
        *sous* notre offre que payer plus cher que l'affiché devient absurde."""
        decision = reagir_a_veille(
            annonce_disparue=False,
            prix_demande_actuel=500,
            devise_prix_demande_actuel=Devise.EUR,
            notre_offre_montant=500,
            notre_offre_devise=Devise.EUR,
        )
        assert decision.action == ActionNegociation.RIEN

    def test_annonce_toujours_valide_ne_fait_rien(self):
        decision = reagir_a_veille(
            annonce_disparue=False,
            prix_demande_actuel=600,
            devise_prix_demande_actuel=Devise.EUR,
            notre_offre_montant=500,
            notre_offre_devise=Devise.EUR,
        )
        assert decision.action == ActionNegociation.RIEN

    def test_devises_differentes_ne_compare_pas(self):
        """Régression (lot L7, sonde réelle 2026-09-21, MESURES.md) : un
        prix en centimes d'euro comparé à un montant en wei déclenchait une
        annulation absurde. CLAUDE.md § « Cohérence d'unité » : on ne compare
        jamais deux devises différentes sans conversion."""
        decision = reagir_a_veille(
            annonce_disparue=False,
            prix_demande_actuel=400,  # 4,00 €, en apparence "sous" l'offre ETH
            devise_prix_demande_actuel=Devise.EUR,
            notre_offre_montant=1_300_000_000_000_000,  # wei
            notre_offre_devise=Devise.ETH,
        )
        assert decision.action == ActionNegociation.RIEN
