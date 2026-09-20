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
