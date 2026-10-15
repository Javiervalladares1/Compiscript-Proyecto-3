"""Ambitos anidados de la tabla de simbolos."""

from __future__ import annotations

from enum import Enum
from typing import Any, Iterator, Optional

from .symbols import Symbol


class ScopeKind(Enum):
    GLOBAL = "global"
    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"
    BLOCK = "block"
    LOOP = "loop"
    CATCH = "catch"
    SWITCH = "switch"

    def __str__(self) -> str:
        return self.value


#: Ambitos que introducen un nuevo marco de activacion (funcion o metodo).
FUNCTION_LIKE_SCOPES = (ScopeKind.FUNCTION, ScopeKind.METHOD)

#: Ambitos que habilitan `continue`.
LOOP_SCOPES = (ScopeKind.LOOP,)

#: Ambitos que habilitan `break`. Compiscript admite `break` dentro de `switch`
#: como extension documentada (ver docs/semantic-decisions.md).
BREAKABLE_SCOPES = (ScopeKind.LOOP, ScopeKind.SWITCH)


class Scope:
    """Un entorno de nombres con referencia a su padre y a sus hijos."""

    def __init__(
        self,
        scope_id: int,
        name: str,
        kind: ScopeKind,
        parent: Optional["Scope"] = None,
    ) -> None:
        self.id = scope_id
        self.name = name
        self.kind = kind
        self.parent = parent
        self.children: list["Scope"] = []
        self.symbols: dict[str, Symbol] = {}
        if parent is not None:
            parent.children.append(self)

    # --- declaracion y busqueda ------------------------------------------

    def declare(self, symbol: Symbol) -> bool:
        """Declara ``symbol`` localmente.

        Devuelve ``False`` si el nombre ya existe en este mismo ambito (el
        sombreado entre ambitos distintos si esta permitido).
        """
        if symbol.name in self.symbols:
            return False
        symbol.scope = self
        self.symbols[symbol.name] = symbol
        return True

    def replace(self, symbol: Symbol) -> None:
        """Declara o sustituye un simbolo local sin comprobar duplicados."""
        symbol.scope = self
        self.symbols[symbol.name] = symbol

    def lookup_local(self, name: str) -> Optional[Symbol]:
        return self.symbols.get(name)

    def resolve(self, name: str) -> Optional[Symbol]:
        """Busca ``name`` desde este ambito hacia los ambitos superiores."""
        current: Optional[Scope] = self
        while current is not None:
            found = current.symbols.get(name)
            if found is not None:
                return found
            current = current.parent
        return None

    def resolve_with_scope(self, name: str) -> tuple[Optional[Symbol], Optional["Scope"]]:
        """Como :meth:`resolve` pero indica tambien en que ambito se encontro."""
        current: Optional[Scope] = self
        while current is not None:
            found = current.symbols.get(name)
            if found is not None:
                return found, current
            current = current.parent
        return None, None

    # --- navegacion -------------------------------------------------------

    def ancestors(self) -> Iterator["Scope"]:
        current: Optional[Scope] = self
        while current is not None:
            yield current
            current = current.parent

    def enclosing_function_scope(self) -> Optional["Scope"]:
        """Ambito de funcion/metodo mas cercano, o ``None`` en el ambito global."""
        for scope in self.ancestors():
            if scope.kind in FUNCTION_LIKE_SCOPES:
                return scope
        return None

    def enclosing_class_scope(self) -> Optional["Scope"]:
        for scope in self.ancestors():
            if scope.kind is ScopeKind.CLASS:
                return scope
        return None

    def is_inside_loop(self) -> bool:
        """True si el ambito esta dentro de un bucle de la misma funcion."""
        for scope in self.ancestors():
            if scope.kind in LOOP_SCOPES:
                return True
            if scope.kind in FUNCTION_LIKE_SCOPES:
                # Un bucle exterior no alcanza al cuerpo de una funcion anidada.
                return False
        return False

    def is_inside_breakable(self) -> bool:
        """True si `break` es valido aqui (dentro de un bucle o de un switch)."""
        for scope in self.ancestors():
            if scope.kind in BREAKABLE_SCOPES:
                return True
            if scope.kind in FUNCTION_LIKE_SCOPES:
                return False
        return False

    @property
    def qualified_name(self) -> str:
        parts = [scope.name for scope in reversed(list(self.ancestors()))]
        return "::".join(parts)

    @property
    def depth(self) -> int:
        return len(list(self.ancestors())) - 1

    # --- exportacion ------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "qualifiedName": self.qualified_name,
            "kind": self.kind.value,
            "depth": self.depth,
            "parent": self.parent.id if self.parent is not None else None,
            "symbols": [symbol.to_dict() for symbol in self.symbols.values()],
            "children": [child.to_dict() for child in self.children],
        }

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuracion
        return f"<Scope {self.qualified_name} ({self.kind.value}) symbols={list(self.symbols)}>"
