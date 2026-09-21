"""L6 : premier envoi réel — une seule offre, sur la carte la moins chère
actuellement en vente à prix fixe sur le marché, approuvée à la main
(PLAN.md § Lots livrables).

L5 s'arrêtait juste avant l'envoi. Ici, on envoie — une fois, un montant de
l'ordre de 1€ — pour prouver que le chemin complet (marché réel → référence
réelle → barrière → prepareOffer → createDirectOffer) fonctionne de bout en
bout. La machine à états complète (escalade, veille, contre-offres) reste
hors périmètre : c'est le lot L7.

Sélection : parmi les 100 annonces à prix fixe les plus récemment mises à
jour sur l'ensemble du marché (`liveSingleSaleOffers`, triée par fraîcheur
côté API — pas par prix), triées ici par prix croissant, on retient la
première qui a une référence de prix réelle valide (médiane sur 7 jours,
au moins 3 ventes de même rareté et même éligibilité de saison — contrainte
portée par la base, `negociation/journal.py`).

**Ce n'est pas la carte la moins chère du marché entier, seulement la moins
chère de cet échantillon glissant** (DECISIONS.md, 2026-09-21) : une annonce
plus ancienne et moins chère peut exister ailleurs sur le marché sans
apparaître dans les 100 annonces les plus fraîches. Suffisant pour L6 (prouver
que l'envoi réel fonctionne) ; élargir la recherche (pagination, ou
`liveSingleSaleOffers(playerSlug:)` par joueur sur la population liquide de
L3) est un sujet de portée L7+.

Mode réel à trois verrous (PLAN.md § Garde-fous, règle 9), comme partout
ailleurs dans le projet :
  1. variable d'environnement ACHETEUR_MODE_REEL=1
  2. flag --mode-reel
  3. re-saisie du montant total à l'invite

Sans les trois, le script s'arrête après avoir affiché ce qu'il aurait
proposé — aucune ligne n'est écrite en base, pour ne pas occuper le couple
(joueur, vendeur) avec une ligne simulée qui bloquerait le vrai essai.

Usage :
    python -m acheteur.cli.premiere_offre_reelle                    (aperçu seul)
    ACHETEUR_MODE_REEL=1 python -m acheteur.cli.premiere_offre_reelle --mode-reel
"""

from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy.orm import Session

from acheteur.approbation import confirmer_montant_total, demander_confirmation_utilisateur
from acheteur.auth.jeton import JetonAbsentError, JetonExpireError, obtenir_jeton_valide
from acheteur.auth.renouvellement import renouveler_si_necessaire
from acheteur.core.db import creer_tables, session_scope
from acheteur.core.horloge import Horloge, HorlogeSysteme
from acheteur.core.journalisation import configurer_journalisation
from acheteur.decision import Palier, proposer_simple
from acheteur.decision.selecteur import est_bonne_affaire
from acheteur.garde_fous import ContexteBarriere, GuardrailViolation, envoyer_offre_proposal
from acheteur.marche import (
    Annonce,
    Devise,
    Montant,
    annonces_depuis_noeuds_marche,
    rarity_brute_depuis_annonce,
    reference_prix_joueur,
    season_eligibility_brute_depuis_annonce,
    ventes_depuis_noeuds_prix,
)
from acheteur.negociation import lignes_ouvertes, reconcilier
from acheteur.sorare import requetes
from acheteur.sorare.client import SorareClient

NOMBRE_ANNONCES_EXAMINEES = 100
# L'API Sorare plafonne tokenPrices(first: ...) à 20 (constaté au premier run
# réel, lot L6, MESURES.md 2026-09-21 — pas documenté dans le SDL local).
NOMBRE_VENTES_EXAMINEES = 20


