"""Groupage des offres par vendeur pour propositions groupées."""

from __future__ import annotations

from collections import defaultdict

from acheteur.decision.paliers import Palier, montant_offre
from acheteur.marche.devises import Devise, arrondir_wei_a_la_maille
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
) -> dict[str, int]:
    """Calcule le montant de l'offre pour chaque annonce du groupe.

    La décote de groupe (65% au lieu de 70%) s'applique au premier palier
    dès que le groupe compte plus d'une annonce — ce n'est pas un réglage
    au choix de l'appelant, c'est la même règle que `proposition.proposer_groupe`
    (DECISIONS.md, lot L3). Les deux fonctions doivent rester en accord :
    un groupe de deux cartes ou plus se décote, un groupe d'une carte non.

    Args:
        annonces: les annonces du groupe (même vendeur)
        palier: niveau d'escalade (70%, 75%, 80%)

    Returns:
        dict {joueur_slug: montant_offre}
    """
    decote = palier == Palier.PREMIER and len(annonces) > 1
    montants = {}
    for annonce in annonces:
        if decote:
            montant = (annonce.prix_demande.valeur * 65) // 100
        else:
            montant = montant_offre(annonce.prix_demande.valeur, palier)
        # Maille du carnet Sorare en ETH (0.0001 ETH) — voir proposition.py,
        # même règle, doit rester en accord (test_montants_offre_groupe_coherent_avec_proposer_groupe).
        if annonce.prix_demande.devise == Devise.ETH:
            montant = arrondir_wei_a_la_maille(montant)
        montants[annonce.joueur.slug] = montant
    return montants
