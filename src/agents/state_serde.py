"""The checkpoint serializer's allow-list (found 2026-10-05 in Cloud Run logs).

LangGraph warns on every resume: "Deserializing unregistered type ... This
will be blocked in a future version." Once blocked, every saved margin-call
run -- paused at the approval gate or the SLA timer -- would fail to load.
So the serializer is given an explicit allow-list, derived from
MarginCallState itself: every Pydantic model and enum reachable from its
fields. A new state field is covered automatically; a unit test checks a
full state round-trips with strict deserialization.
"""

import enum
import types
import typing
from typing import Any

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from pydantic import BaseModel


def reachable_types(root: type) -> set[type]:
    """Pydantic models and enums reachable from `root`'s field annotations."""
    found: set[type] = set()
    stack: list[Any] = [root]
    while stack:
        item = stack.pop()
        for candidate in _expand(item):
            if candidate in found:
                continue
            if isinstance(candidate, type) and issubclass(candidate, BaseModel):
                found.add(candidate)
                stack.extend(field.annotation for field in candidate.model_fields.values())
            elif isinstance(candidate, type) and issubclass(candidate, enum.Enum):
                found.add(candidate)
    return found


def _expand(annotation: Any) -> list[Any]:
    """The concrete classes inside an annotation (unions, list[X], X | None...)."""
    if annotation is None:
        return []
    origin = typing.get_origin(annotation)
    if origin is None:
        return [annotation]
    if origin is typing.Annotated:
        return _expand(typing.get_args(annotation)[0])
    nested: list[Any] = []
    for arg in typing.get_args(annotation):
        nested.extend(_expand(arg))
    if origin not in (typing.Union, types.UnionType) and isinstance(origin, type):
        nested.append(origin)
    return nested


def allowed_modules(root: type) -> list[tuple[str, str]]:
    return sorted((cls.__module__, cls.__qualname__) for cls in reachable_types(root))


def checkpoint_serializer(root: type) -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=allowed_modules(root))
