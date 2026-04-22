# День 6 — Детальный план: fine-tune универсального KMP-агента на дисциплину формата

> Документ фиксирует итоговое решение по Дню 6 после пересмотра исходной идеи.
> Исходная постановка — `plans/day6_plan.md`. Дата финализации — 22.04.2026.
> Цель документа: дать возможность восстановить контекст и продолжить работу в новом сеансе.

---

## 1. Резюме в двух абзацах

**Что делаем.** Forkаем готовый проект `C:\devs\AI\aiadvent_projects\advanced_day6` (Python-проект для подготовки JSONL-датасета FT агента для KMP), адаптируем его под локальный Mac-стек (MLX + Ollama), **сохраняя универсальность датасета** — seeds остаются абстрактными KMP-задачами, не привязанными к `kmm/stocks`.

**Почему так.** Цель FT — прошить дисциплину **формата агентского ответа** (THOUGHT + SELF-CHECK, правильная последовательность tool_calls, replan вместо повтора при ошибке), а не "знание конкретного проекта". Если seeds остаются project-agnostic, а знание конкретного репо приходит в рантайме через project tools, то **одна и та же LoRA применима к любому KMP-проекту**. `kmm/stocks` используется только как интеграционная песочница в Дне 7+, не как источник seeds.

---

## 2. Выбранный путь — форк advanced_day6

### 2.1 Что в `advanced_day6` уже сделано и берётся как есть

| Компонент | Что есть | Роль в нашем плане |
|-----------|----------|---------------------|
| `contracts/tool_schemas.json` | 9 тулов: 5 state + 4 project | Контракт модели — **не трогаем** |
| `contracts/step_schema.json`, `plan_schema.json` | JSON Schema артефактов | **Не трогаем** |
| `prompts/system_agent.md`, `system_plain.md` | System prompts для двух режимов | **Не трогаем** |
| `prompts/meta_*.md` | Мета-промпты для LLM-генератора | **Не трогаем** |
| `dataset/seeds/` | 12 seed-примеров, все универсальные KMP | **Не трогаем** — в этом главная ценность |
| `dataset/gen_synthetic.py` | Retry-with-feedback генератор | **Не трогаем**, при необходимости расширяем `scenarios.py` |
| `dataset/scenarios.py` | Банк идей для генератора | **Опционально** расширяем (см. раздел 4.2) |
| `dataset/mix_and_split.py` | Stratified 80/20 split | **Не трогаем** |
| `validator/validate.py` | 3 прохода: structural / semantic / dedup | **Не трогаем** |
| `baseline/run_baseline.py` | Прогон seeds через gpt-4o-mini | **Расширяем** на второй бэкенд (см. 4.1) |
| `criteria/criteria.md` | 5 авто-метрик + 2 LLM-judge | **Не трогаем**, применяем к обоим бэкендам |
| `ft_client/upload.py, create_job.py, poll.py` | OpenAI fine-tune клиент | **Абстрагируем** под dual backend (см. 4.1) |
| `EXPLANATION.md`, `REPORT.md` | Документация | **Не трогаем**, дополняем в секции MLX |

### 2.2 Ключевые концептуальные находки, которые берём

Подтверждены baseline-замером в проекте (`baseline/outputs/summary.md`):

| Метрика на baseline (gpt-4o-mini без FT) | Значение | Что это значит для FT |
|-----------------------------------------|----------|----------------------|
| `plan_write first` | 8/8 (100%) | Базовая модель уже умеет → FT здесь не нужен |
| `THOUGHT в content` | 0/8 (0%) | Тотальный провал → **это главная цель FT** |
| `SELF-CHECK в content` | 0/8 (0%) | Тотальный провал → **это главная цель FT** |
| `task_id consistency` | 7/8 (87%) | Почти умеет → FT добьёт до 100% |
| `Tool name validity` | 100% | Базовая модель корректна → не улучшится |

