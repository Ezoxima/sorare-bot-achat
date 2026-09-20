"""Signature et envoi d'une offre (L5+).

Pour L5 : structure vide, pas de signature réelle.
L1 a montré que prepareOffer ne demande pas d'autorisation, donc on anticipe
qu'aucune signature ne sera nécessaire. Cette hypothèse sera vérifiée en L6.

L6 implémentera la vraie logique de signature si elle est demandée.
"""

from __future__ import annotations

import logging
from typing import Any

from acheteur.paiement.types import PreparedOffer
from acheteur.sorare.client import SorareClient
from acheteur.sorare.mutations import creer_offre_directe_sorare

logger = logging.getLogger(__name__)


def envoyer_offre_signee(
    client: SorareClient,
    prepared: PreparedOffer,
) -> dict[str, Any]:
    """Envoie une offre signée (ou non signée si pas d'autorisation demandée).

    L5 : pas de signature réelle — approvals vide.
    L6 : implémenter la vraie signature si nécessaire.

    Args:
        client: client GraphQL Sorare
        prepared: offre préparée (résultat de prepareOffer)

    Returns:
        réponse de createDirectOffer

    Raises:
        Peut lever des exceptions réseau (comme prepare_offre)
    """
    # L5 : pas d'autorisation demandée, approvals vide
    if prepared.a_besoin_signature:
        logger.warning(
            "L5 : autorisation(s) demandée(s) mais pas implémentée. "
            "À faire en L6 selon le type : %s",
            [a.request_type.value for a in prepared.authorizations],
        )

    approvals = []  # Pour L5, vide

    # Construire l'input pour createDirectOffer
    create_input = {
        **prepared.input_data,
        "approvals": approvals,
    }

    logger.debug("Appel createDirectOffer...")
    return creer_offre_directe_sorare(client, create_input)
