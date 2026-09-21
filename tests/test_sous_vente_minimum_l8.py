"""`est_sous_vente_minimum` / `prix_minimum_avant` (`decision/selecteur.py`) —
second signal de sélection, inspiré de `SOUS_VENTE_MINI` (sealing-sorare-
apps-script/03 - bonnes affaires.gs). Voir DECISIONS.md (2026-09-22)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from acheteur.decision.selecteur import est_sous_vente_minimum, prix_minimum_avant
from acheteur.marche.devises import Devise, Montant
from acheteur.marche.types import Annonce, Joueur, Rareté, Vente

POSE = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
JOUEUR = Joueur("messi", "Messi", Rareté("Limited", 2))


def _annonce(prix_cents: int) -> Annonce:
    return Annonce(
        joueur=JOUEUR,
        vendeur_slug="vendeur1",
        prix_demande=Montant(prix_cents, Devise.EUR),
        accepte_eth=False,
        accepte_eur=True,
        date_pose=POSE,
    )


def _vente(prix_cents: int, avant: bool, devise: Devise = Devise.EUR) -> Vente:
    date_vente = POSE - timedelta(days=1) if avant else POSE + timedelta(days=1)
    return Vente(joueur=JOUEUR, prix=Montant(prix_cents, devise), date_vente=date_vente)


class TestPrixMinimumAvant:
    def test_ignore_les_ventes_posterieures(self):
        ventes = [_vente(100, avant=True), _vente(50, avant=False)]
        assert prix_minimum_avant(ventes, POSE).valeur == 100

    def test_garde_le_minimum_parmi_plusieurs(self):
        ventes = [_vente(120, avant=True), _vente(90, avant=True), _vente(200, avant=True)]
        assert prix_minimum_avant(ventes, POSE).valeur == 90

    def test_aucune_vente_anterieure_rend_none(self):
        ventes = [_vente(50, avant=False)]
        assert prix_minimum_avant(ventes, POSE) is None

    def test_devises_melangees_leve_une_erreur(self):
        ventes = [_vente(100, avant=True, devise=Devise.EUR), _vente(1, avant=True, devise=Devise.ETH)]
        with pytest.raises(ValueError):
            prix_minimum_avant(ventes, POSE)


class TestEstSousVenteMinimum:
    def test_sous_le_seuil_par_rapport_au_plancher(self):
        annonce = _annonce(70)  # 70% du plancher de 100
        ventes = [_vente(100, avant=True)]
        assert est_sous_vente_minimum(annonce, ventes, seuil_pourcent=80)

    def test_au_dessus_du_seuil(self):
        annonce = _annonce(90)  # 90% du plancher de 100
        ventes = [_vente(100, avant=True)]
        assert not est_sous_vente_minimum(annonce, ventes, seuil_pourcent=80)

    def test_aucune_vente_anterieure_ne_leve_pas_rend_faux(self):
        """Contrairement à `est_bonne_affaire`, l'absence de référence est un
        cas normal (pas une erreur d'appelant) — pas d'exception."""
        annonce = _annonce(1)
        assert not est_sous_vente_minimum(annonce, [], seuil_pourcent=80)

    def test_devise_incoherente_rend_faux_sans_lever(self):
        annonce = _annonce(70)
        ventes = [_vente(1, avant=True, devise=Devise.ETH)]
        assert not est_sous_vente_minimum(annonce, ventes, seuil_pourcent=80)
