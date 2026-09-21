"""Signature et envoi d'une offre (L5+).

L1 avait montré que prepareOffer ne demandait pas d'autorisation sur ses
sondes (paramètres invalides) — hypothèse infirmée en L7 (2026-09-21, voir
DECISIONS.md/MESURES.md) : une offre réelle payée en ETH demande une
`EthereumBankTransferAuthorizationRequest`, une offre payée en EUR une
`MangopayWalletTransferAuthorizationRequest` (rail StarkEx). Ce module route
vers `acheteur.paiement.eth_signature` ou `acheteur.paiement.starkex_signature`
selon le type ; chacun utilise sa propre clé (compte Ethereum vs compte
Starkware — deux comptes distincts, voir DECISIONS.md). Tout autre type
d'autorisation fait échouer l'envoi explicitement plutôt que de tenter un
envoi avec des `approvals` vides.
"""

from __future__ import annotations

import logging
import secrets
from typing import Any

from acheteur.paiement.cle_ethereum import obtenir_cle_privee_valide as obtenir_cle_eth
from acheteur.paiement.cle_starkex import obtenir_cle_privee_valide as obtenir_cle_starkex
from acheteur.paiement.eth_signature import signer_autorisation_ethereum_bank_transfer
from acheteur.paiement.starkex_signature import signer_autorisation_mangopay_wallet_transfer
from acheteur.paiement.types import AuthorizationRequest, AuthorizationType, PreparedOffer
from acheteur.sorare.client import SorareClient
from acheteur.sorare.mutations import creer_offre_directe_sorare

logger = logging.getLogger(__name__)


class SignatureNonSupporteeError(RuntimeError):
    """Sorare demande un type d'autorisation qu'on ne sait pas signer en Python
    (voir DECISIONS.md). Lever plutôt qu'envoyer des `approvals` vides qui
    échoueraient de toute façon côté Sorare."""


def _signer_une_autorisation(auth: AuthorizationRequest) -> dict[str, Any]:
    if auth.request_type == AuthorizationType.ETHEREUM_BANK_TRANSFER:
        cle_privee = obtenir_cle_eth()
        approbation = signer_autorisation_ethereum_bank_transfer(auth.champs, cle_privee)
        return {
            "fingerprint": auth.fingerprint,
            "ethereumBankTransferApproval": {
                "deadline": approbation.deadline,
                "salt": approbation.salt,
                "signature": approbation.signature,
            },
        }
    if auth.request_type == AuthorizationType.MANGOPAY_WALLET:
        cle_privee = obtenir_cle_starkex()
        approbation = signer_autorisation_mangopay_wallet_transfer(auth.champs, cle_privee)
        return {
            "fingerprint": auth.fingerprint,
            "mangopayWalletTransferApproval": {
                "nonce": approbation.nonce,
                "signature": {"r": approbation.signature_r, "s": approbation.signature_s},
            },
        }
    raise SignatureNonSupporteeError(
        f"Type d'autorisation non géré par ce projet : {auth.request_type.value} "
        "(seuls EthereumBankTransferAuthorizationRequest et "
        "MangopayWalletTransferAuthorizationRequest sont signables, voir DECISIONS.md)."
    )


def _construire_approbations(prepared: PreparedOffer) -> list[dict[str, Any]]:
    return [_signer_une_autorisation(auth) for auth in prepared.authorizations]


def _generer_deal_id() -> str:
    """`createDirectOfferInput.dealId` est un `String!` obligatoire —
    identifiant unique de la transaction, PAS renvoyé par `prepareOffer`
    (schema/sorare_schema.graphql:35422 : « Consider using
    `crypto.getRandomValues(new Uint32Array(4)).join()` » côté JS).
    Équivalent Python : jeton hexadécimal aléatoire, assez long pour ne
    jamais collisionner en pratique."""
    return secrets.token_hex(16)


def _construire_input_create_direct_offer(prepared: PreparedOffer, approvals: list) -> dict[str, Any]:
    """Construit `createDirectOfferInput` à partir de `PreparedOffer`.

    Bug réel trouvé en conditions réelles (lot L7, premier envoi réel
    déclenché par l'utilisateur, 2026-09-21, voir MESURES.md) :
    `envoyer_offre_signee` réutilisait tel quel `prepared.input_data`, qui
    est construit pour `prepareOfferInput` (`preparation.py`) — un type
    d'input **différent**. `createDirectOfferInput` n'a pas de champ
    `settlementCurrencies` (erreur GraphQL réelle : « Field is not defined
    on createDirectOfferInput ») et exige un `dealId` que `prepareOfferInput`
    n'a pas et que `prepareOffer` ne renvoie pas. On ne peut donc pas
    réutiliser l'input tel quel : on ne reprend que les champs communs aux
    deux types (`clientMutationId`, `receiveAmount`, `receiveAssetIds`,
    `receiverSlug`, `sendAmount`, `sendAssetIds`) et on ajoute `dealId` et
    `approvals`, propres à `createDirectOfferInput`.
    """
    return {
        "clientMutationId": prepared.input_data.get("clientMutationId"),
        "dealId": _generer_deal_id(),
        "receiveAmount": prepared.input_data.get("receiveAmount"),
        "receiveAssetIds": prepared.input_data.get("receiveAssetIds"),
        "receiverSlug": prepared.input_data.get("receiverSlug"),
        "sendAmount": prepared.input_data.get("sendAmount"),
        "sendAssetIds": prepared.input_data.get("sendAssetIds"),
        "approvals": approvals,
    }


def envoyer_offre_signee(
    client: SorareClient,
    prepared: PreparedOffer,
) -> dict[str, Any]:
    """Envoie une offre signée (ou non signée si pas d'autorisation demandée).

    L5 : pas de signature réelle — approvals vide.
    L6 : implémenter la vraie signature si nécessaire.

    Args:
        client: client GraphQL Sorare
        prepared: offre préparée (résultat de prepareOffer)

    Returns:
        réponse de createDirectOffer

    Raises:
        ClePriveeAbsenteError: autorisation demandée mais aucune clé
            enregistrée pour ce rail (voir `acheteur.cli.enregistrer_cle_ethereum`
            ou `acheteur.cli.enregistrer_cle_starkex`)
        SignatureNonSupporteeError: type d'autorisation qu'on ne sait pas
            signer en Python
        Peut aussi lever des exceptions réseau (comme prepare_offre)
    """
    if prepared.a_besoin_signature:
        logger.info(
            "Autorisation(s) demandée(s) : %s",
            [a.request_type.value for a in prepared.authorizations],
        )
        approvals = _construire_approbations(prepared)
    else:
        approvals = []

    create_input = _construire_input_create_direct_offer(prepared, approvals)

    logger.debug("Appel createDirectOffer...")
    return creer_offre_directe_sorare(client, create_input)
