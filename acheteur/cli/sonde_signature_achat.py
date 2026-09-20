"""Sonde L1 : signature à l'achat.

Détermine quel type d'autorisation est demandé pour un achat sur Sorare,
sans créer aucun objet durable (empreinte avant/après pour le prouver).

Trois tirs, pas un : EUR seul, ETH seul, avec les deux.

Appelle `prepareOffer` pour chaque rail et capture le type d'`AuthorizationRequest`.

Usage : python -m acheteur.cli.sonde_signature_achat
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from acheteur.auth.jeton import JetonAbsentError, JetonExpireError, obtenir_jeton_valide
from acheteur.auth.renouvellement import renouveler_si_necessaire
from acheteur.core.horloge import HorlogeSysteme
from acheteur.core.journalisation import configurer_journalisation
from acheteur.sorare.client import SorareClient, SorareError
from acheteur.sorare.requetes import etat_compte

RESULTATS_DIR = Path(__file__).resolve().parents[2] / "sondes" / "resultats"

PREPARE_OFFER_MUTATION = """
mutation PrepareOffer($input: prepareOfferInput!) {
  prepareOffer(input: $input) {
    clientMutationId
    authorizations {
      id
      fingerprint
      status
      request {
        __typename
      }
      operation {
        __typename
      }
    }
    errors {
      code
      message
      path
    }
  }
}
"""


def comparaison_comptes(avant: dict, apres: dict) -> dict[str, bool]:
    """Vérifie que les champs importants n'ont pas changé entre avant et après."""
    champs = [
        "slug",
        "ethereumAddress",
        "starkKey",
        "shouldMigrateEth",
        "totalBalance",
        "availableBalance",
    ]
    differences = {}
    for champ in champs:
        avant_val = avant.get(champ)
        apres_val = apres.get(champ)
        if avant_val != apres_val:
            differences[champ] = {
                "avant": avant_val,
                "apres": apres_val,
            }
    return differences


def sonde_tir(
    client: SorareClient,
    devise: str,
    montant_eur: int = 100,
    montant_wei: int = 1000000000000000,
) -> dict:
    """Effectue un tir unique : prepareOffer, capture le type d'autorisation."""

    variables = {
        "input": {
            "clientMutationId": f"sonde_L1_{devise}_{datetime.now().isoformat()}",
            "sendAssetIds": [],
            "sendAmount": {
                "amount": "0",
                "currency": "EUR" if devise in ("EUR", "BOTH") else "WEI",
            },
            # Identifiant fictif — la requête échouera validation,
            # mais nous verrons si une autorisation est demandée
            "receiveAssetIds": ["test-card-id"],
            "receiveAmount": {
                "amount": str(montant_eur) if devise in ("EUR", "BOTH") else str(montant_wei),
                "currency": "EUR" if devise in ("EUR", "BOTH") else "WEI",
            },
            "receiverSlug": "test-seller",
            "settlementCurrencies": ["EUR"] if devise == "EUR" else ["WEI"],
        }
    }

    try:
        response = client.execute(PREPARE_OFFER_MUTATION, variables=variables)
        return response
    except SorareError as exc:
        return {"error": str(exc)}


