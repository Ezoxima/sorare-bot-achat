"""Préparation d'une offre pour l'envoi (L5+).

Appelle `prepareOffer` pour valider et récupérer les autorisations demandées.
"""

from __future__ import annotations

import logging
from typing import Any

from acheteur.decision.proposition import PropositionGroupe, PropositionSimple
from acheteur.marche.devises import Devise
from acheteur.paiement.types import AuthorizationRequest, AuthorizationType, PreparedOffer
from acheteur.sorare.client import SorareClient
from acheteur.sorare.mutations import preparer_offre_sorare

logger = logging.getLogger(__name__)


def _construire_input_prepare_offer(
    proposition: PropositionSimple | PropositionGroupe,
) -> dict[str, Any]:
    """Construit les paramètres pour prepareOffer à partir d'une proposition.

    Args:
        proposition: PropositionSimple ou PropositionGroupe

    Returns:
        input pour prepareOfferInput
    """
    if isinstance(proposition, PropositionSimple):
        annonce = proposition.annonce
        devise = annonce.prix_demande.devise
        montant_total = proposition.montant_offre
        vendeur_slug = annonce.vendeur_slug

        # L5 : utiliser un assetId de test pour la chaîne de préparation/signature
        # L6 remplacera par le vrai assetId depuis annonces_marche()
        asset_ids = ["test-asset-id-L5"]
    else:  # PropositionGroupe
        devise = proposition.annonces[0].prix_demande.devise
        montant_total = proposition.montant_total
        vendeur_slug = proposition.annonces[0].vendeur_slug
        asset_ids = ["test-asset-id-L5"] * len(proposition.annonces)

    # Convertir montant en format Sorare (string)
    if devise == Devise.ETH:
        send_currency = "WEI"
        send_amount_str = str(montant_total)
    else:  # EUR
        send_currency = "EUR"
        send_amount_str = str(montant_total)

    return {
        "clientMutationId": f"prepare-offer-{vendeur_slug}",
        "receiveAssetIds": asset_ids,
        "receiverSlug": vendeur_slug,
        "receiveAmount": {
            "amount": "0",  # On envoie l'argent, pas des cartes (on les reçoit)
            "currency": "EUR" if devise == Devise.EUR else "WEI",
        },
        "sendAssetIds": [],  # Pas de cartes à envoyer (c'est une offre directe)
        "sendAmount": {
            "amount": send_amount_str,
            "currency": send_currency,
        },
        "settlementCurrencies": [send_currency],
    }


def _parser_reponse_prepare_offer(
    reponse: dict[str, Any],
) -> tuple[list[AuthorizationRequest], list[dict[str, Any]]]:
    """Parse la réponse de prepareOffer.

    Args:
        reponse: réponse brute de prepareOffer

    Returns:
        (authorizations, errors)
    """
    autorisations = []
    erreurs = []

    if "prepareOffer" not in reponse:
        logger.warning("Réponse prepareOffer manquante dans %s", reponse.keys())
        return [], []

    payload = reponse["prepareOffer"]

    if "authorizations" in payload and payload["authorizations"]:
        for auth in payload["authorizations"]:
            try:
                request_type_str = auth.get("request", {}).get("__typename", "UNKNOWN")
                request_type = AuthorizationType(request_type_str)
            except ValueError:
                request_type = AuthorizationType.NONE

            autorisations.append(
                AuthorizationRequest(
                    id=auth.get("id", ""),
                    fingerprint=auth.get("fingerprint", ""),
                    request_type=request_type,
                    status=auth.get("status", ""),
                )
            )

    if "errors" in payload and payload["errors"]:
        erreurs = payload["errors"]

    return autorisations, erreurs


def preparer_offre(
    client: SorareClient,
    proposition: PropositionSimple | PropositionGroupe,
) -> PreparedOffer:
    """Prépare une offre via prepareOffer et retourne les autorisations demandées.

    Args:
        client: client GraphQL Sorare
        proposition: la proposition à préparer

    Returns:
        PreparedOffer avec autorisations et erreurs

    Raises:
        Aucune exception levée directement — les erreurs sont capturées dans
        PreparedOffer.errors pour que la barrière puisse décider.
    """
    input_data = _construire_input_prepare_offer(proposition)

    logger.debug("Appel prepareOffer pour vendeur %s...", proposition.annonces[0].vendeur_slug if isinstance(proposition, PropositionGroupe) else proposition.annonce.vendeur_slug)

    try:
        reponse = preparer_offre_sorare(client, input_data)
    except Exception as exc:
        logger.error("Erreur lors de prepareOffer : %s", exc)
        return PreparedOffer(
            input_data=input_data,
            authorizations=[],
            errors=[{"code": "NETWORK_ERROR", "message": str(exc)}],
        )

    autorisations, erreurs = _parser_reponse_prepare_offer(reponse)

    if autorisations:
        logger.info(
            "Autorisations demandées : %s",
            [a.request_type.value for a in autorisations],
        )
    else:
        logger.info("Aucune autorisation demandée par prepareOffer")

    if erreurs:
        logger.warning("Erreurs GraphQL : %s", erreurs)

    return PreparedOffer(
        input_data=input_data,
        authorizations=autorisations,
        errors=erreurs,
    )
