"""Stockage de la clé privée Ethereum (rail ETH, lot L7) dans le
gestionnaire d'identifiants Windows — même mécanisme que le jeton Sorare
(`acheteur.auth.jeton`), pour la même raison : jamais dans un fichier.

Cette clé signe les `EthereumBankTransferAuthorizationRequest`
(`acheteur.paiement.eth_signature`) ; elle donne accès aux fonds du compte
Ethereum utilisé pour payer sur Sorare. Elle n'est **jamais journalisée** —
`acheteur.core.journalisation` filtre déjà les séquences hex longues, et ce
module ne fait jamais de `logger.info`/`print` sur la clé elle-même, ni sur
le résultat de sa lecture.

Volontairement séparé de `acheteur.auth` : ce n'est pas un secret Sorare
(mot de passe/2FA/JWT), c'est un secret de paiement — la frontière suivie
partout ailleurs dans ce projet entre `auth/` (identité Sorare) et
`paiement/` (rails de paiement) s'applique aussi aux secrets.

Usage interactif : python -m acheteur.cli.enregistrer_cle_ethereum
"""

from __future__ import annotations

import keyring
from eth_account import Account

from acheteur.core.config import NOM_SERVICE_CLE_ETH

_NOM_UTILISATEUR = "cle-privee"


class ClePriveeAbsenteError(RuntimeError):
    """Aucune clé privée Ethereum enregistrée — envoi réel sur le rail ETH impossible."""


class ClePriveeInvalideError(ValueError):
    """La valeur fournie n'est pas une clé privée Ethereum valide (32 octets hex)."""


def _adresse_depuis_cle(cle_privee: str) -> str:
    """Dérive l'adresse publique — sert à faire confirmer le bon compte à
    l'utilisateur sans jamais afficher la clé elle-même. L'adresse n'est pas
    un secret : `eth_account` lève `ValueError` si `cle_privee` est mal formée.
    """
    try:
        return Account.from_key(cle_privee).address
    except ValueError as exc:
        raise ClePriveeInvalideError(f"Clé privée Ethereum invalide : {exc}") from exc


def enregistrer_cle_privee(cle_privee: str) -> str:
    """Valide puis écrit la clé dans le coffre. Écrase toute valeur précédente.

    Returns:
        l'adresse Ethereum dérivée (publique, à afficher pour confirmation).

    Raises:
        ClePriveeInvalideError: si la valeur n'est pas une clé privée Ethereum
            valide (32 octets hex, avec ou sans préfixe `0x`).
    """
    adresse = _adresse_depuis_cle(cle_privee)
    keyring.set_password(NOM_SERVICE_CLE_ETH, _NOM_UTILISATEUR, cle_privee)
    return adresse


def lire_cle_privee() -> str | None:
    """Lit la clé stockée, ou None si aucune n'a jamais été enregistrée."""
    return keyring.get_password(NOM_SERVICE_CLE_ETH, _NOM_UTILISATEUR)


def effacer_cle_privee() -> None:
    try:
        keyring.delete_password(NOM_SERVICE_CLE_ETH, _NOM_UTILISATEUR)
    except keyring.errors.PasswordDeleteError:
        pass  # déjà absente — pas une erreur


def obtenir_cle_privee_valide() -> str:
    """Renvoie la clé courante, ou lève si elle est absente.

    Ne redemande jamais de saisie interactive elle-même (même logique que
    `acheteur.auth.jeton.obtenir_jeton_valide`) : la boucle automatique doit
    s'arrêter et prévenir, pas mendier un secret.
    """
    cle = lire_cle_privee()
    if cle is None:
        raise ClePriveeAbsenteError(
            "Aucune clé privée Ethereum enregistrée. Lancer : "
            "python -m acheteur.cli.enregistrer_cle_ethereum"
        )
    return cle
