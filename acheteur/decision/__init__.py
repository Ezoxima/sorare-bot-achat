"""Sélection, paliers, groupage par vendeur, proposition.

Fonctions pures uniquement — pas de réseau, pas de base.
"""

from acheteur.decision.groupage import grouper_par_vendeur, montants_offre_groupe
from acheteur.decision.paliers import PALIERS_ESCALADE, Palier, montant_offre, palier_suivant
from acheteur.decision.proposition import (
    PropositionGroupe,
    PropositionSimple,
    proposer_groupe,
    proposer_simple,
)
from acheteur.decision.selecteur import est_bonne_affaire, selectionner_annonces

__all__ = [
    "est_bonne_affaire",
    "selectionner_annonces",
    "Palier",
    "montant_offre",
    "palier_suivant",
    "PALIERS_ESCALADE",
    "grouper_par_vendeur",
    "montants_offre_groupe",
    "PropositionSimple",
    "PropositionGroupe",
    "proposer_simple",
    "proposer_groupe",
]
