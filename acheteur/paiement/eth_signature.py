"""Signature d'une autorisation `EthereumBankTransferAuthorizationRequest`
(lot L7, PLAN.md § « L'inconnue n°1 »).

Confirmé contre le compte réel (2026-09-21, voir MESURES.md) : une offre
payée en ETH demande ce type d'autorisation, pas une signature StarkEx —
donc signable en Python pur. La recette exacte (encodage des paramètres,
hachage, signature) vient de l'exemple officiel Sorare
(`sorare/api`, `examples/baseBankTransfer.js` sur GitHub) ; ce module la
reproduit et la vérifie contre le vecteur de test publié dans cet exemple
(clé privée et signature attendue publiques, pas un secret — voir
`tests/test_eth_signature_l7.py`).

**Aucune clé privée réelle n'est manipulée par ce module lui-même** : il ne
fait que signer étant donné une clé passée par l'appelant. D'où et comment
cette clé est obtenue pour de vrai (jamais stockée en clair, CLAUDE.md §
Secrets) est une décision distincte, pas encore prise — voir DECISIONS.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eth_abi import encode
from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import keccak


@dataclass(frozen=True)
class ApprobationEthereumBankTransfer:
    """Ce qu'il faut renvoyer dans `AuthorizationApprovalInput.ethereumBankTransferApproval`."""

    signature: str
    deadline: str
    salt: str


def _en_bytes32(salt_hex: str) -> bytes:
    """`salt` arrive en hex (`0x...`, 32 octets) — converti pour l'ABI encode."""
    valeur = bytes.fromhex(salt_hex.removeprefix("0x"))
    if len(valeur) != 32:
        raise ValueError(f"salt doit faire 32 octets, en fait {len(valeur)} : {salt_hex!r}")
    return valeur


def construire_hash_ethereum_bank_transfer(champs: dict[str, Any]) -> bytes:
    """Reconstruit le hash à signer pour une `EthereumBankTransferAuthorizationRequest`.

    Args:
        champs: les champs de la requête tels que renvoyés par `prepareOffer`
            (voir `paiement.types.AuthorizationRequest.champs`) —
            `senderAddress`, `receiverAddress`, `amount`, `feeAmount`,
            `deadline`, `salt`, `proxyAddress`, `contractAddress`.

    Returns:
        le hash keccak256 (32 octets) à signer — équivalent Python de
        `keccak256(encodeAbiParameters(...))` côté JS (voir docstring du
        module). L'étape `encodePacked(['bytes'], [hash])` de l'exemple JS
        est l'identité pour un seul argument `bytes` : ce hash EST déjà le
        message final, pas besoin de la reproduire.
    """
    types = ["address", "address", "uint256", "uint256", "uint64", "bytes32", "address", "bytes", "address"]
    valeurs = [
        champs["senderAddress"],
        champs["receiverAddress"],
        int(champs["amount"]),
        int(champs["feeAmount"]),
        int(champs["deadline"]),
        _en_bytes32(champs["salt"]),
        champs["proxyAddress"],
        b"",
        champs["contractAddress"],
    ]
    message = encode(types, valeurs)
    return keccak(message)


def signer_autorisation_ethereum_bank_transfer(
    champs: dict[str, Any],
    cle_privee: str,
) -> ApprobationEthereumBankTransfer:
    """Signe une `EthereumBankTransferAuthorizationRequest`.

    Args:
        champs: voir `construire_hash_ethereum_bank_transfer`
        cle_privee: clé privée Ethereum du compte (hex, avec ou sans `0x`) —
            jamais journalisée, jamais stockée par ce module (voir
            `core.journalisation`, filtre des séquences hex longues).

    Returns:
        l'approbation prête à inclure dans `AuthorizationApprovalInput`
    """
    hash_message = construire_hash_ethereum_bank_transfer(champs)
    signe = Account.sign_message(encode_defunct(primitive=hash_message), private_key=cle_privee)
    return ApprobationEthereumBankTransfer(
        signature=signe.signature.hex()
        if signe.signature.hex().startswith("0x")
        else f"0x{signe.signature.hex()}",
        deadline=str(champs["deadline"]),
        salt=champs["salt"],
    )
