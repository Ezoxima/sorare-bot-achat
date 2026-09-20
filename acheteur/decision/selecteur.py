"""Sélection des annonces : filtre sous 90% de référence."""

from __future__ import annotations

from acheteur.marche.devises import Montant
from acheteur.marche.types import Annonce


def est_bonne_affaire(
    annonce: Annonce,
    reference_prix: Montant,
    seuil_pourcent: int = 90,
) -> bool:
    """Vérifie si le prix demandé est sous le seuil de la référence.

    Args:
        annonce: l'annonce à évaluer
        reference_prix: la référence de prix du joueur (mêmes unités que annonce.prix_demande)
        seuil_pourcent: pourcentage max de la référence (défaut: 90%)

    Returns:
        True si prix_demande <= seuil_pourcent % * référence

    Raises:
        ValueError: si l'annonce et la référence ne sont pas dans la même devise
            (comparer un prix en euros à une référence en wei serait absurde).
    """
    if annonce.prix_demande.devise != reference_prix.devise:
        raise ValueError(
            f"Devise mismatch pour {annonce.joueur.slug} : "
            f"annonce en {annonce.prix_demande.devise}, référence en {reference_prix.devise}"
        )

    seuil = (reference_prix.valeur * seuil_pourcent) // 100
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
