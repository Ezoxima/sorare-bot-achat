"""La machine à états d'une négociation (lot L7, PLAN.md § « La machine à
états d'une négociation »).

Fonctions pures : aucun réseau, aucune base — comme `decision/` et
`negociation/reconciliation.apparier`, testables sur des cas figés. Cette
machine ne fait que **décider** ; c'est à l'appelant (une future boucle L9,
ou un script CLI) d'exécuter la décision via la barrière (`garde_fous`) pour
un envoi, ou via `negociation.annulation` pour une annulation — jamais
directement.

Trois entrées possibles, une décision par appel — PLAN.md ne mélange jamais
un refus, une expiration et une contre-offre dans le même événement, cette
machine non plus :
- `reagir_a_refus` — la table « Ce qui déclenche quoi », lignes refus ;
- `reagir_a_expiration` — la ligne « Expiration silencieuse (24h) » ;
- `reagir_a_contre_offre` — la ligne « Contre-offre du vendeur » ;
- `reagir_a_veille` — la veille défensive (§ « On n'annule jamais pour
  reposter plus haut »), indépendante des trois précédentes : elle tourne
  sur une offre encore *ouverte*, pas sur un événement de clôture.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from acheteur.decision.paliers import Palier, palier_suivant
from acheteur.negociation.journal import MotifRefus


class ActionNegociation(StrEnum):
    """Ce que la machine décide de faire — jamais comment (voir docstring)."""

    ESCALADER = "escalader"
    ABANDONNER = "abandonner"
    REJOUER_MEME_PALIER = "rejouer_meme_palier"
    SOMMEIL = "sommeil"
    ANNULER = "annuler"
    ACCEPTER_CONTRE_OFFRE = "accepter_contre_offre"
    RIEN = "rien"


@dataclass(frozen=True)
class Decision:
    """Résultat d'une réaction : quoi faire, et pourquoi (pour le journal/log)."""

    action: ActionNegociation
    raison: str
    palier_suivant: Palier | None = None


# Motifs qui déclenchent une escalade immédiate — PLAN.md : « pas d'attente
# de 24h ». SANS_MOTIF est traité comme OFFRE_TROP_BASSE (hypothèse, pas un
# fait — voir journal.MotifRefus), mais reste distingué ailleurs (comptage).
_MOTIFS_ESCALADE = (MotifRefus.OFFRE_TROP_BASSE, MotifRefus.SANS_MOTIF)

# Motifs qui arrêtent tout — continuer jetterait de l'argent contre un mur.
_MOTIFS_ABANDON = (MotifRefus.NE_VEND_PAS, MotifRefus.CARTE_NON_DESIREE)


def reagir_a_refus(motif: MotifRefus, palier_courant: Palier) -> Decision:
    """Réaction à un refus explicite (PLAN.md § « Ce qui déclenche quoi »).

    Args:
        motif: le motif de refus observé (ou déduit — `SANS_MOTIF`)
        palier_courant: le palier auquel l'offre refusée avait été faite
    """
    if motif in _MOTIFS_ESCALADE:
        suivant = palier_suivant(palier_courant)
        if suivant is None:
            return Decision(
                ActionNegociation.ABANDONNER,
                raison=f"refus ({motif.value}) déjà au dernier palier ({palier_courant.value}%)",
            )
        return Decision(
            ActionNegociation.ESCALADER,
            raison=f"refus ({motif.value}) : escalade au palier suivant",
            palier_suivant=suivant,
        )

    if motif in _MOTIFS_ABANDON:
        return Decision(ActionNegociation.ABANDONNER, raison=f"refus définitif ({motif.value})")

    if motif is MotifRefus.UNIQUEMENT_CASH:
        return Decision(
            ActionNegociation.REJOUER_MEME_PALIER,
            raison="refus (uniquement_cash) : rejeu au même palier, rail euro",
            palier_suivant=palier_courant,
        )

    if motif is MotifRefus.AJOUTE_CASH:
        suivant = palier_suivant(palier_courant)
        if suivant is None:
            return Decision(
                ActionNegociation.ABANDONNER,
                raison="refus (ajoute_cash) déjà au dernier palier",
            )
        return Decision(
            ActionNegociation.ESCALADER,
            raison="refus (ajoute_cash) : escalade au palier suivant",
            palier_suivant=suivant,
        )

    if motif is MotifRefus.DANS_COMPOSITION:
        return Decision(
            ActionNegociation.SOMMEIL,
            raison="refus (dans_composition) : sommeil jusqu'à la fin de la gameweek",
        )

    raise ValueError(f"Motif de refus non couvert par la machine à états : {motif!r}")


