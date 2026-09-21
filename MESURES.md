# Mesures

Ce que ce fichier contient : uniquement ce qui a été **prouvé** en faisant
tourner une sonde contre l'API Sorare réelle, avec sa date et son effectif.
Une hypothèse de PLAN.md n'y entre pas tant qu'elle n'a pas été vérifiée ici
— voir PLAN.md § « Ce qui reste à mesurer, par ordre de gravité financière »
pour la liste de ce qui est encore supposé.

Format d'une entrée : date, sonde utilisée, ce qui a été observé, ce que ça
implique pour la conception.

---

## 2026-09-20 — Premier `connecter` réel

`python -m acheteur.cli.connecter --email ezoximafifa@gmail.com` a fonctionné
du premier coup : mot de passe + salt bcrypt + mutation `signIn` + rebond 2FA
(`otpSessionChallenge` → `otpAttempt`) tel que porté depuis Pickdeck. Jeton
obtenu (`user=ezox`, expire 2026-10-20T17:54:48+00:00) et confirmé écrit dans
le gestionnaire d'identifiants Windows. **Le flux de connexion porté depuis
Pickdeck est validé tel quel, aucune adaptation nécessaire.**

## 2026-09-20 — Premier `etat_compte` réel : requête corrigée

Premier essai en échec (attendu, pas un problème de fond) :
`AvailableBalances.eurCents` (et les 4 champs frères `gbpCents`, `usdCents`,
`wei`, `lamport`) ne sont **pas** des scalaires malgré leur nom — ce sont
chacun un objet `MonetaryAmount` complet (qui expose lui-même `eurCents`,
`wei`, etc. et `referenceCurrency`). Le SDL local le montrait déjà
(`sorare_schema.graphql:1529`), l'erreur venait de la requête écrite ici, pas
d'une hypothèse fausse de PLAN.md. Corrigé dans
`acheteur/sorare/requetes.py` avec une sous-sélection sur chaque champ.
Prochaine exécution attendue : succès, avec un instantané réel écrit dans
`sondes/resultats/`.

## 2026-09-20 — L1 : sonde de signature à l'achat, trois tirs

`python -m acheteur.cli.sonde_signature_achat` a exécuté sans erreur. Trois tirs
(EUR seul, WEI seul, BOTH) appelle la mutation `prepareOffer` avec des
paramètres partiellement invalides (identifiants d'actifs inexistants,
vendeur fictif), puis compare l'empreinte du compte avant/après.

**Ce qui a été observé :**
- ✓ Empreinte avant = empreinte après pour les trois tirs. **La sonde n'a créé,
  modifié, ni signé aucune offre.**
- → Aucune `AuthorizationRequest` n'a été demandée par la mutation
  `prepareOffer` dans les trois cas.

**Implications pour la conception :**
1. **L'hypothèse PLAN.md § L'inconnue n°1 reste non tranchée.** La sonde
   `prepareOffer` n'a pas encore montré quel type de signature est demandé,
   car elle n'en a demandé aucun. Deux explications possibles :
   - `prepareOffer` ne demande une signature que si les paramètres sont
     valides (carte réelle existante, solde suffisant, etc.).
   - Les signatures ne sont demandées que par `createDirectOffer`, pas
     `prepareOffer`. Dans ce cas `prepareOffer` est une pure validation
     client-side.
2. **Pas de blocage en Python pur pour le moment.** Aucune signature n'ayant
   été demandée, et aucun Node JavaScript n'ayant été nécessaire pour la
   sonde, la route Python pur reste ouverte.

**Prochaines étapes :**
- L6 (premier envoi réel) testera avec une vraie offre sur une carte réelle.
  C'est là que la vraie signature sera demandée, si elle est demandée du tout.

## 2026-09-21 — Premier `premiere_offre_reelle` (aperçu) : requête `offres_envoyees` corrigée

Premier run réel du lot L6 : la réconciliation obligatoire (étape 1, avant
toute recherche de candidate) a échoué avant même d'atteindre le code L6 —
erreur GraphQL sur `OFFRES_ENVOYEES_QUERY` (`sorare/requetes.py`, lot L2,
jamais exécutée contre l'API réelle jusqu'ici) :

> `Selections can't be made directly on unions (see selections on BlockchainUser)`

