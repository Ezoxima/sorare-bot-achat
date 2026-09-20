# Bot d'achat Sorare — plan d'implémentation

## Contexte

Tu veux un automate qui repère les cartes vendues nettement sous leur prix de marché et négocie
leur achat à ta place, sur une population de joueurs liquides. Deux projets couvrent aujourd'hui des
moitiés du problème sans se toucher :

- **`sealing-sorare-apps-script`** détecte déjà les bonnes affaires et calcule le prix à proposer.
  Il est **intégralement en lecture seule** : zéro mutation, zéro signature. Il sait quoi faire, il
  ne sait rien envoyer.
- **Pickdeck** (`sorare_app_v2`) a le client GraphQL robuste, l'historique des ventes en base et les
  médianes en SQL — mais sa règle est de ne rien soumettre automatiquement à Sorare et d'exclure la
  spéculation de son périmètre (D21, D39).

Le bot est donc un **troisième dépôt**, neuf et autonome, seul des trois à écrire vers Sorare. Ce
cloisonnement est le point important : un bug du bot ne peut atteindre ni tes données de jeu, ni ta
feuille de calcul.

**Résultat attendu :** phase 1, un mail quotidien d'offres prêtes que tu valides une par une ;
phase 2, une fois le taux d'acceptation mesuré, le même moteur qui envoie seul.

---

## Décisions prises (2026-09-20)

| Sujet | Décision |
|---|---|
| Emplacement | dépôt séparé, nommé **`acheteur`** (pas de « Sorare » dans le nom : D38 le proscrit pour tout ce qui pourrait devenir public) |
| Langage | **Python 3.12**. Un bout de Node **seulement si** la sonde prouve qu'une signature l'exige |
| Automatisation | phase 1 : propose, tu valides · phase 2 : automatique, débloquée par la mesure |
| Périmètre | **achat seulement**. Revente = lot ultérieur |
| Population | joueurs liquides **recalculés en Python** par le bot |
| Relance | **sur refus explicite uniquement**, et seulement si le motif est « offre trop basse » |
| Budget | **aucun plafond arbitraire**. Le solde fait la limite ; une carte hors budget se saute |
| Exécution | ton poste, tâche planifiée Windows, **toutes les 15 minutes** |
| Notification | **mail**, comme tes alertes Apps Script actuelles |

---

## Ce que le schéma GraphQL nous donne, et qu'on ne savait pas

Quatre découvertes qui changent la conception :

**1. Sorare dit pourquoi le vendeur a refusé.** Six motifs possibles : *offre trop basse*, *je ne
vends pas*, *carte non désirée*, *uniquement en cash*, *ajoute du cash*, *la carte est dans une
composition*. C'est l'information la plus précieuse du schéma : elle transforme ton escalade en
arbre de décision. On ne remonte d'un palier que sur « trop basse » ; on abandonne définitivement
sur « je ne vends pas » ; on rebascule en euros au **même** palier sur « uniquement en cash » ; on
met en sommeil jusqu'à la fin de la gameweek sur « dans une composition ».

**2. Tes propres offres envoyées sont relisibles avec leur état.** Ton projet Apps Script note que
« a-t-il accepté mon offre ? » n'est observable nulle part. C'est faux côté API. Le bot n'aura pas
à deviner : il réconcilie.

**3. La contre-offre est native.** Si un vendeur te contre à un montant sous ton plafond, on peut
accepter directement au lieu d'escalader.

**4. Ton compte est déjà lisible et cohérent :** portefeuille fiat actif, pas de migration ETH en
attente, cartes sur Solana, annonces réglables en ETH **et** en euros. Ça restreint utilement
l'éventail des signatures possibles.

Et une contrainte à connaître : **une offre directe dure au minimum 24 h** (l'API arrondit toute
durée plus courte à un jour).

---

## L'inconnue n°1, à lever avant d'écrire la moindre logique

