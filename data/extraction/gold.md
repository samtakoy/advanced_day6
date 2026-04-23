# Gold-разметка (56 примеров)

По каждой задаче: ссылка на prose-источник + эталонный JSON-ответ assistant'а. Маркеры `[TRAIN]` / `[EVAL]` задают split.

Источники прозы:
- `plans/tasks1_prose.md` — задачи 1–25
- `plans/tasks2.md` — задачи 26–50
- `plans/tasks_adversarial.md` — задачи 51–56

---

## Task 1 — Research архитектуры Workspace / Indicator / Experiment [TRAIN]

**User:** `plans/tasks1_prose.md` §1

```json
{
  "title": "Research архитектуры Workspace / Indicator / Experiment",
  "type": "research",
  "block": "workspace_foundation",
  "modules": [],
  "newModules": [],
  "dependsOn": [],
  "acceptanceCriteria": [
    "plans/research/architecture.md содержит SQL CREATE всех новых таблиц",
    "граф зависимостей модулей",
    "перечень ≥5 решённых развилок с аргументацией"
  ],
  "outOfScope": ["изменения кода"]
}
```

---

## Task 2 — БД и домен Workspace + ChartSlot [EVAL]

**User:** `plans/tasks1_prose.md` §2

```json
{
  "title": "БД и домен Workspace + ChartSlot",
  "type": "feat",
  "block": "workspace_foundation",
  "modules": ["db", "cf-workspaces", "mainentry"],
  "newModules": [],
  "dependsOn": [1],
  "acceptanceCriteria": [
    "./gradlew :composeApp:compileKotlinJvm зелёный",
    "commonTest на CreateWorkspace, ReorderWorkspaces, AddChartSlot по правилам testing.md (Mokkery + Turbine + runTest)",
    "ручной smoke — создать workspace + slot, после перезапуска данные на месте"
  ],
  "outOfScope": ["UI", "индикаторы", "автодогрузка свечей"]
}
```

---

## Task 3 — Таб Main: карусель воркспейсов [TRAIN]

**User:** `plans/tasks1_prose.md` §3

```json
{
  "title": "Таб Main: карусель воркспейсов",
  "type": "feat",
  "block": "workspace_foundation",
  "modules": ["uikit"],
  "newModules": [],
  "dependsOn": [2],
  "acceptanceCriteria": [
    "smoke: empty state → создание workspace → свайп между страницами → индикатор страниц отражает активную",
    "быстрое листание не крашит, состояние каждой страницы сохраняется",
    "features-module.md соблюдён: Component interface + Default...Component, dispose стора в doOnDestroy, ComponentContext через parametersOf"
  ],
  "outOfScope": ["добавление слотов", "рендер графика", "индикаторы", "rename/delete — в задаче 5"]
}
```

---

## Task 4 — ChartSlot с графиком и автодогрузкой свечей [TRAIN]

**User:** `plans/tasks1_prose.md` §4

```json
{
  "title": "ChartSlot с графиком и автодогрузкой свечей",
  "type": "feat",
  "block": "workspace_foundation",
  "modules": ["cf-stocks"],
  "newModules": ["modules:features-api:chart"],
  "dependsOn": [2, 3],
  "acceptanceCriteria": [
    "воркспейс с двумя слотами GAZP/SBER D1 при первом открытии качает и рисует свечи по мере поступления",
    "после рестарта viewport каждого слота восстанавливается (±100 мс)",
    "smoke: слот с уже загруженными данными не ставит новых DownloadTask"
  ],
  "outOfScope": ["UI добавления слота", "индикаторы", "pinch-zoom жесты"]
}
```

---

## Task 5 — CRUD воркспейсов/слотов + общий Ticker/Period Picker [TRAIN]

**User:** `plans/tasks1_prose.md` §5

```json
{
  "title": "CRUD воркспейсов/слотов + общий Ticker/Period Picker",
  "type": "feat",
  "block": "workspace_foundation",
  "modules": ["m-main", "fa-pickers", "cf-stocks", "uikit"],
  "newModules": ["modules:features:pickers"],
  "dependsOn": [4],
  "acceptanceCriteria": [
    "smoke: CRUD workspaces + добавление 2 слотов через picker + reorder + удаление слота",
    "features-api/pickers не зависит от uikit, features/pickers, core/core-features/stocks (только интерфейс + Input + EntryPoint)",
    "features/main обращается к пикеру только через TickerPickerEntryPoint"
  ],
  "outOfScope": ["поиск по тикеру", "ветка избранного/истории"]
}
```

---

## Task 6 — Движок индикаторов — домен + каталог + тесты [EVAL]

**User:** `plans/tasks1_prose.md` §6

```json
{
  "title": "Движок индикаторов — домен + каталог + тесты",
  "type": "feat",
  "block": "indicators",
  "modules": ["cf-indicators"],
  "newModules": [],
  "dependsOn": [1],
  "acceptanceCriteria": [
    "./gradlew :modules:core:core-features:indicators:allTests зелёный, покрытие калькуляторов ≥80%",
    "эталонные значения сверены с TradingView/Wikipedia",
    "нет зависимостей на androidx, Compose, Decompose, Ktor, SQLDelight",
    "IndicatorCatalog.all() возвращает 6 индикаторов с корректными paramsSpec"
  ],
  "outOfScope": []
}
```

---

## Task 7 — IndicatorConfig: персист и рендер на ChartSlot [TRAIN]

