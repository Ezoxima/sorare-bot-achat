"""La barrière : point unique obligatoire avant tout envoi d'offre.

Toute proposition, simulée ou réelle, passe par cette fonction.
Elle applique les 9 garde-fous et décide : autoriser (journal + Sorare si réel)
ou refuser (levée d'exception, aucune mutation).

PLAN.md § « Garde-fous » : « passage obligé avant tout envoi ». Ce module est
ce passage. Un test (test_unique_path.py) prouve qu'il n'existe aucune autre
voie vers l'envoi.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from acheteur.core.horloge import Horloge

logger = logging.getLogger(__name__)
from acheteur.decision.proposition import PropositionGroupe, PropositionSimple
from acheteur.garde_fous.regles import (
    GuardrailViolation,
    verifier_arrêt_d_urgence,
    verifier_coherence_unites,
    verifier_mode_reel_verrous,
    verifier_offre_ne_depasse_pas_prix_demande,
    verifier_offres_par_vendeur_limitees,
    verifier_palier_valide,
    verifier_solde_relu_juste_avant,
    verifier_solde_suffisant,
    verifier_taux_change_frais,
)
from acheteur.marche.devises import Devise, Montant
from acheteur.negociation.journal import enregistrer_ligne
from acheteur.sorare.client import SorareClient
from acheteur.paiement import preparation, signature


@dataclass(frozen=True)
class ContexteBarriere:
    """Contexte d'exécution pour la barrière.

    Rassemble tout ce dont les garde-fous ont besoin : soldes, offres ouvertes,
    taux de change, etc. Construit une fois au début du scan, réutilisé pour
    toutes les propositions.

    `soldes_par_devise` (tel que renvoyé par Sorare) déduit déjà les offres
    réelles déjà ouvertes avant ce cycle — `offres_ouvertes_par_devise` ne
    doit donc contenir que les montants décidés **dans ce même cycle**, pas
    encore reflétés dans ce solde (voir `garde_fous.regles.verifier_solde_suffisant`,
    constaté contre le compte réel 2026-09-21, signalé par l'utilisateur).
    `offres_ouvertes_par_vendeur` est un compteur différent (règle 7,
    anti-démarchage, pas un budget) : lui compte bien toutes les offres
    réelles déjà ouvertes, quel que soit le cycle.
    """

    soldes_par_devise: dict[Devise, Montant]
    offres_ouvertes_par_devise: dict[Devise, int]
    offres_ouvertes_par_vendeur: dict[str, int]
    solde_timestamp: datetime
    taux_change_timestamp: datetime | None
    plafond_offres_par_vendeur: int = 5
    tolerance_solde_sec: int = 30
    tolerance_taux_min: int = 15


def envoyer_offre_proposal(
    proposition: PropositionSimple | PropositionGroupe,
    contexte: ContexteBarriere,
    session: Session,
    horloge: Horloge,
    mode_simulation: bool,
    env_var_mode_reel: bool = False,
    cli_arg_mode_reel: bool = False,
    montant_retape: int | None = None,
    chemin_racine: Path = Path("."),
    client: SorareClient | None = None,
    offre_precedente_id: int | None = None,
) -> None:
    """Envoie une offre après vérification de tous les garde-fous.

    C'est le SEUL point où une proposition devient ligne de journal envoyée
    (ou simulée). Aucune autre fonction ne peut appeler enregistrer_ligne()
    avec mode_simulation=False. Un test mécanique (test_unique_path.py)
    prouve qu'il n'existe qu'une seule occurrence de cette mutation dans le
    code source.

    Args:
        proposition: la proposition (simple ou groupée)
        contexte: soldes, offres ouvertes, taux, etc.
        session: session SQLAlchemy
        horloge: horloge injectable
        mode_simulation: True = simule, False = envoie à Sorare
        env_var_mode_reel: nécessaire si mode_simulation=False
        cli_arg_mode_reel: nécessaire si mode_simulation=False
        montant_retape: nécessaire si mode_simulation=False
        chemin_racine: chemin racine pour détection arrêt d'urgence
        offre_precedente_id: id de la ligne remplacée par cet envoi, si c'est
            une escalade ou un rejeu (lot L7) — voir `journal.OffreJournal.offre_precedente_id`

    Raises:
        GuardrailViolation: si un garde-fou échoue (aucune mutation)
    """
    # Règle 8 : arrêt d'urgence (toujours vérifié, simulation ou réel)
    verifier_arrêt_d_urgence(chemin_racine)

    # === Règles applicables à la simulation ET au mode réel ===

    # Règle 6 : palier valide (Palier est un IntEnum, converti en int)
    verifier_palier_valide(int(proposition.palier))

    # Extraire le montant total et la devise selon le type
    if isinstance(proposition, PropositionSimple):
        montant_total = proposition.montant_offre
        devise = proposition.annonce.prix_demande.devise
        vendeur_slug = proposition.annonce.vendeur_slug

        # Règle 3 : ne pas offrir plus que le prix demandé
        verifier_offre_ne_depasse_pas_prix_demande(
            montant_total, proposition.annonce.prix_demande.valeur
        )
    else:  # PropositionGroupe
        montant_total = proposition.montant_total
        # Pour groupé, assume même devise (vérifiée par decision)
        devise = proposition.annonces[0].prix_demande.devise
        vendeur_slug = proposition.annonces[0].vendeur_slug

        for annonce in proposition.annonces:
            verifier_offre_ne_depasse_pas_prix_demande(
                proposition.montants_offre[annonce.joueur.slug],
                annonce.prix_demande.valeur,
            )

    # Règle 4 : cohérence d'unité
    verifier_coherence_unites(montant_total, devise)

    # Règle 5 : taux de change frais (si conversion)
    verifier_taux_change_frais(
        contexte.taux_change_timestamp,
        horloge,
        contexte.tolerance_taux_min,
    )

    # Règle 7 : plafond par vendeur
    verifier_offres_par_vendeur_limitees(
        vendeur_slug,
        contexte.offres_ouvertes_par_vendeur,
        contexte.plafond_offres_par_vendeur,
    )

    # Règle 1 : solde disponible
    solde_ouvert = contexte.offres_ouvertes_par_devise.get(devise, 0)
    solde_dispo = contexte.soldes_par_devise[devise].valeur
    verifier_solde_suffisant(montant_total, solde_ouvert, solde_dispo)

    # Règle 2 : solde relu juste avant
    verifier_solde_relu_juste_avant(
        contexte.solde_timestamp,
        horloge,
        contexte.tolerance_solde_sec,
    )

    # === Règles supplémentaires si mode réel ===
    if not mode_simulation:
        # Règle 9 : trois verrous pour le mode réel
        verifier_mode_reel_verrous(
            env_var_mode_reel,
            cli_arg_mode_reel,
            montant_retape or 0,
            montant_total,
        )

    # === Tous les garde-fous passé : écriture en base ===
    # La ligne est écrite AVANT l'appel Sorare. Si le processus meurt
    # après, la réconciliation rattrape. C'est la couche 1 d'idempotence.

    if isinstance(proposition, PropositionSimple):
        enregistrer_ligne(
            session,
            joueur_slug=proposition.annonce.joueur.slug,
            vendeur_slug=proposition.annonce.vendeur_slug,
            prix_demande_valeur=proposition.annonce.prix_demande.valeur,
            prix_demande_devise=proposition.annonce.prix_demande.devise,
            montant_offre_valeur=proposition.montant_offre,
            montant_offre_devise=devise,
            reference_prix_valeur=proposition.reference_prix_valeur,
            reference_fenetre_jours=7,  # De DECISIONS.md
            reference_nb_ventes=3,  # Minimum, voir DECISIONS.md
            palier=int(proposition.palier),
            date_pose_annonce=proposition.annonce.date_pose,
            horloge_maintenant=horloge.maintenant(),
            mode_simulation=mode_simulation,
            decote_groupe=False,
            taux_change_horodatage=contexte.taux_change_timestamp,
            offre_precedente_id=offre_precedente_id,
        )
    else:  # PropositionGroupe
        for annonce in proposition.annonces:
            enregistrer_ligne(
                session,
                joueur_slug=annonce.joueur.slug,
                vendeur_slug=annonce.vendeur_slug,
                prix_demande_valeur=annonce.prix_demande.valeur,
                prix_demande_devise=annonce.prix_demande.devise,
                montant_offre_valeur=proposition.montants_offre[annonce.joueur.slug],
                montant_offre_devise=devise,
                reference_prix_valeur=proposition.references_prix.get(annonce.joueur.slug),
                reference_fenetre_jours=7,
                reference_nb_ventes=3,
                palier=int(proposition.palier),
                date_pose_annonce=annonce.date_pose,
                horloge_maintenant=horloge.maintenant(),
                mode_simulation=mode_simulation,
                decote_groupe=proposition.decote_appliquee,
                taux_change_horodatage=contexte.taux_change_timestamp,
                offre_precedente_id=offre_precedente_id,
            )

    # === Mode réel : appel Sorare après écriture en base ===
    if not mode_simulation:
        if client is None:
            raise ValueError(
                "Mode réel exige un client Sorare. Passez client=... à envoyer_offre_proposal"
            )

        # L5 : préparation et signature
        try:
            prepared = preparation.preparer_offre(client, proposition)

            # Vérifier s'il y a des erreurs de validation
            if prepared.errors:
                logger.error(
                    "Erreurs de validation prepareOffer : %s",
                    prepared.errors,
                )
                # Ne pas continuer si validation échoue
                return

            # Signer et envoyer
            offre_creee = signature.envoyer_offre_signee(client, prepared)

            # Récupérer le sorare_id de la réponse
            if "createDirectOffer" in offre_creee:
                payload = offre_creee["createDirectOffer"]

                # Bug réel trouvé en conditions réelles (lot L7, 2026-09-21,
                # voir MESURES.md) : `payload["tokenOffer"]` peut être présent
                # mais valoir `None` (GraphQL renvoie la clé avec une valeur
                # nulle quand la mutation a des erreurs) — appeler `.get()`
                # dessus plantait *avant* que les erreurs ci-dessous ne
                # soient jamais journalisées, masquant la vraie cause de
                # l'échec derrière un message générique.
                token_offer = payload.get("tokenOffer")
                if token_offer:
                    sorare_id = token_offer.get("id")
                    if sorare_id:
                        # La ligne a déjà été enregistrée avec sorare_id=None
                        # Mettre à jour avec le vrai ID
                        # (La ligne la plus récente pour ce couple joueur/vendeur)
                        from acheteur.negociation.journal import OffreJournal

                        if isinstance(proposition, PropositionSimple):
                            joueur_slug = proposition.annonce.joueur.slug
                            vendeur_slug = proposition.annonce.vendeur_slug
                        else:
                            joueur_slug = proposition.annonces[0].joueur.slug
                            vendeur_slug = proposition.annonces[0].vendeur_slug

                        ligne = (
                            session.query(OffreJournal)
                            .filter_by(joueur_slug=joueur_slug, vendeur_slug=vendeur_slug)
                            .order_by(OffreJournal.id.desc())
                            .first()
                        )
                        if ligne:
                            ligne.sorare_id = sorare_id
                            ligne.maj_le = horloge.maintenant()
                            session.flush()
                            logger.info(
                                "Offre envoyée : %s (sorare_id=%s)",
                                joueur_slug,
                                sorare_id,
                            )

                if payload.get("errors"):
                    logger.error("Erreurs createDirectOffer : %s", payload["errors"])

        except Exception as exc:
            # Si la mutation échoue, la ligne reste ENVOYEE et sera réconciliée
            logger.error("Erreur lors de L5 (préparation/envoi) : %s", exc)
            return
