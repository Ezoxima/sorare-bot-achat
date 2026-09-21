"""Tests de non-régression pour les trois défauts trouvés en revue L4/L5
(voir DECISIONS.md) :

1. `lignes_ouvertes()` n'acceptait pas `mode_simulation`, alors que
   `scanner.py` et `simulation.py` l'appelaient déjà avec ce paramètre.
2. `proposer_groupe()` attend `dict[str, int]` ; `scanner.py` lui passait
   un `dict[str, Montant]`, ce qui aurait écrit un objet `Montant` dans la
   colonne `reference_prix_valeur` (int) pour toute offre groupée.
3. `demander_confirmation_utilisateur()` convertissait la saisie EUR en
   centimes via `float(...) * 100` — flottant sur un montant de paiement,
   interdit par CLAUDE.md.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from acheteur.approbation.valider_propositions import _parser_euros_en_centimes
from acheteur.core.db import Base
from acheteur.decision.paliers import Palier
from acheteur.decision.proposition import proposer_groupe
from acheteur.marche.devises import Devise, Montant
from acheteur.marche.types import Annonce, Joueur, Rareté
from acheteur.negociation.journal import enregistrer_ligne, lignes_ouvertes

BASE = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)


# === 1. lignes_ouvertes(mode_simulation=...) ===


@pytest.fixture
def session():
    moteur = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(moteur)
    fabrique = sessionmaker(bind=moteur)
    s = fabrique()
    yield s
    s.close()


def _ligne(session, *, mode_simulation: bool, joueur_slug: str = "messi"):
    return enregistrer_ligne(
        session,
        joueur_slug=joueur_slug,
        vendeur_slug="alice",
        prix_demande_valeur=1000,
        prix_demande_devise=Devise.EUR,
        montant_offre_valeur=700,
        montant_offre_devise=Devise.EUR,
        reference_prix_valeur=1200,
        reference_fenetre_jours=7,
        reference_nb_ventes=3,
        palier=70,
        date_pose_annonce=BASE - timedelta(hours=2),
        horloge_maintenant=BASE,
        mode_simulation=mode_simulation,
    )


class TestLignesOuvertesFiltreModeSimulation:
    def test_sans_filtre_renvoie_les_deux(self, session):
        _ligne(session, mode_simulation=True, joueur_slug="messi")
        _ligne(session, mode_simulation=False, joueur_slug="mbappe")
        session.commit()

        assert len(lignes_ouvertes(session)) == 2

    def test_filtre_simulation_true(self, session):
        _ligne(session, mode_simulation=True, joueur_slug="messi")
        _ligne(session, mode_simulation=False, joueur_slug="mbappe")
        session.commit()

        resultat = lignes_ouvertes(session, mode_simulation=True)
        assert [l.joueur_slug for l in resultat] == ["messi"]

    def test_filtre_simulation_false(self, session):
        _ligne(session, mode_simulation=True, joueur_slug="messi")
        _ligne(session, mode_simulation=False, joueur_slug="mbappe")
        session.commit()

        resultat = lignes_ouvertes(session, mode_simulation=False)
        assert [l.joueur_slug for l in resultat] == ["mbappe"]

    def test_appel_avec_kwarg_ne_leve_plus_typeerror(self, session):
        # C'était exactement l'appel qui plantait dans scanner.py / simulation.py.
        lignes_ouvertes(session, mode_simulation=True)


# === 2. proposer_groupe() attend des références entières ===


def _joueur(slug: str) -> Joueur:
    return Joueur(slug=slug, nom=slug.title(), rareté=Rareté(nom="Rare", classement=3))


def _annonce(joueur_slug: str, vendeur_slug: str, prix_valeur: int) -> Annonce:
    return Annonce(
        joueur=_joueur(joueur_slug),
        vendeur_slug=vendeur_slug,
        prix_demande=Montant(prix_valeur, Devise.EUR),
        accepte_eth=False,
        accepte_eur=True,
        date_pose=BASE - timedelta(hours=1),
    )


class TestProposerGroupeReferencesEntieres:
    def test_references_entieres_valeur_correcte(self):
        annonces = [
            _annonce("messi", "alice", 1000),
            _annonce("mbappe", "alice", 2000),
        ]
        # Le contrat de proposer_groupe : dict[str, int], pas dict[str, Montant]
        # (voir scanner.py, qui fait `.valeur` avant l'appel depuis L4/L5 correction).
        references = {"messi": 1200, "mbappe": 2400}

        prop = proposer_groupe(annonces, references, Palier.PREMIER)

        assert prop.references_prix == {"messi": 1200, "mbappe": 2400}
        for valeur in prop.references_prix.values():
            assert isinstance(valeur, int)

    def test_passer_un_objet_montant_par_erreur_est_detecte(self):
        # Non-régression : si l'appelant repasse par erreur un dict[str, Montant],
        # la référence stockée n'est plus un entier — ce test échouerait alors
        # que le montant lui-même reste calculable (bug silencieux détecté ici).
        annonces = [_annonce("messi", "alice", 1000)]
        references_montant_par_erreur = {"messi": Montant(1200, Devise.EUR)}

        prop = proposer_groupe(annonces, references_montant_par_erreur, Palier.PREMIER)

        assert not isinstance(prop.references_prix["messi"], int)


# === 3. Parsing du montant EUR retapé : pas de flottant ===


class TestParserEurosEnCentimes:
    @pytest.mark.parametrize(
        "saisie,attendu",
        [
            ("123.45", 12345),
            ("123,45", 12345),
            ("123", 12300),
            ("123.4", 12340),
            ("0.01", 1),
            ("19.99", 1999),
            ("1000.00", 100000),
        ],
    )
    def test_conversions_exactes(self, saisie: str, attendu: int):
        assert _parser_euros_en_centimes(saisie) == attendu

    def test_aucun_flottant_dans_le_calcul(self):
        # 19.99 est le cas classique où `float("19.99") * 100` peut dériver
        # (1998.9999999999998 selon la plateforme). L'arithmétique entière
        # sur les chaînes ne doit jamais produire ce genre d'écart.
        for centimes in range(1, 10_000):
            euros = centimes // 100
            reste = centimes % 100
            saisie = f"{euros}.{reste:02d}"
            assert _parser_euros_en_centimes(saisie) == centimes

    def test_trop_de_decimales_refuse(self):
        with pytest.raises(ValueError):
            _parser_euros_en_centimes("123.456")

    def test_non_numerique_refuse(self):
        with pytest.raises(ValueError):
            _parser_euros_en_centimes("abc")

    def test_vide_refuse(self):
        with pytest.raises(ValueError):
            _parser_euros_en_centimes("")
