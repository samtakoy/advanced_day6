# Tasks 2 — seed-задачи для датасета экстракции

Продолжение `tasks.md`, задачи 26–50. Формат — **Slack-тикет**, не план работы: 150–250 токенов прозой, без шаблонных секций `Scope/Out of scope/Критерии`. Нужно как основа gold-разметки для дня 6 (fine-tune экстрактора).

Часть задач намеренно написана **неполно** — без явных критериев, без out-of-scope, без упоминания зависимостей. Это реалистичное распределение тикетов и обучающий сигнал «если в тексте нет — возвращай пустой массив, не выдумывай».

---

## Блок A. Workspace foundation

### 26. Templates воркспейсов

Хочу сделать шаблоны воркспейсов — предустановленные наборы для быстрого старта. Например: шаблон «Российские blue chips» создаёт воркспейс с 4 слотами (GAZP/SBER/LKOH/GMKN), период D1, базовый набор индикаторов SMA20+SMA50. Пользователь открывает приложение первый раз → экран онбординга с выбором из 3–4 шаблонов → жмёт → воркспейс готов.

Сами шаблоны хардкодим как seed-данные в `core-features/workspaces` — отдельная ресурсная папка с JSON, рядом с presets MOEX. Use case `CreateWorkspaceFromTemplate(templateId)`, который дёргает `CreateWorkspaceUseCase` + `AddChartSlotUseCase` в цикле + пачку `UpsertIndicatorConfig`. UI выбора — bottom sheet в `features/main`, пункт «Новый из шаблона» рядом с «Создать пустой».

Нужна задача 5 (CRUD слотов) и 7 (IndicatorConfig) — без них шаблону нечего создавать.

Критерий приёмки: на пустой БД выбираем шаблон Blue chips → появляется воркспейс с 4 слотами и индикаторами, после рестарта всё на месте. Компиляция зелёная, smoke добавлен.

Не трогаем cloud-sync шаблонов (это задача 21) и пользовательские шаблоны («сохранить текущий workspace как template») — только встроенные.

---

### 27. Split-screen ChartSlot

Идея: один слот — два графика рядом. Хочу сравнивать GAZP и LKOH глазами, не переключаясь между страницами карусели. Архитектурно — либо расширить `ChartSlot` вторым `secondaryTickerId`, либо завести отдельную таблицу `SlotPane`, решить по ходу. Затронет миграцию БД (`core/db`), `core-features/workspaces`, `features/main`, видимо сам рендер в `features-api/chart`.

Пока делаем только вертикальный split — второй график под первым. Горизонтальный (рядом) пусть будет следом, отдельным тикетом.

Критерии не продумал, обсудим когда заведёт. Главное чтобы работало и переживало рестарт.

---

### 28. Теги и цветовая группировка воркспейсов

Когда воркспейсов 10+ — карусель превращается в кашу. Хочу раскрашивать воркспейсы по категориям: «крипта» синим, «акции РФ» зелёным, «эксперименты» серым. Чтобы визуально отличать на индикаторе страниц.

БД: `WorkspaceTag(id, workspaceId, color, label)` в `core/db`, FK на Workspace. Модель в `core-features/workspaces`, use case `SetWorkspaceTagUseCase`, `RemoveTagUseCase`. В карусели `features/main` — цветная полоска снизу под активной точкой индикатора. Редактирование тега — в `WorkspaceEditorComponent` (там уже есть rename/delete из задачи 5).

Зависит от задачи 5 — редактор воркспейса должен уже существовать.

Приёмка: на двух воркспейсах задать разные теги → индикатор страниц визуально отличает; после рестарта теги на месте; smoke проходит.

---

### 29. Синхронизация viewport между слотами одного workspace

На воркспейсе с 4 слотами хочу режим «все графики показывают один временной диапазон». Скроллю один — двигаются остальные. Удобно для сравнения поведения разных тикеров в один период.

В `Workspace` добавить поле `viewportMode: Independent | Synced`, дефолт `Independent` (текущее поведение). Когда `Synced` — viewport хранится **на Workspace**, не на каждом `ChartSlot`. В `UpdateSlotViewportUseCase` из задачи 4 — ветка: если synced, пишем в `Workspace.viewport` и нотифицируем соседние слоты через общий Flow. `viewportMode` — миграция `core/db`, затронет `core-features/workspaces`, `features/main`.

