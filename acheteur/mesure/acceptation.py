"""Mesure du taux d'acceptation par palier et par motif de refus (lot L10,
PLAN.md § Lots livrables : « L10 n'est pas décoratif : c'est lui qui dira si
les paliers valent leur complexité, ou si une offre unique bien placée fait
aussi bien. L11 ne s'ouvre pas avant que L10 ait un verdict. »).

Fonction pure, comme `decision/` et `negociation.reconciliation.apparier` :
aucun réseau, aucune base — elle prend les lignes déjà lues par l'appelant
(voir `cli/mesure_acceptation.py`).

PLAN.md laisse volontairement ouverte la question du seuil d'effectif à
partir duquel un taux cesse d'être du bruit (« Reste à préciser » — ce n'est
pas à ce module de trancher unilatéralement une décision explicitement
réservée à l'utilisateur). Ce module se contente donc de compter ; c'est à
l'appelant, avec les effectifs sous les yeux, de juger si un taux est
exploitable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from acheteur.negociation.journal import EtatOffre, MotifRefus, OffreJournal

# États qui concluent une négociation avec un résultat observable. Une ligne
# encore ouverte (SIMULEE/ENVOYEE, journal.ETATS_OUVERTS) ou en sommeil
# (attente fin de gameweek, negociation.etats.ActionNegociation.SOMMEIL) n'a
# pas encore de verdict à compter.
ETATS_CONCLUANTS = (EtatOffre.ACCEPTEE, EtatOffre.REFUSEE, EtatOffre.EXPIREE, EtatOffre.ANNULEE)


@dataclass(frozen=True)
class TauxParPalier:
    palier: int
    acceptees: int
    total: int

    @property
    def taux(self) -> float | None:
        """`None` plutôt que 0.0 : aucune ligne conclue n'est une absence de
        donnée, pas un taux nul — les deux ne doivent jamais se confondre
        dans un rapport qui sert à décider d'ouvrir L11."""
        return self.acceptees / self.total if self.total else None


@dataclass
class RapportAcceptation:
    par_palier: list[TauxParPalier] = field(default_factory=list)
    par_motif_refus: dict[MotifRefus, int] = field(default_factory=dict)

    # Lignes vues mais hors périmètre de la mesure (simulées, importées, ou
    # sans palier connu) — comptées pour transparence, jamais mélangées aux
    # totaux ci-dessus (voir `calculer_taux_acceptation`).
    lignes_hors_perimetre: int = 0

    @property
    def total_conclu(self) -> int:
        return sum(t.total for t in self.par_palier)

    @property
    def total_refuse(self) -> int:
        return sum(self.par_motif_refus.values())


def calculer_taux_acceptation(lignes: list[OffreJournal]) -> RapportAcceptation:
    """PLAN.md L10 : ne mesure que ce qui reflète une vraie négociation.

    Exclut du calcul (comptées dans `lignes_hors_perimetre`) :
    - les lignes simulées (`mode_simulation`) — aucun vendeur réel n'a vu
      l'offre, un taux calculé dessus ne mesurerait rien du marché ;
    - les lignes importées (`import_automatique`) — pas de palier décidé par
      le bot, rien à évaluer ;
    - les lignes sans palier connu (ne devrait pas arriver pour une ligne
      décidée par le bot et non importée, mais le champ reste nullable en
      base — voir `negociation.journal.OffreJournal`).

    Ignore silencieusement (ni comptées « conclues », ni « hors périmètre »)
    les lignes encore ouvertes ou en sommeil : elles n'ont simplement pas
    encore de verdict.
    """
    rapport = RapportAcceptation()
    par_palier: dict[int, list[int]] = {}  # palier -> [acceptees, total]

    for ligne in lignes:
        if ligne.mode_simulation or ligne.import_automatique or ligne.palier is None:
            rapport.lignes_hors_perimetre += 1
            continue
        if ligne.etat not in ETATS_CONCLUANTS:
            continue

        compteur = par_palier.setdefault(ligne.palier, [0, 0])
        compteur[1] += 1
        if ligne.etat == EtatOffre.ACCEPTEE:
            compteur[0] += 1

        if ligne.etat == EtatOffre.REFUSEE:
            motif = ligne.motif_refus or MotifRefus.SANS_MOTIF
            rapport.par_motif_refus[motif] = rapport.par_motif_refus.get(motif, 0) + 1

    rapport.par_palier = [
        TauxParPalier(palier=palier, acceptees=acceptees, total=total)
        for palier, (acceptees, total) in sorted(par_palier.items())
    ]
    return rapport
