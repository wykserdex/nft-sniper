"""Локализация бота (RU/EN) — ТЗ §7,.

Строки собраны в каталог, чтобы рендер и хендлеры не хранили текст внутри.
``Lang = "ru" | "en"``.
"""

from typing import Literal

Lang = Literal["ru", "en"]

LANGUAGES: tuple[Lang, ...] = ("ru", "en")


class _Strings:
    """Один язык. Поля — строки-шаблоны (``{name}`` — подстановки)."""

    # Все поля объявлены явно, чтобы mypy strict видел атрибуты каталога.
    start: str
    help: str
    unknown_command: str
    settings_title: str
    settings_line_discount: str
    settings_line_confidence: str
    settings_line_price: str
    settings_line_liquidity: str
    settings_line_risk: str
    settings_line_lang: str
    settings_prompt: str
    btn_edit_discount: str
    btn_edit_confidence: str
    btn_edit_price_min: str
    btn_edit_price_max: str
    btn_edit_liquidity: str
    btn_edit_risk: str
    btn_toggle_lang: str
    btn_done: str
    ask_discount: str
    ask_confidence: str
    ask_price_min: str
    ask_price_max: str
    ask_liquidity: str
    ask_risk: str
    bad_value: str
    settings_saved: str
    settings_cancelled: str
    watchlist_empty: str
    watchlist_title: str
    watchlist_added: str
    watchlist_line: str
    mute_empty: str
    mute_title: str
    mute_line: str
    mute_done: str
    mute_already: str
    unmute_hint: str
    paused: str
    resumed: str
    no_change: str
    stats_title: str
    stats_lines: str
    no_stats: str
    decided_taken: str
    decided_skipped: str
    decided_watch: str
    decided_muted: str
    decided_unknown: str
    take_link_hint: str
    deal_title: str
    line_collection: str
    line_price: str
    line_price_no_usd: str
    line_fair: str
    line_discount: str
    line_floor: str
    line_median: str
    line_rarity: str
    line_liquidity: str
    line_age: str
    line_confidence: str
    flag_warning: str
    confidence_high: str
    confidence_medium: str
    confidence_low: str
    age_sec: str
    age_min: str
    age_hour: str
    age_day: str
    btn_take: str
    btn_skip: str
    btn_watch: str
    btn_mute: str
    btn_open: str

    def __init__(self, **texts: str) -> None:
        for key, value in texts.items():
            setattr(self, key, value)


