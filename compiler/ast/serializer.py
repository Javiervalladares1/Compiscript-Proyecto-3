"""Serializacion del AST a estructuras JSON.

El IDE consume esta representacion para dibujar el arbol y las pruebas la usan
para verificar la forma del AST sin depender del formato DOT.
"""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from typing import Any

from . import nodes as N

#: Campos que se serializan aparte o que no aportan al arbol.
_SKIPPED_FIELDS = {"span", "resolved_symbol"}


def node_to_dict(node: N.Node) -> dict[str, Any]:
    """Convierte un nodo (y sus descendientes) en un diccionario JSON-serializable."""
    result: dict[str, Any] = {
        "kind": node.kind,
        "label": node.label(),
        "span": node.span.to_dict(),
    }

    attributes: dict[str, Any] = {}
    if is_dataclass(node):
        for field_info in fields(node):
            if field_info.name in _SKIPPED_FIELDS:
                continue
            value = getattr(node, field_info.name)
            if isinstance(value, N.Node) or _is_node_list(value):
                continue
            encoded = _encode_scalar(value)
            if encoded is not None:
                attributes[field_info.name] = encoded
    if attributes:
        result["attributes"] = attributes

    children = [node_to_dict(child) for child in node.children()]
    if children:
        result["children"] = children
    return result


def _is_node_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, N.Node) for item in value) and value


def _encode_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, N.SourceSpan):
        return value.to_dict()
    if isinstance(value, list):
        return [_encode_scalar(item) for item in value] or None
    # Tipos del sistema de tipos y cualquier otro objeto: su nombre legible.
    name = getattr(value, "name", None)
    return name if isinstance(name, str) else str(value)


def ast_to_dict(program: N.Program) -> dict[str, Any]:
    return node_to_dict(program)


def ast_to_json(program: N.Program, indent: int = 2) -> str:
    return json.dumps(ast_to_dict(program), indent=indent, ensure_ascii=False)


def ast_to_text(node: N.Node, indent: int = 0) -> str:
    """Vuelca el AST como arbol indentado (util en consola)."""
    lines = [f"{'  ' * indent}{node.label()}  ({node.span.line}:{node.span.column})"]
    for child in node.children():
        lines.append(ast_to_text(child, indent + 1))
    return "\n".join(lines)
