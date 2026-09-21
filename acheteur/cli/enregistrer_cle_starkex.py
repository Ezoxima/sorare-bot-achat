"""Enregistrement interactif de la clé privée StarkEx (rail EUR, lot L7 suite).

La clé n'est jamais affichée ni journalisée (saisie masquée, `getpass`) ;
seule la clé publique dérivée est affichée, pour que l'utilisateur confirme
que c'est bien le bon compte (Starkware, distinct du compte Ethereum) avant
de continuer.

Usage : python -m acheteur.cli.enregistrer_cle_starkex
"""

from __future__ import annotations

import getpass

from acheteur.paiement.cle_starkex import ClePriveeInvalideError, enregistrer_cle_privee


def main() -> None:
    cle_privee = getpass.getpass("Clé privée StarkEx (non affichée) : ").strip()
    if not cle_privee:
        raise SystemExit("Clé vide — abandon.")

    try:
        cle_publique = enregistrer_cle_privee(cle_privee)
    except ClePriveeInvalideError as exc:
        raise SystemExit(str(exc)) from exc
    finally:
        cle_privee = ""  # ne reste pas en mémoire plus que nécessaire

    print("OK — clé enregistrée dans le gestionnaire d'identifiants Windows.")
    print(f"     Clé publique dérivée : {cle_publique}")
    print("     Vérifie que c'est bien celle de ton compte Starkware.")


if __name__ == "__main__":
    main()
