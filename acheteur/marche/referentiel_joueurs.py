"""Persistance du référentiel de joueurs (pool complet) — construit depuis
l'API Sorare elle-même (compétitions → clubs → joueurs actifs), pas depuis
une base externe.

Remplace le CSV d'origine de `sealing-sorare-apps-script` (collé à la main
depuis la base Postgres d'un autre projet, `sorare_app_v2` — voir
DECISIONS.md, 2026-09-22 : « ce dépôt ne lit jamais la base de Pickdeck »,
donc cette table doit exister sans dépendre d'elle).

⚠️ Ne porte AUCUNE donnée de prix ni de liquidité — seulement l'identité du
joueur (slug, nom, club, compétition domestique). La liquidité et la
référence de prix restent calculées ailleurs, fraîches
(`marche/liquidite.py`, `marche/reference_prix.py`) — mélanger les deux
ferait vivre un prix obsolète dans une table qui ne doit changer qu'une
fois par jour.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from acheteur.core.db import Base

# Une fois par jour, même cadence que `marche.liste_liquidite`
# (DECISIONS.md, 2026-09-22) : le pool de joueurs actifs (transferts,
# retraites) ne change pas assez vite pour justifier un rafraîchissement
# plus fréquent.
DELAI_RAFRAICHISSEMENT_HEURES = 24


class JoueurReferentiel(Base):
    """Un joueur actif connu de l'API Sorare, avec son club et sa
    compétition domestique.

    Remplacée en bloc à chaque rafraîchissement
    (`remplacer_referentiel_joueurs`) — un joueur qui n'a plus de club actif
    dans aucune compétition suivie doit disparaître de la liste, pas y
    traîner avec un vieux `maj_le` (même raison que `JoueurLiquide`).
    """

    __tablename__ = "referentiel_joueurs"

    id: Mapped[int] = mapped_column(primary_key=True)

    joueur_slug: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    nom: Mapped[str] = mapped_column(String, nullable=False, default="")
    club_slug: Mapped[str] = mapped_column(String, nullable=False)
    # La compétition DOMESTIC_LEAGUE du club — vide si le club n'en a
    # aucune dans les compétitions actives connues (voir
    # `cli.maj_referentiel_joueurs._competition_domestique`).
    competition: Mapped[str] = mapped_column(String, nullable=False, default="")

    maj_le: Mapped[datetime] = mapped_column(nullable=False)


# Même raison que `_ID_META_UNIQUE` de `liste_liquidite.py` : une ligne à
# part pour l'horodatage, pour qu'un rafraîchissement qui ne retiendrait
# aucun joueur (cas limite) ne fasse pas perdre la trace qu'il a eu lieu.
_ID_META_UNIQUE = 1


class MetaReferentielJoueurs(Base):
    """Ligne unique : horodatage du dernier rafraîchissement complet."""

    __tablename__ = "meta_referentiel_joueurs"

    id: Mapped[int] = mapped_column(primary_key=True)
    derniere_reconstruction: Mapped[datetime] = mapped_column(nullable=False)


def remplacer_referentiel_joueurs(
    session: Session,
    entrees: list[dict],
    maintenant: datetime,
) -> int:
    """Remplace tout le contenu de la table par `entrees` — un
    rafraîchissement complet, pas une mise à jour incrémentale.

    Args:
        session: session SQLAlchemy (l'appelant commit)
        entrees: `[{"slug", "nom", "club_slug", "competition"}, ...]`
        maintenant: horodatage du rafraîchissement (injectable)

    Returns:
        Le nombre de lignes écrites.
    """
    session.query(JoueurReferentiel).delete()
    for entree in entrees:
        session.add(
            JoueurReferentiel(
                joueur_slug=entree["slug"],
                nom=entree.get("nom", ""),
                club_slug=entree["club_slug"],
                competition=entree.get("competition", ""),
                maj_le=maintenant,
            )
        )

    meta = session.get(MetaReferentielJoueurs, _ID_META_UNIQUE)
    if meta is None:
        session.add(MetaReferentielJoueurs(id=_ID_META_UNIQUE, derniere_reconstruction=maintenant))
    else:
        meta.derniere_reconstruction = maintenant

    session.flush()
    return len(entrees)


def lire_referentiel_joueurs(session: Session) -> list[JoueurReferentiel]:
    """Tout le référentiel courant, tel qu'écrit par le dernier rafraîchissement."""
    return list(session.scalars(select(JoueurReferentiel)).all())


def derniere_maj_referentiel(session: Session) -> datetime | None:
    """L'horodatage du dernier rafraîchissement, ou `None` si jamais construit.

    ⚠️ Même piège que `liste_liquidite.derniere_maj` : SQLite relit un
    `datetime` naïf même écrit en UTC — `UTC` rattaché explicitement pour
    ne pas planter en silence sur une comparaison naïf/aware.
    """
    meta = session.get(MetaReferentielJoueurs, _ID_META_UNIQUE)
    if meta is None:
        return None
    valeur = meta.derniere_reconstruction
    return valeur if valeur.tzinfo is not None else valeur.replace(tzinfo=UTC)


def referentiel_perime(
    session: Session,
    maintenant: datetime,
    delai_heures: int = DELAI_RAFRAICHISSEMENT_HEURES,
) -> bool:
    """Vrai si le référentiel n'a jamais été construit, ou si le dernier
    rafraîchissement date de plus de `delai_heures`."""
    maj = derniere_maj_referentiel(session)
    if maj is None:
        return True
    return maintenant - maj > timedelta(hours=delai_heures)
