"""Approbation des propositions : humaine (L4) + automatique (L11).

L4 (lot courant) : présentation HTML/email + validation CLI avec re-entry du
montant total (« protocole d'un virement bancaire »).

L11 (lot futur) : approbation automatique condditionnée par mesure du taux
d'acceptation.
"""

from acheteur.approbation.present_proposals import (
    formatter_propositions_email,
    formatter_propositions_html,
)
from acheteur.approbation.valider_propositions import (
    confirmer_montant_total,
    demander_action_utilisateur,
    demander_confirmation_utilisateur,
)

__all__ = [
    "formatter_propositions_html",
    "formatter_propositions_email",
    "confirmer_montant_total",
    "demander_confirmation_utilisateur",
    "demander_action_utilisateur",
]
