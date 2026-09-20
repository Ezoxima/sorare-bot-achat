"""Sélection des annonces : filtre sous 90% de référence."""

from __future__ import annotations

from acheteur.marche.types import Annonce


def est_bonne_affaire(
    annonce: Annonce,
    reference_prix: int,
    seuil_pourcent: int = 90,
) -> bool:
    """Vérifie si le prix demandé est sous le seuil de la référence.

    Args:
        annonce: l'annonce à évaluer
        reference_prix: la référence de prix du joueur (même devise que annonce.prix_demande)
        seuil_pourcent: pourcentage max de la référence (défaut: 90%)

    Returns:
        True si prix_demande <= seuil_pourcent % * référence
    """
    if annonce.prix_demande.devise != annonce.prix_demande.devise:
        raise ValueError("Devise mismatch")

    seuil = (reference_prix * seuil_pourcent) // 100
    return annonce.prix_demande.valeur <= seuil


def selectionner_annonces(
    annonces: list[Annonce],
    references: dict[str, int],  # joueur_slug -> référence_prix_valeur
    seuil_pourcent: int = 90,
) -> list[Annonce]:
    """Filtre les annonces qui sont des bonnes affaires.

    Args:
        annonces: toutes les annonces du marché
        references: dict {joueur_slug: référence_prix_valeur}
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
