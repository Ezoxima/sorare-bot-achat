"""Connexion interactive à Sorare — jamais importée par la boucle automatique.

Le mot de passe et le code 2FA ne sont jamais stockés, ni journalisés : ils
transitent en mémoire le temps de l'appel `signIn` et disparaissent. Seul le
jeton obtenu est conservé, dans le coffre (`acheteur.auth.jeton`).

Flux Sorare :
1. GET `/api/v1/users/{email}` → `salt` bcrypt du compte ;
2. `bcrypt.hashpw(password, salt)` → mot de passe hashé ;
3. mutation `signIn(input:{email,password})` → `jwtToken(aud:)` ;
4. si 2FA activé : `otpSessionChallenge` renvoyé → re-`signIn` avec `otpAttempt`.

Usage : python -m acheteur.cli.connecter --email <email>
"""

from __future__ import annotations

import argparse
import getpass
from datetime import datetime

import bcrypt
import httpx

from acheteur.auth.jeton import enregistrer_jeton
from acheteur.core.config import get_settings
from acheteur.sorare.client import SorareClient

SALT_URL = "https://api.sorare.com/api/v1/users/{email}"

SIGN_IN_MUTATION = """
mutation SignIn($input: signInInput!, $aud: String!) {
  signIn(input: $input) {
    currentUser { slug }
    jwtToken(aud: $aud) { token expiredAt }
    otpSessionChallenge
    errors { message }
  }
}
"""


def _recuperer_salt(email: str) -> str:
    resp = httpx.get(SALT_URL.format(email=email), timeout=30.0)
    resp.raise_for_status()
    salt = resp.json().get("salt")
    if not salt:
        raise SystemExit(f"Salt introuvable pour {email} (réponse : {resp.text[:200]}).")
    return salt


def _hacher_mot_de_passe(mot_de_passe: str, salt: str) -> str:
    return bcrypt.hashpw(mot_de_passe.encode(), salt.encode()).decode()


def _se_connecter(client: SorareClient, email: str, hache: str, aud: str) -> dict:
    """Appelle signIn ; gère le rebond 2FA (otpSessionChallenge → otpAttempt)."""
    variables = {"input": {"email": email, "password": hache}, "aud": aud}
    data = client.execute(SIGN_IN_MUTATION, variables)
    resultat = data["signIn"]

    if resultat.get("otpSessionChallenge"):
        otp = getpass.getpass("Code 2FA (OTP) : ").strip()
        variables["input"]["otpAttempt"] = otp
        variables["input"]["otpSessionChallenge"] = resultat["otpSessionChallenge"]
        data = client.execute(SIGN_IN_MUTATION, variables)
        resultat = data["signIn"]

    erreurs = resultat.get("errors") or []
    if erreurs:
        raise SystemExit("Échec signIn : " + "; ".join(e.get("message", "?") for e in erreurs))
    if not (resultat.get("jwtToken") or {}).get("token"):
        raise SystemExit(f"Pas de token dans la réponse : {resultat}")
    return resultat


def connecter(email: str, aud: str | None = None) -> None:
    settings = get_settings()
    aud = aud or settings.sorare_jwt_aud

    mot_de_passe = getpass.getpass("Mot de passe Sorare (non affiché) : ")
    if not mot_de_passe:
        raise SystemExit("Mot de passe vide — abandon.")

    salt = _recuperer_salt(email)
    hache = _hacher_mot_de_passe(mot_de_passe, salt)
    mot_de_passe = ""  # ne reste pas en mémoire plus que nécessaire

    # jwt="" : sans ça, SorareClient() pourrait attacher un JWT déjà expiré à
    # cette requête signIn elle-même, qui n'en a pas besoin, et la faire
    # échouer avant même d'atteindre le mot de passe.
    with SorareClient(jwt="", jwt_aud="") as client:
        resultat = _se_connecter(client, email, hache, aud)

    token = resultat["jwtToken"]["token"]
    expire_le = datetime.fromisoformat(resultat["jwtToken"]["expiredAt"])
    slug = (resultat.get("currentUser") or {}).get("slug")

    enregistrer_jeton(token, expire_le, aud)

    print(f"OK — jeton enregistré dans le gestionnaire d'identifiants Windows (user={slug}).")
    print(f"     Expire : {expire_le.isoformat()}.")
    print(f"     Jeton (tronqué) : {token[:12]}…{token[-6:]}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Connexion interactive à Sorare.")
    parser.add_argument("--email", required=True, help="Email de connexion Sorare.")
    parser.add_argument(
        "--aud",
        default=None,
        help="Audience du JWT. Défaut : SORARE_JWT_AUD du .env.",
    )
    args = parser.parse_args(argv)
    connecter(args.email, args.aud)


if __name__ == "__main__":
    main()
