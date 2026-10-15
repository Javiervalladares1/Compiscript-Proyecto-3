"""Puente hacia los archivos generados por ANTLR.

Los archivos ``CompiscriptLexer.py``, ``CompiscriptParser.py`` y
``CompiscriptVisitor.py`` se generan dentro de ``program/`` para preservar el
flujo de trabajo tradicional del curso::

    cd program && antlr -Dlanguage=Python3 -visitor Compiscript.g4

Ese directorio no es un paquete de Python, asi que este modulo lo agrega a
``sys.path`` una unica vez y reexporta las clases generadas. Es el unico punto
del compilador que sabe donde viven esos archivos.
"""

from __future__ import annotations

import sys
from pathlib import Path

#: Directorio donde ANTLR deja el lexer, el parser y el visitor.
PROGRAM_DIR: Path = Path(__file__).resolve().parents[2] / "program"

_GENERATED_FILES = (
    "CompiscriptLexer.py",
    "CompiscriptParser.py",
    "CompiscriptVisitor.py",
)


class ParserNotGeneratedError(RuntimeError):
    """El lexer/parser de ANTLR todavia no ha sido generado."""


def _ensure_generated() -> None:
    missing = [name for name in _GENERATED_FILES if not (PROGRAM_DIR / name).is_file()]
    if missing:
        raise ParserNotGeneratedError(
            "Faltan archivos generados por ANTLR en "
            f"{PROGRAM_DIR}: {', '.join(missing)}.\n"
            "Ejecute ./scripts/generate_parser.sh desde la raiz del repositorio."
        )


_ensure_generated()

if str(PROGRAM_DIR) not in sys.path:
    sys.path.insert(0, str(PROGRAM_DIR))

from CompiscriptLexer import CompiscriptLexer  # noqa: E402
from CompiscriptParser import CompiscriptParser  # noqa: E402
from CompiscriptVisitor import CompiscriptVisitor  # noqa: E402

__all__ = [
    "CompiscriptLexer",
    "CompiscriptParser",
    "CompiscriptVisitor",
    "ParserNotGeneratedError",
    "PROGRAM_DIR",
]