**Вывод**: FT прошивает именно форму ответа — THOUGHT + SELF-CHECK + жёсткая дисциплина порядка вызовов. Всё, что модель уже умеет — остаётся как есть.

### 2.3 Трёхрежимный датасет (критично)

| Режим | Доля | Назначение | System prompt |
|-------|------|------------|---------------|
| `agent` | 70% | Основной — план + шаги + действия | `system_agent.md` |
| `agent_question` | 16% | Ambiguous request → задать уточнение, не строить план | `system_agent.md` |
| `plain` | 14% | Концептуальные вопросы → проза, без tool_calls | `system_plain.md` |

**Зачем plain**: анти-catastrophic-forgetting. Без него модель после FT начнёт звать `plan_write` даже на вопросы вроде "что такое expect/actual". Проверяется отдельным `eval_plain.jsonl` (5 концептуальных вопросов, LLM-judge оценивает проседание).

### 2.4 Split tool-контракт

**State tools (5):**
- `plan_write(task_id, goal, steps)` — первый вызов на задаче
- `step_read(task_id, step_n)` — перед каждым действием
- `step_update_result(task_id, step_n, status, result)` — после действия, status ∈ {DONE, FAILED, NEEDS_REPLAN}
- `task_status(task_id)` — общий обзор
- `plan_revise(task_id, from_step, new_tail)` — переписать хвост плана после NEEDS_REPLAN

**Project tools (4):**
- `read_file(path)`, `list_dir(path)`, `search_and_replace(path, old, new)`, `write_file(path, content)`

**Ключ к переносимости**: state tools — абстрактная state-machine модели (реализуется как файл-scratchpad или MCP). Project tools — универсальные file-операции, применимые к **любому проекту через MCP-сервер**. Модель учится паттерну использования, не именам файлов.

### 2.5 Replan discipline (отвечает на реальную боль локалки)

Эталонный паттерн восстановления после ошибки:
- `search_and_replace` вернул `matches=0` или `ok=false`
- → `step_update_result(status=NEEDS_REPLAN)`
- → `plan_revise(from_step=N)` с переписанным хвостом
- **НЕ** повторять тот же tool_call с теми же аргументами

Именно это лечит симптом локалки: "правильный анализ → неправильный фикс → возвращает → третий раз другим способом". LoRA закрепляет рефлекс "при неудаче — репланировать, не повторять".

---

## 3. Стек реализации (локальный, Mac 48GB)

### 3.1 Выбор фреймворка

- **MLX (Apple)** — родной для Apple Silicon, оптимизирован под Metal + unified memory
- **НЕ `unsloth`** (CUDA-only), **НЕ `bitsandbytes`**, **НЕ `flash-attention` CUDA**
- `torch + MPS` работает, но в 2–3 раза медленнее MLX

### 3.2 Модель

**Qwen 2.5 7B Instruct** — первый кандидат:
- Нативный OpenAI tool calling (формат датасета переносим без переделки)
- Хорошее следование structured output
- QLoRA на Mac 48GB — 15–30 мин обучения, 6–8 GB пиковой памяти
- После merge + GGUF-экспорта — работает в Ollama с OpenAI-compat API

### 3.3 Рантайм после FT

**Ollama** с JSON schema enforcement:
```python
ollama.chat(
    model="stocks-ft",
    messages=[...],
    tools=[{...}],                             # tool schemas из contracts/
    format={"type":"object", "properties":...}  # опционально для structured output
)
```

Под капотом — llama.cpp + GBNF grammar constraint → 100% валидный JSON на уровне sampling. OpenAI-compat API на `http://localhost:11434/v1` → **код агента не меняется** между baseline, OpenAI FT и MLX FT. Альтернатива — LM Studio (UI + OpenAI-compat server).

---

## 4. Модификации к advanced_day6

### 4.1 Dual FT backend (OpenAI + MLX) без костылей

