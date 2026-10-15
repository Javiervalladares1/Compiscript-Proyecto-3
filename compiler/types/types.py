"""Representacion explicita del sistema de tipos de Compiscript.

Los tipos son objetos inmutables y comparables por valor. Ninguna parte del
compilador debe comparar tipos usando cadenas: para eso existen los predicados
de :mod:`compiler.types.compatibility`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence


class PrimitiveKind(Enum):
    """Tipos atomicos del lenguaje mas los tipos internos del analizador."""

    INTEGER = "integer"
    FLOAT = "float"
    STRING = "string"
    BOOLEAN = "boolean"
    VOID = "void"
    NULL = "null"
    #: Tipo pendiente de resolver (p. ej. el elemento de un arreglo vacio).
    UNKNOWN = "unknown"
    #: Tipo de un error ya reportado; absorbe operaciones para evitar cascadas.
    ERROR = "error"


class Type:
    """Clase base de todos los tipos."""

    @property
    def name(self) -> str:  # pragma: no cover - sobrescrito por subclases
        raise NotImplementedError

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True)
class PrimitiveType(Type):
    kind: PrimitiveKind

    @property
    def name(self) -> str:
        return self.kind.value

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True)
class ArrayType(Type):
    """Tipo estructurado de arreglo: ``element[]``."""

    element: Type

    @property
    def name(self) -> str:
        return f"{self.element.name}[]"

    @property
    def dimensions(self) -> int:
        """Numero de pares ``[]`` acumulados (``integer[][]`` -> 2)."""
        if isinstance(self.element, ArrayType):
            return 1 + self.element.dimensions
        return 1

    @property
    def base_element(self) -> Type:
        """Tipo del elemento mas interno (``integer[][]`` -> ``integer``)."""
        if isinstance(self.element, ArrayType):
            return self.element.base_element
        return self.element

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True)
class ClassType(Type):
    """Tipo nominal de una clase declarada por el usuario."""

    class_name: str

    @property
    def name(self) -> str:
        return self.class_name

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True)
class FunctionType(Type):
    """Firma de una funcion/metodo.

    No es escribible en la gramatica; se usa para tipar el simbolo de una
    funcion cuando se referencia sin llamarla.
    """

    parameters: tuple[Type, ...]
    return_type: Type

    @property
    def name(self) -> str:
        params = ", ".join(p.name for p in self.parameters)
        return f"({params}) => {self.return_type.name}"

    def __str__(self) -> str:
        return self.name


# --- Instancias unicas de los tipos primitivos -----------------------------

INTEGER = PrimitiveType(PrimitiveKind.INTEGER)
FLOAT = PrimitiveType(PrimitiveKind.FLOAT)
STRING = PrimitiveType(PrimitiveKind.STRING)
BOOLEAN = PrimitiveType(PrimitiveKind.BOOLEAN)
VOID = PrimitiveType(PrimitiveKind.VOID)
NULL = PrimitiveType(PrimitiveKind.NULL)
UNKNOWN = PrimitiveType(PrimitiveKind.UNKNOWN)
ERROR = PrimitiveType(PrimitiveKind.ERROR)

#: Nombres de tipo escribibles en una anotacion de la gramatica.
BUILTIN_TYPE_NAMES: dict[str, Type] = {
    "integer": INTEGER,
    "float": FLOAT,
    "string": STRING,
    "boolean": BOOLEAN,
    "void": VOID,
    "null": NULL,
}


def array_of(element: Type, dimensions: int = 1) -> Type:
    """Construye ``element`` envuelto en ``dimensions`` niveles de arreglo."""
    result = element
    for _ in range(dimensions):
        result = ArrayType(result)
    return result


def type_names(types: Sequence[Type]) -> str:
    """Formatea una lista de tipos para mensajes de diagnostico."""
    return ", ".join(t.name for t in types)
