"""Tests du lot L2 : journal des offres + réconciliation en lecture seule."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from acheteur.core.db import Base
from acheteur.marche.devises import Devise
from acheteur.negociation.journal import (
    EtatOffre,
    MotifRefus,
    OffreJournal,
    enregistrer_ligne,
    importer_ligne_manuelle,
    lignes_ouvertes,
)
from acheteur.negociation.reconciliation import (
    CRENEAU_SIGNATURE,
    OffreSorareObservee,
    apparier,
    depuis_reponse_sorare,
    etat_depuis_sorare,
    motif_refus_depuis_sorare,
    reconcilier,
)
from acheteur.core.horloge import HorlogeFigee

BASE = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


@pytest.fixture
def session():
    moteur = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(moteur)
    fabrique = sessionmaker(bind=moteur)
    s = fabrique()
    yield s
    s.close()


def _ligne_decidee(session: Session, **kwargs) -> OffreJournal:
    defauts = dict(
        joueur_slug="messi",
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
        mode_simulation=True,
    )
    defauts.update(kwargs)
    return enregistrer_ligne(session, **defauts)


class TestContraintesBase:
    """PLAN.md § L3 et § Garde-fous : contraintes en base, pas seulement dans le code."""

    def test_palier_superieur_a_80_refuse(self, session: Session):
        with pytest.raises(IntegrityError):
            _ligne_decidee(session, palier=90)
        session.rollback()

    def test_reference_moins_de_3_ventes_refusee(self, session: Session):
        with pytest.raises(IntegrityError):
            _ligne_decidee(session, reference_nb_ventes=2)
        session.rollback()

    def test_ligne_simulee_avec_identifiant_sorare_refusee(self, session: Session):
        with pytest.raises(IntegrityError):
            _ligne_decidee(session, mode_simulation=True, sorare_id="abc123")
        session.rollback()

    def test_ligne_envoyee_avec_identifiant_sorare_acceptee(self, session: Session):
        ligne = _ligne_decidee(session, mode_simulation=False, sorare_id="abc123")
        assert ligne.sorare_id == "abc123"

    def test_import_automatique_echappe_aux_contraintes_de_decision(self, session: Session):
        """Une ligne importée n'a pas de palier ni de référence : ce n'est pas une
        décision du bot, lui imposer ces contraintes ferait mentir la base."""
        ligne = importer_ligne_manuelle(
            session,
            sorare_id="import-1",
            joueur_slug="mbappe",
            vendeur_slug="bob",
            montant_offre_valeur=500,
            montant_offre_devise=Devise.EUR,
            etat=EtatOffre.ENVOYEE,
            motif_refus=None,
            reponse_brute=None,
            creee_le=BASE,
            horloge_maintenant=BASE,
        )
        assert ligne.palier is None
        assert ligne.reference_nb_ventes is None
        assert ligne.import_automatique is True

    def test_deux_offres_ouvertes_sur_meme_joueur_vendeur_refusees(self, session: Session):
        """L'unicité qui empêche physiquement un double envoi sur le même lot."""
        _ligne_decidee(session, mode_simulation=True)
        with pytest.raises(IntegrityError):
            _ligne_decidee(session, mode_simulation=True)
        session.rollback()

    def test_deux_offres_sur_meme_joueur_vendeur_ok_si_la_premiere_est_close(
        self, session: Session
    ):
        premiere = _ligne_decidee(session, mode_simulation=True)
        premiere.etat = EtatOffre.EXPIREE
        session.flush()
        # Le couple (joueur, vendeur) est de nouveau libre.
        seconde = _ligne_decidee(session, mode_simulation=True)
        assert seconde.id != premiere.id

    def test_deux_offres_ouvertes_sur_vendeurs_differents_ok(self, session: Session):
        _ligne_decidee(session, vendeur_slug="alice", mode_simulation=True)
        _ligne_decidee(session, vendeur_slug="bob", mode_simulation=True)
        assert len(lignes_ouvertes(session)) == 2


class TestApparierParIdentifiant:
    def test_ligne_avec_sorare_id_connu_est_appariee(self, session: Session):
        ligne = _ligne_decidee(session, mode_simulation=False, sorare_id="off-1")
        offre = OffreSorareObservee(
            sorare_id="off-1",
            vendeur_slug="quelquun_dautre",  # signature différente : l'ID prime.
            joueurs_slugs=("autre_joueur",),
            montant_valeur=999,
            montant_devise="EUR",
            creee_le=BASE + timedelta(days=10),
            etat_brut="OPENED",
            motif_refus_brut=None,
            reponse_brute={},
        )
        rapport = apparier([ligne], [offre])
        assert rapport.appariees == [(ligne, offre)]
        assert not rapport.a_importer
        assert not rapport.ambigues


