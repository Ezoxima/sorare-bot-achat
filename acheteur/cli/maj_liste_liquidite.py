"""Reconstruction complète de la liste des couples (joueur, rareté,
éligibilité de saison) liquides — lecture seule côté Sorare, écriture
seulement dans la base locale (`marche.liste_liquidite`), jamais vers
Sorare. Job « lent », à programmer une fois toutes les
`DELAI_RAFRAICHISSEMENT_HEURES` (24h par défaut, voir
`marche.liste_liquidite` — choix explicite de l'utilisateur, 2026-09-22).

Ce script ne décide rien et n'envoie rien : il alimente la liste que la
future passe rapide (lot L9, PLAN.md) lira au lieu de recalculer la
liquidité de zéro à chaque exécution. Le pré-filtre lui-même
(`marche.liquidite.est_liquide`) est déjà utilisé par `cli/scan_marche.py`
(lot L8) ; ce script ne fait que le persister.

Usage :
    python -m acheteur.cli.maj_liste_liquidite
    python -m acheteur.cli.maj_liste_liquidite --premieres 500
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
    Annonce,
    Joueur,
    annonces_depuis_noeuds_marche,
    est_liquide,
    mesurer_liquidite,
    rarete_depuis_sorare,
    rarity_brute_depuis_annonce,
    season_eligibility_brute_depuis_annonce,
    ventes_depuis_noeuds_prix,
)
from acheteur.marche.liste_liquidite import remplacer_liste_liquidite
from acheteur.sorare import requetes
from acheteur.sorare.client import SorareClient

NOMBRE_ANNONCES_EXAMINEES_DEFAUT = 500


def _couples_distincts(annonces: list[Annonce]) -> list[dict]:
    """Les couples (joueur, rareté, éligibilité de saison) distincts d'un
    échantillon d'annonces — plusieurs vendeurs peuvent proposer le même
    couple, il ne doit être mesuré qu'une fois.

    Fonction pure : pas de réseau, testable sur des cas figés.
    """
    vus: dict[tuple[str, str, str], dict] = {}
    for annonce in annonces:
        cle = (
            annonce.joueur.slug,
            rarity_brute_depuis_annonce(annonce),
            season_eligibility_brute_depuis_annonce(annonce),
        )
        if cle in vus:
            continue
        vus[cle] = {
            "joueur_slug": cle[0],
            "rarete": cle[1],
            "season_eligibility": cle[2],
        }
    return list(vus.values())


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

        for couple, noeuds_prix in zip(lot, resultats):
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
        description="Reconstruit la liste des couples joueur/rareté/saison liquides. "
        "Lecture seule côté Sorare ; écrit uniquement dans la base locale."
    )
    parser.add_argument(
        "--premieres",
        type=int,
        default=NOMBRE_ANNONCES_EXAMINEES_DEFAUT,
        help=f"Taille de l'échantillon d'annonces examinées (défaut {NOMBRE_ANNONCES_EXAMINEES_DEFAUT}).",
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
        print(f"Récupération de {args.premieres} annonces du marché...")
        noeuds_marche = requetes.annonces_marche(client, premieres=args.premieres)
        annonces = annonces_depuis_noeuds_marche(noeuds_marche)
        print(f"  {len(annonces)} annonces traduites (sur {len(noeuds_marche)} nœuds bruts)")

        couples = _couples_distincts(annonces)
        print(f"  {len(couples)} couples (joueur, rareté, saison) distincts à mesurer")
        print()

        print("Mesure de la liquidité (par lot)...")
        entrees = _entrees_liquides(client, horloge, couples)
        print(f"  {len(entrees)} couples liquides retenus sur {len(couples)}")

        nb_ecrites = remplacer_liste_liquidite(session, entrees, horloge.maintenant())
        print(f"Liste remplacée : {nb_ecrites} ligne(s) écrite(s) dans la base locale.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
