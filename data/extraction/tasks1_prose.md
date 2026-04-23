# Tasks 1 — проза задач 1–25 из roadmap

Прозаические рефразы задач из `tasks.md` в формате Slack-тикета — не копипаста структурированного плана, а как бы это описал коллега в чате. Используются как user-вход для датасета экстракции.

Правило: из текста должны **экстрагироваться** все поля gold-JSON (modules, dependsOn, acceptanceCriteria, outOfScope). Ничего не придумываем — что в оригинале не было, того не добавляем.

Часть задач — длиннее (300–500 токенов: 17, 19, 23, 24, 25), часть короче (150–250).

---

## 1. Research архитектуры Workspace / Indicator / Experiment

Перед тем как писать код для новых поддоменов — Workspace, Indicator, Experiment — надо сесть и зафиксировать архитектуру на бумаге. Иначе потом Workspace и Experiment окажутся несовместимы через `ChartSlot` и `IndicatorConfig`, и придётся всё переписывать. Цена правки позже — высокая.

Задача — документ, не код. Нужно нарисовать эскизы таблиц для Workspace, ChartSlot, IndicatorConfig, Experiment, Run, RunArtifact, ChartSegment — поля, FK, ON DELETE. Решить размещение модулей: новые `core/core-features/workspaces`, `core/core-features/indicators`, `core/core-features/experiments`, `features/main` для Workspace UI, `features/analysis` как новый таб, `features-api/pickers` общий. Расписать потоки данных: `WorkspaceCarousel → WorkspaceComponent → ChartSlotComponent → ChartEntryPoint`, `AnalysisTab → ExperimentRunner → RunArtifact`.

Принципиальные развилки, которые надо закрыть: IndicatorConfig привязан к ChartSlot (не к Workspace); ChartSegment живёт в `experiments` (не в `stocks`), но ссылается на `tickerId` и `periodMinutes`. Подобных развилок должно быть хотя бы 5.

Итог — файл `plans/research/architecture.md` содержит: схемы таблиц в виде SQL CREATE; граф зависимостей модулей; перечень ≥5 решённых развилок с кратким «почему». Код не меняется.

---

## 2. БД и домен Workspace + ChartSlot

Персистентное ядро под воркспейсы и слоты — чтобы они переживали рестарт, переупорядочивались, удалялись.

SQLDelight — `Workspace.sq` и `ChartSlot.sq` в `core/db`. Поля: `Workspace(id, title, orderIndex, createdAt)`, `ChartSlot(id, workspaceId, tickerId, periodMinutes, orderIndex, viewportFromTs, viewportToTs)`, ON DELETE CASCADE от Workspace к Slot.

Создать новый модуль `core/core-features/workspaces` по шаблону `stocks`: `domain/model`, `domain/repository`, `data/repository`, `data/mapper`, `domain/usecase`, `di/workspacesModule.kt`. Use cases: `GetWorkspacesUseCase` (Flow), `CreateWorkspaceUseCase`, `RenameWorkspaceUseCase`, `DeleteWorkspaceUseCase`, `ReorderWorkspacesUseCase`, `AddChartSlotUseCase(workspaceId, tickerId, periodMinutes)`, `RemoveChartSlotUseCase`, `ReorderChartSlotsUseCase`, `UpdateSlotViewportUseCase`. Зарегистрировать `workspacesModule` в `mainentry` — `AppKoinInitializer.appModules()` после `stocksModule`.

Нужна готовая research-задача 1 — там решается структура таблиц и куда что привязано.

Пока никакого UI, индикаторов, автодогрузки свечей — только домен и БД.

Приёмка: `./gradlew :composeApp:compileKotlinJvm` зелёный; commonTest на 2–3 ключевых use case (`CreateWorkspace`, `ReorderWorkspaces`, `AddChartSlot`) по правилам `.claude/rules/testing.md` (Mokkery + Turbine + runTest); ручной smoke через интеграционный тест или временный init-блок — создать workspace + slot, перезапустить, данные на месте.

---

## 3. Таб Main: карусель воркспейсов

Главный таб сейчас заглушка. Пора превратить в живую карусель воркспейсов со свайпом и индикатором страниц.

Переделать на `DefaultMainTabComponent` (уже есть) → внутри `WorkspaceCarouselComponent` через Decompose `ChildPages<WorkspaceConfig, WorkspaceComponent>`. Источник страниц — `GetWorkspacesUseCase` из задачи 2. Сам `WorkspaceComponent` пока пустой — заголовок воркспейса и CTA «Добавить график». Наполнение слотами идёт в задаче 4.

Empty state: если воркспейсов нет — единый экран «Создать первый воркспейс» с кнопкой, которая дёргает `CreateWorkspaceUseCase("Без названия")`. Плюс горизонтальный свайп между воркспейсами и индикатор страниц снизу.

Для индикатора страниц — либо штатный Compose Pager indicator, либо добавить `PageIndicator` в `uikit` (если понадобится повторно в Analysis).

Зависит от задачи 2 — без use case воркспейсов рендерить нечего.

Пока не делаем: добавление слотов, рендер графика, индикаторы, редактирование (rename/delete — в задаче 5).

Приёмка: smoke — старт на главном табе → empty state → создать воркспейс → появился; создать второй → свайп работает → индикатор страниц отражает активную страницу. При быстром листании не крашит, состояние воркспейса сохраняется между страницами. Код соблюдает `features-module.md`: `Component interface + Default...Component`, `dispose` стора в `doOnDestroy`, `ComponentContext` через Koin `parametersOf`.

---

## 4. ChartSlot с графиком и автодогрузкой свечей

Воркспейс из задачи 3 пустой — надо наполнить живыми свечными графиками, которые сами подтягивают данные из БД и догружают недостающее.

Внутри `WorkspaceComponent` — `ChartSlotComponent` с собственным Store: флаги `isLoading/isDownloading`, кандлы (PersistentList, не List), viewport, ticker/period. Маппинг `Candle → ChartComponent.CandleUiModel` через `ChartSlotStateMapper` — UiModel живёт в интерфейсе `ChartComponent` из `features-api/chart` (правило features-module.md: реюзабельный UI-компонент живёт со своим UiModel).

