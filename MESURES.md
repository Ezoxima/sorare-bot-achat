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
