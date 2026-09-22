"""Fichier de propositions horodaté (PLAN.md § « Le mode propose, tu valides » :
« un fichier horodaté dit exactement ce qui a été proposé et sur quelle base,
ce qu'une page éphémère ne fait pas »).

Ce n'est PAS la base : une proposition non encore approuvée n'a pas sa place
dans `OffreJournal` (occuperait l'index unique joueur/vendeur et bloquerait
un futur essai réel — même raison documentée pour `scan_marche.py`/
`scan_liste_liquidite.py`, voir DECISIONS.md). Le fichier JSON est la seule
trace entre le scan périodique (`cli/proposer_periodique.py`) et
l'approbation asynchrone (`cli/approuver_propositions.py`).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from acheteur.decision.paliers import Palier
from acheteur.decision.proposition import PropositionGroupe, PropositionSimple
from acheteur.marche.devises import Devise, Montant
from acheteur.marche.types import Annonce, Joueur, Rareté

DOSSIER_PROPOSITIONS_DEFAUT = Path("propositions")

# Une proposition approuvée bien après le scan qui l'a produite s'appuie sur
# une annonce potentiellement disparue ou repricée entre-temps —
# `cli/approuver_propositions.py` revérifie chaque annonce en direct avant
# tout envoi (comme `cycle_negociation._rafraichir_annonce`), mais un
# fichier trop vieux est un signal à afficher, pas à masquer (PLAN.md :
# « jamais un chiffre sans son effectif »).
DELAI_PEREMPTION_MINUTES_DEFAUT = 30


def fichier_perime(
    horodatage: datetime, maintenant: datetime, delai_minutes: int = DELAI_PEREMPTION_MINUTES_DEFAUT
) -> bool:
    return (maintenant - horodatage).total_seconds() > delai_minutes * 60


def _annonce_vers_dict(annonce: Annonce) -> dict:
    return {
        "joueur_slug": annonce.joueur.slug,
        "joueur_nom": annonce.joueur.nom,
        "rarete_nom": annonce.joueur.rareté.nom,
        "rarete_classement": annonce.joueur.rareté.classement,
        "vendeur_slug": annonce.vendeur_slug,
        "prix_demande_valeur": annonce.prix_demande.valeur,
        "prix_demande_devise": annonce.prix_demande.devise.value,
        "accepte_eth": annonce.accepte_eth,
        "accepte_eur": annonce.accepte_eur,
        "date_pose": annonce.date_pose.isoformat(),
        "asset_id": annonce.asset_id,
        "in_season": annonce.in_season,
    }


def _annonce_depuis_dict(d: dict) -> Annonce:
    return Annonce(
        joueur=Joueur(
            slug=d["joueur_slug"],
            nom=d["joueur_nom"],
            rareté=Rareté(nom=d["rarete_nom"], classement=d["rarete_classement"]),
        ),
        vendeur_slug=d["vendeur_slug"],
        prix_demande=Montant(d["prix_demande_valeur"], Devise(d["prix_demande_devise"])),
        accepte_eth=d["accepte_eth"],
        accepte_eur=d["accepte_eur"],
        date_pose=datetime.fromisoformat(d["date_pose"]),
        asset_id=d.get("asset_id", ""),
        in_season=d.get("in_season"),
    )


def _proposition_vers_dict(p: PropositionSimple | PropositionGroupe) -> dict:
    if isinstance(p, PropositionSimple):
        return {
            "type": "simple",
            "annonce": _annonce_vers_dict(p.annonce),
            "reference_prix_valeur": p.reference_prix_valeur,
            "montant_offre": p.montant_offre,
            "palier": int(p.palier),
        }
    return {
        "type": "groupe",
        "annonces": [_annonce_vers_dict(a) for a in p.annonces],
        "references_prix": p.references_prix,
        "montants_offre": p.montants_offre,
        "palier": int(p.palier),
        "decote_appliquee": p.decote_appliquee,
    }


def _proposition_depuis_dict(d: dict) -> PropositionSimple | PropositionGroupe:
    if d["type"] == "simple":
        return PropositionSimple(
            annonce=_annonce_depuis_dict(d["annonce"]),
            reference_prix_valeur=d["reference_prix_valeur"],
            montant_offre=d["montant_offre"],
            palier=Palier(d["palier"]),
        )
    return PropositionGroupe(
        annonces=tuple(_annonce_depuis_dict(a) for a in d["annonces"]),
        references_prix=d["references_prix"],
        montants_offre=d["montants_offre"],
        palier=Palier(d["palier"]),
        decote_appliquee=d["decote_appliquee"],
    )


def sauvegarder_propositions(
    propositions: list[PropositionSimple | PropositionGroupe],
    horodatage: datetime,
    dossier: Path = DOSSIER_PROPOSITIONS_DEFAUT,
) -> Path:
    """Écrit un fichier JSON horodaté — n'écrase jamais un fichier existant
    (un run répété toutes les 15 minutes produit un nouveau fichier à chaque
    fois, tous conservés comme trace)."""
    dossier.mkdir(parents=True, exist_ok=True)
    nom = f"propositions_{horodatage.strftime('%Y%m%dT%H%M%S')}.json"
    chemin = dossier / nom
    contenu = {
        "horodatage": horodatage.isoformat(),
        "propositions": [_proposition_vers_dict(p) for p in propositions],
    }
    chemin.write_text(json.dumps(contenu, indent=2, ensure_ascii=False), encoding="utf-8")
    return chemin


def charger_propositions(
    chemin: Path,
) -> tuple[datetime, list[PropositionSimple | PropositionGroupe]]:
    contenu = json.loads(chemin.read_text(encoding="utf-8"))
    horodatage = datetime.fromisoformat(contenu["horodatage"])
    propositions = [_proposition_depuis_dict(d) for d in contenu["propositions"]]
    return horodatage, propositions


def dernier_fichier_propositions(dossier: Path = DOSSIER_PROPOSITIONS_DEFAUT) -> Path | None:
    if not dossier.exists():
        return None
    fichiers = sorted(dossier.glob("propositions_*.json"))
    return fichiers[-1] if fichiers else None
