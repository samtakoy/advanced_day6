# Промежуточный эксперимент: baseline extraction на train-сете (до fine-tune)

**Дата:** 2026-04-23
**Цель:** замерить качество extraction без дообучения — на двух локальных моделях через Ollama. Служит точкой отсчёта для оценки эффекта fine-tune.

## Условия

- **Датасет:** 45 train-примеров (extraction: свободный текст → JSON с 7 полями)
- **System prompt:** единый, ~900 токенов (таксономия 21 модуля, 6 блоков, правила)
- **Температура:** 0.3
- **Контекст:** дефолтный (~32K, в будущих прогонах можно снизить до 4096 через `--num-ctx`)

### Модели

| Модель | Размер | Провайдер |
|---|---|---|
| Qwen 2.5 7B Instruct | 4.7 GB (q4) | Ollama local |
| gpt-oss 20B | 13 GB (q4) | Ollama local |

## Результаты

### Метрики (по примерам с успешным JSON-парсингом)

| Метрика | Qwen 2.5 7B (41/45) | gpt-oss 20B (44/45) | Цель после FT |
|---|---|---|---|
| type exact match | 36/41 (88%) | 40/44 (91%) | 100% |
| block exact match | 25/41 (61%) | 38/44 (86%) | 100% |
| **modules IoU (avg)** | **0.376** | **0.618** | **≥ 0.9** |
| dependsOn IoU (avg) | 0.785 | 0.856 | ≥ 0.95 |
| AC recall (avg) | 0.000 | 0.000 | ≥ 0.75 |
| OoS precision (avg) | 0.356 | 0.364 | = 1.0 |

### Распределение modules IoU

| modules IoU | Qwen 7B | gpt-oss 20B |
|---|---|---|
| = 0.0 (полный промах) | 8/41 (20%) | 7/44 (16%) |
| = 1.0 (идеальное совпадение) | 6/41 (15%) | 17/44 (39%) |

### Ошибки валидатора (schema compliance)

| Тип ошибки | Qwen 7B | gpt-oss 20B | Описание |
|---|---|---|---|
| bad_module_alias | 19 | 5 | Модель пишет путь вместо алиаса (`modules:features:main` вместо `m-main`) или выдумывает алиас (`cf-theme`, `fa-chart`) |
| json_parse | 4 | 1 | Модель обернула JSON в markdown или добавила текст |
| bad_block | 1 | 0 | Несуществующий блок (`alerts` вместо `breadth`) |
| bad_deps | 0 | 1 | `dependsOn[0]` — вне диапазона 1..99 |
| **Всего** | **24** | **7** | |
| **Schema valid** | **31/45 (69%)** | **40/45 (89%)** | |

### Токены

| | Qwen 7B | gpt-oss 20B |
|---|---|---|
| tokens in (total) | 73,745 | 69,322 |
| tokens out (total) | 11,687 | 47,181 |
| avg out per example | ~260 | ~1,049 |

## Анализ

### Главная проблема — modules

`modules IoU` — ключевая метрика, подтверждающая необходимость fine-tune:

1. **Путаница путь vs алиас.** Модели знают структуру проекта из system prompt, но не могут устойчиво маппить на алиасы. Qwen пишет `core-features/stocks` вместо `cf-stocks`, gpt-oss — `core/utils` вместо `utils`.

2. **Выдуманные алиасы.** Модели экстраполируют паттерн: видят `cf-stocks`, `cf-indicators` и генерируют `cf-theme` (должно быть просто `theme`) или `cf-telemetry` (должно быть `NEW::modules:core:telemetry`).

3. **Ложные модули.** Модели включают модули, которые упомянуты в тексте как классы/пакеты, но не правятся в задаче (пример из day6-плана: `StocksDatabase` → модель думает `db`, а правильно `cf-stocks`).

### AC recall = 0

Обе модели генерируют критерии приёмки **своими словами** — семантически могут быть близки к gold, но exact string match даёт 0. Для честной оценки нужен LLM-as-judge. Это ожидаемо и не является проблемой данных.

### gpt-oss 20B — болтливый

gpt-oss генерирует в 4x больше токенов на ответ (~1049 vs ~260). Часто добавляет пояснения, расширенные формулировки AC. Для extraction это нежелательно — модель должна возвращать только JSON.

## Что дальше

1. **Fine-tune** на 45 train-примерах — Qwen 7B через MLX (локально)
2. **Post-FT eval** на 11 eval-примерах — те же метрики
3. **Сравнение** baseline vs post-FT — ожидаем modules IoU ≥ 0.9, schema valid = 100%
4. **AC recall** — добавить LLM-as-judge для семантического сравнения критериев

