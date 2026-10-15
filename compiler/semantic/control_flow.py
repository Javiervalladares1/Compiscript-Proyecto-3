"""Analisis de flujo de control: caminos de retorno y codigo inalcanzable.

El analisis es sintactico y conservador: solo afirma que un bloque siempre
retorna cuando puede demostrarlo con la estructura del AST, de modo que nunca
reporta falsos positivos por caminos que en realidad si retornan.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Sequence

from ..ast import nodes as N
from .diagnostics import Code, DiagnosticBag


class Termination(Enum):
    """Como termina una sentencia respecto al flujo secuencial."""

    #: El flujo continua con la siguiente sentencia.
    NORMAL = "normal"
    RETURN = "return"
    BREAK = "break"
    CONTINUE = "continue"

    @property
    def is_abrupt(self) -> bool:
        return self is not Termination.NORMAL


#: Codigo de advertencia asociado a cada terminacion abrupta.
_UNREACHABLE_CODES = {
    Termination.RETURN: (Code.UNREACHABLE_AFTER_RETURN, "return"),
    Termination.BREAK: (Code.UNREACHABLE_AFTER_BREAK, "break"),
    Termination.CONTINUE: (Code.UNREACHABLE_AFTER_CONTINUE, "continue"),
}


@dataclass
class FlowResult:
    termination: Termination

    @property
    def always_returns(self) -> bool:
        return self.termination is Termination.RETURN


def _literal_boolean(expression: Optional[N.Expression]) -> Optional[bool]:
    """Valor de una condicion booleana literal, si se puede determinar."""
    if isinstance(expression, N.BooleanLiteral):
        return expression.value
    if isinstance(expression, N.UnaryExpr) and expression.operator == "!":
        inner = _literal_boolean(expression.operand)
        return None if inner is None else not inner
    return None


class ControlFlowAnalyzer:
    """Calcula terminaciones y reporta codigo inalcanzable.

    Lleva la cuenta de si el recorrido esta dentro de una funcion, de un bucle
    o de un ``switch``. Un ``return``/``break``/``continue`` usado fuera de su
    contexto valido ya se reporta como error semantico, asi que aqui no
    interrumpe el flujo: de lo contrario marcaria como codigo muerto todo lo
    que le sigue.
    """

    def __init__(self, diagnostics: DiagnosticBag) -> None:
        self._diagnostics = diagnostics
        self._function_depth = 0
        self._loop_depth = 0
        self._switch_depth = 0

    # --- API --------------------------------------------------------------

    def analyze_function_body(self, body: N.Block) -> bool:
        """True si el cuerpo retorna un valor por todos los caminos."""
        self._function_depth += 1
        # Un bucle exterior no alcanza al cuerpo de una funcion anidada.
        loops, switches = self._loop_depth, self._switch_depth
        self._loop_depth = self._switch_depth = 0
        try:
            return self.analyze_block(body).always_returns
        finally:
            self._function_depth -= 1
            self._loop_depth, self._switch_depth = loops, switches

    def analyze_block(self, block: N.Block) -> FlowResult:
        return self.analyze_statements(block.statements)

    def analyze_statements(self, statements: Sequence[N.Statement]) -> FlowResult:
        termination = Termination.NORMAL
        for index, statement in enumerate(statements):
            if termination.is_abrupt:
                self._report_unreachable(statements[index], termination)
                # Se sigue analizando el resto para no perder otros mensajes,
                # pero solo se advierte de la primera sentencia inalcanzable.
                self._analyze_statement(statement)
                for remaining in statements[index + 1 :]:
                    self._analyze_statement(remaining)
                return FlowResult(termination)
            termination = self._analyze_statement(statement)
        return FlowResult(termination)

    # --- por tipo de sentencia -------------------------------------------

    def _analyze_statement(self, statement: N.Statement) -> Termination:
        if isinstance(statement, N.ReturnStmt):
            return Termination.RETURN if self._function_depth else Termination.NORMAL
        if isinstance(statement, N.BreakStmt):
            breakable = self._loop_depth or self._switch_depth
            return Termination.BREAK if breakable else Termination.NORMAL
        if isinstance(statement, N.ContinueStmt):
            return Termination.CONTINUE if self._loop_depth else Termination.NORMAL
        if isinstance(statement, N.Block):
            return self.analyze_block(statement).termination
        if isinstance(statement, N.IfStmt):
            return self._analyze_if(statement)
        if isinstance(statement, N.WhileStmt):
            return self._analyze_while(statement)
        if isinstance(statement, N.DoWhileStmt):
            return self._analyze_do_while(statement)
        if isinstance(statement, N.ForStmt):
            return self._analyze_for(statement)
        if isinstance(statement, N.ForEachStmt):
            self._analyze_loop_body(statement.body)
            return Termination.NORMAL
        if isinstance(statement, N.SwitchStmt):
            return self._analyze_switch(statement)
        if isinstance(statement, N.TryCatchStmt):
            return self._analyze_try(statement)
        if isinstance(statement, N.FunctionDecl):
            # El cuerpo de una funcion anidada se analiza en su propio contexto.
            return Termination.NORMAL
        if isinstance(statement, N.ClassDecl):
            return Termination.NORMAL
        return Termination.NORMAL

    def _analyze_if(self, statement: N.IfStmt) -> Termination:
        literal = _literal_boolean(statement.condition)
        then_result = self.analyze_block(statement.then_block)

        if statement.else_block is None:
            if literal is False:
                self._diagnostics.warn(
                    Code.UNREACHABLE_CONDITION,
                    "El bloque 'if' nunca se ejecuta porque la condicion es siempre falsa.",
                    statement.then_block.span,
                )
            if literal is True:
                return then_result.termination
            return Termination.NORMAL

        else_result = self.analyze_block(statement.else_block)
        if literal is True:
            self._diagnostics.warn(
                Code.UNREACHABLE_CONDITION,
                "El bloque 'else' nunca se ejecuta porque la condicion es siempre verdadera.",
                statement.else_block.span,
            )
            return then_result.termination
        if literal is False:
            self._diagnostics.warn(
                Code.UNREACHABLE_CONDITION,
                "El bloque 'if' nunca se ejecuta porque la condicion es siempre falsa.",
                statement.then_block.span,
            )
            return else_result.termination

        if then_result.termination is Termination.NORMAL:
            return Termination.NORMAL
        if else_result.termination is Termination.NORMAL:
            return Termination.NORMAL
        if then_result.termination is else_result.termination:
            return then_result.termination
        # Ramas con terminaciones abruptas distintas (p. ej. return / break):
        # desde fuera del bucle solo se garantiza que no continua en secuencia.
        return Termination.BREAK

    def _analyze_while(self, statement: N.WhileStmt) -> Termination:
        literal = _literal_boolean(statement.condition)
        if literal is False:
            self._diagnostics.warn(
                Code.UNREACHABLE_CONDITION,
                "El cuerpo del 'while' nunca se ejecuta porque la condicion es siempre falsa.",
                statement.body.span,
            )
        body = self._analyze_loop_body(statement.body)
        if literal is True and not self._has_break(statement.body):
            # while (true) sin break: el flujo no continua tras el bucle.
            return Termination.RETURN if body is Termination.RETURN else Termination.BREAK
        return Termination.NORMAL

    def _analyze_do_while(self, statement: N.DoWhileStmt) -> Termination:
        body = self._analyze_loop_body(statement.body)
        if body is Termination.RETURN:
            # El cuerpo se ejecuta siempre al menos una vez.
            return Termination.RETURN
        return Termination.NORMAL

    def _analyze_for(self, statement: N.ForStmt) -> Termination:
        if statement.condition is not None and _literal_boolean(statement.condition) is False:
            if statement.body is not None:
                self._diagnostics.warn(
                    Code.UNREACHABLE_CONDITION,
                    "El cuerpo del 'for' nunca se ejecuta porque la condicion es siempre falsa.",
                    statement.body.span,
                )
        if statement.body is not None:
            self._analyze_loop_body(statement.body)
        return Termination.NORMAL

    def _analyze_loop_body(self, body: N.Block) -> Termination:
        """Analiza el cuerpo de un bucle; ``break``/``continue`` se absorben."""
        self._loop_depth += 1
        try:
            return self.analyze_block(body).termination
        finally:
            self._loop_depth -= 1

    def _analyze_switch(self, statement: N.SwitchStmt) -> Termination:
        self._switch_depth += 1
        try:
            results = [
                self.analyze_statements(case.statements).termination
                for case in statement.cases
            ]
            if statement.default_case is None:
                # Sin 'default' siempre hay un camino en que ningun case aplica.
                return Termination.NORMAL
            results.append(
                self.analyze_statements(statement.default_case.statements).termination
            )
        finally:
            self._switch_depth -= 1
        if results and all(t is Termination.RETURN for t in results):
            return Termination.RETURN
        return Termination.NORMAL

    def _analyze_try(self, statement: N.TryCatchStmt) -> Termination:
        try_result = self.analyze_block(statement.try_block)
        catch_result = self.analyze_block(statement.catch_block)
        if try_result.termination is Termination.RETURN and (
            catch_result.termination is Termination.RETURN
        ):
            return Termination.RETURN
        return Termination.NORMAL

    # --- utilidades -------------------------------------------------------

    def _report_unreachable(self, statement: N.Statement, termination: Termination) -> None:
        code, keyword = _UNREACHABLE_CODES[termination]
        self._diagnostics.warn(
            code,
            f"Codigo inalcanzable despues de '{keyword}'.",
            statement.span,
        )

    @staticmethod
    def _has_break(block: N.Block) -> bool:
        """True si el bloque contiene un ``break`` propio del bucle actual."""

        def walk(node: N.Node) -> bool:
            for child in node.children():
                if isinstance(child, N.BreakStmt):
                    return True
                if isinstance(child, (N.WhileStmt, N.DoWhileStmt, N.ForStmt, N.ForEachStmt)):
                    continue  # los break de bucles anidados no cuentan
                if isinstance(child, (N.FunctionDecl, N.ClassDecl)):
                    continue
                if walk(child):
                    return True
            return False

        return walk(block)
