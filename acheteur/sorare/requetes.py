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
