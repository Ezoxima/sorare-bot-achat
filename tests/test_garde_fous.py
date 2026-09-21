"""Tests du lot L4 : les 9 garde-fous (regles.py) et la barrière (barriere.py).

Fonctions pures (regles.py) et base SQLite en mémoire (barriere.py) — aucun
réseau, conforme à la revue « bancaire » demandée par CLAUDE.md.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from acheteur.core.db import Base
from acheteur.core.horloge import HorlogeFigee
from acheteur.decision.paliers import Palier
from acheteur.decision.proposition import PropositionGroupe, PropositionSimple
from acheteur.garde_fous.barriere import ContexteBarriere, envoyer_offre_proposal
from acheteur.garde_fous.regles import (
    GuardrailViolation,
    verifier_arrêt_d_urgence,
    verifier_coherence_unites,
    verifier_mode_reel_verrous,
    verifier_offre_ne_depasse_pas_prix_demande,
    verifier_offres_par_vendeur_limitees,
    verifier_palier_valide,
    verifier_solde_relu_juste_avant,
    verifier_solde_suffisant,
    verifier_taux_change_frais,
)
from acheteur.marche.devises import Devise, Montant
from acheteur.marche.types import Annonce, Joueur, Rareté
from acheteur.negociation.journal import EtatOffre, OffreJournal

BASE = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)


# === Règles unitaires (fonctions pures) ===


class TestRegleSolde:
    def test_solde_suffisant_passe(self):
        verifier_solde_suffisant(
            montant_total_propose=500, soldes_ouverts=200, solde_disponible=1000
        )

    def test_solde_insuffisant_leve(self):
        with pytest.raises(GuardrailViolation, match="Solde insuffisant"):
            verifier_solde_suffisant(
                montant_total_propose=500, soldes_ouverts=600, solde_disponible=1000
            )

    def test_pile_au_plafond_passe(self):
        verifier_solde_suffisant(
            montant_total_propose=500, soldes_ouverts=500, solde_disponible=1000
        )


class TestRegleSoldeFrais:
    def test_solde_frais_passe(self):
        verifier_solde_relu_juste_avant(
            solde_timestamp=BASE, horloge=HorlogeFigee(BASE + timedelta(seconds=10))
        )

    def test_solde_obsolete_leve(self):
        with pytest.raises(GuardrailViolation, match="obsolète"):
            verifier_solde_relu_juste_avant(
                solde_timestamp=BASE, horloge=HorlogeFigee(BASE + timedelta(seconds=31))
            )

    def test_tolerance_personnalisee(self):
        with pytest.raises(GuardrailViolation):
            verifier_solde_relu_juste_avant(
                solde_timestamp=BASE,
                horloge=HorlogeFigee(BASE + timedelta(seconds=5)),
                tolerance_sec=2,
            )


class TestRegleOffreNeDepassePasPrix:
    def test_offre_inferieure_passe(self):
        verifier_offre_ne_depasse_pas_prix_demande(montant_offre=700, prix_demande=1000)

    def test_offre_egale_passe(self):
        verifier_offre_ne_depasse_pas_prix_demande(montant_offre=1000, prix_demande=1000)

    def test_offre_superieure_leve(self):
        with pytest.raises(GuardrailViolation, match="dépasse le prix demandé"):
            verifier_offre_ne_depasse_pas_prix_demande(montant_offre=1001, prix_demande=1000)


class TestRegleCoherenceUnites:
    def test_eur_positif_passe(self):
        verifier_coherence_unites(1000, Devise.EUR)

    def test_montant_nul_leve(self):
        with pytest.raises(GuardrailViolation, match="nul ou négatif"):
            verifier_coherence_unites(0, Devise.EUR)

    def test_montant_negatif_leve(self):
        with pytest.raises(GuardrailViolation, match="nul ou négatif"):
            verifier_coherence_unites(-100, Devise.EUR)

    def test_eth_en_wei_plausible_passe(self):
        # 0.05 ETH en wei
        verifier_coherence_unites(5 * 10**16, Devise.ETH)

    def test_eth_hors_maille_leve(self):
        # Ressemble à des centimes non convertis en wei — et de toute façon
        # pas un multiple de la maille (0.0001 ETH = 10**14 wei).
        with pytest.raises(GuardrailViolation, match="hors maille"):
            verifier_coherence_unites(700, Devise.ETH)

    def test_eth_petit_mais_sur_la_maille_passe(self):
        """Régression (signalé par l'utilisateur, 2026-09-21) : l'ancien
        seuil (`< 10**15`) rejetait à tort un montant ETH légitimement petit
        (0.0001 ETH ≈ 20-25 centimes est un prix réel sur ce marché)."""
        verifier_coherence_unites(10**14, Devise.ETH)  # 0.0001 ETH, une maille

    def test_eth_hors_maille_meme_au_dessus_de_l_ancien_seuil_leve(self):
        """Pas un multiple de la maille, même si > 10**15 (ancien seuil) —
        preuve que la nouvelle règle porte sur la granularité, pas la taille."""
        with pytest.raises(GuardrailViolation, match="hors maille"):
            verifier_coherence_unites(10**16 + 1, Devise.ETH)


class TestRegleTauxChange:
    def test_pas_de_conversion_passe(self):
        verifier_taux_change_frais(taux_timestamp=None, horloge=HorlogeFigee(BASE))

    def test_taux_frais_passe(self):
        verifier_taux_change_frais(
            taux_timestamp=BASE, horloge=HorlogeFigee(BASE + timedelta(minutes=10))
        )

    def test_taux_obsolete_leve(self):
        with pytest.raises(GuardrailViolation, match="Taux de change obsolète"):
            verifier_taux_change_frais(
                taux_timestamp=BASE, horloge=HorlogeFigee(BASE + timedelta(minutes=16))
            )


class TestReglePalier:
    def test_palier_80_passe(self):
        verifier_palier_valide(80)

    def test_palier_81_leve(self):
        with pytest.raises(GuardrailViolation, match="dépasse 80%"):
            verifier_palier_valide(81)


class TestRegleOffresParVendeur:
    def test_sous_plafond_passe(self):
        verifier_offres_par_vendeur_limitees("alice", {"alice": 4}, plafond_par_vendeur=5)

    def test_au_plafond_leve(self):
        with pytest.raises(GuardrailViolation, match="Plafond d'offres atteint"):
            verifier_offres_par_vendeur_limitees("alice", {"alice": 5}, plafond_par_vendeur=5)

    def test_vendeur_absent_du_dict_passe(self):
        verifier_offres_par_vendeur_limitees("bob", {}, plafond_par_vendeur=5)


class TestRegleArretUrgence:
    def test_sans_fichier_passe(self, tmp_path: Path):
        verifier_arrêt_d_urgence(tmp_path)

    def test_avec_fichier_leve(self, tmp_path: Path):
        (tmp_path / ".arret-urgence").write_text("stop")
        with pytest.raises(GuardrailViolation, match="Arrêt d'urgence"):
            verifier_arrêt_d_urgence(tmp_path)


class TestRegleModeReelVerrous:
    def test_trois_verrous_ok_passe(self):
        verifier_mode_reel_verrous(
            env_var_mode_reel=True,
            cli_arg_mode_reel=True,
            montant_retape=1000,
            montant_decide=1000,
        )

    def test_env_var_absente_leve(self):
        with pytest.raises(GuardrailViolation, match="env var"):
            verifier_mode_reel_verrous(
                env_var_mode_reel=False,
                cli_arg_mode_reel=True,
                montant_retape=1000,
                montant_decide=1000,
            )

    def test_flag_cli_absent_leve(self):
        with pytest.raises(GuardrailViolation, match="flag --mode-reel"):
            verifier_mode_reel_verrous(
                env_var_mode_reel=True,
                cli_arg_mode_reel=False,
                montant_retape=1000,
                montant_decide=1000,
            )

    def test_montant_retape_different_leve(self):
        with pytest.raises(GuardrailViolation, match="montant retapé"):
            verifier_mode_reel_verrous(
                env_var_mode_reel=True,
                cli_arg_mode_reel=True,
                montant_retape=999,
                montant_decide=1000,
            )


# === Barrière : intégration avec une base en mémoire ===


@pytest.fixture
def session():
    moteur = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(moteur)
    fabrique = sessionmaker(bind=moteur)
    s = fabrique()
    yield s
    s.close()


def _joueur(slug: str = "messi") -> Joueur:
    return Joueur(slug=slug, nom=slug.title(), rareté=Rareté(nom="Rare", classement=3))


def _annonce(
    joueur_slug: str = "messi",
    vendeur_slug: str = "alice",
    prix_valeur: int = 1000,
    devise: Devise = Devise.EUR,
) -> Annonce:
    return Annonce(
        joueur=_joueur(joueur_slug),
        vendeur_slug=vendeur_slug,
        prix_demande=Montant(prix_valeur, devise),
        accepte_eth=(devise == Devise.ETH),
        accepte_eur=(devise == Devise.EUR),
        date_pose=BASE - timedelta(hours=1),
    )


def _proposition_simple(
    prix_valeur: int = 1000, montant_offre: int = 700, devise: Devise = Devise.EUR
) -> PropositionSimple:
    return PropositionSimple(
        annonce=_annonce(prix_valeur=prix_valeur, devise=devise),
        reference_prix_valeur=1200,
        montant_offre=montant_offre,
        palier=Palier.PREMIER,
    )


def _contexte(
    solde_eur: int = 100_000,
    offres_ouvertes_eur: int = 0,
    offres_par_vendeur: dict | None = None,
    solde_timestamp: datetime = BASE,
    taux_change_timestamp: datetime | None = None,
) -> ContexteBarriere:
    return ContexteBarriere(
        soldes_par_devise={
            Devise.EUR: Montant(solde_eur, Devise.EUR),
            Devise.ETH: Montant(10**18, Devise.ETH),
        },
        offres_ouvertes_par_devise={Devise.EUR: offres_ouvertes_eur},
        offres_ouvertes_par_vendeur=offres_par_vendeur or {},
        solde_timestamp=solde_timestamp,
        taux_change_timestamp=taux_change_timestamp,
    )


class TestBarriereSimulation:
    def test_proposition_valide_ecrit_une_ligne_simulee(self, session, tmp_path):
        envoyer_offre_proposal(
            _proposition_simple(),
            _contexte(),
            session,
            HorlogeFigee(BASE),
            mode_simulation=True,
            chemin_racine=tmp_path,
        )
        session.commit()

        lignes = session.query(OffreJournal).all()
        assert len(lignes) == 1
        assert lignes[0].etat == EtatOffre.SIMULEE
        assert lignes[0].mode_simulation is True
        assert lignes[0].sorare_id is None
        # Référence figée telle que fournie par la proposition, jamais recalculée.
        assert lignes[0].reference_prix_valeur == 1200

    def test_solde_insuffisant_ne_lit_aucune_ligne(self, session, tmp_path):
        with pytest.raises(GuardrailViolation):
            envoyer_offre_proposal(
                _proposition_simple(montant_offre=700),
                _contexte(solde_eur=500),
                session,
                HorlogeFigee(BASE),
                mode_simulation=True,
                chemin_racine=tmp_path,
            )
        assert session.query(OffreJournal).count() == 0

    def test_offre_superieure_au_prix_demande_refusee(self, session, tmp_path):
        with pytest.raises(GuardrailViolation, match="dépasse le prix demandé"):
            envoyer_offre_proposal(
                _proposition_simple(prix_valeur=1000, montant_offre=1001),
                _contexte(),
                session,
                HorlogeFigee(BASE),
                mode_simulation=True,
                chemin_racine=tmp_path,
            )
        assert session.query(OffreJournal).count() == 0

    def test_arret_urgence_bloque_meme_en_simulation(self, session, tmp_path):
        (tmp_path / ".arret-urgence").write_text("stop")
        with pytest.raises(GuardrailViolation, match="Arrêt d'urgence"):
            envoyer_offre_proposal(
                _proposition_simple(),
                _contexte(),
                session,
                HorlogeFigee(BASE),
                mode_simulation=True,
                chemin_racine=tmp_path,
            )
        assert session.query(OffreJournal).count() == 0

    def test_plafond_par_vendeur_refuse(self, session, tmp_path):
        with pytest.raises(GuardrailViolation, match="Plafond d'offres atteint"):
            envoyer_offre_proposal(
                _proposition_simple(),
                _contexte(offres_par_vendeur={"alice": 5}),
                session,
                HorlogeFigee(BASE),
                mode_simulation=True,
                chemin_racine=tmp_path,
            )
        assert session.query(OffreJournal).count() == 0

    def test_mode_reel_sans_verrous_refuse_meme_avec_client_absent(self, session, tmp_path):
        # Règle 9 doit lever avant même d'exiger un client Sorare.
        with pytest.raises(GuardrailViolation, match="Mode réel"):
            envoyer_offre_proposal(
                _proposition_simple(),
                _contexte(),
                session,
                HorlogeFigee(BASE),
                mode_simulation=False,
                env_var_mode_reel=False,
                cli_arg_mode_reel=False,
                chemin_racine=tmp_path,
            )
        assert session.query(OffreJournal).count() == 0

    def test_mode_reel_createdirectoffer_avec_erreurs_ne_plante_pas(self, session, tmp_path):
        """Régression réelle (lot L7, premier envoi réel de l'utilisateur,
        2026-09-21, voir MESURES.md) : quand `createDirectOffer` renvoie des
        erreurs, `tokenOffer` vaut `None` (présent mais nul) — un `.get()`
        direct dessus plantait avec `'NoneType' object has no attribute
        'get'`, masquant le vrai message d'erreur derrière une exception
        générique. La ligne doit rester ENVOYEE sans sorare_id, sans lever."""

        class _ClientEchecCreateDirectOffer:
            def execute(self, query, variables=None):
                if "prepareOffer" in query:
                    return {"prepareOffer": {"authorizations": [], "errors": []}}
                if "createDirectOffer" in query:
                    return {
                        "createDirectOffer": {
                            "tokenOffer": None,
                            "errors": [{"code": "INVALID", "message": "dealId invalide"}],
                        }
                    }
                raise AssertionError(f"Requête inattendue : {query[:50]}")

        proposition = _proposition_simple()
        proposition = replace(proposition, annonce=replace(proposition.annonce, asset_id="asset-1"))

        # Ne doit lever aucune exception (ni le crash régressé, ni GuardrailViolation).
        envoyer_offre_proposal(
            proposition,
            _contexte(),
            session,
            HorlogeFigee(BASE),
            mode_simulation=False,
            env_var_mode_reel=True,
            cli_arg_mode_reel=True,
            montant_retape=700,
            chemin_racine=tmp_path,
            client=_ClientEchecCreateDirectOffer(),
        )

        lignes = session.query(OffreJournal).all()
        assert len(lignes) == 1
        assert lignes[0].etat == EtatOffre.ENVOYEE
        assert lignes[0].sorare_id is None

    def test_mode_reel_sans_client_leve_value_error(self, session, tmp_path):
        with pytest.raises(ValueError, match="client Sorare"):
            envoyer_offre_proposal(
                _proposition_simple(),
                _contexte(),
                session,
                HorlogeFigee(BASE),
                mode_simulation=False,
                env_var_mode_reel=True,
                cli_arg_mode_reel=True,
                montant_retape=700,
                chemin_racine=tmp_path,
                client=None,
            )
        # La ligne a bien été écrite (état ENVOYEE) avant l'appel réseau —
        # c'est la couche 1 d'idempotence documentée dans barriere.py.
        lignes = session.query(OffreJournal).all()
        assert len(lignes) == 1
        assert lignes[0].etat == EtatOffre.ENVOYEE
        assert lignes[0].sorare_id is None


class TestBarriereGroupee:
    def _proposition_groupe(self) -> PropositionGroupe:
        annonces = (
            _annonce(joueur_slug="messi", vendeur_slug="alice", prix_valeur=1000),
            _annonce(joueur_slug="mbappe", vendeur_slug="alice", prix_valeur=2000),
        )
        montants = {"messi": 650, "mbappe": 1300}  # 65% (décote groupe au 1er palier)
        return PropositionGroupe(
            annonces=annonces,
            references_prix={"messi": 1200, "mbappe": 2400},
            montants_offre=montants,
            palier=Palier.PREMIER,
            decote_appliquee=True,
        )

    def test_proposition_groupe_ecrit_une_ligne_par_annonce(self, session, tmp_path):
        envoyer_offre_proposal(
            self._proposition_groupe(),
            _contexte(),
            session,
            HorlogeFigee(BASE),
            mode_simulation=True,
            chemin_racine=tmp_path,
        )
        session.commit()

        lignes = session.query(OffreJournal).order_by(OffreJournal.joueur_slug).all()
        assert len(lignes) == 2
        assert {l.joueur_slug for l in lignes} == {"messi", "mbappe"}
        assert all(l.decote_groupe for l in lignes)
