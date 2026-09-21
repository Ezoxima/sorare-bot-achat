"""Stockage de la clé privée Ethereum (lot L7) — keyring mocké, aucun vrai secret."""

from __future__ import annotations

import keyring
import pytest
from keyring.backend import KeyringBackend

from acheteur.paiement.cle_ethereum import (
    ClePriveeAbsenteError,
    ClePriveeInvalideError,
    effacer_cle_privee,
    enregistrer_cle_privee,
    lire_cle_privee,
    obtenir_cle_privee_valide,
)

# Vecteur public (déjà utilisé dans test_eth_signature_l7.py) — pas un secret.
_CLE_EXEMPLE = "0xa9405b77d085276e4b6e35cf494e83f0533d4751fc13e2fdceb6229330ef5146"
_ADRESSE_ATTENDUE = "0xB1a1ed82d0C7DC3f3bA7e2b2613328c64e9d9dA3"


class _KeyringMemoire(KeyringBackend):
    """Backend keyring en mémoire, pour ne jamais toucher le vrai coffre Windows en test."""

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


def test_enregistrer_puis_lire_round_trip():
    adresse = enregistrer_cle_privee(_CLE_EXEMPLE)
    assert adresse == _ADRESSE_ATTENDUE
    assert lire_cle_privee() == _CLE_EXEMPLE


def test_lire_sans_avoir_enregistre_renvoie_none():
    assert lire_cle_privee() is None


def test_obtenir_cle_privee_valide_leve_si_absente():
    with pytest.raises(ClePriveeAbsenteError):
        obtenir_cle_privee_valide()


def test_obtenir_cle_privee_valide_renvoie_la_cle():
    enregistrer_cle_privee(_CLE_EXEMPLE)
    assert obtenir_cle_privee_valide() == _CLE_EXEMPLE


def test_cle_invalide_rejetee_et_non_enregistree():
    with pytest.raises(ClePriveeInvalideError):
        enregistrer_cle_privee("pas-une-cle")
    assert lire_cle_privee() is None


def test_effacer_cle_absente_ne_leve_pas():
    effacer_cle_privee()  # ne doit pas lever même si rien n'est enregistré


def test_effacer_cle_presente():
    enregistrer_cle_privee(_CLE_EXEMPLE)
    effacer_cle_privee()
    assert lire_cle_privee() is None
