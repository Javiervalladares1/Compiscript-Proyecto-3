"""Orquestador del analisis semantico.

Ejecuta las pasadas en un orden fijo para que las declaraciones esten
disponibles antes de verificar los cuerpos:

1. Registro de clases globales.
2. Resolucion de herencia (existencia de la base y deteccion de ciclos).
3. Registro de miembros de clase (atributos, metodos y constructor).
4. Registro de firmas de funciones globales.
5. Verificacion de cuerpos, ambitos y tipos.
6. Validaciones de flujo de control (codigo muerto).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..ast import nodes as N
from ..symbols.table import SymbolTable
from .control_flow import ControlFlowAnalyzer
from .declarations import DeclarationCollector
from .diagnostics import DiagnosticBag
from .type_checker import TypeChecker
from .type_resolver import TypeResolver


@dataclass
class SemanticResult:
    table: SymbolTable
    diagnostics: DiagnosticBag


class SemanticAnalyzer:
    """Punto de entrada del analisis semantico."""

    def __init__(self, filename: str = "<memory>") -> None:
        self.filename = filename
        self.diagnostics = DiagnosticBag(filename)
        self.table = SymbolTable(filename)
        self._resolver = TypeResolver(self.table, self.diagnostics)
        self._collector = DeclarationCollector(self.table, self.diagnostics, self._resolver)
        self._checker = TypeChecker(
            self.table, self.diagnostics, self._resolver, self._collector
        )

    def analyze(self, program: N.Program) -> SemanticResult:
        self._collector.collect_classes(program)
        self._collector.resolve_inheritance()
        self._collector.collect_class_members(program)
        self._collector.collect_functions(program)
        self._checker.check_program(program)
        self._analyze_control_flow(program)
        return SemanticResult(table=self.table, diagnostics=self.diagnostics)

    def _analyze_control_flow(self, program: N.Program) -> None:
        """Detecta codigo inalcanzable en el programa y en cada funcion."""
        analyzer = ControlFlowAnalyzer(self.diagnostics)
        analyzer.analyze_statements(program.statements)
        for declaration in _iter_function_declarations(program):
            if declaration.body is not None:
                analyzer.analyze_function_body(declaration.body)


def _iter_function_declarations(node: N.Node) -> list[N.FunctionDecl]:
    """Todas las funciones y metodos del arbol, en orden de aparicion."""
    result: list[N.FunctionDecl] = []
    if isinstance(node, N.FunctionDecl):
        result.append(node)
    for child in node.children():
        result.extend(_iter_function_declarations(child))
    return result
