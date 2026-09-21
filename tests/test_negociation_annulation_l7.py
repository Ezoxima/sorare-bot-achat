"""Lot L7 : annulation d'une offre ouverte (`negociation/annulation.py`) et
comptage des ré-essais sur expiration (`journal.reessai_expiration_deja_fait`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from acheteur.core.db import Base
from acheteur.core.horloge import HorlogeFigee
from acheteur.garde_fous.regles import GuardrailViolation
from acheteur.marche.devises import Devise
from acheteur.negociation.annulation import annuler_ligne
from acheteur.negociation.journal import EtatOffre, MotifRefus, OffreJournal, reessai_expiration_deja_fait

BASE = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)


@pytest.fixture
def session():
    moteur = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(moteur)
    fabrique = sessionmaker(bind=moteur)
    s = fabrique()
    yield s
    s.close()


def _ligne(session, **overrides) -> OffreJournal:
    defaults = dict(
        joueur_slug="messi",
        vendeur_slug="alice",
        montant_offre_valeur=500,
        montant_offre_devise=Devise.EUR,
        etat=EtatOffre.ENVOYEE,
        mode_simulation=False,
        cree_le=BASE,
        maj_le=BASE,
    )
    defaults.update(overrides)
    ligne = OffreJournal(**defaults)
    session.add(ligne)
    session.flush()
    return ligne


class TestAnnulerLigne:
    def test_simulation_marque_annulee_sans_reseau(self, session):
        ligne = _ligne(session, mode_simulation=True, etat=EtatOffre.SIMULEE)
        horloge = HorlogeFigee(BASE)

        annuler_ligne(ligne, session, horloge, mode_simulation=True)

        assert ligne.etat == EtatOffre.ANNULEE

    def test_arret_urgence_bloque(self, session, tmp_path: Path):
        ligne = _ligne(session, mode_simulation=True, etat=EtatOffre.SIMULEE)
        (tmp_path / ".arret-urgence").write_text("stop")
        horloge = HorlogeFigee(BASE)

        with pytest.raises(GuardrailViolation, match="Arrêt d'urgence"):
            annuler_ligne(ligne, session, horloge, mode_simulation=True, chemin_racine=tmp_path)

        # Rien n'a été modifié : l'arrêt d'urgence bloque avant toute mutation.
        assert ligne.etat == EtatOffre.SIMULEE

    def test_mode_reel_sans_sorare_id_ne_touche_pas_le_reseau(self, session):
        """Une ligne envoyée uniquement en simulation (jamais atteint Sorare,
        sorare_id=None) n'a rien à annuler côté réseau — pas d'exception."""
        ligne = _ligne(session, mode_simulation=True, etat=EtatOffre.SIMULEE, sorare_id=None)
        horloge = HorlogeFigee(BASE)

        annuler_ligne(ligne, session, horloge, mode_simulation=False)

        assert ligne.etat == EtatOffre.ANNULEE

    def test_mode_reel_sans_client_leve(self, session):
        ligne = _ligne(session, sorare_id="offer-1")
        horloge = HorlogeFigee(BASE)

        with pytest.raises(ValueError, match="client Sorare"):
            annuler_ligne(
                ligne, session, horloge, mode_simulation=False, blockchain_id="0xabc"
            )

    def test_mode_reel_sans_blockchain_id_leve(self, session):
        ligne = _ligne(session, sorare_id="offer-1")
        horloge = HorlogeFigee(BASE)

        with pytest.raises(ValueError, match="blockchain_id"):
            annuler_ligne(
                ligne, session, horloge, mode_simulation=False, client=object()
            )


class TestReessaiExpirationDejaFait:
    def test_premiere_offre_sans_predecesseur_pas_de_reessai(self, session):
        ligne = _ligne(session)
        assert reessai_expiration_deja_fait(session, ligne) is False

    def test_predecesseur_expire_sans_motif_signale_reessai_consomme(self, session):
        premiere = _ligne(session, etat=EtatOffre.EXPIREE, motif_refus=None)
        retour = _ligne(session, offre_precedente_id=premiere.id)
        assert reessai_expiration_deja_fait(session, retour) is True

    def test_predecesseur_refuse_ne_compte_pas_comme_reessai(self, session):
        """Une escalade née d'un refus (pas d'une expiration) n'a pas encore
        consommé son propre droit au ré-essai sur expiration."""
        premiere = _ligne(session, etat=EtatOffre.REFUSEE, motif_refus=MotifRefus.OFFRE_TROP_BASSE)
        escalade = _ligne(session, offre_precedente_id=premiere.id)
        assert reessai_expiration_deja_fait(session, escalade) is False
