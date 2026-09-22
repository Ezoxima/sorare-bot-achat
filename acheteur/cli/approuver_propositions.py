"""Lot L9 (partie manquante, PLAN.md) : approbation asynchrone des
propositions écrites par `cli/proposer_periodique.py` — le pendant humain
(phase 1) de « propose, tu valides ».

Lit le dernier fichier de propositions (ou `--fichier`), affiche le tableau,
laisse choisir quelles lignes envoyer, fait retaper le montant total **par
devise** (protocole du virement bancaire, PLAN.md), puis envoie chaque ligne
choisie via la barrière — même chemin unique que tout le reste du projet
(`test_unique_path.py`).

**Chaque annonce est revérifiée en direct juste avant son envoi** (comme
`cycle_negociation._rafraichir_annonce`) : le fichier peut avoir plusieurs
minutes (voire plusieurs heures si tu n'es pas devant l'écran) — une annonce
disparue ou dont le prix a changé depuis le scan est écartée plutôt
qu'envoyée sur une base obsolète.

Mode réel à trois verrous (PLAN.md § Garde-fous, règle 9), comme partout
ailleurs :
  1. variable d'environnement ACHETEUR_MODE_REEL=1
  2. flag --mode-reel
  3. re-saisie du montant total (par devise) pour confirmer

Sans les trois, le script affiche le fichier et s'arrête — aucune écriture,
aucun envoi.

Usage :
    python -m acheteur.cli.approuver_propositions                    (aperçu)
    ACHETEUR_MODE_REEL=1 python -m acheteur.cli.approuver_propositions --mode-reel
    python -m acheteur.cli.approuver_propositions --fichier <chemin.json> --mode-reel
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import replace
from pathlib import Path

from sqlalchemy.orm import Session

from acheteur.approbation import (
    DOSSIER_PROPOSITIONS_DEFAUT,
    charger_propositions,
    confirmer_montant_total,
    demander_confirmation_utilisateur,
    dernier_fichier_propositions,
    fichier_perime,
)
from acheteur.auth.jeton import JetonAbsentError, JetonExpireError, obtenir_jeton_valide
from acheteur.auth.renouvellement import renouveler_si_necessaire
from acheteur.cli.scan_marche import _devise_et_montant, _soldes_reels
from acheteur.core.db import creer_tables, session_scope
from acheteur.core.horloge import HorlogeSysteme
from acheteur.core.journalisation import configurer_journalisation
from acheteur.decision.proposition import PropositionGroupe, PropositionSimple
from acheteur.garde_fous import ContexteBarriere, GuardrailViolation, envoyer_offre_proposal
from acheteur.marche import Annonce, Devise, annonce_depuis_noeud_marche
from acheteur.negociation import lignes_ouvertes, reconcilier
from acheteur.sorare import requetes
from acheteur.sorare.client import SorareClient


def _afficher_propositions(propositions: list[PropositionSimple | PropositionGroupe]) -> None:
    for i, p in enumerate(propositions, start=1):
        devise, montant = _devise_et_montant(p)
        if isinstance(p, PropositionSimple):
            a = p.annonce
            print(
                f"[{i}] {a.joueur.nom} ({a.joueur.rareté.nom}) chez {a.vendeur_slug} — "
                f"demandé {a.prix_demande}, offert {montant} {devise.value} "
                f"(palier {int(p.palier)}%)"
            )
        else:
            vendeur = p.annonces[0].vendeur_slug
            noms = ", ".join(a.joueur.nom for a in p.annonces)
            print(
                f"[{i}] Groupe chez {vendeur} ({len(p.annonces)} cartes : {noms}) — "
                f"total offert {montant} {devise.value} (palier {int(p.palier)}%)"
            )


def _parser_selection(saisie: str, n: int) -> list[int] | None:
    """Parse une sélection utilisateur en indices 0-based.

    Accepte "toutes", "aucune", ou une liste d'indices 1-based séparés par
    des virgules ("1,3,5"). Renvoie None si la saisie est invalide (index
    hors bornes, non numérique) — l'appelant redemande plutôt que de deviner
    ce que l'utilisateur voulait dire.
    """
    saisie = saisie.strip().lower()
    if saisie == "aucune":
        return []
    if saisie == "toutes":
        return list(range(n))

    indices: list[int] = []
    for morceau in saisie.split(","):
        morceau = morceau.strip()
        if not morceau.isdigit():
            return None
        idx = int(morceau) - 1
        if not (0 <= idx < n):
            return None
        indices.append(idx)
    return indices


def _totaux_par_devise(
    propositions: list[PropositionSimple | PropositionGroupe], indices: list[int]
) -> dict[Devise, int]:
    totaux: dict[Devise, int] = {}
    for i in indices:
        devise, montant = _devise_et_montant(propositions[i])
        totaux[devise] = totaux.get(devise, 0) + montant
    return totaux


def _rafraichir_annonce(
    client: SorareClient, joueur_slug: str, vendeur_slug: str
) -> Annonce | None:
    """Revérifie qu'une annonce est toujours vivante, au même endroit — voir
    docstring du module : le fichier de propositions peut être vieux de
    plusieurs minutes, jamais réutilisé aveuglément."""
    noeuds = requetes.annonces_marche(client, joueur_slug=joueur_slug)
    for noeud in noeuds:
        annonce = annonce_depuis_noeud_marche(noeud)
        if annonce is not None and annonce.vendeur_slug == vendeur_slug:
            return annonce
    return None


def _proposition_toujours_valide(
    client: SorareClient, proposition: PropositionSimple | PropositionGroupe
) -> bool:
    """Vrai si toutes les annonces de la proposition existent encore, chez
    le même vendeur, au même prix demandé — sinon la proposition (calculée
    sur un prix qui n'est peut-être plus le bon) est écartée."""
    annonces = (
        [proposition.annonce]
        if isinstance(proposition, PropositionSimple)
        else list(proposition.annonces)
    )
    for annonce in annonces:
        actuelle = _rafraichir_annonce(client, annonce.joueur.slug, annonce.vendeur_slug)
        if actuelle is None:
            print(f"  ✗ {annonce.joueur.nom}/{annonce.vendeur_slug} : annonce disparue, ignorée")
            return False
        if actuelle.prix_demande != annonce.prix_demande:
            print(
                f"  ✗ {annonce.joueur.nom}/{annonce.vendeur_slug} : prix changé "
                f"({annonce.prix_demande} → {actuelle.prix_demande}), ignorée"
            )
            return False
    return True


def _offres_ouvertes_par_vendeur_reelles(session: Session) -> dict[str, int]:
    par_vendeur: dict[str, int] = {}
    for ligne in lignes_ouvertes(session, mode_simulation=False):
        par_vendeur[ligne.vendeur_slug] = par_vendeur.get(ligne.vendeur_slug, 0) + 1
    return par_vendeur


def main() -> int:
    configurer_journalisation()

    parser = argparse.ArgumentParser(
        description="Approbation humaine (phase 1) des propositions ecrites par "
        "cli/proposer_periodique.py. Voir le docstring du module pour le detail."
    )
    parser.add_argument(
        "--fichier", type=str, default=None,
        help="Chemin d'un fichier de propositions precis (defaut : le plus recent).",
    )
    parser.add_argument(
        "--mode-reel", action="store_true",
        help="Deuxieme des trois verrous du mode reel (PLAN.md, regle 9).",
    )
    args = parser.parse_args()

    horloge = HorlogeSysteme()
    creer_tables()

    chemin = (
        Path(args.fichier) if args.fichier
        else dernier_fichier_propositions(DOSSIER_PROPOSITIONS_DEFAUT)
    )
    if chemin is None or not chemin.exists():
        print("Aucun fichier de propositions trouve. Lance d'abord : "
              "python -m acheteur.cli.proposer_periodique", file=sys.stderr)
        return 1

    horodatage, propositions = charger_propositions(chemin)
    print(f"Fichier : {chemin} ({horodatage.isoformat()})")
    if fichier_perime(horodatage, horloge.maintenant()):
        age_minutes = int((horloge.maintenant() - horodatage).total_seconds() // 60)
        print(
            f"  AVERTISSEMENT : fichier vieux de plus de {age_minutes} minutes — "
            "les prix peuvent avoir change (revérifiés avant tout envoi)."
        )
    if not propositions:
        print("Aucune proposition dans ce fichier.")
        return 0
    print()
    _afficher_propositions(propositions)
    print()

    try:
        info = obtenir_jeton_valide(horloge)
    except (JetonAbsentError, JetonExpireError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    info = renouveler_si_necessaire(info, horloge)

    env_var_mode_reel = os.environ.get("ACHETEUR_MODE_REEL") == "1"
    cli_arg_mode_reel = args.mode_reel
    mode_reel_deverrouille = env_var_mode_reel and cli_arg_mode_reel

    if not mode_reel_deverrouille:
        print("Apercu seul (mode reel non deverrouille) — aucune ecriture, aucun envoi.")
        print("  Pour approuver reellement :")
        print(
            f"    ACHETEUR_MODE_REEL=1 python -m acheteur.cli.approuver_propositions "
            f"--fichier {chemin} --mode-reel"
        )
        return 0

    saisie = input(
        f"Lignes a envoyer (1-{len(propositions)} separes par des virgules, "
        "'toutes', ou 'aucune') : "
    )
    indices = _parser_selection(saisie, len(propositions))
    if indices is None:
        print("Saisie invalide. Rien envoye.")
        return 1
    if not indices:
        print("Aucune ligne selectionnee. Rien envoye.")
        return 0

    totaux = _totaux_par_devise(propositions, indices)
    for devise, total in totaux.items():
        devise_str = devise.value
        retape = demander_confirmation_utilisateur(total, devise=devise_str)
        if retape is None or not confirmer_montant_total(total, retape, devise_str):
            print(f"Confirmation {devise_str} echouee. Rien envoye.")
            return 1

    with session_scope() as session, SorareClient(jwt=info.token, jwt_aud=info.aud) as client:
        print("\nReconciliation avec Sorare...")
        rapport_reconciliation = reconcilier(session, client, horloge)
        session.commit()
        if rapport_reconciliation.cycle_suspendu:
            print(
                "⚠ CYCLE SUSPENDU — une depense non decidee par le bot a ete detectee. "
                "Rien envoye (python -m acheteur.cli.reconcilier pour le detail).",
                file=sys.stderr,
            )
            return 1
        print("  OK\n")

        compte = requetes.etat_compte(client)
        soldes = _soldes_reels(compte)
        contexte_base = ContexteBarriere(
            soldes_par_devise=soldes,
            offres_ouvertes_par_devise={},
            offres_ouvertes_par_vendeur=_offres_ouvertes_par_vendeur_reelles(session),
            solde_timestamp=horloge.maintenant(),
            taux_change_timestamp=None,
            plafond_offres_par_vendeur=5,
        )

        cumul_devise: dict[Devise, int] = {}
        cumul_vendeur: dict[str, int] = dict(contexte_base.offres_ouvertes_par_vendeur)
        envoyees = 0

        for i in indices:
            proposition = propositions[i]
            devise, montant = _devise_et_montant(proposition)
            print(f"[{i + 1}] verification en direct avant envoi...")
            if not _proposition_toujours_valide(client, proposition):
                continue

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
                    montant_retape=montant,  # verifie mecaniquement par la barriere ;
                    # la confirmation humaine porte sur le total par devise, deja faite ci-dessus.
                    client=client,
                )
                session.commit()
                cumul_devise[devise] = cumul_devise.get(devise, 0) + montant
                vendeur_slug = (
                    proposition.annonce.vendeur_slug
                    if isinstance(proposition, PropositionSimple)
                    else proposition.annonces[0].vendeur_slug
                )
                cumul_vendeur[vendeur_slug] = cumul_vendeur.get(vendeur_slug, 0) + 1
                envoyees += 1
                print(f"  ✓ envoyee ({montant} {devise.value})")
            except GuardrailViolation as exc:
                print(f"  ✗ garde-fou : {exc}")
                session.rollback()

        print(f"\n{envoyees}/{len(indices)} ligne(s) envoyee(s). "
              "Verifier avec python -m acheteur.cli.reconcilier avant tout nouveau cycle.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
