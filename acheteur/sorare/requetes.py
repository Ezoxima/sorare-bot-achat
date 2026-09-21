"""Requêtes GraphQL en lecture seule.

Ce module ne mute jamais rien. `sorare.mutations` (lot L5+) sera le seul
module autorisé à écrire vers Sorare.

Volontairement absents de la requête d'état du compte : `passwordEncryptedPrivateKey`
et `privateKeyRecoveryPayload(s)` sur `UserWallet` — ce sont des clés privées
chiffrées, aucune raison pour ce bot d'y toucher, même en lecture.
"""

from __future__ import annotations

from typing import Any

from acheteur.sorare.client import SorareClient, SorareError

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
#
# `blockchainId` et `counteredOffer` ajoutés lot L7 (veille défensive et
# contre-offres, PLAN.md § « La machine à états ») : NON VÉRIFIÉS contre
# l'API réelle — jamais observé de contre-offre en conditions réelles à ce
# jour (voir MESURES.md). Pour `counteredOffer`, on lit les deux côtés
# (senderSide/receiverSide) comme pour `ANNONCES_MARCHE_QUERY` : on ne sait
# pas encore, sans l'avoir vérifié, quel côté porte le nouveau montant
# proposé par le vendeur.
OFFRES_ENVOYEES_QUERY = """
query OffresEnvoyees($first: Int!) {
  currentUser {
    tokenOffers(direction: SENT, first: $first, sortType: DESC) {
      nodes {
        id
        status
        blockchainId
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
        counteredOffer {
          id
          senderSide {
            amounts {
              eurCents
              wei
            }
          }
          receiverSide {
            amounts {
              eurCents
              wei
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
query AnnoncesMarche($first: Int!, $playerSlug: String, $after: String) {
  tokens {
    liveSingleSaleOffers(first: $first, playerSlug: $playerSlug, after: $after) {
      pageInfo {
        hasNextPage
        endCursor
      }
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
    """Les annonces actuelles du marché à prix fixe (`liveSingleSaleOffers`),
    UNE SEULE page.

    ⚠️ **Plafonné à ~50 nœuds réels quel que soit `premieres`** (constaté
    2026-09-21, voir MESURES.md) : ne pas augmenter `premieres` en espérant
    une couverture plus large sans utiliser `annonces_marche_paginees` à la
    place (2026-09-22 : la pagination par curseur, elle, avance bien —
    vérifié contre l'API réelle, 0 chevauchement entre deux pages
    consécutives, `totalCount` mesuré à plus de 500 000).

    Ne fait que lire et aplatir la réponse brute — la traduction vers le
    type `Annonce` du domaine vit dans `acheteur.marche.traduction`
    (fonction pure, testable sur des cas figés, comme le reste du projet).

    Args:
        client: client GraphQL Sorare
        premieres: nombre maximum d'annonces à récupérer sur cette page
        joueur_slug: filtre optionnel sur un seul joueur

    Returns:
        liste des annonces brutes (`TokenOffer` nodes) du marché
    """
    data = client.execute(
        ANNONCES_MARCHE_QUERY,
        variables={"first": premieres, "playerSlug": joueur_slug, "after": None},
    )
    return data["tokens"]["liveSingleSaleOffers"]["nodes"]


# Taille de page réelle de `liveSingleSaleOffers` : ~50 nœuds quel que soit
# `first` demandé au-delà (constaté 2026-09-21, MESURES.md).
TAILLE_PAGE_ANNONCES_MARCHE = 50


def annonces_marche_paginees(
    client: SorareClient,
    maximum: int,
    joueur_slug: str | None = None,
    taille_page: int = TAILLE_PAGE_ANNONCES_MARCHE,
) -> list[dict[str, Any]]:
    """Comme `annonces_marche`, mais avance par curseur (`after`) jusqu'à
    `maximum` nœuds ou épuisement du flux (fenêtre de 8 jours glissants,
    voir le SDL : « sorted by updated time (from 8 days ago) »).

    Vérifié contre l'API réelle (2026-09-22, MESURES.md) : deux pages
    consécutives ne se chevauchent pas (0 identifiant en commun), et
    `totalCount` dépasse largement `maximum` en pratique — la pagination
    avance donc réellement, contrairement au plafond de `first` sur une
    seule page.

    Args:
        client: client GraphQL Sorare
        maximum: nombre maximum de nœuds à accumuler avant de s'arrêter
        joueur_slug: filtre optionnel sur un seul joueur
        taille_page: nœuds demandés par page (voir `TAILLE_PAGE_ANNONCES_MARCHE`)

    Returns:
        liste des annonces brutes (`TokenOffer` nodes), au plus `maximum`.
    """
    tous: list[dict[str, Any]] = []
    curseur: str | None = None

    while len(tous) < maximum:
        restant = maximum - len(tous)
        data = client.execute(
            ANNONCES_MARCHE_QUERY,
            variables={
                "first": min(taille_page, restant),
                "playerSlug": joueur_slug,
                "after": curseur,
            },
        )
        bloc = data["tokens"]["liveSingleSaleOffers"]
        tous.extend(bloc["nodes"])

        page_info = bloc.get("pageInfo") or {}
        if not page_info.get("hasNextPage") or not page_info.get("endCursor"):
            break
        curseur = page_info["endCursor"]

    return tous


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


# Taille de lot par défaut pour `historique_prix_joueurs_lot`.
#
# VÉRIFIÉ contre l'API réelle (2026-09-22, voir MESURES.md) : 200 alias
# passe confortablement (1,1 s), le lot tient jusqu'à 360 avant échec.
# ⚠️ Ce n'est PAS le plafond de complexité GraphQL attendu par analogie avec
# `CRITERES_BA.aliasVentes = 200` des `.gs` (mesuré là-bas à 121/alias sous
# 30 000 de complexité) : la vraie limite observée ici est une taille de
# PAYLOAD HTTP (`413 Payload Too Large` à 400 alias, pas une erreur de
# complexité GraphQL) — donc dépend de la taille du texte de la requête
# (nombre d'alias × longueur des déclarations), pas d'un coût par champ.
# 200 garde une marge confortable (~45 % de la limite mesurée) sans la
# rapprocher au point qu'une variation de longueur de slugs la fasse basculer.
TAILLE_LOT_HISTORIQUE_PRIX_DEFAUT = 200


def _requete_historique_prix_lot(nombre: int, premieres: int) -> str:
    """Construit une requête à `nombre` alias — un par (joueur, rareté,
    éligibilité de saison) — pour amortir plusieurs joueurs en un seul appel
    réseau (voir DECISIONS.md, 2026-09-22 : `liquiditeParCouple_` dans les
    `.gs`, même principe).

    `first` est un littéral (identique pour tout le lot, comme
    `NOMBRE_VENTES_EXAMINEES` dans `cli/scan_marche.py`) plutôt qu'une
    variable par alias — pas besoin de le faire varier par joueur ici.
    """
    declarations = ", ".join(
        f"$slug{i}: String!, $rarity{i}: Rarity!, $season{i}: SeasonEligibility"
        for i in range(nombre)
    )
    champs = "\n".join(
        f"    a{i}: tokenPrices(playerSlug: $slug{i}, rarity: $rarity{i}, "
        f"first: {premieres}, seasonEligibility: $season{i}) "
        "{ amounts { eurCents wei } date }"
        for i in range(nombre)
    )
    return f"query HistoriquePrixLot({declarations}) {{\n  tokens {{\n{champs}\n  }}\n}}"


def historique_prix_joueurs_lot(
    client: SorareClient,
    demandes: list[dict[str, Any]],
    premieres: int = 20,
) -> list[list[dict[str, Any]]]:
    """Historique de ventes de PLUSIEURS joueurs en un seul appel réseau
    (alias GraphQL), au lieu d'un appel par joueur comme `historique_prix_joueur`.

    Args:
        client: client GraphQL Sorare
        demandes: `[{"joueur_slug": str, "rarete": str, "season_eligibility":
            str | None}, ...]` — un élément par joueur/rareté à interroger,
            dans l'ordre où les résultats seront rendus
        premieres: nombre max de ventes par joueur (même plafond réel que
            `historique_prix_joueur`, voir MESURES.md : 20)

    Returns:
        Une liste de même longueur et même ordre que `demandes` : pour
        chaque demande, la liste des ventes brutes (`TokenPrice`), vide si
        l'alias correspondant n'a rien renvoyé.
    """
    if not demandes:
        return []

    requete = _requete_historique_prix_lot(len(demandes), premieres)
    variables: dict[str, Any] = {}
    for i, demande in enumerate(demandes):
        variables[f"slug{i}"] = demande["joueur_slug"]
        variables[f"rarity{i}"] = demande["rarete"]
        variables[f"season{i}"] = demande.get("season_eligibility")

    data = client.execute(requete, variables=variables)
    racine = data.get("tokens") or {}
    return [racine.get(f"a{i}") or [] for i in range(len(demandes))]


# VÉRIFIÉE contre l'API réelle (2026-09-22, voir MESURES.md). Portée du SDL
# local (`User.liveSingleSaleTokenOffers` — schema/sorare_schema.graphql:31036) :
# le nombre d'annonces en cours d'un vendeur, utilisé comme indice de
# « joignabilité » avant d'exploiter le signal `SOUS_VENTE_MINI`
# (`decision.selecteur.est_sous_vente_minimum`) — voir DECISIONS.md
# (2026-09-22, inspiré de `SOUS_VENTE_MINI.stockMaxVendeur` dans
# sealing-sorare-apps-script/03 - bonnes affaires.gs). `first: 1` : seul
# `totalCount` nous intéresse ici, pas les nœuds.
STOCK_VENDEUR_QUERY = """
query StockVendeur($slug: String!) {
  user(slug: $slug) {
    nickname
    liveSingleSaleTokenOffers(first: 1, sport: [FOOTBALL]) {
      totalCount
    }
  }
}
"""


def stock_vendeur(client: SorareClient, slug_vendeur: str) -> dict[str, Any] | None:
    """La taille de la vitrine d'un vendeur (nombre d'annonces en cours).

    Renvoie `None` si le slug est inconnu de l'API — l'appelant doit alors
    traiter ce vendeur comme non mesurable, pas comme « petit vendeur » par
    défaut (même prudence que `filtrerPetitsVendeurs_` dans les `.gs`).

    ⚠️ **VÉRIFIÉ contre l'API réelle (2026-09-22, voir MESURES.md)** : un
    slug inconnu ne rend PAS `user: null` silencieusement (hypothèse initiale,
    par analogie avec d'autres champs Sorare) — l'API lève une erreur
    GraphQL (`NOT_FOUND`), donc une `SorareError` ici. Capturée et traitée
    comme « non mesurable », pas propagée : un vendeur introuvable (parti,
    renommé entre la lecture de l'annonce et cette vérification) ne doit pas
    faire planter tout le run.
    """
    try:
        data = client.execute(STOCK_VENDEUR_QUERY, variables={"slug": slug_vendeur})
    except SorareError:
        return None
    return data.get("user")


# VÉRIFIÉE contre l'API réelle (2026-09-22, voir MESURES.md). Même champ que
# `STOCK_VENDEUR_QUERY`, avec les nœuds cette fois : sert à l'offre groupée réactive (dès qu'un
# petit vendeur produit une candidate, on relit toute sa vitrine pour voir
# si d'autres de ses cartes correspondent aussi à nos critères — voir
# DECISIONS.md 2026-09-22, `cli/scan_marche.py`). Même forme de nœud que
# `ANNONCES_MARCHE_QUERY` (senderSide/receiverSide/anyCards/userSeller) pour
# pouvoir réutiliser telle quelle `traduction.annonces_depuis_noeuds_marche`
# — `userSeller` est redondant ici (même vendeur pour tous les nœuds) mais
# coûte 0 appel de plus dans la même requête.
VITRINE_VENDEUR_QUERY = """
query VitrineVendeur($slug: String!, $first: Int!) {
  user(slug: $slug) {
    nickname
    liveSingleSaleTokenOffers(first: $first, sport: [FOOTBALL]) {
      totalCount
      nodes {
        id
        status
        type
        createdAt
        userSeller {
          slug
        }
        senderSide {
          amounts { eurCents wei }
          anyCards {
            assetId
            rarityTyped
            inSeasonEligible
            anyPlayer { slug displayName }
          }
        }
        receiverSide {
          amounts { eurCents wei }
          anyCards {
            assetId
            rarityTyped
            inSeasonEligible
            anyPlayer { slug displayName }
          }
        }
      }
    }
  }
}
"""


def vitrine_vendeur(
    client: SorareClient, slug_vendeur: str, premieres: int = 50
) -> dict[str, Any] | None:
    """La vitrine complète (jusqu'à `premieres` annonces) d'un vendeur.

    Args:
        client: client GraphQL Sorare
        slug_vendeur: le vendeur dont on veut la vitrine
        premieres: taille de page — `liveSingleSaleTokenOffers` se pagine
            par vendeur mais ne se filtre ni par prix ni par joueur (constaté
            côté `.gs`) ; ce projet ne lit qu'une page, comme
            `annonces_marche` — un vendeur au-delà de `premieres` annonces
            n'est de toute façon pas le « petit vendeur » ciblé par ce signal.

    Returns:
        `None` si le slug est inconnu de l'API (voir `stock_vendeur` : une
        `SorareError`, pas un `user: null` silencieux — vérifié contre l'API
        réelle 2026-09-22, MESURES.md) ; sinon `{"nickname": str,
        "total_count": int, "nodes": [...]}` — les nœuds bruts, prêts pour
        `traduction.annonces_depuis_noeuds_marche`.
    """
    try:
        data = client.execute(
            VITRINE_VENDEUR_QUERY, variables={"slug": slug_vendeur, "first": premieres}
        )
    except SorareError:
        return None
    utilisateur = data.get("user")
    if utilisateur is None:
        return None
    bloc = utilisateur.get("liveSingleSaleTokenOffers") or {}
    return {
        "nickname": utilisateur.get("nickname"),
        "total_count": bloc.get("totalCount", 0),
        "nodes": bloc.get("nodes") or [],
    }
