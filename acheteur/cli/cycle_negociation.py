"""L7 : un passage de la machine à états — escalade sur motif, veille
défensive, ré-essai sur expiration (PLAN.md § « La machine à états d'une
négociation »).

Ce script ne fait qu'un seul passage (« un cycle ») sur les lignes du
journal ; la boucle planifiée toutes les 15 min et le mail d'approbation
restent hors périmètre (lot L9). Les décisions elles-mêmes vivent dans
`negociation.etats` (fonctions pures, testées séparément) ; ce module ne
fait qu'aller chercher les données réelles dont ces fonctions ont besoin et
exécuter la décision — escalade via la barrière (`garde_fous`, seul chemin
d'envoi), annulation via `negociation.annulation`.

**Acceptation de contre-offre volontairement hors périmètre** : PLAN.md dit
« on accepte » sans détailler le mécanisme, et `acceptOffer` exige une
préparation et une signature (`prepareAcceptOffer`) jamais exercées contre
l'API réelle — aucune contre-offre n'a encore été observée en conditions
réelles (voir MESURES.md). `negociation.etats.reagir_a_contre_offre` existe
et est testée ; ce script se contente de la signaler (log) sans agir, pour
ne pas écrire de code de signature non vérifié sur un mécanisme qui dépense
de l'argent (CLAUDE.md). Àétendre au premier cas réel observé.

Mode réel à trois verrous (PLAN.md § Garde-fous, règle 9), comme partout
ailleurs :
  1. variable d'environnement ACHETEUR_MODE_REEL=1
  2. flag --mode-reel
  3. re-saisie du montant total à l'invite, une fois par escalade envoyée

Sans les trois, le script réconcilie, affiche ce qu'il ferait pour chaque
ligne, et n'écrit ni n'envoie rien de plus que la réconciliation elle-même.

Usage :
    python -m acheteur.cli.cycle_negociation                    (aperçu seul)
    ACHETEUR_MODE_REEL=1 python -m acheteur.cli.cycle_negociation --mode-reel
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import replace

from sqlalchemy.orm import Session

from acheteur.approbation import confirmer_montant_total, demander_confirmation_utilisateur
from acheteur.auth.jeton import JetonAbsentError, JetonExpireError, obtenir_jeton_valide
from acheteur.auth.renouvellement import renouveler_si_necessaire
from acheteur.core.db import creer_tables, session_scope
from acheteur.core.horloge import Horloge, HorlogeSysteme
from acheteur.core.journalisation import configurer_journalisation
from acheteur.decision import Palier, proposer_simple
from acheteur.garde_fous import ContexteBarriere, GuardrailViolation, envoyer_offre_proposal
from acheteur.marche import Annonce, Devise, Montant, annonce_depuis_noeud_marche
from acheteur.negociation import (
    ActionNegociation,
    EtatOffre,
    OffreJournal,
    annuler_ligne,
    lignes_ouvertes,
    reagir_a_expiration,
    reagir_a_refus,
    reagir_a_veille,
    reconcilier,
    reessai_expiration_deja_fait,
)
from acheteur.sorare import requetes
from acheteur.sorare.client import SorareClient

# Lignes closes que la machine à états doit encore examiner — pas ACCEPTEE
# (rien à réagir) ni ANNULEE/EN_SOMMEIL (déjà traitées par un cycle précédent).
_ETATS_A_EXAMINER = (EtatOffre.REFUSEE, EtatOffre.EXPIREE)


def _rafraichir_annonce(client: SorareClient, ligne: OffreJournal) -> Annonce | None:
    """Recherche l'annonce actuelle pour ce (joueur, vendeur) — None si elle
    a disparu (vendue, retirée) : c'est ce que `reagir_a_veille` et
    `reagir_a_expiration` ont besoin de savoir avant d'agir."""
    noeuds = requetes.annonces_marche(client, joueur_slug=ligne.joueur_slug)
    for noeud in noeuds:
        annonce = annonce_depuis_noeud_marche(noeud)
        if annonce is not None and annonce.vendeur_slug == ligne.vendeur_slug:
            return annonce
    return None


def _deja_escaladee(session: Session, ligne: OffreJournal) -> bool:
    """Vrai si une ligne d'escalade a déjà été créée pour cette ligne close —
    évite de la retenter à chaque cycle (une escalade dépense de l'argent,
    contrairement à un abandon ou un sommeil)."""
    return (
        session.query(OffreJournal).filter_by(offre_precedente_id=ligne.id).first() is not None
    )


def _lignes_a_examiner(session: Session) -> list[OffreJournal]:
    lignes = (
        session.query(OffreJournal)
        .filter(OffreJournal.etat.in_(_ETATS_A_EXAMINER))
        .filter(OffreJournal.import_automatique.is_(False))
        .order_by(OffreJournal.id)
        .all()
    )
    return [ligne for ligne in lignes if not _deja_escaladee(session, ligne)]