Датасет идентичен для обоих бэкендов (OpenAI chat messages format с `tool_calls`). Разница только в клиенте обучения. Рефакторим `ft_client/` в абстракцию:

```
ft_client/
├── __init__.py
├── base.py           # class FTBackend: abstract upload()/train()/status()/download()
├── openai_backend.py # существующий код upload.py + create_job.py + poll.py
├── mlx_backend.py    # НОВОЕ: subprocess over mlx_lm.lora + merge + gguf export + Ollama Modelfile
├── cli.py            # python -m ft_client train --backend {openai|mlx}
```

Baseline тоже расширяется — `baseline/run_baseline.py` принимает флаг `--backend`:
- `--backend openai` (существующее): прогон через OpenRouter на `openai/gpt-4o-mini`
- `--backend ollama --model qwen2.5:7b`: прогон через локальный Ollama на базовой Qwen

Итог — **две сравнительные таблицы метрик**:
1. `baseline(gpt-4o-mini) → ft(gpt-4o-mini)` — эффект FT на сильной модели (через OpenAI)
2. `baseline(Qwen2.5-7B) → ft(Qwen2.5-7B)` — эффект FT на слабой локальной модели (через MLX)

Это показывает что FT лечит формат независимо от силы базовой модели — сильный результат для задания.

### 4.2 Расширение датасета (опционально, если не хватит 58)

Если eval после первой итерации покажет слабые места — **добавить сценарии в `scenarios.py`**, прогнать `gen_synthetic.py` с новыми типами. Это не привязка к `kmm/stocks`, а расширение банка идей:
- Новые сценарии рефакторинга (migrate-pattern, rename-across-modules)
- Новые сценарии research (compare-libraries, audit-usage)
- Новые типы ambiguous запросов для `agent_question`

**Семена из `/plans/temp/board/pool/` НЕ берём в датасет** — это конкретные задачи конкретного проекта. Они используются только для integration-теста в Дне 7+ (см. раздел 7).

### 4.3 Что точно не меняем

- `dataset/seeds/*.json` — 12 универсальных KMP-примеров, не добавляем `kmm/stocks`-специфику
- `contracts/*.json` — tool schemas, step/plan schemas
- `prompts/system_*.md`, `prompts/meta_*.md`
- `validator/validate.py`
- `criteria/criteria.md`

Вся архитектура advanced_day6 остаётся. Фактическая правка — **два новых файла** (`ft_client/mlx_backend.py`, `ft_client/base.py`) и рефакторинг существующих скриптов под абстракцию.

---

## 5. Пайплайн (как прогнать всё от начала до конца)

```bash
# 0. Форк в свой репо
cd advanced_day6
python -m venv .venv && source .venv/Scripts/activate
pip install -r requirements.txt
pip install mlx mlx-lm   # дополнительно для MLX backend
cp .env.example .env     # прописать OPENAI_API_KEY или OPENROUTER_API_KEY

# 1. Датасет уже собран (58 примеров). Если нужно расширить:
python -m dataset.gen_synthetic --count 10 --type develop --model openai/gpt-4o --seed 31
python -m validator.validate dataset/seeds dataset/synthetic
python -m dataset.mix_and_split    # → dataset/train.jsonl, dataset/eval.jsonl

# 2. Baseline — оба бэкенда
python -m baseline.run_baseline --backend openai --model openai/gpt-4o-mini
python -m baseline.run_baseline --backend ollama --model qwen2.5:7b
# → baseline/outputs/openai_gpt4o-mini_metrics.json, baseline/outputs/ollama_qwen25-7b_metrics.json

# 3. FT через OpenAI (быстро, дорого)
python -m ft_client train --backend openai --dataset dataset/train.jsonl
python -m ft_client poll   --backend openai --job-id <id>

# 4. FT через MLX (медленнее, бесплатно)
python -m ft_client train --backend mlx --dataset dataset/train.jsonl --model Qwen/Qwen2.5-7B-Instruct
# Под капотом:
#   mlx_lm.lora --model Qwen/Qwen2.5-7B-Instruct --train --data dataset/ --iters 600 --lora-layers 16
#   mlx_lm.fuse --model Qwen/Qwen2.5-7B-Instruct --adapter-path ./adapters --save-path ./qwen-kmp-ft
#   # GGUF export через llama.cpp convert-hf-to-gguf.py
#   # Ollama create stocks-ft -f Modelfile

# 5. Post-FT baseline — те же метрики на FT-моделях
python -m baseline.run_baseline --backend openai --model ft:gpt-4o-mini:<suffix>
python -m baseline.run_baseline --backend ollama --model stocks-ft

# 6. LLM-judge (критерии 6-7)
python -m baseline.judge --in baseline/outputs/ft_<backend>.jsonl --model claude-sonnet-4-6

# 7. Anti-catastrophic-forgetting (plain mode не просел)
python -m baseline.run_eval --in dataset/eval_plain.jsonl --backend ollama --model stocks-ft
```

