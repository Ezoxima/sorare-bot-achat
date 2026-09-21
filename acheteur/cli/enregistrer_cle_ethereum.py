"""Enregistrement interactif de la clé privée Ethereum (rail ETH, lot L7).

La clé n'est jamais affichée ni journalisée (saisie masquée, `getpass`) ;
seule l'adresse publique dérivée est affichée, pour que l'utilisateur
confirme que c'est bien le bon compte avant de continuer.

Usage : python -m acheteur.cli.enregistrer_cle_ethereum
"""

from __future__ import annotations

import getpass

from acheteur.paiement.cle_ethereum import ClePriveeInvalideError, enregistrer_cle_privee


def main() -> None:
    cle_privee = getpass.getpass("Clé privée Ethereum (non affichée) : ").strip()
    if not cle_privee:
        raise SystemExit("Clé vide — abandon.")

    try:
        adresse = enregistrer_cle_privee(cle_privee)
    except ClePriveeInvalideError as exc:
        raise SystemExit(str(exc)) from exc
    finally:
        cle_privee = ""  # ne reste pas en mémoire plus que nécessaire

    print("OK — clé enregistrée dans le gestionnaire d'identifiants Windows.")
    print(f"     Adresse dérivée : {adresse}")
    print("     Vérifie que c'est bien l'adresse de ton compte Ethereum Sorare.")


if __name__ == "__main__":
    main()
