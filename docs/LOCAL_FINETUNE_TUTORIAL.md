# Локальный fine-tune на Mac: пошаговый туториал для новичка

Этот файл — практический дневник: как мы взяли готовую модель Qwen 2.5 7B, обучили её на 47 примерах и импортировали в Ollama. С ошибками, тупиками и решениями.

> **Кому это**: разработчику, который впервые слышит слова MLX, GGUF, LoRA и хочет понять что происходит, а не просто скопировать команды.

---

## Словарик (без него дальше будет тяжело)

| Термин | Что это простыми словами |
|--------|------------------------|
| **MLX** | Фреймворк от Apple для ML на Apple Silicon. Аналог PyTorch, но оптимизирован под чип M1/M2/M3/M4. Умеет обучать и запускать модели. |
| **LoRA / QLoRA** | Способ дообучить большую модель, меняя не все 7 миллиардов параметров, а только маленькую "надстройку" (~6 млн параметров). Как наклейка на учебник — книга та же, но с твоими пометками. **QLoRA** = LoRA + квантизация (экономия памяти). |
| **Адаптер** | Та самая "надстройка" от LoRA. Файл ~25 МБ вместо 15 ГБ всей модели. |
| **Fuse (слияние)** | Объединить адаптер с оригинальной моделью в одну полную модель. Как вклеить наклейки намертво в книгу. |
| **GGUF** | Формат файла модели, который понимает Ollama (и llama.cpp под капотом). Как .mp4 для видео — один файл, внутри всё. |
| **Ollama** | Программа для запуска LLM локально. Как Docker, но для моделей. Скачал → запустил → общаешься через API. |
| **HuggingFace** | "GitHub для моделей". Хранилище, откуда скачиваются веса моделей. |
| **Safetensors** | Формат файла весов модели от HuggingFace. Как GGUF, но другой формат. MLX работает с ним, Ollama — нет (нужна конвертация). |
| **tool calling** | Способность модели не просто отвечать текстом, а вызывать функции (tools). Модель говорит "хочу вызвать plan_write с такими аргументами", а система исполняет. |
| **mask-prompt** | Настройка обучения: считать ошибку (loss) только по ответам модели, а не по промптам. Модель учится отвечать, а не запоминать вопросы. |
| **loss** | Число, показывающее "насколько модель ошибается". Чем ниже — тем лучше. NaN = сломалось, модель ничему не учится. |
| **OOM** | Out of Memory — не хватило оперативной памяти GPU/unified memory. |
| **truncation** | Обрезка длинных примеров до max-seq-length. Если обрезать слишком много — модель видит вопрос без ответа → loss = NaN. |

---

## Что нам понадобится

- Mac с Apple Silicon (M1/M2/M3/M4), минимум 32 ГБ RAM (у нас M4 Max 48 ГБ)
- Python 3.10+ с virtualenv
- Ollama (для запуска моделей)
- Аккаунт на HuggingFace (бесплатный, для скачивания моделей)
- Наш датасет (47 train + 11 eval примеров в JSONL)

---

## Шаг 0. Подготовка окружения

```bash
# Создаём изолированное Python-окружение (чтобы не засорять систему)
python3 -m venv .venv
source .venv/bin/activate

# Ставим зависимости
pip install -r requirements.txt
pip install mlx mlx-lm        # Apple Silicon ML фреймворк
pip install torch              # нужен для конвертации в GGUF
```

**Зачем venv?** Без него пакеты ставятся в системный Python (или Anaconda). Когда у тебя 5 проектов с разными версиями библиотек — начинается ад. Venv — изолированная песочница для каждого проекта.

---

## Шаг 1. Скачать модель с HuggingFace

```bash
# Авторизация (нужен токен с huggingface.co/settings/tokens, бесплатно)
hf auth login

# Скачиваем модель (~15 ГБ, ляжет в ~/.cache/huggingface/)
hf download Qwen/Qwen2.5-7B-Instruct
```

**Почему Qwen 2.5 7B Instruct?**
- **7B** (7 миллиардов параметров) — влезает в 48 ГБ RAM при обучении
- **Instruct** — версия, обученная следовать инструкциям и работать с tool calling
- Без "instruct" — базовая модель, которая просто продолжает текст, не умеет вести диалог

**Почему не 14B?** Мы проверили — при обучении (QLoRA) 7B занимает ~37 ГБ RAM. 14B не влезет.

**Почему не Coder?** Мы прогнали baseline — Coder 7B пишет THOUGHT/SELF-CHECK идеально, но ни разу не вызвала tool call. Она не понимает tool calling протокол. А нам нужно именно это.

---

## Шаг 2. Baseline — замер "до"

Прежде чем обучать, нужно замерить как модель ведёт себя без обучения. Иначе не с чем сравнивать.

```bash
python -m src.baseline.run_baseline \
  --provider ollama \
  --model "qwen2.5:7b-instruct" \
  --from-jsonl data/out/eval.jsonl
```

Скрипт берёт каждый пример из eval.jsonl, отправляет начало диалога (system + user) в модель и смотрит что она ответит. Результаты — в `data/baseline/eval/qwen2.5-7b-instruct/`.