## Воспроизведение

```bash
# Сборка датасета
python -m src.dataset.build_dataset

# Прогон baseline
python -m src.baseline.run_baseline --provider ollama --model qwen2.5:7b-instruct \
    --from-jsonl data/out/train.jsonl --num-ctx 4096

python -m src.baseline.run_baseline --provider ollama --model gpt-oss:20b \
    --from-jsonl data/out/train.jsonl --num-ctx 4096

# Результаты
cat data/baseline/train/qwen2.5-7b-instruct/summary.md
cat data/baseline/train/gpt-oss-20b/summary.md
```

---

# Промежуточный эксперимент 2: подбор гиперпараметров LoRA fine-tune

**Дата:** 2026-04-23
**Цель:** найти оптимальные гиперпараметры для LoRA fine-tune Qwen 2.5 7B Instruct на extraction-датасете (45 train / 11 eval). Критерий — минимальный val loss без переобучения.

## Условия

- **Модель:** Qwen/Qwen2.5-7B-Instruct (7B параметров, f16)
- **Метод:** QLoRA через mlx_lm.lora
- **LoRA layers:** 8 (из 28)
- **Trainable параметры:** 5.767M / 7615.617M (0.076%)
- **Платформа:** Mac M4 Max, 48 GB unified memory
- **mask-prompt:** да (loss только по assistant-ответу)

## Три прогона

### Run A — базовый (batch=1, lr=1e-5)

```
--iters 300 --batch-size 1 --learning-rate 1e-5 --max-seq-length 4096
```

| Iter | Val loss | Train loss | Эпохи |
|---|---|---|---|
| 1 | 0.823 | — | 0 |
| 50 | **0.327** | 0.354 | ~1.1 |
| 100 | 0.328 | 0.094 | ~2.2 |
| 150 | 0.366 ↑ | 0.042 | ~3.3 |
| 200 | 0.452 ↑ | 0.022 | ~4.4 |
| 250 | 0.524 ↑ | 0.013 | ~5.6 |
| 300 | 0.542 ↑ | 0.006 | ~6.7 |

Peak mem: **27.3 GB**. Лучший чекпоинт: **iter 50** (val=0.327). Переобучение с iter 150.

### Run B — большой батч (batch=2, lr=2e-5)

```
--iters 200 --batch-size 2 --learning-rate 2e-5 --max-seq-length 3072
```

| Iter | Val loss | Train loss |
|---|---|---|
| 1 | 0.841 | — |
| 25 | 0.381 | — |
| 50 | 0.345 | 0.385 |
| 75 | 0.447 ↑ | — |

Peak mem: **33.4 GB** — GPU memory pressure, мигания экрана. Прогон остановлен на iter 75.

Попытка с `--max-seq-length 2048` дала truncation (самый длинный пример 2715 токенов) — оценка `len/4` занижает реальное число токенов для русского текста.

LR=2e-5 при batch=2 — переобучение ещё быстрее чем Run A. Batch=2 на 48GB Mac — на пределе.

### Run C — grad accumulation (batch=1, grad_accum=2, lr=1e-5)

```
--iters 150 --batch-size 1 --grad-accum-steps 2 --learning-rate 1e-5 --max-seq-length 3072
```

Эффективный batch=2 при RAM batch=1.

| Iter | Val loss | Train loss | Эпохи |
|---|---|---|---|
| 1 | 0.823 | — | 0 |
| 25 | 0.381 | 0.648 | ~0.6 |
| 50 | 0.349 | 0.385 | ~1.1 |
| 75 | **0.321** | 0.274 | ~1.7 |
| 100 | 0.324 | 0.153 | ~2.2 |
| 125 | 0.348 ↑ | 0.174 | ~2.8 |
| 150 | 0.339 | 0.094 | ~3.3 |

Peak mem: **27.4 GB**. Лучший чекпоинт: **iter 75** (val=0.321).

## Сравнение лучших чекпоинтов

| Прогон | Лучший iter | Val loss | Peak RAM | Начало переобучения |
|---|---|---|---|---|
| Run A (bs=1, lr=1e-5) | 50 | 0.327 | 27.3 GB | iter 150 (~3 эпохи) |
| Run B (bs=2, lr=2e-5) | 50 | 0.345 | 33.4 GB | iter 75 (~1.7 эпохи) |
| **Run C (bs=1, ga=2, lr=1e-5)** | **75** | **0.321** | **27.4 GB** | **iter 125 (~2.8 эпохи)** |