Ключевая новая штука — `EnsureCandlesUseCase(tickerId, periodMinutes, fromTs, toTs)` в `core-features/stocks`. Проверяет `TickerPeriodMeta`, вычисляет недостающие диапазоны, ставит `DownloadTask` через `CreateDownloadTaskUseCase`, возвращает `Flow<CandleRange>`. Рендер слота — через существующий `ChartEntryPoint` из `features-api/chart`, никакого второго рендера свечей.

Сохранение viewport в БД — `UpdateSlotViewportUseCase` с дебаунсом ~500 мс.

Зависит от задач 2 и 3.

Пока не делаем: UI добавления слота через интерфейс (слот создаётся фикстурой или временной кнопкой), индикаторы, pinch-zoom жесты (если они не из коробки в существующем рендере).

Приёмка: воркспейс с двумя слотами (GAZP D1, SBER D1) при первом открытии ставит задачи загрузки и отображает свечи по мере поступления; после рестарта viewport каждого слота восстанавливается (±100 мс); smoke — слот с уже загруженными данными открывается без дополнительной сетевой активности (проверяется отсутствием новой записи в `DownloadTask`).

---

## 5. CRUD воркспейсов/слотов + общий Ticker/Period Picker

Пользователь должен полноценно управлять содержимым: переименовать, удалить, переупорядочить воркспейсы; добавить слот через выбор тикера.

Редактор воркспейса — bottom sheet или отдельный экран `WorkspaceEditorComponent`: rename, delete (с подтверждением), drag-to-reorder слотов, удаление слота. В самой карусели — добавление воркспейса и их переупорядочивание (long-press на индикаторе страниц → режим редактирования или пункт меню).

Отдельная важная часть — новый модуль `features-api/pickers`. По правилу `features-module.md`: если компонент используется из ≥2 мест (сейчас воркспейсы, потом эксперименты), заводим api-модуль: `TickerPickerInput`, `TickerPickerComponent`, `TickerPickerEntryPoint`, `PeriodPickerEntryPoint`. Реализация — новый `features/pickers`. Picker тикера переиспользует `GetAllTickersWithQuoteAndMarketUseCase` из `core-features/stocks`. Открытие пикера из редактора → возврат `(tickerId, periodMinutes)` через label или callback → `AddChartSlotUseCase`.

В uikit добавить `DraggableList`/`ReorderableList` (если нет — понадобится также для индикаторов и сегментов). Bottom sheet — штатный Material3.

Зависит от задачи 4.

Пока не делаем: поиск по тикеру (stretch — можно добавить поле поиска, но не ветку избранного/истории).

Приёмка: smoke — создать/переименовать/удалить workspace; через picker добавить 2 слота; поменять их порядок drag'ом; удалить один слот. Архитектурное: `features-api/pickers` не зависит от `uikit`, `features/pickers`, `core/core-features/stocks` (в api-модуле только интерфейс + Input + EntryPoint). `features/main` и будущий `features/analysis` обращаются к пикеру ТОЛЬКО через `TickerPickerEntryPoint` из `features-api/pickers`, не через конкретную реализацию.

---

## 6. Движок индикаторов — домен + каталог + тесты

Нужно чистое и оттестированное ядро расчёта индикаторов. Будет фундаментом и для графиков, и для сегментации, и для бэктеста. Принципиально: никакой UI-логики внутри.

Новый модуль `core/core-features/indicators` по шаблону stocks: `domain/model`, `domain/calculator`, `domain/catalog`, `data/cache`, `di/indicatorsModule.kt`.

Модели: `IndicatorDefinition(id, title, kind=Overlay|Panel, paramsSpec: List<ParamSpec>)`, `ParamSpec(name, kind=Int|Double|Enum, default, min, max)`, `IndicatorParams(values: Map<String, Any>)`, `IndicatorSeries(points: List<Double?>, meta)`.

Интерфейс `IndicatorCalculator { fun calculate(candles, params): IndicatorSeries }` + реализации SMA, EMA, RSI, MACD, Bollinger, ATR — всё на чистом Kotlin, без корутин.

Каталог: `IndicatorCatalog { fun all(): PersistentList<IndicatorDefinition>; fun calculatorFor(id): IndicatorCalculator }`. Кэш `IndicatorCache` с ключом `(slotId, configId, paramsHash, candlesRangeHash)`, значение — `IndicatorSeries`, LRU или time-bound.

Зависит от задачи 1.

Приёмка: `./gradlew :modules:core:core-features:indicators:allTests` зелёный; покрытие калькуляторов ≥80%, эталонные значения сверены с TradingView/Wikipedia; нет зависимостей на androidx, Compose, Decompose, Ktor, SQLDelight; `IndicatorCatalog.all()` возвращает 6 индикаторов с корректными `paramsSpec`.

---

## 7. IndicatorConfig: персист и рендер на ChartSlot

Пользователь добавляет индикаторы к графику, настраивает параметры, всё это сохраняется. При следующем открытии слота индикаторы восстанавливаются и рисуются поверх или под свечами.

SQLDelight: `IndicatorConfig(id, chartSlotId, indicatorId, paramsJson, styleJson, enabled, orderIndex)` — персистенция в `core/db`, ON DELETE CASCADE от ChartSlot. Use cases: `GetIndicatorsForSlot` (Flow), `UpsertIndicatorConfig`, `RemoveIndicatorConfig`, `ReorderIndicatorConfigs` — место живёт в `cf-workspaces` либо `cf-indicators`, решается в research задачи 1.

UI добавления — bottom sheet `IndicatorPickerContent`: список из `IndicatorCatalog.all()` + форма параметров (spec-driven, рендерится из `paramsSpec`). UI списка индикаторов слота — кнопки edit / toggle / delete / drag-reorder.

Рендер: overlay-индикаторы (SMA/EMA/Bollinger) внутри области свечей; panel-индикаторы (RSI/MACD/ATR) в отдельных панелях под графиком. Пересчёт через `IndicatorCache`.

В uikit добавить: `IndicatorPanelStack` (стек панелей под графиком с собственной осью Y), `IndicatorOverlayLayer` (слой поверх свечного рендера; принимает `PersistentList<IndicatorSeriesUiModel>`), `ParamSpecForm` (Int/Double/Enum — понадобится в экспериментах).

Зависит от задач 4 и 6.

Пока не делаем: пользовательские формулы (backlog задачи 6), пресеты (задача 14).

Приёмка: smoke — на слоте GAZP D1 добавить EMA(20) + RSI(14) → видны overlay и panel; рестарт приложения → они на месте; изменить период EMA → график перерисовался; выключить RSI → панель исчезла; удалить → конфиг из БД ушёл. Скролл по графику при включённых индикаторах — без заметных лагов (повторные открытия используют кэш). Spec-driven форма корректно валидирует границы min/max, Int vs Double.