RU = _Strings(
    # ── команды ─────────────────────────────────────────────────────────
    start=(
        "👋 Привет! Я ищу недооценённые NFT на TON.\n\n"
        "Я ничего не покупаю: нахожу, оцениваю, объясняю и спрашиваю. "
        "Решение всегда за тобой.\n\n"
        "/settings — пороги и язык\n"
        "/watchlist — что отслеживаем\n"
        "/stats — качество алертов\n"
        "/mute — заглушить коллекцию\n"
        "/pause — поставить на паузу\n"
        "/help — справка"
    ),
    help=(
        "Каждый алерт — это сделка с дискаунтом от справедливой цены.\n\n"
        "Кнопки:\n"
        "✅ Взять — диплинк на маркетплейс (я не покупаю)\n"
        "❌ Скип — не интересно\n"
        "🔔 Следить — в вотчлист\n"
        "🔇 Мьют — заглушить коллекцию\n\n"
        "Пороги настраиваются в /settings."
    ),
    unknown_command="Не понял команду. Попробуй /help.",
    # ── настройки ───────────────────────────────────────────────────────
    settings_title="⚙️ Настройки",
    settings_line_discount="Дискаунт от: {value}%",
    settings_line_confidence="Уверенность от: {value}",
    settings_line_price="Цена: {min}–{max} TON",
    settings_line_liquidity="Ликвидность от: {value}",
    settings_line_risk="Риск не выше: {value}",
    settings_line_lang="Язык: {value}",
    settings_prompt=(
        "Текущие настройки:\n"
        "{discount}\n{confidence}\n{price}\n{liquidity}\n{risk}\n{lang}\n\n"
        "Нажми, что изменить."
    ),
    btn_edit_discount="Дискаунт",
    btn_edit_confidence="Уверенность",
    btn_edit_price_min="Мин. цена",
    btn_edit_price_max="Макс. цена",
    btn_edit_liquidity="Ликвидность",
    btn_edit_risk="Риск",
    btn_toggle_lang="Язык: {value}",
    btn_done="Готово",
    ask_discount="Новый порог дискаунта в % (например 25):",
    ask_confidence="Новый порог уверенности от 0 до 1 (например 0.5):",
    ask_price_min="Минимальная цена в TON (например 10):",
    ask_price_max="Максимальная цена в TON (например 500):",
    ask_liquidity="Минимальная ликвидность от 0 до 1 (например 0.2):",
    ask_risk="Максимальный риск от 0 до 1 (например 0.7):",
    bad_value="Не получилось: {error}\nПопробуй ещё раз или /cancel.",
    settings_saved="✅ Настройки сохранены.",
    settings_cancelled="Отменено. Текущие настройки: /settings",
    # ── вотчлист / мьют / пауза / статы ──────────────────────────────────
    watchlist_empty="Вотчлист пуст. Жми «🔔 Следить» в алерте.",
    watchlist_title="🔔 Вотчлист:",
    watchlist_added="🔔 Добавил в вотчлист: {item}",
    watchlist_line="• {item}",
    mute_empty="Заглушённых коллекций нет.",
    mute_title="🔇 Заглушённые коллекции:",
    mute_line="• {collection}",
    mute_done="🔇 Коллекция заглушена: {collection}",
    mute_already="Коллекция уже была заглушена.",
    unmute_hint="Снять мьют — в /settings (позже) или напиши в поддержку.",
    paused="⏸ Алерты на паузе. /resume — продолжить.",
    resumed="▶️ Алерты возобновлены.",
    no_change="Ничего не изменилось.",
    stats_title="📊 Статистика",
    stats_lines=(
        "Алертов отправлено: {sent}\n"
        "Взято (take rate): {taken}/{sent} ({rate}%)\n"
        "Скипнуто: {skipped}\n"
        "На паузе: {paused}"
    ),
    no_stats="Статистики пока нет — жди первых алертов.",
    # ── решения по алерту ───────────────────────────────────────────────
    decided_taken="✅ Взял. Открываю маркетплейс:\n{link}",
    decided_skipped="❌ Скипнуто.",
    decided_watch="🔔 Слежу за этим предметом.",
    decided_muted="🔇 Коллекция заглушена.",
    decided_unknown="Решение записано.",
    take_link_hint="Я не покупаю — это диплинк на маркетплейс. Решение за тобой.",
    # ── рендер алерта ───────────────────────────────────────────────────
    deal_title="🔥 Deal {discount}",
    line_collection="Коллекция: {name}",
    line_price="Цена: {price} TON ({usd})",
    line_price_no_usd="Цена: {price} TON",
    line_fair="Fair price: {fair} TON",
    line_discount="Дискаунт: {discount}",
    line_floor="Floor: {floor} TON (24h: {change})",
    line_median="Median 7d: {median} TON ({sales} продаж)",
    line_rarity="Rarity: топ {pct} по коллекции",
    line_liquidity="Ликвидность: {spd} продаж/день",
    line_age="Возраст листинга: {age}",
    line_confidence="Уверенность оценки: {confidence} ({label})",
    flag_warning="⚠️ Флаг: {flag}",
    confidence_high="высокая",
    confidence_medium="средняя",
    confidence_low="низкая",
    age_sec="{n} сек",
    age_min="{n} мин",
    age_hour="{n} ч",
    age_day="{n} дн",
    btn_take="✅ Взять",
    btn_skip="❌ Скип",
    btn_watch="🔔 Следить",
    btn_mute="🔇 Мьют коллекции",
    btn_open="🔗 Открыть на GetGems",
)

