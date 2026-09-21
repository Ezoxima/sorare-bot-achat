"""Signature d'une autorisation `MangopayWalletTransferAuthorizationRequest`
(rail EUR, lot L7 suite — voir DECISIONS.md 2026-09-21 « Rail EUR »).

Contrairement à l'hypothèse initiale de PLAN.md (« Node.js obligatoire »),
la signature StarkEx n'est pas un algorithme propriétaire Sorare : c'est de
la cryptographie StarkWare publique (Apache 2.0) — un hash Pedersen sur la
courbe STARK, puis une signature ECDSA sur cette même courbe. La recette
exacte pour ce rail précis vient de la lecture du code source publié de
`@sorare/crypto` (npm, package public) :

    message = f"{mangopayWalletId}:{operationHash}:{currency}:{amount}:{nonce}"
    h = sha256(message).hexdigest()               # 64 caractères hex
    hash_msg = pedersen_hash(int(h[:32], 16), int(h[32:], 16))
    r, s = stark_sign(hash_msg, cle_privee_starkex)

Le hash Pedersen et la signature utilisent `acheteur.paiement._starkware_crypto`
— une version allégée, en pur Python, de l'implémentation de référence
StarkWare (`starkware-libs/cairo-lang`, Apache 2.0, voir la licence dans ce
sous-dossier). **Choix fait après un premier essai avec `crypto-cpp-py`**
(bindings C++) : sa DLL (compilée avec MinGW) dépendait de runtimes
(`libgcc_s_seh-1.dll`, `libstdc++-6.dll`) absents par défaut sur Windows, et
son chargement échouait de façon non reproductible sur la machine de
l'utilisateur (marchait dans certains terminaux, pas dans d'autres) —
diagnostiqué comme un problème d'environnement (PATH/antivirus), pas de
code, mais **une dépendance native dont le chargement peut échouer
silencieusement selon l'environnement n'est pas acceptable sur un module qui
déplace de l'argent réel** (CLAUDE.md). Éliminée au profit du pur Python.

**Vérifié** (voir `tests/test_starkex_signature_l7.py`) :
- le hash Pedersen reproduit exactement deux vecteurs de test publics
  StarkWare (`starkware-libs/starkex-resources`, fichier
  `signature_test_data.json`, section `hash_test`) ;
- la signature est cohérente en interne (sign puis verify) ;
- **comparaison croisée bit à bit avec `crypto-cpp-py`** (avant de le
  retirer) : hash Pedersen et signature (r, s) identiques sur le même
  vecteur — confirme que le portage pur Python n'a introduit aucune
  divergence ;
- le vecteur de signature publié dans `signature_test_data.json` lui-même
  ne se re-vérifie pas (même avec l'implémentation de référence StarkWare
  originale, testée séparément) — probablement un fixture obsolète, pas un
  défaut de notre code, documenté ici pour que quiconque retombe dessus ne
  perde pas de temps à chercher un bug côté `acheteur`.

**Aucune clé privée réelle n'est manipulée par ce module lui-même** : il ne
fait que signer étant donné une clé passée par l'appelant (la clé du
« compte Starkware », distincte de la clé Ethereum du rail ETH — voir
`acheteur.paiement.cle_ethereum` pour cette dernière). D'où et comment
cette clé StarkEx est obtenue et stockée est une décision séparée,
symétrique à celle prise pour la clé ETH (CLAUDE.md § Secrets).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from acheteur.paiement._starkware_crypto.signature import (
    pedersen_hash,
    private_to_stark_key,
    sign,
)


@dataclass(frozen=True)
class ApprobationMangopayWalletTransfer:
    """Ce qu'il faut renvoyer dans
    `AuthorizationApprovalInput.mangopayWalletTransferApproval`."""

    nonce: int
    signature_r: str
    signature_s: str


def _pedersen_hash(a: int, b: int) -> int:
    return pedersen_hash(a, b)


def hash_message(message: str) -> int:
    """Hash StarkEx d'une chaîne de caractères : sha256 puis Pedersen sur les
    deux moitiés de 16 octets du condensé — reproduit `hashMessage` de
    `@sorare/crypto`."""
    condense_hex = hashlib.sha256(message.encode("utf-8")).hexdigest()
    moitie_gauche = int(condense_hex[:32], 16)
    moitie_droite = int(condense_hex[32:], 16)
    return _pedersen_hash(moitie_gauche, moitie_droite)


def hash_mangopay_wallet_transfer(champs: dict[str, Any]) -> int:
    """Reconstruit le hash à signer pour une
    `MangopayWalletTransferAuthorizationRequest`.

    Args:
        champs: les champs de la requête tels que renvoyés par `prepareOffer`
            — `mangopayWalletId`, `operationHash`, `currency`, `amount`,
            `nonce` (voir `paiement.types.AuthorizationRequest.champs`).
    """
    message = ":".join(
        str(champs[cle])
        for cle in ("mangopayWalletId", "operationHash", "currency", "amount", "nonce")
    )
    return hash_message(message)


def signer_autorisation_mangopay_wallet_transfer(
    champs: dict[str, Any],
    cle_privee_starkex: str,
) -> ApprobationMangopayWalletTransfer:
    """Signe une `MangopayWalletTransferAuthorizationRequest`.

    Args:
        champs: voir `hash_mangopay_wallet_transfer`
        cle_privee_starkex: clé privée StarkEx (compte Starkware, distinct
            du compte Ethereum) — un entier encodé en hex (avec ou sans
            `0x`), jamais journalisée.

    Returns:
        l'approbation prête à inclure dans `AuthorizationApprovalInput`
    """
    hash_msg = hash_mangopay_wallet_transfer(champs)
    priv = int(cle_privee_starkex, 16)
    r, s = sign(hash_msg, priv)
    return ApprobationMangopayWalletTransfer(
        nonce=int(champs["nonce"]),
        signature_r=f"0x{r:x}",
        signature_s=f"0x{s:x}",
    )


def exporter_cle_publique_starkex(cle_privee_starkex: str) -> str:
    """Dérive la clé publique — sert à faire confirmer le bon compte à
    l'utilisateur sans jamais afficher la clé privée elle-même."""
    priv = int(cle_privee_starkex, 16)
    return f"0x{private_to_stark_key(priv):x}"
