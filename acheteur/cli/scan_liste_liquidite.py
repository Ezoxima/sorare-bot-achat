"""Lot L9 (partie « scan », PLAN.md) : passe rapide qui LIT la liste des
couples liquides déjà construite par `cli/maj_liste_liquidite.py` (job
lent, tourné toutes les `marche.liste_liquidite.DELAI_RAFRAICHISSEMENT_HEURES`)
au lieu de recalculer la liquidité de zéro sur un échantillon tiré au hasard
(ce que fait `cli/scan_marche.py`, lot L8).

Différence avec `scan_marche.py` : celui-ci interroge `annonces_marche`
CIBLÉ (`playerSlug=...`) pour chaque couple déjà connu comme liquide,
plutôt qu'un tirage aléatoire du marché entier — beaucoup moins d'appels
pour un run destiné à tourner souvent (toutes les x minutes, PLAN.md § L9).
Le reste du pipeline (référence, filtre de bonne affaire, garde de
joignabilité, offre groupée réactive, budget) est **strictement le même** —
réutilisé tel quel depuis `scan_marche.py`, pas dupliqué.

**Toujours en lecture seule côté Sorare — aucun envoi.** Décision explicite
de l'utilisateur (2026-09-22) : ce script scanne et rapporte, exactement
comme `scan_marche.py` ; l'envoi réel automatique en boucle reste un futur
choix à part, pas encore fait.

Usage :
    python -m acheteur.cli.scan_liste_liquidite
    python -m acheteur.cli.scan_liste_liquidite --seuil 85 --sortie rapport_liste.txt
"""

from __future__ import annotations

import argparse
import sys
import time

from acheteur.auth.jeton import JetonAbsentError, JetonExpireError, obtenir_jeton_valide
from acheteur.auth.renouvellement import renouveler_si_necessaire
from acheteur.cli.scan_marche import (
    OFFRE_GROUPEE_CARTES_MAX_PAR_VENDEUR_DEFAUT,
    OFFRE_GROUPEE_VENDEURS_MAX_DEFAUT,
    SEUIL_BONNE_AFFAIRE_DEFAUT,
    SOUS_VENTE_MINI_SEUIL_POURCENT_DEFAUT,
    STOCK_MAX_VENDEUR_DEFAUT,
    _bonnes_affaires,
    _calculer_candidates,
    _completer_par_vitrines_vendeurs,
    _construire_propositions,
    _filtrer_par_stock_vendeur,
    _offres_ouvertes_par_devise_info,
    _petits_vendeurs,
    _soldes_reels,
    formatter_rapport,
)
from acheteur.core.db import creer_tables, session_scope
from acheteur.core.horloge import HorlogeSysteme
from acheteur.core.journalisation import configurer_journalisation
from acheteur.marche import Annonce, annonces_depuis_noeuds_marche
from acheteur.marche.liste_liquidite import (
    JoueurLiquide,
    derniere_maj,
    lire_liste_liquidite,
    liste_perimee,
)
from acheteur.marche.traduction import (
    rarity_brute_depuis_annonce,
    season_eligibility_brute_depuis_annonce,
)
from acheteur.sorare import requetes
from acheteur.sorare.client import SorareClient


def _annonces_des_couples(
    client: SorareClient, couples: list[JoueurLiquide], intervalle_log: int = 100
) -> list[Annonce]:
    """Interroge chaque couple liquide, un appel réseau à la fois (pas
    batché, contrairement à `maj_liste_liquidite.py` — voir DECISIONS.md,
    2026-09-22, pour la piste de batching non encore faite).

    Journalise une ligne de progression tous les `intervalle_log` couples :
    avec plusieurs milliers de couples (2 942 mesurés le 2026-09-22,
    DECISIONS.md), un run sans retour intermédiaire pendant de longues
    minutes ressemble à un blocage — signal réclamé par l'utilisateur.
    """
    annonces: list[Annonce] = []
    debut = time.monotonic()
    for i, couple in enumerate(couples, start=1):
        annonces.extend(_annonces_du_couple(client, couple))
        if i % intervalle_log == 0 or i == len(couples):
            ecoule = time.monotonic() - debut
            print(f"  ... {i}/{len(couples)} couples interrogés ({ecoule:.0f} s)")
    return annonces


def _annonces_du_couple(client: SorareClient, couple: JoueurLiquide) -> list[Annonce]:
    """Les annonces actuelles d'un couple précis (joueur, rareté, saison).

    `annonces_marche(playerSlug=...)` rend TOUTES les annonces du joueur,
    toutes raretés/saisons confondues — filtré ici sur le couple exact que
    la liste liquide a retenu, pour ne pas mélanger un couple liquide avec
    un autre qui ne l'est pas forcément (ex. classic liquide, in-season non
    mesuré ou pas liquide).
    """
    noeuds = requetes.annonces_marche(client, joueur_slug=couple.joueur_slug)
    annonces = annonces_depuis_noeuds_marche(noeuds)
    return [
        a
        for a in annonces
        if rarity_brute_depuis_annonce(a) == couple.rarete
        and season_eligibility_brute_depuis_annonce(a) == couple.season_eligibility
    ]


