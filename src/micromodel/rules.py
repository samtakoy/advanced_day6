"""Уровень 1 — Программное извлечение модулей.

Ищет в тексте задачи упоминания 16 известных модулей по regex-паттернам.
Без вызовов LLM. Возвращает список найденных алиасов модулей.
"""

from __future__ import annotations

import re

# Паттерны для каждого модуля: алиас → список regex.
# Если хотя бы один паттерн совпал — модуль считается упомянутым.
MODULE_PATTERNS: dict[str, list[str]] = {
    "db": [
        r"\bcore[/:]db\b", r"\bcore:db\b",
        r"\b\.sq\b", r"\bWorkspace\.sq\b", r"\bChartSlot\.sq\b",
        r"\bStocksDatabase\b",
    ],
    "net": [
        r"\bcore[/:]network\b", r"\bcore:network\b",
        r"\bWebSocket\b",
    ],
    "uikit": [
        r"\bcore[/:]uikit\b", r"\bcore:uikit\b",
        r"\buikit\b",
        r"\bLineChart\b", r"\bHistogramChart\b", r"\bScatterChart\b",
        r"\bChartMarkerLayer\b",
    ],
    "utils": [
        r"\bcore[/:]utils\b", r"\bcore:utils\b",
        r"\bDispatcherProvider\b", r"\bTrayService\b",
    ],
    "theme": [
        r"\bcore[/:]theme\b", r"\bcore:theme\b",
    ],
    "resources": [
        r"\bcore[/:]resources\b", r"\bcore:resources\b",
        r"\bCHANGELOG\.md\b",
    ],
    "mainentry": [
        r"\bmainentry\b", r"\bAppKoinInitializer\b",
    ],
    "m-main": [
        r"\bfeatures[/:]main\b", r"\bfeatures:main\b",
        r"\bMainTab\b", r"\bкарусел",
    ],
    "m-data": [
        r"\bfeatures[/:]data\b", r"\bfeatures:data\b",
        r"\bDataTab\b", r"\bQuoteDetailScreen\b", r"\bTickerDetailScreen\b",
    ],
    "m-settings": [
        r"\bfeatures[/:]settings\b", r"\bfeatures:settings\b",
        r"\bsettings экран", r"\bв settings\b",
    ],
    "m-analysis": [
        r"\bfeatures[/:]analysis\b", r"\bfeatures:analysis\b",
        r"\bAnalysisTab\b",
    ],
    "fa-pickers": [
        r"\bfeatures-api[/:]pickers\b", r"\bfeatures-api:pickers\b",
        r"\bTickerPickerEntryPoint\b",
    ],
    "cf-stocks": [
        r"\bcore-features[/:]stocks\b", r"\bcore-features:stocks\b",
        r"\bcf-stocks\b",
        r"\bCandleRepository\b", r"\bSourceRepository\b",
        r"\bCsvParser\b", r"\bDownloadTask\b",
    ],
    "cf-workspaces": [
        r"\bcore-features[/:]workspaces\b", r"\bcore-features:workspaces\b",
        r"\bcf-workspaces\b",
        r"\bWorkspaceEditor\b", r"\bWorkspaceTag\b",
    ],
    "cf-indicators": [
        r"\bcore-features[/:]indicators\b", r"\bcore-features:indicators\b",
        r"\bcf-indicators\b",
        r"\bIndicatorCatalog\b", r"\bIndicatorCalculator\b",
        r"\bIndicatorCache\b", r"\bDivergenceIndicator\b",
    ],
    "cf-experiments": [
        r"\bcore-features[/:]experiments\b", r"\bcore-features:experiments\b",
        r"\bcf-experiments\b",
        r"\bExperimentRunner\b", r"\bBacktestExecutor\b",
        r"\bSegmentMetricsExecutor\b",
    ],
}


def extract_modules(user_text: str) -> list[str]:
    """Извлечь алиасы модулей из текста задачи по regex-паттернам."""
    found: list[str] = []
    for alias, patterns in MODULE_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, user_text, re.IGNORECASE):
                found.append(alias)
                break  # достаточно одного совпадения на модуль
    return found