---

## 6. Метрики и критерии (из advanced_day6 + расширение)

### 6.1 5 авто-метрик (из `criteria/criteria.md`)

| # | Метрика | Baseline (gpt-4o-mini) | Цель FT |
|---|---------|------------------------|---------|
| 1 | Structural compliance | ≥80% | ≥95% |
| 2 | Tool name validity | 100% | 100% |
| 3 | Task_id consistency (agent) | 100% | 100% |
| 4 | Read-before-action (agent) | <40% | ≥90% |
| 5 | THOUGHT + SELF-CHECK в content | 0/8 | ≥90% |

Bonus: **Replan discipline** (корректная реакция на `matches=0` / `ok=false`) — baseline ~20%, цель ≥80%.

### 6.2 2 LLM-judge метрики

| # | Метрика | Как оцениваем | Цель |
|---|---------|---------------|------|
| 6 | Plan quality | 1–5 по рубрике (шагов 2–5, checklist ≥2, нет повторов) | медиана ≥4 |
| 7 | Mode switch correctness | судья сверяет system+user с actual режимом | ≥90% |

### 6.3 Анти-catastrophic-forgetting

LLM-judge plain-ответов FT-модели **не хуже baseline более чем на 10%**. Если просело — расширить `plain` до 20% в датасете и переобучить.

### 6.4 Расширение под dual backend

Все 7 метрик считаются **для каждого бэкенда отдельно**. В итоге — 2 колонки "Target achieved" (OpenAI / MLX). Это позволяет увидеть:
- одинаковая ли польза от FT на разных классах моделей
- где локальная Qwen катастрофически не дотягивает (индикатор "нужна 14B вместо 7B")

---

## 7. Deliverable Дня 6

- [x] `contracts/` — контракты tools и artifacts (из advanced_day6)
- [x] `prompts/` — system + meta (из advanced_day6)
- [x] `dataset/seeds/*.json` — 12 универсальных seeds (из advanced_day6)
- [x] `dataset/gen_synthetic.py` — генератор с retry (из advanced_day6)
- [x] `dataset/train.jsonl` + `dataset/eval.jsonl` — 47/11 stratified (из advanced_day6)
- [x] `dataset/eval_plain.jsonl` — 5 концептуальных (из advanced_day6)
- [x] `validator/validate.py` (из advanced_day6)
- [x] `criteria/criteria.md` (из advanced_day6)
- [x] `baseline/outputs/` на OpenAI (из advanced_day6)
- [ ] `baseline/outputs/` на **Ollama + Qwen2.5-7B** — добавить
- [ ] `ft_client/base.py`, `ft_client/mlx_backend.py` — добавить
- [ ] `ft_client/cli.py` с `--backend` флагом — добавить
- [ ] Обновить `README.md` и `EXPLANATION.md` — вписать MLX-путь

