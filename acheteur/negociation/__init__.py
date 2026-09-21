"""Machine à états, envoi, réconciliation, escalade, veille.

Lot L2 : journal des offres + réconciliation en lecture seule (`journal`,
`reconciliation`). Lot L7 : la machine à états (`etats`) et l'annulation
défensive (`annulation`) — voir PLAN.md, section « La machine à états d'une
négociation ». L'envoi lui-même reste la barrière (`garde_fous.barriere`,
lots L4-L6).
"""

from acheteur.negociation.annulation import annuler_ligne
from acheteur.negociation.etats import (
    ActionNegociation,
    Decision,
    reagir_a_contre_offre,
    reagir_a_expiration,
    reagir_a_refus,
    reagir_a_veille,
)
from acheteur.negociation.journal import (
    ETATS_OUVERTS,
    EtatOffre,
    MotifRefus,
    OffreJournal,
    enregistrer_ligne,
    importer_ligne_manuelle,
    lignes_ouvertes,
    reessai_expiration_deja_fait,
)
from acheteur.negociation.reconciliation import (
    CRENEAU_SIGNATURE,
    OffreSorareObservee,
    RapportReconciliation,
    apparier,
    depuis_reponse_sorare,
    etat_depuis_sorare,
    motif_refus_depuis_sorare,
    reconcilier,
)

__all__ = [
    "ETATS_OUVERTS",
    "EtatOffre",
    "MotifRefus",
    "OffreJournal",
    "enregistrer_ligne",
    "importer_ligne_manuelle",
    "lignes_ouvertes",
    "reessai_expiration_deja_fait",
    "CRENEAU_SIGNATURE",
    "OffreSorareObservee",
    "RapportReconciliation",
    "apparier",
    "depuis_reponse_sorare",
    "etat_depuis_sorare",
    "motif_refus_depuis_sorare",
    "reconcilier",
    "ActionNegociation",
    "Decision",
    "reagir_a_contre_offre",
    "reagir_a_expiration",
    "reagir_a_refus",
    "reagir_a_veille",
    "annuler_ligne",
]