Нужна задача 4 (ChartSlot с viewport).

Приёмка: переключаем режим в редакторе воркспейса → скролл одного графика двигает все остальные; после рестарта режим помнится; Independent работает как раньше. Компиляция зелёная.

Не делаем синхронизацию между **разными** воркспейсами — только внутри одного.

---

## Блок B. Indicators

### 30. Custom indicator formula DSL

Движок индикаторов (задача 6) сейчас позволяет только встроенные SMA/EMA/RSI и т.д. Хочу дать пользователю выражения: `SMA(close, 20) - SMA(close, 50)` или `(high - low) / close * 100`. Парсер выражений → AST → executor, который при вычислении дёргает уже существующие калькуляторы из `IndicatorCatalog`.

Архитектурно: в `core-features/indicators` новые модели `CustomIndicatorDefinition(id, title, formula, paramsSpec)`, отдельный модуль `parser` (lexer + recursive descent), `FormulaCalculator : IndicatorCalculator`, который реализует `calculate(candles, params)` через AST. Кэш `IndicatorCache` переиспользуется как есть — ключ по hash формулы.

UI создания/редактирования формулы — на экране IndicatorPicker из задачи 7, отдельный таб «Своя формула». Просто `TextField` + preview на последних 100 свечах.

Зависит от задач 6 и 7.

Приёмка: юнит-тесты на парсер (≥10 кейсов: приоритеты операций, скобки, ошибки синтаксиса); создаём формулу `EMA(close,12) - EMA(close,26)` → рисуется overlay, значения совпадают с ручным MACD-like подсчётом; невалидная формула → ошибка с указанием позиции. Smoke добавить.

Не делаем циклы/ветвления в DSL — только арифметика и вызовы встроенных функций. Не трогаем готовые индикаторы.

---

### 31. Параметр-свипер одного индикатора

Хочу на слоте видеть семейство SMA: SMA(10), SMA(20), SMA(50), SMA(200) одной пачкой разных цветов. Сейчас приходится 4 раза добавлять индикатор руками через UI задачи 7.

Идея: рядом с `IndicatorConfig` завести `IndicatorSweepConfig(slotId, indicatorId, paramName, values: List<Double>)` — новая таблица в `core/db`. При рендере — считаем индикатор N раз с разными значениями, рисуем как N overlay-серий. Можно переиспользовать `IndicatorCalculator` и кэш.

Модули: `core-features/indicators`, `features/main`. UI — та же форма индикатора, но вместо единичного значения `period` — список-chips «добавить ещё значение».

Приёмка: создаём свипер SMA с periods=[10, 20, 50] → видим 3 линии разных цветов; цвета стабильны между рестартами; кэш отрабатывает (не пересчитывается на скролле).

---

### 32. Детектор дивергенций RSI vs price

Композитный индикатор: ищет дивергенции между ценой и RSI. Если цена делает новый максимум, а RSI — нет (или наоборот), помечает участок стрелкой на свечном графике.

Строим поверх `IndicatorCatalog` из задачи 6: `DivergenceIndicator` внутри сам дёргает `RsiCalculator` + анализирует свечи, возвращает `IndicatorSeries` со спецом `overlayMarkers: List<Marker>`. Модуль `core-features/indicators`.

Рендер маркеров — в `core/uikit`, новый компонент `ChartMarkerLayer` (если `IndicatorOverlayLayer` из задачи 7 не подходит — отдельный слой). Конфиг через стандартную форму `ParamSpecForm`.

---

### 33. Индикатор на результатах эксперимента

Хочу после бэктеста (задача 11) увидеть его сделки прямо на слоте — стрелки вверх на барах входа, вниз на выходах. По сути, результат `BacktestExecutor` становится источником данных для overlay-слоя.

Ход мысли: в `core-features/experiments` завести `BacktestResultAsIndicator(runId): IndicatorSeries<Marker>` — обёртку, которая читает `TradeLog` последнего завершённого прогона и отдаёт маркеры в том же формате, что задача 32. В `IndicatorConfig` — новый kind `FromExperimentRun(runId)`, enabled/disabled как у обычных индикаторов.

UI: в IndicatorPicker рядом с встроенными — таб «Из экспериментов» со списком последних прогонов. Выбрал → добавилось как overlay.

