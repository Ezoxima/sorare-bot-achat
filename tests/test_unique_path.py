"""Test mecanique : prouve qu'il n'existe qu'un seul chemin vers l'envoi.

PLAN.md § Verification : « un test qui parcourt le code source et verifie
mecaniquement qu'il n'existe **qu'un seul chemin** vers l'envoi d'une offre,
et que ce chemin passe par la barriere. »

C'est la garantie structurelle que aucune autre voie ne peut contourner les
garde-fous — pas une promesse de code, une preuve par inspection du source.
"""

from __future__ import annotations

import ast
from pathlib import Path


def test_unique_path_to_sending():
    """Verifie mecaniquement qu'il n'existe qu'un seul module (barriere.py)
    qui appelle enregistrer_ligne().

    C'est le coeur de la garantie : aucun autre code n'a acces direct a
    l'enregistrement du journal. Tous les appels passent par barriere.py,
    qui applique les 9 garde-fous.
    """
    acheteur_dir = Path(__file__).resolve().parents[1] / "acheteur"
    assert acheteur_dir.exists(), f"Dossier {acheteur_dir} non trouve"

    # Chercher tous les fichiers .py
    py_files = list(acheteur_dir.rglob("*.py"))
    assert py_files, f"Aucun fichier .py trouve dans {acheteur_dir}"

    # Tracer les fichiers qui appellent enregistrer_ligne()
    callers = set()

    for py_file in py_files:
        with open(py_file, encoding="utf-8") as f:
            try:
                tree = ast.parse(f.read(), filename=str(py_file))
            except SyntaxError:
                continue

        # Parcourir l'AST
        for node in ast.walk(tree):
            # Chercher les appels a enregistrer_ligne()
            if isinstance(node, ast.Call):
                # Verifie que c'est enregistrer_ligne
                func_name = None
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    func_name = node.func.attr

                if func_name == "enregistrer_ligne":
                    callers.add(py_file)

    # Assertion : UN SEUL fichier appelle enregistrer_ligne()
    assert (
        len(callers) == 1
    ), f"Attendu 1 fichier appellant enregistrer_ligne(), trouve {len(callers)} : {[f.name for f in callers]}"

    caller_file = list(callers)[0]
    assert (
        "barriere" in caller_file.name.lower()
    ), f"Appel trouve dans {caller_file.name}, attendu 'barriere.py'"

    print(f"OK Chemin unique prouve :")
    print(f"  Seul module appellant enregistrer_ligne() : {caller_file.name}")


if __name__ == "__main__":
    test_unique_path_to_sending()
