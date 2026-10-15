"""Resultado de una compilacion, compartido por el CLI y el IDE."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .ast import nodes as N
from .ast.serializer import ast_to_dict
from .ir.model import IRProgram
from .semantic.diagnostics import Diagnostic, Phase, Severity
from .symbols.table import SymbolTable


@dataclass
class CompileOptions:
    """Opciones de la compilacion."""

    #: Trata las advertencias como errores.
    strict: bool = False
    #: Omite el analisis semantico (solo lexico + sintactico).
    syntax_only: bool = False
    #: Las fases nuevas son opt-in para conservar la API del frontend.
    generate_tac: bool = False
    generate_mips: bool = False
    allocation: str = "registers"

    def __post_init__(self) -> None:
        if self.allocation not in ("registers", "stack"):
            raise ValueError("allocation debe ser 'registers' o 'stack'")
        if self.syntax_only and (self.generate_tac or self.generate_mips):
            raise ValueError("syntax_only no se puede combinar con generacion TAC/MIPS")


@dataclass
class CompilationResult:
    """Salida del frontend y de las fases de generacion solicitadas."""

    filename: str
    source: str
    diagnostics: list[Diagnostic] = field(default_factory=list)
    ast: Optional[N.Program] = None
    symbol_table: Optional[SymbolTable] = None
    options: CompileOptions = field(default_factory=CompileOptions)
    ir: Optional[IRProgram] = None
    mips: Optional[str] = None

    @property
    def tac(self) -> Optional[str]:
        return self.ir.to_text() if self.ir is not None else None

    # --- diagnosticos -----------------------------------------------------

    @property
    def syntax_diagnostics(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.phase in (Phase.LEXICAL, Phase.SYNTACTIC)]

    @property
    def semantic_diagnostics(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.phase is Phase.SEMANTIC]

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity is Severity.WARNING]

    @property
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def warning_count(self) -> int:
        return len(self.warnings)

    @property
    def success(self) -> bool:
        """True si la compilacion no produjo errores.

        En modo ``--strict`` una advertencia tambien invalida la compilacion.
        """
        if self.error_count:
            return False
        if self.options.strict and self.warning_count:
            return False
        return True

    @property
    def exit_code(self) -> int:
        return 0 if self.success else 1

    def codes(self) -> list[str]:
        """Codigos emitidos, util para las pruebas."""
        return [d.code for d in self.diagnostics]

    # --- serializacion ----------------------------------------------------

    def ast_dict(self) -> Optional[dict[str, Any]]:
        return ast_to_dict(self.ast) if self.ast is not None else None

    def symbols_dict(self) -> Optional[dict[str, Any]]:
        return self.symbol_table.to_dict() if self.symbol_table is not None else None

    def to_dict(self) -> dict[str, Any]:
        """Estructura consumida por el IDE y por la salida ``--diagnostics json``."""
        return {
            "success": self.success,
            "file": self.filename,
            "diagnostics": [d.to_dict() for d in self.diagnostics],
            "errorCount": self.error_count,
            "warningCount": self.warning_count,
            "ast": self.ast_dict(),
            "symbolTable": self.symbols_dict(),
            "symbolRows": self.symbol_table.rows() if self.symbol_table is not None else [],
            "tac": self.tac,
            "mips": self.mips,
        }
