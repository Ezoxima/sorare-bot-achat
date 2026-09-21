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

## 2026-09-20 — Lot L4 : Garde-fous + Barrière + Simulation + Scan

**Barrière : une seule fonction, deux modes (simulation ET réel).**
`barriere.envoyer_offre_proposal()` gère les deux modes via param
`mode_simulation`. Avantage : un seul chemin de code à protéger (plus simple),
la preuve mécanique du test unique_path.py tient sur tous les cas. Les 9
garde-fous s'appliquent aux deux modes de la même façon — seule la dernière
étape (appel Sorare) diffère.

**Contexte barrière** : plutôt qu'une forêt de paramètres à envoyer_offre_proposal(),
les garde-fous reçoivent un `ContexteBarriere` (dataclass) qui regroupe soldes,
offres ouvertes, taux de change, timestamps. Plus lisible, plus testable.

**Simulation mode : mode_simulation=True par défaut dans le scanner CLI.**
Le scanner (acheteur.cli.scanner) appelle envoyer_offre_proposal() avec
mode_simulation=True, écrit les lignes dans le journal avec etat=SIMULEE.
Aucun appel Sorare n'est fait. C'est la couche test du lot L4, utilisable
seul pour développement.

**Approbation phase 1 : tableau + retapez montant total.**
Pas de validation ligne-par-ligne interactif (trop lent pour 20+ propositions).
Format email-like (tableau markdown), puis re-entry du montant total —
« protocole d'un virement bancaire » (PLAN.md) qui empêche les clics
machinaux. La structure support du CLI est prête pour phase 2 (automatique,
L11) : juste changer l'appelant en un approuveur auto qui vérifie le taux
d'acceptation.

**Test unique_path.py : preuve AST qu'il n'existe qu'un seul appelant
enregistrer_ligne().**
Garantie structurelle, pas une promesse. Parcourt le source, trouve tout appel
à enregistrer_ligne(), vérifie qu'il n'existe qu'un fichier : barriere.py.
Aucune autre fonction, aucun autre module ne peut écrire le journal en envoyant.
Impossible de contourner les garde-fous.

**Requête annonces_marche() : placeholder pour L6.**
Sorare.requetes.annonces_marche() lève NotImplementedError pour l'instant.
À implémenter au lot L6 selon le schéma GraphQL Sorare réel. Pour L4
(simulation), le scanner teste la chaîne sur données mockées, pas sur marché.

**Module simulation.py** : permet de simuler acceptation/refus des offres
à titre de test, mise à jour des états (ACCEPTEE, REFUSEE + motif) sans
toucher Sorare. Base pour les tests intégration L4.

## 2026-09-20 — Contraintes L4 vérifiées

Les neuf garde-fous PLAN.md sont tous implémentés :
1. Somme offres ≤ solde disponible
2. Solde relu < 30 sec avant envoi
3. Ne jamais offrir > prix demandé
4. Cohérence ETH (wei) vs EUR (centimes), détecte 10^18 facteur
5. Taux change < 15 min, sinon refuse conversion
6. Palier ≤ 80% (appliqué en code ET base CHECK)
7. Offres par vendeur limitées à 5 (plafond injectable)
8. Arrêt d'urgence (.arret-urgence à racine bloque tout)
9. Mode réel : env var AND CLI flag AND retape montant (trois verrous)

Mode simulation par défaut, retour sim à chaque redémarrage.
Pas un seul paramètre dans config ne déverrouille mode réel seul.

## 2026-09-20 — Lot L5 : Préparation d'offre réelle et signature

**Mutations Sorare créées : `prepareOffer` et `createDirectOffer`**
`sorare/mutations.py` expose deux mutations GraphQL + wrappers :
- `PREPARE_OFFER_MUTATION` : valide l'offre, retourne les autorisations demandées
- `CREATE_DIRECT_OFFER_MUTATION` : envoie l'offre signée
- `preparer_offre_sorare()` et `creer_offre_directe_sorare()` : wrappers

**Module paiement : structure pour L5 et L6**
- `paiement/types.py` : `AuthorizationType`, `AuthorizationRequest`, `PreparedOffer`
- `paiement/preparation.py` : appel `prepareOffer`, construit input depuis proposition
- `paiement/signature.py` : placeholder L5 (approvals vide), structure pour L6

**AssetIds fictifs pour la chaîne de test.**
L'annonce ne porte pas d'assetId (juste joueur_slug, vendeur_slug, prix, date).
Choix L5 : utiliser `"test-asset-id-L5"` pour `receiveAssetIds` dans prepareOffer.
L6 remplacera par la vraie requête `annonces_marche()` qui fournira les assetIds réels.
Avec ces IDs fictifs, prepareOffer retournera une erreur de validation, mais c'est OK
pour tester le flux (les autorisations demandées, sinon vides).

**Intégration dans barrière.**
`envoyer_offre_proposal()` accepte un `client` optionnel. En mode réel :
1. Appelle `preparation.preparer_offre(client, proposition)`
2. Vérifie qu'aucune erreur de validation ne s'est produite
3. Appelle `signature.envoyer_offre_signee(client, prepared)`
4. Récupère `sorare_id` de la réponse et met à jour la ligne du journal
5. Les exceptions réseau sont loggées ; la ligne reste en base pour réconciliation

**L5 n'envoie pas réellement l'offre.**
`envoyer_offre_signee()` appelle `createDirectOffer` mais avec un assetId fictif,
ce qui génère une erreur Sorare. La mutation échoue, mais le code L5 est prêt pour
L6 où elle réussira avec un assetId réel. L'erreur est loggée et ne bloque pas.

**Pas d'autorisation demandée.**
L1 montrait que `prepareOffer` ne demandait pas d'autorisation (paramètres invalides).
L5 anticipe pas de signature, donc `approvals=[]` dans `createDirectOffer`.
L6 confirmera (vraie carte réelle, assetId valide) si une signature est demandée,
et L5 servira de squelette pour la vraie implémentation.

## 2026-09-21 — Lot L6 : premier envoi réel (code prêt, envoi laissé à l'utilisateur)

**`Annonce` porte maintenant un `asset_id`.**
`marche/types.py` ajoutait jusqu'ici une annonce sans identifiant de carte
concrète — suffisant pour L3/L4 (décision pure, mockée). L6 a besoin du vrai
`assetId` (`AnyCardInterface.assetId`) pour `prepareOffer`/`createDirectOffer`.
Champ ajouté avec défaut `""` (ne casse pas les annonces mockées existantes) ;
`paiement/preparation.py` lève `ValueError` s'il est vide au moment de
préparer une offre réelle, au lieu de retomber sur l'`assetId` fictif de L5
(`"test-asset-id-L5"`), qui ne peut plus jamais atteindre le réseau par erreur.

**`annonces_marche()` implémentée avec `TokenRoot.liveSingleSaleOffers`.**
Placeholder L4 (`NotImplementedError`) remplacé par une vraie requête GraphQL,
portée du SDL local comme les autres requêtes du projet (`offres_envoyees`,
`renouvellement`) — **non vérifiée contre l'API réelle** avant le premier
`premiere_offre_reelle` (voir MESURES.md). Nouvelle requête
`historique_prix_joueur()` (`TokenRoot.tokenPrices`) pour la référence de
prix réelle d'un joueur — même statut.

**Ambiguïté `senderSide`/`receiverSide` non tranchée, comme pour
`offres_envoyees` (DECISIONS.md, lot L2) — traitée en code, pas en supposition
figée.** Pour un `SINGLE_SALE_OFFER`, on ne sait pas sans l'avoir vérifié
quel côté porte la carte à vendre et quel côté porte le prix. `marche/traduction.py`
(`annonce_depuis_noeud_marche`) lit les deux côtés et retient celui qui porte
une carte (et une seule — un lot est hors périmètre L6) comme la carte, l'autre
comme le prix, plutôt que de figer une hypothèse qui pourrait être fausse.

**Nouveau module `marche/traduction.py` : fonctions pures, testées sur cas
figés.** Traduit les nœuds bruts (`liveSingleSaleOffers`, `tokenPrices`) vers
les types du domaine (`Annonce`, `Vente`). Convention du projet respectée :
aucun réseau ni base dans ces fonctions ; les requêtes brutes restent dans
`sorare/requetes.py`.

