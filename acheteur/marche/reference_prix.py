"""Calcul de la référence de prix pour chaque joueur."""

from __future__ import annotations

from datetime import datetime, timedelta

from acheteur.marche.types import Joueur, Montant, Vente


def reference_prix_joueur(
    joueur: Joueur,
    ventes: list[Vente],
    reference_temps: datetime,
    fenetre_jours: int = 7,
    ventes_min: int = 3,
) -> Montant | None:
    """Calcule la référence de prix (médiane) d'un joueur sur ses dernières ventes.

    Args:
        joueur: le joueur pour lequel calculer la référence
        ventes: historique complet des ventes
        reference_temps: date de calcul (injectable pour test)
        fenetre_jours: fenêtre d'observation en arrière (défaut: 7)
        ventes_min: nombre minimum de ventes requises (défaut: 3)

    Returns:
        la référence de prix (médiane), ou None si insuffisant de ventes.
        Tous les prix doivent être dans la même devise.
    """
    limite_temps = reference_temps - timedelta(days=fenetre_jours)
    ventes_recentes = [
        v for v in ventes
        if v.joueur.slug == joueur.slug and v.date_vente >= limite_temps
    ]

    if len(ventes_recentes) < ventes_min:
        return None

    # Tous les prix doivent être en même devise.
    devises = {v.prix.devise for v in ventes_recentes}
    if len(devises) > 1:
        raise ValueError(f"Ventes en devises mélangées pour {joueur.slug}")

    devise = devises.pop()
    valeurs_triees = sorted(v.prix.valeur for v in ventes_recentes)
    milieu = len(valeurs_triees) // 2
    if len(valeurs_triees) % 2 == 1:
        mediane = valeurs_triees[milieu]
    else:
        # Nombre pair de ventes : aucune des deux valeurs centrales n'est
        # LA médiane. Division entière (arrondi vers le bas), jamais de
        # flottant sur un montant.
        mediane = (valeurs_triees[milieu - 1] + valeurs_triees[milieu]) // 2

    return Montant(mediane, devise)


def references_prix(
    joueurs_liquides: list[Joueur],
    ventes: list[Vente],
    reference_temps: datetime,
) -> dict[str, Montant]:
    """Calcule la référence de prix pour tous les joueurs liquides.

    Args:
        joueurs_liquides: population liquide (résultat de population_liquide())
        ventes: historique des ventes
        reference_temps: date de calcul

    Returns:
        dictionnaire {joueur_slug: référence_prix}.
        Les joueurs sans référence valide en sont absents.
    """
    refs = {}
    for joueur in joueurs_liquides:
        ref = reference_prix_joueur(joueur, ventes, reference_temps)
        if ref is not None:
            refs[joueur.slug] = ref
    return refs
