"""L6 : premier envoi réel — une seule offre, sur la carte la moins chère
actuellement en vente à prix fixe sur le marché, approuvée à la main
(PLAN.md § Lots livrables).

L5 s'arrêtait juste avant l'envoi. Ici, on envoie — une fois, un montant de
l'ordre de 1€ — pour prouver que le chemin complet (marché réel → référence
réelle → barrière → prepareOffer → createDirectOffer) fonctionne de bout en
bout. La machine à états complète (escalade, veille, contre-offres) reste
hors périmètre : c'est le lot L7.

Sélection : parmi les annonces à prix fixe du marché (`liveSingleSaleOffers`),
triées par prix croissant, on retient la première qui a une référence de
prix réelle valide (médiane sur 7 jours, au moins 3 ventes — contrainte
portée par la base, `negociation/journal.py`). Ce n'est *pas* nécessairement
« la carte la moins chère absolue » si les moins chères n'ont pas assez
d'historique — impossible d'enregistrer une ligne sans référence.

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
from acheteur.garde_fous import ContexteBarriere, GuardrailViolation, envoyer_offre_proposal
from acheteur.marche import (
    Annonce,
    Devise,
    Montant,
    annonces_depuis_noeuds_marche,
    reference_prix_joueur,
    ventes_depuis_noeuds_prix,
)
from acheteur.negociation import lignes_ouvertes, reconcilier
from acheteur.sorare import requetes
from acheteur.sorare.client import SorareClient

NOMBRE_ANNONCES_EXAMINEES = 100
# L'API Sorare plafonne tokenPrices(first: ...) à 20 (constaté au premier run
# réel, lot L6, MESURES.md 2026-09-21 — pas documenté dans le SDL local).
NOMBRE_VENTES_EXAMINEES = 20


def _rarity_brute(annonce: Annonce) -> str:
    """Reconstruit la valeur brute de l'enum `Rarity` Sorare depuis le nom
    lisible stocké sur `Rareté` (« Super Rare » -> « super_rare »)."""
    return annonce.joueur.rareté.nom.lower().replace(" ", "_")


def _season_eligibility_brute(annonce: Annonce) -> str:
    """`SeasonEligibility` Sorare (`CLASSIC`/`IN_SEASON`) depuis `Annonce.in_season`.

    Une carte in-season (éligible aux compétitions en cours) et une carte
    classic du même joueur/rareté ne se vendent pas au même prix : sans ce
    filtre sur `tokenPrices`, la référence mélange deux populations de
    ventes sans rapport (constaté en session, lot L6, voir MESURES.md).
    """
    return "IN_SEASON" if annonce.in_season else "CLASSIC"


def trouver_meilleure_candidate(
    client: SorareClient, horloge: Horloge
) -> tuple[Annonce, Montant] | None:
    """Cherche, parmi les annonces les moins chères du marché, la première
    qui a une référence de prix réelle valide.

    Returns:
        (annonce, référence de prix) ou None si aucune candidate n'a de
        référence exploitable parmi celles examinées.
    """
    noeuds_marche = requetes.annonces_marche(client, premieres=NOMBRE_ANNONCES_EXAMINEES)
    annonces = annonces_depuis_noeuds_marche(noeuds_marche)
    annonces.sort(key=lambda a: a.prix_demande.valeur)

    maintenant = horloge.maintenant()
    for annonce in annonces:
        noeuds_prix = requetes.historique_prix_joueur(
            client,
            annonce.joueur.slug,
            _rarity_brute(annonce),
            premieres=NOMBRE_VENTES_EXAMINEES,
            season_eligibility=_season_eligibility_brute(annonce),
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


def _offres_ouvertes_reelles(session: Session) -> tuple[dict[Devise, int], dict[str, int]]:
    """Somme des offres réellement envoyées et encore ouvertes (pas les
    lignes simulées : elles n'engagent aucun solde réel)."""
    par_devise: dict[Devise, int] = {}
    par_vendeur: dict[str, int] = {}
    for ligne in lignes_ouvertes(session, mode_simulation=False):
        par_devise[ligne.montant_offre_devise] = (
            par_devise.get(ligne.montant_offre_devise, 0) + ligne.montant_offre_valeur
        )
        par_vendeur[ligne.vendeur_slug] = par_vendeur.get(ligne.vendeur_slug, 0) + 1
    return par_devise, par_vendeur


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
        print(f"Recherche de la carte la moins chère avec référence réelle "
              f"(parmi {NOMBRE_ANNONCES_EXAMINEES} annonces)...")
        candidate = trouver_meilleure_candidate(client, horloge)
        if candidate is None:
            print("Aucune candidate : aucune des annonces examinées n'a une référence "
                  "de prix réelle valide (>= 3 ventes sur 7 jours). Fin.")
            return 0
        annonce, reference = candidate

        proposition = proposer_simple(annonce, reference.valeur, Palier.PREMIER)
        _afficher_proposition(annonce, reference, proposition.montant_offre)

        # === 4. CONTEXTE BARRIÈRE (soldes/offres ouvertes RÉELS) ===
        offres_ouvertes_devise, offres_ouvertes_vendeur = _offres_ouvertes_reelles(session)
        contexte = ContexteBarriere(
            soldes_par_devise=soldes,
            offres_ouvertes_par_devise=offres_ouvertes_devise,
            offres_ouvertes_par_vendeur=offres_ouvertes_vendeur,
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
