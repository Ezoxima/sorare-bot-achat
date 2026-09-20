"""Sonde d'état du compte — lecture seule, coût 0.

Vérifie que la chaîne jeton → client → requête fonctionne de bout en bout,
et fige un instantané du compte (rails de paiement disponibles, migration ETH
en attente ou non, soldes) dans `sondes/resultats/` (gitignoré : contient des
adresses de portefeuille).

Usage : python -m acheteur.cli.etat_compte
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from acheteur.auth.jeton import JetonAbsentError, JetonExpireError, obtenir_jeton_valide
from acheteur.auth.renouvellement import renouveler_si_necessaire
from acheteur.core.horloge import HorlogeSysteme
from acheteur.core.journalisation import configurer_journalisation
from acheteur.sorare.client import SorareClient
from acheteur.sorare.requetes import etat_compte

RESULTATS_DIR = Path(__file__).resolve().parents[2] / "sondes" / "resultats"


def main() -> int:
    configurer_journalisation()
    horloge = HorlogeSysteme()

    try:
        info = obtenir_jeton_valide(horloge)
    except (JetonAbsentError, JetonExpireError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    info = renouveler_si_necessaire(info, horloge)

    with SorareClient(jwt=info.token, jwt_aud=info.aud) as client:
        compte = etat_compte(client)

    RESULTATS_DIR.mkdir(parents=True, exist_ok=True)
    horodatage = horloge.maintenant().strftime("%Y-%m-%dT%H-%M-%S")
    chemin = RESULTATS_DIR / f"etat_compte_{horodatage}.json"
    chemin.write_text(json.dumps(compte, indent=2, ensure_ascii=False), encoding="utf-8")

    solde = compte.get("availableBalances", {}) or {}
    eur = (solde.get("eurCents") or {}).get("eurCents")
    wei = (solde.get("wei") or {}).get("wei")
    lamport = (solde.get("lamport") or {}).get("lamport")
    print(f"OK — utilisateur : {compte.get('slug')}")
    print(f"     Migration ETH en attente : {compte.get('shouldMigrateEth')}")
    print(f"     Soldes disponibles — EUR: {eur} centimes · wei: {wei} · lamport: {lamport}")
    print(f"     Instantané complet écrit dans {chemin}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
