"""The P value a test statistic implies: t, F, chi-squared and z.

The package has no numerical dependency, and these four need only two functions beyond the
standard library: the regularized incomplete beta function and the regularized incomplete
gamma function. Both are written here from their definitions in the NIST Digital Library of
Mathematical Functions (DLMF, https://dlmf.nist.gov), chapter 8, and tested against values
computed once, outside the package, with SciPy.

* The incomplete beta function by its continued fraction, DLMF 8.17.22, where it converges
  fast, `x <= (a + 1) / (a + b + 2)`, and through the symmetry of DLMF 8.17.4 elsewhere.
* The incomplete gamma function by its series, DLMF 8.7.1, below `x = a + 1`, and by its
  continued fraction, DLMF 8.9.2, above.

A continued fraction is evaluated forwards, by the modified Lentz method (DLMF 3.10(iii)):
each step multiplies the value so far by a ratio, and the fraction is done when that ratio
is one to the precision of a float.

Each distribution's upper tail is one of these:

* Student's t with `df` degrees of freedom, both tails: `I_x(df / 2, 1 / 2)`, with
  `x = df / (df + t^2)`.
* F with `d1` and `d2` degrees of freedom: `I_x(d2 / 2, d1 / 2)`, with `x = d2 / (d2 + d1 F)`.
* Chi-squared with `df` degrees of freedom: `Q(df / 2, chi2 / 2)`.
* The standard normal, both tails: `erfc(|z| / sqrt(2))`, which the standard library has.
"""

from __future__ import annotations

import math

#: Where a series or a continued fraction is taken to have converged.
EPSILON = 1e-15
#: What stands in for nought in a denominator of the Lentz method, so that it never divides
#: by nought.
_TINY = 1e-300
#: A continued fraction that has not converged after this many steps is a bug or an input
#: out of range, and is said rather than returned.
_STEPS = 10_000


class NotConverged(ArithmeticError):
    """A series or a continued fraction did not converge."""


def _lentz(numerator, denominator) -> float:
    """`b0 + a1 / (b1 + a2 / (b2 + ...))`, with `numerator(n)` giving `a_n` and
    `denominator(n)` giving `b_n`, `n = 0` included for `b0`."""
    value = denominator(0) or _TINY
    upper, lower = value, 0.0
    for n in range(1, _STEPS):
        a, b = numerator(n), denominator(n)
        lower = b + a * lower
        lower = 1.0 / (lower or _TINY)
        upper = b + a / upper
        upper = upper or _TINY
        ratio = upper * lower
        value *= ratio
        if abs(ratio - 1.0) < EPSILON:
            return value
    raise NotConverged("a continued fraction did not converge")


def _log_beta(a: float, b: float) -> float:
    return math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)


def incomplete_beta(a: float, b: float, x: float) -> float:
    """The regularized incomplete beta function `I_x(a, b)`, DLMF 8.17.2, for `a, b > 0`
    and `0 <= x <= 1`."""
    if not (a > 0 and b > 0 and 0.0 <= x <= 1.0):
        raise ValueError(f"I_x(a, b) is not defined at a={a}, b={b}, x={x}")
    if x in (0.0, 1.0):
        return x
    if x > (a + 1.0) / (a + b + 2.0):
        return 1.0 - incomplete_beta(b, a, 1.0 - x)

    def numerator(n: int) -> float:
        # DLMF 8.17.22: d_1 = 1 opens the fraction 1 / (1 + d_1 / (1 + d_2 / ...)), so
        # here a_1 = 1 and a_{n+1} = d_n.
        if n == 1:
            return 1.0
        m, odd = divmod(n - 1, 2)
        if odd:
            return -(a + m) * (a + b + m) * x / ((a + 2 * m) * (a + 2 * m + 1))
        return m * (b - m) * x / ((a + 2 * m - 1) * (a + 2 * m))

    front = math.exp(a * math.log(x) + b * math.log1p(-x) - _log_beta(a, b)) / a
    return front * _lentz(numerator, lambda n: 0.0 if n == 0 else 1.0)


def upper_gamma(a: float, x: float) -> float:
    """The regularized upper incomplete gamma function `Q(a, x)`, DLMF 8.2.4, for `a > 0`
    and `x >= 0`."""
    if not (a > 0 and x >= 0.0):
        raise ValueError(f"Q(a, x) is not defined at a={a}, x={x}")
    if x == 0.0:
        return 1.0
    if x < a + 1.0:
        return 1.0 - _lower_gamma_series(a, x)

    def numerator(n: int) -> float:
        # DLMF 8.9.2: Gamma(a, z) = e^-z z^a (1/(z+) (1-a)/(1+) 1/(z+) (2-a)/(1+) 2/(z+) ...)
        if n == 1:
            return 1.0
        m, odd = divmod(n, 2)
        return float(m) if odd else m - a

    def denominator(n: int) -> float:
        if n == 0:
            return 0.0
        return x if n % 2 else 1.0

    front = math.exp(a * math.log(x) - x - math.lgamma(a))
    return front * _lentz(numerator, denominator)


def _lower_gamma_series(a: float, x: float) -> float:
    """`P(a, x)` by DLMF 8.7.1: `x^a e^-x` times the sum of `x^k / Gamma(a + k + 1)`."""
    term = math.exp(a * math.log(x) - x - math.lgamma(a + 1.0))
    total = term
    for k in range(1, _STEPS):
        term *= x / (a + k)
        total += term
        if term <= total * EPSILON:
            return total
    raise NotConverged("the series of the incomplete gamma function did not converge")


def p_t(t: float, df: float) -> float:
    """The two-sided P of Student's t."""
    if not df > 0:
        raise ValueError(f"t has no distribution with {df} degrees of freedom")
    return incomplete_beta(df / 2.0, 0.5, df / (df + t * t))


def p_f(f: float, d1: float, d2: float) -> float:
    """The P of an F statistic, its upper tail."""
    if not (d1 > 0 and d2 > 0):
        raise ValueError(f"F has no distribution with ({d1}, {d2}) degrees of freedom")
    if f <= 0.0:
        return 1.0
    return incomplete_beta(d2 / 2.0, d1 / 2.0, d2 / (d2 + d1 * f))


def p_chi2(chi2: float, df: float) -> float:
    """The P of a chi-squared statistic, its upper tail."""
    if not df > 0:
        raise ValueError(f"chi-squared has no distribution with {df} degrees of freedom")
    return upper_gamma(df / 2.0, max(chi2, 0.0) / 2.0)


def p_z(z: float) -> float:
    """The two-sided P of a standard normal deviate."""
    return math.erfc(abs(z) / math.sqrt(2.0))
