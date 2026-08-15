"""Small, side-effect-free policy for rich chat outputs.

This module deliberately does not load a model, touch the FIFO, or trust model
generated HTML.  The portal can use the decision to call its existing,
capability-gated graphics queue and can attach only validated chart data to a
normal chat response.
"""

# SPDX-FileCopyrightText: 2026 R740 AI Factory contributors
# SPDX-License-Identifier: LGPL-3.0-or-later
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any


MAX_CHART_JSON_BYTES = 16 * 1024
MAX_CHART_POINTS = 50
MAX_CHART_SERIES = 6

_IMAGE_ACTION = re.compile(
    r"\b(?:crea|genera|disegna|produci|fammi|realizza|renderizza)\b", re.IGNORECASE
)
_IMAGE_OBJECT = re.compile(
    r"\b(?:immagine|foto|fotografia|illustrazione|grafica|poster|logo|avatar|copertina)\b",
    re.IGNORECASE,
)
_VISION_ONLY = re.compile(
    r"\b(?:analizza|descrivi|leggi|riconosci|trascrivi|cosa (?:c['’]e|vedi)|che cosa vedi)\b",
    re.IGNORECASE,
)
_TABLE_REQUEST = re.compile(r"\b(?:tabella|tabellare|colonne e righe)\b", re.IGNORECASE)
_CHART_REQUEST = re.compile(
    r"\b(?:grafico|diagramma|istogramma|chart|andamento|serie temporale)\b", re.IGNORECASE
)
_CHART_FENCE = re.compile(r"```chart-json\s*(\{.*?\})\s*```", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class DispatchDecision:
    kind: str
    reason: str
    response_contract: str | None = None


def decide_prompt_dispatch(prompt: str, *, can_generate_images: bool) -> DispatchDecision:
    """Choose only explicit output modes; ambiguous prompts remain normal chat."""
    text = " ".join(str(prompt).split())[:8000]
    explicit_image = bool(_IMAGE_ACTION.search(text) and _IMAGE_OBJECT.search(text))
    if explicit_image and not _VISION_ONLY.search(text):
        if can_generate_images:
            return DispatchDecision(
                "image_generation",
                "richiesta esplicita di generazione immagine",
            )
        return DispatchDecision(
            "chat",
            "generazione immagine non autorizzata per questo account",
        )
    if _CHART_REQUEST.search(text):
        return DispatchDecision(
            "chat",
            "richiesta di grafico",
            "chart-json-v1",
        )
    if _TABLE_REQUEST.search(text):
        return DispatchDecision(
            "chat",
            "richiesta di tabella",
            "safe-markdown-table-v1",
        )
    return DispatchDecision("chat", "richiesta generale o ambigua")


def chart_system_instruction() -> str:
    return (
        "Se un grafico e utile, fornisci prima una breve spiegazione e poi un solo blocco "
        "```chart-json``` con JSON: {version:1,type:'bar'|'line',title:string," 
        "labels:[string],series:[{name:string,values:[number]}]}. "
        "Non produrre HTML, JavaScript, URL, CSS o opzioni di rendering."
    )


def chart_retry_instruction() -> str:
    """A short, closed retry contract for one server-side repair attempt."""
    return (
        "CORREZIONE GRAFICO: rispondi esclusivamente con un singolo blocco "
        "```chart-json``` contenente JSON RFC 8259 valido. Schema esatto: "
        '{"version":1,"type":"bar|line","title":"testo",'
        '"labels":["testo"],"series":[{"name":"testo","values":[numero]}]}. '
        "Usa doppi apici, nessun commento, HTML, JavaScript, URL, CSS o campo aggiuntivo."
    )


def safe_chart_failure_text() -> str:
    """Return a fixed message; never reflect malformed model output."""
    return "Non e stato possibile costruire un grafico valido dai dati richiesti."


def table_system_instruction() -> str:
    return (
        "Se una tabella e utile, usa una sola tabella Markdown semplice con intestazione e "
        "separatore. Non produrre HTML, stili, URL data:, iframe o codice eseguibile."
    )


def _short_text(value: Any, field: str, limit: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} deve essere testo")
    value = " ".join(value.split())
    if not value or len(value) > limit:
        raise ValueError(f"{field} non valido")
    return value


def validate_chart_spec(value: Any) -> dict[str, Any]:
    """Return a canonical data-only chart spec or fail closed."""
    if not isinstance(value, dict) or set(value) - {"version", "type", "title", "labels", "series"}:
        raise ValueError("schema grafico non valido")
    if value.get("version") != 1 or value.get("type") not in {"bar", "line"}:
        raise ValueError("versione o tipo grafico non supportato")
    labels = value.get("labels")
    series = value.get("series")
    if not isinstance(labels, list) or not 1 <= len(labels) <= MAX_CHART_POINTS:
        raise ValueError("numero etichette non valido")
    if not isinstance(series, list) or not 1 <= len(series) <= MAX_CHART_SERIES:
        raise ValueError("numero serie non valido")
    safe_labels = [_short_text(item, "etichetta", 80) for item in labels]
    safe_series: list[dict[str, Any]] = []
    for item in series:
        if not isinstance(item, dict) or set(item) != {"name", "values"}:
            raise ValueError("serie non valida")
        values = item["values"]
        if not isinstance(values, list) or len(values) != len(safe_labels):
            raise ValueError("lunghezza serie non valida")
        safe_values: list[float] = []
        for number in values:
            if isinstance(number, bool) or not isinstance(number, (int, float)):
                raise ValueError("valore grafico non numerico")
            number = float(number)
            if not math.isfinite(number) or abs(number) > 1e12:
                raise ValueError("valore grafico fuori limite")
            safe_values.append(number)
        safe_series.append({"name": _short_text(item["name"], "nome serie", 80), "values": safe_values})
    return {
        "version": 1,
        "type": value["type"],
        "title": _short_text(value.get("title", "Grafico"), "titolo", 120),
        "labels": safe_labels,
        "series": safe_series,
    }


def extract_chart_artifact(answer: str) -> tuple[str, dict[str, Any] | None, str | None]:
    """Extract at most one strict chart fence; never evaluate model output."""
    text = str(answer)
    matches = list(_CHART_FENCE.finditer(text))
    if not matches:
        return text, None, None
    if len(matches) != 1:
        return text, None, "sono ammessi un solo grafico per risposta"
    raw = matches[0].group(1)
    if len(raw.encode("utf-8")) > MAX_CHART_JSON_BYTES:
        return text, None, "specifica grafico troppo grande"
    try:
        spec = validate_chart_spec(json.loads(raw))
    except (json.JSONDecodeError, ValueError) as exc:
        return text, None, str(exc)
    visible = (text[: matches[0].start()] + text[matches[0].end() :]).strip()
    return visible or "Grafico generato dai dati richiesti.", spec, None


def choose_vision_model(*, selection: str, allowed_models: set[str]) -> str:
    """Auto may select the qualified visual model; manual mode stays explicit."""
    if selection == "auto":
        if "qwen3-vl-8b" not in allowed_models:
            raise ValueError("modello visivo non disponibile o non autorizzato")
        return "qwen3-vl-8b"
    if selection != "qwen3-vl-8b" or selection not in allowed_models:
        raise ValueError("la visione diretta richiede Qwen3-VL oppure Auto")
    return selection
