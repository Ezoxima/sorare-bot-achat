"""Renouvellement du jeton, sans mot de passe.

Le renouvellement après coup (jeton déjà expiré) obligerait à ressaisir le
mot de passe, donc à être présent — ce qu'on veut justement éviter pour une
tâche planifiée. La mutation `createJwtToken` (schéma Sorare) délivre un
nouveau jeton pour `currentUser`, authentifiée par le jeton *encore valide*
qu'on lui présente : c'est ce qui rend le renouvellement possible sans mot
de passe, à condition de le déclencher AVANT l'expiration.

Politique : renouveler dès qu'il reste moins de 3 jours avant l'échéance.
Si le jeton est déjà expiré, ce module ne peut rien : voir
`acheteur.auth.jeton.obtenir_jeton_valide`, qui redirige vers la connexion
interactive.
"""

from __future__ import annotations

import logging
from datetime import datetime

from acheteur.auth.jeton import InfoJeton, enregistrer_jeton, jours_avant_expiration
from acheteur.core.horloge import Horloge
from acheteur.sorare.client import SorareClient

logger = logging.getLogger(__name__)

SEUIL_RENOUVELLEMENT_JOURS = 3

CREATE_JWT_TOKEN_MUTATION = """
mutation RenouvelerJwt($input: createJwtTokenInput!) {
  createJwtToken(input: $input) {
    currentUser { slug }
    jwtToken { token expiredAt }
    errors { message }
  }
}
"""


def renouveler_si_necessaire(info: InfoJeton, horloge: Horloge) -> InfoJeton:
    """Renouvelle le jeton s'il expire dans moins de 3 jours, sinon le renvoie tel quel."""
    if jours_avant_expiration(info, horloge) > SEUIL_RENOUVELLEMENT_JOURS:
        return info

    with SorareClient(jwt=info.token, jwt_aud=info.aud) as client:
        data = client.execute(CREATE_JWT_TOKEN_MUTATION, {"input": {"aud": info.aud}})

    resultat = data["createJwtToken"]
    erreurs = resultat.get("errors") or []
    if erreurs:
        logger.warning(
            "Renouvellement du jeton refusé (%s) — le jeton actuel reste utilisable "
            "jusqu'à son échéance.",
            "; ".join(e.get("message", "?") for e in erreurs),
        )
        return info

    nouveau = resultat.get("jwtToken") or {}
    if not nouveau.get("token"):
        logger.warning("Renouvellement du jeton : réponse sans jeton, jeton actuel conservé.")
        return info

    nouvelle_info = InfoJeton(
        token=nouveau["token"],
        expire_le=datetime.fromisoformat(nouveau["expiredAt"]),
        aud=info.aud,
    )
    enregistrer_jeton(nouvelle_info.token, nouvelle_info.expire_le, nouvelle_info.aud)
    logger.info("Jeton renouvelé, nouvelle échéance : %s", nouvelle_info.expire_le.isoformat())
    return nouvelle_info
