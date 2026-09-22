"""Lot L9 (partie manquante, PLAN.md) : tâche destinée à tourner toutes les
15 minutes (Planificateur de tâches Windows) — scanne le marché comme
`cli/scan_liste_liquidite.py`, mais au lieu de se contenter d'un rapport
affiché, **persiste** les propositions dans un fichier horodaté
(`acheteur.approbation.fichier_propositions`) et envoie un mail de
notification si le SMTP est configuré.

**Toujours en lecture seule côté Sorare et côté base — aucun envoi, aucune
ligne `OffreJournal` écrite ici.** L'approbation (humaine, phase 1) se fait
ensuite, de façon asynchrone, avec `cli/approuver_propositions.py` : PLAN.md
§ « Le mode propose, tu valides » — « la validation doit être asynchrone (le
scan tourne toutes les 15 min, tu n'es pas devant l'écran) ».

Reprend intégralement le pipeline de `scan_liste_liquidite.py` (liste
liquide déjà connue, cible ses annonces actuelles) plutôt que de le
dupliquer — seule la sortie diffère (fichier + mail au lieu d'un simple
affichage).

Usage (à planifier toutes les 15 min) :
    python -m acheteur.cli.proposer_periodique

Pour enregistrer la tâche planifiée (Windows), une fois le chemin de
l'interpréteur Python du projet connu :
    schtasks /create /tn "Acheteur - proposer periodique" /sc minute /mo 15 ^
        /tr "\"<chemin\\python.exe>\" -m acheteur.cli.proposer_periodique" ^
        /st 00:00
"""

from __future__ import annotations

import sys

from acheteur.approbation import (
    MailNonConfigureError,
    envoyer_mail_propositions,
    mail_configure,
    sauvegarder_propositions,
)
from acheteur.auth.jeton import JetonAbsentError, JetonExpireError, obtenir_jeton_valide
from acheteur.auth.renouvellement import renouveler_si_necessaire
from acheteur.cli.scan_liste_liquidite import _annonces_du_couple
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
from acheteur.marche import Annonce
from acheteur.marche.liste_liquidite import derniere_maj, lire_liste_liquidite, liste_perimee
from acheteur.negociation import reconcilier
from acheteur.sorare import requetes
from acheteur.sorare.client import SorareClient


def main() -> int:
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
        maintenant = horloge.maintenant()

        if liste_perimee(session, maintenant):
            maj = derniere_maj(session)
            print(
                "Liste liquide absente ou perimee "
                f"(derniere reconstruction : {maj if maj else 'jamais'}). "
                "Lance d'abord : python -m acheteur.cli.maj_liste_liquidite",
                file=sys.stderr,
            )
            return 1

        couples = lire_liste_liquidite(session)
        if not couples:
            print("Liste liquide vide, rien a scanner.")
            return 0

        # Reconciliation en lecture seule : suspend le cycle si une depense
        # non decidee par le bot est detectee (PLAN.md) — un mail de
        # propositions batie sur des soldes faux serait pire qu'aucun mail.
        rapport_reconciliation = reconcilier(session, client, horloge)
        session.commit()
        if rapport_reconciliation.cycle_suspendu:
            print(
                "CYCLE SUSPENDU — une depense non decidee par le bot a ete detectee "
                "(python -m acheteur.cli.reconcilier pour le detail). Aucune proposition generee.",
                file=sys.stderr,
            )
            return 1

        compte = requetes.etat_compte(client)
        soldes = _soldes_reels(compte)
        offres_ouvertes = _offres_ouvertes_par_devise_info(session)

        annonces: list[Annonce] = []
        for couple in couples:
            annonces.extend(_annonces_du_couple(client, couple))

        candidates, illiquide, sans_reference = _calculer_candidates(client, horloge, annonces)
        bonnes_affaires = _bonnes_affaires(candidates, SEUIL_BONNE_AFFAIRE_DEFAUT)
        sous_le_seuil = len(candidates) - len(bonnes_affaires)

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
            bonnes_affaires, stocks, SEUIL_BONNE_AFFAIRE_DEFAUT,
            SOUS_VENTE_MINI_SEUIL_POURCENT_DEFAUT, STOCK_MAX_VENDEUR_DEFAUT,
        )

        petits_vendeurs = _petits_vendeurs(
            bonnes_affaires, stocks, STOCK_MAX_VENDEUR_DEFAUT, OFFRE_GROUPEE_VENDEURS_MAX_DEFAUT,
        )
        if petits_vendeurs:
            bonnes_affaires = _completer_par_vitrines_vendeurs(
                client, horloge, bonnes_affaires, SEUIL_BONNE_AFFAIRE_DEFAUT,
                SOUS_VENTE_MINI_SEUIL_POURCENT_DEFAUT, petits_vendeurs,
                OFFRE_GROUPEE_CARTES_MAX_PAR_VENDEUR_DEFAUT,
            )

        propositions, _references = _construire_propositions(bonnes_affaires)

        rapport = formatter_rapport(
            propositions,
            soldes,
            offres_ouvertes,
            nb_annonces_examinees=len(annonces),
            nb_illiquide=illiquide,
            nb_sans_reference=sans_reference,
            nb_sous_le_seuil=sous_le_seuil,
            seuil_pourcent=SEUIL_BONNE_AFFAIRE_DEFAUT,
        )
        print(rapport)

        if not propositions:
            print("\nAucune proposition — aucun fichier ecrit, aucun mail envoye.")
            return 0

        chemin = sauvegarder_propositions(propositions, maintenant)
        print(f"\nPropositions ecrites dans {chemin}")
        print("Pour approuver : python -m acheteur.cli.approuver_propositions")

        if mail_configure():
            try:
                envoyer_mail_propositions(
                    f"Acheteur Sorare — {len(propositions)} proposition(s) a valider",
                    rapport
                    + f"\n\nFichier : {chemin}\n"
                    "Approuver : python -m acheteur.cli.approuver_propositions\n",
                )
                print("Mail envoye.")
            except MailNonConfigureError:
                pass  # deja verifie par mail_configure(), ne devrait pas arriver
            except Exception as exc:  # smtplib peut lever plusieurs types differents
                print(
                    f"Echec envoi mail ({type(exc).__name__}) — "
                    "le fichier reste la source de verite.",
                    file=sys.stderr,
                )
        else:
            print("SMTP non configure (.env) — pas de mail envoye, seul le fichier fait foi.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
