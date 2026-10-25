"""One Euro filter (Casiez, Roussel, Vogel 2012): smooths jitter when still, keeps lag low when moving.

    cutoff = min_cutoff + beta * |speed|

Still hand -> low cutoff -> heavy smoothing. Fast swipe -> high cutoff -> follows closely.
Tune: raise min_cutoff if it feels laggy at rest, raise beta if fast moves lag behind.
"""

import math


class OneEuroFilter:
    """Filters one scalar signal sampled at irregular times (seconds)."""

    def __init__(self, min_cutoff=1.0, beta=0.0, d_cutoff=1.0):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self.reset()

    def reset(self):
        self._x = None
        self._dx = 0.0
        self._t = None

    @staticmethod
    def _alpha(cutoff, dt):
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def __call__(self, x, t):
        if self._x is None:
            self._x, self._t = x, t
            return x
        dt = t - self._t
        if dt <= 0:  # duplicate or out-of-order sample: keep the last estimate
            return self._x

        a_d = self._alpha(self.d_cutoff, dt)
        self._dx = a_d * (x - self._x) / dt + (1 - a_d) * self._dx

        cutoff = self.min_cutoff + self.beta * abs(self._dx)
        a = self._alpha(cutoff, dt)
        self._x = a * x + (1 - a) * self._x
        self._t = t
        return self._x