**User:** `plans/tasks1_prose.md` §7

```json
{
  "title": "IndicatorConfig: персист и рендер на ChartSlot",
  "type": "feat",
  "block": "indicators",
  "modules": ["db", "cf-indicators", "cf-workspaces", "uikit"],
  "newModules": [],
  "dependsOn": [4, 6],
  "acceptanceCriteria": [
    "smoke: EMA(20)+RSI(14) на GAZP D1 — добавить, рестарт, изменить период EMA, выключить RSI, удалить",
    "скролл при включённых индикаторах без заметных лагов (работает кэш)",
    "spec-driven форма валидирует min/max, Int vs Double"
  ],
  "outOfScope": ["пользовательские формулы", "пресеты"]
}
```

---

## Task 8 — Таб Анализ + каркас ExperimentRunner [TRAIN]

**User:** `plans/tasks1_prose.md` §8

```json
{
  "title": "Таб Анализ + каркас ExperimentRunner",
  "type": "feat",
  "block": "analysis",
  "modules": ["mainentry", "m-analysis", "cf-experiments", "db", "uikit"],
  "newModules": [],
  "dependsOn": [1],
  "acceptanceCriteria": [
    "smoke: таб Анализ → Echo → запуск GAZP D1 → RUNNING → FINISHED, артефакт виден в RunDetail",
    "отменённый прогон CANCELLED, артефакт не создаётся",
    "ExperimentRunner не использует GlobalScope и Dispatchers.* напрямую"
  ],
  "outOfScope": []
}
```

---

## Task 9 — Эксперимент: сегментация графика по правилу [TRAIN]

**User:** `plans/tasks1_prose.md` §9

```json
{
  "title": "Эксперимент: сегментация графика по правилу",
  "type": "feat",
  "block": "analysis",
  "modules": ["cf-experiments", "uikit"],
  "newModules": ["modules:features-api:chart"],
  "dependsOn": [6, 7, 8],
  "acceptanceCriteria": [
    "запуск RsiOverboughtOversold(14, 70/30) на GAZP D1 → ≥N сегментов + сводка в артефакте",
    "из RunDetail 'Открыть в воркспейсе' → слот с подсветкой сегментов",
    "повторный запуск с теми же параметрами не дублирует сегменты"
  ],
  "outOfScope": ["ручное редактирование сегментов (пересечение, объединение, ручная метка)", "кастомные правила"]
}
```

---

## Task 10 — Эксперимент: метрики по серии сегментов [EVAL]

**User:** `plans/tasks1_prose.md` §10

```json
{
  "title": "Эксперимент: метрики по серии сегментов",
  "type": "feat",
  "block": "analysis",
  "modules": ["uikit"],
  "newModules": [],
  "dependsOn": [8, 9],
  "acceptanceCriteria": [
    "запуск без фильтра на N сегментах → артефакты сформированы, графики отображаются",
    "смена фильтра → новый Run с отличающимися метриками",
    "пустая выборка → FINISHED_EMPTY без краха"
  ],
  "outOfScope": []
}
```

---

## Task 11 — Эксперимент: бэктест стратегии индикаторов [TRAIN]

**User:** `plans/tasks1_prose.md` §11

```json
{
  "title": "Эксперимент: бэктест стратегии индикаторов",
  "type": "feat",
  "block": "analysis",
  "modules": ["uikit"],
  "newModules": [],
  "dependsOn": [6, 8, 10],
  "acceptanceCriteria": [
    "EmaCross(9, 21) на SBER D1 за 2 года → ≥10 сделок, equity и метрики отображаются",
    "повторный запуск с теми же параметрами даёт идентичный результат (детерминизм)",
    "smoke: клик по сделке в таблице → переход на WorkspaceMain с подсветкой бара входа/выхода"
  ],
  "outOfScope": ["короткие позиции", "пирамидинг", "мультитикерные стратегии", "оптимизатор параметров"]
}
```

---

## Task 12 — Вынос графических компонентов в core/uikit [TRAIN]

**User:** `plans/tasks1_prose.md` §12

```json
{
  "title": "Вынос графических компонентов в core/uikit",
  "type": "refactor",
  "block": "polish_and_glue",
  "modules": ["uikit", "m-main", "m-analysis"],
  "newModules": [],
  "dependsOn": [7, 10, 11],
  "acceptanceCriteria": [
    "./gradlew assembleDebug зелёный, все существующие smoke проходят",
    "grep Canvas(/drawLine/drawRect в features/* — только в uikit (0 в features/*)",
    "plans/research/uikit-inventory.md перечисляет публичные компоненты uikit с описанием и примером"
  ],
  "outOfScope": ["переписывание визуального стиля", "новые типы графиков", "theming"]
}
```

---

## Task 13 — Кросс-навигация: открыть тикер в Workspace [EVAL]

**User:** `plans/tasks1_prose.md` §13

```json
{
  "title": "Кросс-навигация: открыть тикер в Workspace",
  "type": "feat",
  "block": "polish_and_glue",
  "modules": ["m-data", "m-analysis", "m-main", "uikit"],
  "newModules": ["modules:features-api:workspaces"],
  "dependsOn": [5, 11],
  "acceptanceCriteria": [
    "smoke: из DataTab выбрать тикер → 'В воркспейс' → диалог → выбор → MainTab с открытым workspace, слот появился",
    "тот же флоу из TradeRow задачи 11 — открывает workspace с тем же ticker/period"
  ],
  "outOfScope": ["глубокое диплинкование (URL-схемы)", "shortcuts на рабочем столе"]
}
```

