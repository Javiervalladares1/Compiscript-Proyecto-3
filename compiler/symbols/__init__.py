"""Tabla de simbolos con ambitos anidados."""

from .scope import Scope, ScopeKind
from .symbols import (
    ClassSymbol,
    FunctionSymbol,
    ParameterInfo,
    Symbol,
    SymbolCategory,
    VariableSymbol,
)
from .table import ClassRegistry, SymbolTable

__all__ = [
    "Scope",
    "ScopeKind",
    "Symbol",
    "SymbolCategory",
    "VariableSymbol",
    "FunctionSymbol",
    "ClassSymbol",
    "ParameterInfo",
    "SymbolTable",
    "ClassRegistry",
]
