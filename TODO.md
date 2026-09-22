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

**Élément chiffré, apporté par l'utilisateur après coup** : son ancien
script Apps Script (`sealing-sorare-apps-script`) retrouvait « plusieurs
milliers de couples » — ici, `--premieres 500` (défaut) ne récupère que 500
annonces brutes du marché entier, réduites à 273 couples distincts après
traduction/dédoublonnage, sur un marché mesuré à **543 496 annonces au
total** (MESURES.md, 2026-09-22). L'échantillon actuel couvre environ
0,1 % du marché.

**Confirmé, pas juste une hypothèse : l'utilisateur a fourni le code source
réel de `sealing-sorare-apps-script/02 - liste bonnes affaires.gs`
(2026-09-22).** La méthode d'échantillonnage n'a rien à voir avec la nôtre :

- `majListeComplete()` (référencé, pas encore vu) balaie **le pool COMPLET
  de 36 065 joueurs** et écrit, pour chacun, s'il a une annonce en cours
  (`Joueurs_en_vente`) — un balayage exhaustif par JOUEUR, pas un tirage
  dans le flux d'annonces.
- `majListeBonnesAffaires()` part de cette liste complète et mesure
  liquidité (`liquiditeParCouple_`) + profondeur de carnet
  (`carnetParJoueur_`) pour CHAQUE joueur qui vend, sans échantillonnage
  supplémentaire.

Chez nous, `maj_liste_liquidite.py::main()` interroge
`annonces_marche_paginees` (le marché entier, trié par fraîcheur de mise à
jour) et s'arrête à `--premieres` annonces (500 par défaut) — **on ne
balaie jamais les joueurs, on pioche dans le flux d'annonces les plus
récentes.** C'est structurellement différent : une carte qui se revend
souvent revient sans cesse dans ce flux (donc généralement peu chère) ;
une carte chère revendue une fois par mois n'apparaît presque jamais dans
les 500 premières. **Hypothèse (1) du TODO confirmée par le code source
réel, pas seulement plausible.**

**Le correctif identifié (pas encore fait)** : écrire un équivalent de
`majListeComplete()` côté `acheteur` — balayer une liste de référence des
joueurs (via `players()` ou un référentiel équivalent) et vérifier pour
chacun s'il a une annonce en cours, plutôt que d'échantillonner le flux
`liveSingleSaleOffers` trié par fraîcheur. `maj_liste_liquidite.py`
resterait ensuite quasi inchangé (il ne ferait plus que mesurer la
liquidité sur cette liste complète, comme aujourd'hui sur son petit
échantillon).

**Cadence confirmée par l'utilisateur (2026-09-22) : une fois par jour**,
comme l'Apps Script (`majListeBonnesAffaires()`, « à programmer une fois
par jour ») — cohérent avec `DELAI_RAFRAICHISSEMENT_HEURES = 24` déjà en
place côté `acheteur` (`marche/liste_liquidite.py`), qui n'a donc pas
besoin de changer une fois le vrai correctif écrit.

**Première moitié du correctif faite (2026-09-22) : le référentiel de
joueurs existe maintenant.** L'utilisateur a fourni le code source de
`genererListeJoueurs()` (Apps Script) : construit `LISTE_COMPLETE` (le CSV
d'origine, collé à la main depuis `sorare_app_v2`) directement depuis l'API
Sorare — compétitions énumérables (`leaguesOpenForGameStats`,
`cardShardsPoolCompetitions`) → clubs de chaque compétition
(`football.competitions(slugs:).clubs`, paginé) → joueurs actifs de chaque
club (`football.club(slug:).anyActivePlayers`, aliasé par lots de 150
clubs, paginé). Porté côté `acheteur` :

- [acheteur/marche/referentiel_joueurs.py](acheteur/marche/referentiel_joueurs.py)
  — persistance (même forme que `liste_liquidite.py` : remplacement complet,
  péremption à 24h).
- [acheteur/sorare/requetes.py](acheteur/sorare/requetes.py) — 6 nouvelles
  requêtes (section « Référentiel de joueurs » en fin de fichier).
- [acheteur/cli/maj_referentiel_joueurs.py](acheteur/cli/maj_referentiel_joueurs.py)
  — orchestration, à planifier une fois par jour (commande `schtasks` dans
  le docstring, tâche pas enregistrée dans cette session).

**Pas encore fait, et c'est la partie qui change réellement le résultat** :
brancher ce référentiel dans `maj_liste_liquidite.py` — aujourd'hui ce
script échantillonne toujours `annonces_marche_paginees` (le flux
d'annonces trié par fraîcheur), pas le référentiel. Tant que ce câblage
n'est pas fait, `maj_referentiel_joueurs.py` construit une liste inutilisée
par le reste du pipeline.

**Vérifié contre l'API réelle (2026-09-22, voir MESURES.md)** : l'utilisateur
a lancé `python -m acheteur.cli.maj_referentiel_joueurs` — 26 589 joueurs
écrits, cohérent avec l'estimation Apps Script (~26 000). La méthode
d'énumération marche donc bien côté Python, pas seulement côté Apps
Script. Pas encore mesurés séparément : nombre de clubs, appels réseau,
temps d'exécution (voir MESURES.md pour le détail de ce qui manque).

**Branché et vérifié contre le réel (2026-09-22, voir MESURES.md)** :
`maj_liste_liquidite.py` mesure maintenant tout le référentiel — l'utilisateur
a lancé le run complet, **2 942 couples liquides retenus sur 106 356
mesurés**, contre 19 avec l'ancien pipeline (155x plus). Le diagnostic
initial de ce TODO (échantillonnage biaisé vers les cartes bon marché) est
corrigé côté construction de la liste.

**Vérifié et confirmé (2026-09-22, voir MESURES.md) : effet réel sur les
propositions.** `proposer_periodique.py` relancé après le run complet de
`maj_liste_liquidite.py` — propositions incluant des joueurs Rare (Ramiz
Zerrouki 47€, Fabian Wilfinger 6,3€) et un total EUR proposé dans le
budget de 56,53€, contre 2,11€ avant ce lot. **Ce fil du TODO est clos** :
le biais d'échantillonnage identifié le 2026-09-22 (échantillon par
fraîcheur d'annonces → liste liquide dominée par des cartes bon marché)
est corrigé de bout en bout, mesuré contre le réel à chaque étape.

**Reste ouvert, séparément** : batcher `_annonces_du_couple`
(`scan_liste_liquidite.py`) par lots d'alias — un run scanne aujourd'hui
2 942 couples avec un appel réseau chacun, séquentiel, plusieurs minutes.
Un log de progression a été ajouté (2026-09-22, DECISIONS.md) mais ne
réduit pas le temps réel. Pas un chantier urgent (le job tourne en tâche
planifiée, pas en interactif), mais à traiter si la durée devient gênante.