Зависит от задач 7, 11 и 32 (для маркерного рендера).

Приёмка: прогнать `EmaCross(9,21)` на SBER D1 → из слота SBER добавить overlay этого run → видим стрелки на барах входа/выхода; удалить — исчезли; при новом прогоне старый overlay остаётся валидным (привязан к `runId`, не к эксперименту).

Не трогаем другие виды экспериментов (сегментация, метрики) — только бэктест.

---

## Блок C. Analysis

### 34. Ручная разметка сегментов

Эксперимент сегментации (задача 9) создаёт `ChartSegment` автоматически по правилу. Хочу дополнить — чтобы пользователь мог на слоте выделить диапазон свечей (long-press от бара до бара) и присвоить label руками. Такой сегмент попадает в ту же таблицу `ChartSegment`, но с `runId = null` и `ruleId = "manual"`.

Use case `CreateManualSegmentUseCase(slotId, fromTs, toTs, label)` в `core-features/experiments`. В `SegmentMetricsExecutor` (задача 10) — флаг фильтра «включая ручные» (по умолчанию да), чтобы ручная разметка агрегировалась наравне с авто.

UI выделения — в `features/main` на слоте, режим «select range» в top bar слота. Затронет `features-api/chart` (жесты выделения).

Зависит от задач 4, 9, 10.

Приёмка: выделить диапазон → ввести label → сохранилось; запустить `SegmentMetricsExecutor` без фильтра → ручные сегменты в выборке; удалить ручной сегмент из списка — исчезает; smoke добавлен.

Не делаем объединение/пересечение сегментов (merge/split) — отдельная задача.

---

### 35. Custom rule DSL для сегментации

Правила в `SegmentationExecutor` из задачи 9 сейчас захардкожены enum-ом (RsiOverbought, AtrBreakout). Хочу DSL: пользователь пишет `rsi(14) > 70 AND volume > avg(volume, 30)` → это становится правилом, порождает сегменты.

Лексер/парсер можно переиспользовать из задачи 30 — там уже делается DSL для индикаторов, ядро то же. Новая сущность `SegmentationRule(id, title, expression, paramsJson)` в БД, use case `RunCustomSegmentationUseCase(ruleId, tickerId, periodMinutes)`.

Модули: `core-features/experiments`, `core-features/indicators` (вызов калькуляторов из DSL), `features/analysis` (редактор правила).

Зависит от задач 9 и 30.

---

### 36. Grid-search оптимизатор параметров стратегии

Для бэктеста из задачи 11 — перебирать сетку параметров. Например, `EmaCross` с fast=[5,10,15,20] × slow=[30,50,100] = 12 прогонов. Сортировать по PnL или Sharpe. Находить «лучший» набор.

`BatchOptimizerExecutor` в `core-features/experiments`: принимает базовый конфиг стратегии + список параметров со списками значений, запускает `BacktestExecutor` в цикле, собирает `BacktestSummary` каждого, кладёт как единый артефакт `OptimizerTable`. RunDetail — таблица-grid с сортировкой по колонкам, клик по строке → открыть соответствующий индивидуальный Run.

Затронет `features/analysis`.

Зависит от задач 8, 11, 15.

---

### 37. Шорты в бэктесте

Сейчас `BacktestExecutor` умеет только long-позиции. Нужны короткие — стратегии вида «продаём SBER при RSI > 70, откупаем при RSI < 30». Добавить в движок параметр стратегии `allowShort: Bool`, в `Position` — поле `direction = Long | Short`, инвертировать формулу PnL.

Стратегии из задачи 11 обновить: у `EmaCross` добавить опцию «сигнал вниз закрывает long и открывает short», у `RsiMeanReversion` — работает симметрично.

Модули: `core-features/experiments`, где живёт движок и стратегии.

Зависит от задачи 11.

Приёмка: прогон `RsiMeanReversion` с `allowShort=true` на SBER D1 за 2 года → видим в TradeLog сделки с `direction=Short`; PnL по шорту считается как `(entry - exit) * qty - fees`; при `allowShort=false` поведение идентично текущему. Детерминизм сохраняется.

Не делаем маржинальные требования и плечо — считаем что шорты возможны «как есть», без учёта ставки.

---

## Блок D. Polish & glue

### 38. Global search (Cmd-K)

