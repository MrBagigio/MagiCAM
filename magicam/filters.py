"""Filtro One Euro (Casiez, Roussel, Vogel 2012) per posizione e quaternione.

Un filtro solo, due numeri: `min_cutoff` (Hz: quanto liscia da fermo) e `beta` (quanto insegue in velocita').
Il dt viene dal timestamp del SENSORE, non dall'orologio del PC. I valori di default sono quelli classici del paper
e NON sono tarati su MagiCAM: la taratura e' F1.9 e si scrive in docs/MISURE.md.
"""

from __future__ import annotations

import math

from magicam.math3d import Quat, Vec3, quat_dot, quat_normalize

DEFAULT_MIN_CUTOFF = 1.0
DEFAULT_BETA = 0.05
DEFAULT_D_CUTOFF = 1.0


def _alpha(cutoff: float, dt: float) -> float:
    tau = 1.0 / (2.0 * math.pi * cutoff)
    return 1.0 / (1.0 + tau / dt)


class LowPass:
    def __init__(self) -> None:
        self.value: float | None = None

    def filter(self, x: float, alpha: float) -> float:
        if self.value is None:
            self.value = x
        else:
            self.value += alpha * (x - self.value)  # esatto quando x == value
        return self.value


class OneEuro:
    """One Euro su uno scalare."""

    def __init__(
        self,
        min_cutoff: float = DEFAULT_MIN_CUTOFF,
        beta: float = DEFAULT_BETA,
        d_cutoff: float = DEFAULT_D_CUTOFF,
    ) -> None:
        if min_cutoff <= 0 or d_cutoff <= 0 or beta < 0:
            raise ValueError("min_cutoff e d_cutoff > 0, beta >= 0")
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self._x = LowPass()
        self._dx = LowPass()
        self._t: float | None = None

    def reset(self) -> None:
        self._x = LowPass()
        self._dx = LowPass()
        self._t = None

    def filter(self, x: float, t: float) -> float:
        if self._t is None or t <= self._t:
            # primo campione, o tempo che non avanza (pacchetto duplicato/riordinato): niente derivata
            self._t = t if self._t is None else self._t
            self._dx.filter(0.0, 1.0)
            return self._x.filter(x, 1.0)
        dt = t - self._t
        self._t = t
        prev = self._x.value if self._x.value is not None else x
        dx = (x - prev) / dt
        edx = self._dx.filter(dx, _alpha(self.d_cutoff, dt))
        cutoff = self.min_cutoff + self.beta * abs(edx)
        return self._x.filter(x, _alpha(cutoff, dt))


class OneEuroVec3:
    def __init__(
        self,
        min_cutoff: float = DEFAULT_MIN_CUTOFF,
        beta: float = DEFAULT_BETA,
        d_cutoff: float = DEFAULT_D_CUTOFF,
    ) -> None:
        self._f = [OneEuro(min_cutoff, beta, d_cutoff) for _ in range(3)]

    def reset(self) -> None:
        for f in self._f:
            f.reset()

    def filter(self, v: Vec3, t: float) -> Vec3:
        return (self._f[0].filter(v[0], t), self._f[1].filter(v[1], t), self._f[2].filter(v[2], t))


class OneEuroQuat:
    """One Euro sul quaternione: le 4 componenti con lo STESSO alpha (dalla velocita' angolare), poi normalizza.

    Prima di filtrare il campione si porta nello stesso emisfero dell'uscita precedente (q e -q sono la stessa
    rotazione): senza, il filtro passerebbe per lo zero.
    """

    def __init__(
        self,
        min_cutoff: float = DEFAULT_MIN_CUTOFF,
        beta: float = DEFAULT_BETA,
        d_cutoff: float = DEFAULT_D_CUTOFF,
    ) -> None:
        if min_cutoff <= 0 or d_cutoff <= 0 or beta < 0:
            raise ValueError("min_cutoff e d_cutoff > 0, beta >= 0")
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self._q: Quat | None = None
        self._dq = LowPass()
        self._t: float | None = None

    def reset(self) -> None:
        self._q = None
        self._dq = LowPass()
        self._t = None

    def filter(self, q: Quat, t: float) -> Quat:
        q = quat_normalize(q)
        if self._q is None or self._t is None or t <= self._t:
            if self._q is None:
                self._q = q
                self._t = t
            return self._q
        if quat_dot(q, self._q) < 0.0:
            q = (-q[0], -q[1], -q[2], -q[3])
        dt = t - self._t
        self._t = t
        # velocita' angolare approssimata: 2*|q - q_prev| / dt (vale per piccoli angoli, basta per il cutoff)
        diff = math.sqrt(sum((q[i] - self._q[i]) ** 2 for i in range(4)))
        speed = 2.0 * diff / dt
        espeed = self._dq.filter(speed, _alpha(self.d_cutoff, dt))
        a = _alpha(self.min_cutoff + self.beta * espeed, dt)
        p = self._q
        self._q = quat_normalize(
            (
                a * q[0] + (1.0 - a) * p[0],
                a * q[1] + (1.0 - a) * p[1],
                a * q[2] + (1.0 - a) * p[2],
                a * q[3] + (1.0 - a) * p[3],
            )
        )
        return self._q
