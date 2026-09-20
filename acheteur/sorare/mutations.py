"""Mutations GraphQL pour l'envoi d'offres (L5+).

Ce module ne mute que vers Sorare — c'est le seul endroit où le code
appelle `createDirectOffer` ou `prepareOffer`. Les garde-fous
(`acheteur/garde_fous/`) garantissent qu'on passe par la barrière.
"""

from __future__ import annotations

from typing import Any

from acheteur.sorare.client import SorareClient


# === Mutations ===

PREPARE_OFFER_MUTATION = """
mutation PrepareOffer($input: prepareOfferInput!) {
  prepareOffer(input: $input) {
    clientMutationId
    authorizations {
      id
      fingerprint
      status
      request {
        __typename
      }
    }
    errors {
      code
      message
      path
    }
  }
}
"""

CREATE_DIRECT_OFFER_MUTATION = """
mutation CreateDirectOffer($input: createDirectOfferInput!) {
  createDirectOffer(input: $input) {
    clientMutationId
    tokenOffer {
      id
      status
      createdAt
      receiver {
        slug
      }
    }
    errors {
      code
      message
      path
    }
  }
}
"""


# === Wrappers ===


def preparer_offre_sorare(
    client: SorareClient,
    input_data: dict[str, Any],
) -> dict[str, Any]:
    """Appelle prepareOffer pour valider et lister les autorisations demandées.

    Args:
        client: client GraphQL Sorare
        input_data: paramètres d'input pour prepareOfferInput

    Returns:
        réponse brute ({"prepareOffer": {...}})
    """
    return client.execute(PREPARE_OFFER_MUTATION, variables={"input": input_data})


def creer_offre_directe_sorare(
    client: SorareClient,
    input_data: dict[str, Any],
) -> dict[str, Any]:
    """Appelle createDirectOffer pour envoyer une offre signée.

    Args:
        client: client GraphQL Sorare
        input_data: paramètres d'input pour createDirectOfferInput (avec approvals)

    Returns:
        réponse brute ({"createDirectOffer": {...}} ou erreur)
    """
    return client.execute(CREATE_DIRECT_OFFER_MUTATION, variables={"input": input_data})