---

## Task 14 — Экспорт/импорт воркспейсов и пресетов индикаторов [TRAIN]

**User:** `plans/tasks1_prose.md` §14

```json
{
  "title": "Экспорт/импорт воркспейсов и пресетов индикаторов",
  "type": "feat",
  "block": "polish_and_glue",
  "modules": ["utils"],
  "newModules": [],
  "dependsOn": [5, 7],
  "acceptanceCriteria": [
    "экспорт workspace с 3 слотами и 2 индикаторами → валидный JSON, парсится Json.decodeFromString<WorkspaceSnapshot>",
    "импорт на чистой БД (те же справочники Ticker/Market) → идентичный workspace",
    "импорт при отсутствующем тикере → ImportResult.MissingReferences, частичный workspace не создаётся"
  ],
  "outOfScope": ["облачная синхронизация", "QR-шеринг", "iOS FilePicker"]
}
```

---

## Task 15 — Батч-прогон эксперимента + сравнение прогонов [TRAIN]

**User:** `plans/tasks1_prose.md` §15

```json
{
  "title": "Батч-прогон эксперимента + сравнение прогонов",
  "type": "feat",
  "block": "polish_and_glue",
  "modules": ["uikit"],
  "newModules": [],
  "dependsOn": [5, 10, 11],
  "acceptanceCriteria": [
    "батч EmaCross(9,21) на 10 тикерах → таблица с метриками + сортировка по PnL",
    "Compare двух Run с разными параметрами EmaCross на одном тикере → обе equity + разница метрик"
  ],
  "outOfScope": ["оптимизатор параметров (grid search)"]
}
```

---

## Task 16 — Yahoo Finance как встроенный источник + импорт пресетов по URL [TRAIN]

**User:** `plans/tasks1_prose.md` §16

```json
{
  "title": "Yahoo Finance как встроенный источник + импорт пресетов по URL",
  "type": "feat",
  "block": "breadth",
  "modules": ["cf-stocks"],
  "newModules": [],
  "dependsOn": [],
  "acceptanceCriteria": [
    "smoke: Yahoo как источник + маппинг GAZP→GAZP.ME + дневки за год → ≥200 свечей в CandleTable",
    "импорт валидного JSON-пресета по URL → Source с маппингами; невалидный URL/JSON → error dialog, ничего не создаётся",
    "юнит-тесты на CsvParser с Yahoo-форматом заголовков"
  ],
  "outOfScope": ["OAuth/auth", "автомаппинг тикеров MOEX↔Yahoo"]
}
```

---

## Task 17 — Авторизованные источники: Alor OpenAPI [TRAIN]

**User:** `plans/tasks1_prose.md` §17

```json
{
  "title": "Авторизованные источники: Alor OpenAPI",
  "type": "feat",
  "block": "breadth",
  "modules": ["utils", "net"],
  "newModules": [],
  "dependsOn": [16],
  "acceptanceCriteria": [
    "plans/research/authorized-sources.md с выбором решения принят",
    "настроенный Alor-источник скачивает свечи для тикера MOEX",
    "refresh-токен обновляется автоматически при протухании access-токена (unit-тест с подменённым временем или ручной с коротким TTL)",
    "grep encodeToString(.*RefreshToken) и plaintext по репо — 0 утечек в DataStore/файлы"
  ],
  "outOfScope": ["торговые операции через Alor — только чтение истории", "автосинк позиций"]
}
```

---

## Task 18 — Watchlist — избранные тикеры с последними ценами [TRAIN]

**User:** `plans/tasks1_prose.md` §18

```json
{
  "title": "Watchlist — избранные тикеры с последними ценами",
  "type": "feat",
  "block": "breadth",
  "modules": ["m-main", "m-data", "uikit"],
  "newModules": [],
  "dependsOn": [2, 3, 4, 5, 13],
  "acceptanceCriteria": [
    "smoke: 3 тикера в watchlist + reorder + удаление + клик по строке → открыт воркспейс с этим тикером",
    "при обновлении Candle — значение в watchlist обновляется без ручного рефреша"
  ],
  "outOfScope": ["push-уведомления по цене", "сортировки/фильтры"]
}
```

---

## Task 19 — AlertEngine + локальные уведомления [TRAIN]

**User:** `plans/tasks1_prose.md` §19

```json
{
  "title": "AlertEngine + локальные уведомления",
  "type": "feat",
  "block": "breadth",
  "modules": ["cf-indicators", "utils"],
  "newModules": ["modules:core:core-features:alerts", "modules:features:alerts"],
  "dependsOn": [2, 3, 4, 5, 6],
  "acceptanceCriteria": [
    "smoke: RSI(14) > 70 на GAZP D1 enabled → при свече с RSI > 70 получен notification + запись в AlertEvent",
    "правило disabled не срабатывает",
    "клик по уведомлению в Android → приложение открывается на соответствующем воркспейсе",
    "нет GlobalScope, нет Dispatchers.* напрямую в AlertEvaluator"
  ],
  "outOfScope": ["push через Firebase/APNs", "алерты с сервера", "WebSocket-подписки"]
}
```

---

## Task 20 — Portfolio — учёт позиций и P&L [TRAIN]