def _soldes_reels(compte: dict) -> dict[Devise, Montant]:
    balances = compte.get("availableBalances") or {}
    eur = ((balances.get("eurCents") or {}).get("eurCents")) or 0
    wei = ((balances.get("wei") or {}).get("wei")) or 0
    return {
        Devise.EUR: Montant(int(eur), Devise.EUR),
        Devise.ETH: Montant(int(wei), Devise.ETH),
    }


def _offres_ouvertes_par_vendeur_reelles(session: Session) -> dict[str, int]:
    """Nombre d'offres réellement ouvertes par vendeur (règle 7, anti-
    démarchage) — PAS un montant par devise : `soldes_par_devise` (Sorare)
    a déjà déduit les offres réelles ouvertes avant ce cycle
    (`totalBalance - availableBalance` colle exactement à leur somme,
    constaté contre le compte réel 2026-09-21, signalé par l'utilisateur —
    voir DECISIONS.md/MESURES.md). Les recompter dans
    `offres_ouvertes_par_devise` doublerait la déduction et rendrait la
    règle 1 plus restrictive que prévu ; voir `_executer_reactions`, qui
    part d'un cumul vide pour cette règle-là et ne l'incrémente qu'avec les
    escalades réellement envoyées *pendant ce cycle*."""
    par_vendeur: dict[str, int] = {}
    for ligne in lignes_ouvertes(session, mode_simulation=False):
        par_vendeur[ligne.vendeur_slug] = par_vendeur.get(ligne.vendeur_slug, 0) + 1
    return par_vendeur


def _executer_veille(
    session: Session,
    client: SorareClient,
    horloge: Horloge,
    *,
    mode_reel_deverrouille: bool,
) -> None:
    """Veille défensive : annule toute offre réelle encore ouverte dont
    l'annonce a disparu ou dont le prix affiché est passé sous notre offre.

    Ignore les lignes `import_automatique` (offres groupées ou faites à la
    main, découvertes par la réconciliation) : `_rafraichir_annonce` ne sait
    interroger qu'un seul `joueur_slug` à la fois, alors que
    `reconciliation.importer_ligne_manuelle` stocke plusieurs joueurs
    séparés par des virgules (ou `"inconnu"` si aucun) pour une offre
    groupée — une recherche sur cette chaîne ne trouve jamais rien et
    déclencherait une fausse « annonce disparue » sur une offre légitime
    que le bot n'a de toute façon pas décidée (constaté en session, lot L7,
    voir MESURES.md). Ces lignes restent à la revue humaine.
    """
    for ligne in lignes_ouvertes(session, mode_simulation=False):
        if ligne.import_automatique:
            continue
        annonce = _rafraichir_annonce(client, ligne)
        decision = reagir_a_veille(
            annonce_disparue=annonce is None,
            prix_demande_actuel=annonce.prix_demande.valeur if annonce else None,
            devise_prix_demande_actuel=annonce.prix_demande.devise if annonce else None,
            notre_offre_montant=ligne.montant_offre_valeur,
            notre_offre_devise=ligne.montant_offre_devise,
        )
        if decision.action != ActionNegociation.ANNULER:
            continue

        print(f"Veille : {ligne.joueur_slug}/{ligne.vendeur_slug} — {decision.raison}")
        if not mode_reel_deverrouille:
            print("  (aperçu seul, aucune annulation exécutée)")
            continue

        blockchain_id = None
        for noeud in requetes.offres_envoyees(client):
            if noeud.get("id") == ligne.sorare_id:
                blockchain_id = noeud.get("blockchainId")
                break
        annuler_ligne(
            ligne,
            session,
            horloge,
            blockchain_id=blockchain_id,
            mode_simulation=False,
            client=client,
        )
        session.commit()
        print("  ✓ annulée")