def trouver_meilleure_candidate(
    client: SorareClient,
    horloge: Horloge,
    devise: Devise | None = None,
    seuil_pourcent: int = 90,
) -> tuple[Annonce, Montant] | None:
    """Cherche, parmi les annonces les moins chères du marché, la première
    qui a une référence de prix réelle valide **et** qui est une bonne
    affaire (`decision.selecteur.est_bonne_affaire`, prix demandé <=
    `seuil_pourcent` % de la référence).

    Bug réel trouvé en conditions réelles (2026-09-21, voir DECISIONS.md) :
    ce filtre était absent jusqu'ici — la fonction ne vérifiait qu'« a une
    référence » (>= 3 ventes/7j), pas « le prix est intéressant ». Elle
    pouvait donc retenir une candidate dont le prix demandé est très
    au-dessus de sa propre référence (ex. carte qui se négocie
    invariablement à 0,22 € mais dont le vendeur en demandait 0,40 € — le
    bot l'a achetée à 0,28 €, en payant plus que la valeur réelle du
    marché). `scan_marche.py` appliquait déjà ce filtre ; il manquait ici.

    Args:
        devise: si fourni, ne considère que les annonces dans cette devise.
            Sans filtre, le tri mélange centimes EUR et wei ETH sur la même
            échelle numérique — un prix EUR (quelques centaines) passe
            presque toujours avant un prix ETH (10^14+), donc en pratique
            aucune candidate ETH n'était jamais retenue (constaté en session
            réelle, 2026-09-21 : seul le rail ETH est signable pour l'instant,
            voir DECISIONS.md — filtrer permet de tester ce rail précisément).
        seuil_pourcent: seuil de bonne affaire (défaut 90%, comme
            `scan_marche.py` et `decision/selecteur.py`).

    Returns:
        (annonce, référence de prix) ou None si aucune candidate n'a de
        référence exploitable **et** n'est une bonne affaire parmi celles
        examinées.
    """
    noeuds_marche = requetes.annonces_marche(client, premieres=NOMBRE_ANNONCES_EXAMINEES)
    annonces = annonces_depuis_noeuds_marche(noeuds_marche)
    if devise is not None:
        annonces = [a for a in annonces if a.prix_demande.devise == devise]
    annonces.sort(key=lambda a: a.prix_demande.valeur)

    maintenant = horloge.maintenant()
    for annonce in annonces:
        noeuds_prix = requetes.historique_prix_joueur(
            client,
            annonce.joueur.slug,
            rarity_brute_depuis_annonce(annonce),
            premieres=NOMBRE_VENTES_EXAMINEES,
            season_eligibility=season_eligibility_brute_depuis_annonce(annonce),
        )
        ventes = ventes_depuis_noeuds_prix(noeuds_prix, annonce.joueur)
        reference = reference_prix_joueur(annonce.joueur, ventes, maintenant)
        if reference is None:
            continue
        if reference.devise != annonce.prix_demande.devise:
            # Référence et prix demandé dans deux devises différentes :
            # rien à comparer, on passe à la candidate suivante plutôt que
            # de mélanger les unités (CLAUDE.md).
            continue
        if not est_bonne_affaire(annonce, reference, seuil_pourcent):
            continue
        return annonce, reference

    return None


def _soldes_reels(compte: dict) -> dict[Devise, Montant]:
    balances = (compte.get("availableBalances") or {})
    eur = ((balances.get("eurCents") or {}).get("eurCents")) or 0
    wei = ((balances.get("wei") or {}).get("wei")) or 0
    return {
        Devise.EUR: Montant(int(eur), Devise.EUR),
        Devise.ETH: Montant(int(wei), Devise.ETH),
    }


def _offres_ouvertes_par_vendeur_reelles(session: Session) -> dict[str, int]:
    """Nombre d'offres réellement envoyées et encore ouvertes, par vendeur —
    pour la règle 7 (anti-démarchage), pas pour un calcul de solde.

    Ne compte QUE le nombre d'offres par vendeur, jamais leur montant cumulé
    par devise : `ContexteBarriere.soldes_par_devise` (le solde tel que
    Sorare le renvoie) a déjà déduit ces offres réelles ouvertes —
    `totalBalance - availableBalance` colle exactement à leur somme
    (constaté contre le compte réel, 2026-09-21, signalé par l'utilisateur).
    Les recompter dans `offres_ouvertes_par_devise` rendrait la règle 1 plus
    restrictive que prévu. Ce script n'envoie qu'une seule offre par
    exécution, donc `offres_ouvertes_par_devise` reste `{}` (voir plus bas) :
    rien n'a encore été décidé dans ce cycle avant cette offre-ci."""
    par_vendeur: dict[str, int] = {}
    for ligne in lignes_ouvertes(session, mode_simulation=False):
        par_vendeur[ligne.vendeur_slug] = par_vendeur.get(ligne.vendeur_slug, 0) + 1
    return par_vendeur


def _afficher_proposition(annonce: Annonce, reference: Montant, montant_offre: int) -> None:
    print()
    print("=" * 72)
    print("CANDIDATE RETENUE")
    print("=" * 72)
    print(f"  Joueur         : {annonce.joueur.nom} ({annonce.joueur.slug})")
    print(f"  Rareté         : {annonce.joueur.rareté.nom}")
    print(f"  Saison         : {'in-season' if annonce.in_season else 'classic'}")
    print(f"  Vendeur        : {annonce.vendeur_slug}")
    print(f"  Asset ID       : {annonce.asset_id}")
    print(f"  Prix demandé   : {annonce.prix_demande}")
    print(f"  Référence      : {reference} (médiane, 7j, >= 3 ventes, "
          f"{'in-season' if annonce.in_season else 'classic'} uniquement)")
    print(f"  Palier         : {int(Palier.PREMIER)}%")
    print(f"  Montant offert : {Montant(montant_offre, annonce.prix_demande.devise)}")
    print("=" * 72)


