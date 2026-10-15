"""Tabla de simbolos jerarquica.

Mantiene el arbol de ambitos, el registro de clases (usado como jerarquia de
herencia por el sistema de tipos) y las exportaciones a JSON y texto tabular.
"""

from __future__ import annotations

from typing import Any, Iterator, Optional

from ..types.types import ClassType, Type
from .scope import Scope, ScopeKind
from .symbols import ClassSymbol, FunctionSymbol, Symbol, VariableSymbol


class ClassRegistry:
    """Jerarquia de clases consultable por el sistema de tipos."""

    def __init__(self) -> None:
        self._classes: dict[str, ClassSymbol] = {}

    def add(self, symbol: ClassSymbol) -> None:
        self._classes[symbol.name] = symbol

    def get(self, name: str) -> Optional[ClassSymbol]:
        return self._classes.get(name)

    def __contains__(self, name: object) -> bool:
        return name in self._classes

    def __iter__(self) -> Iterator[ClassSymbol]:
        return iter(self._classes.values())

    def names(self) -> list[str]:
        return list(self._classes)

    def ancestors(self, class_name: str) -> list[str]:
        """Cadena de herencia empezando por ``class_name``.

        Es tolerante a ciclos: se detiene al repetir un nombre, de modo que
        una jerarquia mal formada no cuelga el analizador.
        """
        chain: list[str] = []
        seen: set[str] = set()
        current: Optional[str] = class_name
        while current is not None and current not in seen:
            seen.add(current)
            chain.append(current)
            symbol = self._classes.get(current)
            current = symbol.base_name if symbol is not None else None
        return chain

    def is_subclass(self, subclass: str, superclass: str) -> bool:
        return superclass in self.ancestors(subclass)

    def lookup_field(self, class_name: str, field_name: str) -> Optional[VariableSymbol]:
        """Busca un atributo en la clase y en sus ancestros."""
        for name in self.ancestors(class_name):
            symbol = self._classes.get(name)
            if symbol is not None and field_name in symbol.fields:
                return symbol.fields[field_name]
        return None

    def lookup_method(self, class_name: str, method_name: str) -> Optional[FunctionSymbol]:
        """Busca un metodo en la clase y en sus ancestros."""
        for name in self.ancestors(class_name):
            symbol = self._classes.get(name)
            if symbol is not None and method_name in symbol.methods:
                return symbol.methods[method_name]
        return None

    def lookup_constructor(self, class_name: str) -> Optional[FunctionSymbol]:
        """Busca el constructor mas cercano en la cadena de herencia.

        Si una subclase no declara constructor propio se reutiliza el de la
        clase base, que es el comportamiento que exige ``program.cps``.
        """
        for name in self.ancestors(class_name):
            symbol = self._classes.get(name)
            if symbol is not None and symbol.constructor is not None:
                return symbol.constructor
        return None

    def declaring_class_of_method(self, class_name: str, method_name: str) -> Optional[str]:
        for name in self.ancestors(class_name):
            symbol = self._classes.get(name)
            if symbol is not None and method_name in symbol.methods:
                return name
        return None


