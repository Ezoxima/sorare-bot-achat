"""Mutations GraphQL pour l'envoi d'offres (L5+).

Ce module ne mute que vers Sorare — c'est le seul endroit où le code
appelle `createDirectOffer` ou `prepareOffer`. Les garde-fous
(`acheteur/garde_fous/`) garantissent qu'on passe par la barrière.
"""

from __future__ import annotations

from typing import Any

from acheteur.sorare.client import SorareClient


# === Mutations ===

# `... on EthereumBankTransferAuthorizationRequest { ... }` ajouté lot L7
# (2026-09-21) : les champs propres à ce type sont nécessaires pour
# construire le message à signer (voir `paiement/eth_signature.py`) — sans
# eux, seul le `__typename` était visible, insuffisant pour signer quoi que
# ce soit. Vérifié contre l'API réelle (voir MESURES.md) : les noms de
# champs correspondent exactement au SDL local
# (schema/sorare_schema.graphql:9921).
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
        ... on EthereumBankTransferAuthorizationRequest {
          contractAddress
          senderAddress
          receiverAddress
          amount
          feeAmount
          deadline
          salt
          proxyAddress
        }
        ... on MangopayWalletTransferAuthorizationRequest {
          amount
          currency
          mangopayWalletId
          nonce
          operationHash
        }
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
        ... on User {
          slug
        }
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


CANCEL_OFFER_MUTATION = """
mutation CancelOffer($input: cancelOfferInput!) {
  cancelOffer(input: $input) {
    clientMutationId
    tokenOffer {
      id
      status
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


# NON VÉRIFIÉE contre l'API réelle (voir MESURES.md) : `cancelOfferInput`
# n'exige que `blockchainId` (schema/sorare_schema.graphql:34505), le champ
# `TokenOffer.blockchainId` distinct de `id` — à confirmer avant tout usage
# en L7 réel (une annulation avec le mauvais identifiant échouerait, ce qui
# est un échec sûr : rien n'est débité par une annulation, voir CLAUDE.md).
def annuler_offre_sorare(client: SorareClient, blockchain_id: str) -> dict[str, Any]:
    """Appelle cancelOffer pour annuler une offre encore ouverte (lot L7 —
    veille défensive, PLAN.md § « On n'annule jamais pour reposter plus
    haut »).

    Args:
        client: client GraphQL Sorare
        blockchain_id: `TokenOffer.blockchainId` de l'offre à annuler (PAS
            son `id` — deux champs distincts côté Sorare)

    Returns:
        réponse brute ({"cancelOffer": {...}})
    """
    return client.execute(
        CANCEL_OFFER_MUTATION,
        variables={"input": {"blockchainId": blockchain_id}},
    )
