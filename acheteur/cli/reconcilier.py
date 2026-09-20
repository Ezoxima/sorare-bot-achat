"""Réconciliation lecture seule (lot L2) : compare le journal local aux
offres observées sur Sorare, importe ce qui manque, n'envoie jamais rien.

Usage : python -m acheteur.cli.reconcilier
"""

from __future__ import annotations

import sys

from acheteur.auth.jeton import JetonAbsentError, JetonExpireError, obtenir_jeton_valide
from acheteur.auth.renouvellement import renouveler_si_necessaire
from acheteur.core.db import creer_tables, session_scope
from acheteur.core.horloge import HorlogeSysteme
from acheteur.core.journalisation import configurer_journalisation
from acheteur.negociation.reconciliation import reconcilier
from acheteur.sorare.client import SorareClient


def main() -> int:
    configurer_journalisation()
    horloge = HorlogeSysteme()
    creer_tables()

    try:
        info = obtenir_jeton_valide(horloge)
    except (JetonAbsentError, JetonExpireError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    info = renouveler_si_necessaire(info, horloge)

    with session_scope() as session, SorareClient(jwt=info.token, jwt_aud=info.aud) as client:
        rapport = reconcilier(session, client, horloge)

    print(f"Appariées automatiquement : {len(rapport.appariees)}")
    print(f"Lignes du journal sans contrepartie sur Sorare : {len(rapport.sans_contrepartie)}")
    print(f"Correspondances ambiguës (à examiner à la main) : {len(rapport.ambigues)}")
    for ligne, candidates in rapport.ambigues:
        print(f"  - ligne #{ligne.id} ({ligne.joueur_slug}/{ligne.vendeur_slug}) : "
              f"{len(candidates)} offres Sorare correspondent")
    print(f"Offres importées (faites à la main, hors décision du bot) : {len(rapport.a_importer)}")
    for offre in rapport.a_importer:
        print(f"  - {offre.sorare_id} — {offre.joueurs_slugs} / {offre.vendeur_slug}")

    if rapport.cycle_suspendu:
        print()
        print("⚠ Cycle suspendu : une dépense non décidée par le bot a été détectée.")
        print("  Vérifier les offres importées avant de relancer un scan.")
        return 1

    print()
    print("OK — rien à examiner à la main.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
