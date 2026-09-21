"""Scanner L4 : scan du marché → décision → simulation → approbation.

Point d'entrée principal : orchestre la chaîne complète du scan de marché
à la préparation pour envoi réel (phase 1 = humain valide, phase 2 = auto).

Usage : python -m acheteur.cli.scanner [--help]
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy.orm import Session

from acheteur.approbation import (
    confirmer_montant_total,
    demander_confirmation_utilisateur,
    formatter_propositions_html,
)
from acheteur.auth.jeton import JetonAbsentError, JetonExpireError, obtenir_jeton_valide
from acheteur.auth.renouvellement import renouveler_si_necessaire
from acheteur.core.db import creer_tables, session_scope
from acheteur.core.horloge import HorlogeSysteme
from acheteur.core.journalisation import configurer_journalisation
from acheteur.decision import (
    Palier,
    grouper_par_vendeur,
    proposer_groupe,
    proposer_simple,
    selectionner_annonces,
)
from acheteur.garde_fous import ContexteBarriere, GuardrailViolation, envoyer_offre_proposal
from acheteur.marche import (
    Montant,
    population_liquide,
    reference_prix_joueur,
)
from acheteur.negociation import lignes_ouvertes, reconcilier
from acheteur.sorare.client import SorareClient


def main() -> int:
    """Lance un cycle complet de scan + décision + simulation + approbation.

    Returns:
        0 = succès, propositions prêtes pour L5
        1 = erreur ou cycle suspendu ou annulation utilisateur
    """
    configurer_journalisation()
    horloge = HorlogeSysteme()
    creer_tables()

    try:
        info = obtenir_jeton_valide(horloge)
    except (JetonAbsentError, JetonExpireError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    info = renouveler_si_necessaire(info, horloge)

    with session_scope() as session, SorareClient(jwt=info.token, jwt_aud=info.aud) as client:
        # === 1. RÉCONCILIATION : obligatoire avant scan ===
        print("Réconciliation avec Sorare...")
        rapport = reconcilier(session, client, horloge)

        if rapport.cycle_suspendu:
            print()
            print("⚠ CYCLE SUSPENDU")
            print("  Une dépense non décidée par le bot a été détectée.")
            print("  Vérifier les offres importées avant de relancer un scan.")
            return 1

        print(f"  Appariées : {len(rapport.appariees)}")
        print(f"  Ambiguës : {len(rapport.ambigues)}")
        print(f"  Sans contrepartie : {len(rapport.sans_contrepartie)}")
        print()

        # === 2. ÉTAT DU COMPTE ===
        print("Récupération de l'état du compte...")
        compte = client.etat_compte()
        print(f"  Solde EUR: {compte.solde_eur_centimes / 100:.2f}€")
        print(f"  Solde ETH: {compte.solde_eth_wei} wei")
        print()

        # === 3. POPULATION ET RÉFÉRENCES ===
        print("Calcul de la population liquide et des références...")
        now = horloge.maintenant()
        population = population_liquide(compte.joueurs, compte.ventes, now)
        references = {}
        for joueur in population:
            ref = reference_prix_joueur(joueur, compte.ventes, now)
            if ref:
                references[joueur.slug] = ref
        print(f"  Population liquide : {len(population)} joueurs")
        print(f"  Avec références : {len(references)} joueurs")
        print()

        # === 4. ANNONCES DU MARCHÉ ===
        print("Récupération des annonces du marché...")
        annonces = client.annonces_marche()
        print(f"  Total d'annonces : {len(annonces)}")
        print()

        # === 5. CHAÎNE DE DÉCISION (L3) ===
        print("Application de la chaîne de décision...")

        # references est dict {slug: Montant} ; selectionner_annonces veut des
        # Montant, proposer_groupe veut des valeurs entières nues (même
        # contrat que proposer_simple, qui fait déjà `.valeur` plus bas).
        references_montant = references
        references_valeurs = {slug: montant.valeur for slug, montant in references.items()}

        # Sélection
        selectionnees = selectionner_annonces(
            annonces, references_montant, seuil_pourcent=90
        )
        print(f"  Bonnes affaires (< 90% référence) : {len(selectionnees)}")

        # Groupage
        groups = grouper_par_vendeur(selectionnees)
        print(f"  Vendeurs impliqués : {len(groups)}")

        # Propositions
        from acheteur.decision.proposition import PropositionSimple, PropositionGroupe

        propositions = []
        for vendeur_slug, annonces_vendeur in groups.items():
            for palier in [Palier.PREMIER]:
                if len(annonces_vendeur) == 1:
                    prop = proposer_simple(
                        annonces_vendeur[0],
                        references_montant[annonces_vendeur[0].joueur.slug].valeur,
                        palier,
                    )
                    if prop.montant_offre > 0:
                        propositions.append(prop)
                else:
                    prop = proposer_groupe(annonces_vendeur, references_valeurs, palier)
                    if prop.montant_total > 0:
                        propositions.append(prop)

        print(f"  Propositions générées : {len(propositions)}")
        print()

        # === 6. SIMULATION : écriture en base mode_simulation=True ===
        print("Simulation des propositions dans le journal...")

        # Contexte pour barrière
        from acheteur.marche.devises import Devise

        offres_ouvertes_par_devise = {}
        offres_ouvertes_par_vendeur = {}
        contexte = ContexteBarriere(
            soldes_par_devise={
                Devise.EUR: Montant(compte.solde_eur_centimes, Devise.EUR),
                Devise.ETH: Montant(compte.solde_eth_wei, Devise.ETH),
            },
            offres_ouvertes_par_devise=offres_ouvertes_par_devise,
            offres_ouvertes_par_vendeur=offres_ouvertes_par_vendeur,
            solde_timestamp=now,
            taux_change_timestamp=now,
            plafond_offres_par_vendeur=5,
        )

        rejectees = 0
        for prop in propositions:
            try:
                envoyer_offre_proposal(
                    prop,
                    contexte,
                    session,
                    horloge,
                    mode_simulation=True,  # L4 = simulation toujours
                )
            except GuardrailViolation as e:
                joueur_slug = (
                    prop.annonce.joueur.slug
                    if hasattr(prop, "annonce")
                    else prop.annonces[0].joueur.slug
                )
                print(f"  ✗ {joueur_slug}: {e}")
                rejectees += 1

        session.commit()
        acceptees = len(propositions) - rejectees
        print(f"  Acceptées : {acceptees}")
        print(f"  Rejetées (garde-fous) : {rejectees}")
        print()

        if acceptees == 0:
            print("Aucune proposition acceptée. Fin.")
            return 0

        # === 7. PRÉSENTATION ===
        print()
        print("=" * 120)
        print("PROPOSITIONS PRÊTES À VALIDER")
        print("=" * 120)
        print()

        lignes_simulees = lignes_ouvertes(session, mode_simulation=True)
        tableau = formatter_propositions_html(
            lignes_simulees,
            contexte.soldes_par_devise,
            contexte.offres_ouvertes_par_devise,
        )
        print(tableau)
        print()

        # === 8. VALIDATION ===
        print("=" * 120)
        print()

        # Montant total
        from acheteur.marche.devises import Devise

        montant_total_eur = sum(
            l.montant_offre_valeur
            for l in lignes_simulees
            if l.montant_offre_devise == Devise.EUR
        )
        montant_total_eth = sum(
            l.montant_offre_valeur
            for l in lignes_simulees
            if l.montant_offre_devise == Devise.ETH
        )

        if montant_total_eur > 0:
            montant_retape = demander_confirmation_utilisateur(
                montant_total_eur, devise="EUR"
            )
            if montant_retape is None:
                print("Annulation.")
                session.rollback()
                return 0

            if not confirmer_montant_total(montant_total_eur, montant_retape, "EUR"):
                session.rollback()
                return 0

        if montant_total_eth > 0:
            montant_retape = demander_confirmation_utilisateur(
                montant_total_eth, devise="ETH"
            )
            if montant_retape is None:
                print("Annulation.")
                session.rollback()
                return 0

            if not confirmer_montant_total(montant_total_eth, montant_retape, "ETH"):
                session.rollback()
                return 0

        # === 9. PRÊT POUR L5 ===
        print()
        print("✓ Propositions validées. Prêtes pour envoi (L5).")
        print()

        return 0


if __name__ == "__main__":
    sys.exit(main())
