"""Reglas centralizadas de compatibilidad de tipos.

Todo el analizador semantico consulta este modulo; no debe haber comparaciones
sueltas de nombres de tipo repartidas por el codigo.

Las funciones que necesitan conocer la jerarquia de clases reciben un objeto
``hierarchy`` opcional que implementa :class:`ClassHierarchy`.
"""

from __future__ import annotations

from typing import Iterable, Optional, Protocol, Sequence

from .types import (
    BOOLEAN,
    ERROR,
    FLOAT,
    INTEGER,
    NULL,
    STRING,
    UNKNOWN,
    VOID,
    ArrayType,
    ClassType,
    FunctionType,
    PrimitiveKind,
    PrimitiveType,
    Type,
)


class ClassHierarchy(Protocol):
    """Servicio minimo de consulta de herencia que requiere este modulo."""

    def is_subclass(self, subclass: str, superclass: str) -> bool:
        """True si ``subclass`` es ``superclass`` o desciende de ella."""

    def ancestors(self, class_name: str) -> list[str]:
        """Cadena de herencia de ``class_name``, empezando por ella misma."""


# --- Predicados basicos ----------------------------------------------------


def is_error(type_: Type) -> bool:
    return type_ is ERROR or (isinstance(type_, PrimitiveType) and type_.kind is PrimitiveKind.ERROR)


def is_unknown(type_: Type) -> bool:
    if isinstance(type_, PrimitiveType) and type_.kind is PrimitiveKind.UNKNOWN:
        return True
    if isinstance(type_, ArrayType):
        return is_unknown(type_.element)
    return False


def is_indeterminate(type_: Type) -> bool:
    """True para ``error``/``unknown``: tipos que no deben generar cascadas."""
    return is_error(type_) or is_unknown(type_)


def is_numeric(type_: Type) -> bool:
    return type_ in (INTEGER, FLOAT)


def is_integer(type_: Type) -> bool:
    return type_ == INTEGER


def is_float(type_: Type) -> bool:
    return type_ == FLOAT


def is_boolean(type_: Type) -> bool:
    return type_ == BOOLEAN


def is_string(type_: Type) -> bool:
    return type_ == STRING


def is_null(type_: Type) -> bool:
    return type_ == NULL


def is_void(type_: Type) -> bool:
    return type_ == VOID


def is_array(type_: Type) -> bool:
    return isinstance(type_, ArrayType)


def is_class(type_: Type) -> bool:
    return isinstance(type_, ClassType)


def is_reference(type_: Type) -> bool:
    """Tipos que admiten el valor ``null``.

    Se consideran de referencia las clases, los arreglos y ``string``; los
    tipos ``integer``, ``float`` y ``boolean`` son de valor y no son nulables.
    """
    return isinstance(type_, (ClassType, ArrayType)) or is_string(type_) or is_null(type_)


def is_value_type(type_: Type) -> bool:
    return type_ in (INTEGER, FLOAT, BOOLEAN)


# --- Asignabilidad ---------------------------------------------------------


def is_assignable(
    source: Type,
    target: Type,
    hierarchy: Optional[ClassHierarchy] = None,
) -> bool:
    """True si un valor de tipo ``source`` puede asignarse a ``target``.

    Reglas:

    * ``error``/``unknown`` son compatibles con todo (evita cascadas).
    * ``integer`` se promueve a ``float``; ``float`` **no** se degrada a ``integer``.
    * ``null`` es asignable a cualquier tipo de referencia.
    * Los arreglos son invariantes en su elemento, salvo que el origen tenga
      elemento ``unknown`` (caso del literal ``[]``).
    * Una clase es asignable a si misma o a cualquiera de sus ancestros.
    """
    if is_error(source) or is_error(target):
        return True
    if is_unknown(source) or is_unknown(target):
        # Un arreglo vacio (unknown[]) solo encaja contra otro arreglo.
        if isinstance(source, ArrayType) and not isinstance(target, ArrayType):
            return is_indeterminate(target)
        if isinstance(target, ArrayType) and not isinstance(source, ArrayType):
            return is_indeterminate(source)
        return True

    if source == target:
        return True

    if is_void(source) or is_void(target):
        return False

    if is_null(source):
        return is_reference(target)

    if source == INTEGER and target == FLOAT:
        return True

    if isinstance(source, ArrayType) and isinstance(target, ArrayType):
        # Los arreglos son invariantes: 'integer[]' no es un 'float[]' porque
        # escribir un float en el alias corromperia el arreglo original. El
        # literal '[1, 2]' si encaja en 'float[]' gracias al tipado contextual
        # que aplica el verificador (ver TypeChecker._assignable_expression).
        return source.element == target.element

    if isinstance(source, ClassType) and isinstance(target, ClassType):
        if hierarchy is None:
            return source.class_name == target.class_name
        return hierarchy.is_subclass(source.class_name, target.class_name)

    if isinstance(source, FunctionType) and isinstance(target, FunctionType):
        return source == target

    return False


