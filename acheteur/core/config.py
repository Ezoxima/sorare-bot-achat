"""Configuration via pydantic-settings.

Tous les champs ont un défaut sûr pour que l'import fonctionne sans `.env`
(tests). Le JWT ne figure PAS ici : il vit dans le gestionnaire d'identifiants
Windows (voir `acheteur.auth.jeton`), jamais dans un fichier.

`mode_simulation` par défaut à `True` n'est qu'un filet : le vrai verrou du
mode réel est en ligne de commande (D9, trois verrous), jamais dans `.env`
seul.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

NOM_SERVICE_JETON = "acheteur-sorare"
NOM_SERVICE_CLE_ETH = "acheteur-eth-cle-privee"
NOM_SERVICE_CLE_STARKEX = "acheteur-starkex-cle-privee"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(
        default="sqlite:///./acheteur.db",
        description="URL SQLAlchemy de la base locale.",
    )

    sorare_api_key: str = Field(
        default="",
        description="Clé API Sorare — couvre les données publiques.",
    )
    sorare_jwt_aud: str = Field(
        default="acheteur",
        description="Audience du JWT (header JWT-AUD).",
    )

    mode_simulation: bool = Field(
        default=True,
        description="Filet de sécurité seulement — le mode réel se déverrouille en CLI.",
    )


@lru_cache
def get_settings() -> Settings:
    """Retourne l'instance unique des settings (mise en cache)."""
    return Settings()
