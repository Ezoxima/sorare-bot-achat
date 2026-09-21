"""Persistance de la liste des couples (joueur, rareté, éligibilité de
saison) liquides — le pré-filtre de `marche/liquidite.py`, mais gardé
d'une exécution à l'autre plutôt que recalculé à chaque passe.

Pourquoi cette persistance existe : `cli/scan_marche.py` recalcule
aujourd'hui la liquidité de zéro sur un échantillon tiré au hasard à chaque
exécution — correct pour valider les critères (lot L8), mais inadapté à une
tâche planifiée toutes les x minutes (lot L9, PLAN.md) : la liquidité se
mesure sur une fenêtre de 30 jours à granularité hebdomadaire, elle ne
bouge pas assez vite pour justifier un recalcul aussi fréquent. Même
découpage que `sealing-sorare-apps-script`
(`majListeBonnesAffaires`/`lireCouplesSuivis_`) : un job lent reconstruit
cette liste (voir `DELAI_RAFRAICHISSEMENT_HEURES` — 24h, choix explicite de
l'utilisateur, 2026-09-22), un job rapide ne fait que la lire.

⚠️ **Cette table ne stocke JAMAIS de référence de prix** — seulement le
FAIT qu'un couple est liquide (et les compteurs qui le prouvent, pour le
diagnostic). La référence de prix doit toujours être recalculée fraîche au
moment de la décision d'achat (PLAN.md/CLAUDE.md : « figer la référence de
marché au moment de l'envoi », pas avant) — mélanger les deux ferait vivre
un prix obsolète dans une table censée ne durer qu'un jour.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from acheteur.core.db import Base

# Choix explicite de l'utilisateur (2026-09-22), aligné sur
# `sealing-sorare-apps-script` (`majListeBonnesAffaires`, une fois par
# jour) : la fenêtre de liquidité (30 jours, granularité hebdomadaire) ne
# justifie pas un rafraîchissement plus fréquent.
DELAI_RAFRAICHISSEMENT_HEURES = 24


class JoueurLiquide(Base):
    """Un couple (joueur, rareté, éligibilité de saison) qui passait
    `marche.liquidite.est_liquide` lors du dernier rafraîchissement complet.

    Remplacée en bloc à chaque rafraîchissement (`remplacer_liste_liquidite`)
    — pas de mise à jour ligne à ligne : un couple qui n'est plus liquide
    doit disparaître de la liste, pas y traîner avec un vieux `maj_le`.
    """

    __tablename__ = "joueurs_liquides"

    id: Mapped[int] = mapped_column(primary_key=True)

    joueur_slug: Mapped[str] = mapped_column(String, nullable=False)
    # Rareté brute Sorare en minuscules ("limited", "rare"...) — voir
    # `marche.traduction.rarity_brute_depuis_annonce`.
    rarete: Mapped[str] = mapped_column(String, nullable=False)
    # "CLASSIC" ou "IN_SEASON" — voir
    # `marche.traduction.season_eligibility_brute_depuis_annonce`.
    season_eligibility: Mapped[str] = mapped_column(String, nullable=False)

    # Compteurs de `marche.liquidite.Liquidite`, conservés pour le
    # diagnostic (voir un jour pourquoi tel joueur est/n'est plus retenu)
    # — jamais relus pour une décision, seule la PRÉSENCE de la ligne compte.
    n30: Mapped[int] = mapped_column(nullable=False)
    n7: Mapped[int] = mapped_column(nullable=False)
    semaines_actives: Mapped[int] = mapped_column(nullable=False)

    maj_le: Mapped[datetime] = mapped_column(nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "joueur_slug", "rarete", "season_eligibility",
            name="uq_joueur_liquide_couple",
        ),
    )


# Ligne unique (id fixe) portant l'horodatage du dernier rafraîchissement
# complet — SÉPARÉE de `JoueurLiquide` exprès : un rafraîchissement qui ne
# retient aucun couple (liste vide, cas limite mais possible) ne doit pas
# faire perdre la trace du fait qu'il a bien eu lieu. `MAX(JoueurLiquide.maj_le)`
# rendrait `None` dans ce cas précis, ce qui ferait passer une liste tout
# juste rafraîchie pour périmée.
_ID_META_UNIQUE = 1


class MetaListeLiquidite(Base):
    """Ligne unique : horodatage du dernier rafraîchissement complet."""

    __tablename__ = "meta_liste_liquidite"

    id: Mapped[int] = mapped_column(primary_key=True)
    derniere_reconstruction: Mapped[datetime] = mapped_column(nullable=False)


def remplacer_liste_liquidite(
    session: Session,
    entrees: list[dict],
    maintenant: datetime,
) -> int:
    """Remplace tout le contenu de la table par `entrees` — un rafraîchissement
    complet, pas une mise à jour incrémentale (voir docstring de la classe).

    Args:
        session: session SQLAlchemy (l'appelant commit)
        entrees: `[{"joueur_slug", "rarete", "season_eligibility", "n30",
            "n7", "semaines_actives"}, ...]` — un élément par couple retenu
        maintenant: horodatage du rafraîchissement (injectable, voir
            `core.horloge`)

    Returns:
        Le nombre de lignes écrites.
    """
    session.query(JoueurLiquide).delete()
    for entree in entrees:
        session.add(
            JoueurLiquide(
                joueur_slug=entree["joueur_slug"],
                rarete=entree["rarete"],
                season_eligibility=entree["season_eligibility"],
                n30=entree["n30"],
                n7=entree["n7"],
                semaines_actives=entree["semaines_actives"],
                maj_le=maintenant,
            )
        )

    meta = session.get(MetaListeLiquidite, _ID_META_UNIQUE)
    if meta is None:
        session.add(MetaListeLiquidite(id=_ID_META_UNIQUE, derniere_reconstruction=maintenant))
    else:
        meta.derniere_reconstruction = maintenant

    session.flush()
    return len(entrees)


def lire_liste_liquidite(session: Session) -> list[JoueurLiquide]:
    """Toute la liste courante, telle qu'écrite par le dernier rafraîchissement."""
    return list(session.scalars(select(JoueurLiquide)).all())


def derniere_maj(session: Session) -> datetime | None:
    """L'horodatage du dernier rafraîchissement complet, ou `None` si la
    liste n'a jamais été construite (même vide).

    ⚠️ SQLite ne conserve pas le fuseau horaire d'un `datetime` stocké : il
    est toujours relu naïf, même écrit avec un `Horloge` en UTC (toujours le
    cas dans ce projet). On lui rattache donc `UTC` explicitement au lieu de
    le rendre tel quel — comparer un datetime naïf à un autre aware
    (`liste_perimee`) lèverait sinon `TypeError` en toute discrétion, jamais
    en test avec des horloges figées incohérentes entre elles.
    """
    meta = session.get(MetaListeLiquidite, _ID_META_UNIQUE)
    if meta is None:
        return None
    valeur = meta.derniere_reconstruction
    return valeur if valeur.tzinfo is not None else valeur.replace(tzinfo=UTC)


def liste_perimee(session: Session, maintenant: datetime, delai_heures: int = DELAI_RAFRAICHISSEMENT_HEURES) -> bool:
    """Vrai si la liste n'a jamais été construite, ou si le dernier
    rafraîchissement date de plus de `delai_heures` — signal pour qu'un
    job rapide (futur L9) refuse de s'appuyer sur une liste trop vieille
    plutôt que de le faire silencieusement."""
    maj = derniere_maj(session)
    if maj is None:
        return True
    return maintenant - maj > timedelta(hours=delai_heures)