**Наш результат baseline:**
- plan_write первым: 75% (6/8)
- THOUGHT в ответе: 87% (7/8)
- SELF-CHECK в ответе: 87% (7/8)

Неплохо, но не идеально. Цель FT — дожать до 95-100%.

---

## Шаг 3. Подготовка данных для MLX

MLX ожидает папку с `train.jsonl` и `valid.jsonl`. Наш скрипт `train.py` делает это автоматически, но полезно понимать что происходит:

1. Берёт `data/out/train.jsonl` и `data/out/eval.jsonl`
2. (Опционально) добавляет tool schemas из `data/contracts/tool_schemas.json` в каждую строку
3. Кладёт результат в `data/mlx/<model-slug>/mlx_data/`

**Проблема, на которую мы наступили: tools раздувают размер**

Каждый пример содержит: system prompt + tools schemas + user message + assistant response. Tools schemas (9 инструментов с описаниями и параметрами) добавляют ~1500 токенов к каждому примеру. При лимите 4096 токенов на пример — это 37% бюджета уходит на одинаковые описания инструментов.

**Решение:** убрать tools из тренировочных данных. Модель и так видит имена tools в system prompt и в tool_calls ответов. Набор tools фиксирован (всегда одни и те же 9), модели не нужно учиться "выбирать по описанию".

---

## Шаг 4. Обучение (LoRA fine-tune)

```bash
python -m mlx_lm.lora \
  --model Qwen/Qwen2.5-7B-Instruct \
  --data data/mlx/qwen2.5-7b-instruct/mlx_data \
  --train \
  --mask-prompt \
  --iters 600 \
  --num-layers 8 \
  --batch-size 1 \
  --learning-rate 1e-5 \
  --adapter-path data/mlx/qwen2.5-7b-instruct/adapters \
  --max-seq-length 4096 \
  --val-batches 5
```

**Что значит каждый параметр:**

| Параметр | Значение | Зачем |
|----------|----------|-------|
| `--model` | HuggingFace ID модели | Какую модель дообучаем |
| `--data` | Папка с train/valid.jsonl | Данные для обучения |
| `--train` | — | Режим обучения (а не генерации) |
| `--mask-prompt` | — | Считать loss только по ответам, не по промптам |
| `--iters 600` | 600 итераций | ~12 эпох на 47 примерах (47 × 12 ≈ 564) |
| `--num-layers 8` | 8 LoRA-слоёв | Сколько слоёв модели адаптируем. Больше = лучше качество, но больше RAM |
| `--batch-size 1` | 1 пример за раз | Минимум, экономит RAM |
| `--learning-rate 1e-5` | 0.00001 | Скорость обучения. Слишком большая — модель "забудет" базовые знания |
| `--adapter-path` | Куда сохранить | Путь для LoRA-адаптера |
| `--max-seq-length 4096` | Макс. длина примера | Примеры длиннее обрезаются |
| `--val-batches 5` | 5 примеров на валидацию | Каждые N итераций проверяем loss на eval |

**Как понять что обучение идёт нормально?**

Смотри на строки `Iter N: Train loss X.XXX`:
```
Iter  10: Train loss 1.765    ← начало, модель ошибается
Iter 100: Train loss 0.198    ← учится
Iter 300: Train loss 0.012    ← почти выучила
Iter 600: Train loss 0.005    ← готово
```

Loss должен **падать**. Если loss = **nan** — что-то сломалось (см. проблемы ниже).

Val loss (на eval данных) тоже должен падать, но может слегка расти к концу — это нормальный лёгкий overfitting.

**Время:** ~40-50 минут на M4 Max для 600 итераций.

---

## Шаг 5. Слияние адаптера с моделью (fuse)

После обучения у нас маленький адаптер (~25 МБ). Чтобы использовать модель — нужно "вклеить" адаптер в оригинал:

```bash
python -m mlx_lm.fuse \
  --model Qwen/Qwen2.5-7B-Instruct \
  --adapter-path data/mlx/qwen2.5-7b-instruct/adapters \
  --save-path data/mlx/qwen2.5-7b-instruct/fused
```

Результат: полная модель в HuggingFace формате (safetensors) в папке `fused/`.

---

## Шаг 6. Конвертация в GGUF

Ollama не понимает safetensors. Нужно сконвертировать в GGUF:

```bash
# Нужен конвертер из llama.cpp (одноразовая установка)
git clone --depth 1 https://github.com/ggml-org/llama.cpp.git /tmp/llama.cpp

# Конвертация (~15 ГБ файл, занимает ~20 секунд)
python /tmp/llama.cpp/convert_hf_to_gguf.py \
  data/mlx/qwen2.5-7b-instruct/fused/ \
  --outfile data/mlx/qwen2.5-7b-instruct/fused/model.gguf \
  --outtype f16
```

**Почему не safetensors напрямую?** Ollama умеет импортировать safetensors (`FROM <папка>`), но при этом **теряет chat template** — и модель перестаёт поддерживать tool calling. С GGUF мы можем явно указать template, и Ollama его примет.