**`cli/premiere_offre_reelle.py` : script dédié L6, pas une extension du
scanner (L4).** Le scanner (`cli/scanner.py`) appelle `client.etat_compte()`
et `client.annonces_marche()`, des méthodes qui n'existent pas sur
`SorareClient` (qui n'expose que `.execute()`) — un défaut préexistant du
lot L4, jamais exécuté contre du réel (DECISIONS.md L4 le documentait déjà
comme testé « sur données mockées, pas marché »). Le réécrire pour de vraies
données (population liquide + références sur plusieurs joueurs) est un
travail de portée L7-L9 (boucle complète), pas de L6 (« une seule offre »,
PLAN.md). Le nouveau script est autonome : réconciliation obligatoire, état du
compte réel, recherche de la candidate la moins chère **avec référence réelle
valide** (>= 3 ventes/7j — sans ça, `journal.py` refuserait la ligne au niveau
base), palier 70 %, puis la barrière (`envoyer_offre_proposal`) — même chemin
unique que tout le reste du projet (`test_unique_path.py` le vérifie).

**Sans les trois verrous du mode réel, le script ne fait qu'un aperçu — zéro
écriture en base.** Contrairement au scanner (qui écrit toujours une ligne
`SIMULEE`), un aperçu qui écrirait quand même occuperait le couple
(joueur, vendeur) dans l'index unique et bloquerait le vrai essai suivant sur
la même carte. Le script sert donc aussi de sonde en lecture seule pour
vérifier la traduction du marché réel, sans aucun risque, avant de
déverrouiller le mode réel.

**« La carte la moins chère du marché » (PLAN.md) n'est, dans cette
implémentation, que la moins chère parmi un échantillon glissant — pas un
minimum global.** Constaté en session (2026-09-21, voir MESURES.md) : un
joueur avec ~18 annonces ouvertes réparties sur plusieurs jours n'en avait
qu'une seule dans notre fenêtre au moment du run (celle la plus récemment
mise à jour), pas la moins chère de ses annonces. Cause : `liveSingleSaleOffers`
est trié par fraîcheur de mise à jour, pas par prix, et `annonces_marche()`
n'en récupère que les 100 premières, marché entier confondu — une annonce
plus ancienne (même moins chère) peut rester hors de cette fenêtre
indéfiniment tant qu'elle n'est pas retouchée. **Décision : accepté tel
quel pour L6**, dont le but est de prouver que le chemin d'envoi réel
fonctionne, pas d'optimiser la sélection — élargir la fenêtre (pagination)
ou changer d'approche (interroger `liveSingleSaleOffers(playerSlug:)` par
joueur, ex. sur la population liquide de L3) est un sujet de portée L7+
(boucle complète), pas de L6. À garder en tête : le montant final envoyé en
mode réel dépend de cet échantillonnage, donc « la moins chère à cet instant
dans cette fenêtre », pas « la moins chère du marché entier » au sens
strict — ce que le script affiche reste correct, mais le nom de la fonction
(`trouver_meilleure_candidate`) et le message utilisateur ne doivent pas
laisser croire à une recherche exhaustive.

**L'envoi réel lui-même n'a pas été déclenché dans cette session.** Le code
est prêt et testé (le chemin réseau reste non exécuté contre l'API, comme
toutes les requêtes neuves du projet avant leur premier run réel) ; envoyer
une offre engage un vrai paiement, c'est un geste que l'utilisateur pose
lui-même :
```
python -m acheteur.cli.premiere_offre_reelle                    # aperçu, zéro risque
ACHETEUR_MODE_REEL=1 python -m acheteur.cli.premiere_offre_reelle --mode-reel
```

## 2026-09-21 — Lot L7 : la machine à états, la veille défensive, le cycle réel (code prêt, aucun envoi/annulation réel déclenché)

**La machine à états (`negociation/etats.py`) est un module à part, pur.**
Quatre fonctions, une par ligne de la table PLAN.md § « Ce qui déclenche
quoi » et § « On n'annule jamais pour reposter plus haut » :
`reagir_a_refus`, `reagir_a_expiration`, `reagir_a_contre_offre`,
`reagir_a_veille`. Chacune ne fait que décider (`Decision(action, raison,
palier_suivant)`) — jamais exécuter. C'est `cli/cycle_negociation.py` qui va
chercher les données réelles et exécute, via la barrière pour un envoi
(`garde_fous`, seul chemin, inchangé) ou via le nouveau
`negociation/annulation.py` pour une annulation.

**Contre-offre au-dessus du plafond : abandon, décision prise ici, pas dans
PLAN.md.** PLAN.md dit « sous notre plafond, on accepte » sans dire quoi
faire au-dessus. Le plafond retenu est celui de la règle 6 des garde-fous
(80% du prix demandé, `Palier.TROISIEME`) — cohérent avec le reste du
projet plutôt qu'un nouveau seuil inventé pour l'occasion.

**Acceptation de contre-offre volontairement non câblée côté Sorare.**
`reagir_a_contre_offre` existe et est testée, mais `acceptOffer` exige une
préparation et une signature (`prepareAcceptOffer`) jamais exercées contre
l'API réelle — aucune contre-offre n'a encore été observée sur le compte
(voir MESURES.md). Écrire ce code de signature sans jamais l'avoir vérifié
contre un cas réel serait exactement le genre de raccourci que CLAUDE.md
demande d'éviter sur ce qui dépense de l'argent. `cli/cycle_negociation.py`
ne fait que signaler la présence d'un champ `counteredOffer` (log), sans
agir — à étendre au premier cas réel observé.

**`cancelOffer` ajouté (`sorare/mutations.py`), NON VÉRIFIÉ contre l'API
réelle** (jamais appelé en conditions réelles à ce jour — voir MESURES.md).
Son input n'exige que `TokenOffer.blockchainId`, distinct de l'`id` déjà
utilisé partout ailleurs dans le projet ; `negociation/annulation.py` va le
rechercher au moment d'annuler plutôt que de le stocker en base — plus
simple, et toujours frais.

**Réconciliation étendue : une ligne appariée reflète maintenant l'état réel
observé côté Sorare, pas seulement au moment de l'import.** Jusqu'ici,
`reconcilier()` ne mettait à jour que les offres *manuelles* importées ; une
ligne du journal envoyée par le bot et appariée à une offre Sorare restait
figée à `ENVOYEE` pour toujours, même si Sorare la montrait refusée ou
acceptée depuis longtemps — la machine à états n'aurait jamais rien eu de
réel sur quoi réagir. Correction : `reconcilier()` met à jour `etat` (et
`motif_refus` le cas échéant) de chaque ligne appariée dont l'état observé a
changé. Ne touche jamais `reference_prix_valeur` ni les autres champs figés
à l'envoi (CLAUDE.md).

**Schéma : `offres_journal.offre_precedente_id` (auto-référence, nullable),
migré à la main sur la base réelle (`ALTER TABLE ... ADD COLUMN`, 55 lignes
existantes préservées, pas de framework de migration dans ce projet).**
Relie une ligne d'escalade/rejeu à la ligne close qu'elle remplace — sert à
(a) reconstituer l'historique d'une négociation et (b) compter les
ré-essais sur expiration sans dépendre d'une colonne de comptage qui
pourrait diverger du réel (« un seul ré-essai », PLAN.md) : voir
`journal.reessai_expiration_deja_fait`, qui ne regarde que le prédécesseur
immédiat — un ré-essai est propre à *cette* expiration, pas à la durée de
vie entière d'une négociation qui aurait par ailleurs escaladé sur refus
entre-temps.

**Bug réel trouvé en faisant tourner `cli/cycle_negociation.py` en aperçu
contre le compte réel** (même méthode qu'aux lots L5/L6) : la veille
défensive comparait le prix affiché à notre offre ouverte sans vérifier la
devise — une annonce dont le prix s'affiche en centimes d'euro comparée à
une offre faite en wei déclenchait un faux « prix descendu sous notre
offre » (ex. `400` centimes < `1300000000000000` wei, comparaison qui ne
veut rien dire). Corrigé : `reagir_a_veille` exige maintenant la devise des
deux côtés et n'annule que si elles concordent (CLAUDE.md § « Cohérence
d'unité »). Régression testée (`test_negociation_etats_l7.py`).

**Veille défensive : les lignes `import_automatique` (offres manuelles ou
groupées découvertes par la réconciliation) sont ignorées.**
`_rafraichir_annonce` ne sait interroger qu'un `joueur_slug` unique ;
`reconciliation.importer_ligne_manuelle` stocke plusieurs joueurs séparés
par des virgules (ou `"inconnu"`) pour une offre groupée — chercher cette
chaîne comme un slug ne trouve jamais rien et aurait déclenché une fausse
« annonce disparue » sur une offre légitime que le bot n'a de toute façon
pas décidée (constaté en session contre le compte réel). Ces lignes restent
à la revue humaine, hors périmètre de la veille automatique.

**Cycle réel : aucune escalade ni annulation exécutée dans cette session.**
`python -m acheteur.cli.cycle_negociation` (aperçu) a tourné à plusieurs
reprises contre le compte réel sans erreur — réconciliation, veille, et
recherche de lignes à réagir toutes fonctionnelles de bout en bout. Aucune
ligne décidée par le bot n'était en attente de réaction ce jour-là (les
lignes ouvertes/closes rencontrées étaient toutes `import_automatique`) ; le
chemin d'escalade réelle (palier suivant → barrière → envoi) reste donc,
comme pour L6, du code prêt et testé mais pas encore exercé contre un vrai
refus/expiration en conditions réelles. Pour agir réellement :
```
python -m acheteur.cli.cycle_negociation                    # aperçu, zéro risque
ACHETEUR_MODE_REEL=1 python -m acheteur.cli.cycle_negociation --mode-reel
```

## 2026-09-21 — `cli/scan_marche.py` : passe marché lisible, aucune écriture