**User:** `plans/tasks1_prose.md` §20

```json
{
  "title": "Portfolio — учёт позиций и P&L",
  "type": "feat",
  "block": "breadth",
  "modules": ["fa-pickers", "uikit"],
  "newModules": ["modules:core:core-features:portfolio"],
  "dependsOn": [2, 5],
  "acceptanceCriteria": [
    "smoke: SBER Long 100 @ 250 → unrealized PnL по текущей свече",
    "закрыть @ 270 → realized = (270−250)×100 − fees; суммы в сводке корректны",
    "CSV-импорт на 10 позиций → валидные применяются, невалидные в error list",
    "при переключении бэкенда свечей (Yahoo/MOEX) PnL использует актуальный источник"
  ],
  "outOfScope": ["автосинк с Alor", "налоги", "multi-currency"]
}
```

---

## Task 21 — Cloud sync — выбор стратегии и границ [TRAIN]

**User:** `plans/tasks1_prose.md` §21

```json
{
  "title": "Cloud sync — выбор стратегии и границ",
  "type": "research",
  "block": "breadth",
  "modules": [],
  "newModules": [],
  "dependsOn": [14],
  "acceptanceCriteria": [
    "plans/research/cloud-sync.md: таблица сравнения вариантов, выбранный вариант с аргументацией, диаграмма потока данных, список MVP-задач с оценкой по дням",
    "код не меняется"
  ],
  "outOfScope": []
}
```

---

## Task 22 — Android Widget + App Shortcuts [TRAIN]

**User:** `plans/tasks1_prose.md` §22

```json
{
  "title": "Android Widget + App Shortcuts",
  "type": "feat",
  "block": "breadth",
  "modules": ["mainentry"],
  "newModules": ["composeApp"],
  "dependsOn": [3, 18],
  "acceptanceCriteria": [
    "виджет добавляется на рабочий стол Android, показывает актуальные данные из Watchlist, тап открывает приложение на воркспейсе тикера",
    "long-press иконки приложения — видны 3 shortcut'а, каждый открывает приложение в правильном месте",
    "adb shell am start -a android.intent.action.VIEW -d stocks://workspace/1 → открывает нужный воркспейс"
  ],
  "outOfScope": ["iOS widgets", "iOS shortcuts", "Desktop-tray"]
}
```

---

## Task 23 — Изоляция Ktor HttpClient через API-слой [TRAIN]

**User:** `plans/tasks1_prose.md` §23

```json
{
  "title": "Изоляция Ktor HttpClient через API-слой",
  "type": "refactor",
  "block": "tech_debt_refactor",
  "modules": ["cf-stocks"],
  "newModules": [],
  "dependsOn": [1],
  "acceptanceCriteria": [
    "grep 'io.ktor.client.HttpClient' в modules/core/core-features/stocks/ → 0 (остаётся только в modules/core/network/)",
    "./gradlew :composeApp:compileKotlinJvm зелёный, все существующие smoke без регрессии",
    "новый DefaultChunkedCandleDownloaderTest зелёный, покрывает сценарий частичной отдачи чанков"
  ],
  "outOfScope": ["добавление Yahoo/Alor — задачи 16, 17"]
}
```

---

## Task 24 — Изоляция SQLDelight через DAO-слой [EVAL]

**User:** `plans/tasks1_prose.md` §24

```json
{
  "title": "Изоляция SQLDelight через DAO-слой",
  "type": "refactor",
  "block": "tech_debt_refactor",
  "modules": ["cf-stocks"],
  "newModules": [],
  "dependsOn": [1],
  "acceptanceCriteria": [
    "grep 'import ru.samtakoy.stocks.db.StocksDatabase' в modules/core/core-features/stocks/data/repository/ → 0",
    "все 10 *RepositoryImpl принимают только DAO и опционально DispatcherProvider, не StocksDatabase",
    "./gradlew :composeApp:compileKotlinJvm зелёный, все существующие smoke проходят",
    "SourceRepositoryImplTest.createWithMappings_insertsSourceParamsMarketsAndPeriods_inOrder — verifySuspend в правильной последовательности",
    "CandleRepositoryImplTest.insertBatch_forwardsToDao зелёный",
    "паттерн задокументирован в plans/research/db-isolation.md",
    "паттерн упомянут в архитектурных notes задачи 1"
  ],
  "outOfScope": [
    "переписывание .sq файлов",
    "миграции БД",
    "полный вынос StocksDatabase из core-features/stocks — он остаётся в data/local"
  ]
}
```

---

## Task 25 — Миграция feature/data на единую структуру папок [TRAIN]

**User:** `plans/tasks1_prose.md` §25

```json
{
  "title": "Миграция feature/data на единую структуру папок",
  "type": "refactor",
  "block": "tech_debt_refactor",
  "modules": ["m-data", "cf-stocks"],
  "newModules": [],
  "dependsOn": [],
  "acceptanceCriteria": [
    "./gradlew assembleDebug зелёный; ./gradlew :composeApp:allTests не регрессирует",
    "все smoke-сценарии в smoke/scenarios/ проходят без изменений YAML",
    "grep -r 'BuiltinPresetLoader' modules/features/ → 0",
    "grep -rE '^\\s*(data )?class \\w+With\\w+' modules/features/data/ в корнях screen-папок → 0",
    "modules/features/data/src/commonMain/kotlin/ru/samtakoy/stocks/feature/data/ui/ не существует",
    "все *MappingHelpers.kt декларируют internal типы"
  ],
  "outOfScope": [
    "миграция на PersistentList и удаление дефолтов из Store.State",
    "применение к другим features (main, settings, chart)",
    "переход на hyphenated folder names"
  ]
}
```

