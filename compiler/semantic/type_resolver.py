"""Resolucion de anotaciones sintacticas de tipo a objetos ``Type``."""

from __future__ import annotations

from typing import Optional

from ..ast import nodes as N
from ..symbols.table import SymbolTable
from ..types.types import BUILTIN_TYPE_NAMES, ERROR, ClassType, Type, array_of
from .diagnostics import Code, DiagnosticBag


class TypeResolver:
    """Traduce un :class:`~compiler.ast.nodes.TypeRef` a un tipo del sistema.

    Requiere que los nombres de clase ya esten registrados (pasada 1 de
    :class:`~compiler.semantic.declarations.DeclarationCollector`).
    """

    def __init__(self, table: SymbolTable, diagnostics: DiagnosticBag) -> None:
        self._table = table
        self._diagnostics = diagnostics

    def resolve(self, type_ref: Optional[N.TypeRef]) -> Type:
        if type_ref is None:
            return ERROR

        base = self.resolve_name(type_ref.name, type_ref)
        resolved = array_of(base, type_ref.dimensions) if type_ref.dimensions else base
        type_ref.resolved_type = resolved
        return resolved

    def resolve_name(self, name: str, type_ref: Optional[N.TypeRef] = None) -> Type:
        builtin = BUILTIN_TYPE_NAMES.get(name)
        if builtin is not None:
            return builtin
        if self._table.classes.get(name) is not None:
            return ClassType(name)
        self._diagnostics.report(
            Code.UNKNOWN_TYPE_NAME,
            f"Tipo desconocido: '{name}'.",
            type_ref.span if type_ref is not None else None,
        )
        return ERROR
