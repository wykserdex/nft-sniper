"""Минимальный circuit breaker.

Состояния: ``closed`` → (N подряд неудач) → ``open`` → (ожидание recovery_timeout)
→ ``half_open`` → успех → ``closed`` / неудача → ``open``.

Нужен, чтобы один упавший внешний источник (GetGems, TonAPI, Fragment)
не тянул за собой всё: запросы «в открываш» падают мгновенно, а источник
получает паузу на восстановление.
"""

import time
from collections.abc import Awaitable, Callable
from typing import Literal, TypeVar

T = TypeVar("T")

CircuitState = Literal["closed", "open", "half_open"]


class CircuitBreakerOpenError(RuntimeError):
    """Запрос отклонён: breaker открыт, источник считается недоступным."""


class CircuitBreaker:
    def __init__(self, *, failure_threshold: int = 5, recovery_timeout: float = 30.0) -> None:
        if failure_threshold < 1:
            msg = "failure_threshold должен быть >= 1"
            raise ValueError(msg)
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._failure_count = 0
        self._opened_at: float | None = None
        self._state: CircuitState = "closed"

    @property
    def state(self) -> str:
        """Текущее состояние: "closed" | "open" | "half_open"."""
        return self._state

    async def call(self, func: Callable[[], Awaitable[T]]) -> T:
        """Выполняет ``func`` под защитой breaker'а, передавая исключения наружу."""
        self._trip_if_recoverable()
        if self._state == "open":
            raise CircuitBreakerOpenError(
                f"circuit breaker open: неудач подряд {self._failure_count}, "
                f"восстановление через {self._recovery_timeout:.1f} c"
            )
        try:
            result = await func()
        except Exception:
            self._record_failure()
            raise
        self._record_success()
        return result

    def _trip_if_recoverable(self) -> None:
        if (
            self._state == "open"
            and self._opened_at is not None
            and time.monotonic() - self._opened_at >= self._recovery_timeout
        ):
            self._state = "half_open"

    def _record_failure(self) -> None:
        self._failure_count += 1
        if self._state == "half_open" or self._failure_count >= self._failure_threshold:
            self._state = "open"
            self._opened_at = time.monotonic()

    def _record_success(self) -> None:
        self._failure_count = 0
        self._opened_at = None
        self._state = "closed"
