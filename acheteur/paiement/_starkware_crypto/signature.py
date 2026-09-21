"""Signature ECDSA sur la courbe STARK + hash Pedersen — adapté de
`starkware-libs/cairo-lang`, `src/starkware/crypto/signature/signature.py`
(Apache 2.0, voir `LICENSE` dans ce dossier).

Coupé par rapport à l'original : `get_y_coordinate`/`is_valid_stark_key`/
`get_random_private_key` retirés (inutiles ici : ce projet ne dérive ni ne
valide jamais une clé x-seule, il reçoit une clé privée complète de
l'appelant — voir `paiement.cle_starkex`). `verify()` prend le point complet
(x, y) plutôt que la seule abscisse — on l'a toujours sous la main via
`private_key_to_ec_point_on_stark_curve`, pas besoin de racine carrée modulaire.

Vérifié dans cette session contre les vecteurs de test publics de StarkWare
(`starkware-libs/starkex-resources`, `signature_test_data.json`) et par
comparaison croisée avec les bindings C++ `crypto-cpp-py` (mêmes résultats
bit à bit) — voir `tests/test_starkex_signature_l7.py` et DECISIONS.md
(2026-09-21, « Rail EUR »). Ce module en pur Python remplace `crypto-cpp-py`
suite à un échec de chargement de sa DLL (dépendance MinGW non résolue) sur
la machine de l'utilisateur, non reproductible de façon fiable — éliminer
toute dépendance native est plus sûr qu'un correctif d'environnement sur un
module qui déplace de l'argent réel.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Optional

from ecdsa.rfc6979 import generate_k

from acheteur.paiement._starkware_crypto.math_utils import ECPoint, div_mod, ec_add, ec_double, ec_mult

_PARAMS_PATH = Path(__file__).parent / "pedersen_params.json"
_PARAMS = json.loads(_PARAMS_PATH.read_text())

FIELD_PRIME = _PARAMS["FIELD_PRIME"]
ALPHA = _PARAMS["ALPHA"]
BETA = _PARAMS["BETA"]
EC_ORDER = _PARAMS["EC_ORDER"]
CONSTANT_POINTS = _PARAMS["CONSTANT_POINTS"]

N_ELEMENT_BITS_ECDSA = math.floor(math.log(FIELD_PRIME, 2))
assert N_ELEMENT_BITS_ECDSA == 251

N_ELEMENT_BITS_HASH = FIELD_PRIME.bit_length()
assert N_ELEMENT_BITS_HASH == 252

assert 2**N_ELEMENT_BITS_ECDSA < EC_ORDER < FIELD_PRIME

SHIFT_POINT = CONSTANT_POINTS[0]
MINUS_SHIFT_POINT = (SHIFT_POINT[0], FIELD_PRIME - SHIFT_POINT[1])
EC_GEN = CONSTANT_POINTS[1]

assert SHIFT_POINT == [
    0x49EE3EBA8C1600700EE1B87EB599F16716B0B1022947733551FDE4050CA6804,
    0x3CA0CFE4B3BC6DDF346D49D06EA0ED34E621062C0E056C1D0405D266E10268A,
]
assert EC_GEN == [
    0x1EF15C18599971B7BECED415A40F0C7DEACFD9B0D1819E03D723D8BC943CFCA,
    0x5668060AA49730B7BE4801DF46EC62DE53ECD11ABE43A32873000C36E8DC1F,
]

ECSignature = tuple[int, int]


def private_key_to_ec_point_on_stark_curve(priv_key: int) -> ECPoint:
    assert 0 < priv_key < EC_ORDER
    return ec_mult(priv_key, EC_GEN, ALPHA, FIELD_PRIME)


def private_to_stark_key(priv_key: int) -> int:
    return private_key_to_ec_point_on_stark_curve(priv_key)[0]


def inv_mod_curve_size(x: int) -> int:
    return div_mod(1, x, EC_ORDER)


def generate_k_rfc6979(msg_hash: int, priv_key: int, seed: Optional[int] = None) -> int:
    # Bourrage du hash pour cohérence avec la bibliothèque JS `elliptic.js`.
    if 1 <= msg_hash.bit_length() % 8 <= 4 and msg_hash.bit_length() >= 248:
        msg_hash *= 16

    if seed is None:
        extra_entropy = b""
    else:
        extra_entropy = seed.to_bytes(math.ceil(seed.bit_length() / 8), "big")

    return generate_k(
        EC_ORDER,
        priv_key,
        hashlib.sha256,
        msg_hash.to_bytes(math.ceil(msg_hash.bit_length() / 8), "big"),
        extra_entropy=extra_entropy,
    )


def sign(msg_hash: int, priv_key: int, seed: Optional[int] = None) -> ECSignature:
    assert 0 <= msg_hash < 2**N_ELEMENT_BITS_ECDSA, "Message not signable."

    while True:
        k = generate_k_rfc6979(msg_hash, priv_key, seed)
        if seed is None:
            seed = 1
        else:
            seed += 1

        x = ec_mult(k, EC_GEN, ALPHA, FIELD_PRIME)[0]

        r = int(x)
        if not (1 <= r < 2**N_ELEMENT_BITS_ECDSA):
            continue

        if (msg_hash + r * priv_key) % EC_ORDER == 0:
            continue

        w = div_mod(k, msg_hash + r * priv_key, EC_ORDER)
        if not (1 <= w < 2**N_ELEMENT_BITS_ECDSA):
            continue

        s = inv_mod_curve_size(w)
        return r, s


def _mimic_ec_mult_air(m: int, point: ECPoint, shift_point: ECPoint) -> ECPoint:
    assert 0 < m < 2**N_ELEMENT_BITS_ECDSA
    partial_sum = shift_point
    for _ in range(N_ELEMENT_BITS_ECDSA):
        assert partial_sum[0] != point[0]
        if m & 1:
            partial_sum = ec_add(partial_sum, point, FIELD_PRIME)
        point = ec_double(point, ALPHA, FIELD_PRIME)
        m >>= 1
    assert m == 0
    return partial_sum


def verify(msg_hash: int, r: int, s: int, public_key_point: ECPoint) -> bool:
    """Vérifie une signature contre le POINT complet (x, y) de la clé
    publique (pas seulement son abscisse — pas besoin de racine carrée
    modulaire ici, contrairement à l'original StarkWare)."""
    assert 1 <= s < EC_ORDER, "s = %s" % s
    w = inv_mod_curve_size(s)

    assert 1 <= r < 2**N_ELEMENT_BITS_ECDSA, "r = %s" % r
    assert 1 <= w < 2**N_ELEMENT_BITS_ECDSA, "w = %s" % w
    assert 0 <= msg_hash < 2**N_ELEMENT_BITS_ECDSA, "msg_hash = %s" % msg_hash

    try:
        zG = _mimic_ec_mult_air(msg_hash, EC_GEN, MINUS_SHIFT_POINT)
        rQ = _mimic_ec_mult_air(r, public_key_point, SHIFT_POINT)
        wB = _mimic_ec_mult_air(w, ec_add(zG, rQ, FIELD_PRIME), SHIFT_POINT)
        x = ec_add(wB, MINUS_SHIFT_POINT, FIELD_PRIME)[0]
    except AssertionError:
        return False

    return r == x


def pedersen_hash(*elements: int) -> int:
    return pedersen_hash_as_point(*elements)[0]


def pedersen_hash_as_point(*elements: int) -> ECPoint:
    point = SHIFT_POINT
    for i, x in enumerate(elements):
        assert 0 <= x < FIELD_PRIME
        point_list = CONSTANT_POINTS[2 + i * N_ELEMENT_BITS_HASH : 2 + (i + 1) * N_ELEMENT_BITS_HASH]
        assert len(point_list) == N_ELEMENT_BITS_HASH
        for pt in point_list:
            assert point[0] != pt[0], "Unhashable input."
            if x & 1:
                point = ec_add(point, pt, FIELD_PRIME)
            x >>= 1
        assert x == 0
    return point