Ta sonde du 19/09 prouve que **vendre** ne demande aucune signature. **Elle ne dit rien de
l'achat**, où c'est de l'argent qui sort. Quatre issues, et elles donnent quatre projets :

| Ce que rend la sonde | Conséquence |
|---|---|
| aucune autorisation | **Python pur.** Pas de clé privée sur ta machine, pas de Node. Le projet est deux fois plus simple |
| autorisation Solana | Python pur reste possible (la recette complète est écrite dans tes propres notes) |
| autorisation Ethereum/Base | Python probablement suffisant ; à confirmer sur la forme exacte du message |
| autorisation portefeuille fiat ou StarkEx | **Node obligatoire** : la bibliothèque n'existe qu'en JavaScript. C'est le rail euro qui devient cher — on démarrerait alors en ETH seul |

La sonde ne crée rien : elle se contente de demander ce qu'il faudrait signer. Mais **on le
prouvera au lieu de le supposer** — empreinte du compte avant, empreinte après, et on vérifie que
rien n'a bougé. C'est du vrai argent.

Trois tirs, pas un : en ETH seul, en euros seul, et avec les deux — c'est la comparaison qui
informe.

---

## Architecture

```
acheteur/
├── CLAUDE.md · README.md (runbook : chaque commande, son coût, ce qu'elle dépense)
├── DECISIONS.md          journal daté
├── MESURES.md            ce qui est PROUVÉ par une sonde, avec sa date et son effectif
├── acheteur/
│   ├── core/             config (simulation par défaut), db, horloge injectable,
│   │                     journalisation qui masque les secrets
│   ├── auth/             JWT 30 j + renouvellement ; connexion interactive isolée
│   ├── sorare/
│   │   ├── client.py     porté de Pickdeck : throttle, 429, complexité
│   │   ├── requetes.py   lectures
│   │   └── mutations.py  SEUL module qui sait envoyer une offre
│   ├── marche/           devises · liquidité · population · référence de prix · carnet
│   ├── decision/         sélection · paliers · groupage par vendeur · proposition
│   ├── paiement/         choix du rail · soldes · signature (port + implémentations)
│   ├── garde_fous/       règles pures + la barrière, passage obligé avant tout envoi
│   ├── negociation/      machine à états · envoi · réconciliation · escalade · veille
│   ├── approbation/      port + humain (phase 1) + automatique (phase 2)
│   └── cli/              scanner · approuver · envoyer · reconcilier · veiller · arreter
├── sondes/               + resultats/ (GITIGNORÉ : contient des adresses de portefeuille)
└── signataire/           N'EXISTE QUE SI la sonde l'exige
```

**Le principe structurant :** tout ce qui *décide* est une fonction pure, sans réseau ni base,
testable sur des cas figés. Les appels API et les écritures vivent chez l'appelant. C'est la
convention de Pickdeck, et c'est ici qu'elle vaut le plus cher : la logique qui décide combien
offrir doit être vérifiable sans jamais toucher à l'API de production.

**Le bot ne lit pas la base de Pickdeck.** La référence de prix ne porte que sur quelques jours de
ventes, que l'API rend par paquets de 200 joueurs en un appel. Moins cher qu'un couplage entre deux
bases, et les deux dépôts restent indépendants.

**L'horloge est injectable partout.** Ici ce n'est pas un confort de test : une annonce doit être
comparée au marché **à sa date de pose**, pas à maintenant, sinon on compare un prix d'hier à des
ventes d'aujourd'hui.

**Si le Node devient nécessaire**, ce sera un **sous-processus, pas un serveur** : pas de port en
écoute, la clé privée passe par l'entrée standard et ne survit pas à la signature.

---

## La machine à états d'une négociation

### Ce qui déclenche quoi

