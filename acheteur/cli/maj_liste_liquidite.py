"""Reconstruction complète de la liste des couples (joueur, rareté,
éligibilité de saison) liquides — lecture seule côté Sorare, écriture
seulement dans la base locale (`marche.liste_liquidite`), jamais vers
Sorare. Job « lent », à programmer une fois toutes les
`DELAI_RAFRAICHISSEMENT_HEURES` (24h par défaut, voir
`marche.liste_liquidite` — choix explicite de l'utilisateur, 2026-09-22).

**Câblé sur le référentiel de joueurs (2026-09-22), pas sur un échantillon
du marché.** Jusqu'ici ce script échantillonnait les annonces les plus
récemment mises à jour du marché entier (`annonces_marche_paginees`) — un
biais structurel confirmé (TODO.md, 2026-09-22, à partir du code source
réel de `sealing-sorare-apps-script`) : une carte qui se revend souvent
(donc généralement peu chère) revenait sans cesse dans cet échantillon, une
carte chère mise en vente une fois restait hors échantillon indéfiniment.
Ce script mesure maintenant la liquidité de TOUS les joueurs du référentiel
(`marche.referentiel_joueurs`, construit par
`cli/maj_referentiel_joueurs.py`) — même principe que `liquiditeParCouple_`
côté Apps Script : chaque joueur est mesuré sur 2 raretés (limited, rare) ×
2 éligibilités de saison (CLASSIC, IN_SEASON), qu'il ait ou non une annonce
en cours au moment du scan.

⚠️ **Coût mesuré à ~26 000 joueurs (MESURES.md, 2026-09-22) : ~106 000
couples, ~530 appels réseau par lots de 200 alias, de l'ordre de 10 minutes**
(estimé à partir de `TAILLE_LOT_HISTORIQUE_PRIX_DEFAUT`, ~1,1 s/lot mesuré
ailleurs). Acceptable pour un job quotidien, pas pour un usage plus fréquent.

Ce script ne décide rien et n'envoie rien : il alimente la liste que
`cli/scan_liste_liquidite.py`/`cli/proposer_periodique.py` lisent au lieu
de recalculer la liquidité de zéro à chaque exécution. Le pré-filtre
lui-même (`marche.liquidite.est_liquide`) est déjà utilisé par
`cli/scan_marche.py` (lot L8) ; ce script ne fait que le persister à
l'échelle du référentiel complet.

Usage :
    python -m acheteur.cli.maj_liste_liquidite
    python -m acheteur.cli.maj_liste_liquidite --limite-joueurs 200   (test rapide)
"""

from __future__ import annotations

import argparse
import sys

from acheteur.auth.jeton import JetonAbsentError, JetonExpireError, obtenir_jeton_valide
from acheteur.auth.renouvellement import renouveler_si_necessaire
from acheteur.core.db import creer_tables, session_scope
from acheteur.core.horloge import Horloge, HorlogeSysteme
from acheteur.core.journalisation import configurer_journalisation
from acheteur.marche import (
    Joueur,
    est_liquide,
    mesurer_liquidite,
    rarete_depuis_sorare,
    ventes_depuis_noeuds_prix,
)
from acheteur.marche.liste_liquidite import remplacer_liste_liquidite
from acheteur.marche.referentiel_joueurs import (
    JoueurReferentiel,
    derniere_maj_referentiel,
    lire_referentiel_joueurs,
    referentiel_perime,
)
from acheteur.sorare import requetes
from acheteur.sorare.client import SorareClient

# Mêmes couples que `liquiditeParCouple_` côté Apps Script (DECISIONS.md,
# 2026-09-22) : 2 raretés × 2 éligibilités de saison par joueur, pas
# seulement la combinaison actuellement en vente.
RARETES_MESUREES = ["limited", "rare"]
SAISONS_MESUREES = ["CLASSIC", "IN_SEASON"]


def _couples_du_referentiel(
    joueurs: list[JoueurReferentiel],
    raretes: list[str] = RARETES_MESUREES,
    saisons: list[str] = SAISONS_MESUREES,
) -> list[dict]:
    """Le produit cartésien joueurs × raretés × saisons à mesurer.

    Fonction pure : pas de réseau, testable sur des cas figés.
    """
    return [
        {"joueur_slug": joueur.joueur_slug, "rarete": rarete, "season_eligibility": saison}
        for joueur in joueurs
        for rarete in raretes
        for saison in saisons
    ]


