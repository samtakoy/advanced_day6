"""Scenario bank — fuel for synthetic generation.

Each list is a pool of scenario ideas the generator can pick from. The generator
combines a random scenario with a random `variation` (module/library names) to
produce a unique training example.

Keep ideas short; the meta-prompt expects 1-2 sentences.
"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentScenarioSeed:
    type: str  # develop | refactor | bugfix | research | tests
    scenario: str  # 1-2 sentence hint for the user message


# ------------------------------------------------------------------
# DEVELOP (feature / add / create) — 12 in the target dataset
# ------------------------------------------------------------------
DEVELOP: list[str] = [
    "Добавь зависимость ktor-client-content-negotiation в модуль core-network (commonMain).",
    "Подключи SQLDelight-плагин в build.gradle.kts feature-storage и настрой sourceSet для схемы.",
    "Создай data class Quote (id, symbol, price, timestamp) в domain/model нового фича-модуля feature-quotes.",
    "Добавь настройку DarkTheme в SettingsStore — нужна новая Intent и соответствующий Reducer-case.",
    "Создай новый feature-модуль feature-favorites (gradle + src/commonMain) с пустым Component и Store.",
    "Добавь строковый ресурс loading_error в compose-resources commonMain.",
    "Создай expect fun getDeviceTimezone(): String в core/platform и actual для android/ios.",
    "Добавь поддержку wasmJs таргета в build.gradle.kts модуля core-features/stocks.",
    "Создай UseCase ArchiveTickerUseCase: принимает tickerId, зовёт TickerRepository.archive(id).",
    "Добавь в Koin-модуль core-networkModule factory для нового HttpClient c BearerAuth.",
    "Создай Composable EmptyStateView(text, actionLabel, onAction) в core/uikit/empty.",
    "Создай entity WatchlistEntity (+column adapters) в SQLDelight схеме модуля core-db.",
    "Добавь pull-to-refresh в ExistingFeedScreen — нужно прокинуть onRefresh через Component.",
]


# ------------------------------------------------------------------
# REFACTOR — 6 in target. Always include "no-op" possibility in the scenario.
# ------------------------------------------------------------------
REFACTOR: list[str] = [
    "Проверь файл core/network/KtorClientBuilder.kt на прямое использование Dispatchers.* (anti-pattern) и замени на DispatcherProvider, если есть.",
    "Замени все обращения к legacyDateFormatter() в core/utils/DateUtils.kt на kotlinx-datetime (если такие есть).",
    "Вынеси дублирующуюся логику extension-функций из feature-auth и feature-profile в общий utils/StringExt.kt.",
    "Проверь feature-chart на использование устаревшей androidx.compose.foundation.Canvas и переведи на более новый DrawScope API, если используется.",
    "Замени все @Singleton-аннотации в core-db на Koin `single { }` декларации (если найдутся).",
    "Убери deprecated-обращения к Compose Material 2 в feature-settings, заменив на Material 3 (если есть).",
    "Переименуй parameter name `id` на `tickerId` в функциях TickerRepository — если найдешь в реализации, но только если интерфейс тоже поддерживает.",
]


# ------------------------------------------------------------------
# BUGFIX — 6 in target
# ------------------------------------------------------------------
BUGFIX: list[str] = [
    "Bug: В feature-quotes/QuotesScreen.kt LazyColumn не показывает последний элемент за счёт неверного contentPadding. Найди и поправь.",
    "Bug: В PriceTicker.kt колонка цены рендерится с maxLines=2 — нужно заменить на 1 и добавить overflow=Ellipsis.",
    "Bug: в core/network/ApiErrorInterceptor.kt перехватчик игнорирует код 401 — добавь обработку, которая вызывает AuthRepository.logout().",
    "Bug: В NotificationsStore reducer при MarkAllRead не обнуляет поле unreadCount. Исправь.",
    "Bug: функция formatPrice() в core/utils/PriceFormatter.kt роняет NPE на null. Добавь безопасный fallback.",
    "Bug: expect fun pasteFromClipboard в ClipboardHelper.kt компилируется, но actual в iosMain возвращает пустую строку — нужно прокинуть UIPasteboard.",
    "Bug: forwardRef в feature-chat/ChatViewModel.kt утекает контекст — убери явный this@Chat и используй scope напрямую.",
]


# ------------------------------------------------------------------
# RESEARCH / DOCS — 8 in target. All read-only + write_file final doc.
# ------------------------------------------------------------------
RESEARCH: list[str] = [
    "Research: построй карту UseCase/Repository подмодуля notifications — сохраняй в docs/notifications-map.md.",
    "Research: перечисли все Koin-модули проекта (файлы DI) и пересечения имён. Результат — docs/koin-modules-inventory.md.",
    "Research: оцени, какие commonMain-классы в feature-auth используют java-API (должны только kotlinx/ktx). Результат — docs/feature-auth-kmp-safety.md.",
    "Research: собери все @Serializable data class в core-network и перечисли их поля. Итог — docs/network-dtos.md.",
    "Docs: напиши docs/mvikotlin-store-conventions.md — правила именования Intent/Action/Msg/State на основе существующих Store в feature-*.",
    "Research: посмотри какие тесты в commonTest проверяют Flow и документируй используемые turbine-паттерны в docs/testing-flow-patterns.md.",
    "Research: перечисли все PUBLIC API функции core/uikit, которые принимают Modifier как первый именной параметр (а должны — как последний). Итог — docs/uikit-modifier-audit.md.",
    "Docs: создай docs/adding-new-feature-module.md с чеклистом: gradle → Component → Store → UI → Koin → навигация (на основе feature-settings как эталона).",
    "Research: оцени, есть ли в проекте дубли sealed-классов для результатов операций (Success/Failure/Loading). Результат — docs/result-types-audit.md.",
]


# ------------------------------------------------------------------
# TESTS — 3 in target
# ------------------------------------------------------------------
TESTS: list[str] = [
    "Напиши unit-тест для GetWatchlistUseCase: 2 сценария (репозиторий вернул список / вернул пустой). Правила из .claude/rules/testing.md (Mokkery + Turbine + runTest).",
    "Напиши unit-тест для PriceFormatter.formatPrice(): кейсы — обычное число, ноль, null, отрицательное. kotlin.test + assertEquals, без моков.",
    "Напиши unit-тест для NotificationsStore reducer: MarkAllRead изменяет unreadCount=0; NewNotification добавляет элемент в начало списка. Проверка через Turbine test { }.",
    "Напиши unit-тест для MarketMapper.toDomain(MarketDto): правильные поля маппятся, null-title выкидывает IllegalArgumentException.",
]


# ------------------------------------------------------------------
# QUESTION (ambiguity axes) — 8 in target (we already have 1 seed)
# ------------------------------------------------------------------
# Each entry = (ambiguity_axis, user_request_hint)
QUESTION_AXES = [
    ("library_choice", "Добавь логирование в shared модуль."),
    ("library_choice", "Нужен кеш для HTTP-ответов в клиенте."),
    ("target_module", "Поправь экран настроек — там какая-то ерунда с переключателем."),
    ("target_module", "В UI почему-то не работает drag'n'drop."),
    ("scope_breadth", "Переведи весь проект на Coroutines-Flow v2."),
    ("format", "Сделай импорт/экспорт настроек — хочу поделиться с коллегой."),
    ("behavior", "Сделай чтобы на iPad выглядело как-то иначе."),
    ("priority", "Ускорь запуск приложения, но сохрани все существующие анимации и переходы."),
]


# ------------------------------------------------------------------
# PLAIN (conceptual Q&A) — 7 in target (we already have 1 seed)
# ------------------------------------------------------------------
# Each entry = (topic, angle)
PLAIN_TOPICS = [
    ("kmp_architecture", "Когда стоит использовать expect/actual, а когда intermediate source sets с hierarchical setup?"),
    ("compose_multiplatform", "Как правильно делить UI на platform-specific composables и общие компоненты в Compose Multiplatform?"),
    ("gradle_kmp", "Зачем нужен libs.versions.toml и чем он лучше плоских version catalogs в Groovy?"),
    ("coroutines_flow", "В чём реальная разница между SharedFlow и StateFlow для UI-ViewModel?"),
    ("serialization", "Как настроить Polymorphic serialization в kotlinx-serialization с sealed-иерархией?"),
    ("di_koin", "Как правильно собирать Koin-модули в KMP так, чтобы они работали и на Android, и на iOS?"),
    ("testing", "Чем Mokkery лучше MockK/Mockito для KMP и в каких случаях использовать Turbine вместо собственных collect-хелперов?"),
    ("sqldelight", "Как версионировать SQLDelight-схему и делать миграции без потери данных?"),
    ("decompose_mvikotlin", "Зачем Decompose Component, если уже есть MVIKotlin Store — не дублирует ли это функциональность?"),
]


# ------------------------------------------------------------------
# VARIATION POOLS — kick the generator to use different names
# ------------------------------------------------------------------

MODULE_NAMES = [
    "feature-quotes", "feature-watchlist", "feature-news", "feature-alerts",
    "feature-portfolio", "feature-charts", "feature-auth", "feature-settings",
    "core-network", "core-db", "core-uikit", "core-utils", "core-analytics",
    "core-features/stocks", "core-features/prices", "core-features/users",
    "shared",
]

LIBRARY_NAMES = [
    "ktor-client-core", "ktor-client-content-negotiation", "ktor-client-auth",
    "kotlinx-serialization-json", "kotlinx-datetime", "kotlinx-coroutines-core",
    "sqldelight-runtime", "sqldelight-coroutines-extensions",
    "koin-core", "koin-compose",
    "decompose", "mvikotlin", "mvikotlin-extensions-coroutines",
    "compose-material3", "compose-foundation", "compose-resources",
    "turbine", "mokkery",
]

INDENTATION_STYLES = ["4 пробела", "2 пробела", "tab"]


def pick_variation(rng: random.Random) -> str:
    """Build a short variation hint string."""
    module = rng.choice(MODULE_NAMES)
    lib = rng.choice(LIBRARY_NAMES)
    indent = rng.choice(INDENTATION_STYLES)
    return (
        f"модуль: {module}; упомянуть библиотеку {lib} где уместно; "
        f"отступ в гипотетических файлах: {indent}; "
        f"имена классов и файлов выбирай свежие, не копируй из референса"
    )