---

## Шаг 7. Импорт в Ollama

Создаём `Modelfile` — инструкцию для Ollama, как собрать модель:

```
FROM /path/to/model.gguf

TEMPLATE """...<chat template от Qwen 2.5>..."""

PARAMETER stop "<|im_start|>"
PARAMETER stop "<|im_end|>"
```

Chat template — это шаблон, который говорит Ollama как форматировать диалог для модели. **Без него tool calling не работает.** Template берём из оригинальной модели:

```bash
ollama show qwen2.5:7b-instruct --modelfile
```

Импортируем:
```bash
ollama create kmp-agent-ft -f Modelfile
```

Проверяем:
```bash
ollama list | grep kmp
# kmp-agent-ft:latest    15 GB    just now
```

---

## Шаг 8. Eval — замер "после"

Прогоняем тот же eval что и в шаге 2, но на обученной модели:

```bash
python -m src.baseline.run_baseline \
  --provider ollama \
  --model "kmp-agent-ft" \
  --from-jsonl data/out/eval.jsonl
```

Сравниваем с baseline. Если метрики выросли — fine-tune помог.

---

## Проблемы, на которые мы наступили (и как решили)

### Проблема 1: loss = NaN

**Симптом:** `Iter 10: Train loss nan` — модель ничему не учится.

**Причина:** `--mask-prompt` + длинные примеры. При обрезке (truncation) до max-seq-length от ответа модели ничего не оставалось — весь ответ в "хвосте", который обрезан. Loss считается по пустоте → NaN.

**Решения (что пробовали):**
1. Убрать `--mask-prompt` → loss стал числовым, но модель учит и промпты (менее чистое обучение)
2. Увеличить `--max-seq-length` → OOM (не хватило RAM)
3. **Сократить system prompt** (с ~800 до ~175 токенов) — помогло частично
4. **Убрать tools из данных** (~1500 токенов экономии) — помогло, примеры влезли в 4096

### Проблема 2: OOM (Out of Memory)

**Симптом:** `[METAL] Command buffer execution failed: Insufficient Memory`

**Причина:** Apple Silicon использует unified memory (общая для CPU и GPU). 7B модель + данные + градиенты = ~37 ГБ. При max-seq-length > 4096 не влезает в 48 ГБ.

**Решения:**
- `--num-layers 8` вместо 16 (меньше адаптируемых слоёв = меньше RAM)
- `--max-seq-length 4096` (не больше)
- `--batch-size 1` (минимум)
- Закрыть тяжёлые приложения (браузер с 100 вкладками тоже ест RAM)

### Проблема 3: Ollama "does not support tools"

**Симптом:** `kmp-agent-ft does not support tools` при вызове через API.

**Причина:** при импорте модели из safetensors (`FROM <папка>`) Ollama не подхватывает chat template. Ставит дефолтный `{{ .Prompt }}`, который не знает про tools.

**Решение:** конвертировать в GGUF (шаг 6) и указать template явно в Modelfile. При `FROM <файл.gguf>` Ollama принимает пользовательский TEMPLATE.

### Проблема 4: venv не активирован

**Симптом:** `ModuleNotFoundError: No module named 'openai'` — хотя пакет ставили.

**Причина:** пакеты стояли в системном Anaconda, а скрипт запущен из другого Python. Или наоборот.

**Решение:** всегда запускать через `.venv/bin/python` или активировать venv: `source .venv/bin/activate`.

### Проблема 5: результаты разных моделей перезаписывают друг друга

**Симптом:** прогнали baseline на gpt-4o-mini, потом на qwen — файлы gpt-4o-mini исчезли.

**Причина:** выходная папка не зависела от имени модели.

**Решение:** добавили `model_slug()` — функцию, которая превращает имя модели в безопасное имя папки (`Qwen/Qwen2.5-7B-Instruct` → `qwen2.5-7b-instruct`). Теперь каждая модель пишет в свою подпапку.

---

## Итоговая структура артефактов

```
data/
├── out/                          ← датасет
│   ├── train.jsonl (47 примеров)
│   └── eval.jsonl  (11 примеров)
├── baseline/                     ← результаты baseline
│   └── eval/
│       ├── gpt-4o-mini/
│       ├── qwen2.5-7b-instruct/
│       └── kmp-agent-ft/         ← post-FT результат
└── mlx/                          ← артефакты обучения
    └── qwen2.5-7b-instruct/
        ├── adapters/             ← LoRA-адаптер (~25 МБ)
        ├── mlx_data/             ← подготовленные данные
        └── fused/                ← полная модель + model.gguf
```

---

## Полный пайплайн одной командой (после того как всё настроено)

```bash
# 1. Подготовить данные и обучить
python -m src.ft_client.mlx.train

# 2. Экспортировать в Ollama
python -m src.ft_client.mlx.export

# 3. Прогнать eval
python -m src.baseline.run_baseline \
  --provider ollama --model kmp-agent-ft \
  --from-jsonl data/out/eval.jsonl
```

В реальности каждый шаг может потребовать подбора параметров и отладки. Этот туториал — как раз про это.