Это реалистичный объём на 2–3 дня работы поверх существующего проекта.

---

## 8. Roadmap после Дня 6 — боевое применение

Это ключевой раздел под пользовательский вопрос "как применить модель на практике".

### 8.1 День 7+ — runner

Минимальный python-агент (~300–500 строк), который:
- Принимает `(task_id, user_message)` и `tools_schema` из `contracts/`
- В цикле: вызывает модель через OpenAI-compat (Ollama), получает `tool_calls`
- Реализует tool_results:
  - **State tools** — через файл-scratchpad `.tasks/<task_id>/` (как в advanced_day6 variant B)
  - **Project tools** — через MCP-сервер (см. 8.2)
- Валидирует каждый шаг на соответствие `criteria.md`
- Останавливается по terminal condition (all steps DONE) или по лимиту попыток

### 8.2 MCP-сервер для project tools

Отдельный python-процесс (~150–200 строк):
```python
@mcp.tool
def read_file(path: str) -> str:
    return (WORKSPACE / path).read_text()

@mcp.tool
def list_dir(path: str) -> list[str]:
    return sorted(os.listdir(WORKSPACE / path))

@mcp.tool
def search_and_replace(path: str, old_text: str, new_text: str) -> dict:
    content = (WORKSPACE / path).read_text()
    matches = content.count(old_text)
    if matches == 1:
        (WORKSPACE / path).write_text(content.replace(old_text, new_text))
    return {"ok": matches == 1, "matches": matches}

@mcp.tool
def write_file(path: str, content: str) -> dict:
    (WORKSPACE / path).write_text(content)
    return {"ok": True}
```

**Ключевая особенность**: MCP-сервер принимает путь к воркспейсу через конфиг → **один сервер, любой проект**. Меняешь `WORKSPACE` — получаешь агент для другого проекта, **без переобучения модели**.

### 8.3 Integration test на `kmm/stocks`

Именно здесь `/plans/temp/board/pool/*.md` становится пригодным:

1. Запустить runner с моделью `stocks-ft` (локальная Qwen+LoRA)
2. Подать задачу `/plans/temp/board/pool/1.md` как `user_message`
3. Runner + MCP отрабатывают, модель выдаёт план + действия
4. Сравнить с эталонным `/plans/temp/status/1/PLAN.result.md`
5. Посчитать integration-метрику: `files_jaccard`, `steps_count_delta`, `assembleDebug_passes`

Это **настоящий боевой замер переносимости**: датасет универсальный → модель обучилась паттерну → на неизвестном ей реальном проекте показывает качество близкое к эталону.

### 8.4 Сценарии применения (из обсуждения)

| Сценарий | Что нужно дополнительно | Когда окупается |
|----------|-------------------------|------------------|
| Персональный локальный агент | runner + MCP | сразу |
| Агент для команды KMP | + конфиг MCP под их проект | 5+ разработчиков |
| NDA-safe агент для энтерпрайза | + hardening MCP (permissions, audit log) | коммерческий кейс |
| Семья LoRA-адаптеров (multi-project) | + реестр адаптеров, автопереключение | 3+ разных проекта |
| Публичный датасет/benchmark | + cleanup, публикация на HF | репутация/open-source |

**Главное**: модель остаётся одна и та же, меняются только слои вокруг неё. LoRA-адаптер — переносимый артефакт (~20 МБ).

---

## 9. Открытые вопросы (перед стартом реализации)

1. **API-бюджет для OpenAI FT**: для dual backend нужен OpenAI ключ + $5–30 на эксперимент. Подтвердить что ОК тратить однократно на сравнительный замер. Если нет — начать с MLX, OpenAI-часть сделать в День 7+ (или отложить до полного отказа).

2. **GGUF-экспорт из MLX** — нужно проверить reproducibility цепочки `mlx_lm.fuse → convert-hf-to-gguf.py → Ollama`. Если где-то затык — быть готовым использовать `mlx_lm.server` напрямую как OpenAI-compat endpoint без Ollama-обёртки.

