"""Ошибки адаптера TonAPI.

Транспортные ошибки (httpx, таймауты) и ``CircuitBreakerOpenError`` сюда не
оборачиваются: их уже несёт ``ResilientHttpClient``, и конвейер различает
«источник недоступен» (breaker) и «источник ответил ошибкой» (здесь).
"""


class TonapiError(RuntimeError):
    """Базовая ошибка источника TonAPI."""


class TonapiResponseError(TonapiError):
    """Ответ не в ожидаемой форме: не JSON-объект или отсутствуют нужные поля."""