Хочу быстрый поиск по всему приложению: ввёл «GAZP» — выпали тикеры, воркспейсы с этим тикером, прогоны экспериментов, правила алертов, где он фигурирует. Как Cmd-K в IDE.

Отдельный Decompose-слот поверх текущего экрана, открывается горячей клавишей на Desktop (Ctrl-K) и иконкой поиска в top bar на Android. Внутри — одна поисковая строка и список результатов по категориям (Tickers / Workspaces / Runs / Alerts).

Модуль: новый `features/search` + `features-api/search` для EntryPoint (вызывается из любого таба). Поисковые use case — в существующих core-features: `cf-stocks.SearchTickersUseCase` (уже есть в задаче 5?), `cf-workspaces.SearchWorkspacesByTickerUseCase` (новый), по остальным аналогично.

Зависит от задач 5, 8, 19.

Приёмка: Cmd-K → появился оверлей; ввод GAZP → видим 3 секции; клик по воркспейсу → переход на MainTab с открытым воркспейсом; поиск работает на пустой БД (пустое состояние). Smoke.

Не делаем полнотекстовый поиск по содержимому RunArtifact (слишком дорого) — только по title/ticker.

---

### 39. Темы оформления и настройка цветов графика

Тёмная/светлая тема — есть, но хочу три-четыре preset'а (classic / dark-blue / high-contrast / amoled) + ручную настройку цветов свечей (бычья зелёная vs красная, хайлайт viewport). Настройки в `features/settings`.

Расширить `themeModule` новыми цветовыми схемами, завести `ChartStyle(bullColor, bearColor, gridColor, ...)` — отдельная preferences-группа через DataStore. Передавать `ChartStyle` через CompositionLocal из корня в `features-api/chart`. Затронет `core/theme`, `features/settings`, `features/main`.

Приёмка: в settings выбрать preset «high-contrast» → график и UI поменяли цвета без перезапуска; ручная настройка цвета бычьей свечи → сохранилась между рестартами; smoke добавлен.

Не делаем кастомные шрифты и размеры — только цвета.

---

### 40. i18n — вынос строк + английская локаль

Сейчас весь UI на русском, строки захардкожены в Composable. Хочу вынести в `commonMainResources` через `stringResource(Res.string.foo)`, добавить English-локаль как второй язык, переключалку в settings.

Модули: `core/resources` (сами строки), `core/theme` или `core/utils` (language switcher preferences), применить замену литералов на `stringResource` в `features/main`, `features/data`, `features/settings` и остальных `features/*`.

Приёмка: переключить язык в settings → UI переключился без рестарта; строка, которую забыли вынести, видна в grep на русскую кириллицу в `features/*/ui/` (допустимо ≤10 оставшихся, но в идеале 0); compileKotlinJvm зелёный.

---

### 41. Универсальный RunArtifact inspector

Каждый тип эксперимента кладёт свои артефакты (TradeLog, EquityCurve, MetricsSummary, DurationHistogram — всё в `RunArtifact.payloadJson`). Сейчас для каждого вида в RunDetail пишется свой рендер. Надоело.

Хочу универсальный inspector — один компонент в `features/analysis`, который по `ArtifactKind` диспатчит на нужный рендер: JSON-tree для unknown, таблица для array-of-objects, график если есть поле `series`. Оборачивает всё в общий layout с заголовком и кнопкой «экспорт в clipboard».

Зависит от задач 8, 10, 11 — без них нечего инспектировать.

Не делаем редактирование артефактов — только просмотр.

---

## Блок E. Breadth

### 42. Tinkoff Invest API как источник

Ещё один источник котировок — Tinkoff Invest API. OAuth с токеном пользователя (у Tinkoff не refresh-flow, а статичный long-lived token — проще, чем Alor). Нужен новый builtin-пресет `tinkoff_invest.json` в `core-features/stocks/presets/`.

API возвращает JSON (не CSV как MOEX и Yahoo), придётся расширять парсер ответа — сейчас `CsvParser`, понадобится `JsonCandleParser` или полиморфизм в `CandleFetcher` из задачи 23. Тикеры у Tinkoff по FIGI или по тикеру MOEX — маппинг через тот же `SourceTickerMapping`.

Модули: `core-features/stocks`, `features/data` (UI добавления).