class TestApparierParSignature:
    def _offre(self, **kwargs) -> OffreSorareObservee:
        defauts = dict(
            sorare_id="off-1",
            vendeur_slug="alice",
            joueurs_slugs=("messi",),
            montant_valeur=700,
            montant_devise="EUR",
            creee_le=BASE,
            etat_brut="OPENED",
            motif_refus_brut=None,
            reponse_brute={},
        )
        defauts.update(kwargs)
        return OffreSorareObservee(**defauts)

    def test_signature_identique_dans_le_creneau_est_appariee(self, session: Session):
        ligne = _ligne_decidee(session, mode_simulation=True)  # sorare_id=None
        offre = self._offre(creee_le=ligne.cree_le + timedelta(minutes=5))
        rapport = apparier([ligne], [offre])
        assert rapport.appariees == [(ligne, offre)]

    def test_hors_creneau_horaire_non_appariee_et_devient_a_importer(self, session: Session):
        ligne = _ligne_decidee(session, mode_simulation=True)
        offre = self._offre(creee_le=ligne.cree_le + CRENEAU_SIGNATURE + timedelta(minutes=1))
        rapport = apparier([ligne], [offre])
        assert not rapport.appariees
        assert ligne in rapport.sans_contrepartie
        assert offre in rapport.a_importer

    def test_montant_different_non_apparie(self, session: Session):
        ligne = _ligne_decidee(session, mode_simulation=True, montant_offre_valeur=700)
        offre = self._offre(montant_valeur=750, creee_le=ligne.cree_le)
        rapport = apparier([ligne], [offre])
        assert not rapport.appariees
        assert offre in rapport.a_importer

    def test_deux_candidates_pour_une_ligne_sont_ambigues_pas_devinees(self, session: Session):
        ligne = _ligne_decidee(session, mode_simulation=True)
        offre_a = self._offre(sorare_id="off-a", creee_le=ligne.cree_le)
        offre_b = self._offre(sorare_id="off-b", creee_le=ligne.cree_le + timedelta(minutes=1))
        rapport = apparier([ligne], [offre_a, offre_b])
        assert not rapport.appariees
        assert not rapport.a_importer
        assert len(rapport.ambigues) == 1
        ligne_ambigue, candidates = rapport.ambigues[0]
        assert ligne_ambigue is ligne
        assert {c.sorare_id for c in candidates} == {"off-a", "off-b"}
        assert rapport.cycle_suspendu


class TestImportOffreManuelle:
    def test_offre_sorare_sans_ligne_journal_est_a_importer(self):
        offre = OffreSorareObservee(
            sorare_id="manuelle-1",
            vendeur_slug="carol",
            joueurs_slugs=("haaland",),
            montant_valeur=800,
            montant_devise="EUR",
            creee_le=BASE,
            etat_brut="OPENED",
            motif_refus_brut=None,
            reponse_brute={},
        )
        rapport = apparier([], [offre])
        assert rapport.a_importer == [offre]
        assert rapport.cycle_suspendu

    def test_journal_vide_et_sorare_vide_ne_suspend_rien(self):
        rapport = apparier([], [])
        assert not rapport.cycle_suspendu


class TestTraductionMotifsEtEtats:
    @pytest.mark.parametrize(
        "brut,attendu",
        [
            ("OFFER_TOO_LOW", MotifRefus.OFFRE_TROP_BASSE),
            ("NOT_SELLING", MotifRefus.NE_VEND_PAS),
            ("CARD_NOT_WANTED", MotifRefus.CARTE_NON_DESIREE),
            ("ONLY_CASH", MotifRefus.UNIQUEMENT_CASH),
            ("ADD_CASH", MotifRefus.AJOUTE_CASH),
            ("IN_A_LINEUP", MotifRefus.DANS_COMPOSITION),
        ],
    )
    def test_motifs_connus(self, brut, attendu):
        assert motif_refus_depuis_sorare(brut) == attendu

    def test_motif_absent_devient_sans_motif_pas_une_supposition_silencieuse(self):
        assert motif_refus_depuis_sorare(None) == MotifRefus.SANS_MOTIF

    def test_motif_inconnu_leve_une_erreur_plutot_que_de_deviner(self):
        with pytest.raises(ValueError):
            motif_refus_depuis_sorare("UN_MOTIF_QUI_N_EXISTE_PAS")

    def test_etats_connus(self):
        assert etat_depuis_sorare("ACCEPTED") == EtatOffre.ACCEPTEE
        assert etat_depuis_sorare("REJECTED") == EtatOffre.REFUSEE
        assert etat_depuis_sorare("CANCELLED") == EtatOffre.ANNULEE
        assert etat_depuis_sorare("OPENED") == EtatOffre.ENVOYEE

    def test_etats_en_minuscules_comme_renvoyes_par_l_api_reelle(self):
        """`TokenOffer.status` est un `String!`, pas un enum GraphQL : le
        premier run réel (lot L6, MESURES.md 2026-09-21) a montré qu'il
        renvoie des valeurs en minuscules. Une comparaison sensible à la
        casse faisait tomber une offre réellement rejetée dans le défaut
        ENVOYEE — donc « toujours ouverte » aux yeux du journal."""
        assert etat_depuis_sorare("accepted") == EtatOffre.ACCEPTEE
        assert etat_depuis_sorare("rejected") == EtatOffre.REFUSEE
        assert etat_depuis_sorare("cancelled") == EtatOffre.ANNULEE


