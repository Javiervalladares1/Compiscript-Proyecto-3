"""Diagnosticos centralizados del compilador.

Todo mensaje dirigido al usuario (sintactico o semantico, error o advertencia)
se crea aqui. Ningun modulo de analisis imprime por su cuenta.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Iterator, Optional

from ..ast.nodes import SourceSpan
from ..types.types import Type


class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"

    def __str__(self) -> str:
        return self.value


class Phase(Enum):
    """Fase del compilador que emitio el diagnostico."""

    LEXICAL = "lexical"
    SYNTACTIC = "syntactic"
    SEMANTIC = "semantic"
    CODEGEN = "codegen"


class Code:
    """Catalogo de codigos estables.

    Los codigos no deben reutilizarse ni renumerarse: las pruebas verifican
    por codigo, no por el texto del mensaje.
    """

    # --- Lexico / sintactico ---
    SYNTAX = "SYN001"
    LEXICAL = "SYN002"

    # --- Codigo intermedio y backend ---
    UNSUPPORTED_CODEGEN = "GEN001"

    # --- Declaraciones y ambitos ---
    UNDECLARED_IDENTIFIER = "SEM001"
    UNDECLARED_FUNCTION = "SEM002"
    UNDECLARED_CLASS = "SEM003"
    DUPLICATE_DECLARATION = "SEM004"
    DUPLICATE_PARAMETER = "SEM005"
    DUPLICATE_MEMBER = "SEM006"
    CONST_WITHOUT_INITIALIZER = "SEM007"
    CONST_REASSIGNMENT = "SEM008"
    ASSIGN_TO_UNDECLARED = "SEM009"
    CANNOT_INFER_TYPE = "SEM010"
    UNKNOWN_TYPE_NAME = "SEM011"

    # --- Tipos y operadores ---
    INCOMPATIBLE_ASSIGNMENT = "SEM012"
    NON_NUMERIC_OPERAND = "SEM013"
    NON_BOOLEAN_OPERAND = "SEM014"
    INVALID_RELATIONAL = "SEM015"
    INVALID_EQUALITY = "SEM016"
    NON_BOOLEAN_CONDITION = "SEM017"
    INCOMPATIBLE_TERNARY = "SEM018"
    NOT_A_VALUE = "SEM019"
    INVALID_CONCATENATION = "SEM047"
    NULL_OPERATION = "SEM048"
    VOID_AS_VALUE = "SEM049"

    # --- Funciones ---
    NOT_CALLABLE = "SEM020"
    ARGUMENT_COUNT_MISMATCH = "SEM021"
    ARGUMENT_TYPE_MISMATCH = "SEM022"
    INCOMPATIBLE_RETURN = "SEM023"
    RETURN_OUTSIDE_FUNCTION = "SEM024"
    MISSING_RETURN = "SEM025"
    RETURN_VALUE_IN_VOID = "SEM026"

    # --- Control de flujo ---
    BREAK_OUTSIDE_LOOP = "SEM027"
    CONTINUE_OUTSIDE_LOOP = "SEM028"
    FOREACH_NOT_ITERABLE = "SEM029"

    # --- Arreglos ---
    NON_INTEGER_INDEX = "SEM030"
    NOT_INDEXABLE = "SEM031"
    HETEROGENEOUS_ARRAY = "SEM032"
    UNRESOLVED_EMPTY_ARRAY = "SEM033"

    # --- Clases y objetos ---
    UNKNOWN_PROPERTY = "SEM034"
    UNKNOWN_METHOD = "SEM035"
    PROPERTY_ON_NON_OBJECT = "SEM036"
    THIS_OUTSIDE_CLASS = "SEM037"
    NEW_ON_NON_CLASS = "SEM038"
    UNKNOWN_BASE_CLASS = "SEM039"
    INHERITANCE_CYCLE = "SEM040"
    INCOMPATIBLE_OVERRIDE = "SEM041"
    CONSTRUCTOR_MISUSE = "SEM042"

    # --- switch ---
    INCOMPATIBLE_CASE = "SEM043"
    DUPLICATE_CASE = "SEM044"
    INVALID_SWITCH_SUBJECT = "SEM045"

    # --- Inicializacion / asignabilidad ---
    USE_BEFORE_INITIALIZATION = "SEM046"
    INVALID_ASSIGNMENT_TARGET = "SEM050"

    # --- Advertencias ---
    UNREACHABLE_AFTER_RETURN = "SEM-W001"
    UNREACHABLE_AFTER_BREAK = "SEM-W002"
    UNREACHABLE_AFTER_CONTINUE = "SEM-W003"
    UNREACHABLE_CONDITION = "SEM-W004"
    INDEX_OUT_OF_RANGE = "SEM-W005"


@dataclass(frozen=True)
class Diagnostic:
    """Un mensaje del compilador con ubicacion exacta."""

    code: str
    severity: Severity
    message: str
    file: str
    line: int
    column: int
    phase: Phase = Phase.SEMANTIC
    expected_type: Optional[str] = None
    actual_type: Optional[str] = None
    end_line: Optional[int] = None
    end_column: Optional[int] = None

    @property
    def is_error(self) -> bool:
        return self.severity is Severity.ERROR

    def format(self) -> str:
        """Representacion legible: ``archivo:linea:columna [CODIGO] mensaje``."""
        return f"{self.file}:{self.line}:{self.column} [{self.code}] {self.message}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "phase": self.phase.value,
            "message": self.message,
            "file": self.file,
            "line": self.line,
            "column": self.column,
            "endLine": self.end_line,
            "endColumn": self.end_column,
            "expectedType": self.expected_type,
            "actualType": self.actual_type,
            "formatted": self.format(),
        }

    @property
    def sort_key(self) -> tuple[int, int, str]:
        return (self.line, self.column, self.code)


class DiagnosticBag:
    """Acumulador de diagnosticos.

    El analisis nunca se detiene en el primer error: los diagnosticos se
    acumulan y se ordenan por ubicacion al consultarlos.
    """

    def __init__(self, filename: str = "<memory>") -> None:
        self.filename = filename
        self._items: list[Diagnostic] = []
        self._seen: set[tuple[str, int, int, str]] = set()

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[Diagnostic]:
        return iter(self.sorted())

    def add(self, diagnostic: Diagnostic) -> None:
        key = (diagnostic.code, diagnostic.line, diagnostic.column, diagnostic.message)
        if key in self._seen:
            return
        self._seen.add(key)
        self._items.append(diagnostic)

    def report(
        self,
        code: str,
        message: str,
        span: Optional[SourceSpan] = None,
        *,
        severity: Severity = Severity.ERROR,
        phase: Phase = Phase.SEMANTIC,
        expected: Optional[Type | str] = None,
        actual: Optional[Type | str] = None,
    ) -> None:
        """Registra un diagnostico a partir de un span del AST."""
        file = span.file if span is not None else self.filename
        line = span.line if span is not None else 1
        column = span.column if span is not None else 1
        self.add(
            Diagnostic(
                code=code,
                severity=severity,
                message=message,
                file=file,
                line=line,
                column=column,
                phase=phase,
                expected_type=_type_name(expected),
                actual_type=_type_name(actual),
                end_line=span.end_line if span is not None else None,
                end_column=span.end_column if span is not None else None,
            )
        )

    def warn(
        self,
        code: str,
        message: str,
        span: Optional[SourceSpan] = None,
        **kwargs: Any,
    ) -> None:
        self.report(code, message, span, severity=Severity.WARNING, **kwargs)

    def extend(self, diagnostics: Iterable[Diagnostic]) -> None:
        for diagnostic in diagnostics:
            self.add(diagnostic)

    def sorted(self) -> list[Diagnostic]:
        return sorted(self._items, key=lambda d: d.sort_key)

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.sorted() if d.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.sorted() if d.severity is Severity.WARNING]

    @property
    def has_errors(self) -> bool:
        return any(d.severity is Severity.ERROR for d in self._items)


def _type_name(value: Optional[Type | str]) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.name


@dataclass
class DiagnosticCounts:
    errors: int = 0
    warnings: int = 0
    by_code: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_diagnostics(cls, diagnostics: Iterable[Diagnostic]) -> "DiagnosticCounts":
        counts = cls()
        for diagnostic in diagnostics:
            if diagnostic.severity is Severity.ERROR:
                counts.errors += 1
            else:
                counts.warnings += 1
            counts.by_code[diagnostic.code] = counts.by_code.get(diagnostic.code, 0) + 1
        return counts
