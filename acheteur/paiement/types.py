"""Types pour la préparation et la signature des offres (L5+)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, StrEnum
from typing import Any


class AuthorizationType(StrEnum):
    """Type de signature demandée par Sorare."""

    ETHEREUM_BANK_TRANSFER = "EthereumBankTransferRequest"
    ETHEREUM_BANK_CONDITIONAL = "EthereumBankConditionalTransferRequest"
    SOLANA_BANK_TRANSFER = "SolanaBankTransferRequest"
    SOLANA_BANK_CONDITIONAL = "SolanaBankConditionalTransferRequest"
    SOLANA_TOKEN_TRANSFER = "SolanaTokenTransferRequest"
    STARKEX_LIMIT_ORDER = "StarkexLimitOrderRequest"
    STARKEX_TRANSFER = "StarkexTransferRequest"
    MANGOPAY_WALLET = "MangopayWalletTransferRequest"
    MANGOPAY_APPLE_PAY = "MangopayApplePayRequest"
    NONE = "NONE"


@dataclass(frozen=True)
class AuthorizationRequest:
    """Une autorisation demandée par Sorare avant d'envoyer l'offre.

    Attributes:
        id: identifiant de la demande
        fingerprint: empreinte à transmettre lors de la signature
        request_type: type de signature (AuthorizationType)
        status: état (pending, approved, etc.)
    """

    id: str
    fingerprint: str
    request_type: AuthorizationType
    status: str


@dataclass(frozen=True)
class PreparedOffer:
    """Résultat de prepareOffer : l'offre prête à signer/envoyer.

    Attributes:
        input_data: les paramètres originaux de prepareOffer
        authorizations: liste des demandes de signature
        errors: erreurs GraphQL renvoyées par Sorare
    """

    input_data: dict[str, Any]
    authorizations: list[AuthorizationRequest]
    errors: list[dict[str, Any]]

    @property
    def a_besoin_signature(self) -> bool:
        """Vrai si au moins une autorisation a été demandée."""
        return len(self.authorizations) > 0
