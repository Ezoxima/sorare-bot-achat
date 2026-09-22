"""Reconstruit le référentiel de joueurs (pool complet) depuis l'API Sorare
elle-même — compétitions → clubs → joueurs actifs — sans dépendre d'aucune
base externe (`marche/referentiel_joueurs.py`).

Pourquoi ce script existe : `maj_liste_liquidite.py` échantillonne
aujourd'hui les annonces du marché triées par fraîcheur de mise à jour, pas
par joueur — biais structurel confirmé (TODO.md, 2026-09-22) vers les
cartes bon marché qui se revendent souvent. La correction (câbler ce
référentiel dans `maj_liste_liquidite.py`) reste un chantier séparé, pas
fait ici : ce script ne fait que construire et persister la liste des
joueurs, l'étape manquante identifiée dans TODO.md.

Méthode portée de `sealing-sorare-apps-script/genererListeJoueurs.gs`
(fourni par l'utilisateur, 2026-09-22, mesurée par sonde côté Apps Script
avant écriture) — **NON ENCORE VÉRIFIÉE contre l'API réelle côté Python**
(voir MESURES.md) :

1. `leaguesOpenForGameStats` + `clubsReady` énumèrent une partie du pool
   sans argument.
2. `cardShardsPoolCompetitions` ajoute les compétitions du pool de craft.
3. `football.competitions(slugs:).clubs` rend les clubs de chaque
   compétition (pagination pour les coupes continentales à >100 clubs).
4. `football.club(slug:).anyActivePlayers`, aliasé par lots de 150 clubs
   sous un seul `football { }` (pagination pour les clubs à >50 joueurs).

Couverture attendue, mesurée côté Apps Script : ~800 clubs, ~26 000
joueurs (contre 36 065 dans l'ancien CSV — écart documenté dans le
docstring Apps Script d'origine, compétitions mineures qu'aucune requête
API ne rend aujourd'hui en une fois).

À reconstruire une fois par jour (`DELAI_RAFRAICHISSEMENT_HEURES = 24`,
`marche/referentiel_joueurs.py`) — le pool de joueurs actifs ne change pas
assez vite (transferts, retraites) pour justifier plus.

Usage :
    python -m acheteur.cli.maj_referentiel_joueurs

Pour planifier une fois par jour (Windows) :
    schtasks /create /tn "Acheteur - referentiel joueurs" /sc daily ^
        /tr "\"<chemin\\python.exe>\" -m acheteur.cli.maj_referentiel_joueurs" ^
        /st 03:00
"""

from __future__ import annotations

import sys

from acheteur.auth.jeton import JetonAbsentError, JetonExpireError, obtenir_jeton_valide
from acheteur.auth.renouvellement import renouveler_si_necessaire
from acheteur.core.db import creer_tables, session_scope
from acheteur.core.horloge import HorlogeSysteme
from acheteur.core.journalisation import configurer_journalisation
from acheteur.marche.referentiel_joueurs import remplacer_referentiel_joueurs
from acheteur.sorare import requetes
from acheteur.sorare.client import SorareClient


def _competition_domestique(competitions_actives: list[dict]) -> str:
    """La compétition DOMESTIC_LEAGUE du club, comme le CSV d'origine.

    Fonction pure : pas de réseau, testable sur des cas figés.
    """
    for c in competitions_actives or []:
        if c.get("format") == "DOMESTIC_LEAGUE":
            return c.get("slug") or ""
    return ""


def _tous_clubs(client: SorareClient) -> list[str]:
    """Le pool complet de clubs, toutes compétitions connues confondues."""
    competitions, clubs_deja_connus = requetes.competitions_et_clubs_enumerables(client)
    for slug in requetes.cardshards_pool_competitions(client):
        if slug not in competitions:
            competitions.append(slug)

    clubs = set(clubs_deja_connus)
    resultats = requetes.clubs_des_competitions(client, competitions)
    a_repaginer = []
    for comp in resultats:
        bloc = comp.get("clubs") or {}
        for noeud in bloc.get("nodes") or []:
            clubs.add(noeud["slug"])
        page_info = bloc.get("pageInfo") or {}
        if page_info.get("hasNextPage") and page_info.get("endCursor"):
            a_repaginer.append({"slug": comp["slug"], "apres": page_info["endCursor"]})

    while a_repaginer:
        suite = []
        for item in a_repaginer:
            bloc = requetes.clubs_dune_competition_page(client, item["slug"], item["apres"])
            for noeud in bloc.get("nodes") or []:
                clubs.add(noeud["slug"])
            page_info = bloc.get("pageInfo") or {}
            if page_info.get("hasNextPage") and page_info.get("endCursor"):
                suite.append({"slug": item["slug"], "apres": page_info["endCursor"]})
        a_repaginer = suite

    return sorted(clubs)


def _joueurs_des_clubs(
    client: SorareClient,
    slugs_clubs: list[str],
    taille_lot: int = requetes.TAILLE_LOT_CLUBS_JOUEURS_DEFAUT,
) -> dict[str, dict]:
    """Les joueurs actifs de tous les clubs, indexés par slug joueur (un
    joueur transféré en cours de saison n'apparaît qu'une fois, pour son
    club le plus récemment vu)."""
    joueurs: dict[str, dict] = {}
    a_repaginer = []

    for debut in range(0, len(slugs_clubs), taille_lot):
        lot = slugs_clubs[debut : debut + taille_lot]
        noeuds = requetes.joueurs_actifs_des_clubs_lot(client, lot)
        for slug_club, noeud in zip(lot, noeuds, strict=True):
            if noeud is None:
                continue
            competition = _competition_domestique(noeud.get("activeCompetitions"))
            page = noeud.get("anyActivePlayers") or {}
            for p in page.get("nodes") or []:
                slug_joueur = p.get("slug")
                if not slug_joueur:
                    continue
                joueurs[slug_joueur] = {
                    "slug": slug_joueur,
                    "nom": p.get("displayName") or "",
                    "club_slug": slug_club,
                    "competition": competition,
                }
            page_info = page.get("pageInfo") or {}
            if page_info.get("hasNextPage") and page_info.get("endCursor"):
                a_repaginer.append(
                    {"slug": slug_club, "competition": competition, "apres": page_info["endCursor"]}
                )

    while a_repaginer:
        suite = []
        for item in a_repaginer:
            page = requetes.joueurs_actifs_club_page(client, item["slug"], item["apres"])
            for p in page.get("nodes") or []:
                slug_joueur = p.get("slug")
                if not slug_joueur:
                    continue
                joueurs[slug_joueur] = {
                    "slug": slug_joueur,
                    "nom": p.get("displayName") or "",
                    "club_slug": item["slug"],
                    "competition": item["competition"],
                }
            page_info = page.get("pageInfo") or {}
            if page_info.get("hasNextPage") and page_info.get("endCursor"):
                suite.append({
                    "slug": item["slug"],
                    "competition": item["competition"],
                    "apres": page_info["endCursor"],
                })
        a_repaginer = suite

    return joueurs


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
        print("Enumeration des competitions et clubs...")
        clubs = _tous_clubs(client)
        print(f"  {len(clubs)} clubs")
        print()

        print("Joueurs actifs de chaque club (par lots de "
              f"{requetes.TAILLE_LOT_CLUBS_JOUEURS_DEFAUT})...")
        joueurs = _joueurs_des_clubs(client, clubs)
        print(f"  {len(joueurs)} joueurs")
        print()

        nb = remplacer_referentiel_joueurs(session, list(joueurs.values()), horloge.maintenant())
        print(f"Referentiel remplace : {nb} joueur(s) ecrit(s) dans la base locale.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