3. **Iterations & hyperparams для MLX**: предварительно `--iters 600 --lora-layers 16 --batch-size 1` — это разумная стартовая точка для 47-примерного train-сета на Qwen2.5-7B. Может потребовать тюнинга по eval loss.

4. **Catastrophic forgetting на Qwen локальной**: `eval_plain.jsonl` критичен. Qwen2.5-7B после FT может просесть на prose-ответах сильнее чем gpt-4o-mini. Если ≥20% провал — увеличить plain-долю и переобучить.

---

## 10. Ключевые принципы (TL;DR)

1. **FT прошивает форму, не знания.** Seeds универсальные, знание проекта — в рантайме через MCP.
2. **Один датасет, два бэкенда.** OpenAI и MLX принимают идентичный JSONL.
3. **Замеры на обоих бэкендах.** Показывает что FT работает и на дорогой, и на дешёвой модели.
4. **Переносимость через абстракцию tools.** MCP-сервер меняет `WORKSPACE` — модель работает на любом KMP-проекте.
5. **kmm/stocks — только песочница для integration-теста, не источник seeds.** Проект не эталонный, его паттерны в датасете сузили бы применимость модели.

---

## Приложение A — Эволюция замысла (что передумали и почему)

Не для исполнения, а для честного фиксирования хода рассуждений. Если в будущем возникнет соблазн вернуться к одной из отброшенных идей — ниже причины, почему это будет ошибкой.

### A.1 Первая попытка: "обучить state-machine discipline с нуля"

**Идея**: свой граф стейтов (Init → Plan → Develop → Verify → Done), свои 7 тулов, датасет только про переходы между стейтами.

**Почему отброшено**:
- Дублирует оркестрацию, которую уже делает Claude Code skill (`custom-task-manager`)
- Не лечит реальную боль локалки — она "ходит по кругу" внутри одного шага, а не между стейтами
- Нет готового датасета под такую узкую цель

### A.2 Вторая попытка: "action-log discipline внутри шага"

**Идея**: учить модель вести журнал своих действий и не повторять.

**Почему отброшено**:
- Симптом локалки ("три разных фикса подряд") — это **reasoning limitation**, а не memory problem. Модель пробует **разные** действия, не повторяет одно и то же.
- FT не лечит reasoning — это архитектурное ограничение 7B-модели
- Решение должно быть на уровне **harness + structured decoding**, а не весов модели

### A.3 Третья попытка: "файнтюн PLAN-агента под kmm/stocks"

**Идея**: использовать `/plans/temp/status/*/PLAN.result.md` как эталонные данные, обучить модель генерировать план в формате pipeline.

**Почему отброшено**:
- kmm/stocks не эталонный — обучение на нём размазало бы плохие паттерны
- Узкая привязка к одному проекту убивает применимость модели вне его
- Потребовало бы сложную реконструкцию `messages` с `tool_calls` из прозаических `log.md`
- Реальный объём данных (13 задач) слишком мал

### A.4 Итоговое решение: forkнуть advanced_day6

**Почему именно это**:
- 90% работы уже сделано профессионально (seeds, validator, метрики, baseline с реальными числами)
- Архитектура seeds намеренно универсальная → переносимость "из коробки"
- Добавка MLX-бэкенда — 1–2 дня работы, не недели
- Roadmap к боевому применению (runner + MCP) архитектурно подготовлен самим проектом (Variant B → Variant A)
- kmm/stocks остаётся полезным — как integration-песочница, не как источник seeds

Этот план — результат **пяти последовательных уточнений цели**, каждое из которых сужало задачу и делало решение более конкретным. Финальная форма — форк готового решения с минимальными правками под локальный стек — это самый экономный путь к цели Дня 6 с максимальным потенциалом расширения в Дне 7+.
