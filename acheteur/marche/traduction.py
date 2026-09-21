"""Traduction des nœuds bruts Sorare (marché, historique de prix) vers les
types du domaine (`Annonce`, `Vente`, `Joueur`).

Fonctions pures : aucun réseau, aucune base — testables sur des cas figés,
comme le reste de `acheteur.decision` et `acheteur.marche` (CLAUDE.md,
convention héritée de Pickdeck). Les requêtes brutes vivent dans
`acheteur.sorare.requetes` ; ce module ne fait que les mettre en forme.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from acheteur.marche.devises import Devise, Montant
from acheteur.marche.types import Annonce, Joueur, Rareté, Vente

# Rarity (schéma Sorare, minuscules) -> Rareté du domaine. Le classement
# (1-4, « du plus courant au plus rare », PLAN.md) ne couvre que les quatre
# raretés historiques ; `unique` et `custom_series` sont rangées avec
# `super_rare` (4) faute d'un rang PLAN.md-défini pour elles — approximation
# à revoir si le classement doit un jour trancher entre elles.
_RARETES = {
    "common": Rareté("Common", 1),
    "limited": Rareté("Limited", 2),
    "rare": Rareté("Rare", 3),
    "super_rare": Rareté("Super Rare", 4),
    "unique": Rareté("Unique", 4),
    "custom_series": Rareté("Custom Series", 4),
}


def rarete_depuis_sorare(rarity_brute: str) -> Rareté:
    """Traduit une valeur brute de l'enum `Rarity` Sorare en `Rareté`.

    Raises:
        ValueError: rareté inconnue du schéma local — mieux vaut échouer
            bruyamment que deviner un classement.
    """
    if rarity_brute not in _RARETES:
        raise ValueError(f"Rareté Sorare inconnue : {rarity_brute!r}")
    return _RARETES[rarity_brute]


def rarity_brute_depuis_annonce(annonce: Annonce) -> str:
    """Reconstruit la valeur brute de l'enum `Rarity` Sorare depuis le nom
    lisible stocké sur `Rareté` (« Super Rare » -> « super_rare »).

    Aller-retour exact avec `rarete_depuis_sorare` — testé (voir
    `tests/test_premiere_offre_reelle_l6.py`). Partagée par tout script qui a
    besoin de rappeler `tokenPrices` avec le même `rarity` que celui lu sur
    une annonce (L6, L7).
    """
    return annonce.joueur.rareté.nom.lower().replace(" ", "_")


def season_eligibility_brute_depuis_annonce(annonce: Annonce) -> str:
    """`SeasonEligibility` Sorare (`CLASSIC`/`IN_SEASON`) depuis `Annonce.in_season`.

    Une carte in-season (éligible aux compétitions en cours) et une carte
    classic du même joueur/rareté ne se vendent pas au même prix : sans ce
    filtre sur `tokenPrices`, la référence mélange deux populations de
    ventes sans rapport (constaté en session, lot L6, voir MESURES.md).
    """
    return "IN_SEASON" if annonce.in_season else "CLASSIC"


def _montant_depuis_amounts(amounts: dict[str, Any] | None) -> Montant | None:
    """Lit un `MonetaryAmount` brut. Préfère EUR ; sinon wei. `None` si les
    deux sont absents (rien n'a été demandé dans cette devise)."""
    if not amounts:
        return None
    eur = amounts.get("eurCents")
    if eur is not None:
        return Montant(int(eur), Devise.EUR)
    wei = amounts.get("wei")
    if wei is not None:
        return Montant(int(wei), Devise.ETH)
    return None


def annonce_depuis_noeud_marche(noeud: dict[str, Any]) -> Annonce | None:
    """Traduit un nœud brut `liveSingleSaleOffers` en `Annonce`.

    Une annonce à prix fixe (`SINGLE_SALE_OFFER`) porte une carte d'un côté
    et un prix demandé de l'autre, mais on ne sait pas encore, sans l'avoir
    vérifié contre l'API réelle (voir `sorare.requetes.ANNONCES_MARCHE_QUERY`),
    lequel de `senderSide`/`receiverSide` porte quoi. On prend donc le côté
    qui porte des cartes comme « la carte à vendre », et l'autre côté comme
    « le prix demandé », plutôt que de figer une hypothèse non vérifiée.

    Renvoie `None` (silencieusement, comme `depuis_reponse_sorare` pour les
    devises non gérées) quand le nœud n'a pas la forme attendue — une seule
    carte, un prix dans une devise gérée (EUR ou wei) — plutôt que de
    deviner. Un type d'offre différent de `SINGLE_SALE_OFFER` est ignoré.
    """
    if noeud.get("type") != "SINGLE_SALE_OFFER":
        return None

    cote_a = noeud.get("senderSide") or {}
    cote_b = noeud.get("receiverSide") or {}

    cartes_a = cote_a.get("anyCards") or []
    cartes_b = cote_b.get("anyCards") or []

    if len(cartes_a) == 1 and not cartes_b:
        cote_carte, cote_prix = cartes_a[0], cote_b
    elif len(cartes_b) == 1 and not cartes_a:
        cote_carte, cote_prix = cartes_b[0], cote_a
    else:
        # Zéro carte, ou plusieurs (un lot) : hors périmètre L6 (« une seule
        # offre, sur la carte la moins chère »).
        return None

    prix = _montant_depuis_amounts(cote_prix.get("amounts"))
    if prix is None or prix.valeur <= 0:
        return None

    joueur_brut = cote_carte.get("anyPlayer") or {}
    joueur_slug = joueur_brut.get("slug")
    asset_id = cote_carte.get("assetId")
    rarity_brute = cote_carte.get("rarityTyped")
    in_season = cote_carte.get("inSeasonEligible")
    vendeur_slug = (noeud.get("userSeller") or {}).get("slug")

    if not (joueur_slug and asset_id and rarity_brute and vendeur_slug):
        return None
    if in_season is None:
        # Pas de fourre-tout : sans cette information, `reference_prix_joueur`
        # n'a aucun moyen de savoir sur quelle population de ventes se caler
        # (classic vs in-season, voir marche/types.py) — mieux vaut ignorer
        # l'annonce que produire une référence qui mélange les deux.
        return None

    date_pose_brute = noeud.get("createdAt")
    if not date_pose_brute:
        return None

    return Annonce(
        joueur=Joueur(
            slug=joueur_slug,
            nom=joueur_brut.get("displayName", joueur_slug),
            rareté=rarete_depuis_sorare(rarity_brute),
        ),
        vendeur_slug=vendeur_slug,
        prix_demande=prix,
        accepte_eth=prix.devise == Devise.ETH,
        accepte_eur=prix.devise == Devise.EUR,
        date_pose=datetime.fromisoformat(date_pose_brute),
        asset_id=asset_id,
        in_season=bool(in_season),
    )


def annonces_depuis_noeuds_marche(noeuds: list[dict[str, Any]]) -> list[Annonce]:
    """Traduit une liste de nœuds bruts, en ignorant silencieusement ceux
    qui n'ont pas la forme attendue (voir `annonce_depuis_noeud_marche`)."""
    annonces = []
    for noeud in noeuds:
        annonce = annonce_depuis_noeud_marche(noeud)
        if annonce is not None:
            annonces.append(annonce)
    return annonces


def vente_depuis_noeud_prix(noeud: dict[str, Any], joueur: Joueur) -> Vente | None:
    """Traduit un nœud brut `tokenPrices` en `Vente` pour un joueur donné.

    Renvoie `None` si le montant n'est dans aucune devise gérée, ou si la
    date est absente — plutôt que d'inventer une vente incomplète.
    """
    prix = _montant_depuis_amounts(noeud.get("amounts"))
    date_brute = noeud.get("date")
    if prix is None or prix.valeur <= 0 or not date_brute:
        return None
    return Vente(joueur=joueur, prix=prix, date_vente=datetime.fromisoformat(date_brute))


def ventes_depuis_noeuds_prix(noeuds: list[dict[str, Any]], joueur: Joueur) -> list[Vente]:
    """Traduit une liste de nœuds `tokenPrices` en `Vente`, en ignorant
    silencieusement ceux qui n'ont pas la forme attendue."""
    ventes = []
    for noeud in noeuds:
        vente = vente_depuis_noeud_prix(noeud, joueur)
        if vente is not None:
            ventes.append(vente)
    return ventes