def common_numeric_type(left: Type, right: Type) -> Type:
    """Tipo resultante de una operacion aritmetica entre dos numericos."""
    if is_indeterminate(left) or is_indeterminate(right):
        return ERROR
    if not is_numeric(left) or not is_numeric(right):
        return ERROR
    if is_float(left) or is_float(right):
        return FLOAT
    return INTEGER


def common_type(
    left: Type,
    right: Type,
    hierarchy: Optional[ClassHierarchy] = None,
) -> Optional[Type]:
    """Tipo comun mas especifico entre ``left`` y ``right``.

    Devuelve ``None`` cuando no existe un tipo comun (los tipos son
    incompatibles). Se usa en el operador ternario y en literales de arreglo.
    """
    if is_error(left) or is_error(right):
        return ERROR
    if is_unknown(left):
        return right
    if is_unknown(right):
        return left
    if left == right:
        return left

    if is_numeric(left) and is_numeric(right):
        return common_numeric_type(left, right)

    if is_null(left) and is_reference(right):
        return right
    if is_null(right) and is_reference(left):
        return left

    if isinstance(left, ArrayType) and isinstance(right, ArrayType):
        element = common_type(left.element, right.element, hierarchy)
        return ArrayType(element) if element is not None else None

    if isinstance(left, ClassType) and isinstance(right, ClassType):
        if hierarchy is None:
            return left if left.class_name == right.class_name else None
        for candidate in hierarchy.ancestors(left.class_name):
            if hierarchy.is_subclass(right.class_name, candidate):
                return ClassType(candidate)
        return None

    return None


def common_array_element_type(
    element_types: Sequence[Type],
    hierarchy: Optional[ClassHierarchy] = None,
) -> Optional[Type]:
    """Tipo del elemento de un literal de arreglo.

    Un literal vacio produce ``unknown``, que se concreta al asignarlo a una
    variable con tipo declarado. Devuelve ``None`` si los elementos no son
    homogeneos.
    """
    if not element_types:
        return UNKNOWN

    result: Type = element_types[0]
    for current in element_types[1:]:
        merged = common_type(result, current, hierarchy)
        if merged is None:
            return None
        result = merged
    return result


# --- Operadores ------------------------------------------------------------

#: Operadores relacionales de orden.
RELATIONAL_OPERATORS = ("<", "<=", ">", ">=")
#: Operadores de igualdad.
EQUALITY_OPERATORS = ("==", "!=")


def is_comparable(
    left: Type,
    right: Type,
    operator: str,
    hierarchy: Optional[ClassHierarchy] = None,
) -> bool:
    """True si ``left operator right`` es una comparacion valida.

    * ``<``, ``<=``, ``>``, ``>=`` solo aceptan operandos numericos.
      Compiscript no define orden lexicografico para ``string``, por lo que se
      rechaza la comparacion relacional entre cadenas.
    * ``==`` y ``!=`` aceptan cualquier par de tipos asignables en algun
      sentido, incluyendo ``integer``/``float`` y referencia contra ``null``.
    """
    if is_indeterminate(left) or is_indeterminate(right):
        return True

    if operator in RELATIONAL_OPERATORS:
        return is_numeric(left) and is_numeric(right)

    if operator in EQUALITY_OPERATORS:
        if is_void(left) or is_void(right):
            return False
        if is_null(left) or is_null(right):
            other = right if is_null(left) else left
            return is_null(other) or is_reference(other)
        return is_assignable(left, right, hierarchy) or is_assignable(right, left, hierarchy)

    return False


def is_concatenable(type_: Type) -> bool:
    """True si ``type_`` puede aparecer junto a un ``string`` en ``+``.

    Se admiten los tipos con representacion textual directa. Los arreglos, las
    instancias de clase y ``void`` quedan fuera porque no tienen una conversion
    a cadena definida por el lenguaje.
    """
    if is_indeterminate(type_):
        return True
    return is_string(type_) or is_numeric(type_) or is_boolean(type_) or is_null(type_)


def result_of_additive(left: Type, right: Type) -> Type:
    """Tipo resultante del operador ``+`` (sobrecargado).

    * Si alguno de los operandos es ``string`` y el otro es concatenable,
      ``+`` concatena y produce ``string``.
    * En caso contrario ambos operandos deben ser numericos y se aplica la
      promocion habitual.
    """
    if is_indeterminate(left) or is_indeterminate(right):
        return ERROR
    if is_string(left) or is_string(right):
        if is_concatenable(left) and is_concatenable(right):
            return STRING
        return ERROR
    return common_numeric_type(left, right)


def describe(types: Iterable[Type]) -> str:
    return ", ".join(f"'{t.name}'" for t in types)