EN = _Strings(
    start=(
        "👋 Hi! I hunt undervalued NFTs on TON.\n\n"
        "I never buy: I find, value, explain and ask. "
        "The decision is always yours.\n\n"
        "/settings — thresholds & language\n"
        "/watchlist — tracked items\n"
        "/stats — alert quality\n"
        "/mute — mute a collection\n"
        "/pause — pause alerts\n"
        "/help — help"
    ),
    help=(
        "Every alert is a deal below fair price.\n\n"
        "Buttons:\n"
        "✅ Take — deep link to the marketplace (I don't buy)\n"
        "❌ Skip — not interested\n"
        "🔔 Watch — add to watchlist\n"
        "🔇 Mute — mute the collection\n\n"
        "Tune thresholds in /settings."
    ),
    unknown_command="Didn't get that. Try /help.",
    settings_title="⚙️ Settings",
    settings_line_discount="Min discount: {value}%",
    settings_line_confidence="Min confidence: {value}",
    settings_line_price="Price: {min}–{max} TON",
    settings_line_liquidity="Min liquidity: {value}",
    settings_line_risk="Max risk: {value}",
    settings_line_lang="Language: {value}",
    settings_prompt=(
        "Current settings:\n"
        "{discount}\n{confidence}\n{price}\n{liquidity}\n{risk}\n{lang}\n\n"
        "Tap a field to edit it."
    ),
    btn_edit_discount="Discount",
    btn_edit_confidence="Confidence",
    btn_edit_price_min="Min price",
    btn_edit_price_max="Max price",
    btn_edit_liquidity="Liquidity",
    btn_edit_risk="Risk",
    btn_toggle_lang="Language: {value}",
    btn_done="Done",
    ask_discount="New discount threshold in % (e.g. 25):",
    ask_confidence="New confidence threshold, 0..1 (e.g. 0.5):",
    ask_price_min="Minimum price in TON (e.g. 10):",
    ask_price_max="Maximum price in TON (e.g. 500):",
    ask_liquidity="Minimum liquidity, 0..1 (e.g. 0.2):",
    ask_risk="Maximum risk, 0..1 (e.g. 0.7):",
    bad_value="That didn't work: {error}\nTry again, or /cancel.",
    settings_saved="✅ Settings saved.",
    settings_cancelled="Cancelled. Current settings: /settings",
    watchlist_empty="Watchlist is empty. Tap «🔔 Watch» on an alert.",
    watchlist_title="🔔 Watchlist:",
    watchlist_added="🔔 Added to watchlist: {item}",
    watchlist_line="• {item}",
    mute_empty="No muted collections.",
    mute_title="🔇 Muted collections:",
    mute_line="• {collection}",
    mute_done="🔇 Collection muted: {collection}",
    mute_already="This collection was already muted.",
    unmute_hint="To unmute, use /settings (later) or contact support.",
    paused="⏸ Alerts paused. /resume to continue.",
    resumed="▶️ Alerts resumed.",
    no_change="Nothing changed.",
    stats_title="📊 Statistics",
    stats_lines=(
        "Alerts sent: {sent}\n"
        "Taken (take rate): {taken}/{sent} ({rate}%)\n"
        "Skipped: {skipped}\n"
        "Paused: {paused}"
    ),
    no_stats="No stats yet — wait for the first alerts.",
    decided_taken="✅ Taken. Opening the marketplace:\n{link}",
    decided_skipped="❌ Skipped.",
    decided_watch="🔔 Watching this item.",
    decided_muted="🔇 Collection muted.",
    decided_unknown="Decision recorded.",
    take_link_hint="I don't buy — this is a marketplace deep link. Your call.",
    deal_title="🔥 Deal {discount}",
    line_collection="Collection: {name}",
    line_price="Price: {price} TON ({usd})",
    line_price_no_usd="Price: {price} TON",
    line_fair="Fair price: {fair} TON",
    line_discount="Discount: {discount}",
    line_floor="Floor: {floor} TON (24h: {change})",
    line_median="Median 7d: {median} TON ({sales} sales)",
    line_rarity="Rarity: top {pct} of collection",
    line_liquidity="Liquidity: {spd} sales/day",
    line_age="Listing age: {age}",
    line_confidence="Valuation confidence: {confidence} ({label})",
    flag_warning="⚠️ Flag: {flag}",
    confidence_high="high",
    confidence_medium="medium",
    confidence_low="low",
    age_sec="{n} sec",
    age_min="{n} min",
    age_hour="{n} h",
    age_day="{n} d",
    btn_take="✅ Take",
    btn_skip="❌ Skip",
    btn_watch="🔔 Watch",
    btn_mute="🔇 Mute collection",
    btn_open="🔗 Open on GetGems",
)


def get_strings(lang: str) -> _Strings:
    """Каталог по языку; неизвестный → ru."""
    return RU if lang == "ru" else EN
