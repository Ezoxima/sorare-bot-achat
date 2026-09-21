"""Types de base : joueur, rareté, annonce, vente historique."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from acheteur.marche.devises import Montant


@dataclass(frozen=True)
class Rareté:
    """Rareté d'une carte Sorare."""

    nom: str  # "Common", "Limited", "Rare", "Super Rare"
    classement: int  # 1-4, du plus courant au plus rare


@dataclass(frozen=True)
class Joueur:
    """Joueur Sorare identifié par son slug (identifiant unique)."""

    slug: str
    nom: str
    rareté: Rareté


@dataclass(frozen=True)
class Vente:
    """Vente historique : une transaction passée sur le marché."""

    joueur: Joueur
    prix: Montant
    date_vente: datetime


@dataclass(frozen=True)
class Annonce:
    """Annonce actuelle d'un vendeur."""

    joueur: Joueur
    vendeur_slug: str
    prix_demande: Montant
    accepte_eth: bool
    accepte_eur: bool
    date_pose: datetime
    # Identifiant de la carte blockchain concrète (AnyCardInterface.assetId).
    # Vide sur les annonces mockées/simulées (L3/L4) ; requis pour envoyer une
    # vraie offre (L6+), car prepareOffer/createDirectOffer exigent l'assetId
    # exact de la carte, pas seulement le joueur.
    asset_id: str = ""
    # AnyCardInterface.inSeasonEligible : une carte in-season (éligible aux
    # compétitions en cours) et une carte classic du même joueur/rareté ne se
    # vendent pas au même prix — mélanger les deux dans une référence de
    # marché produit un nombre qui ne correspond à aucune réalité (constaté
    # en session, lot L6, voir MESURES.md). `None` = inconnu (annonces
    # mockées/simulées L3/L4, qui ne portent pas cette information).
    in_season: bool | None = None
