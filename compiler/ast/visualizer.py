"""Representacion visual del AST en formato Graphviz DOT.

La generacion del archivo ``.dot`` no depende de que Graphviz este instalado.
El renderizado a PNG/SVG es opcional y solo se intenta si existe el ejecutable
``dot`` en el PATH.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional

from ..types.types import Type
from . import nodes as N

#: Colores por familia de nodo, para que el grafo sea legible de un vistazo.
_FILL_COLORS: dict[str, str] = {
    "Program": "#1f77b4",
    "Block": "#aec7e8",
    "VarDecl": "#2ca02c",
    "FunctionDecl": "#ff7f0e",
    "ClassDecl": "#d62728",
    "Parameter": "#ffbb78",
    "TypeRef": "#c7c7c7",
}

_STATEMENT_COLOR = "#98df8a"
_EXPRESSION_COLOR = "#dbdb8d"
_DEFAULT_COLOR = "#ffffff"


def _escape(text: str) -> str:
    """Escapa un texto para usarlo dentro de una etiqueta DOT entre comillas."""
    return (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "")
        .replace("{", "\\{")
        .replace("}", "\\}")
        .replace("<", "\\<")
        .replace(">", "\\>")
        .replace("|", "\\|")
    )


def _fill_color(node: N.Node) -> str:
    if node.kind in _FILL_COLORS:
        return _FILL_COLORS[node.kind]
    if isinstance(node, N.Expression):
        return _EXPRESSION_COLOR
    if isinstance(node, N.Statement):
        return _STATEMENT_COLOR
    return _DEFAULT_COLOR


def _node_label(node: N.Node) -> str:
    parts = [node.label(), f"linea {node.span.line}, col {node.span.column}"]
    resolved: Optional[Type] = getattr(node, "resolved_type", None)
    if isinstance(resolved, Type):
        parts.append(f"tipo: {resolved.name}")
    return _escape("\n".join(parts))


def to_dot(program: N.Program, graph_name: str = "AST") -> str:
    """Genera el texto del grafo en formato DOT."""
    lines: list[str] = [
        f'digraph "{_escape(graph_name)}" {{',
        "  graph [rankdir=TB, fontname=\"Helvetica\", bgcolor=\"white\"];",
        '  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=10];',
        '  edge [color="#555555"];',
    ]

    counter = 0

    def emit(node: N.Node, parent_id: Optional[str]) -> None:
        nonlocal counter
        node_id = f"n{counter}"
        counter += 1
        lines.append(
            f'  {node_id} [label="{_node_label(node)}", fillcolor="{_fill_color(node)}"];'
        )
        if parent_id is not None:
            lines.append(f"  {parent_id} -> {node_id};")
        for child in node.children():
            emit(child, node_id)

    emit(program, None)
    lines.append("}")
    return "\n".join(lines) + "\n"


def write_dot(program: N.Program, path: str | Path, graph_name: str = "AST") -> Path:
    """Escribe el archivo ``.dot`` y devuelve su ruta."""
    target = Path(path)
    if target.parent and not target.parent.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(to_dot(program, graph_name), encoding="utf-8")
    return target


def graphviz_available() -> bool:
    return shutil.which("dot") is not None


def render_image(dot_path: str | Path, image_path: str | Path) -> Optional[Path]:
    """Renderiza el DOT a PNG/SVG si Graphviz esta disponible.

    Devuelve ``None`` cuando no hay ejecutable ``dot``; la ausencia de
    Graphviz nunca debe impedir la compilacion.
    """
    if not graphviz_available():
        return None

    source = Path(dot_path)
    target = Path(image_path)
    output_format = target.suffix.lstrip(".").lower() or "png"
    if target.parent and not target.parent.exists():
        target.parent.mkdir(parents=True, exist_ok=True)

    completed = subprocess.run(
        ["dot", f"-T{output_format}", str(source), "-o", str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    return target
