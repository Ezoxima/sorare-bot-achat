"""Liquidité d'un joueur sur une fenêtre de 30 jours : pré-filtre à appliquer
AVANT tout calcul de référence de prix ou toute décision d'achat.

Inspiré de `sealing-sorare-apps-script/04 - bonnes affaires liste.gs`
(`CRITERES_BA`) : un joueur dont les cartes ne se revendent pas n'a pas de
valeur de négociation, quel que soit son prix demandé. Les seuils par
défaut ont été re-choisis par l'utilisateur (2026-09-22, voir DECISIONS.md)
pour viser une vente tous les 2 jours en moyenne (30 / 15 = 2, cohérent
avec `ventes7_mini` resté à 3 plutôt que le 3,5 strictement proportionnel —
choix explicite de l'utilisateur, pas une approximation).

Fonctions pures : aucun réseau, aucune base — comme le reste de
`acheteur.marche` et `acheteur.decision`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from acheteur.marche.types import Vente

VENTES_30_MINI_DEFAUT = 15
VENTES_7_MINI_DEFAUT = 3
SEMAINES_MINI_DEFAUT = 4


@dataclass(frozen=True)
class Liquidite:
    """Les trois compteurs qui décrivent la liquidité récente d'un joueur."""

    n30: int
    n7: int
    semaines_actives: int


def mesurer_liquidite(
    ventes: list[Vente],
    reference_temps: datetime,
    fenetre_jours: int = 30,
) -> Liquidite:
    """Calcule la liquidité d'un joueur à partir de son historique de ventes.

    Une seule fenêtre de 30 jours donne à la fois le compte à 30 jours, le
    compte à 7 jours et la répartition par semaine — pas besoin d'un appel
    réseau séparé pour chacun (même économie que `liquiditeParCouple_` dans
    les `.gs`).

    Args:
        ventes: historique de ventes du joueur (déjà filtré par rareté et
            éligibilité de saison par l'appelant — cette fonction ne fait
            que compter dans le temps)
        reference_temps: date de calcul (injectable pour test)
        fenetre_jours: fenêtre d'observation en arrière (défaut 30)

    Returns:
        Liquidite(n30, n7, semaines_actives)
    """
    limite = reference_temps - timedelta(days=fenetre_jours)
    ages_jours: list[float] = []
    for vente in ventes:
        if vente.date_vente < limite or vente.date_vente > reference_temps:
            continue
        age = (reference_temps - vente.date_vente).total_seconds() / 86400
        ages_jours.append(age)

    n7 = sum(1 for age in ages_jours if age < 7)
    # 4 semaines de 7 jours dans une fenêtre de 30 jours (28 jours couverts
    # entièrement ; les 2 derniers jours n'ouvrent pas de 5e semaine) — même
    # découpage que `mesurerVentes_` dans les `.gs`.
    semaines = {int(age // 7) for age in ages_jours if age < 28}

    return Liquidite(n30=len(ages_jours), n7=n7, semaines_actives=len(semaines))


def est_liquide(
    liquidite: Liquidite,
    ventes_30_mini: int = VENTES_30_MINI_DEFAUT,
    ventes_7_mini: int = VENTES_7_MINI_DEFAUT,
    semaines_mini: int = SEMAINES_MINI_DEFAUT,
) -> bool:
    """Vrai si les trois seuils de liquidité sont atteints.

    Les trois comptent : `ventes_30_mini` seul laisserait passer un pic
    ponctuel (transfert, sortie de carte) sans activité récente régulière ;
    `semaines_mini` écarte précisément ce cas (voir DECISIONS.md).
    """
    return (
        liquidite.n30 >= ventes_30_mini
        and liquidite.n7 >= ventes_7_mini
        and liquidite.semaines_actives >= semaines_mini
    )