Зависит от задач 16, 17, 23.

---

### 43. Binance spot API — крипто-источник

Binance spot public API для крипты — без авторизации для публичных данных (свечи/тикеры). Принципиально новый формат: эндпойнт `/api/v3/klines`, возвращает JSON-массив массивов `[openTime, open, high, low, close, volume, ...]`. Нужен отдельный парсер `BinanceKlinesParser`.

Помимо формата — другие периоды (`1m, 3m, 5m, 15m, 1h, 4h, 1d`), другие тикеры (`BTCUSDT`, `ETHBTC` — без точки, без суффикса биржи). Новый builtin-пресет `binance_spot.json`, возможно потребует расширить `PeriodMapping` под минутные таймфреймы (сейчас фокус на дневках).

Модули: `core-features/stocks`, возможно `core/db` (если периоды в БД захардкожены).

Зависит от задач 16 и 23.

Приёмка: добавить Binance как источник → скачать свечи BTCUSDT 1h за неделю → ≥150 свечей в `CandleTable`; открыть слот с BTCUSDT → график рисуется как обычно; существующие источники (MOEX/Yahoo) продолжают работать. Юнит-тесты на `BinanceKlinesParser` — ≥5 кейсов (валидный ответ, пустой массив, невалидный JSON).

Не делаем WebSocket live-price (это задача 44), не делаем фьючерсы/маржу — только spot.

---

### 44. WebSocket live-quotes для Watchlist

Watchlist (задача 18) сейчас показывает последнюю свечу из БД — «последняя цена» отстаёт от реальной на период свечи (например, на сутки на D1). Хочу live-обновление через WebSocket — подписка по списку тикеров, сервер пушит текущую цену, UI обновляется в реальном времени.

Тянет за собой: в `core/network` — Ktor WebSocket плагин, `LiveQuoteClient` интерфейс + реализация `MoexLiveQuoteClient` (если у MOEX есть WS — проверить, иначе использовать Binance из задачи 43 в демо-режиме). В `core-features/stocks` — `ObserveLiveQuotesUseCase(tickers): Flow<LiveQuote>`. Watchlist-экран в `features/main` совмещает последнюю свечу из БД + live-поток поверх.

Зависит от задач 18 и 43 (нужен хотя бы один источник с публичным WS).

Приёмка: открыть Watchlist с 5 тикерами крипты (Binance) → цены обновляются каждые 1–3 секунды без polling; при уходе экрана с Watchlist → подписка закрывается (grep на активные сокеты — 0); переход обратно → переподписка. Smoke не обязателен (сложно автоматизировать), вместо него — интеграционный тест на `LiveQuoteClient` на фикстурном WS-сервере.

Не сохраняем live-тики в БД — только отображение. Не делаем live-обновление для графиков (overlay на последней свече) — только watchlist.

---

### 45. iOS WidgetKit аналог Android-виджета

На Android уже есть widget из задачи 22. iOS — свой WidgetKit на Swift, который делит SQLite-базу с KMP-приложением через App Group. Виджет показывает топ-5 Watchlist.

Swift-код живёт в `iosApp/`, напрямую читает `stocks.db` через `sqlite3`. Нужна обёртка в KMP (в `core/db`) для проверки, что схема совместима. Обновление — по расписанию WidgetKit (iOS управляет).

Не копаю глубоко пока — надо сначала понять, как делится DataStore/SQLite через App Group.

---

## Блок M. Tech debt / refactor

### 46. Миграция существующих тестов на DispatcherProvider

В проекте CLAUDE.md уже требует `DispatcherProvider` для прода. Но в тестах `core-features/stocks` полно `runBlocking { ... }` и прямых `Dispatchers.IO` — часть написана до правила. Хочу причесать: все тесты с корутинами — через `runTest { }`, диспатчеры — через `TestDispatcherProvider(testDispatcher)`.

Точечный рефакторинг, без изменения поведения. Затронет `core-features/stocks/src/commonTest/`.

Приёмка: `grep -r 'runBlocking' modules/core/core-features/stocks/src/commonTest/` → 0 результатов; `grep -r 'Dispatchers\.' src/commonTest/` → 0; `./gradlew :modules:core:core-features:stocks:allTests` зелёный; диффы меняют только тестовый код, прод не трогается.