class SymbolTable:
    """Arbol de ambitos con una pila de ambito actual."""

    def __init__(self, filename: str = "<memory>") -> None:
        self.filename = filename
        self._next_id = 0
        self.global_scope = self._new_scope("global", ScopeKind.GLOBAL, None)
        self.current: Scope = self.global_scope
        self.classes = ClassRegistry()
        self.all_scopes: list[Scope] = [self.global_scope]

    # --- manejo de ambitos ------------------------------------------------

    def _new_scope(self, name: str, kind: ScopeKind, parent: Optional[Scope]) -> Scope:
        scope = Scope(self._next_id, name, kind, parent)
        self._next_id += 1
        return scope

    def push_scope(self, name: str, kind: ScopeKind) -> Scope:
        scope = self._new_scope(name, kind, self.current)
        self.all_scopes.append(scope)
        self.current = scope
        return scope

    def pop_scope(self) -> Scope:
        if self.current.parent is None:
            raise RuntimeError("No se puede cerrar el ambito global")
        closed = self.current
        self.current = self.current.parent
        return closed

    # --- declaracion y resolucion ----------------------------------------

    def declare(self, symbol: Symbol) -> bool:
        return self.current.declare(symbol)

    def lookup_local(self, name: str) -> Optional[Symbol]:
        return self.current.lookup_local(name)

    def resolve(self, name: str) -> Optional[Symbol]:
        return self.current.resolve(name)

    def resolve_with_scope(self, name: str) -> tuple[Optional[Symbol], Optional[Scope]]:
        return self.current.resolve_with_scope(name)

    def register_class(self, symbol: ClassSymbol) -> None:
        self.classes.add(symbol)

    def class_type(self, name: str) -> Type:
        return ClassType(name)

    # --- exportacion ------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.filename,
            "scopes": self.global_scope.to_dict(),
            "classes": [c.to_dict() for c in self.classes],
            "scopeCount": len(self.all_scopes),
            "symbolCount": sum(len(scope.symbols) for scope in self.all_scopes),
        }

    def rows(self) -> list[dict[str, str]]:
        """Filas planas (una por simbolo) para la salida tabular y el IDE."""
        result: list[dict[str, str]] = []
        for scope in self.all_scopes:
            for symbol in scope.symbols.values():
                extra = ""
                if isinstance(symbol, FunctionSymbol):
                    details = [symbol.signature]
                    if symbol.captures:
                        details.append(f"captura: {', '.join(symbol.captures)}")
                    extra = " | ".join(details)
                elif isinstance(symbol, VariableSymbol):
                    details = ["mutable" if symbol.mutable else "inmutable"]
                    details.append("inicializada" if symbol.initialized else "sin inicializar")
                    if symbol.captured:
                        details.append("capturada")
                    extra = ", ".join(details)
                elif isinstance(symbol, ClassSymbol):
                    extra = f"base: {symbol.base_name}" if symbol.base_name else "sin herencia"
                result.append(
                    {
                        "scope": scope.qualified_name,
                        "scopeKind": scope.kind.value,
                        "name": symbol.name,
                        "category": symbol.category.value,
                        "type": symbol.type.name,
                        "line": str(symbol.span.line) if symbol.span else "-",
                        "column": str(symbol.span.column) if symbol.span else "-",
                        "details": extra,
                    }
                )
        return result

    def to_tree(self) -> str:
        """Tabla de simbolos como arbol de ambitos anidados.

        Es la vista que pide el requisito de "tabla de simbolos visible": deja
        ver de un vistazo la jerarquia Global -> Clase/Funcion -> Bloque y que
        cada parametro vive dentro del ambito de su funcion.
        """
        lines = [_scope_label(self.global_scope)]
        _render_scope(self.global_scope, "", lines)
        return "\n".join(lines)

    def to_text(self) -> str:
        """Tabla de simbolos legible en consola."""
        rows = self.rows()
        headers = {
            "scope": "AMBITO",
            "name": "NOMBRE",
            "category": "CATEGORIA",
            "type": "TIPO",
            "line": "LIN",
            "column": "COL",
            "details": "DETALLES",
        }
        columns = list(headers)
        if not rows:
            return "La tabla de simbolos esta vacia."

        widths = {
            key: max(len(headers[key]), *(len(row[key]) for row in rows)) for key in columns
        }
        separator = "-+-".join("-" * widths[key] for key in columns)
        lines = [
            " | ".join(headers[key].ljust(widths[key]) for key in columns),
            separator,
        ]
        for row in rows:
            lines.append(" | ".join(row[key].ljust(widths[key]) for key in columns))
        return "\n".join(lines)


# --- render del arbol de ambitos -----------------------------------------


def _scope_label(scope: Scope) -> str:
    """Etiqueta de un ambito dentro del arbol."""
    if scope.kind is ScopeKind.GLOBAL:
        return "GLOBAL"
    return f"scope {scope.kind.value}:{scope.name}"


def describe_symbol(symbol: Symbol) -> str:
    """Descripcion de una linea para un simbolo del arbol."""
    if isinstance(symbol, ClassSymbol):
        base = f" (base: {symbol.base_name})" if symbol.base_name else ""
        return f"{symbol.name} : class{base}"
    if isinstance(symbol, FunctionSymbol):
        params = ", ".join(p.type.name for p in symbol.parameters)
        return f"{symbol.name} : {symbol.category.value}({params}) -> {symbol.return_type.name}"
    if isinstance(symbol, VariableSymbol):
        suffix = "" if symbol.mutable else " (inmutable)"
        return f"{symbol.name} : {symbol.category.value} {symbol.type.name}{suffix}"
    return f"{symbol.name} : {symbol.type.name}"


def _render_scope(scope: Scope, prefix: str, lines: list[str]) -> None:
    """Anexa a ``lines`` los simbolos y subambitos de ``scope``."""
    entries: list[tuple[str, Any]] = [("symbol", s) for s in scope.symbols.values()]
    entries.extend(("scope", child) for child in scope.children)

    for index, (kind, item) in enumerate(entries):
        last = index == len(entries) - 1
        connector = "└── " if last else "├── "
        child_prefix = prefix + ("    " if last else "│   ")
        if kind == "symbol":
            lines.append(f"{prefix}{connector}{describe_symbol(item)}")
        else:
            lines.append(f"{prefix}{connector}{_scope_label(item)}")
            _render_scope(item, child_prefix, lines)
