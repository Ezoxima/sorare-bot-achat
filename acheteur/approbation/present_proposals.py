"""Formatage des propositions pour présentation à l'utilisateur (phase 1).

Jamais un chiffre sans son effectif (PLAN.md). Format email-like : table
claire avec tous les éléments de justification.
"""

from __future__ import annotations

from dataclasses import dataclass

from acheteur.marche.devises import Devise, Montant
from acheteur.negociation.journal import OffreJournal


@dataclass(frozen=True)
class LigneProposition:
    """Une ligne formatée prête pour affichage."""

    joueur_nom: str
    rareté: str
    vendeur_slug: str
    prix_demande: str
    reference_mediane: str
    fenetre_jours: int
    nb_ventes: int
    ecart_reference_pct: float
    palier_pct: int
    montant_offre: str
    rail: str
    solde_restant: str


def formatter_propositions_html(
    lignes: list[OffreJournal],
    soldes_par_devise: dict[Devise, Montant],
    offres_ouvertes_par_devise: dict[Devise, int],
) -> str:
    """Formate les propositions en tableau HTML/texte lisible.

    Args:
        lignes: les lignes du journal simulées (mode_simulation=True)
        soldes_par_devise: {devise: Montant disponible}
        offres_ouvertes_par_devise: {devise: somme des offres ouvertes}

    Returns:
        représentation texte formatée (table markdown-like)
    """
    if not lignes:
        return "Aucune proposition."

    # En-tête
    lines = [
        "PROPOSITIONS PRÊTES À VALIDER",
        "=" * 120,
        "",
        "Joueur | Rareté | Vendeur | Prix demandé | Référence (fenêtre/ventes) | Écart | Palier | "
        "Montant | Rail | Solde restant",
        "-" * 120,
    ]

    # Lignes de données
    total_par_devise = {}
    for ligne in lignes:
        # Devise
        devise = ligne.montant_offre_devise
        montant_val = ligne.montant_offre_valeur
        solde_dispo = soldes_par_devise[devise].valeur
        solde_ouvert = offres_ouvertes_par_devise.get(devise, 0)
        solde_restant = solde_dispo - solde_ouvert

        # Formatage devise
        if devise == Devise.EUR:
            montant_str = f"{montant_val / 100:.2f}€"
            solde_str = f"{solde_restant / 100:.2f}€"
            rail_str = "EUR"
        else:  # ETH
            montant_str = f"{montant_val} wei"
            solde_str = f"{solde_restant} wei"
            rail_str = "ETH"

        # Référence
        if ligne.reference_prix_valeur and ligne.reference_nb_ventes:
            ref_str = f"{ligne.reference_prix_valeur} ({ligne.reference_fenetre_jours}j, {ligne.reference_nb_ventes}v)"
        else:
            ref_str = "—"

        # Écart
        if ligne.reference_prix_valeur:
            ecart = (ligne.montant_offre_valeur * 100.0) / ligne.reference_prix_valeur
            ecart_str = f"{ecart:.0f}%"
        else:
            ecart_str = "—"

        # Ligne
        lines.append(
            f"{ligne.joueur_slug:<10} | {ligne.prix_demande_devise.value:<6} | {ligne.vendeur_slug:<10} | "
            f"{ligne.prix_demande_valeur if ligne.prix_demande_valeur else '—':<12} | {ref_str:<28} | "
            f"{ecart_str:<5} | {ligne.palier or '—'}% | {montant_str:<12} | {rail_str:<4} | {solde_str}"
        )

        # Accum totaux
        total_par_devise[devise] = total_par_devise.get(devise, 0) + montant_val

    # Totaux
    lines.append("-" * 120)
    for devise, total in total_par_devise.items():
        if devise == Devise.EUR:
            total_str = f"{total / 100:.2f}€"
        else:
            total_str = f"{total} wei"
        lines.append(f"TOTAL {devise.value.upper()}: {total_str}")

    return "\n".join(lines)


def formatter_propositions_email(
    lignes: list[OffreJournal],
    soldes_par_devise: dict[Devise, Montant],
    offres_ouvertes_par_devise: dict[Devise, int],
) -> str:
    """Formate pour copier dans un mail (compatible avec Apps Script actuel).

    Args:
        lignes: les lignes du journal simulées
        soldes_par_devise: {devise: Montant disponible}
        offres_ouvertes_par_devise: {devise: somme des offres ouvertes}

    Returns:
        texte tabulaire mail-friendly
    """
    # Pour l'instant, réutilise le format HTML (peut être raffiné)
    return formatter_propositions_html(lignes, soldes_par_devise, offres_ouvertes_par_devise)