def main() -> int:
    configurer_journalisation()  # bascule stdout/stderr en UTF-8 avant tout print()

    parser = argparse.ArgumentParser(
        description="L6 : premier envoi réel, une seule offre sur la carte la moins "
        "chère du marché avec référence réelle. Voir le docstring du module pour le détail."
    )
    parser.add_argument(
        "--mode-reel",
        action="store_true",
        help="Deuxième des trois verrous du mode réel (voir PLAN.md § Garde-fous, règle 9).",
    )
    parser.add_argument(
        "--devise",
        choices=["EUR", "ETH"],
        default=None,
        help="Ne considérer que les annonces dans cette devise. Sans filtre, une "
        "candidate EUR est presque toujours choisie (voir docstring de "
        "trouver_meilleure_candidate) — seul le rail ETH est signable actuellement.",
    )
    parser.add_argument(
        "--seuil",
        type=int,
        default=90,
        help="Seuil de bonne affaire, en %% de la référence (défaut 90, "
        "comme scan_marche.py).",
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
        # === 1. RÉCONCILIATION : obligatoire avant tout envoi (PLAN.md) ===
        print("Réconciliation avec Sorare...")
        rapport = reconcilier(session, client, horloge)
        if rapport.cycle_suspendu:
            print()
            print("⚠ CYCLE SUSPENDU — une dépense non décidée par le bot a été détectée.")
            print("  Vérifier les offres importées (python -m acheteur.cli.reconcilier).")
            return 1
        print("  OK")
        print()

        # === 2. ÉTAT DU COMPTE RÉEL ===
        print("Récupération de l'état du compte...")
        compte = requetes.etat_compte(client)
        soldes = _soldes_reels(compte)
        print(f"  Solde EUR : {soldes[Devise.EUR]}")
        print(f"  Solde ETH : {soldes[Devise.ETH]}")
        print()

        # === 3. RECHERCHE DE LA CANDIDATE ===
        print(f"Recherche de la moins chère avec référence réelle "
              f"(parmi les {NOMBRE_ANNONCES_EXAMINEES} annonces les plus récentes du "
              f"marché, pas forcément les moins chères du marché entier)...")
        devise_filtre = Devise[args.devise] if args.devise else None
        candidate = trouver_meilleure_candidate(
            client, horloge, devise=devise_filtre, seuil_pourcent=args.seuil
        )
        if candidate is None:
            print("Aucune candidate : aucune des annonces examinées n'a une référence "
                  "de prix réelle valide (>= 3 ventes sur 7 jours). Fin.")
            return 0
        annonce, reference = candidate

        proposition = proposer_simple(annonce, reference.valeur, Palier.PREMIER)
        _afficher_proposition(annonce, reference, proposition.montant_offre)

        # === 4. CONTEXTE BARRIÈRE (soldes/offres ouvertes RÉELS) ===
        # `soldes` (Sorare) a déjà déduit toutes les offres réelles ouvertes
        # avant ce cycle — offres_ouvertes_par_devise reste vide : ce script
        # ne décide qu'une seule offre par exécution (voir
        # _offres_ouvertes_par_vendeur_reelles ci-dessus, et DECISIONS.md).
        contexte = ContexteBarriere(
            soldes_par_devise=soldes,
            offres_ouvertes_par_devise={},
            offres_ouvertes_par_vendeur=_offres_ouvertes_par_vendeur_reelles(session),
            solde_timestamp=horloge.maintenant(),
            taux_change_timestamp=None,  # pas de conversion : même devise offre/demande
            plafond_offres_par_vendeur=5,
        )

        # === 5. TROIS VERROUS DU MODE RÉEL ===
        env_var_mode_reel = os.environ.get("ACHETEUR_MODE_REEL") == "1"
        cli_arg_mode_reel = args.mode_reel

        if not (env_var_mode_reel and cli_arg_mode_reel):
            print()
            print("Aperçu seul (mode réel non déverrouillé) — aucune écriture, aucun envoi.")
            print("  Pour envoyer réellement :")
            print("    ACHETEUR_MODE_REEL=1 python -m acheteur.cli.premiere_offre_reelle --mode-reel")
            return 0

        # === 6. VALIDATION MANUELLE — retaper le montant total ===
        devise_str = "EUR" if annonce.prix_demande.devise == Devise.EUR else "ETH"
        print()
        print("Mode réel déverrouillé (env var + flag). Dernier verrou : confirmation manuelle.")
        montant_retape = demander_confirmation_utilisateur(
            proposition.montant_offre, devise=devise_str
        )
        if montant_retape is None:
            print("Annulation.")
            session.rollback()
            return 0
        if not confirmer_montant_total(proposition.montant_offre, montant_retape, devise_str):
            session.rollback()
            return 0

        # === 7. ENVOI RÉEL — passe par la barrière, seul chemin possible ===
        print()
        print("Envoi de l'offre réelle...")
        try:
            envoyer_offre_proposal(
                proposition,
                contexte,
                session,
                horloge,
                mode_simulation=False,
                env_var_mode_reel=env_var_mode_reel,
                cli_arg_mode_reel=cli_arg_mode_reel,
                montant_retape=montant_retape,
                client=client,
            )
        except GuardrailViolation as exc:
            print(f"✗ Garde-fou : {exc}")
            session.rollback()
            return 1

        session.commit()
        print("✓ Ligne enregistrée. Vérifier le résultat avec "
              "python -m acheteur.cli.reconcilier avant tout nouvel envoi.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