| Ce qui arrive | Réaction |
|---|---|
| Refus, motif « offre trop basse » (ou « ajoute du cash ») | **escalade immédiate** au palier suivant — pas d'attente de 24 h |
| Refus, motif « je ne vends pas » ou « carte non désirée » | **abandon définitif**. Escalader serait jeter de l'argent contre un mur |
| Refus, motif « uniquement en cash » | rejeu **au même palier**, sur le rail euro |
| Refus, motif « dans une composition » | sommeil jusqu'à la fin de la gameweek |
| Refus sans motif | traité comme « trop basse », mais **compté à part** dans le journal : c'est une hypothèse, pas un fait |
| Expiration silencieuse (24 h) | **un seul** ré-essai, au palier suivant, et seulement si l'annonce est toujours vivante au même prix |
| Contre-offre du vendeur sous notre plafond | on accepte, on n'escalade pas |

**On n'annule jamais pour reposter plus haut.** L'annulation sert à trois choses, toutes
défensives : l'arrêt d'urgence ; l'annonce a disparu ou la carte est partie ailleurs ; et le prix
demandé est descendu **sous** notre offre ouverte — payer plus cher que le prix affiché serait
absurde.

### Ne jamais envoyer deux fois la même offre

Trois couches indépendantes, parce qu'une seule ne suffit pas :

1. **Écriture avant réseau.** La ligne du journal est enregistrée *avant* l'appel. Si le processus
   meurt entre les deux, la trace existe et la réconciliation la rattrape.
2. **Unicité en base.** Un index unique empêche physiquement deux offres vivantes sur le même lot.
   Deux processus lancés en parallèle : le second échoue **avant** d'atteindre le réseau. C'est la
   garantie la plus solide, elle ne dépend d'aucun code applicatif.
3. **Réconciliation obligatoire au démarrage.** Aucun envoi n'est possible tant qu'il reste une
   ligne dont l'état est douteux. Une ligne douteuse **gèle tout son lot** : le risque, ce serait un
   double achat.

---

## Le journal des offres : le harnais de mesure

C'est le cœur du projet. Chaque offre envoyée enregistre non seulement **ce qu'on a fait** mais
**pourquoi** : le prix demandé, la référence de marché, **la fenêtre utilisée et son nombre de
ventes**, si une enchère l'a abaissée, la date de pose de l'annonce, le taux de change utilisé et sa
fraîcheur. Puis, côté observé : l'état, le motif de refus, la réponse brute.

**Figer la référence au moment de l'envoi est la règle la plus importante du projet.** Pickdeck
s'est déjà fait avoir par une colonne réécrite après coup, qui transformait une prédiction en
constat et une mesure de qualité en tautologie. Recalculer après coup le « % de la moyenne » d'une
offre acceptée ferait exactement la même erreur.

Contraintes portées par la base et non par le code : le palier ne peut pas dépasser 80 %, une
référence ne peut pas s'appuyer sur moins de 3 ventes, une ligne simulée ne peut pas porter
d'identifiant Sorare.

**L'appariement avec Sorare** se fait en trois passes — par identifiant quand on l'a ; sinon par
signature métier (mêmes cartes, même vendeur, même montant, même créneau horaire) ; et en dernier
recours, si plusieurs candidates correspondent, on s'arrête et on alerte plutôt que de deviner.
Cas particulier traité : une offre faite à la main depuis l'appli web apparaît comme inconnue du
journal — on l'importe et on **suspend le cycle**, parce qu'une dépense non décidée fausse le
comptage.

---

## Garde-fous : ta règle, appliquée au bon moment

Tu ne veux pas de plafond arbitraire. Ce qui reste n'en est pas — ce sont des attrape-bugs et
l'application littérale de ce que tu as demandé :

