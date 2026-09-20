# Journal des décisions

Décisions prises *après* la conception initiale de [PLAN.md](PLAN.md)
(2026-09-20) — celles qui l'affinent ou tranchent un point qu'il laissait
ouvert. PLAN.md n'est pas réécrit rétroactivement ; ce journal est la source
pour « qu'est-ce qui a changé depuis ».

## 2026-09-20 — Lot L0

**Fichier de sonde déplacé chez Pickdeck, avant tout code ici.**
`backend/sonde_relist.json` (dans `sorare_app_v2`) contenait l'adresse
Ethereum et la clé StarkEx du compte, en clair, non tracké par git mais non
couvert non plus par une règle d'exclusion. Déplacé vers
`backend/discovery/` (déjà gitignoré) avec `backend/sonde_prepare_offer.json`.
Tâche indépendante du bot, listée dans PLAN.md comme prioritaire — faite
avant d'écrire la moindre ligne d'`acheteur`.

**Base de données : SQLite, pas PostgreSQL.**
PLAN.md ne tranche pas explicitement le moteur. Pickdeck utilise PostgreSQL,
mais `acheteur` tourne en tâche planifiée sur un seul poste, avec un seul
processus écrivain à la fois (l'unicité en base, PLAN.md § « Ne jamais
envoyer deux fois la même offre », marche aussi bien avec un index unique
SQLite). Pas de serveur à faire tourner ni à sécuriser pour un projet qui
manipule déjà de l'argent — le plus petit rayon d'exposition possible.
Mode WAL activé pour qu'une lecture (CLI d'inspection) ne bloque jamais un
cycle en écriture.

**`SorareClient` : le JWT n'a plus de valeur par défaut lue depuis `.env`.**
Dans Pickdeck, `SorareClient()` sans argument reprend `settings.sorare_jwt`.
Ici le JWT ne vit jamais dans `.env` (PLAN.md § Secrets) : `SorareClient`
part d'un JWT vide par défaut, et c'est à l'appelant de le fournir
explicitement, lu depuis `acheteur.auth.jeton.obtenir_jeton_valide()`. Divergence
volontaire du port — pas un oubli si on compare au fichier de Pickdeck.

**Renouvellement du jeton : mécanisme identifié dans le schéma, pas encore
vérifié en conditions réelles.**
PLAN.md affirme que le renouvellement se fait « sans mot de passe » trois
jours avant l'échéance. Le schéma GraphQL Sorare local
(`sorare_schema.graphql:14358`) confirme l'existence d'une mutation
`createJwtToken(input: {aud})`, authentifiable par le JWT encore valide —
c'est le mécanisme plausible. Implémenté dans
`acheteur/auth/renouvellement.py`, mais **jamais exécuté contre l'API réelle
à ce stade** : à vérifier au premier renouvellement venu (voir MESURES.md).
Seuil retenu : 3 jours avant échéance, valeur donnée par PLAN.md.

**Sonde d'état du compte : deux champs volontairement absents de la
requête.**
`UserWallet.passwordEncryptedPrivateKey` et
`UserWallet.privateKeyRecoveryPayload(s)` existent dans le schéma mais ne
sont jamais demandés par `acheteur/sorare/requetes.py` — aucune raison pour
ce bot de lire une clé privée chiffrée, même en lecture seule.
