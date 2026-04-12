from __future__ import annotations
import random


class ExponentialBackoff:
    """
    Exponential backoff with full jitter.

    Sequence (initial=1, factor=2, cap=30, jitter=0.5):
        1*[0.5..1.0], 2*[0.5..1.0], 4*[0.5..1.0], 8*[0.5..1.0], 16*[0.5..1.0],
        30*[0.5..1.0], 30*[0.5..1.0], ...

    reset() returns the backoff to its initial value — call this after a successful
    operation so the next failure starts from the bottom rather than the cap.
    """

    def __init__(
        self,
        initial: float = 1.0,
        factor: float = 2.0,
        cap: float = 60.0,
        jitter: float = 0.5,
    ) -> None:
        if initial <= 0 or factor <= 1 or cap < initial or not (0.0 <= jitter <= 1.0):
            raise ValueError(
                f"invalid backoff: initial={initial} factor={factor} cap={cap} jitter={jitter}"
            )
        self._initial = initial
        self._factor = factor
        self._cap = cap
        self._jitter = jitter
        self._current = initial

    def reset(self) -> None:
        self._current = self._initial

    def next(self) -> float:
        delay = self._current
        # Apply full jitter — sample uniformly from [(1-jitter)*delay, delay]
        low = (1.0 - self._jitter) * delay
        sampled = random.uniform(low, delay)
        # Advance for next call
        self._current = min(self._current * self._factor, self._cap)
        return sampled

    @property
    def current(self) -> float:
        return self._current
