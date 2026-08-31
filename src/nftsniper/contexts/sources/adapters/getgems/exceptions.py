"""Ошибки адаптера GetGems.

Транспортные ошибки (httpx, таймауты) и CircuitBreakerOpenError сюда не
оборачиваются: их уже несёт ResilientHttpClient, и конвейер различает
«источник недоступен» (breaker) и «источник ответил ошибкой» (здесь).
"""


class GetGemsError(RuntimeError):
    """Базовая ошибка источника GetGems."""


class GetGemsGraphQLError(GetGemsError):
    """GraphQL вернул поле ``errors`` (плохой запрос, лимит, недоступные данные)."""

    def __init__(self, errors: list[object]) -> None:
        super().__init__(f"GetGems GraphQL вернул ошибки: {errors}")
        self.errors = errors


class GetGemsResponseError(GetGemsError):
    """Ответ не в ожидаемой форме: не JSON-объект или отсутствует ``data``."""
