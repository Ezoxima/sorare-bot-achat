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

## 2026-09-20 — Lot L3

**Population liquide : 5+ ventes en 30 jours.**
PLAN.md dit « recalculée en Python par le bot » sans donner le critère exact.
Choix : minimum 5 ventes dans les 30 derniers jours, injectable pour test. La
fenêtre et l'effectif minimal sont des réglages — le premier tir mesurera si
ces seuils donnent une population raisonnable à comparer avec ta feuille.

**Référence de prix : médiane, 7 jours, min 3 ventes.**
PLAN.md (ligne 368-370) laisse ouverts « médiane ou moyenne » et « fenêtre
3-7 jours selon le joueur ». Choix : médiane (comme Pickdeck) sur 7 jours
fixes, minimum 3 ventes. La fenêtre et le seuil sont injectables pour affiner
après mesure. Les ventes hors-fenêtre sont ignorées. Tous les prix d'un
joueur doivent être dans la même devise (erreur si mélange).

**Seuil et paliers : 90%, puis 70/75/80%.**
PLAN.md § 350-364 tranche complètement : filtre sous 90% de référence, puis
escalade à 70%, 75%, 80% du prix demandé. Implémentation directe, pas
d'hypothèse supplémentaire.

**Groupage par vendeur : décote 65% au premier palier seulement.**
PLAN.md (ligne 373) mentionne une « décote supplémentaire des offres groupées
(65 % au lieu de 70 %) ». Implémentation : si on propose plusieurs cartes au
même vendeur au premier palier, on offre 65% du prix demandé. Aux paliers
suivants, le palier s'applique normalement. Le choix d'appliquer la décote
**seulement** au premier palier rend la groupage intéressante au démarrage.

**Fonctions pures, testables.**
Tous les calculs vivent dans `acheteur/marche/` (population, référence) et
`acheteur/decision/` (sélection, paliers, groupage, propositions). Zéro appel
réseau, zéro écriture base : seuls les paramètres changent. 14 cas de test
couvrent les chemins critiques et les bornes.

## 2026-09-20 — Corrections lot L3 (revue post-implémentation)

Trois défauts trouvés en revue, corrigés, chacun avec un test de non-régression :

**`est_bonne_affaire` comparait une devise à elle-même.** `selecteur.py`
vérifiait `annonce.prix_demande.devise != annonce.prix_demande.devise` —
toujours faux, donc aucune vérification réelle. Corrigé : la fonction prend
maintenant la référence sous forme de `Montant` (pas un `int` nu, qui avait
fait perdre la devise en route) et compare vraiment les deux devises, avec
`ValueError` si elles diffèrent. `selectionner_annonces` suit le même
contrat (`dict[str, Montant]`).

**Décote de groupage à deux règles différentes.** `groupage.montants_offre_groupe`
prenait un booléen `decote_groupe` laissé au choix de l'appelant ;
`proposition.proposer_groupe` décidait seule, automatiquement, sur
`len(annonces) > 1`. Deux fonctions pour le même calcul, deux résultats
possibles pour le même groupe selon celle qu'on appelle. Corrigé : la règle
du 2026-09-20 (« décote seulement si plus d'une annonce, au premier palier »)
est maintenant la seule, appliquée par les deux fonctions de la même façon ;
`montants_offre_groupe` a perdu son paramètre `decote_groupe`.

**Médiane sur nombre pair de ventes reposait sur un flottant implicite.**
`statistics.median` renvoie la moyenne des deux valeurs centrales (un
flottant) quand l'effectif est pair ; `reference_prix.py` la tronquait avec
`int(...)`. Remplacé par une division entière explicite sur les valeurs
triées — aucun flottant ne touche plus le calcul, conforme à CLAUDE.md.

## 2026-09-20 — Lot L2 : journal + réconciliation en lecture seule

**Une ligne de journal = une carte, pas un lot groupé.**
PLAN.md ne tranche pas la granularité de la ligne. Le groupage (lot L3,
calcul pur) n'a encore aucun chemin d'envoi (lots L5+/L8) : modéliser une
ligne comme un lot de plusieurs cartes maintenant serait de la spéculation
sur une forme qui n'existe pas encore. Choix : une ligne par carte. À
revoir explicitement au lot L8 quand l'envoi groupé sera écrit — pas avant.

**Contraintes de décision (palier ≤ 80%, référence ≥ 3 ventes) suspendues
pour une ligne importée.** Une offre trouvée sur Sorare sans contrepartie
dans le journal (faite à la main depuis l'appli web, PLAN.md § « Le
journal des offres ») n'est passée par aucune décision du bot : lui imposer
un palier ou une référence inventerait une donnée. Choix : ces colonnes
sont nullables, les CHECK correspondants ne portent que sur
`import_automatique = 0`. La ligne importée porte quand même l'identifiant
Sorare, le montant réellement observé et son état — ce qu'on sait vraiment.

**Créneau horaire de l'appariement par signature : 15 minutes, autour de
l'horodatage d'écriture de notre ligne (`cree_le`), pas de la date de pose
de l'annonce du vendeur.** PLAN.md mentionne « même créneau horaire » sans
donner de valeur ni préciser quel horodatage. Le bon repère est le moment
où *notre* offre a été écrite (proche du moment où Sorare l'a créée), pas
la date de mise en vente par le vendeur, qui peut être bien antérieure. La
tolérance (15 min) est un réglage à affiner si des cas réels la débordent.

**Requête `offres_envoyees` (`sorare/requetes.py`) non vérifiée contre
l'API réelle.** Portée directement du SDL local
(`UserOffersInterface.tokenOffers`, `TokenOffer`, `TokenOfferSide`), comme
`renouvellement.py` l'avait été au lot L0 : plausible sur la forme du
schéma, jamais encore exécutée contre le compte réel. À vérifier au premier
`python -m acheteur.cli.reconcilier` réel (voir MESURES.md) — en particulier
le mapping `senderSide`/`receiverSide` (montant payé vs. cartes reçues) et
la sémantique de `receiver` comme vendeur.