**Ce qui a été observé :** `TokenOffer.receiver` est de type `BlockchainUser`,
une **union** (`AnonymousUser | User`, `sorare_schema.graphql:2902`) — le SDL
local le montrait déjà, l'erreur venait de la requête (`receiver { slug }`
sans fragment), pas d'une hypothèse fausse. Corrigé en `receiver { ... on
User { slug } } }` dans `sorare/requetes.py` et, par le même défaut, dans
`sorare/mutations.py` (`CREATE_DIRECT_OFFER_MUTATION`, lot L5, elle aussi
jamais exécutée contre le réel). `AnonymousUser` n'a pas de `slug` : une
offre dont le vendeur est anonyme renverra `receiver: null` côté aplati —
pas encore observé, à surveiller au prochain run.

**Implication :** confirme que le format « portée du SDL local, jamais
vérifiée » de ce projet (DECISIONS.md) attrape bien de vraies erreurs de
requête au premier contact avec l'API réelle — exactement ce que ce
protocole est censé faire. Le run n'a eu aucun effet (l'erreur est survenue
avant toute écriture en base ou appel de mutation).

**Prochaine étape :** relancer `python -m acheteur.cli.premiere_offre_reelle`
(sans `--mode-reel`, aperçu seul) pour voir si la réconciliation passe et si
`annonces_marche()`/`historique_prix_joueur()` (elles aussi non vérifiées)
renvoient une forme exploitable.

## 2026-09-21 — Réconciliation non idempotente : suspension permanente

Deuxième run réel : `python -m acheteur.cli.reconcilier` a planté au
deuxième appel d'affilée (le premier avait importé 50 offres historiques,
la plupart closes) — `UNIQUE constraint failed: offres_journal.sorare_id`.

**Ce qui a été observé :** `apparier()` (pure, `negociation/reconciliation.py`)
ne compare les offres Sorare qu'aux lignes du journal **ouvertes**
(`lignes_ouvertes()`), par contrat documenté. Une offre déjà importée puis
close (refusée/acceptée/annulée) sort donc de son champ de vision et
retombe dans `a_importer` à *chaque* réconciliation suivante — pour
toujours. Deux conséquences, la deuxième plus grave que la première :
1. `reconcilier()` tentait de réinsérer la même ligne → violation d'unicité,
   plantage.
2. Même corrigé pour ne pas planter, `rapport.cycle_suspendu` (`bool(a_importer
   or ambigues)`) restait `True` en **permanence** dès qu'une seule offre
   manuelle a un jour existé sur le compte — ce qui, sur un compte réel
   utilisé depuis un moment, revient à bloquer le bot pour toujours. Ce
   n'était pas un cas couvert par les tests figés du lot L2 (aucun d'eux
   n'appelait `reconcilier()` deux fois de suite).

**Corrigé :** `reconcilier()` retire de `rapport.a_importer` toute offre dont
le `sorare_id` figure déjà dans le journal (n'importe quel état), avant
d'importer et avant d'évaluer `cycle_suspendu`. `apparier()` elle-même n'a
pas changé (son contrat pur reste correct pour l'appariement) ; le filtre
supplémentaire vit dans l'orchestration. Test de régression :
`test_offre_close_deja_importee_n_est_pas_reimportee` (`test_negociation_l2.py`)
appelle `reconcilier()` deux fois avec le même client factice et vérifie que
le deuxième appel ne plante pas, ne duplique rien, et ne reste pas suspendu.

**Vérifié en réel après correction :** `reconcilier()` relancé une troisième
fois sur le compte réel → « Appariées automatiquement : 11 », « Offres
importées : 0 », « OK — rien à examiner à la main. » Base stable à 51 lignes
(50 + 1 offre genuinement nouvelle apparue entre les deux runs).

## 2026-09-21 — L6 : premier aperçu complet réussi, `tokenPrices` plafonnée à 20

Après les deux corrections ci-dessus, `python -m acheteur.cli.premiere_offre_reelle`
(sans `--mode-reel`) a échoué une dernière fois sur `historique_prix_joueur()` :

> `first must be less than or equal to 20` (`tokens.tokenPrices`)

Non documenté dans le SDL local (le champ `first: Int` n'y porte aucune
borne). `NOMBRE_VENTES_EXAMINEES` ramené de 50 à 20 dans
`cli/premiere_offre_reelle.py`.

**Après correction, l'aperçu complet a tourné de bout en bout sans erreur :**
réconciliation → état du compte réel (16,23 € / 0,00480929 ETH) → 100
annonces du marché récupérées → première candidate avec référence réelle
valide trouvée : **Jonas Föhrenbach (Limited)**, vendeur `effzeh99`, prix
demandé 0,40 €, référence médiane 2,54 € (7 j, ≥ 3 ventes), palier 70 % →
offre proposée 0,28 €. Aucune écriture en base (mode réel non déverrouillé).

**Implication :** la chaîne réelle complète du lot L6 (marché → référence →
sélection → barrière, jusqu'au seuil du mode réel) fonctionne. Reste à
mesurer : le comportement de `prepareOffer`/`createDirectOffer` avec un
`assetId` réel et un `receiverSlug` réel — inconnue n°1 de PLAN.md, toujours
pas levée, puisque l'envoi réel n'a pas encore été déclenché.

## 2026-09-21 — `tokenPrices` mélangeait classic et in-season : référence fausse

Signalé par l'utilisateur en relisant le résultat ci-dessus : Jonas
Föhrenbach à 0,40 € avec une référence à 2,54 € ne correspondait à aucune
réalité de marché plausible pour ce joueur/rareté.

**Ce qui a été observé :** `tokenPrices` accepte un paramètre
`seasonEligibility: SeasonEligibility` (`CLASSIC` ou `IN_SEASON`,
`sorare_schema.graphql:21978`) que `historique_prix_joueur()` n'utilisait
pas. Une carte in-season (éligible aux compétitions en cours) et une carte
classic du même joueur et de la même rareté se vendent à des prix qui n'ont
aucun rapport — la médiane sans ce filtre mélangeait les deux populations,
produisant un nombre qui ne correspondait à aucune carte réelle en vente.

**Corrigé :** `Annonce` porte maintenant `in_season: bool | None`
(`AnyCardInterface.inSeasonEligible`, ajouté à `ANNONCES_MARCHE_QUERY`) ;
`annonce_depuis_noeud_marche` ignore une annonce sans cette information
plutôt que de deviner ; `historique_prix_joueur()` prend un paramètre
`season_eligibility` que `cli/premiere_offre_reelle.py` dérive de l'annonce
candidate avant d'aller chercher sa référence.

**Vérifié en réel après correction :** nouveau run de
`premiere_offre_reelle` (aperçu) → candidate **Yáser Asprilla (Limited,
classic)**, vendeur `transversale`, prix demandé 0,90 €, référence classic
0,64 € (médiane, 7j, ≥3 ventes), offre 0,63 € (palier 70%, plafonnée par
« jamais plus que le prix demandé »). Un nombre qui se tient enfin par
rapport au prix affiché — contrairement au run précédent.

**Implication plus large :** deux requêtes non vérifiées de suite (le
premier run avait déjà corrigé l'union `receiver` et la non-idempotence de
la réconciliation) ont chacune révélé un défaut réel invisible en lecture
de schéma seule. Aucune des deux n'était un cas couvert par les tests
figés existants — la vigilance humaine en relisant un résultat concret
(comme ici) reste une couche de vérification à part entière, pas
redondante avec les tests.

## 2026-09-21 — `liveSingleSaleOffers` est triée par fraîcheur, pas par prix

Signalé par l'utilisateur : pour le joueur retenu (Yáser Asprilla), la
moins chère de ses annonces vue sur le site était à 0,80 €, alors que le
script avait proposé 0,90 €.

**Ce qui a été observé :** requête directe de `liveSingleSaleOffers(playerSlug:
"yaser-esneider-asprilla-martinez")` → 18 annonces ouvertes pour ce joueur,
dont une à 0,80 € (créée le jour même). L'annonce à 0,90 € retenue par le
script au run précédent (vendeur `transversale`) n'apparaît plus du tout
dans cette liste — soit vendue, soit annulée entre-temps. Le marché change
en continu ; ce n'est pas en soi le problème.

**Le vrai problème :** `annonces_marche()` interroge `liveSingleSaleOffers`
**sans** filtre `playerSlug`, sur l'ensemble du marché, avec `first: 100`.
L'API trie ce flux par fraîcheur de mise à jour (« sorted by updated time »,
documenté dans le SDL — schema/sorare_schema.graphql:30428), pas par prix.
Un joueur avec des annonces ouvertes depuis plusieurs jours n'a, à un instant
donné, qu'une poignée d'entre elles (voire une seule) dans les 100 plus
récentes du marché entier — les autres, même moins chères, restent invisibles
tant qu'elles ne sont pas retouchées. Un deuxième run quelques minutes plus
tard a d'ailleurs renvoyé un joueur complètement différent (Mark McKenzie,
0,40 €), confirmant que la fenêtre glisse à chaque appel.

**Décision (voir DECISIONS.md) : accepté tel quel pour L6.** Le but du lot
est de prouver que l'envoi réel fonctionne, pas d'optimiser la sélection ;
élargir la fenêtre ou interroger par joueur (population liquide de L3) est
un sujet L7+. Le docstring et les messages utilisateur de
`cli/premiere_offre_reelle.py` ont été corrigés pour ne plus prétendre à
« la carte la moins chère du marché » au sens strict.

## 2026-09-21 — Lot L7 : premier `reconcilier()` avec mise à jour des lignes appariées + premier `cycle_negociation` réel (aperçu)

`python -m acheteur.cli.cycle_negociation` (aperçu, sans `--mode-reel`) a
tourné plusieurs fois contre le compte réel. Résultats :

- **La réconciliation étendue (mise à jour des lignes appariées) marche** :
  9 lignes appariées, aucune erreur, aucune régression sur les lignes déjà
  closes.
- **Un cycle a détecté une dépense non décidée par le bot** (offre groupée à
  6 joueurs, `dambietz`, 41,20 €) et a correctement suspendu le cycle — la
  même protection qu'en L2, maintenant exercée en amont d'une vraie escalade
  possible, pas seulement d'un import.
- **Bug réel trouvé et corrigé** : la veille défensive (`reagir_a_veille`)
  comparait le prix demandé actuel à notre offre ouverte sans vérifier la
  devise. Sur des lignes dont l'offre avait été faite en wei, le prix actuel
  de l'annonce (lu en centimes d'euro par `annonce_depuis_noeud_marche`, qui
  préfère EUR à wei — voir `marche/traduction.py`) était comparé tel quel :
  `400` (centimes) < `1 300 000 000 000 000` (wei) déclenchait un faux
  « prix descendu sous notre offre ». Corrigé en exigeant la même devise des
  deux côtés avant toute comparaison (`negociation/etats.py`,
  `reagir_a_veille`) — sans quoi une veille réelle aurait annulé des offres
  parfaitement valides. Régression testée.
- **Les lignes `import_automatique` (offres manuelles/groupées) faussaient
  la veille** : `_rafraichir_annonce` cherche une annonce par un seul
  `joueur_slug`, mais une ligne importée pour une offre groupée stocke
  plusieurs joueurs séparés par des virgules (ou `"inconnu"` si aucun) — la
  recherche ne trouve jamais rien, ce qui aurait fait annuler (en mode réel)
  une offre légitime que le bot n'a pourtant pas décidée. Ces lignes sont
  maintenant explicitement exclues de la veille automatique.
- **Aucune ligne décidée par le bot n'était en attente de réaction** (refus/
  expiration) au moment du run : le chemin d'escalade réelle (palier suivant
  → barrière → envoi) reste non exercé contre un vrai cas — comme pour L6,
  code prêt et testé, mais pas encore prouvé par un envoi réel.
- **Aucune contre-offre observée à ce jour** : `reagir_a_contre_offre` reste
  non exercée contre un cas réel ; `acceptOffer`/`prepareAcceptOffer` ne sont
  toujours pas câblés (décision explicite, voir DECISIONS.md).
- **`cancelOffer` reste NON VÉRIFIÉ contre l'API réelle** : aucune annulation
  réelle n'a eu lieu dans cette session (aperçu seul).

## 2026-09-21 — Écart solde brut / budget net — **hypothèse initiale corrigée, voir plus bas**

`etat_compte` réel : `availableBalances.eurCents.eurCents = 5657` (56,57 €).
Somme des lignes du journal réellement ouvertes (`mode_simulation=False`,
état dans `SIMULEE`/`ENVOYEE`) en EUR : 4465 centimes (44,65 €), dont une
offre groupée à 6 joueurs jamais décidée par le bot (41,20 €, `import_automatique=True`).

Hypothèse initiale (erronée, corrigée le même jour) : « budget net = 56,57 €
- 44,65 € = 11,92 € ». **Faux** — voir l'entrée suivante :
`availableBalance` a déjà déduit ces 44,65 € (`totalBalance` du compte
`PrivateFiatWalletAccount` = 10122 centimes, `availableBalance` = 5657 ;
écart 4465 = exactement la somme ci-dessus). Le budget réel est donc bien
56,57 €, pas 11,92 €. Le correctif (`scan_marche.py::repartir_selon_budget`
et la propagation dans `garde_fous`/`cli`) est documenté dans DECISIONS.md,
entrée « Correction du point précédent ».

Les montants ETH déjà ouverts sur le compte réel sont tous des multiples de
10^14 wei (500000000000000, 1300000000000000, 1200000000000000) — cohérent
avec la maille de 0,0001 ETH signalée par l'utilisateur, bien que ce soit
une observation indirecte (offres déjà existantes, pas un envoi fait par ce
correctif) et non une vérification contre un envoi réel du bot.

## 2026-09-21 — `availableBalance` confirmé net des offres réelles ouvertes (EUR et ETH)

Signalé par l'utilisateur : « le 59€ que j'ai décompte déjà les offres que
j'ai en cours ». Vérifié par les deux champs bruts du compte réel :
- EUR (`PrivateFiatWalletAccount`) : `totalBalance = 10122`,
  `availableBalance = 5657` (centimes) — écart 4465, exactement la somme
  des lignes EUR réellement ouvertes du journal à cet instant.
- ETH (racine `currentUser`) : `totalBalance = "7809290000000000"`,
  `availableBalance = "4809290000000000"` (wei) — écart 3×10^15, exactement
  la somme des lignes ETH réellement ouvertes du journal à cet instant.

Concordance exacte dans les deux devises : `availableBalance(s)` déduit déjà
les offres réelles ouvertes ; le code ne doit jamais les déduire une seconde
fois (voir DECISIONS.md pour la liste des correctifs).

## 2026-09-21 — Premier `createDirectOffer` réel : échec, cause identifiée et corrigée

Premier appel réel de `createDirectOffer` (déclenché par l'utilisateur,
`--mode-reel`), sur Lilian Brassier / effzeh99, 0,28 € (palier 70% de
0,40 €). `prepareOffer` a réussi (aucune autorisation demandée, confirmant
l'hypothèse L1/L5). `createDirectOffer` a échoué :

```
Field is not defined on createDirectOfferInput (settlementCurrencies)
dealId : Expected value to not be null
```

Confirme, contre l'API réelle, que `createDirectOfferInput` et
`prepareOfferInput` sont deux types distincts avec des champs différents
(déjà visible dans le SDL local, jamais vérifié en pratique avant ce run).
Corrigé (voir DECISIONS.md).

**Deuxième essai réel** (après correction, autre carte, Mattéo Xantippe /
effzeh99) : `createDirectOffer` a bien été appelé, avec cette fois un
message d'erreur exploitable une fois le deuxième bug corrigé (voir
DECISIONS.md) : `Missing approval for 0503020cf7d0bcdb3f9fca63eb8d5d0a`.

## 2026-09-21 — L'inconnue n°1 (PLAN.md) est levée : le rail EUR exige une signature StarkEx, pas de Python pur

Sonde en lecture seule (`prepareOffer` uniquement, jamais `createDirectOffer`
— aucun risque, empreinte du compte inchangée par construction de cette
mutation) sur la même candidate que l'essai réel ci-dessus :

```json
{
  "authorizations": [{
    "fingerprint": "0503020cf7d0bcdb3f9fca63eb8d5d0a",
    "status": "CREATED",
    "request": { "__typename": "MangopayWalletTransferAuthorizationRequest" }
  }]
}
```

`MangopayWalletTransferAuthorizationRequest` (schema/sorare_schema.graphql:13424)
exige, pour être approuvée (`AuthorizationApprovalInput.mangopayWalletTransferApproval`,
:1537) : `nonce: Int!` et `signature: StarkwareSignatureInput!` (:13416-13419)
— une signature **StarkEx** (courbe STARK, pas secp256k1 standard), sur un
`operationHash` fourni par la requête d'autorisation elle-même.

**C'est exactement la ligne « autorisation portefeuille fiat ou StarkEx »**
de PLAN.md § « L'inconnue n°1 » : *« Node obligatoire : la bibliothèque
n'existe qu'en JavaScript. C'est le rail euro qui devient cher — on
démarrerait alors en ETH seul »*. Sonde d'échantillon (100 annonces) : aucune
annonce ETH trouvée dans la fenêtre pour tester si le rail ETH tombe sur une
autre ligne du tableau (`autorisation Ethereum/Base`, potentiellement
signable en Python pur) — à refaire avec un échantillon plus large ou un
`liveSingleSaleOffers(playerSlug:)` ciblé sur une carte connue en ETH.

**Ce que ça change concrètement** : le chemin actuel (`paiement/signature.py`,
`approvals: []` en dur) ne peut *jamais* aboutir sur une offre en EUR — pas
un bug à corriger, une limite architecturale que L1 n'avait pas pu trancher
faute d'avoir testé avec des paramètres valides. Décision à prendre par
l'utilisateur (voir DECISIONS.md) : implémenter la signature StarkEx (Node,
plus cher), limiter les envois réels au rail ETH le temps de vérifier son
propre type d'autorisation, ou autre chose.

## 2026-09-21 — Rail ETH : autorisation `EthereumBankTransferAuthorizationRequest`, pas StarkEx

Suite au choix de l'utilisateur (tester le rail ETH avant de trancher),
sonde en lecture seule sur un échantillon élargi (`annonces_marche(premieres=300)`) :
**seuls 50 nœuds bruts sont réellement renvoyés quel que soit le nombre
demandé** (300 et 500 renvoient tous les deux 50 — plafond réel non
documenté dans le SDL local, à ajouter aux limites déjà connues comme celle
de `tokenPrices`). 4 annonces en ETH trouvées dans cette fenêtre (aucune la
fois précédente — confirme, une fois de plus, que l'échantillon change
d'un appel à l'autre, voir l'entrée L6 sur `liveSingleSaleOffers`).

`prepareOffer` sur les 4 candidates ETH demande systématiquement une
`EthereumBankTransferAuthorizationRequest` (schema/sorare_schema.graphql:9921),
**pas** une autorisation StarkEx — c'est la ligne PLAN.md § « L'inconnue
n°1 » : *« autorisation Ethereum/Base | Python probablement suffisant ; à
confirmer sur la forme exacte du message »*. Son approbation
(`EthereumBankTransferApprovalInput`, :9912) attend `deadline: String!`,
`salt: String!`, `signature: String!` — une signature de message standard
(vraisemblablement EIP-712, à confirmer), pas la primitive STARK du rail
fiat. Les champs de la requête elle-même (`contractAddress`, `senderAddress`,
`receiverAddress`, `amount`, `feeAmount`, `deadline`, `salt`, `proxyAddress`)
ressemblent à une méta-transaction relayée (type permit/GSN) plutôt qu'à une
transaction Ethereum classique.

**Ce que ça résout, et ce qui reste ouvert** : confirme que le rail ETH est
signable en Python pur (pas de Node/StarkEx nécessaire) — la partie
« Python probablement suffisant » de PLAN.md tient. **Reste non résolu** :
la forme exacte du message à signer (domaine EIP-712 précis : nom, version,
chainId, types) n'est documentée nulle part dans le SDL — il faudra soit la
retrouver dans les notes de l'utilisateur (PLAN.md y fait référence pour
Solana ; à vérifier si un équivalent existe pour Ethereum), soit
l'inspecter depuis le comportement de l'app Sorare elle-même. Et la question
de la clé privée (jamais stockée par ce projet, CLAUDE.md § Secrets) reste
entière : il faudra une décision explicite sur comment et quand la fournir,
avant d'écrire le moindre code de signature.

## 2026-09-21 — Champs de `EthereumBankTransferAuthorizationRequest` confirmés contre l'API réelle

Après avoir élargi `PREPARE_OFFER_MUTATION` (fragment en ligne sur
`EthereumBankTransferAuthorizationRequest`) et corrigé le bug
`AuthorizationType` (voir DECISIONS.md), sonde en lecture seule (aucune
écriture, aucun envoi) : `prepareOffer` sur une candidate ETH réelle du
marché retourne bien tous les champs attendus, non vides :

```
contractAddress, senderAddress, receiverAddress, amount, feeAmount,
deadline, salt, proxyAddress
```

(valeurs réelles observées, non sensibles — adresses de contrat/relais
publiques, montants et deadline propres à cette offre précise, jamais
réutilisables). Confirme que `paiement/eth_signature.py` (vérifié
séparément contre le vecteur de test public `sorare/api`, voir
DECISIONS.md) reçoit exactement les champs qu'il attend, avec les bons
noms et le bon format (adresses hex, montants en string décimale, `salt`
en hex 32 octets) — plus aucun champ de la recette de signature n'est
« NON VÉRIFIÉ ».

**Vérification croisée du dépôt public `sorare/api`** (`examples/`,
consulté à la demande de l'utilisateur) : rien de nouveau à ajouter. Le seul
exemple pertinent pour le rail ETH est `baseBankTransfer.js`, déjà utilisé
pour construire la recette. `authorizations.js` confirme au passage que les
rails StarkEx et Mangopay (EUR/fiat) passent par `signAuthorizationRequest`
de la lib privée `@sorare/crypto` (npm) — pas de primitive documentée
publiquement, donc pas de raccourci Python pour ce rail ; renforce la
décision de rester sur le rail ETH pour l'instant. Aucun exemple ne montre
d'où vient la clé privée utilisée pour signer (laissé à l'appelant dans
tous les cas) — la question posée à l'utilisateur reste entière.

## 2026-09-21 — Champs de `MangopayWalletTransferAuthorizationRequest` confirmés contre l'API réelle, signature StarkEx produite avec la vraie clé

Sonde en lecture seule (`prepareOffer` seul, aucune écriture, aucun envoi) :
sur 100 annonces récentes du marché, 25 sont payées en EUR. `prepareOffer`
sur l'une d'elles retourne bien tous les champs attendus pour
`MangopayWalletTransferAuthorizationRequest`, non vides :

```
amount (int), currency (str, "EUR"), mangopayWalletId (str),
nonce (int), operationHash (str hex, sans préfixe 0x)
```

Confirme que `paiement/starkex_signature.py` reçoit exactement les champs
qu'il attend, avec les bons types (pas besoin de conversion supplémentaire :
`str()` sur chacun avant la jonction `:` suffit).

**Signature produite de bout en bout avec la vraie clé StarkEx de
l'utilisateur** (enregistrée dans le coffre, jamais lue ni journalisée par
cette sonde — seule sa présence a été vérifiée) sur ces champs réels :
aucune erreur, `nonce`/`r`/`s` bien formés.

## 2026-09-21 — PREMIER ACHAT RÉEL EN EUR RÉUSSI : `createDirectOffer` accepté par Sorare avec la signature StarkEx

L'utilisateur a lancé `--mode-reel` lui-même (comme convenu) sur le rail
EUR. **Sorare a accepté la signature StarkEx produite par
`paiement/_starkware_crypto` + `paiement/starkex_signature.py`** — deux
offres réelles créées avec un vrai `sorare_id` (`SingleBuyOffer:...`),
état `envoyee` en base :
- `jose-gragera-amado` / `effzeh99` — 0,28 € (`id` journal 69)
- `jordi-altena` / `alain-zingovzia` — 1,00 € (`id` journal 68)

**Ce que ça clôt** : la dernière inconnue du rail EUR (« Sorare accepte-t-il
vraiment cette signature côté serveur ? ») est levée — dans les deux sens
(hash Pedersen + ECDSA-STARK), le portage Python pur
(`paiement/_starkware_crypto`, remplaçant `crypto-cpp-py` suite à son
échec de chargement DLL — voir DECISIONS.md) est **prouvé correct contre
un vrai paiement Sorare**, pas seulement contre des vecteurs de test
publics. Les deux rails de paiement (ETH et EUR) sont maintenant
fonctionnels de bout en bout.

## Prochaines mesures attendues, dans l'ordre

1. **Etat du compte (référence du 2026-09-20)** →
   `python -m acheteur.cli.etat_compte` a produit un instantané stable de
   base (EUR: 3556 centimes, wei: 8209290000000000, lamport: 0).
2. **L1 — RÉALISÉ** (voir ci-dessus).
3. **Premier renouvellement de jeton réel**, quand l'échéance approchera
   (jeton valide jusqu'au 2026-10-20) → vérifie que la mutation
   `createJwtToken` marche bien comme identifiée dans le schéma (voir
   DECISIONS.md, 2026-09-20). Tant que ce n'est pas arrivé, considérer le
   renouvellement automatique comme **non vérifié**, pas comme acquis.
4. **L6 — premier envoi réel.** Dépend de L5 (signature si nécessaire).
   Testera avec une vraie offre sur une carte bon marché du marché. C'est
   là que la vraie signature (ou l'absence de signature) sera déterminée.
