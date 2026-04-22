"""Общие утилиты проекта."""

import re


def model_slug(model_name: str) -> str:
    """Превращает имя модели в безопасный slug для имён файлов и папок.

    Примеры:
        Qwen/Qwen2.5-7B-Instruct  → qwen2.5-7b-instruct
        gpt-4o-mini                → gpt-4o-mini
        gpt-4o-mini-2024-07-18     → gpt-4o-mini-2024-07-18
        openai/gpt-4o-mini         → gpt-4o-mini
        qwen2.5:14b-instruct       → qwen2.5-14b-instruct
    """
    # Берём часть после последнего '/' (убираем vendor prefix)
    name = model_name.rsplit("/", 1)[-1]
    # Заменяем двоеточия и пробелы на дефисы (Ollama формат qwen2.5:7b → qwen2.5-7b)
    name = re.sub(r"[:\s]+", "-", name)
    return name.lower()
