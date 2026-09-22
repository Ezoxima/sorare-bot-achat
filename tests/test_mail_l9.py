"""`acheteur.approbation.mail` — vérifie seulement la détection de
configuration et le refus explicite quand SMTP n'est pas configuré. Aucun
test n'ouvre de vraie connexion SMTP (pas de réseau dans les tests)."""

from __future__ import annotations

import pytest

from acheteur.approbation.mail import (
    MailNonConfigureError,
    envoyer_mail_propositions,
    mail_configure,
)
from acheteur.core.config import get_settings


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class TestMailConfigure:
    def test_faux_si_host_absent(self, monkeypatch):
        monkeypatch.setenv("SMTP_HOST", "")
        monkeypatch.setenv("SMTP_DESTINATAIRE", "moi@example.com")
        assert mail_configure() is False

    def test_faux_si_destinataire_absent(self, monkeypatch):
        monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("SMTP_DESTINATAIRE", "")
        assert mail_configure() is False

    def test_vrai_si_les_deux_presents(self, monkeypatch):
        monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("SMTP_DESTINATAIRE", "moi@example.com")
        assert mail_configure() is True


class TestEnvoyerMailPropositionsNonConfigure:
    def test_leve_sans_tenter_de_connexion(self, monkeypatch):
        monkeypatch.setenv("SMTP_HOST", "")
        monkeypatch.setenv("SMTP_DESTINATAIRE", "")
        with pytest.raises(MailNonConfigureError):
            envoyer_mail_propositions("sujet", "corps")
