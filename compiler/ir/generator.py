"""Baja el AST semantico a TAC, conservando tipos y orden de evaluacion."""

from __future__ import annotations

import math

from ..ast import nodes as N
from ..symbols.symbols import FunctionSymbol, VariableSymbol
from ..symbols.table import SymbolTable
from ..types.types import BOOLEAN, FLOAT, INTEGER, NULL, STRING, VOID, ArrayType, Type
from .model import Constant, Instruction, IRFunction, IRProgram, Operand, Place


class CodegenError(Exception):
    def __init__(self, message: str, span: N.SourceSpan | None = None):
        super().__init__(message)
        self.span = span


class IRGenerator:
    def __init__(self, table: SymbolTable):
        self.table = table
        self.program = IRProgram()
        self.function = IRFunction("_cs_entry")
        self.program.functions.append(self.function)
        self.symbol_places: dict[int, Place] = {}
        self.declarations: dict[int, VariableSymbol | FunctionSymbol] = {}
        self.function_names: dict[int, str] = {}
        self.temp_id = 0
        self.label_id = 0
        self.breaks: list[str] = []
        self.continues: list[str] = []
        for scope in table.all_scopes:
            for symbol in scope.symbols.values():
                if symbol.ast_node is not None:
                    self.declarations[id(symbol.ast_node)] = symbol
                if isinstance(symbol, FunctionSymbol):
                    self.function_names[id(symbol)] = f"_cs_fn_{scope.id}_{symbol.name}"

    def emit(self, op: str, result: Place | None = None, *args: Operand,
             target: str = "", span: N.SourceSpan | None = None) -> None:
        self.function.instructions.append(Instruction(op, result, tuple(args), target, span))

    def temp(self, type_: Type) -> Place:
        self.temp_id += 1
        place = Place(f"_t{self.temp_id}", type_)
        self.function.places.append(place)
        return place

    def label(self) -> str:
        self.label_id += 1
        return f"_cs_L{self.label_id}"

    def variable(self, symbol: VariableSymbol) -> Place:
        if id(symbol) not in self.symbol_places:
            scope = symbol.scope
            assert scope is not None
            owner = scope.enclosing_function_scope()
            if owner is not None and self.function.name == "_cs_entry":
                raise CodegenError("No se pueden capturar variables de otra funcion.", symbol.span)
            storage = "global" if owner is None else "local"
            place = Place(f"_v{scope.id}_{symbol.name}", symbol.type, storage)
            self.symbol_places[id(symbol)] = place
            if storage == "global":
                self.program.globals.append(place)
            else:
                self.function.places.append(place)
        return self.symbol_places[id(symbol)]

    def convert(self, value: Operand, type_: Type, span: N.SourceSpan) -> Operand:
        if value.type == INTEGER and type_ == FLOAT:
            result = self.temp(FLOAT)
            self.emit("int_to_float", result, value, span=span)
            return result
        return value

    def generate(self, ast: N.Program) -> IRProgram:
        # Reservar globales antes de bajar cuerpos que las referencien.
        for scope in self.table.all_scopes:
            if scope.enclosing_function_scope() is None:
                for symbol in scope.symbols.values():
                    if isinstance(symbol, VariableSymbol) and symbol.owner_class is None:
                        self.variable(symbol)
        for statement in ast.statements:
            if not isinstance(statement, N.FunctionDecl):
                self.statement(statement)
        self.emit("return")
        for statement in ast.statements:
            if isinstance(statement, N.FunctionDecl):
                self.lower_function(statement)
        return self.program

    def lower_function(self, node: N.FunctionDecl) -> None:
        symbol = self.declarations[id(node)]
        assert isinstance(symbol, FunctionSymbol)
        if symbol.enclosing_function is not None:
            raise CodegenError("El backend MIPS no admite closures ni funciones anidadas.", node.span)
        self.function = IRFunction(self.function_names[id(symbol)], symbol.return_type)
        self.program.functions.append(self.function)
        assert symbol.body_scope is not None
        for parameter in symbol.parameters:
            param_symbol = symbol.body_scope.symbols[parameter.name]
            assert isinstance(param_symbol, VariableSymbol)
            self.function.parameters.append(self.variable(param_symbol))
        if node.body:
            self.statement(node.body)
        # El frontend ya verifica los retornos faltantes; este retorno cubre void.
        self.emit("return")

    def statement(self, node: N.Statement) -> None:
        if isinstance(node, N.Block):
            for child in node.statements:
                self.statement(child)
        elif isinstance(node, N.VarDecl):
            symbol = self.declarations[id(node)]
            assert isinstance(symbol, VariableSymbol)
            dest = self.variable(symbol)
            if node.initializer is not None:
                value = self.convert(self.expression(node.initializer), dest.type, node.span)
                self.emit("copy", dest, value, span=node.span)
        elif isinstance(node, (N.AssignStmt, N.AssignExpr)):
            self.assignment(node.target, node.value, node.span)
        elif isinstance(node, N.ExpressionStmt):
            self.expression(node.expression)
        elif isinstance(node, N.PrintStmt):
            value = self.expression(node.value)
            if isinstance(value.type, ArrayType):
                raise CodegenError("Imprima elementos individuales del arreglo.", node.span)
            self.emit("print", None, value, span=node.span)
        elif isinstance(node, N.ReturnStmt):
            if node.value is None:
                self.emit("return", span=node.span)
            else:
                value = self.convert(self.expression(node.value), self.function.return_type, node.span)
                self.emit("return", None, value, span=node.span)
        elif isinstance(node, N.IfStmt):
            other, end = self.label(), self.label()
            self.emit("ifz", None, self.expression(node.condition), target=other)
            self.statement(node.then_block)
            self.emit("jump", target=end)
            self.emit("label", target=other)
            if node.else_block:
                self.statement(node.else_block)
            self.emit("label", target=end)
        elif isinstance(node, (N.WhileStmt, N.DoWhileStmt, N.ForStmt)):
            self.loop(node)
        elif isinstance(node, N.ForEachStmt):
            self.foreach(node)
        elif isinstance(node, N.SwitchStmt):
            self.switch(node)
        elif isinstance(node, N.BreakStmt):
            self.emit("jump", target=self.breaks[-1])
        elif isinstance(node, N.ContinueStmt):
            self.emit("jump", target=self.continues[-1])
        else:
            raise CodegenError(f"El backend MIPS no admite {node.kind} en esta fase.", node.span)

    def loop(self, node: N.WhileStmt | N.DoWhileStmt | N.ForStmt) -> None:
        start, update, end = self.label(), self.label(), self.label()
        if isinstance(node, N.ForStmt) and node.initializer:
            self.statement(node.initializer)
        self.emit("label", target=start)
        if not isinstance(node, N.DoWhileStmt) and node.condition is not None:
            self.emit("ifz", None, self.expression(node.condition), target=end)
        self.breaks.append(end)
        self.continues.append(update)
        if node.body:
            self.statement(node.body)
        self.continues.pop()
        self.breaks.pop()
        self.emit("label", target=update)
        if isinstance(node, N.ForStmt) and node.update:
            self.expression(node.update)
        if isinstance(node, N.DoWhileStmt):
            self.emit("ifz", None, self.expression(node.condition), target=end)
        self.emit("jump", target=start)
        self.emit("label", target=end)

    def foreach(self, node: N.ForEachStmt) -> None:
        array = self.expression(node.iterable)
        length, index = self.temp(INTEGER), self.temp(INTEGER)
        self.emit("length", length, array)
        self.emit("copy", index, Constant(0, INTEGER))
        symbol = next(s for scope in self.table.all_scopes for s in scope.symbols.values()
                      if isinstance(s, VariableSymbol) and s.name == node.variable and s.span == node.span)
        variable = self.variable(symbol)
        start, update, end = self.label(), self.label(), self.label()
        self.emit("label", target=start)
        test = self.temp(BOOLEAN)
        self.emit("<", test, index, length)
        self.emit("ifz", None, test, target=end)
        self.emit("load_index", variable, array, index)
        self.breaks.append(end)
        self.continues.append(update)
        self.statement(node.body)
        self.continues.pop()
        self.breaks.pop()
        self.emit("label", target=update)
        self.emit("+", index, index, Constant(1, INTEGER))
        self.emit("jump", target=start)
        self.emit("label", target=end)

    def switch(self, node: N.SwitchStmt) -> None:
        subject = self.expression(node.subject)
        end = self.label()
        labels = [self.label() for _ in node.cases]
        default = self.label() if node.default_case else end
        for case, label in zip(node.cases, labels):
            value = self.expression(case.test)
            subject_cmp, value = self.numeric_pair(subject, value, case.span)
            test, following = self.temp(BOOLEAN), self.label()
            self.emit("==", test, subject_cmp, value)
            self.emit("ifz", None, test, target=following)
            self.emit("jump", target=label)
            self.emit("label", target=following)
        self.emit("jump", target=default)
        self.breaks.append(end)
        for case, label in zip(node.cases, labels):
            self.emit("label", target=label)
            for statement in case.statements:
                self.statement(statement)
        if node.default_case:
            self.emit("label", target=default)
            for statement in node.default_case.statements:
                self.statement(statement)
        self.breaks.pop()
        self.emit("label", target=end)

    def assignment(self, target: N.Expression, expression: N.Expression, span: N.SourceSpan) -> Operand:
        if isinstance(target, N.Identifier):
            assert isinstance(target.resolved_symbol, VariableSymbol)
            dest = self.variable(target.resolved_symbol)
            value = self.convert(self.expression(expression), dest.type, span)
            self.emit("copy", dest, value, span=span)
            return value
        if isinstance(target, N.IndexExpr):
            array, index = self.expression(target.target), self.expression(target.index)
            assert isinstance(array.type, ArrayType)
            value = self.convert(self.expression(expression), array.type.element, span)
            self.emit("store_index", None, array, index, value, span=span)
            return value
        raise CodegenError("Asignacion a propiedades no implementada en MIPS.", span)

    def numeric_pair(self, left: Operand, right: Operand, span: N.SourceSpan) -> tuple[Operand, Operand]:
        if FLOAT in (left.type, right.type):
            return self.convert(left, FLOAT, span), self.convert(right, FLOAT, span)
        return left, right

    def expression(self, node: N.Expression) -> Operand:
        type_ = node.resolved_type
        assert type_ is not None
        if isinstance(node, (N.IntegerLiteral, N.FloatLiteral, N.StringLiteral, N.BooleanLiteral)):
            if isinstance(node, N.IntegerLiteral) and not -(2**31) <= node.value < 2**31:
                raise CodegenError("El entero no cabe en 32 bits con signo.", node.span)
            if isinstance(node, N.FloatLiteral) and (not math.isfinite(node.value) or abs(node.value) > 3.402823466e38):
                raise CodegenError("El float no cabe en precision simple MIPS.", node.span)
            if isinstance(node, N.StringLiteral) and "\0" in node.value:
                raise CodegenError("Las cadenas MIPS no admiten caracteres NUL internos.", node.span)
            return Constant(node.value, type_)
        if isinstance(node, N.NullLiteral):
            return Constant(None, NULL)
        if isinstance(node, N.Identifier):
            if not isinstance(node.resolved_symbol, VariableSymbol):
                raise CodegenError("Solo se admiten llamadas directas a funciones; no valores de funcion.", node.span)
            # Congelar lecturas antes de evaluar operandos con efectos laterales.
            result = self.temp(type_)
            self.emit("copy", result, self.variable(node.resolved_symbol), span=node.span)
            return result
        if isinstance(node, N.UnaryExpr):
            if node.operator == "-" and isinstance(node.operand, N.IntegerLiteral) and node.operand.value == 2**31:
                return Constant(-(2**31), INTEGER)
            value = self.expression(node.operand)
            if node.operator == "+":
                return value
            result = self.temp(type_)
            self.emit("neg" if node.operator == "-" else "!", result, value, span=node.span)
            return result
        if isinstance(node, N.BinaryExpr):
            if node.operator in ("&&", "||"):
                return self.short_circuit(node)
            left, right = self.expression(node.left), self.expression(node.right)
            result = self.temp(type_)
            if node.operator == "+" and type_ == STRING:
                left, right = self.stringify(left, node.span), self.stringify(right, node.span)
                self.emit("concat", result, left, right, span=node.span)
            else:
                left, right = self.numeric_pair(left, right, node.span)
                if node.operator == "%" and left.type == FLOAT:
                    raise CodegenError("El modulo MIPS de esta fase requiere operandos integer.", node.span)
                self.emit(node.operator, result, left, right, span=node.span)
            return result
        if isinstance(node, N.TernaryExpr):
            result, other, end = self.temp(type_), self.label(), self.label()
            self.emit("ifz", None, self.expression(node.condition), target=other)
            self.emit("copy", result, self.convert(self.expression(node.then_expr), type_, node.span))
            self.emit("jump", target=end)
            self.emit("label", target=other)
            self.emit("copy", result, self.convert(self.expression(node.else_expr), type_, node.span))
            self.emit("label", target=end)
            return result
        if isinstance(node, N.AssignExpr):
            return self.assignment(node.target, node.value, node.span)
        if isinstance(node, N.CallExpr):
            if not isinstance(node.callee, N.Identifier) or not isinstance(node.callee.resolved_symbol, FunctionSymbol):
                raise CodegenError("El backend MIPS admite llamadas directas a funciones globales.", node.span)
            symbol = node.callee.resolved_symbol
            if symbol.enclosing_function is not None:
                raise CodegenError("El backend MIPS no admite closures ni funciones anidadas.", node.span)
            args = [self.convert(self.expression(arg), parameter.type, arg.span)
                    for arg, parameter in zip(node.arguments, symbol.parameters)]
            result = self.temp(type_) if type_ != VOID else None
            self.emit("call", result, *args, target=self.function_names[id(symbol)], span=node.span)
            return result if result is not None else Constant(0, VOID)
        if isinstance(node, N.ArrayLiteral):
            assert isinstance(type_, ArrayType)
            result = self.temp(type_)
            self.emit("new_array", result, Constant(len(node.elements), INTEGER), span=node.span)
            for index, element in enumerate(node.elements):
                value = self.convert(self.expression(element), type_.element, element.span)
                self.emit("store_index", None, result, Constant(index, INTEGER), value, span=element.span)
            return result
        if isinstance(node, N.IndexExpr):
            array, index = self.expression(node.target), self.expression(node.index)
            result = self.temp(type_)
            self.emit("load_index", result, array, index, span=node.span)
            return result
        raise CodegenError(f"El backend MIPS no admite la expresion {node.kind}.", node.span)

    def stringify(self, value: Operand, span: N.SourceSpan) -> Operand:
        if value.type == STRING:
            return value
        if value.type not in (INTEGER, BOOLEAN, NULL):
            raise CodegenError("La concatenacion MIPS admite string, integer, boolean y null; use print para float.", span)
        result = self.temp(STRING)
        self.emit("to_string", result, value, span=span)
        return result

    def short_circuit(self, node: N.BinaryExpr) -> Operand:
        result, other, end = self.temp(BOOLEAN), self.label(), self.label()
        left = self.expression(node.left)
        self.emit("ifz", None, left, target=other)
        if node.operator == "&&":
            self.emit("copy", result, self.expression(node.right))
        else:
            self.emit("copy", result, Constant(True, BOOLEAN))
        self.emit("jump", target=end)
        self.emit("label", target=other)
        if node.operator == "&&":
            self.emit("copy", result, Constant(False, BOOLEAN))
        else:
            self.emit("copy", result, self.expression(node.right))
        self.emit("label", target=end)
        return result


def generate_ir(ast: N.Program, table: SymbolTable) -> IRProgram:
    return IRGenerator(table).generate(ast)
