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
from acheteur.decision.selecteur import (
    SOUS_VENTE_MINI_SEUIL_POURCENT_DEFAUT,
    TAUX_TAXE_REVENTE_POURCENT,
    est_bonne_affaire,
    est_sous_vente_minimum,
    prix_minimum_avant,
    reference_nette_de_taxe,
    selectionner_annonces,
)

__all__ = [
    "est_bonne_affaire",
    "reference_nette_de_taxe",
    "TAUX_TAXE_REVENTE_POURCENT",
    "est_sous_vente_minimum",
    "prix_minimum_avant",
    "SOUS_VENTE_MINI_SEUIL_POURCENT_DEFAUT",
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