def reagir_a_expiration(
    *,
    annonce_toujours_vivante: bool,
    prix_inchange: bool,
    reessai_deja_fait: bool,
    palier_courant: Palier,
) -> Decision:
    """Réaction à une expiration silencieuse (24h, PLAN.md).

    « Un seul ré-essai, au palier suivant, et seulement si l'annonce est
    toujours vivante au même prix. » Trois conditions, les trois sont
    nécessaires : pas déjà retenté, annonce vivante, prix inchangé.

    Args:
        annonce_toujours_vivante: l'annonce existe encore sur le marché
        prix_inchange: le prix demandé n'a pas bougé depuis l'offre expirée
        reessai_deja_fait: un ré-essai a déjà eu lieu pour cette offre
        palier_courant: le palier de l'offre qui vient d'expirer
    """
    if reessai_deja_fait:
        return Decision(
            ActionNegociation.ABANDONNER,
            raison="expiration : ré-essai déjà consommé, on n'insiste pas deux fois",
        )
    if not annonce_toujours_vivante:
        return Decision(
            ActionNegociation.ABANDONNER,
            raison="expiration : annonce disparue, pas de ré-essai possible",
        )
    if not prix_inchange:
        return Decision(
            ActionNegociation.ABANDONNER,
            raison="expiration : prix demandé a changé, la base du ré-essai n'existe plus",
        )
    suivant = palier_suivant(palier_courant)
    if suivant is None:
        return Decision(
            ActionNegociation.ABANDONNER,
            raison="expiration : déjà au dernier palier, pas de ré-essai possible",
        )
    return Decision(
        ActionNegociation.ESCALADER,
        raison="expiration : un seul ré-essai autorisé, annonce vivante au même prix",
        palier_suivant=suivant,
    )


def reagir_a_contre_offre(*, montant_contre_offre: int, plafond_valeur: int) -> Decision:
    """Réaction à une contre-offre du vendeur (PLAN.md : « Contre-offre du
    vendeur sous notre plafond | on accepte, on n'escalade pas »).

    PLAN.md ne dit pas explicitement quoi faire *au-dessus* du plafond —
    décision pour L7 (voir DECISIONS.md) : on n'accepte jamais au-delà du
    palier maximum (80% du prix demandé, la même règle 6 des garde-fous),
    donc on abandonne plutôt que de dépasser un plafond qu'on s'est fixé
    ailleurs pour une raison précise.

    Args:
        montant_contre_offre: montant proposé par le vendeur en retour
        plafond_valeur: le plafond que l'offre ne doit jamais dépasser
            (typiquement `paliers.montant_offre(prix_demande, Palier.TROISIEME)`)
    """
    if montant_contre_offre <= plafond_valeur:
        return Decision(
            ActionNegociation.ACCEPTER_CONTRE_OFFRE,
            raison=f"contre-offre ({montant_contre_offre}) sous le plafond ({plafond_valeur})",
        )
    return Decision(
        ActionNegociation.ABANDONNER,
        raison=f"contre-offre ({montant_contre_offre}) dépasse le plafond ({plafond_valeur})",
    )


def reagir_a_veille(
    *,
    annonce_disparue: bool,
    prix_demande_actuel: int | None,
    devise_prix_demande_actuel: object | None,
    notre_offre_montant: int,
    notre_offre_devise: object,
) -> Decision:
    """Veille défensive sur une offre encore ouverte (PLAN.md § « On n'annule
    jamais pour reposter plus haut ») : deux des trois raisons d'annuler que
    PLAN.md liste (la troisième, l'arrêt d'urgence, est un garde-fou global,
    déjà couvert par `garde_fous.regles.verifier_arrêt_d_urgence` — pas une
    réaction par offre, donc hors du périmètre de cette fonction).

    Args:
        annonce_disparue: l'annonce n'existe plus (vendue ailleurs, retirée)
        prix_demande_actuel: le prix affiché maintenant, ou None si
            `annonce_disparue` est vrai (aucun prix à lire)
        devise_prix_demande_actuel: devise de `prix_demande_actuel` (`Devise`,
            non importé ici pour ne pas faire dépendre `negociation` de
            `marche` — voir `marche.devises.Devise` côté appelant)
        notre_offre_montant: le montant de notre offre ouverte
        notre_offre_devise: devise de `notre_offre_montant`

    Régression (lot L7, sonde réelle 2026-09-21, voir MESURES.md) : comparer
    ces deux montants sans vérifier la devise a produit un faux « prix
    descendu » en comparant des centimes d'euro à des wei sur une annonce qui
    accepte les deux rails — CLAUDE.md § « Cohérence d'unité ETH / centimes ».
    Une devise différente ne prouve rien : on n'annule pas sur une
    comparaison qu'on ne sait pas faire.
    """
    if annonce_disparue:
        return Decision(ActionNegociation.ANNULER, raison="annonce disparue")
    if (
        prix_demande_actuel is not None
        and devise_prix_demande_actuel == notre_offre_devise
        and prix_demande_actuel < notre_offre_montant
    ):
        return Decision(
            ActionNegociation.ANNULER,
            raison=(
                f"prix demandé ({prix_demande_actuel}) descendu sous notre offre "
                f"({notre_offre_montant}) : payer plus cher que l'affiché serait absurde"
            ),
        )
    return Decision(ActionNegociation.RIEN, raison="annonce toujours valide, offre inchangée")
