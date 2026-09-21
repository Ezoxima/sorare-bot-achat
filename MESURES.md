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