---

## 8. Таб Анализ + каркас ExperimentRunner

Третий таб со списком экспериментов и историей прогонов. Главная идея: добавление нового эксперимента должно сводиться к реализации одного интерфейса `ExperimentExecutor`.

`RootConfig.AnalysisTab` + `AnalysisTabComponent` + регистрация нового таба Analysis в `mainentry` и bottom navigation.

Новый модуль `core/core-features/experiments`: `domain/model` (Experiment, ExperimentKind, Run, RunStatus, RunArtifact, ArtifactKind), `domain/service/ExperimentRunner`, `domain/service/ExperimentExecutor`, `data/repository`, `di/experimentsModule.kt`. SQLDelight-таблицы в `core/db`: `Experiment` (каталог фактически в коде, не в БД, или seed-данные), `Run(id, experimentKind, inputSpecJson, paramsJson, status, startedAt, finishedAt, errorText)`, `RunArtifact(id, runId, kind, payloadJson, blobPath)`.

`ExperimentRunner` — data-layer singleton: инжектится `CoroutineScope` (named qualifier по CLAUDE.md «Coroutine Patterns») + `DispatcherProvider`; хранит активные прогоны, транслирует `Flow<RunProgress>`.

Новый модуль `features/analysis`: `AnalysisTabComponent` (список + история), `RunDetailComponent` (параметры/артефакты). Стартовый `ExperimentExecutor` — «Echo»: на вход `ticker+period`, на выход артефакт со статистикой по свечам (count, min/max ts, средний volume). Цель — проверить каркас end-to-end.

UI-компоненты в `uikit`: `ExperimentCard` (для списка), `RunStatusBadge`, таблица параметров — добавить если не будет дешевле inline в фиче (решать по месту).

Зависит от задачи 1.

Приёмка: smoke — перейти на таб Анализ → виден список с одним Echo → запустить на GAZP D1 → прогон появился в истории RUNNING → FINISHED → открыть RunDetail → параметры и артефакт видны. Отменённый прогон переходит в `CANCELLED`, артефакт не создаётся. `ExperimentRunner` не использует `GlobalScope` и `Dispatchers.*` напрямую.

---

## 9. Эксперимент: сегментация графика по правилу

Появляется механика накопления размеченного датасета «кусков графика»: пользователь задаёт правило — система бежит по истории и сохраняет сегменты.

SQLDelight: `ChartSegment(id, tickerId, periodMinutes, fromTs, toTs, ruleId, ruleParamsJson, label, featuresJson, runId)`.

`SegmentationExecutor : ExperimentExecutor` в `core-features/experiments`. Стартовые правила, выбираются enum'ом:
- `RsiOverboughtOversold(indicatorParams, threshold=70/30)` — сегмент = непрерывный отрезок, где RSI > 70 или < 30.
- `AtrBreakout(atrPeriod, k)` — сегмент = отрезок, где `|close - close[-N]|` > `k * ATR`.

Use cases: `GetSegmentsUseCase`, `DeleteSegmentsByRunUseCase`.

Визуализация на Workspace: при открытии слота подтягивать релевантные сегменты (по ticker+period) и рисовать подсветкой (опционально включается в IndicatorPanel). RunDetail эксперимента: таблица сегментов (from/to/длительность/label), кнопка «Открыть в воркспейсе».

В uikit: `SegmentOverlayLayer` — полупрозрачные прямоугольники поверх области свечей, цветовое кодирование по `label`. Возможно понадобится добавить в `ChartComponent.Input` из `features-api/chart` поле `overlayRegions`.

Зависит от задач 6, 7, 8.

Пока не делаем: ручное редактирование сегментов (пересечение, объединение, ручная метка); кастомные правила.

Приёмка: запуск на GAZP D1 с `RsiOverboughtOversold(14, 70/30)` → ≥N сегментов в БД (эталонное число сверяется ручным просмотром), артефакт содержит сводку; из RunDetail «Открыть в воркспейсе» → слот открывается с подсветкой сегментов; повторный запуск с теми же параметрами не дублирует сегменты (удаление старых по `runId` либо проверка ключа).

---

## 10. Эксперимент: метрики по серии сегментов

Первая настоящая аналитика над накопленным датасетом: взять выборку сегментов, посчитать набор метрик, показать агрегаты и распределения.

`SegmentMetricsExecutor : ExperimentExecutor`. Вход: фильтр сегментов (по ticker, period, ruleId, диапазону дат). Метрики: средняя длительность, распределение длительности, внутрисегментная доходность `(close_last - close_first) / close_first`, max drawdown внутри сегмента, доля прибыльных, корреляция длительности и доходности.

Артефакты: `MetricsSummary` (таблица), `DurationHistogram`, `ReturnHistogram`, `DurationReturnScatter` — каждый как `RunArtifact(kind=..., payloadJson)`. RunDetail UI — табы «Summary / Distributions / Scatter»; для визуализаций — чарты из uikit.

Фильтр-форма — `ParamSpecForm` из задачи 7, плюс специфика: multi-select тикеров через `TickerPickerEntryPoint`.

В uikit добавить (переиспользуется в 11, 12): `LineChart` (equity/временные ряды), `HistogramChart`, `ScatterChart`.

Зависит от задач 8 и 9.

Приёмка: запуск без фильтра на N накопленных сегментах → артефакты сформированы, графики отображаются; смена фильтра (например, конкретный тикер) → новый Run с отличающимися метриками; пустая выборка (нет сегментов под фильтр) не крашит, Run завершается со статусом `FINISHED_EMPTY`.

---

## 11. Эксперимент: бэктест стратегии индикаторов

Симулятор торговли на исторических свечах — журнал сделок, кривая капитала, ключевые метрики (PnL, drawdown, winrate, Sharpe).

`BacktestExecutor : ExperimentExecutor`. Вход: `ticker+period+диапазон`, стратегия. Стартовый набор:
- `EmaCross(fast, slow)` — покупка при пересечении вверх, продажа при пересечении вниз.
- `RsiMeanReversion(period, buyBelow, sellAbove)`.
- `BollingerBreakout(period, stdDevK)`.

Движок событий — детерминированный bar-by-bar, один открытый long-position одновременно, комиссия/проскальзывание параметрами стратегии.

