"""Machine à états, envoi, réconciliation, escalade, veille.

Lot L2 : journal des offres + réconciliation en lecture seule (`journal`,
`reconciliation`). L'envoi, l'escalade et la veille défensive restent vides
— ils arrivent aux lots L5+ et L7 (voir PLAN.md, section « La machine à
états d'une négociation »).
"""

from acheteur.negociation.journal import (
    ETATS_OUVERTS,
    EtatOffre,
    MotifRefus,
    OffreJournal,
    enregistrer_ligne,
    importer_ligne_manuelle,
    lignes_ouvertes,
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
    "CRENEAU_SIGNATURE",
    "OffreSorareObservee",
    "RapportReconciliation",
    "apparier",
    "depuis_reponse_sorare",
    "etat_depuis_sorare",
    "motif_refus_depuis_sorare",
    "reconcilier",
]