## Выводы

1. **Grad accumulation — лучший вариант.** Run C дал минимальный val loss (0.321) при том же расходе RAM что и Run A. Стабильнее градиенты замедляют переобучение.

2. **Batch=2 физический — не вариант на 48GB.** 33 GB + мигания экрана. Grad accumulation решает задачу без нагрузки на память.

3. **lr=1e-5 лучше чем 2e-5.** При 2e-5 переобучение наступает вдвое быстрее. На 45 примерах агрессивный LR вреден.

4. **Оптимум: 1-2 эпохи.** Extraction-задача простая — модель схватывает таксономию за 50-100 итераций, дальше заучивает конкретные примеры.

5. **max-seq-length: 3072 минимум.** Самый длинный пример — 2715 токенов (Qwen tokenizer, русский текст). Оценка `len(text)//4` занижает — реально ~1.5x для кириллицы.

## Следующий шаг

Экспорт Run C iter 75 (val=0.321) в Ollama → прогон eval → сравнение extraction-метрик с baseline.

## Воспроизведение

```bash
# Run A
python -m src.ft_client.mlx.train --iters 300 --batch-size 1 --learning-rate 1e-5 \
  --max-seq-length 4096 --save-every 50 --steps-per-eval 50 --val-batches 11 \
  --adapter-path data/mlx/run-a-bs1-lr1e5/adapters

# Run B (остановлен из-за OOM)
python -m src.ft_client.mlx.train --iters 200 --batch-size 2 --learning-rate 2e-5 \
  --max-seq-length 3072 --save-every 25 --steps-per-eval 25 --val-batches 11 \
  --adapter-path data/mlx/run-b-bs2-lr2e5/adapters

# Run C (победитель)
python -m src.ft_client.mlx.train --iters 150 --batch-size 1 --grad-accum-steps 2 \
  --learning-rate 1e-5 --max-seq-length 3072 \
  --save-every 25 --steps-per-eval 25 --val-batches 11 \
  --adapter-path data/mlx/run-c-bs1-ga2-lr1e5/adapters
```

---

# Промежуточный эксперимент 3: eval fine-tuned модели vs baseline

**Дата:** 2026-04-23
**Цель:** сравнить extraction-метрики fine-tuned модели (Run C, iter 75) с базовой Qwen 2.5 7B Instruct на eval-сете (11 примеров, не виденных при обучении).

## Экспорт модели

### Пайплайн
1. **Fuse** — merge LoRA-адаптера (iter 75) с базовой моделью → HuggingFace safetensors
2. **GGUF конвертация** — через `/tmp/llama_cpp_fresh/convert_hf_to_gguf.py` (пакетный `convert_hf_to_gguf.py` из `llama-cpp-python` падал на `gguf.MODEL_ARCH.GEMMA4` — несовместимость версий)
3. **Ollama create** — с явным TEMPLATE из `qwen2.5:7b-instruct` (без template модель галлюцинирует — теряет chat format)

### Грабли при экспорте

1. **GGUF конвертер из `llama-cpp-python`** — версия конвертера новее пакета `gguf`, падает при импорте на `GEMMA4`. Решение: склонировать свежий `llama.cpp` в `/tmp/` и использовать его `convert_hf_to_gguf.py`.

2. **Модель без chat template** — `FROM model.gguf` без `TEMPLATE` → модель не форматирует чат, выдаёт мусор (продолжает случайный текст вместо JSON). Решение: скопировать TEMPLATE из `ollama show qwen2.5:7b-instruct --template` в Modelfile + добавить stop-токены `<|im_start|>`, `<|im_end|>`.

3. **f16 модель = 14 GB GGUF** — без квантизации Ollama загружает 29 GB (модель + KV-кэш). На 48 GB Mac работает, но медленно и не оставляет места для второй модели. Для продакшена — квантизовать в q4_K_M (~4 GB).

## Результаты eval (11 примеров)

| Метрика | Qwen 7B base | **kmp_extract_ft** | Изменение |
|---|---|---|---|
| JSON parse | 9/11 (82%) | **11/11 (100%)** | **+18%** |
| type match | 8/9 (89%) | **10/11 (91%)** | +2% |
| block match | 5/9 (56%) | **8/11 (73%)** | **+17%** |
| **modules IoU** | **0.500** | **0.667** | **+0.167** |
| dependsOn IoU | 0.833 | 0.864 | +0.031 |
| AC recall | 0.000 | **0.371** | **+0.371** |
| OoS precision | 0.500 | **0.697** | +0.197 |
| schema valid | 7/11 (64%) | **10/11 (91%)** | **+27%** |
| validation errors | 6 | **2** | **-4** |
| tokens out (total) | 3,035 | **1,058** | **-65%** |

