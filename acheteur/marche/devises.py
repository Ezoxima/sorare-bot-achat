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
