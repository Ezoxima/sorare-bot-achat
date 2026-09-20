import logging

from acheteur.core.journalisation import MasqueSecretsFilter


def _filtrer(msg: str, *args: object) -> str:
    record = logging.LogRecord("test", logging.INFO, __file__, 1, msg, args, None)
    MasqueSecretsFilter().filter(record)
    return record.getMessage()


def test_masque_un_jwt() -> None:
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dQw4w9WgXcQ_abcdefghij"
    resultat = _filtrer("jeton reçu : %s", jwt)
    assert jwt not in resultat
    assert "[JWT masqué]" in resultat


def test_masque_une_cle_hex_longue() -> None:
    cle = "0x" + "a" * 64
    resultat = _filtrer(f"clé : {cle}")
    assert cle not in resultat
    assert "[hex masqué]" in resultat


def test_masque_un_bearer() -> None:
    resultat = _filtrer("Authorization: Bearer abcdefghijklmnopqrstuvwxyz")
    assert "abcdefghijklmnopqrstuvwxyz" not in resultat
    assert "[jeton masqué]" in resultat


def test_laisse_un_message_normal_intact() -> None:
    assert _filtrer("scan terminé, 3 offres trouvées") == "scan terminé, 3 offres trouvées"