---

## Task 26 — Templates воркспейсов [TRAIN]

**User:** `plans/tasks2.md` §26

```json
{
  "title": "Templates воркспейсов",
  "type": "feat",
  "block": "workspace_foundation",
  "modules": ["cf-workspaces", "m-main"],
  "newModules": [],
  "dependsOn": [5, 7],
  "acceptanceCriteria": [
    "smoke: выбор шаблона 'Blue chips' на пустой БД → воркспейс с 4 слотами и индикаторами, после рестарта всё на месте",
    "компиляция зелёная"
  ],
  "outOfScope": [
    "cloud-sync шаблонов (задача 21)",
    "пользовательские шаблоны (сохранить текущий workspace как template)"
  ]
}
```

---

## Task 27 — Split-screen ChartSlot [TRAIN]

**User:** `plans/tasks2.md` §27

```json
{
  "title": "Split-screen ChartSlot",
  "type": "feat",
  "block": "workspace_foundation",
  "modules": ["db", "cf-workspaces", "m-main"],
  "newModules": ["modules:features-api:chart"],
  "dependsOn": [],
  "acceptanceCriteria": [],
  "outOfScope": ["горизонтальный split (рядом)"]
}
```

---

## Task 28 — Теги и цветовая группировка воркспейсов [EVAL]

**User:** `plans/tasks2.md` §28

```json
{
  "title": "Теги и цветовая группировка воркспейсов",
  "type": "feat",
  "block": "workspace_foundation",
  "modules": ["db", "cf-workspaces", "m-main"],
  "newModules": [],
  "dependsOn": [5],
  "acceptanceCriteria": [
    "на двух воркспейсах задать разные теги → индикатор страниц визуально отличает",
    "после рестарта теги на месте",
    "smoke проходит"
  ],
  "outOfScope": []
}
```

---

## Task 29 — Синхронизация viewport между слотами одного workspace [TRAIN]

**User:** `plans/tasks2.md` §29

```json
{
  "title": "Синхронизация viewport между слотами одного workspace",
  "type": "feat",
  "block": "workspace_foundation",
  "modules": ["db", "cf-workspaces", "m-main"],
  "newModules": [],
  "dependsOn": [4],
  "acceptanceCriteria": [
    "режим Synced → скролл одного графика двигает все остальные",
    "после рестарта режим помнится",
    "Independent работает как раньше",
    "компиляция зелёная"
  ],
  "outOfScope": ["синхронизация между разными воркспейсами — только внутри одного"]
}
```

---

## Task 30 — Custom indicator formula DSL [TRAIN]

**User:** `plans/tasks2.md` §30

```json
{
  "title": "Custom indicator formula DSL",
  "type": "feat",
  "block": "indicators",
  "modules": ["cf-indicators"],
  "newModules": [],
  "dependsOn": [6, 7],
  "acceptanceCriteria": [
    "юнит-тесты на парсер ≥10 кейсов (приоритеты операций, скобки, ошибки синтаксиса)",
    "формула EMA(close,12) - EMA(close,26) → рисуется overlay, значения совпадают с ручным MACD-like подсчётом",
    "невалидная формула → ошибка с указанием позиции",
    "smoke добавлен"
  ],
  "outOfScope": ["циклы/ветвления в DSL — только арифметика и вызовы встроенных функций", "изменения готовых индикаторов"]
}
```

---

## Task 31 — Параметр-свипер одного индикатора [TRAIN]

**User:** `plans/tasks2.md` §31

```json
{
  "title": "Параметр-свипер одного индикатора",
  "type": "feat",
  "block": "indicators",
  "modules": ["db", "cf-indicators", "m-main"],
  "newModules": [],
  "dependsOn": [],
  "acceptanceCriteria": [
    "свипер SMA с periods=[10, 20, 50] → 3 линии разных цветов",
    "цвета стабильны между рестартами",
    "кэш отрабатывает (не пересчитывается на скролле)"
  ],
  "outOfScope": []
}
```

---

## Task 32 — Детектор дивергенций RSI vs price [EVAL]

**User:** `plans/tasks2.md` §32

```json
{
  "title": "Детектор дивергенций RSI vs price",
  "type": "feat",
  "block": "indicators",
  "modules": ["cf-indicators", "uikit"],
  "newModules": [],
  "dependsOn": [6],
  "acceptanceCriteria": [],
  "outOfScope": []
}
```

---

## Task 33 — Индикатор на результатах эксперимента [TRAIN]

**User:** `plans/tasks2.md` §33

```json
{
  "title": "Индикатор на результатах эксперимента",
  "type": "feat",
  "block": "indicators",
  "modules": ["cf-experiments"],
  "newModules": [],
  "dependsOn": [7, 11, 32],
  "acceptanceCriteria": [
    "прогон EmaCross(9,21) на SBER D1 → из слота SBER добавить overlay этого run → стрелки на барах входа/выхода",
    "удалить overlay → исчезли",
    "при новом прогоне старый overlay остаётся валидным (привязан к runId, не к эксперименту)"
  ],
  "outOfScope": ["другие виды экспериментов (сегментация, метрики) — только бэктест"]
}
```

