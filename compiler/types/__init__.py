"""Sistema de tipos de Compiscript."""

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
    Type,
    array_of,
)

__all__ = [
    "Type",
    "ArrayType",
    "ClassType",
    "FunctionType",
    "INTEGER",
    "FLOAT",
    "STRING",
    "BOOLEAN",
    "VOID",
    "NULL",
    "UNKNOWN",
    "ERROR",
    "array_of",
]
