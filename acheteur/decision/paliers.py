"""Paliers d'offre : 70%, 75%, 80% du prix demandé."""

from __future__ import annotations

from enum import IntEnum


class Palier(IntEnum):
    """Niveau d'offre en pourcentage du prix demandé."""

    PREMIER = 70
    DEUXIEME = 75
    TROISIEME = 80


PALIERS_ESCALADE = [Palier.PREMIER, Palier.DEUXIEME, Palier.TROISIEME]


def montant_offre(prix_demande: int, palier: Palier) -> int:
    """Calcule le montant de l'offre au palier donné.

    Args:
        prix_demande: prix affiché par le vendeur
        palier: niveau d'offre (70, 75 ou 80)

    Returns:
        montant de l'offre (arrondi vers le bas pour ne pas dépasser l'enveloppe)
    """
    return (prix_demande * palier) // 100


def palier_suivant(palier_courant: Palier | None) -> Palier | None:
    """Escalade : passe au palier suivant.

    Args:
        palier_courant: le palier actuel, ou None pour commencer

    Returns:
        le prochain palier, ou None si on a atteint le dernier (80%)
    """
    if palier_courant is None:
        return Palier.PREMIER
    try:
        idx = PALIERS_ESCALADE.index(palier_courant)
        return PALIERS_ESCALADE[idx + 1]
    except IndexError:
        return None