---

## Task 34 — Ручная разметка сегментов [TRAIN]

**User:** `plans/tasks2.md` §34

```json
{
  "title": "Ручная разметка сегментов",
  "type": "feat",
  "block": "analysis",
  "modules": ["cf-experiments", "m-main"],
  "newModules": ["modules:features-api:chart"],
  "dependsOn": [4, 9, 10],
  "acceptanceCriteria": [
    "выделить диапазон → ввести label → сохранилось",
    "запустить SegmentMetricsExecutor без фильтра → ручные сегменты в выборке",
    "удалить ручной сегмент из списка → исчезает",
    "smoke добавлен"
  ],
  "outOfScope": ["объединение/пересечение сегментов (merge/split)"]
}
```

---

## Task 35 — Custom rule DSL для сегментации [TRAIN]

**User:** `plans/tasks2.md` §35

```json
{
  "title": "Custom rule DSL для сегментации",
  "type": "feat",
  "block": "analysis",
  "modules": ["cf-experiments", "cf-indicators", "m-analysis"],
  "newModules": [],
  "dependsOn": [9, 30],
  "acceptanceCriteria": [],
  "outOfScope": []
}
```

---

## Task 36 — Grid-search оптимизатор параметров стратегии [TRAIN]

**User:** `plans/tasks2.md` §36

```json
{
  "title": "Grid-search оптимизатор параметров стратегии",
  "type": "feat",
  "block": "analysis",
  "modules": ["cf-experiments", "m-analysis"],
  "newModules": [],
  "dependsOn": [8, 11, 15],
  "acceptanceCriteria": [],
  "outOfScope": []
}
```

---

## Task 37 — Шорты в бэктесте [EVAL]

**User:** `plans/tasks2.md` §37

```json
{
  "title": "Шорты в бэктесте",
  "type": "feat",
  "block": "analysis",
  "modules": ["cf-experiments"],
  "newModules": [],
  "dependsOn": [11],
  "acceptanceCriteria": [
    "прогон RsiMeanReversion с allowShort=true на SBER D1 за 2 года → TradeLog содержит сделки с direction=Short",
    "PnL по шорту считается как (entry - exit) * qty - fees",
    "при allowShort=false поведение идентично текущему",
    "детерминизм сохраняется"
  ],
  "outOfScope": ["маржинальные требования и плечо — шорты без учёта ставки"]
}
```

---

## Task 38 — Global search (Cmd-K) [TRAIN]

**User:** `plans/tasks2.md` §38

```json
{
  "title": "Global search (Cmd-K)",
  "type": "feat",
  "block": "polish_and_glue",
  "modules": ["cf-stocks", "cf-workspaces"],
  "newModules": ["modules:features:search", "modules:features-api:search"],
  "dependsOn": [5, 8, 19],
  "acceptanceCriteria": [
    "Cmd-K → появился оверлей",
    "ввод GAZP → 3 секции результатов (Tickers/Workspaces/Runs)",
    "клик по воркспейсу → переход на MainTab с открытым воркспейсом",
    "поиск работает на пустой БД (пустое состояние)",
    "smoke добавлен"
  ],
  "outOfScope": ["полнотекстовый поиск по содержимому RunArtifact"]
}
```

---

## Task 39 — Темы оформления и настройка цветов графика [TRAIN]

**User:** `plans/tasks2.md` §39

```json
{
  "title": "Темы оформления и настройка цветов графика",
  "type": "feat",
  "block": "polish_and_glue",
  "modules": ["theme", "m-settings", "m-main"],
  "newModules": ["modules:features-api:chart"],
  "dependsOn": [],
  "acceptanceCriteria": [
    "выбрать preset 'high-contrast' в settings → график и UI поменяли цвета без перезапуска",
    "ручная настройка цвета бычьей свечи сохраняется между рестартами",
    "smoke добавлен"
  ],
  "outOfScope": ["кастомные шрифты и размеры — только цвета"]
}
```

---

## Task 40 — i18n — вынос строк в resources + английская локаль [TRAIN]

**User:** `plans/tasks2.md` §40

```json
{
  "title": "i18n — вынос строк в resources + английская локаль",
  "type": "feat",
  "block": "polish_and_glue",
  "modules": ["resources", "theme", "utils", "m-main", "m-data", "m-settings"],
  "newModules": [],
  "dependsOn": [],
  "acceptanceCriteria": [
    "переключить язык в settings → UI переключился без рестарта",
    "grep на русскую кириллицу в features/*/ui/ ≤10 оставшихся (в идеале 0)",
    "compileKotlinJvm зелёный"
  ],
  "outOfScope": []
}
```

---

## Task 41 — Универсальный RunArtifact inspector [TRAIN]

**User:** `plans/tasks2.md` §41

```json
{
  "title": "Универсальный RunArtifact inspector",
  "type": "feat",
  "block": "polish_and_glue",
  "modules": ["m-analysis"],
  "newModules": [],
  "dependsOn": [8, 10, 11],
  "acceptanceCriteria": [],
  "outOfScope": ["редактирование артефактов — только просмотр"]
}
```

---

## Task 42 — Tinkoff Invest API как источник [TRAIN]

**User:** `plans/tasks2.md` §42

```json
{
  "title": "Tinkoff Invest API как источник",
  "type": "feat",
  "block": "breadth",
  "modules": ["cf-stocks", "m-data"],
  "newModules": [],
  "dependsOn": [16, 17, 23],
  "acceptanceCriteria": [],
  "outOfScope": []
}
```

