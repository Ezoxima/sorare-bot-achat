"""Signature `MangopayWalletTransferAuthorizationRequest` (rail EUR, lot L7 suite).

Vecteurs de test : fichier officiel StarkWare
(`starkware-libs/starkex-resources`, `crypto/starkware/crypto/signature/
signature_test_data.json`, récupéré le 2026-09-21) — clés privées et hash
publiés publiquement dans ce fichier de test, pas un secret de ce projet ni
de l'utilisateur.

Le hash Pedersen est vérifié contre deux vecteurs officiels indépendants
(section `hash_test`). La signature est vérifiée par cohérence interne
(sign puis verify) plutôt que par reproduction d'un vecteur externe : le
vecteur `transfer_order` du même fichier ne se re-vérifie pas, y compris
avec l'implémentation Python de référence de StarkWare elle-même
(`cairo-lang`, calculée indépendamment pour comparaison croisée pendant
cette session) — documenté dans `starkex_signature.py`, pas un défaut de
ce module.
"""

from __future__ import annotations

from acheteur.paiement._starkware_crypto.signature import (
    private_key_to_ec_point_on_stark_curve,
    verify,
)
from acheteur.paiement.starkex_signature import (
    _pedersen_hash,
    exporter_cle_publique_starkex,
    hash_mangopay_wallet_transfer,
    signer_autorisation_mangopay_wallet_transfer,
)


class TestPedersenHash:
    def test_vecteur_officiel_1(self):
        a = 0x3D937C035C878245CAF64531A5756109C53068DA139362728FEB561405371CB
        b = 0x208A0A10250E382E1E4BBE2880906C2791BF6275695E02FBBC6AEFF9CD8B31A
        attendu = 0x30E480BED5FE53FA909CC0F8C4D99B8F9F2C016BE4C41E13A4848797979C662
        assert _pedersen_hash(a, b) == attendu

    def test_vecteur_officiel_2(self):
        a = 0x58F580910A6CA59B28927C08FE6C43E2E303CA384BADC365795FC645D479D45
        b = 0x78734F65A067BE9BDB39DE18434D71E79F7B6466A4B66BBD979AB9E7515FE0B
        attendu = 0x68CC0B76CDDD1DD4ED2301ADA9B7C872B23875D5FF837B3A87993E0D9996B87
        assert _pedersen_hash(a, b) == attendu


# Clé StarkEx du vecteur officiel `transfer_order` (publique, voir docstring).
_CLE_PRIVEE_EXEMPLE = "0x7cc2767a160d4ea112b436dc6f79024db70b26b11ed7aa2cb6d7eef19ace703"
_CLE_PUBLIQUE_ATTENDUE = "0x59a543d42bcc9475917247fa7f136298bb385a6388c3df7309955fcb39b8dd4"

_CHAMPS_EXEMPLE = {
    "mangopayWalletId": "wallet-1",
    "operationHash": "0xabc123",
    "currency": "EUR",
    "amount": 1000,
    "nonce": 42,
}


class TestSignerAutorisationMangopayWalletTransfer:
    def test_cle_publique_dérivée_correctement(self):
        """Non-régression sur l'utilisation de crypto-cpp-py : la dérivation
        de clé publique doit être correcte pour que la signature qui suit
        ait un sens (vérifié contre la clé publique du vecteur officiel
        `transfer_order`, dérivée indépendamment de sa propre signature)."""
        assert exporter_cle_publique_starkex(_CLE_PRIVEE_EXEMPLE) == _CLE_PUBLIQUE_ATTENDUE

    def test_signature_auto_verifiable(self):
        """La signature produite doit être valide pour le hash et la clé
        publique correspondants."""
        approbation = signer_autorisation_mangopay_wallet_transfer(
            _CHAMPS_EXEMPLE, _CLE_PRIVEE_EXEMPLE
        )
        hash_msg = hash_mangopay_wallet_transfer(_CHAMPS_EXEMPLE)
        priv = int(_CLE_PRIVEE_EXEMPLE, 16)
        point = private_key_to_ec_point_on_stark_curve(priv)
        r = int(approbation.signature_r, 16)
        s = int(approbation.signature_s, 16)
        assert verify(hash_msg, r, s, point)

    def test_nonce_repris_tel_quel(self):
        approbation = signer_autorisation_mangopay_wallet_transfer(
            _CHAMPS_EXEMPLE, _CLE_PRIVEE_EXEMPLE
        )
        assert approbation.nonce == 42

    def test_deux_champs_differents_donnent_des_hash_differents(self):
        h1 = hash_mangopay_wallet_transfer(_CHAMPS_EXEMPLE)
        h2 = hash_mangopay_wallet_transfer({**_CHAMPS_EXEMPLE, "amount": 1001})
        assert h1 != h2
