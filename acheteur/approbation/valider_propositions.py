"""Validation interactive des propositions via CLI (phase 1, humain).

L'utilisateur revoit le tableau et retape le montant total — le protocole
d'un virement bancaire pour empêcher les clics machinaux.
"""

from __future__ import annotations


def _parser_euros_en_centimes(saisie: str) -> int:
    """Parse une saisie EUR ("123", "123.45", "123,45") en centimes, en entier.

    Jamais de `float` sur un montant qui touche un rail de paiement
    (CLAUDE.md) : la conversion se fait par arithmétique entière sur les
    chaînes de caractères, pas par multiplication flottante.

    Raises:
        ValueError: saisie vide, non numérique, ou plus de 2 décimales
            (une précision que l'EUR ne représente pas — mieux vaut refuser
            que d'arrondir silencieusement).
    """
    partie_entiere, separateur, partie_decimale = saisie.replace(",", ".").partition(".")

    if not partie_entiere.lstrip("-").isdigit():
        raise ValueError(f"Partie entière invalide : {partie_entiere!r}")

    if separateur:
        if not partie_decimale.isdigit() or len(partie_decimale) > 2:
            raise ValueError(f"Partie décimale invalide : {partie_decimale!r}")
        partie_decimale = partie_decimale.ljust(2, "0")
    else:
        partie_decimale = "00"

    signe = -1 if partie_entiere.startswith("-") else 1
    centimes_entiers = int(partie_entiere.lstrip("-")) * 100 + int(partie_decimale)
    return signe * centimes_entiers


def confirmer_montant_total(
    montant_total: int,
    montant_retape: int,
    devise_affichage: str = "EUR",
) -> bool:
    """Demande à l'utilisateur de confirmer en retapant le montant total.

    Le montant retapé doit exactement correspondre. Protocole de sécurité
    comme un virement bancaire.

    Args:
        montant_total: montant qu'on propose
        montant_retape: montant que l'utilisateur a retapé
        devise_affichage: devise pour l'affichage (EUR ou ETH)

    Returns:
        True si les montants correspondent, False sinon
    """
    if montant_total == montant_retape:
        return True

    # Formatage pour affichage
    if devise_affichage == "EUR":
        total_str = f"{montant_total / 100:.2f}€"
        retape_str = f"{montant_retape / 100:.2f}€"
    else:  # ETH
        total_str = f"{montant_total} wei"
        retape_str = f"{montant_retape} wei"

    print(f"✗ Montant retapé ({retape_str}) ≠ montant décidé ({total_str})")
    print("  Propositions rejetées. Aucune mutation.")
    return False


def demander_confirmation_utilisateur(
    montant_total: int,
    devise: str = "EUR",
) -> int | None:
    """Demande à l'utilisateur le montant total pour confirmer.

    Interactive CLI prompt pour que l'utilisateur retape le montant.

    Args:
        montant_total: le montant à confirmer
        devise: devise (EUR ou ETH) pour l'affichage

    Returns:
        montant retapé (int), ou None si utilisateur annule
    """
    # Formatage
    if devise == "EUR":
        montant_str = f"{montant_total / 100:.2f}€"
        prompt = f"Retapez le montant total ({montant_str}) pour confirmer : "
        try:
            retape_str = input(prompt).strip()
            # Parser le montant (accepte "123.45" ou "123.45€")
            retape_str = retape_str.replace("€", "").strip()
            montant_retape = _parser_euros_en_centimes(retape_str)
            return montant_retape
        except (ValueError, KeyboardInterrupt):
            return None
    else:  # ETH (wei)
        montant_str = f"{montant_total} wei"
        prompt = f"Retapez le montant en wei ({montant_str}) : "
        try:
            retape_str = input(prompt).strip()
            montant_retape = int(retape_str)
            return montant_retape
        except (ValueError, KeyboardInterrupt):
            return None


def demander_action_utilisateur() -> str:
    """Demande à l'utilisateur : continuer, modifier ou annuler ?

    Returns:
        'continuer', 'modifier', ou 'annuler'
    """
    while True:
        reponse = input(
            "Action ? (continuer/modifier/annuler) : "
        ).strip().lower()
        if reponse in ("continuer", "modifier", "annuler"):
            return reponse
        print("Choix invalide. Réessayez.")
