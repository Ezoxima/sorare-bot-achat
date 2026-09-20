"""Simulation complète sans appel Sorare (extension de L2).

Permets de tester la chaîne complète decision → journal → approbation
sans toucher à l'API réelle. Les propositions sont écrites en base avec
`mode_simulation=True`, jamais envoyées à Sorare.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from acheteur.core.horloge import Horloge
from acheteur.decision.proposition import PropositionGroupe, PropositionSimple
from acheteur.garde_fous import ContexteBarriere, envoyer_offre_proposal
from acheteur.negociation.journal import EtatOffre, MotifRefus, lignes_ouvertes


def simuler_propositions(
    propositions: list[PropositionSimple | PropositionGroupe],
    contexte: ContexteBarriere,
    session: Session,
    horloge: Horloge,
) -> list[str]:
    """Simule l'envoi d'une liste de propositions (mode test).

    Écrit toutes les propositions dans le journal avec `mode_simulation=True`.
    Si un garde-fou échoue sur une proposition, elle est ignorée (journalisée).

    Args:
        propositions: liste des propositions à simuler
        contexte: soldes, offres ouvertes, etc.
        session: session SQLAlchemy
        horloge: horloge injectable

    Returns:
        liste des IDs de lignes créées (ou messages d'erreur si rejet)
    """
    resultats = []

    for prop in propositions:
        try:
            envoyer_offre_proposal(
                prop,
                contexte,
                session,
                horloge,
                mode_simulation=True,  # Toujours simulation ici
            )
            # Si succès, récupère l'ID de la ligne créée
            lignes = lignes_ouvertes(session, mode_simulation=True)
            if lignes:
                resultats.append(f"OK (ligne #{lignes[-1].id})")
        except Exception as e:
            resultats.append(f"Rejet : {str(e)}")

    return resultats


def simuler_acceptation_offre(
    ligne_id: int,
    session: Session,
    horloge: Horloge,
) -> None:
    """Simule l'acceptation d'une offre par le vendeur.

    Bascule la ligne de SIMULEE à ACCEPTEE.

    Args:
        ligne_id: ID de la ligne du journal
        session: session SQLAlchemy
        horloge: horloge injectable
    """
    from acheteur.negociation.journal import OffreJournal

    ligne = session.query(OffreJournal).filter_by(id=ligne_id).one()
    ligne.etat = EtatOffre.ACCEPTEE
    ligne.maj_le = horloge.maintenant()
    session.flush()


def simuler_refus_offre(
    ligne_id: int,
    motif: MotifRefus,
    session: Session,
    horloge: Horloge,
) -> None:
    """Simule le refus d'une offre par le vendeur.

    Bascule la ligne de SIMULEE à REFUSEE avec motif.

    Args:
        ligne_id: ID de la ligne du journal
        motif: motif du refus
        session: session SQLAlchemy
        horloge: horloge injectable
    """
    from acheteur.negociation.journal import OffreJournal

    ligne = session.query(OffreJournal).filter_by(id=ligne_id).one()
    ligne.etat = EtatOffre.REFUSEE
    ligne.motif_refus = motif
    ligne.maj_le = horloge.maintenant()
    session.flush()