### Per-example modules IoU

| Пример | Gold title | Base | FT |
|---|---|---|---|
| eval_01 | БД и домен Workspace + ChartSlot | fail (JSON) | 0.33 |
| eval_02 | Движок индикаторов | fail (JSON) | **1.00** |
| eval_03 | Метрики по серии сегментов | 0.50 | 0.50 |
| eval_04 | Кросс-навигация | 0.33 | 0.33 |
| eval_05 | Изоляция SQLDelight через DAO | 0.50 | **1.00** |
| eval_06 | Теги и группировка воркспейсов | 0.67 | 0.67 |
| eval_07 | Детектор дивергенций RSI | 0.00 | **1.00** |
| eval_08 | Шорты в бэктесте | **1.00** | **1.00** |
| eval_09 | Desktop system tray | 0.00 | 0.00 |
| eval_10 | О приложении в Settings | 0.50 | 0.50 |
| eval_11 | Юнит-тесты на CsvParser | **1.00** | **1.00** |

### Оставшиеся ошибки валидатора (FT модель)

Только eval_09 (Desktop system tray):
- `composeApp/desktopMain` — не алиас и не `NEW:` (должно быть `NEW::composeApp`)
- `core/utils` — не алиас (должно быть `utils`)

Это adversarial-пример с `NEW::composeApp` — модель видела мало примеров с `NEW:` синтаксисом.

## Анализ

### Что улучшилось
1. **JSON parse 100%** — модель научилась возвращать чистый JSON без markdown-обёрток
2. **AC recall с 0 до 0.37** — модель начала копировать формулировки критериев из входа вместо придумывания своих
3. **Ответы в 3x компактнее** (1058 vs 3035 токенов) — нет "болтовни", только JSON
4. **modules IoU: 3 примера выросли с 0.0-0.5 до 1.0** (eval_02, eval_05, eval_07) — модель выучила маппинг путей на алиасы

### Что не дотянули
1. **modules IoU 0.667 < цели 0.9** — 4 из 11 примеров ниже 0.5
2. **eval_09 (adversarial)** — `NEW:` синтаксис не выучен, модулей мало в train-сете
3. **block match 73%** — 3 промаха (eval_08, eval_09, eval_11)
4. **AC recall неравномерный** — на одних примерах 1.0 (exact match), на других 0.0

### Возможные причины недотяга
- **45 train-примеров** — мало для устойчивого маппинга 21 алиаса + `NEW:` синтаксис
- **iter 75 (~1.7 эпохи)** — модель видела каждый пример менее 2 раз
- **f16 без квантизации** — не влияет на качество, но замедляет итерации экспериментов
- **AC recall = exact string match** — занижает реальное качество; LLM-as-judge покажет выше

## Следующие шаги

1. **Квантизация** — пересобрать GGUF с `q4_K_M` для быстрого инференса
2. **Больше данных** — augmentation существующих примеров (перефразирование, шум)
3. **Другие чекпоинты** — попробовать iter 100 (val=0.324, чуть больше обучения)
4. **LLM-as-judge** — для AC recall и OoS precision, exact match слишком строг

## Воспроизведение

```bash
# Подставить чекпоинт iter 75
cp data/mlx/run-c-bs1-ga2-lr1e5/adapters/0000075_adapters.safetensors \
   data/mlx/run-c-bs1-ga2-lr1e5/adapters/adapters.safetensors

# Fuse
python -m mlx_lm.fuse --model Qwen/Qwen2.5-7B-Instruct \
  --adapter-path data/mlx/run-c-bs1-ga2-lr1e5/adapters \
  --save-path data/mlx/qwen2.5-7b-instruct/fused

# GGUF (через свежий llama.cpp)
python /tmp/llama_cpp_fresh/convert_hf_to_gguf.py \
  data/mlx/qwen2.5-7b-instruct/fused \
  --outfile data/mlx/qwen2.5-7b-instruct/fused/model.gguf

# Ollama (с template!)
ollama create kmp_extract_ft -f /tmp/Modelfile_extract

# Eval
python -m src.baseline.run_baseline --provider ollama --model kmp_extract_ft \
  --from-jsonl data/out/eval.jsonl --num-ctx 4096

# Baseline для сравнения
python -m src.baseline.run_baseline --provider ollama --model qwen2.5:7b-instruct \
  --from-jsonl data/out/eval.jsonl --num-ctx 4096
```
