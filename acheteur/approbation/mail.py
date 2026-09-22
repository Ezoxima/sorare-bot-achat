"""Envoi du mail d'approbation (PLAN.md § « Le mode propose, tu valides ») :
« Le mail reprend le format de tes alertes actuelles ». Optionnel — le
fichier de propositions (`acheteur.approbation.fichier_propositions`) reste
la source de vérité relue par `cli/approuver_propositions.py` ; le mail n'est
qu'une notification pour ne pas avoir à surveiller le dossier.

Le mot de passe SMTP n'est jamais journalisé : en cas d'échec, seuls
host/port (non sensibles) apparaissent dans le log, jamais l'exception brute
du serveur (qui pourrait, sur un serveur mal configuré, échoter des
identifiants).
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from acheteur.core.config import get_settings

logger = logging.getLogger(__name__)


class MailNonConfigureError(Exception):
    """smtp_host ou smtp_destinataire absents de la configuration."""


def mail_configure() -> bool:
    s = get_settings()
    return bool(s.smtp_host and s.smtp_destinataire)


def envoyer_mail_propositions(sujet: str, corps: str) -> None:
    """Envoie `corps` (texte brut) au destinataire configuré.

    Raises:
        MailNonConfigureError: si smtp_host/smtp_destinataire ne sont pas
            renseignés dans .env — l'appelant décide s'il s'agit d'une
            erreur bloquante ou d'un simple avertissement (le fichier de
            propositions, lui, est toujours écrit avant cet appel).
    """
    s = get_settings()
    if not mail_configure():
        raise MailNonConfigureError(
            "SMTP non configuré (ACHETEUR_SMTP_HOST / ACHETEUR_SMTP_DESTINATAIRE "
            "absents de .env) — mail non envoyé."
        )

    message = EmailMessage()
    message["Subject"] = sujet
    message["From"] = s.smtp_expediteur or s.smtp_user or s.smtp_destinataire
    message["To"] = s.smtp_destinataire
    message.set_content(corps)

    try:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30) as serveur:
            if s.smtp_use_tls:
                serveur.starttls()
            if s.smtp_user:
                serveur.login(s.smtp_user, s.smtp_password)
            serveur.send_message(message)
    except Exception as exc:
        logger.error(
            "Échec envoi mail (host=%s, port=%s) : %s", s.smtp_host, s.smtp_port, type(exc).__name__
        )
        raise
