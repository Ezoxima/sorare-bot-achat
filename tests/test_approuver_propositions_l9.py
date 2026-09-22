"""`cli/approuver_propositions.py` — fonctions pures uniquement (parsing de
la sélection utilisateur, totaux par devise) ; le reste (réseau, DB, envoi
réel) est déjà couvert par les tests L6/L7 sur les mêmes primitives
partagées (barrière, réconciliation)."""

from __future__ import annotations

from datetime import UTC, datetime

from acheteur.cli.approuver_propositions import _parser_selection, _totaux_par_devise
from acheteur.decision.paliers import Palier
from acheteur.decision.proposition import PropositionSimple
from acheteur.marche.devises import Devise, Montant
from acheteur.marche.types import Annonce, Joueur, Rareté

BASE = datetime(2026, 9, 22, 19, 0, tzinfo=UTC)


def _proposition(joueur_slug: str, montant: int, devise: Devise = Devise.EUR) -> PropositionSimple:
    annonce = Annonce(
        joueur=Joueur(slug=joueur_slug, nom=joueur_slug.title(), rareté=Rareté("Limited", 2)),
        vendeur_slug="vendeur1",
        prix_demande=Montant(montant * 2, devise),
        accepte_eth=devise == Devise.ETH,
        accepte_eur=devise == Devise.EUR,
        date_pose=BASE,
        asset_id=f"asset-{joueur_slug}",
        in_season=False,
    )
    return PropositionSimple(
        annonce=annonce,
        reference_prix_valeur=montant * 3,
        montant_offre=montant,
        palier=Palier.PREMIER,
    )


class TestParserSelection:
    def test_toutes(self):
        assert _parser_selection("toutes", 3) == [0, 1, 2]

    def test_aucune(self):
        assert _parser_selection("aucune", 3) == []

    def test_liste_indices(self):
        assert _parser_selection("1,3", 3) == [0, 2]

    def test_espaces_tolérés(self):
        assert _parser_selection(" 1 , 2 ", 3) == [0, 1]

    def test_index_hors_bornes_invalide(self):
        assert _parser_selection("1,4", 3) is None

    def test_index_zero_invalide(self):
        assert _parser_selection("0", 3) is None

    def test_non_numerique_invalide(self):
        assert _parser_selection("abc", 3) is None


class TestTotauxParDevise:
    def test_additionne_par_devise(self):
        propositions = [
            _proposition("a", 100, Devise.EUR),
            _proposition("b", 200, Devise.EUR),
            _proposition("c", 5 * 10**14, Devise.ETH),
        ]
        totaux = _totaux_par_devise(propositions, [0, 1, 2])
        assert totaux[Devise.EUR] == 300
        assert totaux[Devise.ETH] == 5 * 10**14

    def test_ne_compte_que_les_indices_selectionnes(self):
        propositions = [_proposition("a", 100), _proposition("b", 200)]
        totaux = _totaux_par_devise(propositions, [1])
        assert totaux[Devise.EUR] == 200