Не трогаем инструментальные/Android-тесты (если есть) — только commonTest. Не переписываем тест-логику, только boilerplate.

---

### 47. DataStore за интерфейсом PreferencesStore

`DataStore<Preferences>` сейчас инжектится напрямую в репозитории настроек и в `themeModule`. Это final-тип, а значит репозитории не мокабельны по правилу `.claude/rules/testing.md` — такая же история, как задачи 23 и 24 про Ktor и SQLDelight.

Ввести интерфейс `PreferencesStore` в `core/utils` с методами под наши нужды (`readString`, `observeString`, `writeString`, по типам — `readBoolean`, `readInt` и т.д.). Реализация `DataStorePreferencesStore` в `core/utils/data/`. Все потребители — `theme`, потребитель PreferencesStore в `features/settings`, возможно `cf-stocks` если там есть prefs — переключаются на интерфейс.

Паттерн такой же как DAO в задаче 24: интерфейс в domain/utils, реализация в data, Koin регистрирует интерфейс.

Зависит от задачи 1 (архитектурный research должен зафиксировать паттерн).

Приёмка: `grep -r 'import.*DataStore' modules/ --include="*.kt"` вне `core/utils/data/` → 0; появился `PreferencesStoreTest` на реализацию (integration); `ThemeRepositoryTest` с `mock<PreferencesStore>()` — проверяет вызовы; assembleDebug зелёный.

---

### 48. Convention plugin `kmp.feature` для feature-модулей

Все `modules/features/*` и `modules/features-api/*` имеют почти идентичные `build.gradle.kts` — target-конфигурация, compose dependencies, Koin, Decompose, MVIKotlin, `kmp.library` convention. При добавлении 8 новых feature-модулей из роадмапа (workspaces, indicators, analysis, experiments, alerts, portfolio, pickers, search) это 8× копипаста.

Вынести в `build-logic/convention/` плагин `kmp.feature`, который применяется одной строчкой в feature-модуле и подтягивает весь стандартный набор. Для `features-api/*` — отдельный `kmp.feature-api` с урезанным набором (только Decompose).

Применить `kmp.feature` в `features/main`, `features/data`, `features/settings` и остальных `modules/features/**/build.gradle.kts` (упрощаются), плюс `build-logic/convention/` (новый plugin).

Приёмка: `build.gradle.kts` среднего feature-модуля ≤30 строк (сейчас ~60); применение плагина в новом модуле — одна строка `plugins { id("kmp.feature") }`; `./gradlew build` зелёный; размер артефактов не изменился.

Не делаем `kmp.core-feature` (для `core/core-features/*`) — они разнообразнее, пусть пока живут как есть. Не трогаем `composeApp` и `mainentry` — там свои особенности.

---

### 49. Screen-tests фреймворк на Paparazzi/Roborazzi

Хочу visual regression для ключевых экранов: при изменении темы, шрифта, layout-логики — автоматический тест ловит отличие от эталонного PNG. Paparazzi для Compose Android, Roborazzi как альтернатива (работает и в KMP-commonTest через JVM). Выбор — определить в ходе задачи.

Покрыть хотя бы: `DataHubScreen`, `WorkspaceCarousel` с 2 воркспейсами, `SettingsScreen`, `IndicatorPicker` из задачи 7. Скриншоты — в `test-screenshots/` папке, версионируются в git.

Зависит от задачи 7.

---

### 50. Smoke fixture generator из fake-данных

Сейчас smoke-фикстуры (`.db` файлы) создаются вручную: протыкай UI → `adb exec-out run-as ... cat stocks.db > fixture.db`. Это утомительно и хрупко при изменении `.sq` схемы — все fixture ломаются одновременно.

Хочу Gradle-таск `:modules:core:db:generateSmokeFixtures`, который по seed-конфигу (YAML или Kotlin DSL) генерит `.db` прямо в `smoke/fixtures/` на хосте. Внутри — SQLDelight driver на in-memory или file SQLite, `insertAll` фейковых данных, `copy` в целевой файл.

Сидовые конфиги лежат рядом со сценариями: `smoke/fixtures/base_sectors.seed.yaml` → `smoke/fixtures/base_sectors.db`.

Не трогаем сами smoke-сценарии — они как читали fixture, так и будут. Не генерим live-данные (котировки, свечи) из API — только seed-файлы.
