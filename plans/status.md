# Status: Day 6 — Fine-tune KMP-агента

Последнее обновление: 2026-04-22

## Задание

День 6 AI Advent: подготовить датасет для fine-tune маленькой LLM, чтобы она работала как дисциплинированный агент-исполнитель для Kotlin Multiplatform проекта.

**Цель FT** — не новые знания, а **дисциплина формата**:
- Первый ход — `plan_write`
- Перед действием — `step_read`
- Каждый ответ: `THOUGHT:` + `SELF-CHECK:` + один tool_call
- При ошибке — `plan_revise`, не повторять
- На нечёткий запрос — `QUESTION:`, не угадывать

## Что сделано

### Датасет
- 12 seeds (вручную) + 46 synthetic (через LLM) = 58 примеров
- 3 режима: agent (70%), agent_question (16%), plain (14%)
- Compact system prompt (~175 токенов вместо ~800)
- Валидатор (30+ проверок) + mix_and_split (stratified 80/20)

### Baseline (без FT)
| Модель | plan_write first | task_id | THOUGHT |
|--------|:---:|:---:|:---:|
| gpt-4o-mini | 100% | 100% | 0% |
| qwen2.5-7b-instruct | 87% | 75% | 12% |
| qwen2.5-3b-instruct | 37% | 37% | 0% |
| qwen2.5-coder-7b | 0% | 0% | 0% |

### FT прогоны

#### Прогон 1: 3B, multi-turn, без mask-prompt, с tools
- iters=400, lr=5e-5, checkpoint iter-200
- **Результат: plan_write 37%->75%, task_id 37%->87%**
- Val loss: минимум на iter-200, потом рос (переобучение)

#### Прогон 2 (текущий): 3B, single-turn split, с mask-prompt, с tools
- Данные разбиты split_turns.py: 58 -> 502 single-turn примера
- Каждый assistant-ход = отдельный обучающий пример
- mask-prompt корректно маскирует промпт, учит только assistant
- **Статус: обучение запущено, 400 итераций, ждём результат**

## Найденные проблемы и решения

1. **train/eval mismatch** — тренировочные данные без `tools`, eval с tools. Модель видела разные промпты. Решение: inject tools в train.jsonl.

2. **mask-prompt + multi-turn** — маскирует все assistant-ходы кроме последнего. Модель не учится на plan_write (первый ход). Решение: split_turns.py разбивает на single-turn.

3. **Anaconda MPICH vs MLX** — `python` в PATH указывал на Anaconda с несовместимым MPICH, mlx_lm крашился с SIGABRT. Решение: всегда запускать через `.venv/bin/python` (source .venv/bin/activate).

4. **OOM при 7B + 8192 seq** — 48GB не хватает. Решение: 3B модель или уменьшить seq-length/lora-layers.

5. **loss=nan** — max-seq-length обрезал примеры, ответ модели терялся. Решение: увеличить max-seq-length.

6. **Ollama tool calling** — импорт из safetensors игнорирует TEMPLATE. Решение: конвертировать в GGUF, прописать TEMPLATE с `<tool_call>` в Modelfile.

## Что дальше

1. Дождаться результатов прогона 2 (split + mask-prompt)
2. Сравнить с прогоном 1 — стало ли лучше от правильного маскирования
3. Export в Ollama + eval через run_baseline
4. Если результат хороший — попробовать на Coder 7B (сейчас 0% baseline)
5. Обновить REPORT.md финальными результатами
6. Commit всех изменений

## Структура артефактов

```
data/
├── seeds/          # 12 оригинальных примеров
├── synthetic/      # 46 сгенерированных
├── split/          # 502 single-turn (из split_turns.py)
│   ├── seeds/
│   └── synthetic/
├── out/            # train.jsonl + eval.jsonl
├── mlx/            # MLX артефакты по моделям
│   └── qwen2.5-3b-instruct/
│       ├── adapters/   # LoRA веса
│       └── mlx_data/   # данные с injected tools
├── baseline/       # результаты baseline eval
└── contracts/      # tool schemas
```
