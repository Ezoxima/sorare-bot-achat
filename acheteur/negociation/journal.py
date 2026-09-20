"""Le journal des offres : le harnais de mesure du projet (PLAN.md § « Le
journal des offres »).

Une ligne = une carte proposée (pas un lot groupé — le groupage n'a pas
encore de chemin d'envoi ; voir DECISIONS.md, lot L2, pour la portée exacte).

Ce module ne mute jamais rien vers Sorare : il n'écrit que dans la base
locale. `negociation.envoi` (lot L5+) écrira une ligne *avant* l'appel
réseau ; ici on ne fait qu'enregistrer et lire.

Contraintes portées par la base, pas seulement par le code (PLAN.md § L3
et § Garde-fous) :
- le palier ne peut pas dépasser 80% ;
- une référence de prix ne peut pas s'appuyer sur moins de 3 ventes ;
- une ligne simulée ne peut pas porter d'identifiant Sorare ;
- au plus une offre *ouverte* (simulée ou envoyée) par couple joueur/vendeur
  — l'unicité qui empêche physiquement un double envoi sur le même lot.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum, StrEnum

from sqlalchemy import CheckConstraint, Index, String, Text, text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, Session, mapped_column

from acheteur.core.db import Base
from acheteur.marche.devises import Devise


def _enum_par_valeur(enum_cls: type[Enum]) -> SQLEnum:
    """`Enum` SQLAlchemy qui stocke `.value` (pas `.name`, son défaut).

    Nécessaire pour que les contraintes SQL écrites à la main plus bas
    (CHECK, index partiel) puissent comparer `etat` à des chaînes lisibles
    ('simulee', 'envoyee'...) au lieu des noms de membres en capitales.
    """
    return SQLEnum(enum_cls, values_callable=lambda obj: [e.value for e in obj])


class EtatOffre(StrEnum):
    """État d'une ligne du journal — le cycle de vie de l'offre elle-même.

    Une ligne importée (voir `reconciliation.py`, `import_automatique=True`)
    prend l'un de ces mêmes états, celui observé côté Sorare : la provenance
    (décidée par le bot ou trouvée après coup) et le cycle de vie sont deux
    informations distinctes, portées par deux colonnes différentes.
    """

    SIMULEE = "simulee"
    ENVOYEE = "envoyee"
    ACCEPTEE = "acceptee"
    REFUSEE = "refusee"
    EXPIREE = "expiree"
    ANNULEE = "annulee"
    EN_SOMMEIL = "en_sommeil"


class MotifRefus(StrEnum):
    """Les six motifs de refus renvoyés par Sorare, plus un septième local.

    `SANS_MOTIF` n'existe pas côté Sorare : PLAN.md demande qu'un refus sans
    motif soit traité comme « trop basse » pour l'escalade, mais **compté à
    part** dans le journal — c'est une hypothèse, pas un fait observé.
    """

    OFFRE_TROP_BASSE = "offre_trop_basse"
    NE_VEND_PAS = "ne_vend_pas"
    CARTE_NON_DESIREE = "carte_non_desiree"
    UNIQUEMENT_CASH = "uniquement_cash"
    AJOUTE_CASH = "ajoute_cash"
    DANS_COMPOSITION = "dans_composition"
    SANS_MOTIF = "sans_motif"


# États d'une ligne qui occupe encore le couple (joueur, vendeur) — c'est sur
# ceux-là que porte l'index unique, et sur ceux-là seulement que le
# réconciliateur va chercher une contrepartie côté Sorare.
ETATS_OUVERTS = (EtatOffre.SIMULEE, EtatOffre.ENVOYEE)


class OffreJournal(Base):
    """Une ligne du journal des offres."""

    __tablename__ = "offres_journal"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Absent tant que l'offre n'a pas été envoyée à Sorare et confirmée ;
    # jamais présent sur une ligne simulée (ck_simulee_sans_identifiant_sorare).
    sorare_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)

    joueur_slug: Mapped[str] = mapped_column(String, nullable=False)
    vendeur_slug: Mapped[str] = mapped_column(String, nullable=False)

    # Nullables : inconnus pour une ligne importée (`import_automatique`) —
    # une offre faite à la main depuis l'appli web n'est passée par aucune
    # décision du bot, il n'y a ni référence, ni palier, ni prix affiché
    # connu à enregistrer. Les CHECK ci-dessous n'exigent ces valeurs que
    # pour une ligne *décidée par le bot* (`import_automatique = 0`).
    prix_demande_valeur: Mapped[int | None] = mapped_column(nullable=True)
    prix_demande_devise: Mapped[Devise | None] = mapped_column(
        _enum_par_valeur(Devise), nullable=True
    )

    montant_offre_valeur: Mapped[int] = mapped_column(nullable=False)
    montant_offre_devise: Mapped[Devise] = mapped_column(_enum_par_valeur(Devise), nullable=False)

    # Référence de marché figée au moment de l'envoi (PLAN.md : ne jamais la
    # recalculer après coup dans le journal — voir CLAUDE.md).
    reference_prix_valeur: Mapped[int | None] = mapped_column(nullable=True)
    reference_fenetre_jours: Mapped[int | None] = mapped_column(nullable=True)
    reference_nb_ventes: Mapped[int | None] = mapped_column(nullable=True)

    palier: Mapped[int | None] = mapped_column(nullable=True)
    decote_groupe: Mapped[bool] = mapped_column(nullable=False, default=False)

    date_pose_annonce: Mapped[datetime | None] = mapped_column(nullable=True)

    # Fraîcheur du taux de change utilisé pour cette offre, si un rail a été
    # converti (garde-fou : refuser de convertir si > 15 min, lot L4).
    taux_change_horodatage: Mapped[datetime | None] = mapped_column(nullable=True)

    etat: Mapped[EtatOffre] = mapped_column(_enum_par_valeur(EtatOffre), nullable=False)
    mode_simulation: Mapped[bool] = mapped_column(nullable=False)
    motif_refus: Mapped[MotifRefus | None] = mapped_column(
        _enum_par_valeur(MotifRefus), nullable=True
    )
    reponse_brute: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Vrai pour une ligne créée par la réconciliation (offre manuelle
    # découverte sur Sorare), jamais par une décision du bot.
    import_automatique: Mapped[bool] = mapped_column(nullable=False, default=False)

    cree_le: Mapped[datetime] = mapped_column(nullable=False)
    maj_le: Mapped[datetime] = mapped_column(nullable=False)

    __table_args__ = (
        # `import_automatique = 1` : ligne non décidée par le bot, ces
        # contraintes ne portent que sur ce que le bot lui-même a calculé.
        CheckConstraint(
            "import_automatique = 1 OR palier <= 80",
            name="ck_palier_max_80",
        ),
        CheckConstraint(
            "import_automatique = 1 OR reference_nb_ventes >= 3",
            name="ck_reference_min_3_ventes",
        ),
        CheckConstraint(
            "NOT (mode_simulation = 1 AND sorare_id IS NOT NULL)",
            name="ck_simulee_sans_identifiant_sorare",
        ),
        Index(
            "ix_offre_ouverte_unique_par_joueur_vendeur",
            "joueur_slug",
            "vendeur_slug",
            unique=True,
            sqlite_where=text(
                "etat IN ('" + "', '".join(e.value for e in ETATS_OUVERTS) + "')"
            ),
        ),
    )


def enregistrer_ligne(
    session: Session,
    *,
    joueur_slug: str,
    vendeur_slug: str,
    prix_demande_valeur: int,
    prix_demande_devise: Devise,
    montant_offre_valeur: int,
    montant_offre_devise: Devise,
    reference_prix_valeur: int,
    reference_fenetre_jours: int,
    reference_nb_ventes: int,
    palier: int,
    date_pose_annonce: datetime,
    horloge_maintenant: datetime,
    mode_simulation: bool,
    decote_groupe: bool = False,
    taux_change_horodatage: datetime | None = None,
    sorare_id: str | None = None,
) -> OffreJournal:
    """Écrit une ligne *décidée par le bot* (référence, palier connus).

    En lot L2, appelée seulement par les tests — l'écriture *avant l'envoi
    réel* d'une ligne décidée par le bot arrive en L5. Pour importer une
    offre trouvée sur Sorare sans décision du bot, voir `importer_ligne_manuelle`.
    """
    ligne = OffreJournal(
        sorare_id=sorare_id,
        joueur_slug=joueur_slug,
        vendeur_slug=vendeur_slug,
        prix_demande_valeur=prix_demande_valeur,
        prix_demande_devise=prix_demande_devise,
        montant_offre_valeur=montant_offre_valeur,
        montant_offre_devise=montant_offre_devise,
        reference_prix_valeur=reference_prix_valeur,
        reference_fenetre_jours=reference_fenetre_jours,
        reference_nb_ventes=reference_nb_ventes,
        palier=palier,
        decote_groupe=decote_groupe,
        date_pose_annonce=date_pose_annonce,
        taux_change_horodatage=taux_change_horodatage,
        etat=EtatOffre.SIMULEE if mode_simulation else EtatOffre.ENVOYEE,
        mode_simulation=mode_simulation,
        import_automatique=False,
        cree_le=horloge_maintenant,
        maj_le=horloge_maintenant,
    )
    session.add(ligne)
    session.flush()
    return ligne


def importer_ligne_manuelle(
    session: Session,
    *,
    sorare_id: str,
    joueur_slug: str,
    vendeur_slug: str,
    montant_offre_valeur: int,
    montant_offre_devise: Devise,
    etat: EtatOffre,
    motif_refus: MotifRefus | None,
    reponse_brute: str | None,
    creee_le: datetime,
    horloge_maintenant: datetime,
) -> OffreJournal:
    """Importe une offre trouvée sur Sorare sans ligne de journal correspondante.

    PLAN.md : une offre faite à la main depuis l'appli web. On ne connaît
    ni la référence de marché ni le palier qui l'ont justifiée — ces champs
    restent NULL plutôt que d'inventer une valeur qui ferait croire à une
    décision du bot. `import_automatique = True` le marque sans ambiguïté ;
    c'est à l'appelant de suspendre le cycle (voir `reconciliation.cycle_suspendu`).
    """
    ligne = OffreJournal(
        sorare_id=sorare_id,
        joueur_slug=joueur_slug,
        vendeur_slug=vendeur_slug,
        montant_offre_valeur=montant_offre_valeur,
        montant_offre_devise=montant_offre_devise,
        etat=etat,
        mode_simulation=False,
        motif_refus=motif_refus,
        reponse_brute=reponse_brute,
        import_automatique=True,
        cree_le=creee_le,
        maj_le=horloge_maintenant,
    )
    session.add(ligne)
    session.flush()
    return ligne


def lignes_ouvertes(session: Session) -> list[OffreJournal]:
    """Les lignes qui occupent encore un couple (joueur, vendeur)."""
    return list(
        session.query(OffreJournal)
        .filter(OffreJournal.etat.in_(ETATS_OUVERTS))
        .order_by(OffreJournal.id)
        .all()
    )
