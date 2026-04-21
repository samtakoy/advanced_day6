# План реализации — Вариант B (файловый scratchpad + OpenAI function calling)

> Цель: за один день собрать все артефакты Дня 6 (датасет 50 JSONL + валидатор + baseline + критерии + FT-клиент) в отдельном Python-проекте, не трогая KMP-монорепу.

---

## 0. Быстрая сводка по архитектуре

**Суть**: модель через function calling использует **два класса инструментов** — **state tools** (семантические, одинаковые в B и A) и **project tools** (работа с реальным кодом). В B-реализации state tools под капотом пишут JSON в `.tasks/<task_id>/`; в A-реализации — зовут MCP-сервер. Для модели tool-интерфейс идентичен → **переход B→A без переобучения**. Runner запустим позже (День 7+); для Дня 6 нужен лишь контракт и датасет.

**State tools (5 штук — управление собственным планом, семантические):**
```
plan_write(task_id: str, goal: str, steps: [StepSpec]) -> {"ok": bool}
step_read(task_id: str, step_n: int) -> StepData
step_update_result(task_id: str, step_n: int, status: "DONE"|"FAILED"|"NEEDS_REPLAN", result: str, notes?: str) -> {"ok": bool}
task_status(task_id: str) -> {"goal": str, "current_step": int, "total": int, "steps_summary": [{n, status}]}
plan_revise(task_id: str, from_step: int, new_tail: [StepSpec]) -> {"ok": bool}
```
где `StepSpec` = `{goal, preconds[], checklist[], action_hint, success_criteria}`  
и `StepData` = `StepSpec + {n, status, result, notes?}`

**Project tools (4 штуки — работа с кодом проекта):**
```
read_file(path: str) -> {"content": str}
list_dir(path: str) -> {"entries": [str]}
search_and_replace(path: str, old_text: str, new_text: str) -> {"ok": bool, "matches": int}
write_file(path: str, content: str) -> {"ok": bool, "created": bool}   # для НОВЫХ файлов
```
`search_and_replace` — для редактирования существующих (безопаснее). `write_file` — только для создания новых (тесты, доки, новые source-файлы).

**Хранение state на диске (B-реализация):**
```
.tasks/
  t-0042/
    plan.json        # {task_id, goal, steps: [StepData, ...]}
    step_01.json     # StepData
    step_02.json
    ...
```
`plan_write` создаёт весь набор файлов атомарно. `step_read` читает `step_NN.json`. `step_update_result` обновляет `step_NN.json` и синхронизирует `plan.json`. Всё читается глазами через `cat` / `jq` — прозрачность сохраняется.

**Ключевое**: модель НЕ оперирует путями типа `.tasks/t-0042/step_01.json` — она вызывает `step_read(task_id="t-0042", step_n=1)`. Путь — деталь реализации. В A-варианте под теми же `step_read` будет вызов MCP-сервера, код модели не меняется.

---

## 1. Структура проекта