| | Règle | Pourquoi |
|---|---|---|
| 1 | **Somme des offres ouvertes ≤ solde disponible du rail** | Ta règle « pas assez d'argent → on saute », appliquée au bon moment. Dix offres à 3 € sur 12 € de solde peuvent toutes aboutir |
| 2 | Solde relu **juste avant** l'envoi | Un solde lu il y a dix minutes n'est pas un solde |
| 3 | Jamais offrir plus que le prix demandé | Un dépassement signale presque toujours une erreur d'unité, pas une décision |
| 4 | Cohérence d'unité ETH / centimes | Le facteur d'erreur est de 10¹⁸. Un montant en wei qui tient dans un petit entier est presque sûrement des centimes non convertis |
| 5 | Taux de change de moins de 15 min, sinon on refuse de convertir | |
| 6 | Palier plafonné à 80 % | En base **et** dans le code |
| 7 | Plafond d'offres ouvertes **par vendeur** | Pas un budget : une précaution contre le démarchage, tant qu'on ne sait pas si Sorare a un anti-spam |
| 8 | Arrêt d'urgence | Un fichier à la racine suffit à tout bloquer |
| 9 | Mode réel à trois verrous | Variable d'environnement **et** option de ligne de commande **et** re-saisie du montant total. C'est le protocole d'un virement bancaire, et c'est le bon |

Et un défaut d'ingénierie : **le bot démarre en simulation et y revient à chaque redémarrage.**

**Ce qui prouve que ces règles tiennent**, et c'est le point qui compte : un test qui parcourt tout
le code source et vérifie mécaniquement qu'il n'existe **qu'un seul chemin** vers l'envoi d'une
offre, et que ce chemin passe par la barrière. Quinze lignes, et ça rattrape le jour où quelqu'un
prendra un raccourci « juste pour tester ».

---

## Le mode « propose, tu valides »

**Fichier de propositions + mail + ligne de commande, pas de page web.** Trois raisons : la
validation doit être asynchrone (le scan tourne toutes les 15 min, tu n'es pas devant l'écran) ; un
fichier horodaté dit exactement ce qui a été proposé et sur quelle base, ce qu'une page éphémère ne
fait pas ; et une page web, c'est un serveur à sécuriser pour un automate qui dépense de l'argent —
le pire rapport bénéfice/risque du projet.

Le mail reprend le format de tes alertes actuelles : un tableau avec, par ligne, joueur · rareté ·
vendeur · prix demandé · référence (fenêtre **et nombre de ventes**) · écart · palier · montant ·
rail · solde restant. **Jamais un chiffre sans son effectif.**

Tu valides ensuite en une commande, ligne par ligne, et la confirmation finale te demande de
**retaper le montant total**. C'est délibéré : c'est le geste qui empêche le « oui » machinal.

**Le passage en phase 2 ne réécrit rien.** L'approbation est un composant interchangeable : la
version humaine, c'est toi ; la version automatique approuve ce que la barrière autorise, avec une
politique **plus stricte**. Et elle **refuse de démarrer** tant que le journal ne contient pas assez
d'offres closes dont au moins une acceptée. Le basculement est conditionné par la mesure, pas par
une case à cocher.

---

## Secrets

**Jamais stockés :** ton mot de passe Sorare (saisi à la main, en session interactive seulement) et
les codes de double authentification. Conséquence directe : **le module de connexion n'est jamais
importé par la boucle automatique.** Si le jeton expire, le bot s'arrête et te le dit ; il ne se
reconnecte pas tout seul.

**Le jeton (30 jours) va dans le gestionnaire d'identifiants Windows**, pas dans un fichier. Pickdeck
met le sien dans un fichier ignoré par git — ici c'est de l'argent, et un fichier traîne dans les
sauvegardes et les partages d'écran. Il se renouvelle **trois jours avant l'échéance**, sans mot de
passe : renouveler après coup obligerait à ressaisir le mot de passe, donc à être présent.

**Double authentification sur changement d'adresse internet :** traitée comme un arrêt d'urgence. On
ne déclenche jamais une invite automatique et on ne cherche jamais à la contourner. Un VPN activé par
inadvertance cassera le bot — c'est le comportement voulu.

