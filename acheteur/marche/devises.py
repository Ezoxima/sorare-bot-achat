"""Devises, conversions, montants.

ETH a 18 décimales. EUR en centimes. Jamais de flottant sur un montant
qui touche un rail de paiement.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class Devise(Enum):
    """Rails de paiement."""

    ETH = "ETH"
    EUR = "EUR"


# Plus petite maille d'un montant en ETH sur le carnet Sorare : 0.0001 ETH,
# soit environ 20-25 centimes au taux courant (signalé par l'utilisateur,
# 2026-09-21 — pas dans le SDL, qui ne documente aucune granularité sur les
# montants). Un montant qui n'est pas un multiple exact de cette maille n'a
# aucune chance d'être un montant réellement négociable sur ce rail.
MAILLE_ETH_WEI = 10**14


def arrondir_wei_a_la_maille(valeur_wei: int) -> int:
    """Arrondit un montant en wei à la maille du carnet Sorare (0.0001 ETH).

    Toujours vers le bas (PLAN.md § « Le choix du rail de paiement » :
    « à l'envoi, vers le bas : on ne dépense jamais plus que ce qui a été
    approuvé »). Peut ramener un très petit montant à 0 — PLAN.md le prévoit
    explicitement (« un arrondi vers le bas peut faire tomber le montant à
    zéro sur une petite carte ») ; c'est à l'appelant de traiter un montant
    nul comme un refus, pas à cette fonction de le masquer.
    """
    return (valeur_wei // MAILLE_ETH_WEI) * MAILLE_ETH_WEI


@dataclass(frozen=True)
class Montant:
    """Montant avec sa devise et sa précision."""

    valeur: int  # Wei (10^-18 pour ETH) ou centimes (10^-2 pour EUR).
    devise: Devise

    def en_eth(self) -> int:
        """Supposé déjà en wei."""
        if self.devise != Devise.ETH:
            raise ValueError("Conversion EUR→ETH non implémentée ici")
        return self.valeur

    def en_eur_centimes(self) -> int:
        """Supposé déjà en centimes."""
        if self.devise != Devise.EUR:
            raise ValueError("Conversion ETH→EUR non implémentée ici")
        return self.valeur

    def __str__(self) -> str:
        if self.devise == Devise.ETH:
            eth = Decimal(self.valeur) / Decimal(10 ** 18)
            return f"{eth} ETH"
        else:
            eur = Decimal(self.valeur) / Decimal(100)
            return f"{eur} EUR"
