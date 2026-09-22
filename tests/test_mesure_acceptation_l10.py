"""Tests du lot L10 : taux d'acceptation par palier et par motif de refus."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import count

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from acheteur.core.db import Base
from acheteur.marche.devises import Devise
from acheteur.mesure.acceptation import calculer_taux_acceptation
from acheteur.negociation.journal import (
    EtatOffre,
    MotifRefus,
    enregistrer_ligne,
    importer_ligne_manuelle,
)

BASE = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
_COMPTEUR_JOUEUR = count()


@pytest.fixture
def session():
    moteur = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(moteur)
    fabrique = sessionmaker(bind=moteur)
    s = fabrique()
    yield s
    s.close()


def _ligne_close(
    session: Session,
    *,
    etat: EtatOffre,
    motif_refus: MotifRefus | None = None,
    **kwargs,
):
    """Écrit une ligne décidée par le bot puis la fait passer directement à
    un état clos — l'unicité (joueur, vendeur) ne porte que sur les états
    ouverts (`journal.ETATS_OUVERTS`), donc plusieurs lignes closes peuvent
    partager le même couple sans violer la contrainte."""
    defauts = dict(
        joueur_slug=f"joueur-{next(_COMPTEUR_JOUEUR)}",
        vendeur_slug="vendeur",
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
        mode_simulation=False,
    )
    defauts.update(kwargs)
    ligne = enregistrer_ligne(session, **defauts)
    ligne.etat = etat
    ligne.motif_refus = motif_refus
    session.flush()
    return ligne


class TestPerimetre:
    def test_ligne_simulee_exclue_du_calcul(self, session: Session):
        ligne = _ligne_close(session, etat=EtatOffre.ACCEPTEE, mode_simulation=True)
        rapport = calculer_taux_acceptation([ligne])
        assert rapport.par_palier == []
        assert rapport.lignes_hors_perimetre == 1
        assert rapport.par_motif_refus == {}

    def test_ligne_importee_exclue_du_calcul(self, session: Session):
        ligne = importer_ligne_manuelle(
            session,
            sorare_id="import-1",
            joueur_slug="mbappe",
            vendeur_slug="bob",
            montant_offre_valeur=500,
            montant_offre_devise=Devise.EUR,
            etat=EtatOffre.ACCEPTEE,
            motif_refus=None,
            reponse_brute=None,
            creee_le=BASE,
            horloge_maintenant=BASE,
        )
        rapport = calculer_taux_acceptation([ligne])
        assert rapport.par_palier == []
        assert rapport.lignes_hors_perimetre == 1

    def test_ligne_ouverte_ni_conclue_ni_hors_perimetre(self, session: Session):
        """Une ligne encore envoyée (pas de verdict) : ignorée sans compter
        comme hors périmètre — ce n'est pas exclue par construction, juste
        pas encore terminée."""
        ligne = _ligne_close(session, etat=EtatOffre.ENVOYEE)
        rapport = calculer_taux_acceptation([ligne])
        assert rapport.par_palier == []
        assert rapport.lignes_hors_perimetre == 0

    def test_ligne_en_sommeil_ni_conclue_ni_hors_perimetre(self, session: Session):
        ligne = _ligne_close(session, etat=EtatOffre.EN_SOMMEIL)
        rapport = calculer_taux_acceptation([ligne])
        assert rapport.par_palier == []
        assert rapport.lignes_hors_perimetre == 0


class TestTauxParPalier:
    def test_taux_calcule_correctement(self, session: Session):
        lignes = [
            _ligne_close(session, etat=EtatOffre.ACCEPTEE, palier=70),
            _ligne_close(session, etat=EtatOffre.ACCEPTEE, palier=70),
            _ligne_close(session, etat=EtatOffre.REFUSEE, palier=70, motif_refus=MotifRefus.OFFRE_TROP_BASSE),
            _ligne_close(session, etat=EtatOffre.REFUSEE, palier=70, motif_refus=MotifRefus.OFFRE_TROP_BASSE),
        ]
        rapport = calculer_taux_acceptation(lignes)
        assert len(rapport.par_palier) == 1
        ligne = rapport.par_palier[0]
        assert ligne.palier == 70
        assert ligne.acceptees == 2
        assert ligne.total == 4
        assert ligne.taux == 0.5

    def test_paliers_distincts_regroupes_separement(self, session: Session):
        lignes = [
            _ligne_close(session, etat=EtatOffre.ACCEPTEE, palier=70),
            _ligne_close(session, etat=EtatOffre.ACCEPTEE, palier=80),
            _ligne_close(session, etat=EtatOffre.REFUSEE, palier=80, motif_refus=MotifRefus.OFFRE_TROP_BASSE),
        ]
        rapport = calculer_taux_acceptation(lignes)
        par_palier = {t.palier: t for t in rapport.par_palier}
        assert par_palier[70].total == 1
        assert par_palier[70].taux == 1.0
        assert par_palier[80].total == 2
        assert par_palier[80].taux == 0.5

    def test_taux_absent_est_none_pas_zero(self, session: Session):
        """PLAN.md laisse le seuil d'effectif ouvert : un total à 0 doit
        rester distinguable d'un vrai 0% de succès."""
        from acheteur.mesure.acceptation import TauxParPalier

        vide = TauxParPalier(palier=70, acceptees=0, total=0)
        assert vide.taux is None

    def test_expiree_et_annulee_comptent_comme_conclues_non_acceptees(self, session: Session):
        lignes = [
            _ligne_close(session, etat=EtatOffre.EXPIREE, palier=70),
            _ligne_close(session, etat=EtatOffre.ANNULEE, palier=70),
        ]
        rapport = calculer_taux_acceptation(lignes)
        assert rapport.par_palier[0].total == 2
        assert rapport.par_palier[0].acceptees == 0


class TestMotifsRefus:
    def test_motifs_comptes_par_type(self, session: Session):
        lignes = [
            _ligne_close(session, etat=EtatOffre.REFUSEE, motif_refus=MotifRefus.OFFRE_TROP_BASSE),
            _ligne_close(session, etat=EtatOffre.REFUSEE, motif_refus=MotifRefus.OFFRE_TROP_BASSE),
            _ligne_close(session, etat=EtatOffre.REFUSEE, motif_refus=MotifRefus.NE_VEND_PAS),
        ]
        rapport = calculer_taux_acceptation(lignes)
        assert rapport.par_motif_refus[MotifRefus.OFFRE_TROP_BASSE] == 2
        assert rapport.par_motif_refus[MotifRefus.NE_VEND_PAS] == 1
        assert rapport.total_refuse == 3

    def test_refus_sans_motif_compte_a_part(self, session: Session):
        """journal.MotifRefus : SANS_MOTIF n'existe pas côté Sorare, mais un
        refus explicite sans motif renseigné doit être compté à part, pas
        fusionné silencieusement avec OFFRE_TROP_BASSE (c'est une hypothèse
        d'escalade, pas un fait mesuré — voir journal.py)."""
        ligne = _ligne_close(session, etat=EtatOffre.REFUSEE, motif_refus=None)
        rapport = calculer_taux_acceptation([ligne])
        assert rapport.par_motif_refus == {MotifRefus.SANS_MOTIF: 1}

    def test_acceptees_n_apparaissent_pas_dans_les_motifs(self, session: Session):
        ligne = _ligne_close(session, etat=EtatOffre.ACCEPTEE)
        rapport = calculer_taux_acceptation([ligne])
        assert rapport.par_motif_refus == {}