Besoin exprimé après coup : la sortie de `cycle_negociation.py` ne réagit
qu'aux lignes déjà dans le journal — elle ne dit rien de ce que le bot
proposerait sur un balayage frais du marché. C'est exactement ce que
`cli/scanner.py` (L4) devait faire, mais DECISIONS.md notait déjà (lot L6)
qu'il appelle des méthodes inexistantes sur `SorareClient` et n'a jamais
tourné contre du réel — le réécrire était noté « portée L7-L9 ».

**Nouveau script, pas une réparation de `scanner.py`.** Reprend la même
chaîne de décision (référence réelle par saison → seuil de bonne affaire
→ groupage par vendeur → palier de départ) mais **n'écrit jamais de ligne
`OffreJournal`** : une ligne `SIMULEE` occuperait l'index unique
(joueur, vendeur) et bloquerait un futur essai réel sur la même carte
(même raison que L6, voir plus haut) — encore plus vrai ici puisque ce
script est fait pour tourner à répétition, juste pour lire un rapport.
Les propositions restent des objets `PropositionSimple`/`PropositionGroupe`
en mémoire, formatées directement en texte (`formatter_rapport`).

**Refactor mineur** : `_rarity_brute`/`_season_eligibility_brute`
(dupliquées à l'origine dans `cli/premiere_offre_reelle.py`) déplacées vers
`marche/traduction.py` (`rarity_brute_depuis_annonce`,
`season_eligibility_brute_depuis_annonce`) pour être partagées entre L6 et
ce nouveau script sans copier-coller.

**Usage** :
```
python -m acheteur.cli.scan_marche                                    # 100 annonces, seuil 90%
python -m acheteur.cli.scan_marche --premieres 200 --seuil 85 --sortie rapport.txt
```
Testé contre le compte réel (`--premieres 60`) : pipeline complet exercé de
bout en bout (annonces sans référence exploitable, propositions simples et
groupées, solde restant qui devient négatif quand le cumul dépasse le
solde disponible — affichage volontaire, pas un bug, ça montre où le
budget s'épuise). Même limite d'échantillonnage que L6 (fenêtre glissante,
pas un minimum global) : documentée dans le docstring du script.

## 2026-09-21 — Deux points signalés par l'utilisateur après le premier rapport réel

**« Je n'ai pas 11 euros sur mon compte » — le rapport confondait solde brut
et budget réellement disponible.** Le premier `formatter_rapport` cumulait
les montants dans l'ordre de rencontre et n'affichait qu'un solde restant
en fin de ligne, qui pouvait devenir négatif sans que ce soit mis en
évidence. Vérification contre le compte réel : solde EUR disponible 56,57 €,
mais 44,65 € déjà engagés sur des offres réelles ouvertes (dont une offre
groupée à 6 joueurs jamais décidée par le bot) → budget net réel 11,92 €,
pas 56,57 €. **Corrigé** : `scan_marche.py` calcule maintenant
`repartir_selon_budget()` — sépare explicitement les propositions « dans le
budget » de celles « hors budget », dans l'ordre des meilleures affaires
d'abord (prix demandé / référence, pas le pourcentage offert : ce dernier
vaut toujours le même palier par construction, donc ne distingue rien entre
propositions). Le rapport affiche maintenant le budget net en tête, avant
toute proposition. Régression testée (`test_scan_marche_l7.py`).

**« Si dépense en ETH, la maille la plus fine est le 0.0001 ETH, soit
environ 20-25 centimes ».** Deux conséquences, corrigées ensemble :
1. Les montants calculés pour une offre en ETH (`decision/proposition.py`,
   `decision/groupage.py`) n'étaient jamais arrondis à cette maille — un
   montant arbitraire en wei n'a aucune chance d'être négociable sur le
   carnet Sorare. Ajout de `marche.devises.arrondir_wei_a_la_maille`
   (arrondi vers le bas, jamais vers le haut — PLAN.md), appliqué
   systématiquement dans `proposer_simple`/`proposer_groupe`/
   `montants_offre_groupe`.
2. La règle 4 des garde-fous (`verifier_coherence_unites`) rejetait à tort
   tout montant ETH sous 10^15 wei (0,001 ETH) comme « suspectement petit,
   probablement des centimes non convertis » — un seuil arbitraire, jamais
   vérifié contre la vraie granularité du marché. Or 0,0001-0,0009 ETH
   (jusqu'à 9×10^14 wei) sont des prix réels et valides sur ce marché.
   **Remplacé par une règle exacte** : le montant doit être un multiple de
   la maille (`MAILLE_ETH_WEI = 10**14`), ce qui couvre à la fois la
   détection de bug d'unité (un montant en centimes n'est jamais un
   multiple de la maille) et la granularité réelle du carnet — sans faux
   positif sur un montant petit mais légitime. Régression testée
   (`test_garde_fous.py`, `test_decision_l3.py`).

Ces deux corrections touchent `decision/`, `garde_fous/` et `marche/` —
revues avec le niveau d'attention demandé par CLAUDE.md pour ces modules,
mais **non vérifiées contre un envoi ETH réel** (aucune offre ETH envoyée
par le bot à ce jour) : la maille de 0,0001 ETH vient de l'utilisateur, pas
d'une sonde contre l'API — à confirmer au premier envoi réel en ETH
(MESURES.md).

## 2026-09-21 — Correction du point précédent : le solde Sorare déduit déjà les offres ouvertes

**L'utilisateur a corrigé le correctif ci-dessus** : « le 59€ que j'ai
décompte déjà les offres que j'ai en cours ». Vérifié contre le compte réel
— `currentUser.myAccounts[].accountable.on PrivateFiatWalletAccount` renvoie
`totalBalance: 10122` et `availableBalance: 5657` (centimes) ; l'écart,
4465, colle **exactement** à la somme des lignes réelles ouvertes en EUR du
journal. Même constat côté ETH (`totalBalance`/`availableBalance` du compte
racine, écart de 3×10^15 wei = exactement la somme des lignes ETH ouvertes).
**`availableBalance(s)` est donc déjà net des offres réelles ouvertes** —
la correction précédente (« budget net = solde - offres ouvertes »),
introduite en réponse à « je n'ai pas 11 euros », soustrayait ces offres
**une seconde fois**, sous-estimant le budget réel (11,92 € affiché au lieu
de 56,57 €).

**Corrigé partout où cette double déduction existait** :
- `garde_fous/regles.py::verifier_solde_suffisant` (règle 1) — docstring
  clarifié : `soldes_ouverts` ne doit contenir que les montants décidés
  **dans le cycle en cours**, pas encore reflétés dans `solde_disponible`
  (le cas visé par PLAN.md : « dix offres à 3€ sur 12€ de solde peuvent
  toutes aboutir » — plusieurs décisions du même cycle, pas l'historique).
- `cli/premiere_offre_reelle.py` et `cli/cycle_negociation.py` — la fonction
  `_offres_ouvertes_reelles` (qui sommait tout l'historique réel ouvert)
  est remplacée par `_offres_ouvertes_par_vendeur_reelles`, qui ne compte
  que par vendeur (règle 7, anti-démarchage — un compteur différent, non
  affecté par ce bug, qui reste légitimement basé sur l'historique réel).
  `offres_ouvertes_par_devise` part de `{}` dans `ContexteBarriere`.
- `cli/cycle_negociation.py::_executer_reactions` peut escalader plusieurs
  lignes dans un même cycle — ajout d'un cumul par devise qui démarre à
  zéro (pas de l'historique) et ne grandit qu'avec les escalades **envoyées
  pendant ce cycle**, pour rattraper le cas PLAN.md sans redoubler la
  déduction déjà faite par Sorare.
- `cli/scan_marche.py::repartir_selon_budget` — ne prend plus
  `offres_ouvertes_par_devise` en paramètre ; le budget est `soldes_par_devise`
  tel quel. La fonction garde un paramètre du même nom côté
  `formatter_rapport`, mais purement informatif (affiché, jamais soustrait).

**Leçon retenue** : la mesure de départ (« je n'ai pas 11 euros ») était un
signal correct (le rapport montrait un chiffre trop bas), mais la première
hypothèse sur la cause était fausse — corriger vite sans vérifier le sens
de la déduction contre les vraies données du compte a produit une régression
dans l'autre sens. Vérifié cette fois avec les deux nombres bruts
(`totalBalance`/`availableBalance`) avant de toucher au code. Régression
testée (`test_scan_marche_l7.py::TestRepartirSelonBudget`,
`test_premiere_offre_reelle_l6.py::TestOffresOuvertesParVendeurReelles`).

## 2026-09-21 — Premier envoi réel déclenché par l'utilisateur : `createDirectOffer` échoue (bug trouvé et corrigé, aucun argent débité)

L'utilisateur a lancé `ACHETEUR_MODE_REEL=1 python -m acheteur.cli.premiere_offre_reelle --mode-reel`
lui-même (comme convenu). La barrière, `prepareOffer` et la ligne écrite en
base (avant réseau, couche 1 d'idempotence) ont fonctionné ; `createDirectOffer`
a échoué avec une vraie erreur GraphQL :

```
Variable $input of type createDirectOfferInput! was provided invalid value
for settlementCurrencies (Field is not defined on createDirectOfferInput),
dealId (Expected value to not be null)
```

**Cause** : `paiement/signature.py::envoyer_offre_signee` réutilisait tel
quel `prepared.input_data` — construit pour `prepareOfferInput`
(`preparation.py`) — comme input de `createDirectOffer`. Ce sont deux types
GraphQL différents (confirmé contre le schéma local,
`schema/sorare_schema.graphql:35410` et `:37894`) :
`prepareOfferInput` a `settlementCurrencies` mais pas `dealId` ;
`createDirectOfferInput` a `dealId: String!` (obligatoire, absent de la
réponse de `prepareOffer` — à générer côté client, le schéma suggère
`crypto.getRandomValues(...)` en JS) mais pas `settlementCurrencies`.
Hypothèse de L5 (« on anticipe qu'aucune signature ne sera nécessaire »)
jamais mise en doute sur la forme de l'input lui-même — un angle mort qui
n'apparaît qu'au premier vrai appel de `createDirectOffer`, jamais testé
jusqu'ici (`signature.py` n'avait aucun test).

**Corrigé** : nouvelle fonction `_construire_input_create_direct_offer`
qui ne reprend que les champs communs aux deux types (`clientMutationId`,
`receiveAmount`, `receiveAssetIds`, `receiverSlug`, `sendAmount`,
`sendAssetIds`) et ajoute `dealId` (généré, `secrets.token_hex`) et
`approvals`. Testé (`test_signature_l7.py`) — toujours pas vérifié contre un
`createDirectOffer` réel réussi (aucun essai relancé dans cette session,
voir MESURES.md).

**Conséquence locale nettoyée** : l'échec réseau a laissé une ligne
`ENVOYEE` en base sans `sorare_id` (couche 1 d'idempotence : la ligne
s'écrit avant l'appel réseau, comme prévu). Cette ligne occupait le couple
(lilian-brassier, effzeh99) dans l'index unique, bloquant tout nouvel essai
sur la même carte. Marquée `ANNULEE` à la main via `negociation.annulation.annuler_ligne`
(mode_simulation=True — aucun `sorare_id`, donc rien à annuler côté réseau,
juste une correction de l'état local). Aucun montant n'a été débité : Sorare
a rejeté la mutation avant toute confirmation d'offre.

## 2026-09-21 — Deuxième essai réel : `createDirectOffer` répond, mais un deuxième bug masquait les erreurs

Après la correction ci-dessus, l'utilisateur a relancé `--mode-reel`
lui-même sur une autre carte (Mattéo Xantippe / effzeh99). `createDirectOffer`
a bien été appelé cette fois (plus d'erreur de validation d'input), mais le
script a planté :

```
'NoneType' object has no attribute 'get'
```

**Cause** : `garde_fous/barriere.py`, juste après l'appel réel, faisait
`payload["tokenOffer"].get("id")` en ne testant que `"tokenOffer" in
payload` — or GraphQL renvoie la clé `tokenOffer` présente mais **nulle**
quand la mutation a des erreurs (ce qui était le cas ici). L'appel `.get()`
sur `None` plantait *avant* que le code n'atteigne la ligne suivante censée
journaliser `payload["errors"]` — masquant le vrai message d'erreur de
Sorare derrière une exception Python générique, capturée par le `try/except`
englobant qui ne loggue que `str(exc)`.

**Corrigé** : `token_offer = payload.get("tokenOffer")` puis test de
vérité avant d'appeler `.get("id")` dessus ; le log des erreurs
(`payload.get("errors")`) n'est plus conditionné à avoir passé ce bloc.
Régression testée (`test_garde_fous.py::TestBarriereSimulation::test_mode_reel_createdirectoffer_avec_erreurs_ne_plante_pas`,
faux client renvoyant exactement cette forme de réponse).

Ligne locale orpheline (mattheo-xantippe/effzeh99, `ENVOYEE` sans
`sorare_id`) nettoyée de la même façon que la précédente.

## 2026-09-21 — L'inconnue n°1 de PLAN.md est levée : le rail EUR exige une signature StarkEx

Grâce au fix ci-dessus, le vrai message d'erreur de Sorare est enfin apparu :
« Missing approval for 0503020cf7d0bcdb3f9fca63eb8d5d0a ». Sonde en lecture
seule (`prepareOffer` seul, jamais `createDirectOffer` — voir MESURES.md
pour le détail) : l'autorisation demandée est un
`MangopayWalletTransferAuthorizationRequest`, qui exige une signature
StarkEx (`AuthorizationApprovalInput.mangopayWalletTransferApproval` →
`StarkwareSignatureInput`) — pas une signature Ethereum/EIP-712 standard.

**C'est exactement le cas que PLAN.md § « L'inconnue n°1 » avait anticipé et
laissé ouvert** (« autorisation portefeuille fiat ou StarkEx → Node
obligatoire, la bibliothèque n'existe qu'en JavaScript. C'est le rail euro
qui devient cher — on démarrerait alors en ETH seul »). L1 (sonde du
19-20/09) n'avait pas pu trancher cette question car elle utilisait des
paramètres invalides et n'avait obtenu aucune autorisation en retour — cette
session-ci est la première à obtenir une vraie demande d'autorisation, avec
des paramètres réels.

**Conséquence directe** : `paiement/signature.py` (approvals vide en dur)
ne peut structurellement pas aboutir sur une offre payée en EUR — ni la
correction du premier bug (input `createDirectOffer`) ni celle du deuxième
(crash sur `tokenOffer: null`) ne changent cela ; elles étaient nécessaires
mais pas suffisantes. Ce n'est pas un bug de plus à corriger dans ce
module : c'est la limite architecturale que L1 devait clarifier avant que
la logique aval ne soit écrite (elle l'a été entre-temps, en anticipant que
« ça ne serait probablement pas nécessaire »).

**Ce projet n'implémente pas de signature StarkEx à ce stade** — ni le
Node.js requis par la bibliothèque (JS uniquement, confirmé par les notes
de l'utilisateur citées dans PLAN.md), ni la gestion de clé privée
correspondante, ce qui engagerait un niveau de risque et de portée que
CLAUDE.md demande de ne jamais improviser sur ce genre de module. Décision
laissée à l'utilisateur : implémenter la signature StarkEx (Node, portée
significative), limiter les envois réels au rail ETH en attendant de vérifier
son propre type d'autorisation (peut-être signable en Python, PLAN.md ne
l'exclut pas), ou une autre voie. Non tranché à la clôture de cette session.

## 2026-09-21 — Rail ETH : signature `EthereumBankTransferAuthorizationRequest` implémentée et vérifiée (clé privée non encore câblée)

Suite au choix de l'utilisateur (« on fait les deux dans l'ordre » : d'abord
la forme du message, puis la clé privée), sonde en lecture seule sur 4
annonces réelles payées en ETH (voir MESURES.md) : elles demandent toutes
une `EthereumBankTransferAuthorizationRequest`, **pas** StarkEx — la ligne
PLAN.md « autorisation Ethereum/Base : Python probablement suffisant ».

**Bug trouvé en cours de route, corrigé** : `paiement/types.py::AuthorizationType`
avait TOUTES ses valeurs fausses — il manquait « Authorization » au milieu
de chaque nom de type (`EthereumBankTransferRequest` au lieu du vrai
`EthereumBankTransferAuthorizationRequest`, vérifié contre le SDL local
pour les 9 valeurs). Conséquence : toute autorisation réellement demandée
par Sorare tombait dans `except ValueError: AuthorizationType.NONE` — les
sondes L1 n'avaient rien demandé du tout (paramètres invalides), donc
n'auraient jamais pu révéler ce bug ; c'est le premier `prepareOffer` de
cette session avec des paramètres réels qui l'a fait apparaître (log :
« Autorisations demandées : ['NONE'] », alors qu'une vraie autorisation
Mangopay avait bien été demandée).

**Forme exacte du message trouvée** : dans l'exemple officiel du dépôt
GitHub `sorare/api` (`examples/baseBankTransfer.js`) — pas dans les notes
personnelles de l'utilisateur, qui n'en avait pas pour Ethereum (seulement
pour Solana, comme prévu par PLAN.md). Cet exemple encode 9 paramètres
(`senderAddress, receiverAddress, amount, feeAmount, deadline, salt,
proxyAddress, data vide, contractAddress`) via l'ABI Solidity standard,
les hache en keccak256, puis signe ce hash avec le préfixe standard
« Ethereum Signed Message » (pas de l'EIP-712 typé — une signature de
message brut, plus simple).

**Reproduit en Python et vérifié octet pour octet** contre le vecteur de
test publié dans cet exemple (clé privée et signature attendue publiques,
pas un secret) : `paiement/eth_signature.py::signer_autorisation_ethereum_bank_transfer`
produit exactement la même signature que l'implémentation JavaScript
officielle. Nouvelle dépendance `eth-account` (bibliothèque standard de la
Ethereum Foundation, pas une lib maison).

**Ce qui manque encore avant de pouvoir réellement acheter en ETH** :
1. La question posée en fin de session précédente reste ouverte : **d'où
   vient la clé privée**, et comment (jamais stockée en clair — CLAUDE.md §
   Secrets). `eth_signature.py` ne fait que signer étant donné une clé
   fournie par l'appelant ; personne ne l'appelle encore avec une vraie clé.
2. `paiement/signature.py::envoyer_offre_signee` ne route pas encore vers
   `eth_signature.py` selon le type d'autorisation demandée — le câblage
   dans le chemin réel reste à faire, volontairement, tant que (1) n'est
   pas tranché.
3. ~~`PREPARE_OFFER_MUTATION` non vérifié contre l'API réelle~~ — **vérifié
   le 2026-09-21** (voir MESURES.md) : une sonde en lecture seule sur une
   candidate ETH réelle confirme que tous les champs
   (`contractAddress, senderAddress, receiverAddress, amount, feeAmount,
   deadline, salt, proxyAddress`) sont bien retournés, non vides, au bon
   format. Seuls les points (1) et (2) restent ouverts.

## 2026-09-21 — Clé privée Ethereum : gestionnaire d'identifiants Windows (même mécanisme que le JWT), et incident de fuite

**Décision (point 1 ci-dessus, tranché)** : la clé privée Ethereum suit
exactement le même mécanisme que le jeton Sorare (`acheteur.auth.jeton`) —
`keyring` / gestionnaire d'identifiants Windows, jamais un fichier, jamais
journalisée. Nouveau module `paiement/cle_ethereum.py` (`enregistrer_cle_privee`,
`lire_cle_privee`, `effacer_cle_privee`, `obtenir_cle_privee_valide`), même
forme que `auth/jeton.py`. `enregistrer_cle_privee` valide la clé en
dérivant son adresse publique (`eth_account.Account.from_key`) avant
écriture — une clé mal formée n'est jamais stockée. Script interactif
`cli/enregistrer_cle_ethereum.py` (saisie masquée, `getpass`) : n'affiche
jamais la clé, seulement l'adresse dérivée, pour que l'utilisateur confirme
que c'est le bon compte.

**Incident : la clé a été écrite en clair dans le fichier source**
(`paiement/cle_ethereum.py`, constante `_NOM_UTILISATEUR`) au lieu de
transiter par le script d'enregistrement — vraisemblablement collée
directement dans le fichier plutôt que saisie via `enregistrer_cle_ethereum.py`.
Détecté immédiatement (le diff du fichier modifié a été signalé), corrigé
(constante restaurée). Fichier resté non tracké par git (`??`, jamais
ajouté ni commité) — pas de fuite dans l'historique du dépôt. **Mais la clé
a transité en clair dans la conversation avec l'assistant**, un canal hors
du coffre prévu par CLAUDE.md § Secrets — l'utilisateur a été informé que
la seule mitigation fiable est de considérer cette clé comme compromise et
d'en changer ; il contacte le support Sorare pour savoir si un changement
de clé est possible. **Décision de l'utilisateur en attendant sa réponse :
continuer à travailler avec la clé actuelle.**

**Câblage réel (point 2 ci-dessus, fait)** : `paiement/signature.py::envoyer_offre_signee`
route maintenant chaque `AuthorizationRequest` selon son type :
`EthereumBankTransferAuthorizationRequest` → `eth_signature.signer_autorisation_ethereum_bank_transfer`,
clé obtenue via `cle_ethereum.obtenir_cle_privee_valide()` (lève
`ClePriveeAbsenteError` si rien n'est enregistré — n'a jamais tenté d'envoyer
sans signer). **Tout autre type d'autorisation (StarkEx, Mangopay/EUR) lève
`SignatureNonSupporteeError`** plutôt que d'envoyer des `approvals` vides
qui échoueraient de toute façon côté Sorare — explicite plutôt que silencieux.
Testé (`test_signature_eth_l7.py`) : cas sans autorisation, cas ETH signé
(vecteur public, signature vérifiée), cas clé absente, cas type non géré.
**Chemin encore non exercé contre un `createDirectOffer` réel réussi** —
aucun envoi ETH réel déclenché à ce jour (voir MESURES.md).

## 2026-09-21 — Premier test réel du garde-fou de signature : refus propre sur une candidate EUR, bug de sélection trouvé

L'utilisateur a relancé `--mode-reel` lui-même sur `premiere_offre_reelle.py`.
`trouver_meilleure_candidate` a choisi une carte payée en EUR (Na Sang-Ho,
0,40 €) — Sorare a demandé une `MangopayWalletTransferAuthorizationRequest`,
et `signature.envoyer_offre_signee` (voir entrée précédente) a levé
`SignatureNonSupporteeError` **au lieu d'envoyer des `approvals` vides** :
exactement le comportement voulu, aucun crash, message clair dans les logs,
aucune écriture chez Sorare au-delà de `prepareOffer`. Ligne locale
orpheline (`ENVOYEE` sans `sorare_id`) nettoyée comme les fois précédentes.

**Bug de sélection trouvé en creusant pourquoi une carte EUR a été choisie
alors qu'on veut tester le rail ETH** : `trouver_meilleure_candidate` triait
`annonces` par `prix_demande.valeur` brut, sans tenir compte de la devise —
or un prix EUR se compte en centaines de centimes, un prix ETH en 10^14+
wei. Sur cette échelle mélangée, une annonce EUR est presque *toujours*
« moins chère » qu'une annonce ETH, quel que soit leur prix réel respectif.
Conséquence concrète : tant qu'aucune carte EUR n'est explicitement
écartée, ce script ne retient quasiment jamais de candidate ETH — le seul
rail actuellement signable ne pouvait donc jamais être exercé par ce script.

**Corrigé** : nouveau paramètre `devise: Devise | None` sur
`trouver_meilleure_candidate` (filtre les annonces avant le tri si fourni)
et nouveau flag CLI `--devise {EUR,ETH}` sur `premiere_offre_reelle.py`.
Sans le flag, comportement inchangé (pas de régression sur L6). Régression
testée (`test_premiere_offre_reelle_l6.py::TestTrouverMeilleureCandidate::test_filtre_devise_ignore_les_annonces_d_une_autre_devise`).

## 2026-09-21 — Rail EUR : la signature StarkEx N'EST PAS Node-only, revirement de la décision précédente

**Demande explicite de l'utilisateur** : essayer de valider une transaction
en EUR — ce qui suppose d'implémenter la signature StarkEx, exactement ce
que l'entrée précédente (« Ce projet n'implémente pas de signature StarkEx
à ce stade ») excluait. Avant d'écrire du code sur un module qui déplace de
l'argent réel (CLAUDE.md), vérification : la signature StarkEx est-elle
vraiment « Node.js obligatoire », ou est-ce une hypothèse jamais vérifiée
(reprise des notes de l'utilisateur, citées dans PLAN.md, jamais du code
inspecté) ?

**Inspection du paquet npm public `@sorare/crypto`** (licence Apache 2.0,
StarkWare Industries — code lisible, téléchargé et lu directement, pas une
inspection de code privé) : `signAuthorizationRequest` route vers
`signFiatTransfer` pour `MangopayWalletTransferAuthorizationRequest`, qui
fait :
```
message = f"{mangopayWalletId}:{operationHash}:{currency}:{amount}:{nonce}"
h = sha256(message).hexdigest()
hash_msg = pedersen_hash(int(h[:32], 16), int(h[32:], 16))
signature = stark_sign(hash_msg, cle_privee)   # ECDSA sur la courbe STARK
```
**Ce n'est pas un algorithme propriétaire Sorare** : le hash Pedersen et la
signature ECDSA-STARK sont la cryptographie StarkWare publique et
documentée (même bibliothèque `micro-starknet` que citée dans
`authorizations.js`), utilisée par tout l'écosystème StarkNet/StarkEx —
Sorare n'en est qu'un consommateur. **L'évaluation précédente était trop
pessimiste** : elle datait d'avant toute inspection directe.

**Choix d'implémentation initial : `crypto-cpp-py` (bindings C++), abandonné
en cours de session — voir entrée suivante.** Paquet maintenu par Software
Mansion (auteurs de `starknet.py`), essayé en premier plutôt qu'une
réimplémentation ECDSA maison : une bibliothèque de référence largement
utilisée semblait préférable à du code écrit pour l'occasion sur un module
qui déplace de l'argent réel. Sa DLL s'est révélée dépendre d'un runtime
MinGW absent par défaut sur Windows et son chargement était instable selon
l'environnement — remplacé par un portage Python pur (voir plus bas),
resté préférable pour la même raison qui l'avait fait choisir au départ :
éviter l'imprévisible sur un module qui déplace de l'argent réel.

**Validation, avant tout câblage réel** :
1. Le hash Pedersen (`cpp_hash`) reproduit exactement deux vecteurs de
   test **officiels** StarkWare (`starkware-libs/starkex-resources`,
   `signature_test_data.json`, section `hash_test`).
2. La signature est auto-cohérente (signer puis vérifier avec la même
   bibliothèque réussit) et **produit exactement le même résultat**
   qu'une exécution indépendante de l'implémentation Python de référence
   de StarkWare (`starkware-libs/cairo-lang`,
   `src/starkware/crypto/signature/signature.py`, récupérée et exécutée
   dans cette session pour comparaison croisée).
3. Point notable pour quiconque retombe dessus : le vecteur `transfer_order`
   du même fichier `signature_test_data.json` (signature déjà publiée) ne
   se re-vérifie **avec aucune des deux implémentations**, y compris
   l'implémentation de référence StarkWare elle-même — vraisemblablement
   un fixture obsolète (nonce non déterministe à l'époque de sa
   génération), pas un défaut du code de ce projet. Documenté dans
   `paiement/starkex_signature.py` pour ne pas être reperdu.

**Nouveau module `paiement/starkex_signature.py`** (miroir de
`eth_signature.py`) : `hash_mangopay_wallet_transfer`,
`signer_autorisation_mangopay_wallet_transfer`,
`exporter_cle_publique_starkex`. Nouvelle dépendance `crypto-cpp-py`.

**Clé StarkEx : même mécanisme que la clé Ethereum, coffre séparé.**
Nouveau module `paiement/cle_starkex.py` (miroir de `cle_ethereum.py`) —
`keyring`, service `acheteur-starkex-cle-privee` distinct de
`acheteur-eth-cle-privee`. **C'est la clé du compte Starkware**, distincte
de la clé du compte Ethereum (l'utilisateur a mentionné avoir les deux dès
le début, sans qu'on sache jusqu'ici laquelle servait à quoi — c'est
maintenant clair : ETH → clé Ethereum, EUR → clé Starkware). Script
interactif `cli/enregistrer_cle_starkex.py`, saisie masquée, n'affiche que
la clé publique dérivée pour confirmation.

**Câblage dans `paiement/signature.py`** : `_signer_une_autorisation` route
maintenant aussi `MangopayWalletTransferAuthorizationRequest` vers
`starkex_signature`, clé obtenue via `cle_starkex.obtenir_cle_privee_valide()`.
Chaque rail récupère sa propre clé, à la demande (pas besoin d'avoir les
deux clés enregistrées si un seul rail est utilisé). `PREPARE_OFFER_MUTATION`
(`sorare/mutations.py`) étend son fragment en ligne pour inclure les champs
de `MangopayWalletTransferAuthorizationRequest` (`amount`, `currency`,
`mangopayWalletId`, `nonce`, `operationHash`), repris de `authorizations.js`.
Testé (`test_starkex_signature_l7.py`, `test_signature_starkex_l7.py`) :
hash contre les vecteurs officiels, câblage complet mocké (clé présente/absente).

**Ce qui reste avant un vrai achat en EUR** :
1. L'utilisateur doit enregistrer sa clé StarkEx via
   `python -m acheteur.cli.enregistrer_cle_starkex` — rien n'est encore
   dans le coffre à la clôture de cette session.
2. Les nouveaux champs de `MangopayWalletTransferAuthorizationRequest`
   dans `PREPARE_OFFER_MUTATION` ne sont **pas encore vérifiés contre
   l'API réelle** (seuls ceux d'`EthereumBankTransferAuthorizationRequest`
   l'ont été) — à confirmer au prochain `prepareOffer` réel sur une
   candidate EUR.
3. Aucun envoi réel en EUR n'a été tenté après ce câblage (le seul essai
   réel EUR de la session précédait cette correction et avait été refusé
   par le garde-fou, voir entrée précédente) — le chemin complet reste
   non exercé contre un `createDirectOffer` réel réussi.

## 2026-09-21 — `crypto-cpp-py` remplacé par un portage Python pur (échec de chargement DLL non reproductible)

En essayant d'enregistrer la clé StarkEx, l'utilisateur a rencontré
`pywintypes.error: (126, 'LoadLibraryEx', 'Le module spécifié est
introuvable.')` — la DLL de `crypto-cpp-py` (compilée avec MinGW) dépend de
`libgcc_s_seh-1.dll`/`libstdc++-6.dll`, absentes de Windows par défaut mais
présentes via l'installation Git for Windows de l'utilisateur (dans le PATH
de Bash/Git Bash, pas de son PowerShell). Copier ces deux DLL à côté de
`libcrypto_c_exports.dll` (dans `site-packages`) a réglé le problème dans
plusieurs terminaux testés, **mais pas de façon fiable partout** : le même
échec est réapparu ensuite dans le terminal PowerShell intégré de VS Code,
y compris après avoir découvert et corrigé un problème séparé (voir
ci-dessous) et re-copié les DLL au bon endroit.

**Cause profonde jamais élucidée avec certitude, mais peu importe : une
dépendance native dont le chargement dépend de l'environnement d'exécution
(terminal, PATH, peut-être antivirus) est exactement ce que CLAUDE.md
demande d'éviter sur un module qui déplace de l'argent réel.** Plutôt que
de continuer à chasser un problème d'environnement Windows, remplacé
`crypto-cpp-py` par un portage Python pur de l'implémentation de référence
StarkWare elle-même (`starkware-libs/cairo-lang`, Apache 2.0) — zéro DLL,
zéro compilation, seulement des dépendances `pip` standard (`ecdsa` pour la
génération RFC6979 du nonce ; l'inverse modulaire utilise `pow(x, -1, p)`,
natif Python, à la place de `sympy.igcdex` de l'original, pour éviter une
dépendance lourde inutile ici).

**Nouveau sous-module `paiement/_starkware_crypto/`** (`math_utils.py`,
`signature.py`, `pedersen_params.json`, `LICENSE`) : version allégée de
l'original, ne gardant que ce qui sert (`pedersen_hash`, `sign`, `verify`,
`private_to_stark_key`) — `get_y_coordinate`/`is_valid_stark_key`/
`get_random_private_key` retirés (jamais utiles ici, ce projet ne dérive ni
ne valide jamais une clé, il en reçoit une complète de l'appelant).
`starkex_signature.py` route maintenant vers ce sous-module au lieu de
`crypto_cpp_py.cpp_bindings`.

**Revalidé avant le remplacement, pas après** : comparaison croisée bit à
bit entre `crypto-cpp-py` et le portage Python pur sur le même hash Pedersen
et la même signature (mêmes `r`, `s`) — confirme que le portage ne change
rien au résultat, avant même de retirer l'ancienne dépendance. Les deux
vecteurs de test officiels StarkWare (hash Pedersen) et le test
d'auto-cohérence (sign + verify) re-passent avec le nouveau module
(`test_starkex_signature_l7.py`, mis à jour pour ne plus dépendre de
`crypto_cpp_py`). Dépendance `crypto-cpp-py` retirée de `pyproject.toml`
(remplacée par `ecdsa`, qui était déjà une dépendance transitive) ;
désinstallée des deux environnements Python touchés pendant le diagnostic
(voir ci-dessous) ; DLL copiées manuellement supprimées.

**Découverte annexe pendant ce diagnostic : deux environnements Python
distincts sur la machine de l'utilisateur.** L'installation globale
(`AppData\Local\Programs\Python\Python312`) — celle que mes propres
commandes (Bash/PowerShell) utilisaient par défaut tout du long de cette
session — et le `.venv` du projet (`c:\...\acheteur\.venv`), celui que VS
Code active automatiquement et donc celui que l'utilisateur utilise
réellement au quotidien. Toutes mes installations de dépendances
(`eth-account`, puis `crypto-cpp-py`) n'avaient touché que l'environnement
global, jamais le `.venv` — d'où le symptôme observé
(`ModuleNotFoundError: No module named 'crypto_cpp_py'` dans le terminal
VS Code). Corrigé : `.venv/Scripts/python.exe -m pip install -e .`
resynchronise le venv avec `pyproject.toml`. **Point de vigilance retenu
pour la suite de ce projet** : toujours vérifier quel interpréteur Python
exécute réellement une commande avant de diagnostiquer une erreur
d'environnement — deux installations peuvent coexister silencieusement sur
la même machine.

## 2026-09-21 — Rail EUR confirmé fonctionnel de bout en bout (premier achat réel réussi, voir MESURES.md)

L'utilisateur a déclenché `--mode-reel` sur une candidate EUR : deux offres
réelles créées avec succès (`sorare_id` réel obtenu, voir MESURES.md pour
le détail). **La signature StarkEx en pur Python
(`paiement/_starkware_crypto`) est donc prouvée correcte contre l'API
réelle Sorare**, pas seulement contre les vecteurs de test publics
StarkWare — la dernière incertitude sur ce rail (acceptation côté serveur)
est levée. Les rails ETH (lot L6/L7) et EUR sont désormais tous les deux
opérationnels de bout en bout ; PLAN.md § « L'inconnue n°1 » est
définitivement clos.

## 2026-09-21 — Bug réel trouvé après coup : `premiere_offre_reelle.py` n'appliquait jamais le filtre « bonne affaire »

L'utilisateur a remarqué, après le premier achat EUR réussi ci-dessus, que
la carte achetée (Gragera, 0,40 € demandé, offre à 0,28 €) se négocie en
réalité systématiquement autour de 0,22 € (visible sur l'historique des
ventes de l'appli Sorare) — un prix de vente qui ne remonte jamais, pas une
« bonne affaire » du tout : 0,40 € représente 182 % de sa propre référence
médiane (0,22 €), très au-dessus du seuil de 90 % que ce projet applique
partout ailleurs (`decision/selecteur.py::est_bonne_affaire`, PLAN.md).

**Cause** : `cli/premiere_offre_reelle.py::trouver_meilleure_candidate`
ne vérifiait que « la candidate a une référence de prix réelle valide
(>= 3 ventes/7j) », jamais « le prix demandé est intéressant par rapport à
cette référence ». `est_bonne_affaire` existe depuis le lot L3 et est bien
appliqué par `scan_marche.py` (lot L7) — il n'avait simplement jamais été
branché dans le script L6, qui cherchait juste « la moins chère du marché
avec une référence », sans jamais comparer prix et référence entre eux.
Conséquence concrète : le bot a réellement payé plus que la valeur de
marché d'une carte, deux fois (Gragera 0,28 €, et potentiellement Altena
selon sa propre référence — à vérifier).

**Corrigé** : `trouver_meilleure_candidate` prend maintenant un paramètre
`seuil_pourcent` (défaut 90, comme partout ailleurs) et appelle
`est_bonne_affaire(annonce, reference, seuil_pourcent)` avant de retenir une
candidate — une annonce dont le prix demandé dépasse ce seuil est
maintenant ignorée, comme dans `scan_marche.py`. Nouveau flag CLI `--seuil`
sur `premiere_offre_reelle.py` (même nom que sur `scan_marche.py`, cohérence
d'interface). Régression testée
(`test_premiere_offre_reelle_l6.py::TestTrouverMeilleureCandidate::test_ignore_une_candidate_dont_le_prix_est_au_dessus_de_sa_reference`,
reproduit exactement le cas Gragera : prix 0,40 €, référence médiane
0,22 €). Les fixtures de deux tests existants (`messi`, `mbappe`) ont dû
être ajustées : leurs prix de test, choisis avant ce correctif, ne
passaient pas non plus le nouveau filtre — signe que ce bug aurait pu être
détecté plus tôt si ces tests avaient reflété une vraie bonne affaire dès
le départ.

**Point non résolu à la clôture de cette session** : les deux achats EUR
réels de cette session (Gragera 0,28 €, Altena 1,00 €) sont restés en
l'état — ce ne sont pas des erreurs d'exécution (le bot a fait exactement
ce que son code (bogué) lui demandait), donc pas de rollback technique à
faire, mais l'utilisateur reste libre de revendre ces cartes s'il juge
l'achat mauvais commercialement.

## 2026-09-22 — Taxe de revente Sorare (5%) intégrée dans `est_bonne_affaire`

Sorare prélève 5% du montant de toute revente de carte (frais de
transaction). `reference_prix_joueur` calcule une référence à partir de
ventes conclues — donc au prix BRUT payé par l'acheteur à l'époque, pas ce
qu'un vendeur touche net une fois la carte revendue.

`est_bonne_affaire` comparait jusqu'ici le prix demandé directement à cette
référence brute. Ça surestimait la marge réelle de 5 points de pourcentage
sur toute transaction : au seuil par défaut (90%), un achat à 89% de la
référence brute semblait une bonne affaire, alors qu'en revendant au niveau
de la référence on ne toucherait que 95% de ce montant — soit un rendement
net de 0,95 / 0,89 ≈ 6,7% de marge réelle, pas les ~11% que le calcul brut
laissait croire.

Décision (choix explicite de l'utilisateur, recommandé) : `est_bonne_affaire`
compare maintenant le prix demandé à la référence NETTE de cette taxe
(`reference_nette_de_taxe`, `acheteur/decision/selecteur.py` — référence ×
95 // 100), pas à la référence brute. Le seuil `seuil_pourcent` (90% par
défaut) porte donc sur ce qu'on peut réellement espérer récupérer en
revendant, pas sur un chiffre de marché qui ignore les frais de la
plateforme.

Conséquence mécanique : le filtre est plus strict qu'avant (une référence
nette est toujours inférieure à la référence brute), donc certaines annonces
qui passaient de justesse ne passent plus. Deux fixtures de test ont dû être
resserrées pour rester des « bonnes affaires » sous ce nouveau calcul
(`test_premiere_offre_reelle_l6.py` : messi 170→150 centimes, mbappe
5,8×10¹⁵→5,4×10¹⁵ wei) — même schéma que la correction du 2026-09-21, un
signe de plus que les fixtures doivent rester proches des vrais seuils
plutôt que de les frôler arbitrairement.

`TAUX_TAXE_REVENTE_POURCENT = 5` est une constante de règle métier (le taux
Sorare), pas une mesure — elle n'a donc pas sa place dans MESURES.md.

## 2026-09-22 — Pré-filtre liquidité + second signal SOUS_VENTE_MINI + offre groupée réactive (`scan_marche.py`)

Suite à la revue des critères de `sealing-sorare-apps-script` (voir échange
avec l'utilisateur, 2026-09-22) : trois ajouts à `cli/scan_marche.py`, tous
en aval de la taxe de revente ci-dessus. Périmètre volontairement limité à
`scan_marche.py` (aperçu, lecture seule) pour valider les critères avant de
les brancher un jour sur un envoi automatique périodique.

**1. Pré-filtre de liquidité** (`marche/liquidite.py`, nouveau module).
Seuils choisis par l'utilisateur : `ventes_30_mini = 15`, `ventes_7_mini =
3` (inchangé — 3,5 n'est pas atteignable avec un compte entier, l'utilisateur
a préféré garder 3 plutôt qu'arrondir à 4), `semaines_mini = 4`. `15` vise
une vente tous les 2 jours en moyenne sur la fenêtre de 30 jours (30/2=15),
même logique de taux que celle qui a justifié `ventes_30Mini=10` dans les
`.gs`, simplement resserrée. Calculé sur le MÊME historique de ventes déjà
récupéré pour la référence de prix — aucun appel réseau de plus. Un joueur
illiquide est écarté avant même de savoir si son prix est intéressant :
sans acheteur en face, une « bonne affaire » ne se réalise jamais.

`ecoulementMaxJours`/`partLimited` (les deux autres critères des `.gs`, sur
la profondeur du carnet) ont été explicitement écartés (accord des deux
parties) : le concept est valide mais `partLimited=0.78` est une estimation
calibrée sur un échantillon `sealing`, à une date donnée — pas question de
la porter sans la re-mesurer sur le marché que `acheteur` regarde.

**2. Second signal de sélection : `est_sous_vente_minimum`**
(`decision/selecteur.py`). Indépendant de `est_bonne_affaire` (qui compare
à la MÉDIANE des ventes récentes) : celui-ci compare le prix demandé au
MINIMUM des ventes antérieures à la pose de l'annonce (point-in-time, même
saison/rareté par construction puisqu'on réutilise le même historique
filtré). Une candidate est retenue si `est_bonne_affaire` OU
`est_sous_vente_minimum` — deux façons indépendantes d'être une affaire.

Version volontairement simplifiée par rapport à `SOUS_VENTE_MINI` des
`.gs` : ceux-ci laissent en plus une enchère, ou l'annonce la moins chère
de la PASSE PRÉCÉDENTE, faire baisser ce minimum. `acheteur` ne lit pas les
enchères (hors périmètre, PLAN.md) et `scan_marche.py` ne conserve aucun
état d'une exécution à l'autre (lecture seule, rien n'est persisté) — donc
pas de « passe précédente » à comparer. Seules les ventes entre managers
comptent ici.

**3. Garde de joignabilité + offre groupée réactive.** Signalé par
l'utilisateur (retour d'expérience empirique, 2026-09-22) : le signal
`est_sous_vente_minimum` seul est peu fiable, mais très fort combiné à un
petit vendeur (≤ 20 annonces en cours, `STOCK_MAX_VENDEUR_DEFAUT`). Une
candidate qui ne doit sa sélection qu'à ce second signal (pas à
`est_bonne_affaire`) est donc rejetée si son vendeur est absent, non
mesurable, ou trop gros (`_necessite_verification_stock`,
`_filtrer_par_stock_vendeur`) — un appel réseau supplémentaire
(`requetes.stock_vendeur`), mais seulement pour les candidates qui en ont
besoin, jamais pour celles déjà retenues par `est_bonne_affaire`.

Pour chaque petit vendeur ainsi confirmé (plafonné à
`OFFRE_GROUPEE_VENDEURS_MAX_DEFAUT = 6`), toute sa vitrine est relue
(`requetes.vitrine_vendeur`, `cartes_max_par_vendeur = 20`) et ses AUTRES
cartes limited/rare sont réévaluées contre les mêmes critères
(`_completer_par_vitrines_vendeurs`). Idée de l'utilisateur : la couverture
du groupage par vendeur existant (`decision/groupage.py`) est bornée par
l'échantillon de marché tiré au hasard — si les autres cartes d'un vendeur
retenu ne sont pas tombées dans cet échantillon, elles restent invisibles
et une offre groupée avantageuse (décote à 65% dès 2 cartes, voir
`groupage.py`) est manquée. Cette relecture ciblée comble ce trou de
couverture sans étendre l'échantillon global. Aucune nouvelle logique de
groupage : les cartes supplémentaires partagent le `vendeur_slug` des
candidates existantes, `_construire_propositions` les regroupe déjà
automatiquement.

Coût ajouté, borné : 1 appel `stock_vendeur` par vendeur distinct des
candidates nécessitant la vérification, puis 1 appel de vitrine + 1 appel
d'historique de prix par carte supplémentaire retenue, pour au plus 6
petits vendeurs par exécution.

## 2026-09-22 — Historique de prix par lot (alias GraphQL), avant de retirer le plafond de 100 annonces

L'utilisateur voulait tester `scan_marche.py` sans se limiter à un
échantillon de 100 annonces. Obstacle identifié avant d'y toucher :
`historique_prix_joueur` faisait 1 appel réseau PAR annonce (pas de lot),
contrairement à `sealing-sorare-apps-script` qui groupe jusqu'à 200 joueurs
par appel via des alias GraphQL. Sur un échantillon élargi (voire le marché
entier, mesuré à ~13 000 annonces sur le pool `sealing`), ça aurait fait
des milliers d'appels en un seul run. Choix explicite de l'utilisateur :
résoudre le lot AVANT de toucher à la pagination du marché lui-même.

**Ajouté** : `sorare.requetes.historique_prix_joueurs_lot` +
`_requete_historique_prix_lot` — une requête à N alias (`a0`, `a1`, ...),
chacun avec ses PROPRES variables `playerSlug`/`rarity`/`seasonEligibility`
(contrairement aux `.gs`, qui bouclent sur les 4 combinaisons
marché×rareté pour tout le lot à chaque fois : ici, chaque alias porte
exactement la rareté/éligibilité déjà connue de son annonce — pas de combo
inutile interrogé). `TAILLE_LOT_HISTORIQUE_PRIX_DEFAUT = 200`, choisi par
analogie avec `CRITERES_BA.aliasVentes = 200` des `.gs` (mesuré là-bas à
121 de complexité/alias pour un jeu de champs plus large que le nôtre) —
mais ⚠️ **NON VÉRIFIÉ contre l'API réelle avec notre jeu de champs**
(`eurCents`/`wei`/`date` seulement). À confirmer au premier run réel et
consigner dans MESURES.md avant de monter ce chiffre.

`cli/scan_marche.py::_calculer_candidates` boucle maintenant par lot de
`taille_lot` annonces au lieu d'une boucle par annonce.

**Ce que ça ne résout PAS encore** : `annonces_marche()`
(`liveSingleSaleOffers`) reste plafonnée à ~50 nœuds réels quel que soit
`--premieres` (constaté 2026-09-21, voir MESURES.md) — aucune pagination
par curseur n'est implémentée. Retirer la limite de 100 annonces demande
donc un second chantier (paginer `liveSingleSaleOffers` via
`after`/`hasNextPage`, champ confirmé dans le SDL,
schema/sorare_schema.graphql:30431) — pas fait dans cette session, à la
demande explicite de l'utilisateur (batching d'abord, mesurer ensuite).

## 2026-09-22 — Persistance de la liste des joueurs liquides (préparation L9)

Suite à la question de l'utilisateur sur la tâche planifiée périodique
(lot L9, PLAN.md) : définition de la liste des joueurs liquides et de son
délai de rafraîchissement, avant tout code de boucle.

**Découpage retenu** (même principe que `sealing-sorare-apps-script`,
`majListeBonnesAffaires`/`lireCouplesSuivis_`) : un job lent
(`cli/maj_liste_liquidite.py`, nouveau) reconstruit périodiquement une
liste persistée des couples (joueur, rareté, éligibilité de saison)
liquides (table `joueurs_liquides`, `marche/liste_liquidite.py`) ; un futur
job rapide (L9, pas encore écrit) ne fera que la LIRE au lieu de recalculer
la liquidité de zéro à chaque passage.

**Délai de rafraîchissement : 24h**, choix explicite de l'utilisateur
(option recommandée) — aligné sur le `.gs` d'origine. La liquidité se
mesure sur une fenêtre de 30 jours à granularité hebdomadaire
(`marche/liquidite.py`) : elle ne bouge pas assez vite pour justifier un
recalcul plus fréquent, et ce choix garde le coût réseau de la
reconstruction (le scan du marché + les lots de prix) une fois par jour.

**Ce que la table NE stocke PAS** : aucune référence de prix. Seul le fait
qu'un couple est liquide (plus les compteurs `n30`/`n7`/`semaines_actives`,
gardés pour le diagnostic) est persisté — la référence de prix doit
toujours être recalculée fraîche au moment de la décision d'achat (PLAN.md :
« figer la référence de marché au moment de l'envoi », pas avant).

**Remplacement complet, pas incrémental** (`remplacer_liste_liquidite`) :
un couple qui n'est plus liquide doit disparaître de la liste au
rafraîchissement suivant, pas y traîner avec un vieil horodatage.

**Horodatage du dernier rafraîchissement dans une table à part**
(`meta_liste_liquidite`, ligne unique) plutôt que `MAX(joueurs_liquides.maj_le)` :
un rafraîchissement qui ne retiendrait aucun couple (liste vide, cas limite
mais possible si le marché est temporairement peu liquide) aurait sinon
fait perdre la trace du fait qu'il a bien eu lieu, faisant passer une liste
tout juste reconstruite pour périmée (`liste_perimee`).

**Bug SQLite découvert en écrivant les tests** : un `datetime` stocké via
`Mapped[datetime]` (comme partout ailleurs dans ce projet, ex.
`negociation/journal.py`) est relu SANS fuseau horaire par SQLite, même
écrit avec un `Horloge` en UTC. `derniere_maj()` rattache donc `UTC`
explicitement à la lecture — sans ce correctif, `liste_perimee` aurait levé
`TypeError` (comparaison naïf/aware) en production dès le premier appel
réel. Les autres colonnes `datetime` du projet (`OffreJournal.cree_le`/
`maj_le`) portent probablement le même défaut mais n'ont, à ce jour, jamais
été comparées après relecture — non corrigé ici (hors périmètre de cette
session), à surveiller si un jour elles le sont.

**Reste hors périmètre de cette session** : le job rapide qui LIT cette
liste (le cœur de L9), la déduplication d'`annonces_marche` reste bornée
par la limite de pagination déjà connue (~50 nœuds réels, voir MESURES.md
2026-09-21) — `cli/maj_liste_liquidite.py` en hérite tel quel pour
l'instant.

## 2026-09-22 — Dette technique résorbée : pagination du marché, taille de lot confirmée, correction stock_vendeur/vitrine_vendeur

Trois points de dette technique identifiés en clôturant la session
précédente, traités et mesurés contre l'API réelle avant tout autre
développement.

**1. Pagination de `liveSingleSaleOffers`** — `annonces_marche` restait
plafonnée à ~50 nœuds réels quel que soit `--premieres` (une seule page).
Ajout de `annonces_marche_paginees` (`sorare/requetes.py`) : avance par
curseur (`after`/`pageInfo.endCursor`) jusqu'à un maximum choisi, vérifié
en réel (0 chevauchement entre pages, `totalCount` mesuré à 543 496 — voir
MESURES.md). Branché dans `cli/maj_liste_liquidite.py`, qui en avait le
plus besoin (couverture de la liste liquide). Testé en réel à
`--premieres 500` : 8 couples liquides retenus contre 2 sur un échantillon
de 100 précédemment. `cli/scan_marche.py` et `cli/scan_liste_liquidite.py`
gardent volontairement `annonces_marche` en une seule page — le premier est
un outil d'aperçu/validation (`--premieres` déjà un réglage explicite), le
second cible un joueur précis (`playerSlug`) où une seule page suffit
largement.

**2. `TAILLE_LOT_HISTORIQUE_PRIX_DEFAUT = 200` confirmé contre l'API réelle**
— testé jusqu'à 360 alias (succès) et 380/400 (échec, `HTTP 413 Payload Too
Large`). Découverte importante : ce n'est pas un plafond de complexité
GraphQL comme supposé par analogie avec les `.gs`, mais une limite de
taille de payload HTTP — donc sensible à la longueur du texte de la
requête, pas au coût du champ interrogé. 200 reste le défaut, avec une
marge confortable (~45%) avant la limite mesurée.

**3. Bug réel trouvé et corrigé : `stock_vendeur`/`vitrine_vendeur`
plantaient sur un vendeur inconnu** au lieu de rendre `None`. L'hypothèse
initiale (un slug inconnu rend `user: null` silencieusement, par analogie
avec d'autres champs Sorare) était fausse : l'API lève une erreur GraphQL
(`NOT_FOUND`), que `sorare/client.py` traduit en `SorareError` — jamais
interceptée avant ce correctif, ce qui aurait fait planter tout un run de
`scan_marche.py`/`scan_liste_liquidite.py` sur un vendeur parti ou renommé
entre la lecture d'une annonce et la vérification de son stock. Les deux
fonctions capturent maintenant explicitement `SorareError` et rendent
`None` (« non mesurable »), cohérent avec la prudence déjà appliquée pour
un stock trop gros ou absent (`_filtrer_par_stock_vendeur`).

Les trois points sont mesurés et consignés dans MESURES.md (pas seulement
supposés). 268 tests passent après ces correctifs.
