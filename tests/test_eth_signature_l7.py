"""Signature `EthereumBankTransferAuthorizationRequest` (lot L7).

Vecteur de test : exemple officiel Sorare
(`sorare/api`, `examples/baseBankTransfer.js` sur GitHub, récupéré le
2026-09-21) — clé privée et signature attendue **publiées publiquement dans
cet exemple**, pas un secret de ce projet ni de l'utilisateur. Sert à
prouver, sans toucher à un vrai compte, que la reconstruction Python du
message à signer produit un octet pour octet la même signature que
l'implémentation JavaScript officielle.
"""

from __future__ import annotations

from acheteur.paiement.eth_signature import (
    construire_hash_ethereum_bank_transfer,
    signer_autorisation_ethereum_bank_transfer,
)

# Vecteur public, voir docstring du module.
_CLE_PRIVEE_EXEMPLE = "0xa9405b77d085276e4b6e35cf494e83f0533d4751fc13e2fdceb6229330ef5146"
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


def test_hash_reconstruit_correctement():
    """Le hash n'est pas exposé par l'exemple JS (seule la signature finale
    l'est) — ce test protège au moins contre une régression de forme."""
    hash_message = construire_hash_ethereum_bank_transfer(_CHAMPS_EXEMPLE)
    assert isinstance(hash_message, bytes)
    assert len(hash_message) == 32


def test_signature_identique_a_l_exemple_officiel_sorare():
    """LE test qui compte : reproduit exactement `examples/baseBankTransfer.js`
    du dépôt officiel `sorare/api`, signature attendue publiée dans ce
    fichier en commentaire."""
    approbation = signer_autorisation_ethereum_bank_transfer(_CHAMPS_EXEMPLE, _CLE_PRIVEE_EXEMPLE)
    assert approbation.signature == _SIGNATURE_ATTENDUE

    assert approbation.deadline == "1763474595"
    assert approbation.salt == _CHAMPS_EXEMPLE["salt"]


def test_salt_de_mauvaise_taille_leve():
    champs = dict(_CHAMPS_EXEMPLE, salt="0x1234")
    import pytest

    with pytest.raises(ValueError, match="32 octets"):
        construire_hash_ethereum_bank_transfer(champs)