---

## Task 43 — Binance spot API — крипто-источник [TRAIN]

**User:** `plans/tasks2.md` §43

```json
{
  "title": "Binance spot API — крипто-источник",
  "type": "feat",
  "block": "breadth",
  "modules": ["cf-stocks", "db"],
  "newModules": [],
  "dependsOn": [16, 23],
  "acceptanceCriteria": [
    "добавить Binance как источник → скачать BTCUSDT 1h за неделю → ≥150 свечей в CandleTable",
    "открыть слот с BTCUSDT → график рисуется как обычно",
    "существующие источники (MOEX/Yahoo) продолжают работать",
    "юнит-тесты на BinanceKlinesParser ≥5 кейсов (валидный ответ, пустой массив, невалидный JSON)"
  ],
  "outOfScope": ["WebSocket live-price — задача 44", "фьючерсы/маржа — только spot"]
}
```

---

## Task 44 — WebSocket live-quotes для Watchlist [TRAIN]

**User:** `plans/tasks2.md` §44

```json
{
  "title": "WebSocket live-quotes для Watchlist",
  "type": "feat",
  "block": "breadth",
  "modules": ["net", "cf-stocks", "m-main"],
  "newModules": [],
  "dependsOn": [18, 43],
  "acceptanceCriteria": [
    "Watchlist с 5 тикерами крипты (Binance) → цены обновляются каждые 1-3 секунды без polling",
    "при уходе экрана с Watchlist → подписка закрывается (grep активных сокетов 0)",
    "переход обратно → переподписка",
    "интеграционный тест на LiveQuoteClient на фикстурном WS-сервере"
  ],
  "outOfScope": ["сохранение live-тиков в БД — только отображение", "live-обновление для графиков (overlay) — только watchlist"]
}
```

---

## Task 45 — iOS WidgetKit аналог Android-виджета [TRAIN]

**User:** `plans/tasks2.md` §45

```json
{
  "title": "iOS WidgetKit аналог Android-виджета",
  "type": "feat",
  "block": "breadth",
  "modules": ["db"],
  "newModules": ["iosApp"],
  "dependsOn": [22],
  "acceptanceCriteria": [],
  "outOfScope": []
}
```

---

## Task 46 — Миграция существующих тестов на DispatcherProvider [TRAIN]

**User:** `plans/tasks2.md` §46

```json
{
  "title": "Миграция существующих тестов на DispatcherProvider",
  "type": "refactor",
  "block": "tech_debt_refactor",
  "modules": ["cf-stocks"],
  "newModules": [],
  "dependsOn": [],
  "acceptanceCriteria": [
    "grep -r 'runBlocking' modules/core/core-features/stocks/src/commonTest/ → 0",
    "grep -r 'Dispatchers\\.' src/commonTest/ → 0",
    "./gradlew :modules:core:core-features:stocks:allTests зелёный",
    "диффы меняют только тестовый код, прод не трогается"
  ],
  "outOfScope": ["инструментальные/Android-тесты — только commonTest", "переписывание тест-логики — только boilerplate"]
}
```

---

## Task 47 — DataStore за интерфейсом PreferencesStore [TRAIN]

**User:** `plans/tasks2.md` §47

```json
{
  "title": "DataStore за интерфейсом PreferencesStore",
  "type": "refactor",
  "block": "tech_debt_refactor",
  "modules": ["utils", "theme", "m-settings", "cf-stocks"],
  "newModules": [],
  "dependsOn": [1],
  "acceptanceCriteria": [
    "grep -r 'import.*DataStore' modules/ --include='*.kt' вне core/utils/data/ → 0",
    "появился PreferencesStoreTest на реализацию (integration)",
    "ThemeRepositoryTest с mock<PreferencesStore> проверяет вызовы",
    "assembleDebug зелёный"
  ],
  "outOfScope": []
}
```

---

## Task 48 — Convention plugin kmp.feature для feature-модулей [TRAIN]

**User:** `plans/tasks2.md` §48

```json
{
  "title": "Convention plugin kmp.feature для feature-модулей",
  "type": "refactor",
  "block": "tech_debt_refactor",
  "modules": ["m-main", "m-data", "m-settings"],
  "newModules": ["build-logic:convention"],
  "dependsOn": [],
  "acceptanceCriteria": [
    "build.gradle.kts среднего feature-модуля ≤30 строк (сейчас ~60)",
    "применение плагина в новом модуле — одна строка plugins { id('kmp.feature') }",
    "./gradlew build зелёный",
    "размер артефактов не изменился"
  ],
  "outOfScope": ["kmp.core-feature plugin для core/core-features/*", "composeApp и mainentry — со своими особенностями"]
}
```

---

## Task 49 — Screen-tests фреймворк на Paparazzi/Roborazzi [TRAIN]

**User:** `plans/tasks2.md` §49

```json
{
  "title": "Screen-tests фреймворк на Paparazzi/Roborazzi",
  "type": "refactor",
  "block": "tech_debt_refactor",
  "modules": [],
  "newModules": [],
  "dependsOn": [7],
  "acceptanceCriteria": [],
  "outOfScope": []
}
```

---

## Task 50 — Smoke fixture generator из fake-данных [TRAIN]

**User:** `plans/tasks2.md` §50

