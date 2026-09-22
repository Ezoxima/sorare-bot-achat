"""Fichier de propositions (`acheteur.approbation.fichier_propositions`) —
round-trip JSON (fonctions pures, pas de réseau ni base réelle) et détection
de péremption."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from acheteur.approbation.fichier_propositions import (
    charger_propositions,
    dernier_fichier_propositions,
    fichier_perime,
    sauvegarder_propositions,
)
from acheteur.decision.paliers import Palier
from acheteur.decision.proposition import PropositionGroupe, PropositionSimple
from acheteur.marche.devises import Devise, Montant
from acheteur.marche.types import Annonce, Joueur, Rareté

BASE = datetime(2026, 9, 22, 19, 0, tzinfo=UTC)


def _annonce(joueur_slug: str, prix_cents: int, vendeur_slug: str = "vendeur1") -> Annonce:
    return Annonce(
        joueur=Joueur(slug=joueur_slug, nom=joueur_slug.title(), rareté=Rareté("Limited", 2)),
        vendeur_slug=vendeur_slug,
        prix_demande=Montant(prix_cents, Devise.EUR),
        accepte_eth=False,
        accepte_eur=True,
        date_pose=BASE,
        asset_id=f"asset-{joueur_slug}",
        in_season=False,
    )


class TestRoundTripSimple:
    def test_sauvegarde_puis_chargement_preserve_toutes_les_valeurs(self, tmp_path):
        proposition = PropositionSimple(
            annonce=_annonce("a", 700),
            reference_prix_valeur=1000,
            montant_offre=490,
            palier=Palier.PREMIER,
        )
        chemin = sauvegarder_propositions([proposition], BASE, dossier=tmp_path)
        horodatage, propositions = charger_propositions(chemin)

        assert horodatage == BASE
        assert len(propositions) == 1
        rechargee = propositions[0]
        assert isinstance(rechargee, PropositionSimple)
        assert rechargee.annonce.joueur.slug == "a"
        assert rechargee.annonce.prix_demande == Montant(700, Devise.EUR)
        assert rechargee.reference_prix_valeur == 1000
        assert rechargee.montant_offre == 490
        assert rechargee.palier == Palier.PREMIER


class TestRoundTripGroupe:
    def test_sauvegarde_puis_chargement_preserve_le_groupe(self, tmp_path):
        proposition = PropositionGroupe(
            annonces=(_annonce("a", 700, "vendeur1"), _annonce("b", 500, "vendeur1")),
            references_prix={"a": 1000, "b": 800},
            montants_offre={"a": 455, "b": 325},
            palier=Palier.PREMIER,
            decote_appliquee=True,
        )
        chemin = sauvegarder_propositions([proposition], BASE, dossier=tmp_path)
        _horodatage, propositions = charger_propositions(chemin)

        rechargee = propositions[0]
        assert isinstance(rechargee, PropositionGroupe)
        assert len(rechargee.annonces) == 2
        assert rechargee.montant_total == 780
        assert rechargee.decote_appliquee is True


class TestDernierFichier:
    def test_absent_si_dossier_vide(self, tmp_path):
        assert dernier_fichier_propositions(tmp_path) is None

    def test_renvoie_le_plus_recent(self, tmp_path):
        proposition = PropositionSimple(
            annonce=_annonce("a", 700),
            reference_prix_valeur=1000,
            montant_offre=490,
            palier=Palier.PREMIER,
        )
        plus_ancien = sauvegarder_propositions([proposition], BASE, dossier=tmp_path)
        plus_recent = sauvegarder_propositions(
            [proposition], BASE + timedelta(minutes=15), dossier=tmp_path
        )

        assert plus_ancien != plus_recent
        assert dernier_fichier_propositions(tmp_path) == plus_recent


class TestFichierPerime:
    def test_pas_perime_juste_apres(self):
        assert fichier_perime(BASE, BASE + timedelta(minutes=5)) is False

    def test_perime_au_dela_du_delai(self):
        assert fichier_perime(BASE, BASE + timedelta(minutes=31)) is True

    def test_delai_personnalise(self):
        assert fichier_perime(BASE, BASE + timedelta(minutes=10), delai_minutes=5) is True
