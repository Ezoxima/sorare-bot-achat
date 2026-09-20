"""Règles pures + la barrière, passage obligé avant tout envoi (lot L4).

PLAN.md § « Garde-fous » : neuf contraintes appliquées au bon moment, avant
tout envoi d'offre. `barriere.envoyer_offre_proposal()` est le point unique
de passage — un test mécanique prouve qu'aucune autre voie ne mène à l'envoi.
"""

from acheteur.garde_fous.barriere import (
    ContexteBarriere,
    envoyer_offre_proposal,
)
from acheteur.garde_fous.regles import (
    GuardrailViolation,
    verifier_arrêt_d_urgence,
    verifier_coherence_unites,
    verifier_mode_reel_verrous,
    verifier_offre_ne_depasse_pas_prix_demande,
    verifier_offres_par_vendeur_limitees,
    verifier_palier_valide,
    verifier_solde_relu_juste_avant,
    verifier_solde_suffisant,
    verifier_taux_change_frais,
)

__all__ = [
    "GuardrailViolation",
    "ContexteBarriere",
    "envoyer_offre_proposal",
    "verifier_solde_suffisant",
    "verifier_solde_relu_juste_avant",
    "verifier_offre_ne_depasse_pas_prix_demande",
    "verifier_coherence_unites",
    "verifier_taux_change_frais",
    "verifier_palier_valide",
    "verifier_offres_par_vendeur_limitees",
    "verifier_arrêt_d_urgence",
    "verifier_mode_reel_verrous",
]
