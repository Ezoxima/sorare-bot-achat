"""Point d'entrée CLI de la connexion interactive.

Fin mince sur `acheteur.auth.connexion`, isolé du reste du bot : ce module et
tout ce qu'il importe ne doivent jamais être importés par la boucle
automatique (scan, envoi, réconciliation).

Usage : python -m acheteur.cli.connecter --email <email>
"""

from acheteur.auth.connexion import main

if __name__ == "__main__":
    main()