```
day6-finetune-agent/
├── README.md
├── pyproject.toml              # python>=3.11, openai>=1.30, anthropic, python-dotenv
├── .env.example                # OPENAI_API_KEY=..., ANTHROPIC_API_KEY=...
├── .gitignore                  # .env, .tasks/, __pycache__
│
├── contracts/
│   ├── tool_schemas.json       # OpenAI tools format: 5 state-tools + 3 project-tools
│   ├── step_schema.json        # JSON Schema для StepData
│   └── plan_schema.json        # JSON Schema для Plan файла
│
├── prompts/
│   ├── system_agent.md         # System prompt для agent-mode
│   ├── system_plain.md         # System prompt для plain Q&A
│   ├── meta_agent.md           # Мета-промпт генерации agent-примеров
│   ├── meta_question.md        # Мета-промпт для QUESTION-ветки
│   └── meta_plain.md           # Мета-промпт для plain-примеров
│
├── dataset/
│   ├── golden_example.jsonl    # 1 эталонный пример, написанный вручную
│   ├── gen_synthetic.py        # Массовая генерация через GPT-4o + Claude 3.5 Sonnet
│   ├── real_examples.jsonl     # 10 реальных примеров (ручками, из adv_day6_plan.md)
│   ├── synthetic_raw.jsonl     # Сырой выход генераторов (до валидации)
│   ├── mix_and_split.py        # Композиция 35/8/7 + split train/eval 80/20
│   ├── train.jsonl             # ИТОГ: 40 примеров
│   └── eval.jsonl              # ИТОГ: 10 примеров
│
├── validator/
│   ├── validate.py             # Главный CLI: python -m validator --in train.jsonl
│   ├── checks_structural.py    # JSON valid, роли, непустой content, длины
│   ├── checks_semantic.py      # task_id, tool_calls, plan/step refs, self-check
│   └── checks_dedup.py         # Embedding-based semantic dedup (cosine > 0.92)
│
├── baseline/
│   ├── run_baseline.py         # Прогон 10 eval через gpt-4o-mini (без FT)
│   ├── outputs/                # Сырые ответы baseline
│   └── summary.md              # Фиксация метрик baseline
│
├── criteria/
│   └── criteria.md             # Критерии "стало лучше" (авто-метрики + LLM-judge)
│
├── ft_client/
│   ├── upload.py               # Загрузка train.jsonl в OpenAI Files API
│   ├── create_job.py           # Создание fine-tuning job (не запускать без подтверждения)
│   ├── poll.py                 # Polling статуса job
│   └── README.md               # Как использовать: upload → create → poll
│
└── runner/                     # ЗАГЛУШКА для Дня 7+. Не обязательно на День 6.
    └── agent_runner.py         # (stub) цикл: read_step → LLM → tool → update → next
```

---

## 2. Последовательность работы (фазы)

### Фаза 0 — Setup (30 мин)
1. `mkdir day6-finetune-agent && cd day6-finetune-agent`
2. Инициализация Python-проекта: `uv init` или классический `python -m venv .venv`.
3. Зависимости: `openai`, `anthropic`, `python-dotenv`, `pyyaml`, `numpy` (для embedding dedup).
4. `.env` с ключами OpenAI и Anthropic.
5. `README.md` с командами запуска.

### Фаза 1 — Контракты и "золотой" пример (1-1.5 ч)
1. Написать `contracts/tool_schemas.json` — OpenAI tools format: 5 state-tools (`plan_write`, `step_read`, `step_update_result`, `task_status`, `plan_revise`) + 3 project-tools (`read_file`, `list_dir`, `search_and_replace`).
2. Написать JSON Schemas для `step_schema.json` и `plan_schema.json` — валидация того, что кладём в `.tasks/<task_id>/`.
3. Написать 2 system prompt-а (`system_agent.md` со списком всех 8 tools и правилом workflow; `system_plain.md` без tools — чистый Q&A режим).
4. **Вручную собрать `golden_example.jsonl`** — одну строку с полным "идеальным" multi-turn диалогом (см. §3 ниже), включая ветку replan. Это эталон стиля, по которому мы будем генерировать остальные 39 синтетических.

> **Важно**: не генерировать 40 штук до того, как golden отполирован. Плохой golden → 40 плохих клонов. Лучше 2 часа на golden, чем переделка всей выборки.

### Фаза 2 — Генерация синтетики (3-4 ч)

#### 2.1. Типология задач (важное архитектурное решение)

Мета-паттерн (plan → step_read → action → self-check → update → next) одинаков для всех задач. Но **форма шагов** различается по типу — именно этому разнообразию должна научиться модель. Тип задачи НЕ фиксируется как отдельное поле в tool-схеме; он проявляется через структуру плана (какие `action_hint`, есть ли `search_and_replace`, есть ли финальный verify-шаг, что написано в `goal` плана).

**Целевое распределение в agent-подмножестве (35 из 50):**

