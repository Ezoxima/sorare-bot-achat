"""Persistance de la liste des couples liquides (`marche/liste_liquidite.py`)
et construction des couples à mesurer depuis le référentiel de joueurs
(`cli/maj_liste_liquidite.py`) — voir DECISIONS.md (2026-09-22, câblage sur
le référentiel plutôt que sur un échantillon du marché)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from acheteur.cli.maj_liste_liquidite import _couples_du_referentiel
from acheteur.core.db import Base
from acheteur.marche.liste_liquidite import (
    DELAI_RAFRAICHISSEMENT_HEURES,
    derniere_maj,
    lire_liste_liquidite,
    liste_perimee,
    remplacer_liste_liquidite,
)
from acheteur.marche.referentiel_joueurs import JoueurReferentiel

BASE = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)


@pytest.fixture
def session():
    moteur = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(moteur)
    fabrique = sessionmaker(bind=moteur)
    s = fabrique()
    yield s
    s.close()


def _joueur_referentiel(slug: str) -> JoueurReferentiel:
    return JoueurReferentiel(
        joueur_slug=slug, nom=slug, club_slug="club1", competition="ligue-1", maj_le=BASE
    )


class TestCouplesDuReferentiel:
    def test_produit_cartesien_rarete_x_saison(self):
        couples = _couples_du_referentiel([_joueur_referentiel("messi")])
        assert len(couples) == 4  # 2 raretés x 2 saisons
        assert {(c["rarete"], c["season_eligibility"]) for c in couples} == {
            ("limited", "CLASSIC"), ("limited", "IN_SEASON"),
            ("rare", "CLASSIC"), ("rare", "IN_SEASON"),
        }

    def test_un_couple_par_joueur_et_par_combinaison(self):
        couples = _couples_du_referentiel(
            [_joueur_referentiel("messi"), _joueur_referentiel("mbappe")]
        )
        assert len(couples) == 8
        assert {c["joueur_slug"] for c in couples} == {"messi", "mbappe"}

    def test_liste_vide_si_aucun_joueur(self):
        assert _couples_du_referentiel([]) == []

    def test_raretes_et_saisons_personnalisables(self):
        couples = _couples_du_referentiel(
            [_joueur_referentiel("messi")], raretes=["limited"], saisons=["CLASSIC"]
        )
        assert couples == [
            {"joueur_slug": "messi", "rarete": "limited", "season_eligibility": "CLASSIC"}
        ]


class TestRemplacerListeLiquidite:
    def test_ecrit_puis_relit(self, session):
        entrees = [
            {"joueur_slug": "messi", "rarete": "limited", "season_eligibility": "IN_SEASON",
             "n30": 15, "n7": 3, "semaines_actives": 4},
        ]
        nb = remplacer_liste_liquidite(session, entrees, BASE)
        session.commit()
        assert nb == 1
        lignes = lire_liste_liquidite(session)
        assert len(lignes) == 1
        assert lignes[0].joueur_slug == "messi"
        # SQLite relit un datetime naïf (voir liste_liquidite.derniere_maj) —
        # seul `derniere_maj` rattache UTC explicitement, pas cette colonne
        # (jamais comparée pour elle-même, seulement affichée en diagnostic).
        assert lignes[0].maj_le.replace(tzinfo=UTC) == BASE

    def test_remplace_completement_l_ancienne_liste(self, session):
        remplacer_liste_liquidite(
            session,
            [{"joueur_slug": "ancien", "rarete": "limited", "season_eligibility": "IN_SEASON",
              "n30": 15, "n7": 3, "semaines_actives": 4}],
            BASE,
        )
        session.commit()

        remplacer_liste_liquidite(
            session,
            [{"joueur_slug": "nouveau", "rarete": "limited", "season_eligibility": "IN_SEASON",
              "n30": 20, "n7": 5, "semaines_actives": 4}],
            BASE + timedelta(hours=24),
        )
        session.commit()

        lignes = lire_liste_liquidite(session)
        assert [ligne.joueur_slug for ligne in lignes] == ["nouveau"]


class TestDerniereMajEtPeremption:
    def test_derniere_maj_none_si_jamais_construite(self, session):
        assert derniere_maj(session) is None

    def test_derniere_maj_rend_l_horodatage_ecrit(self, session):
        remplacer_liste_liquidite(
            session,
            [{"joueur_slug": "messi", "rarete": "limited", "season_eligibility": "IN_SEASON",
              "n30": 15, "n7": 3, "semaines_actives": 4}],
            BASE,
        )
        session.commit()
        assert derniere_maj(session) == BASE

    def test_liste_perimee_si_jamais_construite(self, session):
        assert liste_perimee(session, BASE)

    def test_liste_perimee_au_dela_du_delai(self, session):
        remplacer_liste_liquidite(session, [], BASE)
        session.commit()
        maintenant = BASE + timedelta(hours=DELAI_RAFRAICHISSEMENT_HEURES + 1)
        assert liste_perimee(session, maintenant)

    def test_liste_pas_perimee_dans_le_delai(self, session):
        remplacer_liste_liquidite(session, [], BASE)
        session.commit()
        maintenant = BASE + timedelta(hours=DELAI_RAFRAICHISSEMENT_HEURES - 1)
        assert not liste_perimee(session, maintenant)
