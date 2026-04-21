# Criteria — "Стало лучше" для Дня 6

Что мы считаем успехом fine-tune поверх `gpt-4o-mini`. Все метрики прогоняются автоматически на `eval.jsonl` (10 примеров). Baseline зафиксирован в `baseline/outputs/summary.md`.

---

## Режимы eval и что проверяем в каждом

| Режим | Доля в eval | Что должна делать модель | Что НЕ делать |
|---|---|---|---|
| `agent` | ~7/10 | План → step_read → action → SELF-CHECK → update | Пропускать `step_read`, держать план в памяти |
| `agent_question` | ~2/10 | В `content` блок `QUESTION:` с уточнениями | Писать план на глазок / предлагать "можно сделать так" |
| `plain` | ~1/10 | Свободная проза, ответ по существу | Звать `plan_write` на разъяснительный вопрос |

---

## 5 авто-метрик

Метрики вычисляются одной командой:
```
python -m validator.validate --in baseline/outputs/<model>.jsonl
```
(сводный отчёт — в `baseline/outputs/<model>_metrics.json`).

| # | Метрика | Что считаем | Baseline (gpt-4o-mini) | Цель FT |
|---|---|---|---|---|
| 1 | **Structural compliance** | валидный JSON + есть `messages` + каждый tool_call имеет валидный `arguments`-JSON | ≥80% | ≥95% |
| 2 | **Tool name validity** | все tool names ∈ {plan_write, step_read, step_update_result, task_status, plan_revise, read_file, list_dir, search_and_replace, write_file} | 100% (на baseline) | 100% |
| 3 | **Task_id consistency** (agent only) | `task_id` присутствует во всех state-tool call (plan_write / step_read / step_update_result / task_status / plan_revise) | 100% | 100% |
| 4 | **Read-before-action** (agent only) | перед каждым вызовом project-tool в текущем шаге был `step_read` этого шага | **<40%** (модель "помнит" план, а не читает) | **≥90%** |
| 5 | **THOUGHT + SELF-CHECK в content** | в каждом assistant с tool_calls есть обе метки в `content` | **0/8 на baseline** — тотальный провал | **≥90%** |

Бонус (не обязательно для сдачи Дня 6):
- **Replan discipline**: после `matches=0` / `ok=false` — сначала `step_update_result(status=NEEDS_REPLAN)`, потом `plan_revise`, **не** повтор того же tool call. Измеряется на подмножестве eval с подсовом ошибки. Baseline: ~20% (модель повторяет). Цель: ≥80%.

---

## 2 LLM-judge метрики (Claude-4-sonnet как судья)

Вычисляются `python -m baseline.judge --in <eval-run>.jsonl --model claude-sonnet-4-6`.
Судья видит пару (user_request → assistant_response) и ставит 1-5.

| # | Метрика | Как оцениваем | Baseline | Цель FT |
|---|---|---|---|---|
| 6 | **Plan quality** (agent only) | на вход судье: `plan_write.arguments`. Рубрика 1-5: шагов 2-5, каждый с checklist ≥2 и success_criteria, не дублируются, не "read_file then read_file". | 2-3 | **4+** на медиане |
| 7 | **Mode switch correctness** | судья смотрит system_prompt + user → решает, какой режим правильный (agent / agent_question / plain), и сверяет с actual. | не измерено (см. ниже) | **≥90%** корректных переключений |

> Baseline-наблюдение: на `golden_03_question_branch` baseline вызвал `plan_write` вместо `QUESTION:` → mode-switch-fail. На `plain_01_expect_actual_vs_interface` baseline корректно не вызвал tool. Т.е. baseline fails mode-switch на недоопределённых запросах — именно этому FT должен учить.

---

## Анти-катастрофическое-забывание

Параллельно с eval.jsonl прогоняем `eval_plain.jsonl` (5 концептуальных вопросов про KMP, system = `system_plain.md`). Требование: **LLM-judge plain-ответа у FT-модели не хуже baseline на более чем 10%**. Если деградирует — увеличиваем долю plain в датасете и переобучаем.

Файл `eval_plain.jsonl` подготавливаем в Дне 6 (5 строк), прогоняем после FT в Дне 7+.

---

## Сдача Дня 6 — что считается "готово"

- [x] `baseline/outputs/summary.md` — 5 авто-метрик посчитаны на baseline (без FT).
- [x] Числовые цели прописаны (см. таблицы выше).
- [ ] `train.jsonl` (40) + `eval.jsonl` (10) собраны и валидны.
- [ ] `eval_plain.jsonl` (5) подготовлен.
- [ ] `ft_client/` — скрипты загрузки + создания job с `--confirm` guard (не запущены).
- [ ] LLM-judge скрипт готов (может быть заглушкой на День 6, полноценный прогон после FT).

---

## Что сознательно не меряем

- **Точную адекватность ответа задаче** — для этого нужно писать интеграционный runner с реальными tool-implementations. Отложено на День 7+.
- **Latency / стоимость** — FT-модель `gpt-4o-mini` в OpenAI по определению дешевле/быстрее `gpt-4o`. Это не цель Дня 6.
- **Subjective readability** — THOUGHT/SELF-CHECK проверяем по факту наличия, не по стилю. Стиль подтянется из seeds.
