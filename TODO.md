# TODO

Points ouverts, pas encore corrigés — chacun daté, avec pourquoi il n'est
pas résolu immédiatement.

## 2026-09-22 — Comprendre en détail comment `maj_liste_liquidite.py` construit la liste liquide

**Constat** : la liste liquide (19 couples, run du 2026-09-22) ne contient
que des joueurs Limited (sauf un Rare) — aucune Super Rare, aucune Unique,
tous à faible valeur. Abaisser `ventes_30_mini` de 15 à 10 (voir DECISIONS.md,
même jour) n'a pas changé la nature du problème : les propositions restées
faibles (0,39€ à 0,88€) sur un budget disponible de 111€.

**Hypothèse posée mais pas vérifiée en détail** : `maj_liste_liquidite.py`
échantillonne les N annonces les plus récemment mises à jour sur tout le
marché (`annonces_marche_paginees`, triée par fraîcheur, pas par prix) —
une carte qui se revend souvent (donc généralement peu chère) revient sans
cesse dans cet échantillon ; une carte chère, mise en vente une fois et
jamais retouchée, reste hors échantillon indéfiniment. Cohérent avec le
biais déjà documenté pour `scan_marche.py`/`premiere_offre_reelle.py`
(DECISIONS.md, 2026-09-21), mais **jamais vérifié précisément pour
`maj_liste_liquidite.py` lui-même** : pas mesuré combien d'annonces
Rare/Super Rare/Unique apparaissent réellement dans l'échantillon brut
avant le filtre de liquidité, ni si le filtre de liquidité lui-même
élimine plus que l'échantillonnage.

**À faire avant de corriger quoi que ce soit** : instrumenter ou sonder
`maj_liste_liquidite.py` pour savoir, sur un run réel :
1. La répartition par rareté des annonces brutes échantillonnées (avant tout filtre).
2. Combien de couples par rareté passent le pré-filtre de liquidité.
3. Si le problème est surtout l'échantillonnage (1) ou surtout le critère
   de liquidité lui-même (2) — les deux corrections possibles ne sont pas
   les mêmes (élargir/changer l'échantillonnage vs. assouplir encore les
   seuils, avec le risque de biais différent).

**Pourquoi pas corrigé maintenant** : décision explicite de l'utilisateur
(2026-09-22) — comprendre d'abord le mécanisme en détail avant de choisir
un correctif, plutôt que d'empiler un réglage de plus sur une hypothèse non
vérifiée (cohérent avec CLAUDE.md — modules touchant à la décision d'achat).
