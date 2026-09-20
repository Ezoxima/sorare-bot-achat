"""Règles pures des garde-fous : 9 contraintes qui empêchent les erreurs.

Aucune règle ne mute rien — ce sont des vérifications pures. L'appelant
(barrière.py) reçoit `bool` et décide d'envoyer ou non.

PLAN.md § « Garde-fous : ta règle, appliquée au bon moment » définit chaque
règle. Les CHECK en base (journal.py) complètent ce code en empêchant
physiquement les violations au niveau SQL.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from acheteur.core.horloge import Horloge
from acheteur.decision.proposition import PropositionGroupe, PropositionSimple
from acheteur.marche.devises import Devise, Montant


class GuardrailViolation(Exception):
    """Une règle a été violée."""

    pass


def verifier_solde_suffisant(
    montant_total_propose: int,
    soldes_ouverts: int,
    solde_disponible: int,
) -> None:
    """Règle 1 : somme des offres ouvertes ≤ solde disponible du rail.

    Args:
        montant_total_propose: montant qu'on s'apprête à ajouter
        soldes_ouverts: somme des offres déjà ouvertes (en attente)
        solde_disponible: solde du compte sur ce rail

    Raises:
        GuardrailViolation: si soldes_ouverts + montant > solde_disponible
    """
    if soldes_ouverts + montant_total_propose > solde_disponible:
        raise GuardrailViolation(
            f"Solde insuffisant : {soldes_ouverts} + {montant_total_propose} > {solde_disponible}"
        )


def verifier_solde_relu_juste_avant(
    solde_timestamp: datetime,
    horloge: Horloge,
    tolerance_sec: int = 30,
) -> None:
    """Règle 2 : solde relu juste avant l'envoi (tolerance 30 sec par défaut).

    Args:
        solde_timestamp: quand le solde a été lu
        horloge: horloge injectable
        tolerance_sec: tolérance en secondes (défaut 30 sec)

    Raises:
        GuardrailViolation: si le solde est trop ancien
    """
    age = horloge.maintenant() - solde_timestamp
    if age > timedelta(seconds=tolerance_sec):
        raise GuardrailViolation(
            f"Solde obsolète : lu il y a {age.total_seconds():.0f}s (tolérance {tolerance_sec}s)"
        )


def verifier_offre_ne_depasse_pas_prix_demande(
    montant_offre: int,
    prix_demande: int,
) -> None:
    """Règle 3 : ne jamais offrir plus que le prix demandé.

    Un dépassement signale presque toujours une erreur d'unité, pas une décision.

    Args:
        montant_offre: montant qu'on propose
        prix_demande: prix affiché par le vendeur

    Raises:
        GuardrailViolation: si offre > prix_demande
    """
    if montant_offre > prix_demande:
        raise GuardrailViolation(
            f"Offre dépasse le prix demandé : {montant_offre} > {prix_demande}"
        )


def verifier_coherence_unites(montant: int, devise: Devise) -> None:
    """Règle 4 : cohérence d'unité ETH/centimes.

    ETH a 18 décimales (wei). Un entier petit (< 10^15) dans ETH est presque
    sûrement des centimes non convertis. Un montant nul est interdit.

    Args:
        montant: valeur numérique
        devise: devise (ETH ou EUR)

    Raises:
        GuardrailViolation: si montant est 0 ou unité suspecte
    """
    if montant <= 0:
        raise GuardrailViolation(f"Montant nul ou négatif : {montant}")

    if devise == Devise.ETH:
        # Un wei < 10^15 n'a pas assez de décimales pour être un vrai prix en ETH
        if montant < 10**15:
            raise GuardrailViolation(
                f"Wei suspectemet petit ({montant}) — possiblement centimes non convertis"
            )


def verifier_taux_change_frais(
    taux_timestamp: datetime | None,
    horloge: Horloge,
    tolerance_min: int = 15,
) -> None:
    """Règle 5 : taux de change < 15 min (sinon refuser de convertir).

    Args:
        taux_timestamp: quand le taux a été lu (None = pas de conversion)
        horloge: horloge injectable
        tolerance_min: tolérance en minutes (défaut 15)

    Raises:
        GuardrailViolation: si taux est obsolète
    """
    if taux_timestamp is None:
        return  # Pas de conversion, aucune contrainte

    age = horloge.maintenant() - taux_timestamp
    if age > timedelta(minutes=tolerance_min):
        raise GuardrailViolation(
            f"Taux de change obsolète : {age.total_seconds()/60:.1f}m (tolérance {tolerance_min}min)"
        )


def verifier_palier_valide(palier: int) -> None:
    """Règle 6 : palier plafonné à 80%.

    PLAN.md et DECISIONS.md tranchent : max 80%, c'est un réglage, pas une
    constante arbitraire. La base (journal.py) porte un CHECK — ce code le
    réitère en couche applicative pour éviter les appels réseau inutiles.

    Args:
        palier: pourcentage du palier (70, 75, 80)

    Raises:
        GuardrailViolation: si palier > 80
    """
    if palier > 80:
        raise GuardrailViolation(f"Palier dépasse 80% : {palier}%")


def verifier_offres_par_vendeur_limitees(
    vendeur_slug: str,
    offres_ouvertes_par_vendeur: dict[str, int],
    plafond_par_vendeur: int = 5,
) -> None:
    """Règle 7 : plafond d'offres ouvertes par vendeur.

    Pas un budget : une précaution contre le démarchage tant qu'on ne sait
    pas si Sorare a un anti-spam. PLAN.md demande ce plafond ; le nombre
    exact (5) est injectable pour affiner après mesure.

    Args:
        vendeur_slug: le vendeur auquel on s'apprête à faire une offre
        offres_ouvertes_par_vendeur: dict {vendeur_slug: nombre d'offres ouvertes}
        plafond_par_vendeur: nombre max d'offres par vendeur (défaut 5)

    Raises:
        GuardrailViolation: si déjà au plafond pour ce vendeur
    """
    count = offres_ouvertes_par_vendeur.get(vendeur_slug, 0)
    if count >= plafond_par_vendeur:
        raise GuardrailViolation(
            f"Plafond d'offres atteint pour vendeur {vendeur_slug} : {count}/{plafond_par_vendeur}"
        )


def verifier_arrêt_d_urgence(chemin_racine: Path = Path(".")) -> None:
    """Règle 8 : arrêt d'urgence (fichier à la racine du projet).

    Si le fichier `.arret-urgence` existe à la racine, tout est bloqué.
    C'est le disjoncteur : même le bot en mode réel s'arrête s'il existe.

    Args:
        chemin_racine: racine du projet (défaut : ".")

    Raises:
        GuardrailViolation: si fichier d'arrêt existe
    """
    fichier_arret = chemin_racine / ".arret-urgence"
    if fichier_arret.exists():
        raise GuardrailViolation(f"Arrêt d'urgence activé ({fichier_arret})")


def verifier_mode_reel_verrous(
    env_var_mode_reel: bool,
    cli_arg_mode_reel: bool,
    montant_retape: int,
    montant_decide: int,
) -> None:
    """Règle 9 : mode réel verrouillé par trois cadenas indépendants.

    Protocole d'un virement bancaire : pas un seul paramètre ne suffit.

    Args:
        env_var_mode_reel: ACHETEUR_MODE_REEL=True dans l'env
        cli_arg_mode_reel: --mode-reel dans la CLI
        montant_retape: montant retapé par l'utilisateur
        montant_decide: montant décidé par le bot

    Raises:
        GuardrailViolation: si l'un des trois verrous est absent ou incorrect
    """
    if not env_var_mode_reel:
        raise GuardrailViolation("Mode réel : env var ACHETEUR_MODE_REEL manquante")

    if not cli_arg_mode_reel:
        raise GuardrailViolation("Mode réel : flag --mode-reel manquant en CLI")

    if montant_retape != montant_decide:
        raise GuardrailViolation(
            f"Mode réel : montant retapé ({montant_retape}) ≠ montant décidé ({montant_decide})"
        )