Артефакты: `TradeLog` (таблица сделок), `EquityCurve` (временной ряд), `BacktestSummary` (PnL, max drawdown, winrate, average trade, Sharpe, trades count). RunDetail — табы «Summary / Equity / Trades / Parameters»; Equity использует `LineChart` из задачи 10; таблица сделок сортируемая.

Uikit: `EquityChart` (если отличается от LineChart — например, с подсветкой drawdown), `TradeRow`. Остальное — `LineChart`/таблица из задачи 10.

Зависит от задач 6, 8, 10.

Пока не делаем: короткие позиции, пирамидинг, мультитикерные стратегии, оптимизатор параметров (последнее — кандидат в задачу 15).

Приёмка: `EmaCross(9, 21)` на SBER D1 за 2 года → ≥10 сделок, equity и метрики отображаются; повторный запуск с теми же параметрами даёт идентичный результат (детерминизм); smoke — клик по сделке в таблице → переход на `WorkspaceMain` с подсветкой бара входа/выхода (reuse механики задачи 9).

---

## 12. Вынос графических компонентов в core/uikit

Чартовые и табличные компоненты сейчас дублируются между Workspace и Analysis. Пора вытащить их в uikit и стабилизировать API визуализации.

Ревизия: что сейчас фактически живёт в `uikit`, что в `features/main`, что в `features/analysis`. Список — в документ `plans/research/uikit-inventory.md` с описанием и примером использования каждого публичного компонента.

Перенести в uikit: `IndicatorPanelStack`, `IndicatorOverlayLayer`, `SegmentOverlayLayer`, `LineChart`, `HistogramChart`, `ScatterChart`, `EquityChart`, `ParamSpecForm`, `DraggableList` (если ещё не там).

Все компоненты должны принимать `PersistentList`/`ImmutableList` — проверить и починить где нарушено. Для каждого компонента — свой UiModel в uikit (правило: реюзабельный UI-компонент живёт со своим UiModel).

Зависит от задач 7, 10, 11. Делать после того, как компоненты уже кристаллизовались в фичах, а не до — иначе абстракция будет неправильной.

Пока не делаем: переписывание визуального стиля, новые типы графиков, theming (это отдельная тема).