def main() -> int:
    configurer_journalisation()

    parser = argparse.ArgumentParser(
        description="Passe rapide (lot L9) : lit la liste des joueurs liquides deja "
        "construite (cli/maj_liste_liquidite.py) et cherche leurs annonces actuelles. "
        "Lecture seule cote Sorare, aucun envoi."
    )
    parser.add_argument(
        "--seuil",
        type=int,
        default=SEUIL_BONNE_AFFAIRE_DEFAUT,
        help=f"Seuil de bonne affaire, en %% de la reference nette de taxe (defaut {SEUIL_BONNE_AFFAIRE_DEFAUT}).",
    )
    parser.add_argument(
        "--sortie",
        type=str,
        default=None,
        help="Chemin d'un fichier .txt ou ecrire le rapport (en plus de l'affichage).",
    )
    parser.add_argument(
        "--ignorer-peremption",
        action="store_true",
        help="Continue meme si la liste liquide n'a pas ete rafraichie depuis le delai prevu "
        "(deconseille : les couples retenus peuvent ne plus etre liquides).",
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

        if liste_perimee(session, maintenant):
            maj = derniere_maj(session)
            message = (
                "Liste liquide absente ou perimee "
                f"(derniere reconstruction : {maj if maj else 'jamais'}). "
                "Lance d'abord : python -m acheteur.cli.maj_liste_liquidite"
            )
            if not args.ignorer_peremption:
                print(message, file=sys.stderr)
                return 1
            print(f"  AVERTISSEMENT : {message} (--ignorer-peremption : on continue quand meme)")

        couples = lire_liste_liquidite(session)
        print(f"{len(couples)} couple(s) liquide(s) dans la liste (maj le {derniere_maj(session)}).")
        if not couples:
            print("Rien a scanner.")
            return 0
        print()

        print("Recuperation de l'etat du compte...")
        compte = requetes.etat_compte(client)
        soldes = _soldes_reels(compte)
        offres_ouvertes = _offres_ouvertes_par_devise_info(session)
        print()

        print(f"Recherche des annonces actuelles pour {len(couples)} couple(s)...")
        annonces = _annonces_des_couples(client, couples)
        print(f"  {len(annonces)} annonce(s) trouvee(s)")
        print()

        print("Calcul de la liquidite (deja connue) puis des references reelles...")
        candidates, illiquide, sans_reference = _calculer_candidates(client, horloge, annonces)
        print(f"  {len(candidates)} avec reference exploitable, {illiquide} illiquides "
              f"(ne devrait plus arriver ici), {sans_reference} sans reference")
        print()

        bonnes_affaires = _bonnes_affaires(candidates, args.seuil)
        sous_le_seuil = len(candidates) - len(bonnes_affaires)

        print("Verification de la taille de vitrine des vendeurs concernes...")
        vendeurs_a_verifier = sorted({c.annonce.vendeur_slug for c in bonnes_affaires})
        stocks: dict[str, int | None] = {}
        for slug_vendeur in vendeurs_a_verifier:
            info_vendeur = requetes.stock_vendeur(client, slug_vendeur)
            if info_vendeur is None:
                stocks[slug_vendeur] = None
                continue
            bloc = info_vendeur.get("liveSingleSaleTokenOffers") or {}
            stocks[slug_vendeur] = bloc.get("totalCount")
        bonnes_affaires = _filtrer_par_stock_vendeur(
            bonnes_affaires, stocks, args.seuil, SOUS_VENTE_MINI_SEUIL_POURCENT_DEFAUT,
            STOCK_MAX_VENDEUR_DEFAUT,
        )
        print(f"  {len(bonnes_affaires)} candidate(s) apres filtre de joignabilite")
        print()

        petits_vendeurs = _petits_vendeurs(
            bonnes_affaires, stocks, STOCK_MAX_VENDEUR_DEFAUT, OFFRE_GROUPEE_VENDEURS_MAX_DEFAUT,
        )
        if petits_vendeurs:
            print(f"Offre groupee reactive : relecture de {len(petits_vendeurs)} "
                  "vitrine(s) de petit(s) vendeur(s)...")
            avant = len(bonnes_affaires)
            bonnes_affaires = _completer_par_vitrines_vendeurs(
                client, horloge, bonnes_affaires, args.seuil,
                SOUS_VENTE_MINI_SEUIL_POURCENT_DEFAUT, petits_vendeurs,
                OFFRE_GROUPEE_CARTES_MAX_PAR_VENDEUR_DEFAUT,
            )
            print(f"  {len(bonnes_affaires) - avant} carte(s) supplementaire(s) qualifiee(s)")
            print()

        propositions, _references = _construire_propositions(bonnes_affaires)

        rapport = formatter_rapport(
            propositions,
            soldes,
            offres_ouvertes,
            nb_annonces_examinees=len(annonces),
            nb_illiquide=illiquide,
            nb_sans_reference=sans_reference,
            nb_sous_le_seuil=sous_le_seuil,
            seuil_pourcent=args.seuil,
        )
        print(rapport)

        if args.sortie:
            with open(args.sortie, "w", encoding="utf-8") as f:
                f.write(rapport)
            print()
            print(f"Rapport ecrit dans {args.sortie}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
