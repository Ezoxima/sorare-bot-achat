"""`paiement/signature.py` : câblage de la signature ETH dans l'envoi réel
(lot L7, suite du 2026-09-21 — voir DECISIONS.md/MESURES.md).

`envoyer_offre_signee` doit :
- ne rien signer si aucune autorisation n'est demandée (comportement L5/L6
  inchangé) ;
- signer via `eth_signature` quand une `EthereumBankTransferAuthorizationRequest`
  est demandée et qu'une clé est enregistrée ;
- lever `ClePriveeAbsenteError` si une signature est nécessaire mais qu'aucune
  clé n'est enregistrée (jamais essayer d'envoyer sans signer) ;
- lever `SignatureNonSupporteeError` pour tout autre type d'autorisation
  (StarkEx, Mangopay/EUR) plutôt que d'envoyer des `approvals` vides.
"""

from __future__ import annotations

import keyring
import pytest
from keyring.backend import KeyringBackend

from acheteur.paiement.cle_ethereum import ClePriveeAbsenteError, enregistrer_cle_privee
from acheteur.paiement.signature import SignatureNonSupporteeError, envoyer_offre_signee
from acheteur.paiement.types import AuthorizationRequest, AuthorizationType, PreparedOffer

# Vecteur public (déjà utilisé dans test_eth_signature_l7.py) — pas un secret.
_CLE_EXEMPLE = "0xa9405b77d085276e4b6e35cf494e83f0533d4751fc13e2fdceb6229330ef5146"

_CHAMPS_EXEMPLE = {
    "contractAddress": "0xC887caC5924033340bdd4dd97812738824bCf989",
    "deadline": "1763474595",
    "amount": "1000000000000000",
    "feeAmount": "0",
    "proxyAddress": "0x0000000000000000000000000000000000000000",
    "receiverAddress": "0xABd4c585d69Fe6fC7380Ad0bE9a9D932Ba74F709",
    "salt": "0x1b6de9fc32e321756431d71322b1c4ed7e45ea1199b7e278dcbc8547bdc7235f",
    "senderAddress": "0xB1a1ed82d0C7DC3f3bA7e2b2613328c64e9d9dA3",
}
_SIGNATURE_ATTENDUE = (
    "0xc503f3f479dfc8c2a76ca8cdf336b0a270cda0ae407fe5270a87b7cdacd2efb"
    "8046ccb6e31a7853e22a7541b67f2c49a6ae8cf006673ed17d6995aeb3e624f"
    "bf1c"
)


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
    """Capture l'input envoyé à createDirectOffer, sans jamais toucher le réseau."""

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
        "receiveAmount": {"amount": "0", "currency": "WEI"},
        "sendAssetIds": [],
        "sendAmount": {"amount": "6600000000000000", "currency": "WEI"},
        "settlementCurrencies": ["WEI"],
    }
    return PreparedOffer(input_data=input_data, authorizations=authorizations, errors=[])


def test_sans_autorisation_approvals_vide_et_pas_de_cle_requise():
    client = _ClientEnregistreInput()
    envoyer_offre_signee(client, _prepared([]))
    assert client.dernier_input["approvals"] == []


def test_autorisation_ethereum_signee_avec_la_cle_enregistree():
    enregistrer_cle_privee(_CLE_EXEMPLE)
    auth = AuthorizationRequest(
        id="auth-1",
        fingerprint="empreinte-1",
        request_type=AuthorizationType.ETHEREUM_BANK_TRANSFER,
        status="pending",
        champs=_CHAMPS_EXEMPLE,
    )
    client = _ClientEnregistreInput()

    envoyer_offre_signee(client, _prepared([auth]))

    approvals = client.dernier_input["approvals"]
    assert len(approvals) == 1
    assert approvals[0]["fingerprint"] == "empreinte-1"
    assert approvals[0]["ethereumBankTransferApproval"]["signature"] == _SIGNATURE_ATTENDUE
    assert approvals[0]["ethereumBankTransferApproval"]["deadline"] == "1763474595"
    assert approvals[0]["ethereumBankTransferApproval"]["salt"] == _CHAMPS_EXEMPLE["salt"]


def test_autorisation_ethereum_sans_cle_enregistree_leve():
    auth = AuthorizationRequest(
        id="auth-1",
        fingerprint="empreinte-1",
        request_type=AuthorizationType.ETHEREUM_BANK_TRANSFER,
        status="pending",
        champs=_CHAMPS_EXEMPLE,
    )
    with pytest.raises(ClePriveeAbsenteError):
        envoyer_offre_signee(_ClientEnregistreInput(), _prepared([auth]))


def test_autorisation_non_geree_leve_sans_envoyer_approvals_vides():
    """`MangopayWalletTransferAuthorizationRequest` est géré depuis
    (voir test_signature_starkex_l7.py) — ce test vérifie qu'un type
    vraiment non géré (StarkEx transfer/limit order) échoue toujours."""
    enregistrer_cle_privee(_CLE_EXEMPLE)
    auth = AuthorizationRequest(
        id="auth-2",
        fingerprint="empreinte-2",
        request_type=AuthorizationType.STARKEX_TRANSFER,
        status="pending",
        champs={"nonce": "1", "amount": "100"},
    )
    with pytest.raises(SignatureNonSupporteeError, match="StarkexTransferAuthorizationRequest"):
        envoyer_offre_signee(_ClientEnregistreInput(), _prepared([auth]))
