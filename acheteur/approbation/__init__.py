"""Approbation des propositions : humaine (L4) + automatique (L11).

L4 (lot courant) : présentation HTML/email + validation CLI avec re-entry du
montant total (« protocole d'un virement bancaire »).

L11 (lot futur) : approbation automatique condditionnée par mesure du taux
d'acceptation.
"""

from acheteur.approbation.fichier_propositions import (
    DELAI_PEREMPTION_MINUTES_DEFAUT,
    DOSSIER_PROPOSITIONS_DEFAUT,
    charger_propositions,
    dernier_fichier_propositions,
    fichier_perime,
    sauvegarder_propositions,
)
from acheteur.approbation.mail import (
    MailNonConfigureError,
    envoyer_mail_propositions,
    mail_configure,
)
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
    "DOSSIER_PROPOSITIONS_DEFAUT",
    "DELAI_PEREMPTION_MINUTES_DEFAUT",
    "sauvegarder_propositions",
    "charger_propositions",
    "dernier_fichier_propositions",
    "fichier_perime",
    "MailNonConfigureError",
    "mail_configure",
    "envoyer_mail_propositions",
]
