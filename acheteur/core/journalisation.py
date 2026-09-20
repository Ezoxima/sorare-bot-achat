"""Journalisation qui masque ce qui ressemble à un jeton ou à une clé.

Défense en profondeur : même si un secret finit par erreur dans un message de
log (variable mal nommée, exception qui capture trop), il ne doit jamais
atterrir en clair dans un fichier ou une console. Le filtre agit sur le
message déjà formaté, donc il s'applique aussi aux `%s` interpolés.
"""

from __future__ import annotations

import logging
import re

# JWT (trois segments base64url séparés par des points).
_MOTIF_JWT = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")
# Séquence hexadécimale longue (clé StarkEx, clé privée, hash bcrypt...).
_MOTIF_HEX_LONG = re.compile(r"\b0x[a-fA-F0-9]{40,}\b")
# Jeton porteur explicite dans un header ou un message d'erreur.
_MOTIF_BEARER = re.compile(r"(Bearer\s+)[A-Za-z0-9._-]{10,}", re.IGNORECASE)


def _masquer(texte: str) -> str:
    texte = _MOTIF_JWT.sub("[JWT masqué]", texte)
    texte = _MOTIF_HEX_LONG.sub("[hex masqué]", texte)
    texte = _MOTIF_BEARER.sub(r"\1[jeton masqué]", texte)
    return texte


class MasqueSecretsFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _masquer(record.getMessage())
        record.args = ()
        return True


def configurer_journalisation(niveau: int = logging.INFO) -> None:
    """Installe le filtre de masquage sur le logger racine.

    Idempotent : n'ajoute pas le filtre en double si déjà appelé.
    """
    racine = logging.getLogger()
    racine.setLevel(niveau)

    if not any(isinstance(f, MasqueSecretsFilter) for f in racine.filters):
        racine.addFilter(MasqueSecretsFilter())

    if not racine.handlers:
        gestionnaire = logging.StreamHandler()
        gestionnaire.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        racine.addHandler(gestionnaire)
