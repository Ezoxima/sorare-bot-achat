"""Réconciliation du journal local avec les offres observées sur Sorare —
lecture seule (lot L2 : aucun module d'envoi n'existe encore, voir PLAN.md
§ Lots livrables. L5/L6 ajouteront l'écriture ; ici on ne fait qu'observer
et importer ce qui manque).

Trois couches indépendantes protègent déjà contre le double envoi
(PLAN.md § « Ne jamais envoyer deux fois la même offre ») : l'écriture
avant réseau, l'index unique en base, et cette réconciliation. Son rôle :
détecter les lignes douteuses *avant* qu'un cycle d'envoi ne démarre.

**Appariement en trois passes**, dans cet ordre :
1. par identifiant Sorare, quand la ligne du journal en a un ;
2. sinon par signature métier — mêmes cartes, même vendeur, même montant,
   même créneau horaire (`CRENEAU_SIGNATURE` autour de l'horodatage de
   création de la ligne, PAS de la date de pose de l'annonce : c'est
   l'instant où *notre* offre a été écrite qui doit coller à l'instant où
   Sorare l'a créée) ;
3. si plusieurs offres Sorare correspondent à la même ligne, on s'arrête et
   on alerte plutôt que de deviner (PLAN.md est explicite là-dessus).

**Import** : une offre Sorare qui ne correspond à aucune ligne du journal
est une offre faite à la main depuis l'appli web. PLAN.md dit de l'importer
et de **suspendre le cycle** — une dépense non décidée fausserait le
comptage des mesures (L10). Cette suspension est un simple drapeau sur le
rapport ; appliquer la suspension (empêcher un nouveau scan) est le travail
de l'appelant (CLI / boucle), pas de ce module.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from acheteur.core.horloge import Horloge
from acheteur.marche.devises import Devise
from acheteur.negociation import journal
from acheteur.negociation.journal import EtatOffre, MotifRefus, OffreJournal
from acheteur.sorare import requetes
from acheteur.sorare.client import SorareClient

# Tolérance sur l'écart entre l'horodatage de notre ligne et la date de
# création de l'offre côté Sorare, pour l'appariement par signature métier.
# Un aller-retour réseau + file d'attente Sorare ne devrait jamais dépasser
# ça ; au-delà, deux offres distinctes sur les mêmes cartes/montant/vendeur
# sont plus probables qu'une latence anormale.
CRENEAU_SIGNATURE = timedelta(minutes=15)


@dataclass(frozen=True)
class OffreSorareObservee:
    """Une offre envoyée, telle que lue depuis l'API Sorare (déjà aplatie).

    `joueurs_slugs` est un tuple (pas une liste) : c'est une clé de
    signature, elle doit être triée par l'appelant pour que l'ordre ne
    fausse pas la comparaison.
    """

    sorare_id: str
    vendeur_slug: str
    joueurs_slugs: tuple[str, ...]
    montant_valeur: int
    montant_devise: str
    creee_le: datetime
    etat_brut: str
    motif_refus_brut: str | None
    reponse_brute: dict
    # `TokenOffer.blockchainId` — requis par `cancelOffer` (lot L7), distinct
    # de `sorare_id` (`TokenOffer.id`). Absent tant qu'une offre n'a pas
    # encore été confirmée on-chain.
    blockchain_id: str | None = None
    # Montant de la contre-offre du vendeur (`TokenOffer.counteredOffer`),
    # même devise que `montant_devise`. `None` si aucune contre-offre.
    contre_offre_montant: int | None = None


@dataclass
class RapportReconciliation:
    appariees: list[tuple[OffreJournal, OffreSorareObservee]] = field(default_factory=list)
    a_importer: list[OffreSorareObservee] = field(default_factory=list)
    ambigues: list[tuple[OffreJournal, list[OffreSorareObservee]]] = field(default_factory=list)
    # Lignes ouvertes dans le journal sans contrepartie visible côté Sorare
    # (offre pas encore remontée, déjà réglée hors de la fenêtre demandée...).
    # Ce n'est pas en soi une alerte au lot L2 : juste une information.
    sans_contrepartie: list[OffreJournal] = field(default_factory=list)

    @property
    def cycle_suspendu(self) -> bool:
        """Vrai si un cycle d'envoi doit s'arrêter avant de démarrer.

        PLAN.md : une ligne douteuse gèle tout son lot — ici, une offre
        manuelle non comptée (`a_importer`) ou une correspondance ambiguë
        (`ambigues`) sont exactement ce type de doute.
        """
        return bool(self.a_importer or self.ambigues)


def _signature_journal(ligne: OffreJournal) -> tuple[tuple[str, ...], str, int]:
    return ((ligne.joueur_slug,), ligne.vendeur_slug, ligne.montant_offre_valeur)


def _signature_sorare(offre: OffreSorareObservee) -> tuple[tuple[str, ...], str, int]:
    return (offre.joueurs_slugs, offre.vendeur_slug, offre.montant_valeur)


def apparier(
    lignes_journal: list[OffreJournal],
    offres_sorare: list[OffreSorareObservee],
) -> RapportReconciliation:
    """Fonction pure : aucun réseau, aucune base — testable sur des cas figés.

    N'accepte en entrée que des lignes déjà filtrées sur les états ouverts
    (voir `journal.lignes_ouvertes`) : réconcilier une ligne déjà close
    n'aurait pas de sens.
    """
    rapport = RapportReconciliation()
    restantes = list(offres_sorare)

    # Passe 1 : par identifiant Sorare.
    par_id = {o.sorare_id: o for o in offres_sorare}
    lignes_sans_id: list[OffreJournal] = []
    for ligne in lignes_journal:
        correspondance = par_id.get(ligne.sorare_id) if ligne.sorare_id else None
        if correspondance is not None:
            rapport.appariees.append((ligne, correspondance))
            restantes = [o for o in restantes if o.sorare_id != correspondance.sorare_id]
        else:
            lignes_sans_id.append(ligne)

    # Passe 2 : par signature métier (cartes, vendeur, montant, créneau horaire).
    for ligne in lignes_sans_id:
        signature = _signature_journal(ligne)
        candidates = [
            o
            for o in restantes
            if _signature_sorare(o) == signature
            and abs(o.creee_le - ligne.cree_le) <= CRENEAU_SIGNATURE
        ]
        if len(candidates) == 1:
            trouvee = candidates[0]
            rapport.appariees.append((ligne, trouvee))
            restantes.remove(trouvee)
        elif len(candidates) > 1:
            rapport.ambigues.append((ligne, candidates))
            for candidate in candidates:
                restantes.remove(candidate)
        else:
            rapport.sans_contrepartie.append(ligne)

    # Passe 3 : ce qui reste côté Sorare ne correspond à rien dans le journal.
    rapport.a_importer = restantes
    return rapport


def motif_refus_depuis_sorare(motif_brut: str | None) -> MotifRefus:
    """Traduit le motif brut Sorare (`TokenOfferRejectionReason`) en `MotifRefus`.

    `None` devient `SANS_MOTIF` — PLAN.md : traité comme « trop basse » pour
    l'escalade, mais compté à part car c'est une hypothèse, pas un fait.
    """
    correspondance = {
        "OFFER_TOO_LOW": MotifRefus.OFFRE_TROP_BASSE,
        "NOT_SELLING": MotifRefus.NE_VEND_PAS,
        "CARD_NOT_WANTED": MotifRefus.CARTE_NON_DESIREE,
        "ONLY_CASH": MotifRefus.UNIQUEMENT_CASH,
        "ADD_CASH": MotifRefus.AJOUTE_CASH,
        "IN_A_LINEUP": MotifRefus.DANS_COMPOSITION,
    }
    if motif_brut is None:
        return MotifRefus.SANS_MOTIF
    if motif_brut not in correspondance:
        raise ValueError(f"Motif de refus Sorare inconnu : {motif_brut!r}")
    return correspondance[motif_brut]


def etat_depuis_sorare(etat_brut: str) -> EtatOffre:
    """Traduit l'état brut Sorare (`TokenOffer.status`, un `String!` — pas un
    enum GraphQL) en `EtatOffre` du journal.

    Comparaison insensible à la casse : DECISIONS.md/MESURES.md supposait des
    valeurs en capitales (convention des enums Sorare habituels) ; le premier
    run réel (lot L6, 2026-09-21) a montré que ce champ-ci renvoie des
    valeurs en minuscules (`"rejected"`, pas `"REJECTED"`). Comparer en
    capitales silencieusement faisait tomber tout état réel dans le défaut
    `ENVOYEE` — y compris une offre réellement rejetée, qui restait alors
    « ouverte » aux yeux du journal (voir MESURES.md).

    `EXPIRED` (lot L7, PLAN.md § « Expiration silencieuse ») : NON VÉRIFIÉE
    contre l'API réelle — jamais observée à ce jour (voir MESURES.md). Une
    valeur de statut ni reconnue ici ni ci-dessus retombe sur `ENVOYEE`
    (offre encore ouverte aux yeux du journal) plutôt que de deviner.
    """
    etat_normalise = etat_brut.upper()
    if etat_normalise == "ACCEPTED":
        return EtatOffre.ACCEPTEE
    if etat_normalise == "REJECTED":
        return EtatOffre.REFUSEE
    if etat_normalise == "CANCELLED":
        return EtatOffre.ANNULEE
    if etat_normalise == "EXPIRED":
        return EtatOffre.EXPIREE
    return EtatOffre.ENVOYEE


_DEVISE_DEPUIS_SUPPORTED_CURRENCY = {"EUR": Devise.EUR, "WEI": Devise.ETH}


def depuis_reponse_sorare(noeuds: list[dict[str, Any]]) -> list[OffreSorareObservee]:
    """Traduit les nœuds bruts de `sorare.requetes.offres_envoyees` en
    `OffreSorareObservee`. Ignore silencieusement une offre dont la devise
    de règlement n'est ni EUR ni WEI (aucun rail du projet ne les gère —
    PLAN.md, portefeuilles fiat + ETH/Solana) plutôt que de deviner un montant.
    """
    offres = []
    for noeud in noeuds:
        devises_reglement = noeud.get("settlementCurrencies") or []
        if not devises_reglement or devises_reglement[0] not in _DEVISE_DEPUIS_SUPPORTED_CURRENCY:
            continue
        devise = _DEVISE_DEPUIS_SUPPORTED_CURRENCY[devises_reglement[0]]

        montants = (noeud.get("senderSide") or {}).get("amounts") or {}
        montant_valeur = montants.get("eurCents") if devise == Devise.EUR else montants.get("wei")
        if montant_valeur is None:
            continue

        cartes = ((noeud.get("receiverSide") or {}).get("anyCards")) or []
        joueurs_slugs = tuple(
            sorted(
                carte["anyPlayer"]["slug"]
                for carte in cartes
                if carte.get("anyPlayer") and carte["anyPlayer"].get("slug")
            )
        )

        contre_offre = noeud.get("counteredOffer") or None
        contre_offre_montant = None
        if contre_offre is not None:
            for cote in ("senderSide", "receiverSide"):
                montants_cote = (contre_offre.get(cote) or {}).get("amounts") or {}
                valeur = montants_cote.get("eurCents") if devise == Devise.EUR else montants_cote.get(
                    "wei"
                )
                if valeur is not None:
                    contre_offre_montant = int(valeur)
                    break

        offres.append(
            OffreSorareObservee(
                sorare_id=noeud["id"],
                vendeur_slug=(noeud.get("receiver") or {}).get("slug", ""),
                joueurs_slugs=joueurs_slugs,
                montant_valeur=int(montant_valeur),
                montant_devise=devise.value,
                creee_le=datetime.fromisoformat(noeud["createdAt"]),
                etat_brut=noeud["status"],
                motif_refus_brut=noeud.get("rejectionReason"),
                reponse_brute=noeud,
                blockchain_id=noeud.get("blockchainId"),
                contre_offre_montant=contre_offre_montant,
            )
        )
    return offres


def reconcilier(session: Session, client: SorareClient, horloge: Horloge) -> RapportReconciliation:
    """Orchestration lecture seule (L2) : lit le journal et Sorare, apparie,
    importe ce qui manque. N'envoie jamais rien — `negociation.envoi` (L5+)
    est le seul module qui écrit vers Sorare.
    """
    lignes = journal.lignes_ouvertes(session)
    noeuds_bruts = requetes.offres_envoyees(client)
    offres = depuis_reponse_sorare(noeuds_bruts)

    rapport = apparier(lignes, offres)

    # `apparier()` (pure) ne compare que contre les lignes *ouvertes* — c'est
    # son contrat documenté, et il reste correct pour l'appariement lui-même.
    # Mais une offre déjà importée puis close (refusée/acceptée/annulée)
    # n'apparaît plus dans `lignes_ouvertes()` : sans ce filtre, `a_importer`
    # la redésignerait comme « à importer » à *chaque* réconciliation, pour
    # toujours — ce qui (a) tenterait de la réinsérer avec le même
    # `sorare_id` (violation d'unicité, plantage observé au premier run réel,
    # lot L6, MESURES.md 2026-09-21) et (b), même une fois l'insertion
    # protégée, laisserait `rapport.cycle_suspendu` bloqué à `True` en
    # permanence dès qu'une seule offre manuelle a un jour existé sur le
    # compte — l'exact contraire du but de cette suspension (signaler une
    # dépense *nouvelle*, pas ressasser l'historique connu). On retire donc
    # de `a_importer` tout ce qui porte déjà un `sorare_id` connu du journal,
    # dans n'importe quel état, avant même de regarder `cycle_suspendu`.
    sorare_ids_deja_connus = {
        sid for (sid,) in session.query(OffreJournal.sorare_id).filter(
            OffreJournal.sorare_id.isnot(None)
        )
    }
    rapport.a_importer = [
        offre for offre in rapport.a_importer if offre.sorare_id not in sorare_ids_deja_connus
    ]

    maintenant = horloge.maintenant()
    for offre in rapport.a_importer:
        journal.importer_ligne_manuelle(
            session,
            sorare_id=offre.sorare_id,
            joueur_slug=",".join(offre.joueurs_slugs) or "inconnu",
            vendeur_slug=offre.vendeur_slug,
            montant_offre_valeur=offre.montant_valeur,
            montant_offre_devise=Devise(offre.montant_devise),
            etat=etat_depuis_sorare(offre.etat_brut),
            motif_refus=motif_refus_depuis_sorare(offre.motif_refus_brut)
            if offre.etat_brut.upper() == "REJECTED"
            else None,
            reponse_brute=json.dumps(offre.reponse_brute, ensure_ascii=False),
            creee_le=offre.creee_le,
            horloge_maintenant=maintenant,
        )

    # Lot L7 : une ligne appariée reste un simple reflet de ce qu'on a nous-
    # même décidé d'envoyer (état ENVOYEE figé) tant que personne ne la met à
    # jour avec ce que Sorare observe *maintenant* — sans quoi la machine à
    # états (lot L7) n'aurait jamais de refus/acceptation/expiration sur
    # lesquels réagir. On ne touche qu'à `etat`, `motif_refus` et
    # `reponse_brute` : jamais à `reference_prix_valeur` ni aux autres champs
    # figés au moment de l'envoi (CLAUDE.md — la règle qui a déjà cassé
    # Pickdeck).
    for ligne, offre in rapport.appariees:
        nouvel_etat = etat_depuis_sorare(offre.etat_brut)
        if nouvel_etat == ligne.etat:
            continue
        ligne.etat = nouvel_etat
        ligne.motif_refus = (
            motif_refus_depuis_sorare(offre.motif_refus_brut)
            if nouvel_etat == EtatOffre.REFUSEE
            else None
        )
        ligne.reponse_brute = json.dumps(offre.reponse_brute, ensure_ascii=False)
        ligne.maj_le = maintenant
    session.flush()

    return rapport
