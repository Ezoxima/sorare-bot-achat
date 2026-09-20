"""Groupage des offres par vendeur pour propositions groupées."""

from __future__ import annotations

from collections import defaultdict

from acheteur.decision.paliers import Palier, montant_offre
from acheteur.marche.types import Annonce


def grouper_par_vendeur(annonces: list[Annonce]) -> dict[str, list[Annonce]]:
    """Groupe les annonces par vendeur.

    Args:
        annonces: annonces sélectionnées

    Returns:
        dict {vendeur_slug: liste des annonces de ce vendeur}
    """
    groups = defaultdict(list)
    for annonce in annonces:
        groups[annonce.vendeur_slug].append(annonce)
    return dict(groups)


def montants_offre_groupe(
    annonces: list[Annonce],
    palier: Palier,
    decote_groupe: bool = False,
) -> dict[str, int]:
    """Calcule le montant de l'offre pour chaque annonce du groupe.

    Args:
        annonces: les annonces du groupe (même vendeur)
        palier: niveau d'escalade (70%, 75%, 80%)
        decote_groupe: si True, applique 65% au lieu de 70% pour le premier palier

    Returns:
        dict {joueur_slug: montant_offre}
    """
    montants = {}
    for annonce in annonces:
        if decote_groupe and palier == Palier.PREMIER:
            montants[annonce.joueur.slug] = (annonce.prix_demande.valeur * 65) // 100
        else:
            montants[annonce.joueur.slug] = montant_offre(annonce.prix_demande.valeur, palier)
    return montants
