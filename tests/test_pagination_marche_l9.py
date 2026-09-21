"""Pagination par curseur de `annonces_marche_paginees` (voir DECISIONS.md
et MESURES.md, 2026-09-22) — testée avec un faux client, pas de réseau réel."""

from __future__ import annotations

from acheteur.sorare.requetes import annonces_marche_paginees


class _ClientFactice:
    """Simule `liveSingleSaleOffers` paginé par curseur : `pages` est une
    liste de (nodes, has_next_page), une entrée consommée par appel."""

    def __init__(self, pages: list[tuple[list[dict], bool]]) -> None:
        self._pages = pages
        self.appels = 0

    def execute(self, query: str, variables: dict | None = None) -> dict:
        nodes, has_next = self._pages[self.appels]
        premieres = (variables or {}).get("first")
        if premieres is not None:
            nodes = nodes[:premieres]
        curseur = f"curseur{self.appels}" if has_next else None
        self.appels += 1
        return {
            "tokens": {
                "liveSingleSaleOffers": {
                    "nodes": nodes,
                    "pageInfo": {"hasNextPage": has_next, "endCursor": curseur},
                }
            }
        }


def _noeuds(n: int, prefixe: str) -> list[dict]:
    return [{"id": f"{prefixe}-{i}"} for i in range(n)]


class TestAnnoncesMarchePaginees:
    def test_avance_sur_plusieurs_pages(self):
        client = _ClientFactice(
            [
                (_noeuds(50, "p1"), True),
                (_noeuds(50, "p2"), True),
                (_noeuds(20, "p3"), True),
            ]
        )
        resultat = annonces_marche_paginees(client, maximum=120)
        assert len(resultat) == 120
        assert client.appels == 3

    def test_s_arrete_a_hasnextpage_false(self):
        client = _ClientFactice([(_noeuds(50, "p1"), False)])
        resultat = annonces_marche_paginees(client, maximum=1000)
        assert len(resultat) == 50
        assert client.appels == 1

    def test_ne_depasse_jamais_maximum(self):
        client = _ClientFactice([(_noeuds(50, "p1"), True), (_noeuds(50, "p2"), True)])
        resultat = annonces_marche_paginees(client, maximum=75)
        assert len(resultat) == 75
        assert client.appels == 2
