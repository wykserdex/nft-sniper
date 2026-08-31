# Контекст: alerts

Матчинг листингов с настройками пользователей, дедупликация, rate limit,
quiet hours, приоритизация (сначала лучшие сделки). Решения пользователя
(taken/skipped/watch/muted) записываются для калибровки модели.

## Что готово

- **Домен** (`domain/alert.py`): Alert, Decision, AlertButton (callback или url),
  AlertMessage, AlertPolicy (условия алерта ТЗ §4). Кнопка-ссылка — диплинк
  на маркетплейс (ТЗ §1: «Взять» не покупает).
- **Порты** (`ports/__init__.py`): NotifierPort (send/edit), AlertRepository,
  DecisionRepository.
- **Адаптер Telegram** (`adapters/telegram/notifier.py`): `TelegramNotifier` —
  отправка и редактирование алертов (parse_mode HTML), `build_inline_keyboard`.

Рендер алерта (формат ТЗ §1) и кнопки-решения — в `entrypoints/bot/`
(render.py, service.py, handlers.py): бот строит AlertMessage и передаёт
нотификатору, а после решения — редактирует сообщение (ТЗ §6).

## Дальше (11)

- матчинг листингов с `UserSettings.alert_policy()` (бот уже умеет их хранить);
- дедупликация, rate limit, quiet hours, приоритизация;
- запись решений в Postgres и калибровка порогов.
