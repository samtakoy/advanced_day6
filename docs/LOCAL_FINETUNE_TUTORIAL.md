# Локальный fine-tune на Mac: пошаговый туториал

Практический дневник: как мы взяли Qwen 2.5 7B, обучили на 45 примерах extraction-задач и импортировали в Ollama. С ошибками, тупиками и решениями.

> **Кому это**: разработчику, который впервые слышит слова MLX, GGUF, LoRA и хочет понять что происходит.

---

## Словарик

| Термин | Что это простыми словами |
|--------|------------------------|
| **MLX** | Фреймворк от Apple для ML на Apple Silicon. Аналог PyTorch, но оптимизирован под M1/M2/M3/M4. |
| **LoRA / QLoRA** | Способ дообучить модель, меняя не все 7 млрд параметров, а маленькую "надстройку" (~6 млн). Как наклейка на учебник. **QLoRA** = LoRA + квантизация (экономия памяти). |
| **Адаптер** | "Надстройка" от LoRA. Файл ~25 МБ вместо 15 ГБ всей модели. |
| **Fuse (слияние)** | Объединить адаптер с моделью в одну. Как вклеить наклейки в книгу. |
| **GGUF** | Формат модели для Ollama. Как .mp4 для видео — один файл, внутри всё. |
| **Ollama** | Программа для запуска LLM локально. Как Docker, но для моделей. |
| **mask-prompt** | Считать loss только по ответам модели, не по промптам. Модель учится отвечать, а не запоминать вопросы. |
| **loss** | Число «насколько модель ошибается». Чем ниже — тем лучше. |
| **val loss** | Loss на примерах, которые модель не видела при обучении. Если растёт — переобучение. |

---

## Что нам понадобится

- Mac с Apple Silicon (M1/M2/M3/M4), минимум 32 ГБ RAM (у нас M4 Max 48 ГБ)
- Python 3.10+ с virtualenv
- Ollama (для запуска моделей)
- Наш датасет (45 train + 11 eval примеров в JSONL)

---

## Шаг 0. Подготовка

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install mlx mlx-lm
```

**Зачем venv?** Системный Python (или Anaconda) может содержать пакеты, несовместимые с MLX (например MPICH вызывает SIGABRT). Venv изолирует окружение.

---

## Шаг 1. Сборка датасета

```bash
python -m src.dataset.build_dataset
python -m src.validator.validate
```

Первая команда парсит `data/extraction/gold.md` + prose-файлы → собирает `data/out/train.jsonl` (45 примеров) и `eval.jsonl` (11).

Вторая — проверяет схему, таксономию, дубли, leakage между train/eval.

---

## Шаг 2. Baseline — замер "до"

```bash
python -m src.baseline.run_baseline \
  --provider ollama --model qwen2.5:7b-instruct \
  --from-jsonl data/out/eval.jsonl --num-ctx 4096
```

Отправляет system+user в модель, парсит JSON-ответ, считает метрики. Результаты в `data/baseline/eval/qwen2.5-7b-instruct/`.

---

## Шаг 3. Обучение

```bash
pkill -f ollama  # освободить GPU

python -m src.ft_client.mlx.train \
  --iters 200 --batch-size 1 --grad-accum-steps 2 \
  --learning-rate 1e-5 --max-seq-length 3072 \
  --save-every 25 --steps-per-eval 25 --val-batches 11
```

**Параметры:**

| Параметр | Значение | Зачем |
|----------|----------|-------|
| `--iters 200` | 200 итераций | ~4 эпохи на 45 примерах. Оптимум обычно 75-100 |
| `--batch-size 1` | 1 пример за раз | Экономит RAM |
| `--grad-accum-steps 2` | Накопление градиентов | Эффективный batch=2, стабильнее обучение |
| `--learning-rate 1e-5` | Скорость обучения | 2e-5 переобучается вдвое быстрее |
| `--max-seq-length 3072` | Макс. длина примера | Самый длинный ~2715 токенов |
| `--mask-prompt` | (включён по умолчанию) | Loss только по assistant-ответу |
| `--save-every 25` | Чекпоинт каждые 25 | Можно откатиться к лучшему |

**Как понять что обучение идёт нормально?**

Смотрим val loss каждые 25 итераций:
```
Iter  25: Val loss 0.386    ← падает, хорошо
Iter  50: Val loss 0.349    ← падает
Iter  75: Val loss 0.323    ← минимум!
Iter 100: Val loss 0.323    ← плато
Iter 125: Val loss 0.336    ← растёт → переобучение
```

Берём чекпоинт с минимальным val loss (iter 75 или 100).

**Время:** ~10-15 минут на M4 Max. Peak RAM: ~25 ГБ.

---

## Шаг 4. Экспорт в Ollama

```bash
# Подставить лучший чекпоинт
cp data/mlx/<run>/adapters/0000100_adapters.safetensors \
   data/mlx/<run>/adapters/adapters.safetensors

# Fuse (merge адаптера с моделью)
python -m mlx_lm.fuse \
  --model Qwen/Qwen2.5-7B-Instruct \
  --adapter-path data/mlx/<run>/adapters \
  --save-path data/mlx/qwen2.5-7b-instruct/fused

# GGUF конвертация
git clone --depth 1 https://github.com/ggerganov/llama.cpp.git /tmp/llama_cpp_fresh
python /tmp/llama_cpp_fresh/convert_hf_to_gguf.py \
  data/mlx/qwen2.5-7b-instruct/fused \
  --outfile data/mlx/qwen2.5-7b-instruct/fused/model.gguf

# Создать модель в Ollama (с chat template!)
ollama serve &  # если не запущена
ollama show qwen2.5:7b-instruct --template  # скопировать template
# Создать Modelfile с FROM model.gguf + TEMPLATE + stop-токены
ollama create kmp_extract_ft -f /tmp/Modelfile_extract
```

**Критично:** без TEMPLATE модель теряет chat format и галлюцинирует.

---

## Шаг 5. Eval — замер "после"

```bash
python -m src.baseline.run_baseline \
  --provider ollama --model kmp_extract_ft \
  --from-jsonl data/out/eval.jsonl --num-ctx 4096
```

Сравниваем с baseline из шага 2.

---

## Проблемы, на которые мы наступили

### OOM (Out of Memory)
- `--batch-size 2` → 33 ГБ, мигание экрана на 48 ГБ Mac
- **Решение:** `--batch-size 1 --grad-accum-steps 2` — тот же эффективный batch, вдвое меньше RAM

### Модель галлюцинирует после экспорта
- Ollama: `FROM model.gguf` без TEMPLATE → модель продолжает случайный текст
- **Решение:** скопировать template из `ollama show qwen2.5:7b-instruct --template` в Modelfile

### GGUF конвертер падает
- `llama-cpp-python` в pip: конвертер новее пакета `gguf`, падает на `GEMMA4`
- **Решение:** клонировать свежий `llama.cpp` и использовать его `convert_hf_to_gguf.py`

### f16 модель слишком большая
- GGUF без квантизации: 14 ГБ, Ollama загружает 29 ГБ с KV-кэшем
- **Решение:** для продакшена — квантизовать в q4_K_M (~4 ГБ)

### Переобучение наступает быстро
- На 45 примерах оптимум: 75-100 итераций (~2 эпохи)
- Val loss растёт после iter 125 — модель заучивает примеры
- **Решение:** частые чекпоинты (`--save-every 25`), брать лучший по val loss

### max-seq-length 2048 обрезает примеры
- Qwen tokenizer: русский текст ≈ 1.5x от оценки `len/4`
- Самый длинный пример: 2715 токенов
- **Решение:** `--max-seq-length 3072`
