"""Requêtes GraphQL en lecture seule.

Ce module ne mute jamais rien. `sorare.mutations` (lot L5+) sera le seul
module autorisé à écrire vers Sorare.

Volontairement absents de la requête d'état du compte : `passwordEncryptedPrivateKey`
et `privateKeyRecoveryPayload(s)` sur `UserWallet` — ce sont des clés privées
chiffrées, aucune raison pour ce bot d'y toucher, même en lecture.
"""

from __future__ import annotations

from typing import Any

from acheteur.sorare.client import SorareClient

ETAT_COMPTE_QUERY = """
query EtatCompte {
  currentUser {
    slug
    nickname
    ethereumAddress
    starkKey
    shouldMigrateEth
    shouldMigrateEthBeforeWithdrawal
    totalBalance
    availableBalance
    availableBalances {
      eurCents { eurCents referenceCurrency }
      gbpCents { gbpCents referenceCurrency }
      usdCents { usdCents referenceCurrency }
      wei { wei referenceCurrency }
      lamport { lamport referenceCurrency }
    }
    wallet {
      ethereumAddress
      solanaAddress
      starkKey
      status
      holdsValue
      confirmedDevice
    }
    myAccounts {
      accountable {
        __typename
        ... on PrivateFiatWalletAccount {
          availableBalance
          totalBalance
          state
          kycStatus
        }
        ... on StarkwarePrivateAccount {
          id
        }
      }
    }
  }
}
"""


def etat_compte(client: SorareClient) -> dict[str, Any]:
    """Interroge l'état du compte courant. Nécessite un JWT valide."""
    data = client.execute(ETAT_COMPTE_QUERY)
    return data["currentUser"]


# NON VÉRIFIÉE contre l'API réelle (voir MESURES.md : ce fichier ne
# consigne que ce qui est prouvé par une sonde). Portée directement du SDL
# local (`schema/sorare_schema.graphql` : `UserOffersInterface.tokenOffers`,
# `TokenOffer`, `TokenOfferSide`) — à confirmer au premier `reconcilier`
# réel, comme `renouvellement.py` l'a été (DECISIONS.md, lot L0).
#
# Une seule page (`first`) : la pagination complète n'est pas nécessaire au
# lot L2, qui ne regarde que les offres ouvertes récentes. À revoir si le
# nombre d'offres ouvertes dépasse durablement `first`.
OFFRES_ENVOYEES_QUERY = """
query OffresEnvoyees($first: Int!) {
  currentUser {
    tokenOffers(direction: SENT, first: $first, sortType: DESC) {
      nodes {
        id
        status
        rejectionReason
        createdAt
        settlementCurrencies
        receiver {
          slug
        }
        senderSide {
          amounts {
            eurCents
            wei
          }
        }
        receiverSide {
          anyCards {
            assetId
            anyPlayer {
              slug
            }
          }
        }
      }
    }
  }
}
"""


def offres_envoyees(client: SorareClient, premieres: int = 100) -> list[dict[str, Any]]:
    """Les offres directes envoyées par l'utilisateur courant, non paginé.

    Renvoie les nœuds bruts (pas de traduction ici — `sorare.requetes` ne
    fait que lire) ; `negociation.reconciliation` les met en forme.
    """
    data = client.execute(OFFRES_ENVOYEES_QUERY, variables={"first": premieres})
    return data["currentUser"]["tokenOffers"]["nodes"]


def annonces_marche(client: SorareClient) -> list[dict[str, Any]]:
    """Les annonces actuelles du marché (offres ouvertes pour achat).

    À L4 (lot courant), c'est un placeholder : le scanner teste la chaîne
    de décision sur des données mockées, pas sur le marché réel.
    À L6+, remplacer par une vraie requête GraphQL selon le schéma Sorare.

    Returns:
        liste des annonces brutes du marché
    """
    # TODO(L6) : implémenter la vraie requête GraphQL selon le schéma Sorare
    # Pour l'instant, lever une exception pour rappeler que c'est à faire
    raise NotImplementedError(
        "annonces_marche() est un placeholder L4. À implémenter L6 selon le schéma Sorare."
    )
