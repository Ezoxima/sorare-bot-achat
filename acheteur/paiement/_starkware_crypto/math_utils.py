"""Arithmétique de courbe elliptique (courbe STARK) — adapté de
`starkware-libs/cairo-lang`, `src/starkware/crypto/signature/math_utils.py`
(Apache 2.0, voir `LICENSE` dans ce dossier).

Coupé par rapport à l'original : `is_quad_residue`/`sqrt_mod`/`pi_as_string`
retirés (inutiles ici, évite la dépendance `sympy`/`mpmath`) ; `div_mod`
utilise `pow(x, -1, p)` (natif depuis Python 3.8) plutôt que `sympy.igcdex`.
"""

from __future__ import annotations

# Un point (x, y) sur une courbe elliptique.
ECPoint = tuple[int, int]


def div_mod(n: int, m: int, p: int) -> int:
    """Trouve 0 <= x < p tel que (m * x) % p == n."""
    return (n * pow(m, -1, p)) % p


def ec_add(point1: ECPoint, point2: ECPoint, p: int) -> ECPoint:
    """Somme de deux points (forme affine, abscisses différentes)."""
    assert (point1[0] - point2[0]) % p != 0
    m = div_mod(point1[1] - point2[1], point1[0] - point2[0], p)
    x = (m * m - point1[0] - point2[0]) % p
    y = (m * (point1[0] - x) - point1[1]) % p
    return x, y


def ec_neg(point: ECPoint, p: int) -> ECPoint:
    x, y = point
    return (x, (-y) % p)


def ec_double(point: ECPoint, alpha: int, p: int) -> ECPoint:
    """Double un point (y^2 = x^3 + alpha*x + beta mod p, y != 0)."""
    assert point[1] % p != 0
    m = div_mod(3 * point[0] * point[0] + alpha, 2 * point[1], p)
    x = (m * m - 2 * point[0]) % p
    y = (m * (point[0] - x) - point[1]) % p
    return x, y


def ec_mult(m: int, point: ECPoint, alpha: int, p: int) -> ECPoint:
    """Multiplie un point par un scalaire (0 < m < order(point))."""
    if m == 1:
        return point
    if m % 2 == 0:
        return ec_mult(m // 2, ec_double(point, alpha, p), alpha, p)
    return ec_add(ec_mult(m - 1, point, alpha, p), point, p)
