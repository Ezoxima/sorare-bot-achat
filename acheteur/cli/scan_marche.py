"""Passe marché en lecture seule : applique tous nos critères de décision à
un échantillon du marché réel et produit un rapport lisible — **aucune
écriture, ni en base ni vers Sorare.**

Différent des autres scripts réels du projet :
- `premiere_offre_reelle.py` (L6) s'arrête à la **première** candidate
  valide, pour prouver que le chemin d'envoi fonctionne.
- `cycle_negociation.py` (L7) réagit aux lignes déjà présentes dans le
  journal (refus, expiration, veille) — il ne regarde pas de nouvelles
  annonces.
- Celui-ci évalue **toutes** les annonces de l'échantillon contre la chaîne
  de décision complète (référence réelle par saison, seuil de bonne affaire,
  groupage par vendeur, palier de départ) et affiche ce qui *serait*
  proposé — sans jamais écrire de ligne `SIMULEE` (qui occuperait l'index
  unique (joueur, vendeur) et bloquerait un futur essai réel sur la même
  carte, comme documenté pour L6 — voir DECISIONS.md).

Même limite d'échantillonnage que L6 (DECISIONS.md, 2026-09-21) :
`liveSingleSaleOffers` est triée par fraîcheur de mise à jour, pas par prix,
et ce script n'en récupère qu'une page — ce rapport n'est donc pas exhaustif
sur le marché entier, seulement sur l'échantillon récupéré.

Usage :
    python -m acheteur.cli.scan_marche
    python -m acheteur.cli.scan_marche --premieres 200 --seuil 85 --sortie rapport.txt
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy.orm import Session

from acheteur.auth.jeton import JetonAbsentError, JetonExpireError, obtenir_jeton_valide
from acheteur.auth.renouvellement import renouveler_si_necessaire
from acheteur.core.db import creer_tables, session_scope
from acheteur.core.horloge import Horloge, HorlogeSysteme
from acheteur.core.journalisation import configurer_journalisation
from acheteur.decision import Palier, grouper_par_vendeur, proposer_groupe, proposer_simple
from acheteur.decision.proposition import PropositionGroupe, PropositionSimple
from acheteur.decision.selecteur import (
    SOUS_VENTE_MINI_SEUIL_POURCENT_DEFAUT,
    est_bonne_affaire,
    est_sous_vente_minimum,
)
from acheteur.marche import (
    Annonce,
    Devise,
    Montant,
    Vente,
    annonces_depuis_noeuds_marche,
    est_liquide,
    mesurer_liquidite,
    rarity_brute_depuis_annonce,
    reference_prix_joueur,
    season_eligibility_brute_depuis_annonce,
    ventes_depuis_noeuds_prix,
)
from acheteur.negociation import lignes_ouvertes, reconcilier
from acheteur.sorare import requetes
from acheteur.sorare.client import SorareClient

NOMBRE_ANNONCES_EXAMINEES_DEFAUT = 100
NOMBRE_VENTES_EXAMINEES = 20  # Plafond réel de tokenPrices(first:), voir MESURES.md
SEUIL_BONNE_AFFAIRE_DEFAUT = 90

# SOUS_VENTE_MINI.stockMaxVendeur (sealing-sorare-apps-script/03 - bonnes
# affaires.gs) : un candidat qui n'est retenu QUE par `est_sous_vente_minimum`
# (pas par `est_bonne_affaire`) n'est fiable que chez un petit vendeur —
# signal confirmé empiriquement par l'utilisateur (2026-09-22, voir
# DECISIONS.md). Ne s'applique pas aux candidates qui passent déjà
# `est_bonne_affaire` : cette réserve est spécifique au second signal.
STOCK_MAX_VENDEUR_DEFAUT = 20

# Offre groupée réactive : dès qu'un petit vendeur produit une candidate, on
# relit toute sa vitrine pour voir si d'autres de ses cartes qualifient aussi
# (voir DECISIONS.md 2026-09-22, `OFFRE_GROUPEE` dans le `.gs` d'origine).
# Plafonds pour borner le coût — un run avec beaucoup de petits vendeurs
# retenus ne doit pas partir en vrille.
OFFRE_GROUPEE_VENDEURS_MAX_DEFAUT = 6
OFFRE_GROUPEE_CARTES_MAX_PAR_VENDEUR_DEFAUT = 20


class Candidate:
    """Une annonce dont la référence réelle a été calculée — sert à la fois
    au filtrage (bonne affaire ou non) et à l'affichage du rapport.

    `ventes` : l'historique complet déjà récupéré pour calculer `reference`
    (même fenêtre) — réutilisé pour `est_sous_vente_minimum`, sans appel
    réseau supplémentaire. Vide par défaut pour ne pas casser les usages
    (et tests) qui ne construisent une candidate qu'avec sa référence.
    """

    def __init__(
        self,
        annonce: Annonce,
        reference: Montant,
        nb_ventes: int,
        ventes: list[Vente] = (),
    ) -> None:
        self.annonce = annonce
        self.reference = reference
        self.nb_ventes = nb_ventes
        self.ventes = list(ventes)


def _calculer_candidates(
    client: SorareClient,
    horloge: Horloge,
    annonces: list[Annonce],
    taille_lot: int = requetes.TAILLE_LOT_HISTORIQUE_PRIX_DEFAUT,
) -> tuple[list[Candidate], int, int]:
    """Calcule la liquidité puis la référence réelle de chaque annonce (même
    logique que L6 : médiane sur 7 jours, filtrée par saison — voir
    `marche.reference_prix`).

    L'historique de prix est récupéré PAR LOT (`requetes.historique_prix_joueurs_lot`,
    alias GraphQL, jusqu'à `taille_lot` joueurs par appel) plutôt qu'un
    appel réseau par annonce — indispensable pour examiner un échantillon
    large sans multiplier les appels un par un (voir DECISIONS.md,
    2026-09-22 : même principe que `liquiditeParCouple_` dans les `.gs`
    d'origine, mais avec les rareté/éligibilité de saison exactes de chaque
    annonce plutôt qu'un balayage par combinaison).

    La liquidité (`marche.liquidite.est_liquide`) est vérifiée EN PREMIER,
    sur le même historique de ventes que la référence — pas d'appel réseau
    de plus. Un joueur illiquide n'a pas de valeur de négociation, quel que
    soit le prix demandé.

    Returns:
        (candidates avec liquidité et référence valides, nombre d'annonces
        illiquides, nombre d'annonces liquides mais sans référence
        exploitable) — les deux compteurs sont distincts pour que le rapport
        montre où le taux de couverture se perd.
    """
    maintenant = horloge.maintenant()
    candidates: list[Candidate] = []
    illiquide = 0
    sans_reference = 0

    for debut in range(0, len(annonces), taille_lot):
        lot = annonces[debut : debut + taille_lot]
        demandes = [
            {
                "joueur_slug": annonce.joueur.slug,
                "rarete": rarity_brute_depuis_annonce(annonce),
                "season_eligibility": season_eligibility_brute_depuis_annonce(annonce),
            }
            for annonce in lot
        ]
        resultats = requetes.historique_prix_joueurs_lot(
            client, demandes, premieres=NOMBRE_VENTES_EXAMINEES
        )

        for annonce, noeuds_prix in zip(lot, resultats):
            ventes = ventes_depuis_noeuds_prix(noeuds_prix, annonce.joueur)

            liquidite = mesurer_liquidite(ventes, maintenant)
            if not est_liquide(liquidite):
                illiquide += 1
                continue

            reference = reference_prix_joueur(annonce.joueur, ventes, maintenant)
            if reference is None or reference.devise != annonce.prix_demande.devise:
                sans_reference += 1
                continue
            candidates.append(Candidate(annonce, reference, len(ventes), ventes=ventes))

    return candidates, illiquide, sans_reference


def _bonnes_affaires(
    candidates: list[Candidate],
    seuil_pourcent: int,
    seuil_sous_vente_min_pourcent: int = SOUS_VENTE_MINI_SEUIL_POURCENT_DEFAUT,
) -> list[Candidate]:
    """Retient une candidate si elle passe `est_bonne_affaire` (comparaison à
    la référence médiane, nette de taxe de revente) OU `est_sous_vente_minimum`
    (annonce sous le plancher des ventes antérieures) — deux signaux
    indépendants, voir DECISIONS.md (2026-09-22).

    Le second signal seul est peu fiable (fréquent, pas forcément une
    affaire) : `_necessite_verification_stock`/`_filtrer_par_stock_vendeur`
    exigent en plus un petit vendeur pour les candidates qui ne doivent leur
    sélection qu'à lui.
    """
    return [
        c
        for c in candidates
        if est_bonne_affaire(c.annonce, c.reference, seuil_pourcent)
        or est_sous_vente_minimum(c.annonce, c.ventes, seuil_sous_vente_min_pourcent)
    ]


def _necessite_verification_stock(
    candidate: Candidate,
    seuil_pourcent: int,
    seuil_sous_vente_min_pourcent: int,
) -> bool:
    """Vrai si la candidate ne doit sa sélection qu'à `est_sous_vente_minimum`
    (pas à `est_bonne_affaire`) — seul cas où la taille de la vitrine du
    vendeur doit être vérifiée avant de la retenir définitivement."""
    return not est_bonne_affaire(
        candidate.annonce, candidate.reference, seuil_pourcent
    ) and est_sous_vente_minimum(candidate.annonce, candidate.ventes, seuil_sous_vente_min_pourcent)


def _filtrer_par_stock_vendeur(
    candidates: list[Candidate],
    stocks: dict[str, int | None],
    seuil_pourcent: int,
    seuil_sous_vente_min_pourcent: int,
    stock_max_vendeur: int,
) -> list[Candidate]:
    """Écarte les candidates retenues uniquement par `est_sous_vente_minimum`
    dont le vendeur est absent de `stocks`, non mesurable (`None`), ou trop
    gros (> `stock_max_vendeur`) — un vendeur illisible n'est PAS gardé par
    défaut (même prudence que `filtrerPetitsVendeurs_` dans les `.gs`).

    Les candidates retenues par `est_bonne_affaire` ne sont jamais affectées :
    cette réserve est spécifique au second signal.
    """
    retenues = []
    for c in candidates:
        if not _necessite_verification_stock(c, seuil_pourcent, seuil_sous_vente_min_pourcent):
            retenues.append(c)
            continue
        stock = stocks.get(c.annonce.vendeur_slug)
        if stock is None or stock > stock_max_vendeur:
            continue
        retenues.append(c)
    return retenues


def _petits_vendeurs(
    candidates: list[Candidate],
    stocks: dict[str, int | None],
    stock_max_vendeur: int,
    vendeurs_max: int,
) -> list[str]:
    """Les vendeurs distincts, parmi les candidates retenues, dont la
    vitrine est mesurée et assez petite pour justifier une offre groupée
    réactive — plafonné à `vendeurs_max` (coût : 2 appels réseau par
    vendeur retenu, voir `main()`)."""
    slugs = sorted(
        {
            c.annonce.vendeur_slug
            for c in candidates
            if stocks.get(c.annonce.vendeur_slug) is not None
            and stocks[c.annonce.vendeur_slug] <= stock_max_vendeur
        }
    )
    return slugs[:vendeurs_max]


def _construire_propositions(
    bonnes_affaires: list[Candidate],
) -> tuple[list[PropositionSimple | PropositionGroupe], dict[str, Montant]]:
    """Groupe par vendeur puis construit les propositions au palier de
    départ (70%) — même logique que `cli/scanner.py` (L4), mais sur des
    annonces et références réelles plutôt que mockées."""
    references = {c.annonce.joueur.slug: c.reference for c in bonnes_affaires}
    annonces = [c.annonce for c in bonnes_affaires]
    groupes = grouper_par_vendeur(annonces)

    propositions: list[PropositionSimple | PropositionGroupe] = []
    for annonces_vendeur in groupes.values():
        if len(annonces_vendeur) == 1:
            annonce = annonces_vendeur[0]
            propositions.append(
                proposer_simple(annonce, references[annonce.joueur.slug].valeur, Palier.PREMIER)
            )
        else:
            references_valeurs = {a.joueur.slug: references[a.joueur.slug].valeur for a in annonces_vendeur}
            propositions.append(proposer_groupe(annonces_vendeur, references_valeurs, Palier.PREMIER))
    return propositions, references


def _soldes_reels(compte: dict) -> dict[Devise, Montant]:
    balances = compte.get("availableBalances") or {}
    eur = ((balances.get("eurCents") or {}).get("eurCents")) or 0
    wei = ((balances.get("wei") or {}).get("wei")) or 0
    return {
        Devise.EUR: Montant(int(eur), Devise.EUR),
        Devise.ETH: Montant(int(wei), Devise.ETH),
    }


def _offres_ouvertes_par_devise_info(session: Session) -> dict[Devise, int]:
    """Purement informatif pour le rapport (voir `formatter_rapport`) — ne
    sert jamais à réduire le budget, déjà net côté Sorare."""
    par_devise: dict[Devise, int] = {}
    for ligne in lignes_ouvertes(session, mode_simulation=False):
        par_devise[ligne.montant_offre_devise] = (
            par_devise.get(ligne.montant_offre_devise, 0) + ligne.montant_offre_valeur
        )
    return par_devise


def _formatter_montant(valeur: int, devise: Devise) -> str:
    return f"{valeur / 100:.2f}€" if devise == Devise.EUR else f"{valeur} wei"


def _devise_et_montant(proposition: PropositionSimple | PropositionGroupe) -> tuple[Devise, int]:
    if isinstance(proposition, PropositionSimple):
        return proposition.annonce.prix_demande.devise, proposition.montant_offre
    return proposition.annonces[0].prix_demande.devise, proposition.montant_total


def _ratio_prix_sur_reference(proposition: PropositionSimple | PropositionGroupe) -> float:
    """Sert à trier les propositions des meilleures affaires relatives aux
    moins bonnes — un budget limité doit d'abord aller aux offres les plus
    avantageuses, pas à celles rencontrées en premier dans l'échantillon.

    Prix demandé / référence, pas `pourcent_demande` : ce dernier vaut le
    palier (70% ou 65% en décote groupe) *par construction* pour toutes les
    propositions de ce script (elles sortent toutes du même palier de
    départ), donc ne discrimine rien entre elles. Le vrai signal de qualité
    d'une affaire, c'est l'écart entre ce que le vendeur demande et la
    référence — pas ce qu'on décide d'en offrir.
    """
    if isinstance(proposition, PropositionSimple):
        if proposition.reference_prix_valeur == 0:
            return float("inf")
        return proposition.annonce.prix_demande.valeur / proposition.reference_prix_valeur

    prix_demande_total = sum(a.prix_demande.valeur for a in proposition.annonces)
    reference_totale = sum(
        proposition.references_prix[a.joueur.slug] for a in proposition.annonces
    )
    if reference_totale == 0:
        return float("inf")
    return prix_demande_total / reference_totale


def repartir_selon_budget(
    propositions: list[PropositionSimple | PropositionGroupe],
    soldes_par_devise: dict[Devise, Montant],
) -> tuple[
    list[tuple[PropositionSimple | PropositionGroupe, int]],
    list[PropositionSimple | PropositionGroupe],
]:
    """Sépare les propositions entre celles qui tiennent dans le budget
    réellement disponible et celles qui n'y tiennent plus, dans l'ordre des
    meilleures affaires relatives d'abord.

    Le budget, c'est `soldes_par_devise` tel quel — le solde renvoyé par
    Sorare (`currentUser.availableBalance(s)`) a **déjà** déduit toutes les
    offres réelles ouvertes avant ce passage (`totalBalance - availableBalance`
    colle exactement à leur somme, constaté contre le compte réel,
    2026-09-21, signalé par l'utilisateur). Une version antérieure de cette
    fonction soustrayait ces offres une seconde fois, ce qui sous-estimait
    le budget réel — voir DECISIONS.md/MESURES.md.

    Ne fait aucune hypothèse d'exhaustivité (ce n'est pas un problème
    d'optimisation de sac à dos) : une fois une proposition écartée faute de
    budget, les suivantes — potentiellement plus petites — sont quand même
    testées, plutôt que d'arrêter au premier dépassement.

    Returns:
        (propositions dans le budget avec le solde restant *après* chacune,
        propositions hors budget)
    """
    restant: dict[Devise, int] = {devise: montant.valeur for devise, montant in soldes_par_devise.items()}
    dans_le_budget: list[tuple[PropositionSimple | PropositionGroupe, int]] = []
    hors_budget: list[PropositionSimple | PropositionGroupe] = []

    for proposition in sorted(propositions, key=_ratio_prix_sur_reference):
        devise, montant = _devise_et_montant(proposition)
        if montant <= restant.get(devise, 0):
            restant[devise] -= montant
            dans_le_budget.append((proposition, restant[devise]))
        else:
            hors_budget.append(proposition)

    return dans_le_budget, hors_budget


def formatter_rapport(
    propositions: list[PropositionSimple | PropositionGroupe],
    soldes_par_devise: dict[Devise, Montant],
    offres_ouvertes_par_devise: dict[Devise, int],
    *,
    nb_annonces_examinees: int,
    nb_illiquide: int = 0,
    nb_sans_reference: int,
    nb_sous_le_seuil: int,
    seuil_pourcent: int,
) -> str:
    """Rapport texte, prêt à copier dans un mail ou à écrire dans un .txt.

    Une ligne par proposition, jamais un chiffre sans son effectif (PLAN.md
    § « Le mode propose, tu valides ») — comme `approbation.present_proposals`,
    mais sur des `Proposition*` en mémoire : ce script n'écrit jamais de
    ligne `OffreJournal`, donc ne peut pas réutiliser ce formateur-là.

    Sépare explicitement ce qui tient dans le budget disponible (meilleures
    affaires d'abord) de ce qui n'y tient plus — signalé par l'utilisateur
    (2026-09-21) : un simple solde restant qui devient négatif en bout de
    liste passe trop facilement inaperçu.

    `offres_ouvertes_par_devise` n'est **pas** déduit du budget — Sorare l'a
    déjà fait (`soldes_par_devise` vient de `currentUser.availableBalance(s)`,
    qui déduit tout seul les offres réelles ouvertes ; `totalBalance -
    availableBalance` colle exactement à leur somme, vérifié contre le
    compte réel). Ce paramètre ne sert qu'à l'affichage informatif — le
    montrer explique pourquoi le budget peut sembler plus serré qu'un solde
    total, sans jamais le soustraire une seconde fois (régression corrigée
    le même jour : une version antérieure soustrayait, sous-estimant le
    budget réel — voir DECISIONS.md/MESURES.md).
    """
    lignes = [
        "PASSE MARCHÉ — aperçu, aucune écriture (ni base, ni Sorare)",
        "=" * 100,
        f"Annonces examinées      : {nb_annonces_examinees}",
        f"Illiquides (liquidité insuffisante) : {nb_illiquide}",
        f"Sans référence exploitable (< 3 ventes/7j) : {nb_sans_reference}",
        f"Au-dessus du seuil ({seuil_pourcent}% de la référence) : {nb_sous_le_seuil}",
        f"Propositions générées   : {len(propositions)}",
    ]
    for devise, montant in soldes_par_devise.items():
        lignes.append(f"Budget disponible {devise.value} : {_formatter_montant(montant.valeur, devise)}")
        deja_ouvert = offres_ouvertes_par_devise.get(devise, 0)
        if deja_ouvert:
            lignes.append(
                f"  (dont {_formatter_montant(deja_ouvert, devise)} déjà réservés sur des offres "
                "ouvertes — déjà compris dans le budget ci-dessus, pas à soustraire)"
            )
    lignes.append("=" * 100)
    lignes.append("")

    if not propositions:
        lignes.append("Aucune bonne affaire dans cet échantillon.")
        return "\n".join(lignes)

    dans_le_budget, hors_budget = repartir_selon_budget(propositions, soldes_par_devise)

    def _decrire(proposition: PropositionSimple | PropositionGroupe) -> list[str]:
        devise, montant = _devise_et_montant(proposition)
        if isinstance(proposition, PropositionSimple):
            annonce = proposition.annonce
            return [
                f"{annonce.joueur.nom} ({annonce.joueur.rareté.nom}, "
                f"{'in-season' if annonce.in_season else 'classic'})",
                f"  Vendeur         : {annonce.vendeur_slug}",
                f"  Prix demandé    : {annonce.prix_demande}",
                f"  Référence       : {Montant(proposition.reference_prix_valeur, devise)} "
                f"(médiane, écart {proposition.ecart_pourcent:.0f}%)",
                f"  Palier          : {int(proposition.palier)}%",
                f"  Montant offert  : {Montant(montant, devise)}",
            ]
        vendeur = proposition.annonces[0].vendeur_slug
        sortie = [f"Groupe chez {vendeur} ({len(proposition.annonces)} cartes)"]
        for annonce in proposition.annonces:
            montant_carte = proposition.montants_offre[annonce.joueur.slug]
            sortie.append(
                f"  - {annonce.joueur.nom} : demandé {annonce.prix_demande}, "
                f"offert {Montant(montant_carte, devise)}"
            )
        sortie.append(
            f"  Palier          : {int(proposition.palier)}%"
            f"{' (décote groupe 65%)' if proposition.decote_appliquee else ''}"
        )
        sortie.append(f"  Montant total   : {Montant(montant, devise)}")
        return sortie

    lignes.append(f"=== DANS LE BUDGET ({len(dans_le_budget)}) — meilleures affaires d'abord ===")
    lignes.append("")
    if not dans_le_budget:
        lignes.append("Aucune — le budget net ne couvre même la meilleure affaire trouvée.")
        lignes.append("")
    for proposition, solde_restant in dans_le_budget:
        devise, _ = _devise_et_montant(proposition)
        lignes.extend(_decrire(proposition))
        lignes.append(f"  Solde restant après cette offre : {_formatter_montant(solde_restant, devise)}")
        lignes.append("")

    if hors_budget:
        lignes.append(f"=== HORS BUDGET ({len(hors_budget)}) — budget épuisé avant d'y arriver ===")
        lignes.append("")
        for proposition in hors_budget:
            lignes.extend(_decrire(proposition))
            lignes.append("  (ne tiendrait plus dans le budget net disponible)")
            lignes.append("")

    lignes.append("-" * 100)
    total_par_devise: dict[Devise, int] = {}
    for proposition, _ in dans_le_budget:
        devise, montant = _devise_et_montant(proposition)
        total_par_devise[devise] = total_par_devise.get(devise, 0) + montant
    for devise, total in total_par_devise.items():
        lignes.append(f"TOTAL {devise.value.upper()} proposé (dans le budget) : {_formatter_montant(total, devise)}")

    return "\n".join(lignes)


def _evaluer_autre_carte_vendeur(
    client: SorareClient,
    horloge: Horloge,
    annonce: Annonce,
    seuil_pourcent: int,
    seuil_sous_vente_min_pourcent: int,
) -> Candidate | None:
    """Reprend exactement la logique de `_calculer_candidates` puis
    `_bonnes_affaires`, pour UNE annonce trouvée dans la vitrine d'un
    vendeur déjà retenu (offre groupée réactive) — mêmes critères, pas de
    règle à part pour ces cartes-là."""
    noeuds_prix = requetes.historique_prix_joueur(
        client,
        annonce.joueur.slug,
        rarity_brute_depuis_annonce(annonce),
        premieres=NOMBRE_VENTES_EXAMINEES,
        season_eligibility=season_eligibility_brute_depuis_annonce(annonce),
    )
    ventes = ventes_depuis_noeuds_prix(noeuds_prix, annonce.joueur)
    maintenant = horloge.maintenant()

    if not est_liquide(mesurer_liquidite(ventes, maintenant)):
        return None
    reference = reference_prix_joueur(annonce.joueur, ventes, maintenant)
    if reference is None or reference.devise != annonce.prix_demande.devise:
        return None
    if not (
        est_bonne_affaire(annonce, reference, seuil_pourcent)
        or est_sous_vente_minimum(annonce, ventes, seuil_sous_vente_min_pourcent)
    ):
        return None
    return Candidate(annonce, reference, len(ventes), ventes=ventes)


def _completer_par_vitrines_vendeurs(
    client: SorareClient,
    horloge: Horloge,
    candidates: list[Candidate],
    seuil_pourcent: int,
    seuil_sous_vente_min_pourcent: int,
    petits_vendeurs: list[str],
    cartes_max_par_vendeur: int,
) -> list[Candidate]:
    """Offre groupée réactive : pour chaque petit vendeur déjà retenu, relit
    toute sa vitrine et réévalue ses AUTRES cartes contre nos critères — pas
    seulement celle qui a déclenché la sélection. Les nouvelles candidates
    partagent le `vendeur_slug` des candidates existantes : `_construire_propositions`
    les groupera automatiquement (aucune logique de groupage à dupliquer ici).

    Coût : 1 appel de vitrine + 1 appel d'historique de prix par AUTRE carte
    retenue (limited/rare uniquement — mêmes raretés que le reste du
    projet), par petit vendeur. Voir DECISIONS.md (2026-09-22).
    """
    assets_deja_connus = {c.annonce.asset_id for c in candidates}
    supplementaires: list[Candidate] = []

    for slug_vendeur in petits_vendeurs:
        vitrine = requetes.vitrine_vendeur(client, slug_vendeur, premieres=cartes_max_par_vendeur)
        if not vitrine:
            continue
        autres = [
            a
            for a in annonces_depuis_noeuds_marche(vitrine["nodes"])
            if a.asset_id not in assets_deja_connus
            and rarity_brute_depuis_annonce(a) in ("limited", "rare")
        ]
        for annonce in autres:
            candidate = _evaluer_autre_carte_vendeur(
                client, horloge, annonce, seuil_pourcent, seuil_sous_vente_min_pourcent
            )
            if candidate is None:
                continue
            supplementaires.append(candidate)
            assets_deja_connus.add(annonce.asset_id)

    return candidates + supplementaires


def main() -> int:
    configurer_journalisation()

    parser = argparse.ArgumentParser(
        description="Passe marche en lecture seule : applique nos criteres de decision "
        "a un echantillon du marche reel. N'ecrit jamais rien (ni base, ni Sorare)."
    )
    parser.add_argument(
        "--premieres",
        type=int,
        default=NOMBRE_ANNONCES_EXAMINEES_DEFAUT,
        help=f"Taille de l'échantillon d'annonces examinées (défaut {NOMBRE_ANNONCES_EXAMINEES_DEFAUT}).",
    )
    parser.add_argument(
        "--seuil",
        type=int,
        default=SEUIL_BONNE_AFFAIRE_DEFAUT,
        help=f"Seuil de bonne affaire, en %% de la référence (défaut {SEUIL_BONNE_AFFAIRE_DEFAUT}).",
    )
    parser.add_argument(
        "--sortie",
        type=str,
        default=None,
        help="Chemin d'un fichier .txt où écrire le rapport (en plus de l'affichage).",
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
        print("Réconciliation avec Sorare...")
        rapport_reconciliation = reconcilier(session, client, horloge)
        session.commit()
        if rapport_reconciliation.cycle_suspendu:
            print("  ⚠ une dépense non décidée par le bot a été détectée "
                  "(python -m acheteur.cli.reconcilier pour le détail) — "
                  "le rapport continue, mais les soldes affichés peuvent être imprécis.")
        else:
            print("  OK")
        print()

        print("Récupération de l'état du compte...")
        compte = requetes.etat_compte(client)
        soldes = _soldes_reels(compte)
        offres_ouvertes = _offres_ouvertes_par_devise_info(session)
        print()

        print(f"Récupération de {args.premieres} annonces du marché...")
        noeuds_marche = requetes.annonces_marche(client, premieres=args.premieres)
        annonces = annonces_depuis_noeuds_marche(noeuds_marche)
        print(f"  {len(annonces)} annonces traduites (sur {len(noeuds_marche)} nœuds bruts)")
        print()

        print(f"Calcul de la liquidité puis des références réelles "
              f"(par lot de {requetes.TAILLE_LOT_HISTORIQUE_PRIX_DEFAUT} joueurs)...")
        candidates, illiquide, sans_reference = _calculer_candidates(client, horloge, annonces)
        print(f"  {len(candidates)} liquides avec référence exploitable, "
              f"{illiquide} illiquides, {sans_reference} sans référence")
        print()

        bonnes_affaires = _bonnes_affaires(candidates, args.seuil)
        sous_le_seuil = len(candidates) - len(bonnes_affaires)

        print("Vérification de la taille de vitrine des vendeurs concernés...")
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
        print(f"  {len(bonnes_affaires)} candidates après filtre de joignabilité")
        print()

        petits_vendeurs = _petits_vendeurs(
            bonnes_affaires, stocks, STOCK_MAX_VENDEUR_DEFAUT, OFFRE_GROUPEE_VENDEURS_MAX_DEFAUT,
        )
        if petits_vendeurs:
            print(f"Offre groupée réactive : relecture de {len(petits_vendeurs)} "
                  "vitrine(s) de petit(s) vendeur(s)...")
            avant = len(bonnes_affaires)
            bonnes_affaires = _completer_par_vitrines_vendeurs(
                client, horloge, bonnes_affaires, args.seuil,
                SOUS_VENTE_MINI_SEUIL_POURCENT_DEFAUT, petits_vendeurs,
                OFFRE_GROUPEE_CARTES_MAX_PAR_VENDEUR_DEFAUT,
            )
            print(f"  {len(bonnes_affaires) - avant} carte(s) supplémentaire(s) qualifiée(s)")
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
            print(f"Rapport écrit dans {args.sortie}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
