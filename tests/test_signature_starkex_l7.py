"""`paiement/signature.py` : câblage de la signature StarkEx/Mangopay (rail
EUR) dans l'envoi réel (lot L7 suite — voir DECISIONS.md « Rail EUR »).

Même structure que `test_signature_eth_l7.py`, pour le rail EUR cette fois :
`envoyer_offre_signee` doit signer via `starkex_signature` quand une
`MangopayWalletTransferAuthorizationRequest` est demandée et qu'une clé
StarkEx est enregistrée, et lever `ClePriveeAbsenteError` sinon.
"""

from __future__ import annotations

import keyring
import pytest
from keyring.backend import KeyringBackend

from acheteur.paiement.cle_starkex import ClePriveeAbsenteError, enregistrer_cle_privee
from acheteur.paiement.signature import envoyer_offre_signee
from acheteur.paiement.types import AuthorizationRequest, AuthorizationType, PreparedOffer

# Vecteur public StarkWare (déjà utilisé dans test_starkex_signature_l7.py) — pas un secret.
_CLE_PRIVEE_EXEMPLE = "0x7cc2767a160d4ea112b436dc6f79024db70b26b11ed7aa2cb6d7eef19ace703"

_CHAMPS_EXEMPLE = {
    "mangopayWalletId": "wallet-1",
    "operationHash": "0xabc123",
    "currency": "EUR",
    "amount": 1000,
    "nonce": 42,
}


class _KeyringMemoire(KeyringBackend):
    priority = 1

    def __init__(self):
        self._stockage: dict[tuple[str, str], str] = {}

    def set_password(self, service, username, password):
        self._stockage[(service, username)] = password

    def get_password(self, service, username):
        return self._stockage.get((service, username))

    def delete_password(self, service, username):
        try:
            del self._stockage[(service, username)]
        except KeyError:
            raise keyring.errors.PasswordDeleteError("absent")


@pytest.fixture(autouse=True)
def _keyring_isole():
    ancien = keyring.get_keyring()
    keyring.set_keyring(_KeyringMemoire())
    yield
    keyring.set_keyring(ancien)


class _ClientEnregistreInput:
    def __init__(self):
        self.dernier_input = None

    def execute(self, query, variables=None):
        assert "createDirectOffer" in query
        self.dernier_input = variables["input"]
        return {"createDirectOffer": {"tokenOffer": {"id": "token-1"}, "errors": []}}


def _prepared(authorizations: list[AuthorizationRequest]) -> PreparedOffer:
    input_data = {
        "clientMutationId": "prepare-offer-alice",
        "receiveAssetIds": ["asset-1"],
        "receiverSlug": "alice",
        "receiveAmount": {"amount": "0", "currency": "EUR"},
        "sendAssetIds": [],
        "sendAmount": {"amount": "1000", "currency": "EUR"},
        "settlementCurrencies": ["EUR"],
    }
    return PreparedOffer(input_data=input_data, authorizations=authorizations, errors=[])


def test_autorisation_mangopay_signee_avec_la_cle_starkex_enregistree():
    enregistrer_cle_privee(_CLE_PRIVEE_EXEMPLE)
    auth = AuthorizationRequest(
        id="auth-1",
        fingerprint="empreinte-1",
        request_type=AuthorizationType.MANGOPAY_WALLET,
        status="pending",
        champs=_CHAMPS_EXEMPLE,
    )
    client = _ClientEnregistreInput()

    envoyer_offre_signee(client, _prepared([auth]))

    approvals = client.dernier_input["approvals"]
    assert len(approvals) == 1
    assert approvals[0]["fingerprint"] == "empreinte-1"
    approbation = approvals[0]["mangopayWalletTransferApproval"]
    assert approbation["nonce"] == 42
    assert approbation["signature"]["r"].startswith("0x")
    assert approbation["signature"]["s"].startswith("0x")


def test_autorisation_mangopay_sans_cle_starkex_enregistree_leve():
    auth = AuthorizationRequest(
        id="auth-1",
        fingerprint="empreinte-1",
        request_type=AuthorizationType.MANGOPAY_WALLET,
        status="pending",
        champs=_CHAMPS_EXEMPLE,
    )
    with pytest.raises(ClePriveeAbsenteError):
        envoyer_offre_signee(_ClientEnregistreInput(), _prepared([auth]))
