"""Sélection des annonces : filtre sous 90% de référence."""

from __future__ import annotations

from datetime import datetime

from acheteur.marche.devises import Montant
from acheteur.marche.types import Annonce, Vente

# Sorare prélève 5% du montant sur toute revente (frais de transaction sur la
# vente d'une carte). `reference_prix` est calculée sur des ventes conclues,
# donc au PRIX BRUT payé par l'acheteur — pas ce que le vendeur (nous, plus
# tard) touchera réellement en revendant au même niveau. Sans cette
# correction, `est_bonne_affaire` compare le prix d'achat à un objectif de
# revente qu'on ne peut pas réellement atteindre net : elle surestime la
# marge de 5 points de pourcentage sur toute transaction. Voir DECISIONS.md
# (2026-09-22).
TAUX_TAXE_REVENTE_POURCENT = 5


def reference_nette_de_taxe(reference_prix: Montant) -> Montant:
    """La référence de prix, nette des 5% que Sorare prélève à la revente.

    C'est ce qu'on peut réellement espérer récupérer en revendant au niveau
    de la référence — pas la référence brute (prix payé par l'acheteur lors
    des ventes passées qui l'ont construite).
    """
    valeur_nette = (reference_prix.valeur * (100 - TAUX_TAXE_REVENTE_POURCENT)) // 100
    return Montant(valeur_nette, reference_prix.devise)


def est_bonne_affaire(
    annonce: Annonce,
    reference_prix: Montant,
    seuil_pourcent: int = 90,
) -> bool:
    """Vérifie si le prix demandé est sous le seuil de la référence NETTE de
    la taxe de revente (5%, voir `TAUX_TAXE_REVENTE_POURCENT`).

    Args:
        annonce: l'annonce à évaluer
        reference_prix: la référence de prix BRUTE du joueur (mêmes unités
            que annonce.prix_demande) — la conversion en net se fait ici.
        seuil_pourcent: pourcentage max de la référence nette (défaut: 90%)

    Returns:
        True si prix_demande <= seuil_pourcent % * référence nette de taxe

    Raises:
        ValueError: si l'annonce et la référence ne sont pas dans la même devise
            (comparer un prix en euros à une référence en wei serait absurde).
    """
    if annonce.prix_demande.devise != reference_prix.devise:
        raise ValueError(
            f"Devise mismatch pour {annonce.joueur.slug} : "
            f"annonce en {annonce.prix_demande.devise}, référence en {reference_prix.devise}"
        )

    reference_nette = reference_nette_de_taxe(reference_prix)
    seuil = (reference_nette.valeur * seuil_pourcent) // 100
    return annonce.prix_demande.valeur <= seuil


# Second signal de sélection, indépendant de `est_bonne_affaire` : une
# annonce postée sous le minimum des ventes qui l'ont précédée, chez un
# petit vendeur. Inspiré de `SOUS_VENTE_MINI`
# (`sealing-sorare-apps-script/03 - bonnes affaires.gs`) : l'utilisateur y a
# trouvé empiriquement de bonnes affaires, et signale que le signal est
# surtout fort quand `seuilPct` ET la petite taille du vendeur (vérifiée à
# part, côté réseau — voir `cli/scan_marche.py`) sont réunis (2026-09-22).
#
# ⚠️ Version volontairement simplifiée par rapport aux `.gs` : ceux-ci
# laissent en plus une enchère ou l'annonce la moins chère de la passe
# précédente faire BAISSER ce minimum. `acheteur` ne conserve pas d'état
# entre deux passes de `scan_marche.py` (lecture seule, rien n'est persisté)
# et ne lit pas les enchères (hors périmètre, PLAN.md) — cette fonction ne
# regarde donc que les ventes entre managers antérieures à la mise en vente.
SOUS_VENTE_MINI_SEUIL_POURCENT_DEFAUT = 80


def prix_minimum_avant(ventes: list[Vente], avant: datetime) -> Montant | None:
    """Le prix minimum parmi des ventes strictement antérieures à `avant`.

    Args:
        ventes: historique de ventes du joueur (même rareté/saison que
            l'annonce évaluée — filtré par l'appelant, comme pour
            `reference_prix_joueur`)
        avant: date de mise en vente de l'annonce jugée (point-in-time :
            on ne compare qu'à ce qui existait déjà, jamais à des ventes
            que l'annonce elle-même aurait pu influencer)

    Returns:
        Le montant le plus bas, ou `None` si aucune vente antérieure.

    Raises:
        ValueError: ventes antérieures en devises mélangées — un mélange
            EUR/wei rendrait le minimum arbitraire.
    """
    candidates = [v.prix for v in ventes if v.date_vente < avant]
    if not candidates:
        return None
    devises = {m.devise for m in candidates}
    if len(devises) > 1:
        raise ValueError(f"Ventes antérieures en devises mélangées : {devises}")
    return min(candidates, key=lambda m: m.valeur)


def est_sous_vente_minimum(
    annonce: Annonce,
    ventes: list[Vente],
    seuil_pourcent: int = SOUS_VENTE_MINI_SEUIL_POURCENT_DEFAUT,
) -> bool:
    """Vrai si le prix demandé est sous `seuil_pourcent`% du minimum des
    ventes antérieures à la mise en vente de l'annonce.

    Ne dit rien de la joignabilité du vendeur (taille de sa vitrine) — voir
    `cli/scan_marche.py` pour le croisement avec la taille du stock,
    nécessaire côté réseau et donc hors de cette fonction pure.

    Returns:
        False si aucune vente antérieure exploitable, ou si l'annonce et
        les ventes ne sont pas dans la même devise (jamais une exception ici
        : contrairement à `est_bonne_affaire`, l'absence de référence est un
        cas normal et fréquent pour ce signal, pas une erreur d'appelant).
    """
    minimum = prix_minimum_avant(ventes, annonce.date_pose)
    if minimum is None or minimum.devise != annonce.prix_demande.devise:
        return False
    seuil = (minimum.valeur * seuil_pourcent) // 100
    return annonce.prix_demande.valeur <= seuil


def selectionner_annonces(
    annonces: list[Annonce],
    references: dict[str, Montant],  # joueur_slug -> référence de prix
    seuil_pourcent: int = 90,
) -> list[Annonce]:
    """Filtre les annonces qui sont des bonnes affaires.

    Args:
        annonces: toutes les annonces du marché
        references: dict {joueur_slug: référence de prix}
        seuil_pourcent: pourcentage max de la référence (défaut: 90%)

    Returns:
        annonces sélectionnées (triées par joueur/prix pour reproductibilité)
    """
    selectionnees = []
    for annonce in annonces:
        if annonce.joueur.slug not in references:
            continue
        ref = references[annonce.joueur.slug]
        if est_bonne_affaire(annonce, ref, seuil_pourcent):
            selectionnees.append(annonce)

    return sorted(selectionnees, key=lambda a: (a.joueur.slug, a.prix_demande.valeur))