def main() -> int:
    configurer_journalisation()
    horloge = HorlogeSysteme()

    try:
        info = obtenir_jeton_valide(horloge)
    except (JetonAbsentError, JetonExpireError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    info = renouveler_si_necessaire(info, horloge)

    # Lire l'empreinte initiale
    with SorareClient(jwt=info.token, jwt_aud=info.aud) as client:
        empreinte_avant = etat_compte(client)

    print("=" * 80)
    print("SONDE L1 : SIGNATURE À L'ACHAT")
    print("=" * 80)
    print(f"Utilisateur : {empreinte_avant.get('slug')}")
    print(f"Horodatage début : {horloge.maintenant().isoformat()}")
    print()

    resultats = {
        "horodatage": horloge.maintenant().isoformat(),
        "methode": "prepareOffer avec paramètres partiellement invalides",
        "tirs": [],
    }

    # Trois tirs
    tirs_config = [
        ("EUR", {"montant_eur": 100}),
        ("WEI", {"montant_wei": 1000000000000000}),
        ("BOTH", {"montant_eur": 100, "montant_wei": 1000000000000000}),
    ]

    with SorareClient(jwt=info.token, jwt_aud=info.aud) as client:
        for devise, kwargs in tirs_config:
            print(f"Tir {devise}...")
            try:
                reponse = sonde_tir(client, devise, **kwargs)

                # Analyser les autorisations demandées
                autorisations = []
                erreurs = []
                if "prepareOffer" in reponse:
                    payload = reponse["prepareOffer"]
                    if "authorizations" in payload:
                        for auth in payload["authorizations"]:
                            if "request" in auth:
                                request_type = auth["request"].get("__typename", "UNKNOWN")
                                autorisations.append(request_type)
                    if "errors" in payload and payload["errors"]:
                        erreurs = payload["errors"]

                resultats["tirs"].append(
                    {
                        "devise": devise,
                        "autorisations_demandees": autorisations,
                        "erreurs": erreurs,
                    }
                )

                if autorisations:
                    print(f"  ✓ Autorisations demandées : {autorisations}")
                else:
                    status = (
                        "pas d'autorisation demandée" if not erreurs else "erreur de validation"
                    )
                    print(f"  → {status}")

            except Exception as exc:
                print(f"  ✗ Exception : {exc}")
                resultats["tirs"].append(
                    {
                        "devise": devise,
                        "erreur": str(exc),
                    }
                )

    # Prendre l'empreinte finale
    with SorareClient(jwt=info.token, jwt_aud=info.aud) as client:
        empreinte_apres = etat_compte(client)

    # Comparer
    differences = comparaison_comptes(empreinte_avant, empreinte_apres)
    resultats["differences"] = differences
    resultats["empreinte_conservee"] = len(differences) == 0

    print()
    print("Vérification d'impact...")
    if resultats["empreinte_conservee"]:
        print("  ✓ Aucun changement détecté (empreinte avant = empreinte après)")
        print("    → Sonde L1 sans effet : aucune offre n'a été créée ou modifiée")
    else:
        print(f"  ✗ Changements détectés : {json.dumps(differences, indent=2)}")

    print()
    print("=" * 80)

    # Écrire les résultats
    RESULTATS_DIR.mkdir(parents=True, exist_ok=True)
    horodatage_fichier = horloge.maintenant().strftime("%Y-%m-%dT%H-%M-%S")
    chemin = RESULTATS_DIR / f"sonde_signature_achat_{horodatage_fichier}.json"
    chemin.write_text(json.dumps(resultats, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Résultats complets écrits : {chemin}")

    # Synthèse
    print()
    print("SYNTHÈSE")
    print("--------")
    print(f"Empreinte conservée (pas d'effet) : {resultats['empreinte_conservee']}")
    for tir in resultats["tirs"]:
        devise = tir.get("devise", "?")
        auteurs = tir.get("autorisations_demandees", [])
        erreurs = tir.get("erreurs", [])
        err_msg = f" ({len(erreurs)} erreur(s) validación)" if erreurs else ""
        auth_str = ", ".join(auteurs) if auteurs else "—"
        print(f"  {devise:6} → Autorisations : {auth_str}{err_msg}")

    print()
    if not any(tir.get("autorisations_demandees") for tir in resultats["tirs"]):
        print("⚠ Aucune autorisation n'a été demandée par prepareOffer.")
        print("  Cela peut signifier :")
        print("  1. Les paramètres invalides causent une validation préalable")
        print("  2. L'autorisation n'est demandée que par createDirectOffer, pas prepareOffer")
        print("  3. L'API Sorare a un comportement inattendu")
        print()
        print("  Prochaine étape : vérifier L6 avec une vraie offre sur une carte réelle.")

    return 0 if resultats["empreinte_conservee"] else 1


if __name__ == "__main__":
    sys.exit(main())
