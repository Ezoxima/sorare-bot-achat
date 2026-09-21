"""Journalisation qui masque ce qui ressemble à un jeton ou à une clé.

Défense en profondeur : même si un secret finit par erreur dans un message de
log (variable mal nommée, exception qui capture trop), il ne doit jamais
atterrir en clair dans un fichier ou une console. Le filtre agit sur le
message déjà formaté, donc il s'applique aussi aux `%s` interpolés.
"""

from __future__ import annotations

import logging
import re
import sys

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


def _forcer_utf8_console() -> None:
    """Bascule stdout/stderr en UTF-8 si la console ne l'est pas déjà.

    Les CLI du projet impriment des symboles (✓, ✗, ⚠, €) qui n'existent pas
    dans l'encodage par défaut d'une console Windows (`cp1252`) — un premier
    run réel (lot L6, MESURES.md 2026-09-21) a planté sur `⚠` avant même
    d'afficher un message d'alerte pourtant important (cycle suspendu).
    `reconfigure` est un no-op si le flux est déjà en UTF-8 (ex. terminal
    Unix) ; enveloppé dans un `try` parce que certains flux redirigés
    (fichier déjà ouvert, pipe fermé) ne le supportent pas.
    """
    for flux in (sys.stdout, sys.stderr):
        if getattr(flux, "encoding", "").lower() not in ("utf-8", "utf8"):
            try:
                flux.reconfigure(encoding="utf-8")
            except (AttributeError, ValueError, OSError):
                pass


def configurer_journalisation(niveau: int = logging.INFO) -> None:
    """Installe le filtre de masquage sur le logger racine.

    Idempotent : n'ajoute pas le filtre en double si déjà appelé.
    """
    _forcer_utf8_console()

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
