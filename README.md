# acheteur

Bot d'achat automatique de cartes Sorare vendues nettement sous leur prix de
marché. Voir [PLAN.md](PLAN.md) pour le contexte complet, l'architecture et
les lots livrables ; [DECISIONS.md](DECISIONS.md) pour le journal des
décisions ; [MESURES.md](MESURES.md) pour ce qui est prouvé (par opposition à
supposé) sur l'API Sorare.

**État actuel : L0 (squelette).** Aucun envoi vers Sorare n'est possible —
`acheteur/sorare/mutations.py` n'existe pas encore.

## Installation

```bash
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
copy .env.example .env
```

Remplir `.env` (clé API Sorare — voir sorare.com pour l'obtenir). Le jeton
JWT ne va **pas** dans `.env` : il vit dans le gestionnaire d'identifiants
Windows, voir la commande de connexion ci-dessous.

## Commandes, leur coût, ce qu'elles dépensent

| Commande | Coût | Effet |
|---|---|---|
| `python -m acheteur.cli.connecter --email <email>` | 0 € | Connexion interactive (mot de passe + 2FA demandés au clavier). Écrit le jeton dans le gestionnaire d'identifiants Windows. **Jamais** appelée par la boucle automatique. |
| `python -m acheteur.cli.etat_compte` | 0 € | Lecture seule. Vérifie que le jeton stocké est valide (le renouvelle si besoin), interroge l'état du compte (soldes, migration ETH), écrit un instantané dans `sondes/resultats/` (gitignoré). |
| `python scripts/rafraichir_schema.py` | 0 € | Télécharge le SDL GraphQL Sorare dans `schema/` (gitignoré, régénérable). |
| `pytest` | 0 € | Aucun appel réseau — tout le cœur de décision est testé sur des cas figés. |

Aucune autre commande n'existe encore : pas d'envoi d'offre possible tant que
le lot L1 (sonde de signature) n'a pas tranché l'architecture du paiement.

## Simulation par défaut

Le bot démarre en simulation et y revient à **chaque** redémarrage. Le mode
réel (à partir du lot L6) demandera trois verrous distincts : variable
d'environnement, option de ligne de commande, et re-saisie du montant total
au moment de valider. Voir PLAN.md, section « Garde-fous », règle 9.

## Arrêt d'urgence

Un fichier nommé `ARRET_URGENCE` à la racine du dépôt bloque tout envoi (à
partir du lot L4). Il n'existe pas encore de mécanisme à bloquer — pour
l'instant cette section documente juste le nom retenu.

## Secrets

- **Mot de passe et codes 2FA** : jamais stockés, transitent en mémoire le
  temps de `acheteur.auth.connexion` puis disparaissent.
- **Jeton JWT** : gestionnaire d'identifiants Windows (`acheteur-sorare`),
  jamais dans un fichier.
- **Clé API Sorare** : `.env` (gitignoré) — c'est la clé publique, pas un
  secret de compte.
- Les journaux masquent automatiquement ce qui ressemble à un jeton ou une
  clé (`acheteur.core.journalisation`).
