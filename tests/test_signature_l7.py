"""`paiement/signature.py` : construction de `createDirectOfferInput`.

Régression réelle (lot L7, premier envoi réel déclenché par l'utilisateur,
2026-09-21, voir MESURES.md) : l'input était recopié tel quel depuis
`prepareOfferInput` (préparation), un type différent — erreur GraphQL réelle
« settlementCurrencies is not defined on createDirectOfferInput » et
`dealId` (requis) manquant. Fonctions pures ici, aucun réseau.
"""

from __future__ import annotations

from acheteur.paiement.signature import _construire_input_create_direct_offer, _generer_deal_id
from acheteur.paiement.types import PreparedOffer


def _prepared(**overrides) -> PreparedOffer:
    input_data = {
        "clientMutationId": "prepare-offer-alice",
        "receiveAssetIds": ["asset-1"],
        "receiverSlug": "alice",
        "receiveAmount": {"amount": "0", "currency": "EUR"},
        "sendAssetIds": [],
        "sendAmount": {"amount": "700", "currency": "EUR"},
        "settlementCurrencies": ["EUR"],
    }
    input_data.update(overrides)
    return PreparedOffer(input_data=input_data, authorizations=[], errors=[])


class TestGenererDealId:
    def test_renvoie_une_chaine_non_vide(self):
        assert isinstance(_generer_deal_id(), str)
        assert len(_generer_deal_id()) > 0

    def test_deux_appels_ne_collisionnent_pas(self):
        assert _generer_deal_id() != _generer_deal_id()


class TestConstruireInputCreateDirectOffer:
    def test_ne_contient_jamais_settlement_currencies(self):
        """`createDirectOfferInput` n'a pas ce champ — le laisser cause une
        vraie erreur GraphQL (« Field is not defined »)."""
        input_create = _construire_input_create_direct_offer(_prepared(), approvals=[])
        assert "settlementCurrencies" not in input_create

    def test_contient_un_deal_id(self):
        """`dealId` est `String!` (obligatoire) côté createDirectOfferInput."""
        input_create = _construire_input_create_direct_offer(_prepared(), approvals=[])
        assert input_create["dealId"]
        assert isinstance(input_create["dealId"], str)

    def test_reprend_les_champs_communs_de_prepared(self):
        input_create = _construire_input_create_direct_offer(_prepared(), approvals=[])
        assert input_create["receiverSlug"] == "alice"
        assert input_create["receiveAssetIds"] == ["asset-1"]
        assert input_create["sendAmount"] == {"amount": "700", "currency": "EUR"}
        assert input_create["sendAssetIds"] == []
        assert input_create["clientMutationId"] == "prepare-offer-alice"

    def test_transmet_les_approvals_donnees(self):
        approvals = [{"id": "auth-1", "signature": "0xabc"}]
        input_create = _construire_input_create_direct_offer(_prepared(), approvals=approvals)
        assert input_create["approvals"] == approvals
