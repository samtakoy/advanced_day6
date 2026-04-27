"""Tools для SkyHelper: Pydantic-схемы args, реализация и dispatcher.

Slice 2: только search_flights. Остальные тулы добавляются в следующих
slice'ах одинаковым паттерном (схема + функция + регистрация в TOOLS).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, Field, ValidationError

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "travel"
FLIGHTS_PATH = DATA_DIR / "flights.json"

_flights_cache: list[dict] | None = None


def _load_flights() -> list[dict]:
    global _flights_cache
    if _flights_cache is None:
        _flights_cache = json.loads(FLIGHTS_PATH.read_text(encoding="utf-8"))
    return _flights_cache


# ---------------------------------------------------------------------------
# search_flights
# ---------------------------------------------------------------------------

class SearchFlightsArgs(BaseModel):
    from_city: str | None = Field(
        default=None,
        description="Город вылета на русском. Например: Москва.",
    )
    to_city: str | None = Field(
        default=None,
        description="Город прилёта на русском. Например: Денпасар, Пхукет, Дубай, Анталия, Пунта-Кана, Сочи, Тбилиси, Стамбул.",
    )
    date: str | None = Field(
        default=None,
        description="Дата вылета. Поддерживаются префиксы: '2026-10' (любая дата октября), '2026-10-12' (точная дата).",
    )
    flight_class: Literal["economy", "business"] | None = Field(
        default=None,
        description="Класс обслуживания.",
    )


def search_flights(args: SearchFlightsArgs) -> dict:
    """Поиск one-way рейсов в каталоге по маршруту, дате, классу. Возвращает топ-10 совпадений, отсортированных по дате и цене."""
    results = _load_flights()
    if args.from_city:
        needle = args.from_city.lower()
        results = [f for f in results if needle in f["from_city"].lower()]
    if args.to_city:
        needle = args.to_city.lower()
        results = [f for f in results if needle in f["to_city"].lower()]
    if args.date:
        results = [f for f in results if f["date"].startswith(args.date)]
    if args.flight_class:
        results = [f for f in results if f["class"] == args.flight_class]
    results = sorted(results, key=lambda f: (f["date"], f["price_rub"]))[:10]
    return {"count": len(results), "flights": results}


# ---------------------------------------------------------------------------
# Tool registry + dispatcher
# ---------------------------------------------------------------------------

# name -> (args_model, callable, description)
TOOLS: dict[str, tuple[type[BaseModel], Callable, str]] = {
    "search_flights": (
        SearchFlightsArgs,
        search_flights,
        "Поиск one-way рейсов в каталоге по маршруту, дате и классу. Возвращает топ-10 вариантов.",
    ),
}


def build_tool_schemas() -> list[dict]:
    """Собрать список tool-объявлений в формате OpenAI tools API."""
    schemas = []
    for name, (args_model, _fn, description) in TOOLS.items():
        schemas.append({
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": args_model.model_json_schema(),
            },
        })
    return schemas


def dispatch(name: str, arguments_json: str) -> str:
    """Вызвать тул по имени с JSON-args. Возвращает JSON-строку результата."""
    if name not in TOOLS:
        return json.dumps({"error": f"Unknown tool: {name}"}, ensure_ascii=False)
    args_model, fn, _description = TOOLS[name]
    try:
        args = args_model.model_validate_json(arguments_json)
    except ValidationError as e:
        return json.dumps(
            {"error": "Invalid arguments", "details": e.errors()},
            ensure_ascii=False,
        )
    result = fn(args)
    return json.dumps(result, ensure_ascii=False)