| Тип задачи | Квота | Характерная форма плана |
|---|---|---|
| **develop** (feature: add/create) | 12 | find path → read file → search_and_replace или write_file → verify |
| **refactor** | 6 | grep нарушений → read N файлов → множество search_and_replace → verify. Включая ветку «нарушений нет → ничего не делаем». |
| **bugfix** | 6 | reproduce/parse stack → locate → fix → verify |
| **research** (+ docs) | 8 | list_dir + read_file series → write_file итогового документа. Без модификаций исходного кода. |
| **tests** (coverage) | 3 | find existing tests → read conventions → write_file new test → verify |

Плюс 8 `agent_question` + 7 `plain` = итого 50.

(review-тип смержен в research: в реальных задачах стеба нет чистых review — всегда либо research-документ, либо feature с анализом как префазой.)

#### 2.2. Seeds-расширение (дотянуть перед массовой генерацией)

Сейчас есть 2 develop seeds (golden_01, golden_02), 1 question (golden_03), 1 plain (plain_01). Нужно дописать **4 seeds на базе реальных задач из внешнего KMP-проекта (C:\devs\kmm\stocks\task\board\pool)**: refactor (#13 DispatcherProvider), bugfix (#4 table wrap), research (#15 domain map), tests (#14 GetSectorsUseCase unit tests). Каждый станет референсом для мета-промпта.

#### 2.3. Мета-промпты (`prompts/meta_*.md`)

- `meta_agent.md` — параметризуется `(type, scenario, variation)`. На вход — 1-2 seed того же типа как референс + список tools. Выход — 1 JSONL-строка.
- `meta_question.md` — генератор QUESTION-примеров (недостаток данных).
- `meta_plain.md` — генератор plain Q&A (conceptual questions).

#### 2.4. Генератор (`gen_synthetic.py`)

- Список сценариев распределён по 6 типам согласно квоте.
- Половина через GPT-4o, половина через Claude 3.5 Sonnet (страховка от стилевого overfit).
- Батчами по 5, retry с exponential backoff при rate-limit.
- Каждый сгенерированный пример прогоняется через валидатор (Фаза 4). Провалидированные — в `synthetic_raw.jsonl`. Failed — retry с обратной связью "что именно не так".

Итого `synthetic_raw.jsonl`: ~40 строк (≈25 agent разных типов + ≈8 question + ≈7 plain).

### Фаза 3 — Реальные примеры (1-1.5 ч)
Написать 10 руками в `real_examples.jsonl`, опираясь на реальные задачи из `adv_day6_plan.md`:
1. "Добавь сериализацию в shared" (add_dep)
2. "Прикрути Ktor к десктопной части" (add_dep cross-platform)
3. "Сделай expect класс для получения ID устройства" (expect/actual)
4. "Переделай навигацию с Decompose на Voyager" (большой refactor, хороший для replan-сценария)
5. "Глянь лог — где именно упал iOS билд?" (stacktrace parse, read-only)
6. "Добавь строковой ресурс login_title" (compose resources)
7. "Создай модуль feature-auth с поддержкой ios и android" (create_module)
8. "Добавь поддержку wasmJs в проект" (configure_target)
9. "Верни назад internal visibility в DataSource.kt" (search_and_replace)
10. "Почему у меня в androidMain не видно expect из commonMain?" (plain Q&A, без action)

> В реальных примерах прячутся нюансы, которые синтетика пропустит. Именно здесь модель увидит "живой" стиль постановки задачи.

### Фаза 4 — Валидатор (1-2 ч)
`validate.py` должен делать три прохода:

**Structural checks (checks_structural.py):**
- Каждая строка — валидный JSON.
- Есть ключ `messages` (список).
- В каждом message есть `role` ∈ {system, user, assistant, tool} и `content` (либо `tool_calls`).
- `content` непустой, длина > 10 и < 8000 символов.
- Порядок ролей: начинается с system → user → assistant, чередование корректное.

**Semantic checks (checks_semantic.py):**
- Для agent-примеров (есть tool_calls в assistant): `task_id` фигурирует как аргумент во всех state-tool calls.
- Первый assistant tool_call — это `plan_write` (жёсткий инвариант workflow).
- Перед каждым `step_update_result` или project-tool action должен быть `step_read` в одном из предыдущих ходов (read-before-action).
- Есть self-check паттерн (ключевые слова: "SELF-CHECK", "checklist", "success_criteria") в assistant.content.
- Все вызываемые tool names ∈ {plan_write, step_read, step_update_result, task_status, plan_revise, read_file, list_dir, search_and_replace}. Любое другое имя — немедленный fail.
- `arguments` в каждом tool_call — валидный JSON, матчит ожидаемую схему инструмента.
- Для plain-примеров: нет tool_calls, нет JSON-блоков в content, ответ — это проза.

**Dedup checks (checks_dedup.py):**
- Embeddings (OpenAI `text-embedding-3-small`) для всех user-сообщений.
- Cosine similarity > 0.92 → флаг "возможный дубль", ручная ревизия.

Выход: отчёт с ошибками + отфильтрованный `clean.jsonl`.

### Фаза 5 — Микс и split (30 мин)
`mix_and_split.py`:
1. Объединить `real_examples.jsonl` + провалидированную синтетику.
2. Проверить композицию: ~70% agent, ~16% question, ~14% plain. Подрезать лишнее, добрать недостающее.
3. Random seed = 42, shuffle.
4. Split 80/20: `train.jsonl` (40 примеров) и `eval.jsonl` (10 примеров).
5. Гарантировать, что все три типа (agent/question/plain) представлены в eval.

### Фаза 6 — Baseline (1 ч)
`run_baseline.py`:
1. Прочитать `eval.jsonl`.
2. Для каждой строки: взять только system + первый user message, отправить в `gpt-4o-mini` (без FT), собрать ответ.
3. Сохранить в `baseline/outputs/eval_{i}.json`: `{input, expected, actual}`.
4. В `summary.md` — качественные наблюдения + замер авто-метрик (см. §4).

### Фаза 7 — Критерии (30 мин)
`criteria/criteria.md` — документ с 5 авто-метриками и 2 LLM-judge метриками (скопировать раздел 7 из `adv_day6_analisys.md`, уточнить под этот датасет).

### Фаза 8 — FT-клиент (1 ч)
`ft_client/`:
- `upload.py`: `client.files.create(file=open("train.jsonl"), purpose="fine-tune")`, логируем file_id.
- `create_job.py`: `client.fine_tuning.jobs.create(training_file=..., model="gpt-4o-mini-2024-07-18", hyperparameters={"n_epochs": "auto"})`. **Обернуть в confirm-prompt**, чтобы случайно не запустить.
- `poll.py`: цикл `client.fine_tuning.jobs.retrieve(job_id)` с интервалом 30 с, прерывание по `succeeded`/`failed`.
- `README.md` — 3 команды: `python upload.py`, `python create_job.py --dry-run`, `python poll.py <job_id>`.

---

## 3. Как выглядит золотой пример (golden_example.jsonl)

Одна строка JSONL с multi-turn диалогом. Ниже — раскрытая схема (в реальности одна строка с экранированием). Сценарий: добавить kotlinx-serialization в shared, третий шаг падает → срабатывает replan.

```
messages:
  [0] system:
      "Ты KMP-агент. State tools: plan_write, step_read, step_update_result, task_status, plan_revise.
       Project tools: read_file, list_dir, search_and_replace.
       Workflow: (1) при получении задачи ВСЕГДА начинаешь с plan_write, (2) перед каждым шагом
       ВСЕГДА делаешь step_read, (3) после выполнения — step_update_result, (4) при ошибке
       или изменении контекста — plan_revise. Каждый шаг: THOUGHT → SELF-CHECK → tool call."

  [1] user:
      "Задача: добавь kotlinx-serialization в shared модуль. task_id=t-0042."

  [2] assistant: (содержит THOUGHT в content + tool_call)
      content: "THOUGHT: Сериализация в KMP идёт в commonMain. План из 4 шагов: осмотреть shared/,
               прочитать build.gradle.kts, вставить dependency через search_and_replace, verify."
      tool_calls: [plan_write(task_id="t-0042", goal="add kotlinx-serialization to shared",
                    steps=[
                      {n:1, goal:"найти build.gradle.kts в shared/", preconds:[],
                       checklist:["shared/ существует","в списке есть build.gradle.kts"],
                       action_hint:"list_dir shared/",
                       success_criteria:"build.gradle.kts в entries"},
                      {n:2, goal:"прочитать build.gradle.kts", preconds:["шаг 1 DONE"],
                       checklist:["нашёл блок kotlin {}","нашёл commonMain.dependencies"],
                       action_hint:"read_file shared/build.gradle.kts",
                       success_criteria:"content содержит commonMain.dependencies"},
                      {n:3, goal:"вставить зависимость в commonMain", preconds:["шаг 2 DONE"],
                       checklist:["не дублирую строку","сохраняю отступ","импорт из libs.versions"],
                       action_hint:"search_and_replace на найденной строке",
                       success_criteria:"matches >= 1"},
                      {n:4, goal:"верификация", preconds:["шаг 3 DONE"],
                       checklist:["строка реально в файле","формат корректный"],
                       action_hint:"read_file ещё раз, проверить подстроку",
                       success_criteria:"kotlinx-serialization в content"}
                    ])]

  [3] tool: {"ok": true}

  [4] assistant:
      content: "План сохранён. Перехожу к шагу 1 — читаю его спецификацию."
      tool_calls: [step_read(task_id="t-0042", step_n=1)]

  [5] tool: {n:1, goal:"найти build.gradle.kts в shared/", checklist:[...], action_hint:"list_dir shared/", status:"TODO", ...}

  [6] assistant:
      content: "SELF-CHECK перед action: checklist требует убедиться, что shared/ существует
               и build.gradle.kts в списке. Оба пункта закроются одним list_dir."
      tool_calls: [list_dir(path="shared/")]

  [7] tool: {"entries": ["build.gradle.kts", "src"]}

  [8] assistant:
      content: "SELF-CHECK результата: build.gradle.kts найден (пункт 2 ✓), shared/ вернул entries (пункт 1 ✓).
               success_criteria выполнен. Фиксирую DONE."
      tool_calls: [step_update_result(task_id="t-0042", step_n=1, status="DONE",
                    result="build.gradle.kts at shared/build.gradle.kts")]

  [9] tool: {"ok": true}

  [10] assistant:
       content: "К шагу 2."
       tool_calls: [step_read(task_id="t-0042", step_n=2)]

  [11] tool: {n:2, ...}

  [12] assistant:
       content: "SELF-CHECK: сейчас читаю файл, после прочтения проверю наличие блоков kotlin и commonMain.dependencies."
       tool_calls: [read_file(path="shared/build.gradle.kts")]

  [13] tool: {"content": "plugins { ... }\\nkotlin {\\n  sourceSets {\\n    commonMain.dependencies {\\n      implementation(libs.ktor.core)\\n    }\\n  }\\n}"}

  [14] assistant:
       content: "SELF-CHECK: нашёл kotlin {} (✓), нашёл commonMain.dependencies (✓). Шаг 2 DONE."
       tool_calls: [step_update_result(task_id="t-0042", step_n=2, status="DONE",
                     result="commonMain.dependencies block found, currently has ktor.core")]

  [15] tool: {"ok": true}

  # Шаг 3 — демонстрация ошибки и replan
  [16] assistant:
       tool_calls: [step_read(task_id="t-0042", step_n=3)]

  [17] tool: {n:3, action_hint:"search_and_replace на найденной строке", ...}

  [18] assistant:
       content: "SELF-CHECK: вставляю строку implementation(libs.kotlinx.serialization.json) ПОСЛЕ libs.ktor.core.
                Старый текст — 'implementation(libs.ktor.core)', новый — та же строка + перенос + моя."
       tool_calls: [search_and_replace(path="shared/build.gradle.kts",
                     old_text="implementation(libs.ktor.core)",
                     new_text="implementation(libs.ktor.core)\\n      implementation(libs.kotlinx.serialization.json)")]

  [19] tool: {"ok": false, "matches": 0, "error": "old_text not found"}

  [20] assistant:
       content: "SELF-CHECK ловит ошибку: matches=0 значит контекст поменялся или формат другой.
                Нужен replan: сначала считать реальное содержимое ещё раз (возможно пробелы/табы)
                и уточнить old_text. Переключаю шаг 3 в NEEDS_REPLAN, добавляю промежуточный шаг 3a."
       tool_calls: [step_update_result(task_id="t-0042", step_n=3, status="NEEDS_REPLAN",
                     result="search_and_replace returned matches=0, old_text mismatch")]

  [21] tool: {"ok": true}

  [22] assistant:
       tool_calls: [plan_revise(task_id="t-0042", from_step=3, new_tail=[
                     {n:3, goal:"перечитать файл и извлечь точный old_text с пробелами",
                      action_hint:"read_file + визуальный парсинг", ...},
                     {n:4, goal:"повторить search_and_replace с точным old_text", ...},
                     {n:5, goal:"верификация", ...}
                   ])]

  [23] tool: {"ok": true}

  # ... далее шаги 3,4,5 нового плана, с успешной вставкой и verify
```

**Что тут важного:**
1. **plan_write — всегда первый ход.** Fine-tune прошивает этот рефлекс.
2. **step_read ВСЕГДА предшествует action.** Модель не "помнит" план по памяти — она его читает.
3. **Два SELF-CHECK на шаг:** один ДО action (что проверим), один ПОСЛЕ (что получилось). Оба материализованы как текст.
4. **Task_id в каждом tool call** — не опускается никогда.
5. **Ошибка → NEEDS_REPLAN → plan_revise.** Модель не повторяет упавший action, она обновляет план.
6. **Tool names семантические** — `step_read(task_id, step_n)` а не `read_file(".tasks/t-0042/step_01.json")`. Это критично для перехода на MCP без переобучения.

Полная раскрытая строка JSONL лежит в `dataset/golden_example.jsonl` (одна строка, все сообщения в одном объекте `{"messages": [...]}`).

---

## 4. Метрики baseline ↔ fine-tuned (что замеряем)

Из `criteria.md` — 5 авто-метрик + 2 LLM-judge (все автоматически проверяются скриптом):

| Метрика | Baseline ожидание | После FT ожидание |
|---|---|---|
| Structural compliance (есть все блоки + валидный JSON в tool_calls) | 30-50% | >90% |
| Tool name validity (нет галлюцинаций tool names) | 5-15% ошибок | 0% |
| Task_id consistency (во всех tool calls) | 50-70% | 100% |
| Read-before-action (читает step перед action) | <40% | >90% |
| Replan on error (после tool error — правит план, не повторяет) | ~20% | >80% |
| LLM-judge: plan quality (1-5) | 2-3 | 4-5 |
| LLM-judge: mode switch (не путает agent/plain) | не измеряется до FT | >90% |

---

## 5. Проверка на catastrophic forgetting (важно!)

Помимо основных 10 eval-примеров, подготовить **mini-eval на plain-mode**:
- 5 простых вопросов про KMP ("что такое expect/actual?", "разница commonMain и androidMain", etc.)
- System prompt — `system_plain.md` (без agent-режима).
- Прогнать через baseline **и** через fine-tuned модель (после запуска FT, уже в День 7+).
- Сравнить качество ответов: если FT-модель деградирует на plain-вопросах >10% по LLM-judge — увеличить долю plain-примеров в датасете и переобучить.

Для Дня 6 достаточно **подготовить** этот mini-eval (5 строк JSONL в `eval_plain.jsonl`), запускать будем позже.

---

## 6. Оценка трудозатрат

| Фаза | Время | Блокеры |
|---|---|---|
| 0. Setup | 30 мин | API keys |
| 1. Контракты + golden | 1.5 ч | качество golden критично — не экономить |
| 2. Синтетика | 3-4 ч | rate limits OpenAI/Anthropic |
| 3. Реальные 10 | 1.5 ч | ручная работа, вдумчиво |
| 4. Валидатор | 1.5 ч | особенно tool_calls парсинг |
| 5. Mix + split | 30 мин | — |
| 6. Baseline | 1 ч | сеть до OpenAI |
| 7. Критерии | 30 мин | копипаст + уточнение |
| 8. FT-клиент | 1 ч | — |
| **ИТОГО** | **~10-12 ч** | реалистично в 1 полный рабочий день |

---

## 7. Что НЕ делаем на Дне 6 (явные отсечения)

- **Не** пишем реальный agent_runner — заглушка есть, запуск откладываем на День 7.
- **Не** запускаем fine-tune job (код готов, но `create_job` стоит за `--confirm` флагом).
- **Не** поднимаем MCP-сервер — это путь варианта A, делаем позже если решим.
- **Не** пишем интеграцию с Claude Desktop / Cursor — не нужна для обучения.
- **Не** делаем UI / CLI для runner-а — нужна просто возможность прогнать eval через API.

---

## 8. Checklist сдачи Дня 6

- [ ] `train.jsonl` — 40 валидных примеров
- [ ] `eval.jsonl` — 10 валидных примеров
- [ ] `validator/validate.py` — прогоняется без ошибок
- [ ] `baseline/outputs/` — 10 ответов gpt-4o-mini без FT
- [ ] `baseline/summary.md` — зафиксированные наблюдения
- [ ] `criteria/criteria.md` — 5 авто + 2 LLM-judge метрики
- [ ] `ft_client/upload.py` + `create_job.py` + `poll.py` — работают в `--dry-run`, **не** запущены
- [ ] `README.md` — инструкция, как это всё воспроизвести
- [ ] Видео: показать структуру, прогнать validate, прогнать baseline, объяснить критерии, показать ft_client в dry-run

---

## 9. Риски при реализации и страховки

| Риск | Страховка |
|---|---|
| Синтетика получается однообразной | Генерация половина через GPT-4o, половина через Claude; разные промпты; разные имена модулей |
| Валидатор пропускает битый JSON в `tool_calls.arguments` | Отдельная проверка: `json.loads(tool_call["function"]["arguments"])` |
| Rate limit OpenAI на этапе генерации | Батчи по 5, `time.sleep(2)` между запросами, retry с exponential backoff |
| Embedding dedup сносит полезные вариации | Порог 0.92 (не слишком строгий), ручная ревизия флагов |
| Эмбеддинги стоят денег | text-embedding-3-small — 50 строк × $0.02/1M ≈ копейки |
| FT-клиент случайно запущен | Явный `--confirm` флаг в create_job.py, job создаётся только если он установлен |

---

## 10. Что отличает этот план от наивной реализации

1. **Golden example как "медь" всего датасета** — 1.5 часа на эталон экономят день переделок.
2. **Два генератора (GPT-4o + Claude)** — защита от стилевого overfit, который легко проверить, но легко пропустить.
3. **Три режима в датасете (70/16/14)** — защита от catastrophic forgetting, обоснована в предыдущем ответе.
4. **Разные system prompts для режимов** — модель учится режим-переключению, а не общему формату.
5. **Mini-eval на plain-mode** — подготовлена сейчас, используется после FT для проверки, не сломалась ли модель.
6. **Явный `--confirm` у create_job** — fine-tune стоит денег, случайный запуск обиден.
7. **FS sandbox через `.tasks/<task_id>/`** — запуск агента не оставит мусор в корне проекта.

---

## Финальный вывод

План реализуется за ~10-12 часов сфокусированной работы. Критическая точка — Фаза 1 (golden example), экономия тут → провал всего датасета. Все остальные фазы — инженерная рутина по отработанным контрактам.
