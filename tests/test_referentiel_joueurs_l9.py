"""Référentiel de joueurs (`marche/referentiel_joueurs.py`, persistance) et
`cli/maj_referentiel_joueurs.py` (fonctions pures : compétition domestique,
agrégation des joueurs par club) — voir TODO.md (2026-09-22)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from acheteur.cli.maj_referentiel_joueurs import (
    _competition_domestique,
    _joueurs_des_clubs,
    _tous_clubs,
)
from acheteur.core.db import Base
from acheteur.marche.referentiel_joueurs import (
    DELAI_RAFRAICHISSEMENT_HEURES,
    derniere_maj_referentiel,
    lire_referentiel_joueurs,
    referentiel_perime,
    remplacer_referentiel_joueurs,
)

BASE = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)


@pytest.fixture
def session():
    moteur = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(moteur)
    fabrique = sessionmaker(bind=moteur)
    s = fabrique()
    yield s
    s.close()


class TestCompetitionDomestique:
    def test_trouve_le_format_domestic_league(self):
        competitions = [
            {"slug": "champions-league", "format": "CONTINENTAL_CUP"},
            {"slug": "ligue-1", "format": "DOMESTIC_LEAGUE"},
        ]
        assert _competition_domestique(competitions) == "ligue-1"

    def test_vide_si_aucune_domestic_league(self):
        competitions = [{"slug": "champions-league", "format": "CONTINENTAL_CUP"}]
        assert _competition_domestique(competitions) == ""

    def test_vide_si_liste_vide_ou_none(self):
        assert _competition_domestique([]) == ""
        assert _competition_domestique(None) == ""


class TestRemplacerReferentielJoueurs:
    def test_ecrit_puis_relit(self, session):
        entrees = [
            {"slug": "messi", "nom": "Messi", "club_slug": "psg", "competition": "ligue-1"},
        ]
        nb = remplacer_referentiel_joueurs(session, entrees, BASE)
        session.commit()
        assert nb == 1
        lignes = lire_referentiel_joueurs(session)
        assert len(lignes) == 1
        assert lignes[0].joueur_slug == "messi"
        assert lignes[0].club_slug == "psg"
        assert lignes[0].competition == "ligue-1"

    def test_remplace_completement_l_ancien_referentiel(self, session):
        remplacer_referentiel_joueurs(
            session, [{"slug": "ancien", "nom": "", "club_slug": "psg", "competition": ""}], BASE
        )
        session.commit()

        remplacer_referentiel_joueurs(
            session,
            [{"slug": "nouveau", "nom": "", "club_slug": "psg", "competition": ""}],
            BASE + timedelta(hours=24),
        )
        session.commit()

        lignes = lire_referentiel_joueurs(session)
        assert [ligne.joueur_slug for ligne in lignes] == ["nouveau"]


class TestDerniereMajEtPeremption:
    def test_derniere_maj_none_si_jamais_construit(self, session):
        assert derniere_maj_referentiel(session) is None

    def test_derniere_maj_rend_l_horodatage_ecrit(self, session):
        remplacer_referentiel_joueurs(
            session, [{"slug": "messi", "nom": "", "club_slug": "psg", "competition": ""}], BASE
        )
        session.commit()
        assert derniere_maj_referentiel(session) == BASE

    def test_perime_si_jamais_construit(self, session):
        assert referentiel_perime(session, BASE)

    def test_perime_au_dela_du_delai(self, session):
        remplacer_referentiel_joueurs(session, [], BASE)
        session.commit()
        maintenant = BASE + timedelta(hours=DELAI_RAFRAICHISSEMENT_HEURES + 1)
        assert referentiel_perime(session, maintenant)

    def test_pas_perime_dans_le_delai(self, session):
        remplacer_referentiel_joueurs(session, [], BASE)
        session.commit()
        maintenant = BASE + timedelta(hours=DELAI_RAFRAICHISSEMENT_HEURES - 1)
        assert not referentiel_perime(session, maintenant)


class _ClientFactice:
    """Dispatch par sous-chaîne du nom d'opération GraphQL — suffisant pour
    tester la logique d'agrégation/pagination sans dépendre du texte exact
    des requêtes (voir `sorare/requetes.py`)."""

    def __init__(self, reponses: dict[str, object]):
        self._reponses = reponses

    def execute(self, query: str, variables: dict | None = None):
        for motif, reponse in self._reponses.items():
            if motif in query:
                if callable(reponse):
                    return reponse(variables or {})
                return reponse
        raise AssertionError(f"Aucune reponse factice pour la requete : {query[:60]}")


class TestTousClubs:
    def test_agrege_enumerables_et_pagine_les_grosses_competitions(self):
        client = _ClientFactice({
            "CompetitionsClubsEnumerables": {
                "football": {
                    "leaguesOpenForGameStats": [{"slug": "ligue-1"}],
                    "clubsReady": [{"slug": "club-hors-competition"}],
                }
            },
            "CardShardsPoolCompetitions": {"cardShardsPoolCompetitions": [{"slug": "ligue-1"}]},
            "ClubsDesCompetitions": {
                "football": {
                    "competitions": [
                        {
                            "slug": "ligue-1",
                            "clubs": {
                                "nodes": [{"slug": "psg"}],
                                "pageInfo": {"hasNextPage": True, "endCursor": "curseur1"},
                            },
                        }
                    ]
                }
            },
            "ClubsDuneCompetitionPage": {
                "football": {
                    "competitions": [
                        {
                            "clubs": {
                                "nodes": [{"slug": "om"}],
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                            }
                        }
                    ]
                }
            },
        })
        clubs = _tous_clubs(client)
        assert clubs == ["club-hors-competition", "om", "psg"]


class TestJoueursDesClubs:
    def test_agrege_et_pagine_les_gros_clubs(self):
        client = _ClientFactice({
            "PoolJoueursLot": {
                "football": {
                    "a0": {
                        "slug": "psg",
                        "activeCompetitions": [{"slug": "ligue-1", "format": "DOMESTIC_LEAGUE"}],
                        "anyActivePlayers": {
                            "pageInfo": {"hasNextPage": True, "endCursor": "curseur1"},
                            "nodes": [{"slug": "messi", "displayName": "Messi"}],
                        },
                    }
                }
            },
            "JoueursActifsClubPage": {
                "football": {
                    "club": {
                        "anyActivePlayers": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [{"slug": "mbappe", "displayName": "Mbappe"}],
                        }
                    }
                }
            },
        })
        joueurs = _joueurs_des_clubs(client, ["psg"])
        assert set(joueurs.keys()) == {"messi", "mbappe"}
        assert joueurs["messi"]["club_slug"] == "psg"
        assert joueurs["messi"]["competition"] == "ligue-1"
        assert joueurs["mbappe"]["club_slug"] == "psg"

    def test_ignore_les_noeuds_absents(self):
        client = _ClientFactice({"PoolJoueursLot": {"football": {}}})
        joueurs = _joueurs_des_clubs(client, ["club-inconnu"])
        assert joueurs == {}