def _entrees_liquides(
    client: SorareClient,
    horloge: Horloge,
    couples: list[dict],
    taille_lot: int = requetes.TAILLE_LOT_HISTORIQUE_PRIX_DEFAUT,
) -> list[dict]:
    """Mesure la liquidité de chaque couple (par lot, alias GraphQL — même
    principe que `cli/scan_marche.py::_calculer_candidates`) et ne garde
    que ceux qui passent `marche.liquidite.est_liquide`."""
    maintenant = horloge.maintenant()
    retenus: list[dict] = []

    for debut in range(0, len(couples), taille_lot):
        lot = couples[debut : debut + taille_lot]
        demandes = [
            {
                "joueur_slug": c["joueur_slug"],
                "rarete": c["rarete"],
                "season_eligibility": c["season_eligibility"],
            }
            for c in lot
        ]
        resultats = requetes.historique_prix_joueurs_lot(client, demandes)

        for couple, noeuds_prix in zip(lot, resultats, strict=True):
            # Un `Joueur` minimal, seulement pour porter le slug attendu par
            # `ventes_depuis_noeuds_prix` (le nom/la rareté ne servent pas à
            # `mesurer_liquidite`, qui ne regarde que les dates).
            joueur = Joueur(
                slug=couple["joueur_slug"],
                nom=couple["joueur_slug"],
                rareté=rarete_depuis_sorare(couple["rarete"]),
            )
            ventes = ventes_depuis_noeuds_prix(noeuds_prix, joueur)
            liquidite = mesurer_liquidite(ventes, maintenant)
            if not est_liquide(liquidite):
                continue
            retenus.append(
                {
                    **couple,
                    "n30": liquidite.n30,
                    "n7": liquidite.n7,
                    "semaines_actives": liquidite.semaines_actives,
                }
            )
    return retenus


def main() -> int:
    configurer_journalisation()

    parser = argparse.ArgumentParser(
        description="Reconstruit la liste des couples joueur/rareté/saison liquides, a "
        "partir du referentiel complet de joueurs. Lecture seule cote Sorare ; ecrit "
        "uniquement dans la base locale."
    )
    parser.add_argument(
        "--limite-joueurs",
        type=int,
        default=None,
        help="Ne mesurer que les N premiers joueurs du referentiel (test rapide, pas "
        "un usage normal — la liste liquide serait tronquee).",
    )
    parser.add_argument(
        "--ignorer-peremption",
        action="store_true",
        help="Continue meme si le referentiel de joueurs n'a pas ete reconstruit depuis "
        "le delai prevu (deconseille : la liste liquide porterait sur un pool obsolete).",
    )
    args = parser.parse_args()

    horloge = HorlogeSysteme()
    creer_tables()

    try:
        info = obtenir_jeton_valide(horloge)
    except (JetonAbsentError, JetonExpireError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    info = renouveler_si_necessaire(info, horloge)

    with session_scope() as session, SorareClient(jwt=info.token, jwt_aud=info.aud) as client:
        maintenant = horloge.maintenant()

        if referentiel_perime(session, maintenant):
            maj = derniere_maj_referentiel(session)
            message = (
                "Referentiel de joueurs absent ou perime "
                f"(derniere reconstruction : {maj if maj else 'jamais'}). "
                "Lance d'abord : python -m acheteur.cli.maj_referentiel_joueurs"
            )
            if not args.ignorer_peremption:
                print(message, file=sys.stderr)
                return 1
            print(f"  AVERTISSEMENT : {message} (--ignorer-peremption : on continue quand meme)")

        joueurs = lire_referentiel_joueurs(session)
        if args.limite_joueurs is not None:
            joueurs = joueurs[: args.limite_joueurs]
        print(f"{len(joueurs)} joueur(s) dans le referentiel a mesurer "
              f"({len(RARETES_MESUREES)} rarete(s) x {len(SAISONS_MESUREES)} saison(s)).")
        if not joueurs:
            print("Referentiel vide. Rien a mesurer.", file=sys.stderr)
            return 1

        couples = _couples_du_referentiel(joueurs)
        print(f"  {len(couples)} couples a mesurer")
        print()

        print("Mesure de la liquidite (par lot)...")
        entrees = _entrees_liquides(client, horloge, couples)
        print(f"  {len(entrees)} couples liquides retenus sur {len(couples)}")

        nb_ecrites = remplacer_liste_liquidite(session, entrees, maintenant)
        print(f"Liste remplacee : {nb_ecrites} ligne(s) ecrite(s) dans la base locale.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
