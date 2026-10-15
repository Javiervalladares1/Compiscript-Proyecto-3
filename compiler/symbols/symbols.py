"""Simbolos de la tabla de simbolos.

Cada simbolo guarda la informacion que necesita el analisis semantico y la que
requeriran las fases posteriores del compilador (generacion de codigo
intermedio y final): desplazamientos, tamanos, capturas de closures y la
referencia al nodo del AST que lo declaro.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

from ..ast.nodes import SourceSpan
from ..types.types import Type, VOID

if TYPE_CHECKING:  # pragma: no cover - solo para anotaciones
    from .scope import Scope


class SymbolCategory(Enum):
    VARIABLE = "variable"
    CONSTANT = "constant"
    PARAMETER = "parameter"
    FUNCTION = "function"
    CLASS = "class"
    FIELD = "field"
    METHOD = "method"
    CONSTRUCTOR = "constructor"

    def __str__(self) -> str:
        return self.value


class Visibility(Enum):
    """Compiscript solo tiene visibilidad publica; se modela para el futuro."""

    PUBLIC = "public"

    def __str__(self) -> str:
        return self.value


@dataclass
class Symbol:
    """Base comun a todos los simbolos."""

    name: str
    category: SymbolCategory
    type: Type
    span: Optional[SourceSpan] = None
    scope: Optional["Scope"] = field(default=None, repr=False, compare=False)
    visibility: Visibility = Visibility.PUBLIC
    ast_node: Optional[Any] = field(default=None, repr=False, compare=False)
    #: Reservado para la asignacion de memoria de fases posteriores.
    offset: Optional[int] = None

    @property
    def qualified_name(self) -> str:
        return self.name

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category.value,
            "type": self.type.name,
            "visibility": self.visibility.value,
            "declaredAt": self.span.to_dict() if self.span is not None else None,
            "scope": self.scope.qualified_name if self.scope is not None else None,
            "offset": self.offset,
        }


@dataclass
class VariableSymbol(Symbol):
    """Variable, constante, parametro o atributo de clase."""

    mutable: bool = True
    initialized: bool = False
    #: Clase propietaria cuando el simbolo es un atributo.
    owner_class: Optional[str] = None
    #: True si alguna funcion anidada captura esta variable.
    captured: bool = False
    #: Longitud del arreglo cuando se conoce estaticamente (literal directo).
    #: Se invalida (``None``) en cuanto la variable se reasigna.
    array_length: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(
            {
                "mutable": self.mutable,
                "initialized": self.initialized,
                "ownerClass": self.owner_class,
                "captured": self.captured,
            }
        )
        return data


@dataclass
class ParameterInfo:
    """Descripcion posicional de un parametro dentro de una firma."""

    name: str
    type: Type
    index: int
    span: Optional[SourceSpan] = None

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "type": self.type.name, "index": self.index}


@dataclass
class FunctionSymbol(Symbol):
    """Funcion global, funcion anidada, metodo o constructor."""

    parameters: list[ParameterInfo] = field(default_factory=list)
    return_type: Type = VOID
    #: True cuando el tipo de retorno se infirio (no habia anotacion).
    return_type_inferred: bool = False
    owner_class: Optional[str] = None
    #: Nombres de variables de ambitos externos capturadas por la funcion.
    captures: list[str] = field(default_factory=list)
    #: Funcion que la contiene lexicamente (None si es de nivel superior).
    enclosing_function: Optional[str] = None
    body_scope: Optional["Scope"] = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        self.refresh_type()

    @property
    def arity(self) -> int:
        return len(self.parameters)

    @property
    def parameter_types(self) -> tuple[Type, ...]:
        return tuple(p.type for p in self.parameters)

    def refresh_type(self) -> None:
        """Sincroniza ``type`` con la firma actual.

        Debe llamarse tras inferir el tipo de retorno, para que la tabla de
        simbolos exporte la firma definitiva.
        """
        from ..types.types import FunctionType

        self.type = FunctionType(self.parameter_types, self.return_type)

    @property
    def signature(self) -> str:
        params = ", ".join(f"{p.name}: {p.type.name}" for p in self.parameters)
        return f"{self.name}({params}): {self.return_type.name}"

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(
            {
                "parameters": [p.to_dict() for p in self.parameters],
                "returnType": self.return_type.name,
                "returnTypeInferred": self.return_type_inferred,
                "ownerClass": self.owner_class,
                "captures": list(self.captures),
                "enclosingFunction": self.enclosing_function,
                "signature": self.signature,
            }
        )
        return data


@dataclass
class ClassSymbol(Symbol):
    """Clase declarada por el usuario."""

    base_name: Optional[str] = None
    base_span: Optional[SourceSpan] = None
    fields: dict[str, VariableSymbol] = field(default_factory=dict)
    methods: dict[str, FunctionSymbol] = field(default_factory=dict)
    constructor: Optional[FunctionSymbol] = None
    class_scope: Optional["Scope"] = field(default=None, repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(
            {
                "baseClass": self.base_name,
                "fields": [f.to_dict() for f in self.fields.values()],
                "methods": [m.to_dict() for m in self.methods.values()],
                "constructor": self.constructor.to_dict() if self.constructor else None,
            }
        )
        return data
