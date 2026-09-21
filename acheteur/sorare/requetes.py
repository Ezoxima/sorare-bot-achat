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
          ... on User {
            slug
          }
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


# NON VÉRIFIÉE contre l'API réelle (voir MESURES.md). Portée du SDL local
# (`TokenRoot.liveSingleSaleOffers` — schema/sorare_schema.graphql:30431) :
# les annonces à prix fixe posées par un vendeur (par opposition aux
# enchères, `TokenAuction`, hors périmètre du projet). À confirmer par la
# sonde `acheteur/cli/sonde_annonces_marche.py` avant tout usage en L6.
#
# Ambiguïté délibérément non tranchée ici, comme pour `offres_envoyees`
# (DECISIONS.md, lot L2) : on ne sait pas encore, sans l'avoir vérifié
# contre l'API réelle, quel côté (`senderSide`/`receiverSide`) porte la
# carte à vendre et quel côté porte le prix demandé pour un
# `SINGLE_SALE_OFFER`. `acheteur.marche.traduction.annonce_depuis_noeud_marche`
# lit les deux côtés et prend celui qui porte des cartes / celui qui porte
# un montant, plutôt que de figer une hypothèse fausse en dur.
ANNONCES_MARCHE_QUERY = """
query AnnoncesMarche($first: Int!, $playerSlug: String) {
  tokens {
    liveSingleSaleOffers(first: $first, playerSlug: $playerSlug) {
      nodes {
        id
        status
        type
        createdAt
        userSeller {
          slug
        }
        senderSide {
          amounts {
            eurCents
            wei
          }
          anyCards {
            assetId
            rarityTyped
            inSeasonEligible
            anyPlayer {
              slug
              displayName
            }
          }
        }
        receiverSide {
          amounts {
            eurCents
            wei
          }
          anyCards {
            assetId
            rarityTyped
            inSeasonEligible
            anyPlayer {
              slug
              displayName
            }
          }
        }
      }
    }
  }
}
"""


def annonces_marche(
    client: SorareClient, premieres: int = 100, joueur_slug: str | None = None
) -> list[dict[str, Any]]:
    """Les annonces actuelles du marché à prix fixe (`liveSingleSaleOffers`).

    Ne fait que lire et aplatir la réponse brute — la traduction vers le
    type `Annonce` du domaine vit dans `acheteur.marche.traduction`
    (fonction pure, testable sur des cas figés, comme le reste du projet).

    Args:
        client: client GraphQL Sorare
        premieres: nombre maximum d'annonces à récupérer (non paginé)
        joueur_slug: filtre optionnel sur un seul joueur

    Returns:
        liste des annonces brutes (`TokenOffer` nodes) du marché
    """
    data = client.execute(
        ANNONCES_MARCHE_QUERY,
        variables={"first": premieres, "playerSlug": joueur_slug},
    )
    return data["tokens"]["liveSingleSaleOffers"]["nodes"]


# NON VÉRIFIÉE contre l'API réelle. Portée du SDL local
# (`TokenRoot.tokenPrices` — schema/sorare_schema.graphql:30462) : historique
# des ventes réglées pour un joueur et une rareté donnés, ce dont
# `acheteur.marche.reference_prix` a besoin pour calculer une référence de
# marché réelle (médiane, fenêtre glissante, minimum de ventes — DECISIONS.md
# lot L3).
HISTORIQUE_PRIX_QUERY = """
query HistoriquePrixJoueur($playerSlug: String!, $rarity: Rarity!, $first: Int, $from: ISO8601DateTime, $seasonEligibility: SeasonEligibility) {
  tokens {
    tokenPrices(playerSlug: $playerSlug, rarity: $rarity, first: $first, from: $from, seasonEligibility: $seasonEligibility) {
      amounts {
        eurCents
        wei
      }
      date
    }
  }
}
"""


def historique_prix_joueur(
    client: SorareClient,
    joueur_slug: str,
    rarete: str,
    premieres: int = 50,
    depuis: str | None = None,
    season_eligibility: str | None = None,
) -> list[dict[str, Any]]:
    """Historique des ventes réglées d'un joueur (une rareté), non traduit.

    Args:
        client: client GraphQL Sorare
        joueur_slug: le joueur concerné
        rarete: rareté Sorare en minuscules (ex. "limited", "rare") — voir
            l'enum `Rarity` du schéma
        premieres: nombre maximum de ventes à récupérer (l'API plafonne à 20,
            constaté au premier run réel, lot L6 — non documenté dans le SDL)
        depuis: horodatage ISO8601 optionnel, borne inférieure
        season_eligibility: `"CLASSIC"` ou `"IN_SEASON"` (enum `SeasonEligibility`
            du schéma). Une carte classic et une carte in-season du même
            joueur/rareté ne se vendent pas au même prix (l'in-season est
            éligible aux compétitions en cours) — sans ce filtre, la médiane
            mélange deux populations de prix qui n'ont rien à voir (constaté
            en session, voir MESURES.md : la référence calculée pour une
            annonce classic ne correspondait à aucune réalité de marché).
            `None` = pas de filtre (comportement d'avant ce correctif).

    Returns:
        liste des ventes brutes (`TokenPrice`)
    """
    data = client.execute(
        HISTORIQUE_PRIX_QUERY,
        variables={
            "playerSlug": joueur_slug,
            "rarity": rarete,
            "first": premieres,
            "from": depuis,
            "seasonEligibility": season_eligibility,
        },
    )
    return data["tokens"]["tokenPrices"]
