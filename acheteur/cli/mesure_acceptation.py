"""Mesure lecture seule (lot L10) : taux d'acceptation par palier et par
motif de refus, à partir du journal local. Aucun réseau — c'est le rapport
qui dira si les paliers valent leur complexité (PLAN.md § Lots livrables).

Usage : python -m acheteur.cli.mesure_acceptation
"""

from __future__ import annotations

import sys

from acheteur.core.db import creer_tables, session_scope
from acheteur.core.journalisation import configurer_journalisation
from acheteur.mesure.acceptation import calculer_taux_acceptation
from acheteur.negociation.journal import toutes_les_lignes


def main() -> int:
    configurer_journalisation()
    creer_tables()

    with session_scope() as session:
        lignes = toutes_les_lignes(session)

    rapport = calculer_taux_acceptation(lignes)

    if not rapport.par_palier:
        print("Aucune ligne conclue (réellement envoyée, décidée par le bot) à mesurer.")
        print(f"Lignes hors périmètre (simulées/importées/sans palier) : {rapport.lignes_hors_perimetre}")
        return 0

    print("Taux d'acceptation par palier (lignes réelles, décidées par le bot, conclues) :")
    for ligne in rapport.par_palier:
        taux = f"{ligne.taux:.0%}" if ligne.taux is not None else "—"
        print(f"  - palier {ligne.palier}% : {ligne.acceptees}/{ligne.total} ({taux})")

    print()
    print(f"Total conclu : {rapport.total_conclu}")
    print(f"Lignes hors périmètre (simulées/importées/sans palier) : {rapport.lignes_hors_perimetre}")

    print()
    if rapport.par_motif_refus:
        print(f"Motifs de refus (total refusé : {rapport.total_refuse}) :")
        for motif, effectif in sorted(rapport.par_motif_refus.items(), key=lambda kv: -kv[1]):
            print(f"  - {motif.value} : {effectif}")
    else:
        print("Aucun refus enregistré.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