class TestDepuisReponseSorare:
    def test_parse_un_noeud_complet(self):
        noeuds = [
            {
                "id": "off-1",
                "status": "OPENED",
                "rejectionReason": None,
                "createdAt": "2026-09-20T12:00:00+00:00",
                "settlementCurrencies": ["EUR"],
                "receiver": {"slug": "alice"},
                "senderSide": {"amounts": {"eurCents": 700, "wei": "0"}},
                "receiverSide": {
                    "anyCards": [
                        {"assetId": "card-1", "anyPlayer": {"slug": "messi"}},
                    ]
                },
            }
        ]
        offres = depuis_reponse_sorare(noeuds)
        assert len(offres) == 1
        offre = offres[0]
        assert offre.sorare_id == "off-1"
        assert offre.vendeur_slug == "alice"
        assert offre.joueurs_slugs == ("messi",)
        assert offre.montant_valeur == 700
        assert offre.montant_devise == "EUR"
        # blockchainId/counteredOffer absents du fixture : valeurs par défaut,
        # pas de KeyError sur un champ optionnel manquant (lot L7).
        assert offre.blockchain_id is None
        assert offre.contre_offre_montant is None

    def test_parse_blockchain_id_et_contre_offre(self):
        """Lot L7 : `blockchainId` (annulation) et `counteredOffer`
        (contre-offre) ajoutés à `OFFRES_ENVOYEES_QUERY` — NON VÉRIFIÉ contre
        l'API réelle (voir requetes.py, MESURES.md)."""
        noeuds = [
            {
                "id": "off-1",
                "status": "OPENED",
                "blockchainId": "0xabc123",
                "rejectionReason": None,
                "createdAt": "2026-09-20T12:00:00+00:00",
                "settlementCurrencies": ["EUR"],
                "receiver": {"slug": "alice"},
                "senderSide": {"amounts": {"eurCents": 700, "wei": "0"}},
                "receiverSide": {
                    "anyCards": [{"assetId": "card-1", "anyPlayer": {"slug": "messi"}}]
                },
                "counteredOffer": {
                    "id": "off-2",
                    "senderSide": {"amounts": {"eurCents": None, "wei": None}},
                    "receiverSide": {"amounts": {"eurCents": 650, "wei": None}},
                },
            }
        ]
        offres = depuis_reponse_sorare(noeuds)
        assert len(offres) == 1
        offre = offres[0]
        assert offre.blockchain_id == "0xabc123"
        assert offre.contre_offre_montant == 650

    def test_devise_de_reglement_non_geree_est_ignoree(self):
        noeuds = [
            {
                "id": "off-2",
                "status": "OPENED",
                "rejectionReason": None,
                "createdAt": "2026-09-20T12:00:00+00:00",
                "settlementCurrencies": ["USD"],
                "receiver": {"slug": "alice"},
                "senderSide": {"amounts": {"eurCents": 700, "wei": "0"}},
                "receiverSide": {"anyCards": []},
            }
        ]
        assert depuis_reponse_sorare(noeuds) == []


class _ClientFactice:
    """Renvoie toujours les mêmes nœuds `offres_envoyees`, sans réseau."""

    def __init__(self, noeuds: list[dict]) -> None:
        self._noeuds = noeuds

    def execute(self, query: str, variables: dict | None = None) -> dict:
        assert "tokenOffers" in query
        return {"currentUser": {"tokenOffers": {"nodes": self._noeuds}}}


def _noeud_offre_close(sorare_id: str, statut: str = "rejected") -> dict:
    return {
        "id": sorare_id,
        "status": statut,
        "rejectionReason": None,
        "createdAt": "2026-09-20T12:00:00+00:00",
        "settlementCurrencies": ["EUR"],
        "receiver": {"slug": "alice"},
        "senderSide": {"amounts": {"eurCents": 500, "wei": "0"}},
        "receiverSide": {"anyCards": [{"assetId": "a1", "anyPlayer": {"slug": "messi"}}]},
    }