```json
{
  "title": "Smoke fixture generator из fake-данных",
  "type": "refactor",
  "block": "tech_debt_refactor",
  "modules": ["db"],
  "newModules": [],
  "dependsOn": [],
  "acceptanceCriteria": [],
  "outOfScope": ["сами smoke-сценарии — они как читали fixture, так и будут", "live-данные (котировки, свечи) из API — только seed-файлы"]
}
```

---

## Task 51 — Desktop system tray [EVAL]

**User:** `plans/tasks_adversarial.md` §51

```json
{
  "title": "Desktop system tray",
  "type": "feat",
  "block": "breadth",
  "modules": ["utils", "cf-stocks"],
  "newModules": ["composeApp"],
  "dependsOn": [],
  "acceptanceCriteria": [
    "на Desktop при запуске видна иконка в трее",
    "клик 'показать' при свёрнутом окне → разворачивается",
    "кнопка 'остановить' завершает активные download",
    "на Linux без DBus приложение стартует без краха (трей просто отсутствует)"
  ],
  "outOfScope": ["Android tray", "iOS системные иконки"]
}
```

---

## Task 52 — О приложении в Settings [EVAL]

**User:** `plans/tasks_adversarial.md` §52

```json
{
  "title": "О приложении в Settings",
  "type": "feat",
  "block": "polish_and_glue",
  "modules": ["m-settings", "resources"],
  "newModules": [],
  "dependsOn": [],
  "acceptanceCriteria": [
    "в settings пункт 'О приложении' → клик → видна версия, автор, ссылка, changelog (хотя бы последние 5 записей)",
    "ничего не крашит"
  ],
  "outOfScope": ["починка падающего loader при ребуте — отдельный тикет", "тёмная тема на iOS"]
}
```

---

## Task 53 — ShareService expect/actual [TRAIN]

**User:** `plans/tasks_adversarial.md` §53

```json
{
  "title": "ShareService expect/actual",
  "type": "feat",
  "block": "polish_and_glue",
  "modules": ["utils", "m-main", "m-analysis"],
  "newModules": [],
  "dependsOn": [13, 22],
  "acceptanceCriteria": [
    "на слоте кнопка 'Поделиться' → на Android открывается системный chooser",
    "на Desktop URL-ссылка в буфере обмена + toast",
    "на iOS дефолтный activity sheet (UIActivityViewController)",
    "shareService инжектится через Koin во все три платформы"
  ],
  "outOfScope": ["починка кнопки refresh в TickerDetailScreen — отдельный bug fix"]
}
```

---

## Task 54 — Юнит-тесты на CsvParser [EVAL]

**User:** `plans/tasks_adversarial.md` §54

```json
{
  "title": "Юнит-тесты на CsvParser",
  "type": "refactor",
  "block": "tech_debt_refactor",
  "modules": ["cf-stocks"],
  "newModules": [],
  "dependsOn": [],
  "acceptanceCriteria": [],
  "outOfScope": []
}
```

---

## Task 55 — Research: миграция Ktor 2.x → 3.x [TRAIN]

**User:** `plans/tasks_adversarial.md` §55

```json
{
  "title": "Research: миграция Ktor 2.x → 3.x",
  "type": "research",
  "block": "tech_debt_refactor",
  "modules": ["net"],
  "newModules": [],
  "dependsOn": [],
  "acceptanceCriteria": [
    "plans/research/ktor-migration.md с перечнем проблемных мест и оценкой по часам",
    "если пробовал поднять — отдельно зафиксировано что именно падает"
  ],
  "outOfScope": ["изменения в main-ветке — только локальная ветка"]
}
```

---

## Task 56 — Локальная телеметрия ошибок [TRAIN]

**User:** `plans/tasks_adversarial.md` §56

```json
{
  "title": "Локальная телеметрия ошибок",
  "type": "feat",
  "block": "breadth",
  "modules": ["m-settings", "utils"],
  "newModules": ["modules:core:telemetry"],
  "dependsOn": [],
  "acceptanceCriteria": [
    "при возникновении Exception в любом месте — запись в telemetry.db",
    "SettingsScreen → пункт 'Логи' → список последних 100 записей с уровнями",
    "кнопка 'Копировать' → в clipboard JSON"
  ],
  "outOfScope": ["отправка наружу (Sentry, Crashlytics) — только локально"]
}
```

---

## Сводка по split

**TRAIN (45):** 1, 3, 4, 5, 7, 8, 9, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 25, 26, 27, 29, 30, 31, 33, 34, 35, 36, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 53, 55, 56

**EVAL (11):** 2, 6, 10, 13, 24, 28, 32, 37, 51, 52, 54

## Что ещё нужно для финального JSONL (день 7)

Тривиальная сборка скриптом:
1. Загрузить system из `dataset/system.md` (убрать заголовок и markdown-обрамление) как строку.
2. Для каждой задачи — найти prose по ссылке (`plans/tasks1_prose.md §N`), вынуть текст между `## N.` и следующим `## `.
3. Найти соответствующий gold-JSON в этом файле.
4. Собрать: `{"messages":[{"role":"system","content":SYSTEM},{"role":"user","content":PROSE},{"role":"assistant","content":GOLD_JSON_STRING}]}`.
5. Разложить по `dataset/train.jsonl` и `dataset/eval.jsonl` согласно маркерам `[TRAIN]` / `[EVAL]`.

20–30 строк Python.
