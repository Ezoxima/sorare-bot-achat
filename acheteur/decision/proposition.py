"""Proposition complète d'offre : annonce(s), montant(s), référence, écart."""

from __future__ import annotations

from dataclasses import dataclass

from acheteur.decision.paliers import Palier, montant_offre
from acheteur.marche.types import Annonce


@dataclass(frozen=True)
class PropositionSimple:
    """Une offre sur une annonce unique."""

    annonce: Annonce
    reference_prix_valeur: int  # Même devise que annonce.prix_demande
    montant_offre: int
    palier: Palier

    @property
    def ecart_pourcent(self) -> float:
        """Écart entre prix demandé et montant proposé, en %."""
        if self.reference_prix_valeur == 0:
            return 0.0
        return (self.montant_offre * 100.0) / self.reference_prix_valeur

    @property
    def pourcent_demande(self) -> float:
        """Montant offert en % du prix demandé."""
        if self.annonce.prix_demande.valeur == 0:
            return 0.0
        return (self.montant_offre * 100.0) / self.annonce.prix_demande.valeur


def proposer_simple(
    annonce: Annonce,
    reference_valeur: int,
    palier: Palier,
) -> PropositionSimple:
    """Crée une proposition pour une annonce simple.

    Args:
        annonce: l'annonce
        reference_valeur: référence de prix du joueur (même devise)
        palier: niveau d'escalade

    Returns:
        proposition prête à être examinée
    """
    montant = montant_offre(annonce.prix_demande.valeur, palier)
    return PropositionSimple(
        annonce=annonce,
        reference_prix_valeur=reference_valeur,
        montant_offre=montant,
        palier=palier,
    )


@dataclass(frozen=True)
class PropositionGroupe:
    """Une offre groupée sur plusieurs annonces du même vendeur."""

    annonces: tuple[Annonce, ...]  # Immuable
    references_prix: dict[str, int]  # joueur_slug -> valeur
    montants_offre: dict[str, int]  # joueur_slug -> montant
    palier: Palier
    decote_appliquee: bool

    @property
    def montant_total(self) -> int:
        """Somme des montants offerts pour le groupe."""
        return sum(self.montants_offre.values())

    @property
    def pourcent_demande_moyen(self) -> float:
        """Montant total offert en % du prix demandé total."""
        prix_demande_total = sum(a.prix_demande.valeur for a in self.annonces)
        if prix_demande_total == 0:
            return 0.0
        return (self.montant_total * 100.0) / prix_demande_total


def proposer_groupe(
    annonces: list[Annonce],
    references: dict[str, int],
    palier: Palier,
) -> PropositionGroupe:
    """Crée une proposition groupée pour plusieurs annonces.

    Args:
        annonces: les annonces du groupe (même vendeur recommandé)
        references: dict {joueur_slug: référence_prix_valeur}
        palier: niveau d'escalade

    Returns:
        proposition groupée
    """
    montants = {}
    refs_utilisees = {}
    decote = False

    for annonce in annonces:
        if annonce.joueur.slug not in references:
            continue

        ref = references[annonce.joueur.slug]
        refs_utilisees[annonce.joueur.slug] = ref

        # Décote 65% seulement au premier palier
        if palier == Palier.PREMIER and len(annonces) > 1:
            montants[annonce.joueur.slug] = (annonce.prix_demande.valeur * 65) // 100
            decote = True
        else:
            montants[annonce.joueur.slug] = montant_offre(annonce.prix_demande.valeur, palier)

    return PropositionGroupe(
        annonces=tuple(annonces),
        references_prix=refs_utilisees,
        montants_offre=montants,
        palier=palier,
        decote_appliquee=decote,
    )
