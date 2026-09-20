"""Client GraphQL Sorare.

Porté de `sorare_app_v2` (Pickdeck) quasi à l'identique — seule la source des
settings change. Encapsule le transport HTTP, les retries/backoff et un
throttle proactif.

Auth : la clé API (header `APIKEY`) couvre toutes les données publiques.
Le JWT (`Authorization: Bearer` + `JWT-AUD`) débloque `currentUser`.

Rate-limit (constaté sur l'API) : aucune en-tête de quota restant n'est
renvoyée ; seul un 429 + `Retry-After` signale le dépassement. Le coût de
chaque requête est exposé via `x-gql-complexity`. La stratégie est donc :
espacement proactif (`min_interval`) + respect de `Retry-After` sur 429.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import httpx

from acheteur.core.config import get_settings

logger = logging.getLogger(__name__)

SORARE_GRAPHQL_URL = "https://api.sorare.com/graphql"

# Statuts pour lesquels un nouvel essai a du sens (transitoires / rate-limit).
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class SorareError(RuntimeError):
    """Erreur transport (HTTP) ou GraphQL renvoyée par l'API Sorare."""


class SorareClient:
    """Client GraphQL pour l'API Sorare.

    Par défaut, s'authentifie via la clé API lue dans la config (`.env`).
    `transport`, `sleep` et `monotonic` sont injectables pour tester sans
    réseau ni délai réel.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        jwt: str | None = None,
        jwt_aud: str | None = None,
        url: str = SORARE_GRAPHQL_URL,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        min_interval: float = 0.0,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        settings = get_settings()
        self._api_key = api_key if api_key is not None else settings.sorare_api_key
        # JWT : requis pour les requêtes `currentUser`. `Authorization: Bearer <jwt>`
        # doit être accompagné de `JWT-AUD` == `aud` du token.
        self._jwt = jwt if jwt is not None else ""
        self._jwt_aud = jwt_aud if jwt_aud is not None else settings.sorare_jwt_aud
        self._url = url
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": "acheteur/0.1"},
            transport=transport,
        )
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._min_interval = min_interval
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request_at: float | None = None
        # Dernières en-têtes de réponse (rate-limit / coût) — exploitées par le throttle.
        self.last_headers: httpx.Headers | None = None

    @property
    def has_api_key(self) -> bool:
        return bool(self._api_key)

    @property
    def has_jwt(self) -> bool:
        """Vrai si un JWT *et* son audience sont présents (les deux sont requis)."""
        return bool(self._jwt and self._jwt_aud)

    def _auth_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["APIKEY"] = self._api_key
        # JWT en plus de la clé API : la clé couvre le public, le JWT débloque
        # `currentUser`. `JWT-AUD` sans token (ou l'inverse) est inutile.
        if self._jwt and self._jwt_aud:
            headers["Authorization"] = f"Bearer {self._jwt}"
            headers["JWT-AUD"] = self._jwt_aud
        return headers

    def _throttle(self) -> None:
        """Espacement proactif entre requêtes, si `min_interval` > 0."""
        if self._min_interval > 0 and self._last_request_at is not None:
            wait = self._min_interval - (self._monotonic() - self._last_request_at)
            if wait > 0:
                self._sleep(wait)
        self._last_request_at = self._monotonic()

    def _backoff(self, attempt: int) -> float:
        """Backoff exponentiel : base * 2**attempt."""
        return self._backoff_base * (2**attempt)

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float:
        """Délai avant réessai : `Retry-After` si présent, sinon backoff."""
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass  # format date HTTP non géré → on retombe sur le backoff
        return self._backoff(attempt)

    @staticmethod
    def _log_cost(response: httpx.Response) -> None:
        logger.debug(
            "sorare request id=%s complexity=%s depth=%s status=%s",
            response.headers.get("x-request-id"),
            response.headers.get("x-gql-complexity"),
            response.headers.get("x-gql-depth"),
            response.status_code,
        )

    def execute(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """Exécute une requête GraphQL et renvoie le bloc ``data``.

        Réessaie sur erreurs transitoires (réseau, 5xx, 429). Lève
        :class:`SorareError` sur erreur définitive (4xx hors 429, erreurs
        GraphQL, ou épuisement des essais).
        """
        body = {"query": query, "variables": variables or {}}
        last_error: SorareError | None = None

        for attempt in range(self._max_retries + 1):
            self._throttle()
            try:
                response = self._client.post(self._url, json=body, headers=self._auth_headers())
            except httpx.HTTPError as exc:  # réseau, timeout, DNS…
                last_error = SorareError(f"Erreur transport vers l'API Sorare : {exc}")
                if attempt < self._max_retries:
                    self._sleep(self._backoff(attempt))
                    continue
                raise last_error from exc

            self.last_headers = response.headers
            self._log_cost(response)

            if response.status_code in RETRYABLE_STATUS:
                last_error = SorareError(
                    f"HTTP {response.status_code} de l'API Sorare (transitoire)."
                )
                if attempt < self._max_retries:
                    self._sleep(self._retry_delay(response, attempt))
                    continue
                raise last_error

            if response.status_code >= 400:
                raise SorareError(
                    f"HTTP {response.status_code} de l'API Sorare : {response.text[:500]}"
                )

            payload = response.json()
            errors = payload.get("errors")
            if errors:
                raise SorareError(f"Erreurs GraphQL : {errors}")
            return payload.get("data", {})

        # Sécurité : théoriquement inatteignable (la boucle lève avant).
        raise last_error or SorareError("Échec de la requête Sorare.")

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SorareClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
