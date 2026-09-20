"""Base SQLAlchemy et gestion de session.

SQLite, pas de serveur : le bot tourne en tâche planifiée sur un seul poste,
un seul écrivain à la fois. Le mode WAL est activé pour qu'une lecture (CLI
d'inspection) ne bloque pas un cycle en cours.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import cache

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from acheteur.core.config import get_settings


class Base(DeclarativeBase):
    pass


@cache
def _moteur_pour(url: str) -> Engine:
    est_sqlite = "sqlite" in url
    moteur = create_engine(url, connect_args={"check_same_thread": False} if est_sqlite else {})

    if est_sqlite:

        @event.listens_for(moteur, "connect")
        def _activer_wal(connexion_dbapi, _record) -> None:
            curseur = connexion_dbapi.cursor()
            curseur.execute("PRAGMA journal_mode=WAL")
            curseur.execute("PRAGMA foreign_keys=ON")
            curseur.close()

    return moteur


def obtenir_moteur() -> Engine:
    return _moteur_pour(get_settings().database_url)


def creer_tables() -> None:
    """Crée les tables manquantes. Idempotent — n'efface jamais rien.

    Importe les modules de modèles ici (pas en haut de fichier) : ils
    importent `Base` depuis ce module, un import en tête créerait un cycle.
    """
    from acheteur.negociation import journal  # noqa: F401

    Base.metadata.create_all(obtenir_moteur())


def obtenir_fabrique_session() -> sessionmaker[Session]:
    return sessionmaker(bind=obtenir_moteur(), autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    fabrique = obtenir_fabrique_session()
    session = fabrique()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
