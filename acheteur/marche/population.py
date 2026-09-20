"""Calcul de la population liquide : joueurs avec assez de ventes récentes."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from acheteur.marche.types import Joueur, Vente


def population_liquide(
    tous_les_joueurs: list[Joueur],
    ventes: list[Vente],
    reference_temps: datetime,
    ventes_min: int = 5,
    fenetre_jours: int = 30,
) -> list[Joueur]:
    """Filtre les joueurs avec au moins `ventes_min` ventes dans les `fenetre_jours` derniers jours.

    Args:
        tous_les_joueurs: liste complète des joueurs Sorare
        ventes: historique des ventes
        reference_temps: date de calcul (injectable pour test)
        ventes_min: nombre minimum de ventes requises (défaut: 5)
        fenetre_jours: fenêtre d'observation en arrière (défaut: 30)

    Returns:
        liste des joueurs liquides
    """
    limite_temps = reference_temps - timedelta(days=fenetre_jours)
    ventes_recentes_par_joueur = defaultdict(int)

    for vente in ventes:
        if vente.date_vente >= limite_temps:
            ventes_recentes_par_joueur[vente.joueur.slug] += 1

    return [j for j in tous_les_joueurs if ventes_recentes_par_joueur[j.slug] >= ventes_min]
