"""Stockage du jeton JWT Sorare dans le gestionnaire d'identifiants Windows.

Jamais dans un fichier : un fichier traîne dans les sauvegardes et les
partages d'écran, et ici c'est de l'argent. `keyring` utilise le
gestionnaire Windows (Credential Manager) comme coffre.

Ce module est volontairement passif : il lit et écrit un jeton, il ne se
connecte jamais lui-même à Sorare. La connexion (mot de passe, 2FA) vit dans
`acheteur.auth.connexion`, isolée, jamais importée par la boucle automatique.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

import keyring

from acheteur.core.config import NOM_SERVICE_JETON
from acheteur.core.horloge import Horloge

_NOM_UTILISATEUR = "jwt"


class JetonAbsentError(RuntimeError):
    """Aucun jeton trouvé — une connexion interactive est nécessaire."""


class JetonExpireError(RuntimeError):
    """Le jeton stocké est expiré — une connexion interactive est nécessaire."""


@dataclass(frozen=True)
class InfoJeton:
    token: str
    expire_le: datetime
    aud: str


def enregistrer_jeton(token: str, expire_le: datetime, aud: str) -> None:
    """Écrit le jeton dans le coffre. Écrase toute valeur précédente."""
    if expire_le.tzinfo is None:
        raise ValueError("expire_le doit être un datetime avec fuseau (UTC de préférence).")
    charge = json.dumps({"token": token, "expire_le": expire_le.isoformat(), "aud": aud})
    keyring.set_password(NOM_SERVICE_JETON, _NOM_UTILISATEUR, charge)


def lire_jeton() -> InfoJeton | None:
    """Lit le jeton stocké, ou None si aucun n'a jamais été enregistré."""
    brut = keyring.get_password(NOM_SERVICE_JETON, _NOM_UTILISATEUR)
    if brut is None:
        return None
    charge = json.loads(brut)
    return InfoJeton(
        token=charge["token"],
        expire_le=datetime.fromisoformat(charge["expire_le"]),
        aud=charge["aud"],
    )


def effacer_jeton() -> None:
    try:
        keyring.delete_password(NOM_SERVICE_JETON, _NOM_UTILISATEUR)
    except keyring.errors.PasswordDeleteError:
        pass  # déjà absent — pas une erreur


def obtenir_jeton_valide(horloge: Horloge) -> InfoJeton:
    """Renvoie le jeton courant s'il est valide.

    Ne se reconnecte jamais tout seul (D pas de mot de passe en mémoire dans
    la boucle automatique). Si le jeton est absent ou expiré, la boucle
    automatique doit s'arrêter et prévenir — pas essayer une connexion.
    """
    info = lire_jeton()
    if info is None:
        raise JetonAbsentError(
            "Aucun jeton Sorare enregistré. Lancer la connexion interactive : "
            "python -m acheteur.cli.connecter"
        )
    if info.expire_le <= horloge.maintenant():
        raise JetonExpireError(
            f"Jeton Sorare expiré depuis {horloge.maintenant() - info.expire_le}. "
            "Lancer la connexion interactive : python -m acheteur.cli.connecter"
        )
    return info


def jours_avant_expiration(info: InfoJeton, horloge: Horloge) -> float:
    return (info.expire_le - horloge.maintenant()).total_seconds() / 86400
