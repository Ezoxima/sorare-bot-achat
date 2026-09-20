"""Télécharge le SDL GraphQL Sorare (source de vérité des champs).

L'introspection `{ __schema }` est désactivée côté Sorare, mais le SDL complet
est servi en clair sur `/graphql/schema`. On le garde en local (gitignoré,
sous `schema/`) pour pouvoir grep les champs hors-ligne. Le schéma évolue :
re-lancer périodiquement.

Usage (depuis la racine du dépôt) : python scripts/rafraichir_schema.py
"""

import pathlib

import httpx

from acheteur.core.config import get_settings

SCHEMA_URL = "https://api.sorare.com/graphql/schema"
SORTIE = pathlib.Path(__file__).resolve().parent.parent / "schema" / "sorare_schema.graphql"


def main() -> None:
    settings = get_settings()
    headers = {"APIKEY": settings.sorare_api_key} if settings.sorare_api_key else {}
    resp = httpx.get(SCHEMA_URL, headers=headers, timeout=60.0)
    resp.raise_for_status()
    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(resp.text, encoding="utf-8")
    print(f"SDL écrit : {SORTIE} ({resp.text.count(chr(10)) + 1} lignes)")


if __name__ == "__main__":
    main()
