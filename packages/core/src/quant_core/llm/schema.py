"""Convert a Pydantic model into a JSON schema accepted by structured-output APIs.

Structured outputs require `additionalProperties: false` on every object and do not support
numeric/string/array bound constraints. Those bounds are removed from the schema and moved
into the field description as a hint; Pydantic still enforces them when validating the reply.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

_UNSUPPORTED = (
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minLength",
    "maxLength",
    "pattern",
    "minItems",
    "maxItems",
    "uniqueItems",
)
_SUPPORTED_FORMATS = frozenset(
    {"date-time", "time", "date", "duration", "email", "hostname", "uri", "ipv4", "ipv6", "uuid"}
)


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    schema = model.model_json_schema()
    _strip(schema)
    return schema


def schema_instruction(schema: dict[str, Any]) -> str:
    """Prompt text for providers that cannot enforce a schema themselves."""
    return (
        "Reply with a single JSON object and no other text. "
        "The JSON must conform to this JSON schema:\n"
        + json.dumps(schema, ensure_ascii=False, sort_keys=True)
    )


def _strip(node: Any) -> None:
    if isinstance(node, list):
        for item in node:
            _strip(item)
        return
    if not isinstance(node, dict):
        return

    hints = [f"{key}={node.pop(key)}" for key in _UNSUPPORTED if key in node]
    if "format" in node and node["format"] not in _SUPPORTED_FORMATS:
        hints.append(f"format={node.pop('format')}")
    if hints:
        desc = node.get("description", "")
        node["description"] = f"{desc} ({', '.join(hints)})".strip()

    if node.get("type") == "object" or "properties" in node:
        node["additionalProperties"] = False

    for value in node.values():
        _strip(value)