Et un filtre qui masque dans les journaux tout ce qui ressemble à un jeton ou à une clé.

---

## Le choix du rail de paiement

« ETH si possible, sinon euros » n'est pas un choix libre : il est contraint par l'annonce (toutes
n'acceptent pas les deux), par tes portefeuilles, et par le solde effectif **une fois les offres en
cours déduites**. Aucun rail finançable → l'offre n'est pas proposée, et **la raison va au journal** :
savoir combien d'affaires tu perds faute de solde est un chiffre que tu veux connaître.

Deux pièges à écrire en gros dans le code :

- **L'arrondi s'inverse entre l'affichage et l'envoi.** À l'affichage on arrondit vers le haut
  (annoncer un prix qu'on ne peut pas payer serait pire). À l'envoi, vers le bas : on ne dépense
  jamais plus que ce qui a été approuvé. Et comme un cran vaut environ 0,22 € — soit le prix
  plancher du marché — un arrondi vers le bas peut faire tomber le montant à zéro sur une petite
  carte. Un montant nul, ou qui s'écarte de plus de 2 % de ce qui a été décidé, est un refus.
- **Aucun nombre à virgule flottante n'approche la chaîne des montants.** Les montants en ETH ont
  18 décimales ; un flottant les massacre silencieusement.

---

## Lots livrables

| Lot | Contenu | Dépense |
|---|---|---|
| **L0** | Squelette, config (simulation par défaut), client porté, jeton, sonde d'état du compte | 0 € |
| **L1** | **La sonde de signature à l'achat** — empreinte avant/après. **Décide de l'architecture de tous les suivants** | 0 € |
| **L2** | Journal + réconciliation **en lecture seule** ; import des offres déjà envoyées | 0 € |
| **L3** | Population de joueurs liquides recalculée, référence de prix, seuil, paliers, groupage — **tout hors réseau** | 0 € |
| **L4** | Garde-fous + barrière + simulation complète + scan et approbation | 0 € |
| **L5** | Préparation d'offre réelle et signature si L1 l'exige. **On s'arrête juste avant l'envoi** | 0 € |
| **L6** | **Premier envoi réel : une seule offre, sur la carte la moins chère du marché, approuvée à la main** | ~1 € |
| **L7** | Machine à états, escalade sur motif, veille défensive, contre-offres | quelques € |
| **L8** | Offres groupées par vendeur | selon budget |
| **L9** | Tâche planifiée toutes les 15 min + mail + boucle complète phase 1 | réelle |
| **L10** | **Mesure** : taux d'acceptation par palier et par motif de refus | — |
| **L11** | Bascule automatique, débloquée par L10 | réelle |

L10 n'est pas décoratif : c'est lui qui dira si les paliers valent leur complexité, ou si une offre
unique bien placée fait aussi bien. **L11 ne s'ouvre pas avant que L10 ait un verdict.**

---

## À faire tout de suite, indépendamment du bot

`backend/sonde_relist.json` (dans Pickdeck) contient ton adresse Ethereum et ta clé de portefeuille
en clair, et n'est couvert par aucune règle d'exclusion git. À déplacer dans `backend/discovery/`
(déjà prévu pour ça, déjà ignoré) ou à supprimer.

---

## Vérification

- **L1** : la sonde imprime le type exact d'autorisation demandé, et prouve par comparaison
  avant/après qu'elle n'a rien créé.
- **Cœur de décision** : les cas réels figés du projet Apps Script rejoués en Python doivent donner
  les mêmes verdicts et les mêmes montants. Un test qui passerait aussi avec la version fautive ne
  compte pas.
- **Population recalculée** : comparer la liste produite à celle de ta feuille. Tout écart doit
  s'expliquer par la date de calcul, pas par une divergence de règle.
- **Engagement ≤ solde** : test de propriété sur des jeux d'offres tirés au hasard.
- **Crash au milieu d'un envoi** : on interrompt volontairement entre l'appel et l'enregistrement,
  puis on réconcilie. Attendu : une seule ligne, zéro doublon.
- **Course entre deux processus** : le second doit échouer avant d'émettre le moindre appel réseau.
- **Chemin unique** : le test qui parcourt le code et prouve qu'aucune autre voie ne mène à l'envoi.
- **Bout en bout (L6)** : une offre réelle à ~1 €, retrouvée côté Sorare avec le bon montant, puis
  annulée.

---

## Ce qui reste à mesurer, par ordre de gravité financière

1. **La signature à l'achat.** Bloque tout — c'est L1.
2. **La sonde est-elle vraiment sans effet ?** L'empreinte avant/après le prouve. Si elle l'infirme,
   il n'existe aucun point de mesure gratuit et L6 devient plus délicat.
3. **Que devient une offre quand la carte est vendue à quelqu'un d'autre entre-temps ?** Si l'offre
   survit, tu peux acheter une carte que tu ne voulais plus. C'est **le risque le plus insidieux du
   projet** ; en attendant la réponse, la veille annule par défaut.
4. **Un refus porte-t-il toujours son motif ?** Toute la machine à états repose là-dessus. Si le
   motif manque souvent, l'escalade redevient aveugle et il faudra revoir la politique.
5. **Sorare a-t-il un anti-spam ?** Rien dans le schéma. Le plafond d'offres par vendeur est une
   précaution en attendant de savoir.
6. **Qui paie les frais de marché à l'achat ?** Ça change le montant réellement débité.
7. **Une offre directe sur une carte déjà en vente est-elle recevable**, ou le vendeur doit-il
   d'abord retirer son annonce ?
8. **Y a-t-il un plafond au nombre d'offres ouvertes simultanées ?**

---

## La règle de décision, tranchée

**Filtre d'entrée :** on ne retient qu'une annonce dont le prix demandé est **sous 90 % de la
référence de marché** du joueur.

**Montant offert : 70 % du prix demandé**, puis 75 %, puis 80 % maximum.

Les deux se tiennent, et c'est ce qui rend la règle sûre : comme le filtre garantit que le prix
demandé est déjà sous le marché, une offre à 70 % de ce prix vaut **au plus 63 % de la valeur réelle
de la carte**. Le cas gênant — offrir plus cher que l'annonce — est exclu par construction, sans
avoir besoin de la précaution que ton code Apps Script avait dû ajouter.

**Sur le seuil à 90 %, un chiffre à garder en tête :** tes propres mesures disent qu'une annonce se
situe en médiane à 90 % de la moyenne sur 7 jours. Le filtre retiendra donc de l'ordre de la moitié
des annonces, et c'est la négociation qui fera le tri. C'est un choix assumé — volume élevé d'offres
basses plutôt que sélection en amont. Le seuil est **un réglage**, pas une constante en dur, et le
lot 10 mesurera le taux d'acceptation pour dire si le volume vaut son coût.

**Reste à préciser avant le lot 3** (la conception statistique tourne encore) :

- **Moyenne ou médiane** pour la référence — Pickdeck a tranché « médiane, jamais moyenne » parce
  que le marché porte des annonces délirantes ; ton Apps Script calcule la moyenne. Les deux
  existent déjà, l'écart se mesure sur tes données.
- **La fenêtre de 3 à 7 jours « selon le joueur »** : sur quel critère elle varie (volume de ventes ?
  volatilité ?), et l'effectif minimal sous lequel on n'affiche rien.
- **La décote supplémentaire des offres groupées** (65 % au lieu de 70 %) : par quoi elle se
  justifie, et que faire si le vendeur accepte un lot où seules deux cartes sur cinq étaient de
  vraies affaires.
- **Combien d'offres** il faut avoir envoyées avant qu'un taux d'acceptation par palier soit autre
  chose que du bruit — c'est ce qui conditionne l'ouverture du lot 11.
