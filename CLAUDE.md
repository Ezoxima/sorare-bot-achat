# CLAUDE.md

Contexte pour tout assistant (ou humain) qui reprend ce dépôt.

## Ce projet dépense de l'argent réel

Ce n'est pas un projet logiciel ordinaire : le code écrit ici, une fois en
mode réel, engage des paiements Sorare sans confirmation humaine par appel
(phase 2) ou avec confirmation asynchrone par mail (phase 1). Toute
modification touchant `acheteur/garde_fous/`, `acheteur/paiement/`,
`acheteur/sorare/mutations.py` ou `acheteur/negociation/` doit être relue
avec le niveau d'attention d'une revue de code bancaire, pas d'un script
interne.

Lire [PLAN.md](PLAN.md) en entier avant de toucher à ces modules — il
contient les décisions déjà prises et leurs raisons ; ne pas les
redemander, ne pas les re-trancher unilatéralement.

## Règles non négociables (résumé — PLAN.md fait foi)

- **Un seul chemin vers l'envoi d'une offre**, qui passe par la barrière
  (`acheteur/garde_fous/`). Il existe un test qui le vérifie mécaniquement en
  parcourant le code source — ne jamais le contourner « pour tester ».
- **Le bot démarre en simulation** et y revient à chaque redémarrage. Le mode
  réel ne se déverrouille jamais par un seul réglage.
- **Aucun flottant** sur un montant qui touche un rail de paiement (ETH a 18
  décimales ; un flottant les massacre silencieusement). Toujours des entiers
  (wei, centimes).
- **Le mot de passe Sorare et les codes 2FA ne sont jamais stockés, ni
  journalisés, ni importés par la boucle automatique.** Seul
  `acheteur/auth/connexion.py` (isolé) les manipule, en mémoire, le temps
  d'un appel.
- **Le jeton JWT va dans le gestionnaire d'identifiants Windows**
  (`acheteur.auth.jeton`), jamais dans un fichier.
- **L'horloge est injectable partout** où du code raisonne sur des dates
  (comparaison prix/marché, expiration de jeton, escalade). Ne jamais appeler
  `datetime.now()` en dur dans `acheteur/decision/`, `acheteur/marche/`,
  `acheteur/negociation/`.
- **Figer la référence de marché au moment de l'envoi**, ne jamais la
  recalculer après coup dans le journal des offres (ça a déjà cassé un
  projet frère, Pickdeck — voir PLAN.md).
- **Contraintes en base, pas seulement dans le code** : palier ≤ 80 %,
  référence sur ≥ 3 ventes, ligne simulée sans identifiant Sorare.

## Conventions héritées de Pickdeck (`sorare_app_v2`)

- Fonctions de décision **pures**, sans réseau ni base, testables sur des cas
  figés. Les appels API et les écritures vivent chez l'appelant.
- `acheteur/sorare/client.py` est un **port** du client GraphQL de Pickdeck
  (même throttle, même gestion 429/backoff). Le garder synchronisé si
  Pickdeck corrige un bug dessus vaut la peine d'être vérifié à l'occasion,
  mais ce n'est pas un couplage — les deux fichiers divergent librement.
- Regénérer le SDL local avec `scripts/rafraichir_schema.py` avant de grep un
  champ GraphQL — l'introspection `{ __schema }` est désactivée côté Sorare.

## Ce dépôt ne lit jamais la base de Pickdeck

Couplage volontairement évité (voir PLAN.md). Si un besoin de lire les
données de Pickdeck apparaît, c'est un signal pour reposer la question, pas
pour ajouter une connexion croisée en douce.

## Où sont les décisions et les mesures

- **PLAN.md** : la conception, figée le 2026-09-20, avec ses raisons.
- **DECISIONS.md** : journal daté des décisions prises *après* PLAN.md
  (celles qui affinent ou révisent le plan initial).
- **MESURES.md** : ce qui est *prouvé* par une sonde réelle contre l'API
  Sorare, avec sa date et son effectif — à distinguer de ce que PLAN.md
  *suppose*.