def _executer_reactions(
    session: Session,
    client: SorareClient,
    horloge: Horloge,
    contexte_base: ContexteBarriere,
    *,
    env_var_mode_reel: bool,
    cli_arg_mode_reel: bool,
) -> None:
    """Un cycle peut escalader plusieurs lignes : `contexte_base.soldes_par_devise`
    (Sorare) a déjà déduit tout ce qui était ouvert *avant* ce cycle, donc on
    parcourt les lignes avec un cumul par devise qui démarre à zéro et ne
    grandit qu'avec les escalades réellement envoyées ici — sinon la
    deuxième escalade du même cycle recompterait la première ET l'historique
    (voir `_offres_ouvertes_par_vendeur_reelles`). Le cumul par vendeur, lui,
    part de l'historique réel (règle 7, anti-démarchage — pas un budget)."""
    mode_reel_deverrouille = env_var_mode_reel and cli_arg_mode_reel
    cumul_devise: dict[Devise, int] = {}
    cumul_vendeur: dict[str, int] = dict(contexte_base.offres_ouvertes_par_vendeur)

    for ligne in _lignes_a_examiner(session):
        if ligne.etat == EtatOffre.REFUSEE:
            decision = reagir_a_refus(ligne.motif_refus, Palier(ligne.palier))
            annonce = None
        else:  # EXPIREE
            annonce = _rafraichir_annonce(client, ligne)
            decision = reagir_a_expiration(
                annonce_toujours_vivante=annonce is not None,
                prix_inchange=annonce is not None
                and annonce.prix_demande.valeur == ligne.prix_demande_valeur,
                reessai_deja_fait=reessai_expiration_deja_fait(session, ligne),
                palier_courant=Palier(ligne.palier),
            )

        print(f"{ligne.joueur_slug}/{ligne.vendeur_slug} (palier {ligne.palier}%) : "
              f"{decision.action.value} — {decision.raison}")

        if decision.action == ActionNegociation.SOMMEIL:
            ligne.etat = EtatOffre.EN_SOMMEIL
            ligne.maj_le = horloge.maintenant()
            session.commit()
            continue

        if decision.action != ActionNegociation.ESCALADER:
            continue  # ABANDONNER : ligne close reste telle quelle

        if annonce is None:
            annonce = _rafraichir_annonce(client, ligne)
        if annonce is None:
            print("  annonce disparue entre-temps, escalade impossible")
            continue

        if not mode_reel_deverrouille:
            montant = (annonce.prix_demande.valeur * int(decision.palier_suivant)) // 100
            print(f"  (aperçu seul) offrirait {Montant(montant, annonce.prix_demande.devise)} "
                  f"au palier {int(decision.palier_suivant)}%")
            continue

        proposition = proposer_simple(annonce, ligne.reference_prix_valeur, decision.palier_suivant)
        devise_str = "EUR" if annonce.prix_demande.devise == Devise.EUR else "ETH"
        montant_retape = demander_confirmation_utilisateur(
            proposition.montant_offre, devise=devise_str
        )
        if montant_retape is None or not confirmer_montant_total(
            proposition.montant_offre, montant_retape, devise_str
        ):
            print("  escalade annulée par l'utilisateur")
            continue

        devise = annonce.prix_demande.devise
        contexte = replace(
            contexte_base,
            offres_ouvertes_par_devise=cumul_devise,
            offres_ouvertes_par_vendeur=cumul_vendeur,
        )
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
                offre_precedente_id=ligne.id,
            )
            session.commit()
            cumul_devise[devise] = cumul_devise.get(devise, 0) + proposition.montant_offre
            cumul_vendeur[annonce.vendeur_slug] = cumul_vendeur.get(annonce.vendeur_slug, 0) + 1
            print("  ✓ escalade envoyée")
        except GuardrailViolation as exc:
            print(f"  ✗ garde-fou : {exc}")
            session.rollback()


def main() -> int:
    configurer_journalisation()

    parser = argparse.ArgumentParser(
        description="L7 : un cycle de la machine a etats (escalade, veille, "
        "reessai sur expiration). Voir le docstring du module pour le detail."
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

    env_var_mode_reel = os.environ.get("ACHETEUR_MODE_REEL") == "1"
    cli_arg_mode_reel = args.mode_reel
    mode_reel_deverrouille = env_var_mode_reel and cli_arg_mode_reel

    with session_scope() as session, SorareClient(jwt=info.token, jwt_aud=info.aud) as client:
        print("Réconciliation avec Sorare...")
        rapport = reconcilier(session, client, horloge)
        session.commit()
        if rapport.cycle_suspendu:
            print()
            print("⚠ CYCLE SUSPENDU — une dépense non décidée par le bot a été détectée.")
            print("  Vérifier les offres importées (python -m acheteur.cli.reconcilier).")
            return 1
        print(f"  OK ({len(rapport.appariees)} appariées)")
        print()

        if not mode_reel_deverrouille:
            print("Aperçu seul (mode réel non déverrouillé) — aucune écriture au-delà de la "
                  "réconciliation, aucune annulation, aucun envoi.")
            print("  Pour agir réellement :")
            print("    ACHETEUR_MODE_REEL=1 python -m acheteur.cli.cycle_negociation --mode-reel")
            print()

        print("=== Veille défensive ===")
        _executer_veille(session, client, horloge, mode_reel_deverrouille=mode_reel_deverrouille)
        print()

        print("=== Réactions (refus / expiration) ===")
        compte = requetes.etat_compte(client)
        soldes = _soldes_reels(compte)
        # soldes (Sorare) a déjà déduit tout ce qui est ouvert avant ce
        # cycle — offres_ouvertes_par_devise part vide, voir _executer_reactions.
        contexte = ContexteBarriere(
            soldes_par_devise=soldes,
            offres_ouvertes_par_devise={},
            offres_ouvertes_par_vendeur=_offres_ouvertes_par_vendeur_reelles(session),
            solde_timestamp=horloge.maintenant(),
            taux_change_timestamp=None,
            plafond_offres_par_vendeur=5,
        )
        _executer_reactions(
            session,
            client,
            horloge,
            contexte,
            env_var_mode_reel=env_var_mode_reel,
            cli_arg_mode_reel=cli_arg_mode_reel,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