class TestReconcilierIdempotent:
    """`reconcilier()` doit pouvoir tourner deux fois de suite sans planter.

    Régression : le premier run réel (lot L6, MESURES.md 2026-09-21) a
    planté au *deuxième* `reconcilier` d'affilée avec `UNIQUE constraint
    failed: offres_journal.sorare_id`. Cause : `apparier()` (pure) ne
    compare que contre les lignes *ouvertes* (`lignes_ouvertes`) — une
    offre déjà importée puis close (refusée/acceptée/annulée) redevenait
    « à importer » à chaque nouveau run, et `reconcilier()` tentait de la
    réinsérer avec le même `sorare_id`.
    """

    def test_offre_close_deja_importee_n_est_pas_reimportee(self, session: Session):
        client = _ClientFactice([_noeud_offre_close("off-close-1")])
        horloge = HorlogeFigee(BASE)

        premier = reconcilier(session, client, horloge)
        assert len(premier.a_importer) == 1
        assert premier.cycle_suspendu is True
        assert session.query(OffreJournal).count() == 1

        # Deuxième run : mêmes offres côté Sorare (pas de réseau réel, donc
        # pas de nouveauté) — ne doit ni planter, ni dupliquer la ligne, ni
        # rester indéfiniment suspendu à cause d'une offre déjà connue.
        deuxieme = reconcilier(session, client, horloge)
        assert deuxieme.a_importer == []
        assert deuxieme.cycle_suspendu is False
        assert session.query(OffreJournal).count() == 1
        ligne = session.query(OffreJournal).one()
        assert ligne.sorare_id == "off-close-1"
        assert ligne.etat == EtatOffre.REFUSEE


class TestReconcilierMetAJourLesLignesAppariees:
    """Lot L7 : sans cette mise à jour, une ligne appariée reste ENVOYEE pour
    toujours dans le journal local même si Sorare l'a refusée/acceptée/
    annulée/expirée — la machine à états (`negociation.etats`) n'aurait
    jamais rien de réel sur quoi réagir."""

    def test_ligne_envoyee_devient_refusee_avec_son_motif(self, session: Session):
        ligne = enregistrer_ligne(
            session,
            joueur_slug="messi",
            vendeur_slug="alice",
            prix_demande_valeur=1000,
            prix_demande_devise=Devise.EUR,
            montant_offre_valeur=700,
            montant_offre_devise=Devise.EUR,
            reference_prix_valeur=900,
            reference_fenetre_jours=7,
            reference_nb_ventes=3,
            palier=70,
            date_pose_annonce=BASE,
            horloge_maintenant=BASE,
            mode_simulation=False,
            sorare_id="off-1",
        )
        noeud = _noeud_offre_close("off-1", statut="rejected")
        noeud["rejectionReason"] = "OFFER_TOO_LOW"
        client = _ClientFactice([noeud])
        horloge = HorlogeFigee(BASE)

        rapport = reconcilier(session, client, horloge)

        assert len(rapport.appariees) == 1
        assert ligne.etat == EtatOffre.REFUSEE
        assert ligne.motif_refus == MotifRefus.OFFRE_TROP_BASSE
        # La référence figée au moment de l'envoi ne bouge jamais (CLAUDE.md).
        assert ligne.reference_prix_valeur == 900

    def test_toujours_ouverte_cote_sorare_ne_touche_pas_maj_le(self, session: Session):
        """Pas de sur-écriture si l'état observé n'a pas changé depuis le
        dernier passage — évite un `maj_le` qui bouge sans raison."""
        ligne = enregistrer_ligne(
            session,
            joueur_slug="messi",
            vendeur_slug="alice",
            prix_demande_valeur=1000,
            prix_demande_devise=Devise.EUR,
            montant_offre_valeur=700,
            montant_offre_devise=Devise.EUR,
            reference_prix_valeur=900,
            reference_fenetre_jours=7,
            reference_nb_ventes=3,
            palier=70,
            date_pose_annonce=BASE,
            horloge_maintenant=BASE,
            mode_simulation=False,
            sorare_id="off-1",
        )
        assert ligne.etat == EtatOffre.ENVOYEE
        client = _ClientFactice([_noeud_offre_close("off-1", statut="opened")])
        horloge = HorlogeFigee(BASE + timedelta(hours=1))

        rapport = reconcilier(session, client, horloge)

        assert len(rapport.appariees) == 1
        assert ligne.etat == EtatOffre.ENVOYEE
        assert ligne.maj_le == BASE
