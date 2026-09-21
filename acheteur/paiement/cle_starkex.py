"""Stockage de la clé privée StarkEx (rail EUR, lot L7 suite) dans le
gestionnaire d'identifiants Windows — même mécanisme que le jeton Sorare
(`acheteur.auth.jeton`) et que la clé Ethereum (`acheteur.paiement.cle_ethereum`).

Cette clé est celle du **compte Starkware**, distincte de la clé du compte
Ethereum (rail ETH) — elle signe les `MangopayWalletTransferAuthorizationRequest`
(`acheteur.paiement.starkex_signature`). Jamais dans un fichier, jamais
journalisée (`acheteur.core.journalisation` filtre déjà les séquences hex
longues).

Usage interactif : python -m acheteur.cli.enregistrer_cle_starkex
"""

from __future__ import annotations

import keyring

from acheteur.core.config import NOM_SERVICE_CLE_STARKEX
from acheteur.paiement.starkex_signature import exporter_cle_publique_starkex

_NOM_UTILISATEUR = "cle-privee"


class ClePriveeAbsenteError(RuntimeError):
    """Aucune clé privée StarkEx enregistrée — envoi réel sur le rail EUR impossible."""


class ClePriveeInvalideError(ValueError):
    """La valeur fournie n'est pas une clé privée StarkEx valide (entier hex)."""


def enregistrer_cle_privee(cle_privee: str) -> str:
    """Valide puis écrit la clé dans le coffre. Écrase toute valeur précédente.

    Returns:
        la clé publique StarkEx dérivée (publique, à afficher pour confirmation).

    Raises:
        ClePriveeInvalideError: si la valeur n'est pas une clé privée StarkEx
            valide (entier hex, avec ou sans préfixe `0x`).
    """
    try:
        cle_publique = exporter_cle_publique_starkex(cle_privee)
    except (ValueError, AssertionError) as exc:
        raise ClePriveeInvalideError(f"Clé privée StarkEx invalide : {exc}") from exc
    keyring.set_password(NOM_SERVICE_CLE_STARKEX, _NOM_UTILISATEUR, cle_privee)
    return cle_publique


def lire_cle_privee() -> str | None:
    """Lit la clé stockée, ou None si aucune n'a jamais été enregistrée."""
    return keyring.get_password(NOM_SERVICE_CLE_STARKEX, _NOM_UTILISATEUR)


def effacer_cle_privee() -> None:
    try:
        keyring.delete_password(NOM_SERVICE_CLE_STARKEX, _NOM_UTILISATEUR)
    except keyring.errors.PasswordDeleteError:
        pass  # déjà absente — pas une erreur


def obtenir_cle_privee_valide() -> str:
    """Renvoie la clé courante, ou lève si elle est absente.

    Ne redemande jamais de saisie interactive elle-même (même logique que
    `acheteur.auth.jeton.obtenir_jeton_valide` et
    `acheteur.paiement.cle_ethereum.obtenir_cle_privee_valide`).
    """
    cle = lire_cle_privee()
    if cle is None:
        raise ClePriveeAbsenteError(
            "Aucune clé privée StarkEx enregistrée. Lancer : "
            "python -m acheteur.cli.enregistrer_cle_starkex"
        )
    return cle
