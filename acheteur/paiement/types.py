"""Types pour la préparation et la signature des offres (L5+)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, StrEnum
from typing import Any


class AuthorizationType(StrEnum):
    """Type de signature demandée par Sorare.

    Valeurs corrigées le 2026-09-21 (lot L7, voir DECISIONS.md/MESURES.md) :
    toutes portaient un nom de type erroné (il manquait « Authorization »
    au milieu — ex. `EthereumBankTransferRequest` au lieu du vrai
    `EthereumBankTransferAuthorizationRequest`, confirmé contre
    `schema/sorare_schema.graphql`). Conséquence concrète du bug : TOUTE
    autorisation réellement demandée par Sorare tombait dans
    `except ValueError: NONE` (voir `preparation._parser_reponse_prepare_offer`)
    — jamais détectée jusqu'au premier vrai `prepareOffer` avec des
    paramètres valides de cette session (les sondes L1 n'avaient rien
    demandé du tout, donc n'auraient pas pu révéler ce bug).
    """

    ETHEREUM_BANK_TRANSFER = "EthereumBankTransferAuthorizationRequest"
    ETHEREUM_BANK_CONDITIONAL = "EthereumBankConditionalTransferAuthorizationRequest"
    SOLANA_BANK_TRANSFER = "SolanaBankTransferAuthorizationRequest"
    SOLANA_BANK_CONDITIONAL = "SolanaBankConditionalTransferAuthorizationRequest"
    SOLANA_TOKEN_TRANSFER = "SolanaTokenTransferAuthorizationRequest"
    STARKEX_LIMIT_ORDER = "StarkexLimitOrderAuthorizationRequest"
    STARKEX_TRANSFER = "StarkexTransferAuthorizationRequest"
    MANGOPAY_WALLET = "MangopayWalletTransferAuthorizationRequest"
    MANGOPAY_APPLE_PAY = "MangopayApplePayAuthorizationRequest"
    NONE = "NONE"


@dataclass(frozen=True)
class AuthorizationRequest:
    """Une autorisation demandée par Sorare avant d'envoyer l'offre.

    Attributes:
        id: identifiant de la demande
        fingerprint: empreinte à transmettre lors de la signature
        request_type: type de signature (AuthorizationType)
        status: état (pending, approved, etc.)
        champs: les champs propres au type concret de la requête (ex.
            `contractAddress`, `senderAddress`, `amount`... pour
            `EthereumBankTransferAuthorizationRequest`) — nécessaires pour
            construire le message à signer, mais dont la forme dépend du
            type. Vide si le type n'est pas géré par la requête GraphQL
            (`mutations.PREPARE_OFFER_MUTATION` ne demande ces champs que
            pour les types que ce projet sait signer).
    """

    id: str
    fingerprint: str
    request_type: AuthorizationType
    status: str
    champs: dict[str, Any] = field(default_factory=dict)


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