Приёмка: `./gradlew assembleDebug` зелёный, все существующие smoke проходят. `features/main` и `features/analysis` не содержат Canvas-рендеров — grep на `Canvas(`, `drawLine`, `drawRect` в features/* даёт результаты только в uikit. Документ `plans/research/uikit-inventory.md` перечисляет публичные компоненты `uikit`.

---

## 13. Кросс-навигация: открыть тикер в Workspace

Быстрый флоу из каталога (DataTab) и из результатов эксперимента: «добавить этот тикер в воркспейс» — без ручного поиска в пикере.

На экранах `QuoteDetailScreen` и `TickerDetailScreen` (features/data) и на элементах RunArtifact в features/analysis — кнопка «В воркспейс». Навигация из MainTab в `features/main` переключает на нужный воркспейс. Диалог выбора воркспейса (существующие + «Создать новый») — компонент из нового минимального модуля `features-api/workspaces`: `AddToWorkspaceEntryPoint` + `AddToWorkspaceInput(tickerId, periodMinutes)`. После подтверждения → `AddChartSlotUseCase` → переключение bottom navigation на MainTab + `selectPage(workspaceIndex)`.

Uikit: `WorkspacePickerDialog` — если попадает под реюз, в uikit; иначе inline.

Зависит от задач 5 и 11.

Пока не делаем: глубокое диплинкование (URL-схемы), shortcuts на рабочем столе.

Приёмка: smoke — из каталога DataTab выбрать тикер → «В воркспейс» → диалог → выбрать воркспейс → переход на MainTab, нужный workspace открыт, слот в нём появился. Тот же флоу из TradeRow задачи 11 — открывает workspace с тем же ticker/period.

---

## 14. Экспорт/импорт воркспейсов и пресетов индикаторов

Перенос состояния между устройствами, бэкап, шеринг — нужна сериализация в JSON.

`WorkspaceSnapshot(title, slots: List<SlotSnapshot>)`, где `SlotSnapshot(tickerCode, marketCode, periodMinutes, indicators: List<IndicatorConfigSnapshot>)`. Сериализация через `kotlinx.serialization`. Тикер/маркет по **кодам**, не по id — устройства разные.

Use cases: `ExportWorkspaceUseCase(workspaceId): String`, `ImportWorkspaceUseCase(json): WorkspaceId`. Импорт резолвит ticker/market по коду; если отсутствует — возвращает `ImportResult.MissingReferences`.

Пресеты индикаторов: `IndicatorPreset(name, items: List<IndicatorConfigSnapshot>)` — отдельная таблица `IndicatorPreset`, экспорт/импорт аналогично.

UI: в редакторе воркспейса — пункты «Экспорт в файл» / «Импорт из файла»; на выборе индикаторов — «Применить пресет» / «Сохранить как пресет». Платформенный FilePicker — `expect/actual` в `core/utils` (или использовать существующий — проверить); минимальная реализация Android+Desktop.

Зависит от задач 5 и 7.

Пока не делаем: облачную синхронизацию (задача 21), QR-шеринг, iOS FilePicker (если некритично — заглушку).

Приёмка: экспорт воркспейса с 3 слотами и 2 индикаторами → JSON-файл валиден, проходит `Json.decodeFromString<WorkspaceSnapshot>`; импорт на чистой БД (с теми же справочниками Ticker/Market) восстанавливает воркспейс идентично — те же слоты в том же порядке с теми же индикаторами; импорт при отсутствующем тикере — показывает список отсутствующих кодов и не создаёт частичный воркспейс.

---

## 15. Батч-прогон эксперимента + сравнение прогонов

Проверять стратегию не на одном тикере, а на списке; сравнивать два прогона с разными параметрами бок о бок.

Расширение `ExperimentRunner` и `Run`: `inputSpec.tickers: List<TickerRef>` или отдельный `BatchRun` (решить по месту). Агрегированные артефакты: `BatchSummary` (таблица метрик по тикерам), `BatchEquityAggregate`.

UI на AnalysisTab: multi-select тикеров через пикер из задачи 5 (возможно, потребует доработки пикера под мультивыбор — оценить до старта). RunCompare-экран: выбрать 2 прогона из истории → боковое сравнение Summary, Equity, ключевых метрик. Сортировка/фильтрация истории Run по метрикам.

Uikit: `CompareLayout` (двухколоночная раскладка с синхронизированным скроллом), `MultiLineChart` (наложить 2 кривые).

Зависит от задач 5, 10, 11.

Пока не делаем: оптимизатор параметров (grid search) — отдельная будущая задача.

Приёмка: батч-прогон `EmaCross(9, 21)` на 10 тикерах → таблица с метриками по каждому, сортировка по PnL работает; Compare двух Run с разными параметрами `EmaCross` на одном тикере → видны обе equity и разница метрик.

---

## 16. Yahoo Finance как встроенный источник + импорт пресетов по URL

Снизить зависимость от единственного источника (MOEX) — добавить бесплатный международный. Заодно открыть механику шаринга пресетов ссылкой.

Новый builtin-пресет `yahoo_finance.json` в `core/core-features/stocks/presets/...` рядом с существующими. Endpoint: `https://query1.finance.yahoo.com/v7/finance/download/{symbol}?period1={from}&period2={to}&interval={interval}`.

Проверить и при необходимости расширить `PlaceholderResolver` / `PlaceholderContext` (Unix-секунды vs миллисекунды, формат интервала `1d`/`1h`/`5m`). Адаптировать `CsvParser` под заголовки Yahoo `Date,Open,High,Low,Close,Adj Close,Volume` — колонка `Adj Close` игнорируется.

`SourceTickerMapping` — у Yahoo другие коды (`GAZP` → `GAZP.ME`); примеры маппинга включить в пресет.

`ImportPresetFromUrlUseCase(url): SourcePreset` — скачивает JSON-пресет по URL, валидирует через существующий `SourcePresetParser` (уже есть для локальных), создаёт Source. UI — пункт «Импорт из URL» в `SourceListScreen`.

Пока не делаем: OAuth/auth (задача 17), автомаппинг тикеров между MOEX и Yahoo (только ручной).

Приёмка: smoke — добавить Yahoo как источник → создать маппинг `GAZP → GAZP.ME` → скачать дневки за год → ≥200 свечей в `CandleTable`; импорт валидного JSON-пресета по URL создаёт Source со всеми маркет/период-маппингами; невалидный URL или JSON → error dialog, ничего не создаётся; юнит-тесты на `CsvParser` с Yahoo-форматом заголовков.

---

## 17. Авторизованные источники: Alor OpenAPI

Расширить движок Source под API с OAuth-авторизацией и добавить Alor OpenAPI — первый реалистичный брокерский источник. Открывает путь к Portfolio (задача 20) с автосинком позиций.

**Research-часть.** Документ `plans/research/authorized-sources.md`: анализ текущего `Source`/`SourceParam`, варианты расширения — поле `authConfigJson` в `Source` vs отдельная таблица `SourceAuth` 1-к-1; схема refresh-token-flow для Alor; выбор решения с аргументацией.

**Модель.** Новый домен `SourceAuthConfig(kind=OAuth2RefreshToken, tokenEndpoint, clientId, ...)`. Миграция БД.

**Secure-стор.** `SecureStorage` — `expect/actual` в `core/utils`: Android Keystore, iOS Keychain, Desktop — DPAPI/keyring. Refresh-токены хранить **только** там, в plaintext на диске они лежать не должны ни при каких условиях.

**HTTP.** Расширение Ktor HttpClient в `core/network`: `Auth` plugin с `bearerTokens` + refresh при 401. Отдельный `AuthorizedHttpClient` — используется только для авторизованных источников, чтобы не тянуть auth-interceptor на MOEX/Yahoo.

**Alor preset + UI ввода учётных данных** (один раз при создании Source).

Зависит от задачи 16 (чтобы уже был отработан сценарий «новый источник»), но технически независимо.

Пока не делаем: торговые операции через Alor (только чтение истории). Автосинк позиций — Portfolio (задача 20), интеграция — stretch.

Приёмка:
- документ с выбором решения принят;
- настроенный Alor-источник скачивает свечи для тикера MOEX;
- refresh-токен обновляется автоматически при протухании access-токена (unit-тест с подменённым временем или ручной с коротким TTL);
- `grep encodeToString(.*RefreshToken)` / `plaintext` по репо — нет утечек в DataStore/файлы.

---

## 18. Watchlist — избранные тикеры с последними ценами

Быстрый табличный взгляд на N интересных тикеров без открытия графика. Отдельный UX от Workspace: таблица vs чарты.

БД: `WatchlistItem(id, tickerId, orderIndex, addedAt)`.

Новый модуль-фича или раздел: либо `features/main` с отдельным экраном, либо **первый** слот в карусели с типом `WATCHLIST` (spec-решение). Рекомендация — отдельный экран, доступный из `TopBar` на главном, чтобы не смешивать сущности.

Use cases: `AddToWatchlistUseCase`, `RemoveFromWatchlistUseCase`, `ReorderWatchlistUseCase`, `GetWatchlistWithLastQuoteUseCase` — Flow, объединяет `WatchlistItem` + последняя Candle D1 из `CandleRepository`.

В `TickerDetailScreen` / `QuoteDetailScreen` (features/data) — кнопка «В избранное». Клик по строке — кросс-навигация в Workspace (reuse задачи 13).

Uikit: `WatchlistRow` — тикер, цена, дельта; переиспользует `PercentChangeBadge` (новый компонент с цветовой кодировкой +/-).

Зависит от задачи 4 (ChartSlot с viewport — без него нечего показывать в кросс-навигации), а также задач 2–5 (Workspace для кросс-навигации), желательно 13.

Пока не делаем: push-уведомления по цене (задача 19), сортировки/фильтры (stretch).

Приёмка: smoke — добавить 3 тикера из каталога в watchlist → открыть Watchlist → 3 строки с последними ценами; переупорядочить; удалить один; клик по строке → открыт воркспейс с этим тикером. При обновлении Candle (новая скачанная свеча) — значение в watchlist обновляется без ручного рефреша.

---

## 19. AlertEngine + локальные уведомления

Получать локальное уведомление при срабатывании условия на индикаторе или цене: «RSI(14) пересёк 70 на GAZP D1», «цена SBER пересекла SMA(200) снизу». Первый полезный сценарий пассивного использования приложения.

**Domain.** Новый модуль `core/core-features/alerts`: `AlertRule(id, tickerId, periodMinutes, kind, configJson, enabled, createdAt)`, `AlertEvent(id, ruleId, triggeredAt, snapshotJson)`. Виды: `IndicatorThreshold(indicatorId, params, operator=Above|Below|CrossAbove|CrossBelow, value)`, `PriceCrossIndicator(indicatorId, params, direction)`.

**Evaluator.** `AlertEvaluator` — data-layer singleton (корутин-scope + DispatcherProvider по CLAUDE.md). Подписывается на Flow новых свечей (или хук в `ChunkedCandleDownloader` на завершение чанка). Для каждого активного правила считает индикатор через `IndicatorCatalog` из `core-features/indicators` (задача 6), сравнивает с предыдущим значением, при срабатывании пишет `AlertEvent` + вызывает `NotificationService`.

**NotificationService.** `expect/actual` в `core/utils`:
- Android — `NotificationManagerCompat`, канал `stocks_alerts`.
- iOS — `UNUserNotificationCenter` (локальная, без push-сервера).
- Desktop — системный tray / `java.awt.SystemTray`; fallback — in-app toast.

**UI.** Новый экран (`features/alerts` — NEW либо как раздел settings): список правил, создание (Ticker picker + Period + тип условия + spec-driven форма параметров через `ParamSpecForm` из задачи 7), лог `AlertEvent`.

**Глубокая ссылка.** Тап по уведомлению → открыть воркспейс с этим тикером + подсветить последнюю свечу.

Зависит от задач 3 и 4 (карусель воркспейсов и ChartSlot для deep link), задачи 6 (индикаторы), задач 2–5 в целом.

Пока не делаем: push через Firebase/APNs (offline-only, локальные); алерты с сервера; WebSocket-подписки — работает только на свежескачанных свечах.

Приёмка:
- smoke — правило «RSI(14) > 70 на GAZP D1» + enabled → после прихода свечи с RSI > 70 (можно fixture'ом подделать) — notification получен + запись в `AlertEvent` создана;
- правило `disabled` не срабатывает;
- клик по уведомлению в Android → приложение открывается на соответствующем воркспейсе;
- нет `GlobalScope`, нет `Dispatchers.*` напрямую в `AlertEvaluator`.

---

## 20. Portfolio — учёт позиций и P&L

Ручной трекинг открытых позиций с автоматическим расчётом unrealized/realized P&L по текущей цене. Первый мост к «трейдерскому» сценарию использования.

**Domain.** Новый модуль `core/core-features/portfolio`: `Position(id, tickerId, direction=Long|Short, entryPrice, quantity, entryTs, exitPrice?, exitTs?, fees, note)`, `PortfolioSummary(totalRealized, totalUnrealized, byTicker)`.

**Расчёт.** `GetPositionsWithLivePnlUseCase` — Flow, объединяет позиции с последней Candle через `CandleRepository`. Формулы: unrealized = `(currentPrice - entryPrice) * quantity - fees`, для short — знак инвертирован; realized для закрытых.

**UI.** Экран списка позиций (открытые / закрытые табами), форма открытия/закрытия/редактирования позиции (Ticker picker из `fa-pickers` + числовые поля), сводка сверху (total unrealized / total realized / total fees).

**CSV-импорт позиций.** Минимальный: загрузка файла с колонками `ticker,direction,entry_price,quantity,entry_ts` для быстрого занесения ретро-данных.

Uikit: `PositionCard`, `PnlBadge` (цвет по знаку), `MoneyText` с форматированием, `DirectionChip`.

Зависит от задачи 2 (базовые use case по тикерам), 5 (picker). Независимо от индикаторов/экспериментов.

Пока не делаем: автосинк с Alor (stretch на стыке 17 и 20), налоги, multi-currency.

Приёмка: smoke — открыть позицию SBER Long 100 @ 250 → unrealized P&L считается по текущей свече; закрыть по 270 → realized = `(270 − 250) × 100 − fees`; суммы в сводке корректные; импорт CSV на 10 позиций создаёт их все — невалидные строки выводятся в error list, валидные применяются; при переключении бэкенда свечей (Yahoo/MOEX) P&L использует актуальный источник для тикера.

---

## 21. Cloud sync — выбор стратегии и границ

Определить архитектуру синхронизации **до** её реализации. Цена ошибки высокая: неправильный выбор бэкенда или модели конфликтов даёт месяцы технического долга.

Сравнение вариантов: Firebase Firestore, Supabase, собственный бэкенд (Ktor Server + Postgres), CRDT-подход (Yjs / Automerge). Ограничения: KMP-совместимость SDK; App Store review (запрет сторонних бэкендов для некоторых кейсов); приватность (биржевые данные + позиции — PII?); стоимость.

**Границы sync.** Что синкать: workspaces + indicator-presets (критично), alert-rules (желательно), portfolio (желательно), свечи (NO — слишком много данных), Run/RunArtifact (NO — локальные).

**Модель конфликтов.** Last-write-wins vs vector clocks vs user-prompt.

**Auth.** Анонимный ID vs Google/Apple sign-in vs email.

Отдельно — что минимально реализовать в MVP (например, только workspaces + indicator-presets, last-write-wins, anonymous ID).

Зависит от задачи 14 — ручной экспорт/импорт это фактический baseline, который cloud sync должен превзойти.

Приёмка: документ `plans/research/cloud-sync.md` содержит таблицу сравнения вариантов, выбранный вариант с аргументацией, диаграмму потока данных, список задач для MVP-реализации с оценкой по дням. Код не меняется.

---

## 22. Android Widget + App Shortcuts

Платформенная интеграция: виджет Watchlist на домашнем экране Android + быстрые действия через long-press иконки приложения.

**Widget.** Glance-based (Jetpack Compose Glance) виджет `WatchlistWidget`: отображает до 5 тикеров из Watchlist с ценой и дельтой, обновляется по расписанию (WorkManager 15-минутный периодический) или по изменению `WatchlistItem`. Тап по строке → deep link в приложение на соответствующий воркспейс.

**Shortcuts.** `AndroidManifest.xml` + `shortcuts.xml` + dynamic shortcuts через `ShortcutManagerCompat`: «Открыть Watchlist», «Открыть последний воркспейс», «Запустить последний эксперимент». До 4 штук, динамические для «последних».

**Deep-link routing.** Расширить `RootConfig` или навигацию в `mainentry` под URI-схему: `stocks://workspace/{id}`, `stocks://watchlist`, `stocks://experiment/{id}/rerun`.

Модули: Android-специфичный код живёт в `composeApp/androidMain` (widget provider, shortcuts xml); deep-link routing в `modules/mainentry`.

Zависит от задачи 18 (Watchlist), 3 (Workspace навигация).

Пока не делаем: iOS widgets, iOS shortcuts (требуют отдельной SwiftUI-работы, KMP здесь не помогает); Desktop-tray.

Uikit: виджет использует Glance-компоненты (отдельная композиция, не Compose UI) — нельзя переиспользовать `WatchlistRow` из основного `uikit`. Это нормальное ограничение Glance.

Приёмка:
- виджет добавляется на рабочий стол Android, показывает актуальные данные из Watchlist, тап открывает приложение на воркспейсе соответствующего тикера;
- long-press иконки приложения — видны 3 shortcut'а, каждый открывает приложение в правильном месте;
- deep-link URL из `adb shell am start -a android.intent.action.VIEW -d stocks://workspace/1` открывает нужный воркспейс (как smoke-проверка).

---

## 23. Изоляция Ktor HttpClient через API-слой

Убрать `HttpClient` из бизнес-кода `core-features/stocks`; открыть дверь для нескольких источников данных (MOEX, Yahoo, Alor) без дублирования HTTP-boilerplate; восстановить тестируемость `DefaultChunkedCandleDownloader` и всех будущих сервисов загрузки.

**Research-часть** — компактный параграф в `plans/research/network-isolation.md`, не отдельный большой документ. Два слоя или один?
- Вариант A: **один слой** — `CandleFetcher(source, ticker, period, range): List<Candle>` в `core-features/stocks/domain/remote`, реализации `MoexCandleFetcher`, `YahooCandleFetcher`, `AlorCandleFetcher` в data/remote. HttpClient живёт в реализациях.
- Вариант B: **два слоя** — низкий `HttpGateway(request): Response` в `core/network` (интерфейс над HttpClient) + высокий `CandleFetcher` над ним.

Рекомендация — вариант A для первой итерации. Вариант B вводит абстракцию без реального второго бэкенда — преждевременно.

**Интерфейс.** `core-features/stocks/domain/remote/CandleFetcher`:

```kotlin
interface CandleFetcher {
    suspend fun fetch(source: Source, ticker: Ticker, period: Period, range: TimeRange): List<Candle>
}
```

**Реализация.** `data/remote/MoexCandleFetcher(httpClient, urlBuilder, placeholderResolver, csvParser)` — вся текущая логика `DefaultMoexCandleDownloader` + `DefaultCandleDownloadService` ужимается сюда.

**Рефакторинг потребителей.** `DefaultChunkedCandleDownloader` принимает `CandleFetcher`, не `HttpClient`. Цикл по чанкам, merge-логика, retry — остаются как есть.

**Koin.** `StocksModule.kt` больше **не** импортирует `io.ktor.client.HttpClient`. Ktor — только в `data/remote/MoexCandleFetcher`. `CandleFetcher` регистрируется как `single<CandleFetcher> { MoexCandleFetcher(...) }` (позже — factory по `source.kind`).

**Тесты.** `DefaultChunkedCandleDownloaderTest` — `mock<CandleFetcher>()`, Turbine на прогресс, проверка правильной разбивки диапазона на чанки. На `MoexCandleFetcher` юнитов не пишем — он становится integration-only.

Зависит от задачи 1 (архитектурный research должен зафиксировать паттерн как обязательный для новых модулей).

Пока не делаем: добавление Yahoo/Alor — это задачи 16 и 17, и они уже легко ложатся на новый интерфейс.

Приёмка:
- `grep -r 'io\.ktor\.client\.HttpClient' modules/core/core-features/stocks/` → 0 результатов (остаётся только в `modules/core/network/`);
- `./gradlew :composeApp:compileKotlinJvm` зелёный, все существующие smoke-сценарии проходят без регрессии (загрузка MOEX CSV работает как раньше);
- `./gradlew :modules:core:core-features:stocks:allTests` — как минимум один новый тест `DefaultChunkedCandleDownloaderTest` зелёный, в том числе покрывает сценарий «fetcher вернул часть чанков, остальные запросили повторно».

---

## 24. Изоляция SQLDelight через DAO-слой

Убрать `StocksDatabase` из всех репозиториев; восстановить тестируемость 10 `*RepositoryImpl` (особенно `SourceRepositoryImpl.createWithMappings` с транзакционной логикой); зафиксировать паттерн для будущих модулей (Workspace, IndicatorConfig, Experiment, Run, Segment).

**Research-часть** в `plans/research/db-isolation.md`, компактно:
- Гранулярность DAO: один на таблицу (`CandleDao`, `SourceDao`, ...) vs один на агрегат (`SourceAggregateDao` включает Source + SourceParam + SourceMarketMapping + SourcePeriodMapping).
- Рекомендация: **один DAO на агрегат корня**, где агрегат существует (Source + его params/mappings — один агрегат). Для одиночных таблиц — один к одному (`CandleDao`, `PeriodDao`, `MarketDao`). Итого ~8–9 DAO вместо 13+ Queries.
- Транзакции: `transaction { ... }` из SQLDelight доступна через `TransactionWithoutReturn`. В DAO-интерфейсе оставляем **semantic method** (`createWithMappings(...)`), не вытаскиваем `transaction` наверх — иначе DAO тоже нельзя будет мокать полноценно.

**Интерфейсы DAO.** `core-features/stocks/domain/local/`:

```kotlin
interface CandleDao {
    fun getByTickerAndPeriod(tickerId: Long, periodMinutes: Int, limit: Int, offset: Int): Flow<List<Candle>>
    suspend fun getMinTimestamp(tickerId: Long, periodMinutes: Int): Long?
    suspend fun insertBatch(candles: List<Candle>)
    // и т.д., один-к-одному с публичным API CandleRepositoryImpl
}
```

По аналогии — `MarketDao`, `PeriodDao`, `SectorDao`, `QuoteDao`, `TickerDao`, `SourceDao` (с `createWithMappings`), `SourceMappingDao`, `TickerPeriodMetaDao`, `DownloadTaskDao`.

**Реализации.** `data/local/`:
- `CandleDaoImpl(database: StocksDatabase, dispatchers: DispatcherProvider)` — переносит всю SQLDelight-работу + `withContext(dispatchers.io)` (заодно закрывается хардкод `Dispatchers.IO` в репозиториях).
- По одной реализации на интерфейс.

**Рефакторинг репозиториев.** `CandleRepositoryImpl(candleDao)`, `SourceRepositoryImpl(sourceDao, sourceMappingDao)` — репо больше **не знает** про `StocksDatabase`, только про свои DAO.

**Koin.** `StocksModule.kt`:
- `single<CandleDao> { CandleDaoImpl(get(), get()) }` и т.д.
- `single<CandleRepository> { CandleRepositoryImpl(get()) }` — остаётся, но `get()` теперь резолвит DAO, не Database.

**Тесты.** `SourceRepositoryImplTest` — `mock<SourceDao>()`, `mock<SourceMappingDao>()`, проверяем поведение `createWithMappings` (что вызвало правильные методы DAO в правильном порядке). Аналогично для одного-двух других репо с нетривиальной логикой.

Зависит от задачи 1.

Пока не делаем: переписывание `.sq` файлов, миграции (отдельная задача); полный вынос `StocksDatabase` из `core-features/stocks` — он остаётся внутри `data/local/`, просто не проникает в репозитории и наверх.

**Связь с техдолгом.** В DAO-имплементациях используем `DispatcherProvider.io` вместо хардкода `Dispatchers.IO` — этот пункт закрывается попутно, отдельная задача «миграция на DispatcherProvider» становится не нужна. Логирование через `stocksLogger<T>` в новых DAO — тоже по правилу CLAUDE.md, без отдельной задачи.

Приёмка:
- `grep -r 'import ru\.samtakoy\.stocks\.db\.StocksDatabase' modules/core/core-features/stocks/data/repository/` → 0 результатов (Database остался только в `data/local/` реализациях DAO и в `di/StocksModule.kt`);
- все 10 `*RepositoryImpl` принимают только DAO (и опциональные utils вроде DispatcherProvider), не `StocksDatabase`;
- `./gradlew :composeApp:compileKotlinJvm` зелёный; все существующие smoke проходят;
- `SourceRepositoryImplTest.createWithMappings_insertsSourceParamsMarketsAndPeriods_inOrder` — `verifySuspend` в правильной последовательности;
- `CandleRepositoryImplTest.insertBatch_forwardsToDao` — как минимум один простой тест;
- паттерн задокументирован в `plans/research/db-isolation.md` и упомянут в архитектурных notes задачи 1 — чтобы задачи 2, 7, 8 сразу делали модули по нему.

---

## 25. Миграция feature/data на единую структуру папок

Привести `modules/features/data` в соответствие с разделом «Folder Structure» в `.claude/rules/features-module.md` (правила уже обновлены). Убрать кашу, накопившуюся на старте: разбросанные UiModel-файлы, промежуточные mapping-классы в корне screen-папок, диалог рядом со Screen, data-loader внутри feature-модуля.

Точечные перемещения ~9 файлов, без массового переименования папок — nested-иерархия сохраняется:

- `sources/SourceUiModel.kt` → `sources/model/SourceUiModel.kt` (если появятся ещё) либо оставить в корне `sources/`. Правило: UiModel собираются в `model/` при ≥2 файлах; одиночный — в корне.
- `sources/BuiltinPresetLoader.kt` → `core/core-features/stocks/core/presets/BuiltinPresetLoader.kt`. Это data-loader, не feature-specific — должен покинуть feature-модуль, лечь рядом с `SourcePresetParser`.
- `candles/DownloadResultUi.kt` → переименовать в `DownloadResultUiModel.kt`, оставить в корне `candles/`. Одиночный UiModel может лежать в корне; имя приводим к конвенции `*UiModel.kt`.
- `catalog/quotedetail/TickerWithMarket.kt` → `catalog/quotedetail/mapper/QuoteDetailMappingHelpers.kt` (+ `internal`). Это промежуточный класс маппинга, не UiModel.
- `catalog/tickerdetail/SourceWithMapping.kt` → `catalog/tickerdetail/mapper/TickerDetailMappingHelpers.kt` (+ `internal`). То же.
- `sources/detail/MarketWithMapping.kt` + `sources/detail/PeriodWithMapping.kt` → объединить в `sources/detail/mapper/SourceDetailMappingHelpers.kt`. Один файл helpers на экран.
- `tickerperiods/ui/HistoryDownloadDialog.kt` → `tickerperiods/ui/dialogs/HistoryDownloadDialog.kt`. Диалоги отделены от Screen.
- `ui/DataContent.kt`, `ui/DataHubScreen.kt`, `ui/DataHubMenuScreen.kt` (root-level `ui/`) → создать `hub/` screen-folder: `hub/ui/DataHubScreen.kt` + `hub/ui/DataHubMenuScreen.kt`; `DataContent.kt` — либо в `hub/ui/`, либо удалить если дублирует. Корневой `ui/` вне screen-folder'а — нарушение правила.

Попутно:
- пакеты переименованных папок обновить (`ru.samtakoy.stocks.feature.data.catalog.quotedetail.mapper` и т.д.);
- все `*MappingHelpers` пометить `internal` — чтобы не утекали в публичный API;
- Koin-модуль `dataFeatureModule` скорректировать под новые пути; регистрацию `BuiltinPresetLoader` перенести в `stocksModule`.

Пока не делаем: миграцию на `PersistentList` и удаление дефолтов из `Store.State` (отдельная задача — `CandleDataStore`, `QuotesTabStore`, `ReferenceStore`, `TickerPeriodsStore`); применение правил к другим features (`main`, `settings`, `chart`) — там такой каши нет; переход на hyphenated folder names — правила прямо запрещают.

Приёмка:
- `./gradlew assembleDebug` зелёный; `./gradlew :composeApp:allTests` не регрессирует;
- все smoke-сценарии в `smoke/scenarios/` проходят без изменений YAML (ui-поведение семантически то же);
- `grep -r "BuiltinPresetLoader" modules/features/` → 0 результатов (лоадер ушёл в `core-features/stocks`);
- `grep -rE '^\s*(data )?class \w+With\w+' modules/features/data/` в корнях screen-папок даёт 0 результатов — всё переехало в соответствующие `mapper/*MappingHelpers.kt`;
- папка `modules/features/data/src/commonMain/kotlin/ru/samtakoy/stocks/feature/data/ui/` не существует;
- все `*MappingHelpers.kt` декларируют `internal` типы.
