"""Annulation d'une offre ouverte (lot L7, veille défensive — PLAN.md §
« On n'annule jamais pour reposter plus haut »).

Symétrique de `garde_fous.barriere` pour l'envoi, en plus simple : annuler
n'engage pas d'argent (donc pas des neuf garde-fous), mais reste une action
irréversible côté Sorare — CLAUDE.md exige la même vigilance sur tout ce qui
touche `acheteur/negociation/`. Ce module est le seul point qui marque une
ligne `ANNULEE` et appelle `cancelOffer`.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from acheteur.core.horloge import Horloge
from acheteur.garde_fous.regles import verifier_arrêt_d_urgence
from acheteur.negociation.journal import EtatOffre, OffreJournal
from acheteur.sorare.client import SorareClient
from acheteur.sorare.mutations import annuler_offre_sorare

logger = logging.getLogger(__name__)


def annuler_ligne(
    ligne: OffreJournal,
    session: Session,
    horloge: Horloge,
    *,
    blockchain_id: str | None = None,
    mode_simulation: bool = True,
    chemin_racine: Path = Path("."),
    client: SorareClient | None = None,
) -> None:
    """Annule une ligne ouverte : marque `ANNULEE` en base, puis `cancelOffer`
    côté Sorare si `mode_simulation` est faux.

    Args:
        ligne: la ligne à annuler (doit être dans un état ouvert)
        session: session SQLAlchemy
        horloge: horloge injectable
        blockchain_id: `TokenOffer.blockchainId` de l'offre, requis si
            `mode_simulation` est faux et que `ligne.sorare_id` est déjà
            connu (offre réellement envoyée, pas seulement simulée)
        mode_simulation: True = ne touche que la base locale
        chemin_racine: chemin racine pour détection arrêt d'urgence
        client: client Sorare, requis si `mode_simulation` est faux

    Raises:
        GuardrailViolation: si l'arrêt d'urgence est actif
        ValueError: si le mode réel manque le client ou le blockchain_id
            requis pour une ligne déjà envoyée à Sorare
    """
    verifier_arrêt_d_urgence(chemin_racine)

    maintenant: datetime = horloge.maintenant()
    ligne.etat = EtatOffre.ANNULEE
    ligne.maj_le = maintenant
    session.flush()

    if mode_simulation:
        return

    if ligne.sorare_id is None:
        # Ligne envoyée en simulation seulement (jamais atteint Sorare) :
        # rien à annuler côté réseau.
        return

    if client is None:
        raise ValueError("Mode réel exige un client Sorare. Passez client=... à annuler_ligne")
    if not blockchain_id:
        raise ValueError(
            f"Annulation réelle de {ligne.sorare_id} exige blockchain_id "
            "(TokenOffer.blockchainId, distinct de sorare_id)."
        )

    try:
        reponse = annuler_offre_sorare(client, blockchain_id)
        payload = reponse.get("cancelOffer") or {}
        if payload.get("errors"):
            logger.error("Erreurs cancelOffer pour %s : %s", ligne.sorare_id, payload["errors"])
        else:
            logger.info("Offre annulée : %s (blockchain_id=%s)", ligne.sorare_id, blockchain_id)
    except Exception as exc:
        # La ligne reste marquée ANNULEE localement même si l'appel réseau
        # échoue : la réconciliation suivante rattrapera l'écart, comme pour
        # l'envoi (barriere.py) — mieux vaut un état local optimiste que de
        # rouvrir une ligne qu'on a déjà décidé de fermer.
        logger.error("Erreur lors de cancelOffer pour %s : %s", ligne.sorare_id, exc)
