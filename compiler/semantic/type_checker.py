"""Verificacion de cuerpos: ambitos, tipos y reglas semanticas por sentencia.

Esta es la pasada principal. Recorre el AST propio construyendo los ambitos
anidados, resolviendo identificadores, tipando cada expresion y acumulando
diagnosticos. Los cuerpos de funciones y metodos se difieren al final del
ambito que los contiene para que puedan ver todas las declaraciones hermanas
(recursion mutua, closures y uso de variables globales).
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator, Optional, Sequence

from ..ast import nodes as N
from ..symbols.scope import Scope, ScopeKind
from ..symbols.symbols import (
    ClassSymbol,
    FunctionSymbol,
    Symbol,
    SymbolCategory,
    VariableSymbol,
)
from ..symbols.table import SymbolTable
from ..types import compatibility as compat
from ..types.types import (
    BOOLEAN,
    ERROR,
    FLOAT,
    INTEGER,
    NULL,
    STRING,
    VOID,
    ArrayType,
    ClassType,
    FunctionType,
    Type,
)
from .declarations import DeclarationCollector
from .diagnostics import Code, DiagnosticBag
from .type_resolver import TypeResolver

#: Tipo semantico del identificador de `catch`. Ver docs/semantic-decisions.md.
CATCH_ERROR_TYPE: Type = STRING

_ARITHMETIC_OPERATORS = ("-", "*", "/", "%")
_LOGICAL_OPERATORS = ("&&", "||")


@dataclass
class _PendingBody:
    """Cuerpo cuyo analisis se difiere al cierre del ambito que lo contiene."""

    node: N.Statement
    scope: Scope


@dataclass
class _FunctionContext:
    """Estado del analisis dentro de una funcion o metodo."""

    symbol: FunctionSymbol
    scope: Scope
    returned: list[tuple[Type, N.SourceSpan]] = field(default_factory=list)


class TypeChecker:
    """Comprueba ambitos, tipos y reglas semanticas sobre el AST."""

    def __init__(
        self,
        table: SymbolTable,
        diagnostics: DiagnosticBag,
        resolver: TypeResolver,
        collector: DeclarationCollector,
    ) -> None:
        self._table = table
        self._diagnostics = diagnostics
        self._resolver = resolver
        self._collector = collector
        self._functions: list[_FunctionContext] = []
        self._classes: list[ClassSymbol] = []

    # --- utilidades de ambito --------------------------------------------

    @contextmanager
    def _scope(self, name: str, kind: ScopeKind) -> Iterator[Scope]:
        scope = self._table.push_scope(name, kind)
        try:
            yield scope
        finally:
            self._table.pop_scope()

    @contextmanager
    def _in_scope(self, scope: Scope) -> Iterator[Scope]:
        """Reentra en un ambito ya creado (p. ej. el ambito de una clase)."""
        previous = self._table.current
        self._table.current = scope
        try:
            yield scope
        finally:
            self._table.current = previous

    @property
    def _current_function(self) -> Optional[_FunctionContext]:
        return self._functions[-1] if self._functions else None

    @property
    def _current_class(self) -> Optional[ClassSymbol]:
        return self._classes[-1] if self._classes else None

    # --- programa ---------------------------------------------------------

    def check_program(self, program: N.Program) -> None:
        # Las funciones y clases globales ya fueron registradas por
        # DeclarationCollector, por eso no se vuelven a hoistear aqui.
        self._check_statements(program.statements, hoist=False)

    def _check_statements(self, statements: Sequence[N.Statement], hoist: bool = True) -> None:
        if hoist:
            self._collector.hoist_functions(statements, self._table.current)

        pending: list[_PendingBody] = []
        for statement in statements:
            if isinstance(statement, (N.FunctionDecl, N.ClassDecl)):
                pending.append(_PendingBody(statement, self._table.current))
                continue
            self._check_statement(statement)

        # Los cuerpos se analizan al final para que vean todas las
        # declaraciones del ambito, incluidas las posteriores.
        for item in pending:
            with self._in_scope(item.scope):
                if isinstance(item.node, N.FunctionDecl):
                    self._check_function_body(item.node)
                else:
                    self._check_class_body(item.node)  # type: ignore[arg-type]

    # --- sentencias -------------------------------------------------------

    def _check_statement(self, statement: N.Statement) -> None:
        handlers = {
            N.VarDecl: self._check_var_decl,
            N.AssignStmt: self._check_assign_stmt,
            N.Block: self._check_block,
            N.IfStmt: self._check_if,
            N.WhileStmt: self._check_while,
            N.DoWhileStmt: self._check_do_while,
            N.ForStmt: self._check_for,
            N.ForEachStmt: self._check_foreach,
            N.SwitchStmt: self._check_switch,
            N.TryCatchStmt: self._check_try_catch,
            N.BreakStmt: self._check_break,
            N.ContinueStmt: self._check_continue,
            N.ReturnStmt: self._check_return,
            N.PrintStmt: self._check_print,
            N.ExpressionStmt: self._check_expression_statement,
        }
        handler = handlers.get(type(statement))
        if handler is not None:
            handler(statement)  # type: ignore[operator]
        elif isinstance(statement, (N.FunctionDecl, N.ClassDecl)):
            # Alcanzable solo si aparecen anidadas en un contexto no manejado.
            self._check_statements([statement])

    def _check_block(self, block: N.Block) -> None:
        with self._scope("block", ScopeKind.BLOCK):
            self._check_statements(block.statements)

    def _check_block_in_current_scope(self, block: N.Block) -> None:
        """Analiza las sentencias de un bloque sin crear un ambito extra."""
        self._check_statements(block.statements)

    # --- declaraciones ----------------------------------------------------

    def _check_var_decl(self, declaration: N.VarDecl) -> None:
        declared: Optional[Type] = None
        if declaration.declared_type is not None:
            declared = self._resolver.resolve(declaration.declared_type)
            if compat.is_void(declared):
                self._diagnostics.report(
                    Code.VOID_AS_VALUE,
                    f"No se puede declarar '{declaration.name}' con tipo 'void'.",
                    declaration.span,
                )
                declared = ERROR

        if declaration.is_const and declaration.initializer is None:
            self._diagnostics.report(
                Code.CONST_WITHOUT_INITIALIZER,
                f"La constante '{declaration.name}' debe inicializarse en su declaracion.",
                declaration.span,
            )

        initializer_type: Optional[Type] = None
        if declaration.initializer is not None:
            initializer_type = self._check_expression(declaration.initializer)
            initializer_type = self._require_value(initializer_type, declaration.initializer.span)

        final_type = self._resolve_declaration_type(declaration, declared, initializer_type)
        declaration.resolved_type = final_type

        symbol = VariableSymbol(
            name=declaration.name,
            category=SymbolCategory.CONSTANT if declaration.is_const else SymbolCategory.VARIABLE,
            type=final_type,
            span=declaration.span,
            ast_node=declaration,
            mutable=not declaration.is_const,
            initialized=declaration.initializer is not None,
            array_length=_literal_array_length(declaration.initializer),
        )
        if not self._table.declare(symbol):
            self._diagnostics.report(
                Code.DUPLICATE_DECLARATION,
                f"'{declaration.name}' ya esta declarado en este ambito.",
                declaration.span,
            )

    def _resolve_declaration_type(
        self,
        declaration: N.VarDecl,
        declared: Optional[Type],
        initializer_type: Optional[Type],
    ) -> Type:
        if declared is not None:
            if initializer_type is not None and not self._assignable_expression(
                declaration.initializer, initializer_type, declared
            ):
                self._diagnostics.report(
                    Code.INCOMPATIBLE_ASSIGNMENT,
                    f"Asignacion incompatible en '{declaration.name}': se esperaba "
                    f"'{declared.name}' y se recibio '{initializer_type.name}'.",
                    declaration.initializer.span if declaration.initializer else declaration.span,
                    expected=declared,
                    actual=initializer_type,
                )
            if declaration.initializer is not None:
                # Un literal vacio adopta el tipo declarado.
                declaration.initializer.resolved_type = declared
            return declared

        if initializer_type is None:
            self._diagnostics.report(
                Code.CANNOT_INFER_TYPE,
                f"No se puede inferir el tipo de '{declaration.name}': agregue una "
                "anotacion de tipo o un inicializador.",
                declaration.span,
            )
            return ERROR

        if compat.is_unknown(initializer_type):
            self._diagnostics.report(
                Code.UNRESOLVED_EMPTY_ARRAY,
                f"No se puede inferir el tipo de '{declaration.name}' a partir de un "
                "arreglo vacio; agregue una anotacion de tipo.",
                declaration.span,
            )
            return ERROR

        if compat.is_null(initializer_type):
            self._diagnostics.report(
                Code.CANNOT_INFER_TYPE,
                f"No se puede inferir el tipo de '{declaration.name}' a partir de 'null'; "
                "agregue una anotacion de tipo.",
                declaration.span,
            )
            return ERROR

        return initializer_type

    # --- asignaciones -----------------------------------------------------

    def _check_assign_stmt(self, statement: N.AssignStmt) -> None:
        self._check_assignment(statement.target, statement.value, statement.span)

    def _check_assignment(
        self, target: N.Expression, value: N.Expression, span: N.SourceSpan
    ) -> Type:
        value_type = self._require_value(self._check_expression(value), value.span)

        if isinstance(target, N.Identifier):
            target_type = self._check_identifier_assignment(target, value_type, value)
        elif isinstance(target, N.PropertyAccess):
            target_type = self._check_property_assignment(target, value_type, value)
        elif isinstance(target, N.IndexExpr):
            target_type = self._check_index_assignment(target, value_type, value)
        else:
            self._diagnostics.report(
                Code.INVALID_ASSIGNMENT_TARGET,
                "El destino de la asignacion no es asignable.",
                target.span,
            )
            target_type = ERROR

        target.resolved_type = target_type
        return value_type

    def _check_identifier_assignment(
        self, target: N.Identifier, value_type: Type, value: N.Expression
    ) -> Type:
        symbol = self._table.resolve(target.name)
        if symbol is None:
            self._diagnostics.report(
                Code.ASSIGN_TO_UNDECLARED,
                f"No se puede asignar a '{target.name}': no esta declarado.",
                target.span,
            )
            return ERROR

        target.resolved_symbol = symbol
        if isinstance(symbol, (FunctionSymbol, ClassSymbol)):
            self._diagnostics.report(
                Code.INVALID_ASSIGNMENT_TARGET,
                f"'{target.name}' es una {symbol.category} y no puede reasignarse.",
                target.span,
            )
            return ERROR

        assert isinstance(symbol, VariableSymbol)
        if not symbol.mutable:
            self._diagnostics.report(
                Code.CONST_REASSIGNMENT,
                f"No se puede reasignar la constante '{target.name}'.",
                target.span,
            )
            return symbol.type

        self._check_assignable(value_type, symbol.type, target.name, target.span, value)
        symbol.initialized = True
        # La longitud estatica deja de conocerse tras una reasignacion.
        symbol.array_length = None
        return symbol.type

    def _check_property_assignment(
        self, target: N.PropertyAccess, value_type: Type, value: N.Expression
    ) -> Type:
        object_type = self._check_expression(target.target)
        member_type = self._resolve_member_type(object_type, target.name, target.span)
        if compat.is_error(member_type):
            return ERROR

        owner = object_type.class_name if isinstance(object_type, ClassType) else None
        if owner is not None:
            field_symbol = self._table.classes.lookup_field(owner, target.name)
            if field_symbol is not None and not field_symbol.mutable:
                self._diagnostics.report(
                    Code.CONST_REASSIGNMENT,
                    f"No se puede reasignar la constante '{owner}.{target.name}'.",
                    target.span,
                )
                return member_type
            if field_symbol is None:
                self._diagnostics.report(
                    Code.INVALID_ASSIGNMENT_TARGET,
                    f"'{target.name}' es un metodo de '{owner}' y no puede reasignarse.",
                    target.span,
                )
                return ERROR
            field_symbol.initialized = True

        self._check_assignable(value_type, member_type, target.name, target.span, value)
        return member_type

    def _check_index_assignment(
        self, target: N.IndexExpr, value_type: Type, value: N.Expression
    ) -> Type:
        element_type = self._check_index_expression(target)
        if compat.is_error(element_type):
            return ERROR
        self._check_assignable(
            value_type, element_type, "elemento del arreglo", target.span, value
        )
        return element_type

    def _check_assignable(
        self,
        source: Type,
        target: Type,
        name: str,
        span: N.SourceSpan,
        expression: Optional[N.Expression] = None,
    ) -> None:
        if self._assignable_expression(expression, source, target):
            return
        self._diagnostics.report(
            Code.INCOMPATIBLE_ASSIGNMENT,
            f"Asignacion incompatible en '{name}': se esperaba '{target.name}' y se "
            f"recibio '{source.name}'.",
            span,
            expected=target,
            actual=source,
        )

    def _assignable_expression(
        self,
        expression: Optional[N.Expression],
        source: Type,
        target: Type,
    ) -> bool:
        """Asignabilidad con tipado contextual de literales de arreglo.

        Los arreglos son invariantes, pero un literal escrito en el lugar de la
        asignacion puede adoptar el tipo destino si cada elemento encaja: asi
        `let x: float[] = [1, 2];` es valido sin abrir la puerta a la
        covarianza entre variables de tipo arreglo.
        """
        if compat.is_assignable(source, target, self._table.classes):
            return True
        if isinstance(expression, N.ArrayLiteral) and isinstance(target, ArrayType):
            for element in expression.elements:
                element_type = element.resolved_type or ERROR
                if not self._assignable_expression(element, element_type, target.element):
                    return False
            expression.resolved_type = target
            return True
        return False

    # --- funciones --------------------------------------------------------

    def _check_function_body(self, declaration: N.FunctionDecl) -> None:
        symbol = self._table.current.lookup_local(declaration.name)
        if not isinstance(symbol, FunctionSymbol):
            return  # hubo un error de declaracion; no se analiza el cuerpo
        self._analyze_callable(declaration, symbol, ScopeKind.FUNCTION)

    def _analyze_callable(
        self,
        declaration: N.FunctionDecl,
        symbol: FunctionSymbol,
        kind: ScopeKind,
    ) -> None:
        scope_name = (
            f"{symbol.owner_class}.{declaration.name}"
            if symbol.owner_class
            else declaration.name
        )
        with self._scope(scope_name, kind) as scope:
            symbol.body_scope = scope
            for parameter in symbol.parameters:
                scope.declare(
                    VariableSymbol(
                        name=parameter.name,
                        category=SymbolCategory.PARAMETER,
                        type=parameter.type,
                        span=parameter.span,
                        mutable=True,
                        initialized=True,
                    )
                )

            context = _FunctionContext(symbol=symbol, scope=scope)
            self._functions.append(context)
            try:
                if declaration.body is not None:
                    self._check_statements(declaration.body.statements)
            finally:
                self._functions.pop()

            self._finalize_return_type(declaration, symbol, context)

    def _finalize_return_type(
        self,
        declaration: N.FunctionDecl,
        symbol: FunctionSymbol,
        context: _FunctionContext,
    ) -> None:
        if symbol.return_type_inferred and compat.is_unknown(symbol.return_type):
            symbol.return_type = self._merge_returns(context)
        symbol.refresh_type()

        if compat.is_void(symbol.return_type) or compat.is_error(symbol.return_type):
            return
        if declaration.body is None:
            return

        from .control_flow import ControlFlowAnalyzer

        # El analisis de caminos se hace sobre una bolsa desechable: las
        # advertencias de codigo muerto las emite la pasada dedicada.
        silent = DiagnosticBag(self._diagnostics.filename)
        if not ControlFlowAnalyzer(silent).analyze_function_body(declaration.body):
            self._diagnostics.report(
                Code.MISSING_RETURN,
                f"La funcion '{declaration.name}' declara el tipo de retorno "
                f"'{symbol.return_type.name}' pero existe al menos un camino que "
                "termina sin retornar un valor.",
                declaration.span,
                expected=symbol.return_type,
            )

    def _merge_returns(self, context: _FunctionContext) -> Type:
        if not context.returned:
            return VOID
        result = context.returned[0][0]
        for current, span in context.returned[1:]:
            merged = compat.common_type(result, current, self._table.classes)
            if merged is None:
                self._diagnostics.report(
                    Code.INCOMPATIBLE_RETURN,
                    f"Los 'return' de la funcion devuelven tipos incompatibles: "
                    f"'{result.name}' y '{current.name}'.",
                    span,
                    expected=result,
                    actual=current,
                )
                return ERROR
            result = merged
        return result

    def _check_return(self, statement: N.ReturnStmt) -> None:
        context = self._current_function
        if context is None:
            self._diagnostics.report(
                Code.RETURN_OUTSIDE_FUNCTION,
                "'return' solo puede utilizarse dentro de una funcion o metodo.",
                statement.span,
            )
            if statement.value is not None:
                self._check_expression(statement.value)
            return

        symbol = context.symbol
        if statement.value is None:
            if not compat.is_void(symbol.return_type) and not symbol.return_type_inferred:
                self._diagnostics.report(
                    Code.INCOMPATIBLE_RETURN,
                    f"'return' sin valor en la funcion '{symbol.name}', que declara el "
                    f"tipo de retorno '{symbol.return_type.name}'.",
                    statement.span,
                    expected=symbol.return_type,
                    actual=VOID,
                )
            return

        value_type = self._require_value(
            self._check_expression(statement.value), statement.value.span
        )

        if symbol.category is SymbolCategory.CONSTRUCTOR:
            self._diagnostics.report(
                Code.RETURN_VALUE_IN_VOID,
                "El constructor no puede devolver un valor.",
                statement.span,
            )
            return

        if symbol.return_type_inferred:
            context.returned.append((value_type, statement.span))
            if compat.is_void(symbol.return_type):
                symbol.return_type = value_type
                symbol.refresh_type()
            return

        if compat.is_void(symbol.return_type):
            self._diagnostics.report(
                Code.RETURN_VALUE_IN_VOID,
                f"La funcion '{symbol.name}' es 'void' y no puede devolver un valor.",
                statement.span,
                expected=VOID,
                actual=value_type,
            )
            return

        if not self._assignable_expression(statement.value, value_type, symbol.return_type):
            self._diagnostics.report(
                Code.INCOMPATIBLE_RETURN,
                f"Tipo de retorno incompatible en '{symbol.name}': se esperaba "
                f"'{symbol.return_type.name}' y se recibio '{value_type.name}'.",
                statement.span,
                expected=symbol.return_type,
                actual=value_type,
            )

    # --- clases -----------------------------------------------------------

    def _check_class_body(self, declaration: N.ClassDecl) -> None:
        class_symbol = self._table.classes.get(declaration.name)
        if class_symbol is None or class_symbol.class_scope is None:
            return

        self._classes.append(class_symbol)
        try:
            with self._in_scope(class_symbol.class_scope):
                for member in declaration.members:
                    if isinstance(member, N.VarDecl):
                        self._check_field_initializer(class_symbol, member)
                for member in declaration.members:
                    if isinstance(member, N.FunctionDecl):
                        self._check_method_body(class_symbol, member)
        finally:
            self._classes.pop()

    def _check_field_initializer(self, class_symbol: ClassSymbol, member: N.VarDecl) -> None:
        if member.initializer is None:
            return
        value_type = self._require_value(
            self._check_expression(member.initializer), member.initializer.span
        )
        field_symbol = class_symbol.fields.get(member.name)
        if field_symbol is None:
            return
        self._check_assignable(
            value_type, field_symbol.type, member.name, member.initializer.span,
            member.initializer,
        )

    def _check_method_body(self, class_symbol: ClassSymbol, member: N.FunctionDecl) -> None:
        if member.name == "constructor":
            symbol = class_symbol.constructor
        else:
            symbol = class_symbol.methods.get(member.name)
        if symbol is None:
            return
        self._analyze_callable(member, symbol, ScopeKind.METHOD)

    # --- control de flujo -------------------------------------------------

    def _check_condition(self, expression: N.Expression, keyword: str) -> None:
        condition_type = self._check_expression(expression)
        if compat.is_indeterminate(condition_type):
            return
        if not compat.is_boolean(condition_type):
            self._diagnostics.report(
                Code.NON_BOOLEAN_CONDITION,
                f"La condicion de '{keyword}' debe ser 'boolean' y se recibio "
                f"'{condition_type.name}'.",
                expression.span,
                expected=BOOLEAN,
                actual=condition_type,
            )

    def _check_if(self, statement: N.IfStmt) -> None:
        self._check_condition(statement.condition, "if")
        self._check_block(statement.then_block)
        if statement.else_block is not None:
            self._check_block(statement.else_block)

    def _check_while(self, statement: N.WhileStmt) -> None:
        self._check_condition(statement.condition, "while")
        with self._scope("while", ScopeKind.LOOP):
            self._check_block_in_current_scope(statement.body)

    def _check_do_while(self, statement: N.DoWhileStmt) -> None:
        with self._scope("do-while", ScopeKind.LOOP):
            self._check_block_in_current_scope(statement.body)
        self._check_condition(statement.condition, "do-while")

    def _check_for(self, statement: N.ForStmt) -> None:
        with self._scope("for", ScopeKind.LOOP):
            if statement.initializer is not None:
                self._check_statement(statement.initializer)
            if statement.condition is not None:
                self._check_condition(statement.condition, "for")
            if statement.update is not None:
                self._check_expression(statement.update)
            if statement.body is not None:
                self._check_block_in_current_scope(statement.body)

    def _check_foreach(self, statement: N.ForEachStmt) -> None:
        iterable_type = self._check_expression(statement.iterable)
        element_type: Type = ERROR
        if isinstance(iterable_type, ArrayType):
            element_type = iterable_type.element
        elif not compat.is_indeterminate(iterable_type):
            self._diagnostics.report(
                Code.FOREACH_NOT_ITERABLE,
                f"'foreach' requiere un arreglo y se recibio '{iterable_type.name}'.",
                statement.iterable.span,
                actual=iterable_type,
            )
        statement.element_type = element_type

        with self._scope("foreach", ScopeKind.LOOP) as scope:
            scope.declare(
                VariableSymbol(
                    name=statement.variable,
                    category=SymbolCategory.VARIABLE,
                    type=element_type,
                    span=statement.span,
                    mutable=True,
                    initialized=True,
                )
            )
            self._check_block_in_current_scope(statement.body)

    def _check_switch(self, statement: N.SwitchStmt) -> None:
        subject_type = self._check_expression(statement.subject)
        if not compat.is_indeterminate(subject_type) and not _is_switchable(subject_type):
            self._diagnostics.report(
                Code.INVALID_SWITCH_SUBJECT,
                f"La expresion de 'switch' debe tener un tipo comparable y se recibio "
                f"'{subject_type.name}'.",
                statement.subject.span,
                actual=subject_type,
            )
            # Se degrada a 'error' para no encadenar un SEM043 por cada 'case'.
            subject_type = ERROR

        seen_literals: dict[object, N.SourceSpan] = {}
        with self._scope("switch", ScopeKind.SWITCH):
            for case in statement.cases:
                case_type = self._check_expression(case.test)
                if not compat.is_indeterminate(subject_type) and not compat.is_comparable(
                    case_type, subject_type, "==", self._table.classes
                ):
                    self._diagnostics.report(
                        Code.INCOMPATIBLE_CASE,
                        f"El 'case' tiene tipo '{case_type.name}', incompatible con el tipo "
                        f"'{subject_type.name}' de la expresion del 'switch'.",
                        case.test.span,
                        expected=subject_type,
                        actual=case_type,
                    )

                literal = _literal_value(case.test)
                if literal is not None:
                    if literal in seen_literals:
                        original = seen_literals[literal]
                        self._diagnostics.report(
                            Code.DUPLICATE_CASE,
                            f"El valor de 'case' {literal[1]!r} ya aparece en la linea "
                            f"{original.line}.",
                            case.test.span,
                        )
                    else:
                        seen_literals[literal] = case.test.span

                with self._scope("case", ScopeKind.BLOCK):
                    self._check_statements(case.statements)

            if statement.default_case is not None:
                with self._scope("default", ScopeKind.BLOCK):
                    self._check_statements(statement.default_case.statements)

    def _check_try_catch(self, statement: N.TryCatchStmt) -> None:
        with self._scope("try", ScopeKind.BLOCK):
            self._check_block_in_current_scope(statement.try_block)

        with self._scope("catch", ScopeKind.CATCH) as scope:
            scope.declare(
                VariableSymbol(
                    name=statement.error_name,
                    category=SymbolCategory.VARIABLE,
                    type=CATCH_ERROR_TYPE,
                    span=statement.error_span or statement.span,
                    mutable=False,
                    initialized=True,
                )
            )
            self._check_block_in_current_scope(statement.catch_block)

    def _check_break(self, statement: N.BreakStmt) -> None:
        if not self._table.current.is_inside_breakable():
            self._diagnostics.report(
                Code.BREAK_OUTSIDE_LOOP,
                "'break' solo puede utilizarse dentro de un bucle o de un 'switch'.",
                statement.span,
            )

    def _check_continue(self, statement: N.ContinueStmt) -> None:
        if not self._table.current.is_inside_loop():
            self._diagnostics.report(
                Code.CONTINUE_OUTSIDE_LOOP,
                "'continue' solo puede utilizarse dentro de un bucle.",
                statement.span,
            )

    def _check_print(self, statement: N.PrintStmt) -> None:
        self._require_value(self._check_expression(statement.value), statement.value.span)

    def _check_expression_statement(self, statement: N.ExpressionStmt) -> None:
        self._check_expression(statement.expression)

    # --- expresiones ------------------------------------------------------

    def _check_expression(self, expression: N.Expression) -> Type:
        result = self._dispatch_expression(expression)
        expression.resolved_type = result
        return result

    def _dispatch_expression(self, expression: N.Expression) -> Type:
        if isinstance(expression, N.IntegerLiteral):
            return INTEGER
        if isinstance(expression, N.FloatLiteral):
            return FLOAT
        if isinstance(expression, N.StringLiteral):
            return STRING
        if isinstance(expression, N.BooleanLiteral):
            return BOOLEAN
        if isinstance(expression, N.NullLiteral):
            return NULL
        if isinstance(expression, N.ArrayLiteral):
            return self._check_array_literal(expression)
        if isinstance(expression, N.Identifier):
            return self._check_identifier(expression)
        if isinstance(expression, N.ThisExpr):
            return self._check_this(expression)
        if isinstance(expression, N.NewExpr):
            return self._check_new(expression)
        if isinstance(expression, N.CallExpr):
            return self._check_call(expression)
        if isinstance(expression, N.IndexExpr):
            return self._check_index_expression(expression)
        if isinstance(expression, N.PropertyAccess):
            return self._check_property_access(expression)
        if isinstance(expression, N.UnaryExpr):
            return self._check_unary(expression)
        if isinstance(expression, N.BinaryExpr):
            return self._check_binary(expression)
        if isinstance(expression, N.TernaryExpr):
            return self._check_ternary(expression)
        if isinstance(expression, N.AssignExpr):
            return self._check_assignment(expression.target, expression.value, expression.span)
        return ERROR  # pragma: no cover - todas las formas estan cubiertas

    def _check_array_literal(self, expression: N.ArrayLiteral) -> Type:
        element_types = [self._check_expression(item) for item in expression.elements]
        for item, item_type in zip(expression.elements, element_types):
            self._require_value(item_type, item.span)
        element = compat.common_array_element_type(element_types, self._table.classes)
        if element is None:
            self._diagnostics.report(
                Code.HETEROGENEOUS_ARRAY,
                "Los elementos del arreglo no tienen un tipo comun: "
                + compat.describe(element_types)
                + ".",
                expression.span,
            )
            return ERROR
        return ArrayType(element)

    def _check_identifier(self, expression: N.Identifier) -> Type:
        symbol, declaring_scope = self._table.resolve_with_scope(expression.name)
        if symbol is None:
            self._diagnostics.report(
                Code.UNDECLARED_IDENTIFIER,
                f"Identificador no declarado: '{expression.name}'.",
                expression.span,
            )
            return ERROR

        expression.resolved_symbol = symbol
        if isinstance(symbol, ClassSymbol):
            self._diagnostics.report(
                Code.NOT_A_VALUE,
                f"'{expression.name}' es una clase y no puede usarse como valor.",
                expression.span,
            )
            return ERROR

        if declaring_scope is not None:
            self._record_capture(symbol, declaring_scope)

        if isinstance(symbol, FunctionSymbol):
            return FunctionType(symbol.parameter_types, symbol.return_type)

        assert isinstance(symbol, VariableSymbol)
        if not symbol.initialized and symbol.category in (
            SymbolCategory.VARIABLE,
            SymbolCategory.CONSTANT,
        ):
            self._diagnostics.report(
                Code.USE_BEFORE_INITIALIZATION,
                f"La variable '{expression.name}' se usa antes de inicializarse.",
                expression.span,
            )
        return symbol.type

    def _record_capture(self, symbol: Symbol, declaring_scope: Scope) -> None:
        """Registra la captura de una variable de un ambito externo (closure)."""
        context = self._current_function
        if context is None:
            return
        if declaring_scope.kind is ScopeKind.GLOBAL:
            return  # las globales no se consideran capturas
        if declaring_scope.enclosing_function_scope() is context.scope:
            return  # pertenece a la funcion actual
        if not isinstance(symbol, VariableSymbol):
            return
        symbol.captured = True
        if symbol.name not in context.symbol.captures:
            context.symbol.captures.append(symbol.name)

    def _check_this(self, expression: N.ThisExpr) -> Type:
        current = self._current_class
        if current is None:
            self._diagnostics.report(
                Code.THIS_OUTSIDE_CLASS,
                "'this' solo puede utilizarse dentro de una clase.",
                expression.span,
            )
            return ERROR
        return ClassType(current.name)

    def _check_new(self, expression: N.NewExpr) -> Type:
        symbol = self._table.resolve(expression.class_name)
        class_symbol = self._table.classes.get(expression.class_name)
        if class_symbol is None:
            if symbol is None:
                self._diagnostics.report(
                    Code.UNDECLARED_CLASS,
                    f"La clase '{expression.class_name}' no esta declarada.",
                    expression.span,
                )
            else:
                self._diagnostics.report(
                    Code.NEW_ON_NON_CLASS,
                    f"'new' requiere una clase y '{expression.class_name}' es una "
                    f"{symbol.category}.",
                    expression.span,
                )
            for argument in expression.arguments:
                self._check_expression(argument)
            return ERROR

        constructor = self._table.classes.lookup_constructor(expression.class_name)
        argument_types = [self._check_expression(a) for a in expression.arguments]
        if constructor is None:
            if argument_types:
                self._diagnostics.report(
                    Code.CONSTRUCTOR_MISUSE,
                    f"La clase '{expression.class_name}' no declara constructor, por lo que "
                    "no admite argumentos.",
                    expression.span,
                )
        else:
            self._check_arguments(
                constructor,
                expression.arguments,
                argument_types,
                expression.span,
                f"constructor de '{expression.class_name}'",
            )
        return ClassType(expression.class_name)

    def _check_call(self, expression: N.CallExpr) -> Type:
        callee = expression.callee

        if isinstance(callee, N.Identifier):
            return self._check_direct_call(expression, callee)
        if isinstance(callee, N.PropertyAccess):
            return self._check_method_call(expression, callee)

        callee_type = self._check_expression(callee)
        argument_types = [self._check_expression(a) for a in expression.arguments]
        if compat.is_indeterminate(callee_type):
            return ERROR
        if isinstance(callee_type, FunctionType):
            if len(argument_types) != len(callee_type.parameters):
                self._diagnostics.report(
                    Code.ARGUMENT_COUNT_MISMATCH,
                    f"La llamada esperaba {len(callee_type.parameters)} argumento(s) y "
                    f"recibio {len(argument_types)}.",
                    expression.span,
                )
            return callee_type.return_type
        self._diagnostics.report(
            Code.NOT_CALLABLE,
            f"La expresion de tipo '{callee_type.name}' no es invocable.",
            expression.span,
            actual=callee_type,
        )
        return ERROR

    def _check_direct_call(self, expression: N.CallExpr, callee: N.Identifier) -> Type:
        symbol, declaring_scope = self._table.resolve_with_scope(callee.name)
        argument_types = [self._check_expression(a) for a in expression.arguments]

        if symbol is None:
            self._diagnostics.report(
                Code.UNDECLARED_FUNCTION,
                f"La funcion '{callee.name}' no esta declarada.",
                callee.span,
            )
            return ERROR

        callee.resolved_symbol = symbol
        if isinstance(symbol, ClassSymbol):
            self._diagnostics.report(
                Code.NOT_CALLABLE,
                f"'{callee.name}' es una clase; use 'new {callee.name}(...)' para instanciarla.",
                expression.span,
            )
            return ERROR

        if isinstance(symbol, FunctionSymbol):
            if declaring_scope is not None:
                self._record_capture(symbol, declaring_scope)
            self._check_arguments(
                symbol, expression.arguments, argument_types, expression.span, f"'{symbol.name}'"
            )
            return symbol.return_type

        assert isinstance(symbol, VariableSymbol)
        if isinstance(symbol.type, FunctionType):
            return symbol.type.return_type
        if compat.is_indeterminate(symbol.type):
            return ERROR
        self._diagnostics.report(
            Code.NOT_CALLABLE,
            f"'{callee.name}' es una variable de tipo '{symbol.type.name}' y no es invocable.",
            expression.span,
            actual=symbol.type,
        )
        return ERROR

    def _check_method_call(self, expression: N.CallExpr, callee: N.PropertyAccess) -> Type:
        object_type = self._check_expression(callee.target)
        argument_types = [self._check_expression(a) for a in expression.arguments]

        if compat.is_indeterminate(object_type):
            return ERROR
        if not isinstance(object_type, ClassType):
            self._diagnostics.report(
                Code.PROPERTY_ON_NON_OBJECT,
                f"No se puede invocar '{callee.name}' sobre un valor de tipo "
                f"'{object_type.name}'.",
                callee.span,
                actual=object_type,
            )
            return ERROR

        method = self._table.classes.lookup_method(object_type.class_name, callee.name)
        if method is None:
            field_symbol = self._table.classes.lookup_field(object_type.class_name, callee.name)
            if field_symbol is not None and isinstance(field_symbol.type, FunctionType):
                return field_symbol.type.return_type
            self._diagnostics.report(
                Code.UNKNOWN_METHOD,
                f"La clase '{object_type.class_name}' no define el metodo '{callee.name}'.",
                callee.span,
            )
            return ERROR

        self._check_arguments(
            method,
            expression.arguments,
            argument_types,
            expression.span,
            f"'{object_type.class_name}.{callee.name}'",
        )
        callee.resolved_type = FunctionType(method.parameter_types, method.return_type)
        return method.return_type

    def _check_arguments(
        self,
        symbol: FunctionSymbol,
        arguments: Sequence[N.Expression],
        argument_types: Sequence[Type],
        span: N.SourceSpan,
        description: str,
    ) -> None:
        expected = len(symbol.parameters)
        received = len(argument_types)
        if expected != received:
            self._diagnostics.report(
                Code.ARGUMENT_COUNT_MISMATCH,
                f"La llamada a {description} esperaba {expected} argumento(s) y recibio "
                f"{received}.",
                span,
            )
            return

        for parameter, argument, argument_type in zip(symbol.parameters, arguments, argument_types):
            if self._assignable_expression(argument, argument_type, parameter.type):
                continue
            self._diagnostics.report(
                Code.ARGUMENT_TYPE_MISMATCH,
                f"El argumento '{parameter.name}' de {description} esperaba "
                f"'{parameter.type.name}' y recibio '{argument_type.name}'.",
                argument.span,
                expected=parameter.type,
                actual=argument_type,
            )

    def _check_index_expression(self, expression: N.IndexExpr) -> Type:
        target_type = self._check_expression(expression.target)
        index_type = self._check_expression(expression.index)

        if not compat.is_indeterminate(index_type) and not compat.is_integer(index_type):
            self._diagnostics.report(
                Code.NON_INTEGER_INDEX,
                f"El indice de un arreglo debe ser 'integer' y se recibio "
                f"'{index_type.name}'.",
                expression.index.span,
                expected=INTEGER,
                actual=index_type,
            )

        if compat.is_indeterminate(target_type):
            return ERROR
        if not isinstance(target_type, ArrayType):
            self._diagnostics.report(
                Code.NOT_INDEXABLE,
                f"No se puede indexar un valor de tipo '{target_type.name}'.",
                expression.target.span,
                actual=target_type,
            )
            return ERROR

        self._check_static_index_range(expression)
        return target_type.element

    def _check_static_index_range(self, expression: N.IndexExpr) -> None:
        """Advierte cuando el indice y el tamano son literales conocidos."""
        if not isinstance(expression.index, N.IntegerLiteral):
            return
        index = expression.index.value
        length = _static_array_length(expression.target, self._table)
        if length is None:
            return
        if index < 0 or index >= length:
            self._diagnostics.warn(
                Code.INDEX_OUT_OF_RANGE,
                f"El indice {index} esta fuera del rango del arreglo (tamano {length}); "
                "la comprobacion definitiva ocurre en tiempo de ejecucion.",
                expression.index.span,
            )

    def _check_property_access(self, expression: N.PropertyAccess) -> Type:
        object_type = self._check_expression(expression.target)
        return self._resolve_member_type(object_type, expression.name, expression.span)

    def _resolve_member_type(
        self, object_type: Type, member: str, span: N.SourceSpan
    ) -> Type:
        if compat.is_indeterminate(object_type):
            return ERROR
        if not isinstance(object_type, ClassType):
            self._diagnostics.report(
                Code.PROPERTY_ON_NON_OBJECT,
                f"No se puede acceder a '.{member}' sobre un valor de tipo "
                f"'{object_type.name}'.",
                span,
                actual=object_type,
            )
            return ERROR

        field_symbol = self._table.classes.lookup_field(object_type.class_name, member)
        if field_symbol is not None:
            return field_symbol.type

        method = self._table.classes.lookup_method(object_type.class_name, member)
        if method is not None:
            return FunctionType(method.parameter_types, method.return_type)

        self._diagnostics.report(
            Code.UNKNOWN_PROPERTY,
            f"La clase '{object_type.class_name}' no define el miembro '{member}'.",
            span,
        )
        return ERROR

    def _check_unary(self, expression: N.UnaryExpr) -> Type:
        operand_type = self._check_expression(expression.operand)
        if compat.is_indeterminate(operand_type):
            return ERROR

        if expression.operator == "-":
            if not compat.is_numeric(operand_type):
                self._diagnostics.report(
                    Code.NON_NUMERIC_OPERAND,
                    f"El operador unario '-' requiere un operando numerico y se recibio "
                    f"'{operand_type.name}'.",
                    expression.span,
                    actual=operand_type,
                )
                return ERROR
            return operand_type

        if not compat.is_boolean(operand_type):
            self._diagnostics.report(
                Code.NON_BOOLEAN_OPERAND,
                f"El operador '!' requiere un operando 'boolean' y se recibio "
                f"'{operand_type.name}'.",
                expression.span,
                expected=BOOLEAN,
                actual=operand_type,
            )
            return ERROR
        return BOOLEAN

    def _check_binary(self, expression: N.BinaryExpr) -> Type:
        left = self._require_value(
            self._check_expression(expression.left), expression.left.span
        )
        right = self._require_value(
            self._check_expression(expression.right), expression.right.span
        )
        operator = expression.operator

        if compat.is_indeterminate(left) or compat.is_indeterminate(right):
            return ERROR

        if operator == "+":
            return self._check_addition(expression, left, right)
        if operator in _ARITHMETIC_OPERATORS:
            return self._check_arithmetic(expression, left, right)
        if operator in _LOGICAL_OPERATORS:
            return self._check_logical(expression, left, right)
        if operator in compat.RELATIONAL_OPERATORS:
            if not compat.is_comparable(left, right, operator, self._table.classes):
                self._diagnostics.report(
                    Code.INVALID_RELATIONAL,
                    f"El operador '{operator}' requiere operandos numericos y se recibieron "
                    f"'{left.name}' y '{right.name}'.",
                    expression.span,
                )
            return BOOLEAN
        if operator in compat.EQUALITY_OPERATORS:
            if not compat.is_comparable(left, right, operator, self._table.classes):
                self._diagnostics.report(
                    Code.INVALID_EQUALITY,
                    f"No se pueden comparar con '{operator}' los tipos '{left.name}' y "
                    f"'{right.name}'.",
                    expression.span,
                    expected=left,
                    actual=right,
                )
            return BOOLEAN

        return ERROR  # pragma: no cover - la gramatica no genera otros operadores

    def _check_addition(self, expression: N.BinaryExpr, left: Type, right: Type) -> Type:
        result = compat.result_of_additive(left, right)
        if not compat.is_error(result):
            return result

        if compat.is_string(left) or compat.is_string(right):
            self._diagnostics.report(
                Code.INVALID_CONCATENATION,
                f"No se puede concatenar 'string' con '{(right if compat.is_string(left) else left).name}'.",
                expression.span,
            )
            return STRING

        if compat.is_null(left) or compat.is_null(right):
            self._diagnostics.report(
                Code.NULL_OPERATION,
                "No se permiten operaciones aritmeticas con 'null'.",
                expression.span,
            )
            return ERROR

        self._diagnostics.report(
            Code.NON_NUMERIC_OPERAND,
            f"El operador '+' requiere operandos numericos o al menos un 'string'; se "
            f"recibieron '{left.name}' y '{right.name}'.",
            expression.span,
        )
        return ERROR

    def _check_arithmetic(self, expression: N.BinaryExpr, left: Type, right: Type) -> Type:
        if compat.is_null(left) or compat.is_null(right):
            self._diagnostics.report(
                Code.NULL_OPERATION,
                "No se permiten operaciones aritmeticas con 'null'.",
                expression.span,
            )
            return ERROR
        result = compat.common_numeric_type(left, right)
        if compat.is_error(result):
            self._diagnostics.report(
                Code.NON_NUMERIC_OPERAND,
                f"El operador '{expression.operator}' requiere operandos numericos y se "
                f"recibieron '{left.name}' y '{right.name}'.",
                expression.span,
            )
            return ERROR
        return result

    def _check_logical(self, expression: N.BinaryExpr, left: Type, right: Type) -> Type:
        if not compat.is_boolean(left) or not compat.is_boolean(right):
            self._diagnostics.report(
                Code.NON_BOOLEAN_OPERAND,
                f"El operador '{expression.operator}' requiere operandos 'boolean' y se "
                f"recibieron '{left.name}' y '{right.name}'.",
                expression.span,
                expected=BOOLEAN,
            )
        return BOOLEAN

    def _check_ternary(self, expression: N.TernaryExpr) -> Type:
        self._check_condition(expression.condition, "?:")
        then_type = self._require_value(
            self._check_expression(expression.then_expr), expression.then_expr.span
        )
        else_type = self._require_value(
            self._check_expression(expression.else_expr), expression.else_expr.span
        )
        if compat.is_indeterminate(then_type) or compat.is_indeterminate(else_type):
            return ERROR

        merged = compat.common_type(then_type, else_type, self._table.classes)
        if merged is None:
            self._diagnostics.report(
                Code.INCOMPATIBLE_TERNARY,
                f"Las ramas del operador ternario tienen tipos incompatibles: "
                f"'{then_type.name}' y '{else_type.name}'.",
                expression.span,
                expected=then_type,
                actual=else_type,
            )
            return ERROR
        return merged

    # --- utilidades -------------------------------------------------------

    def _require_value(self, type_: Type, span: N.SourceSpan) -> Type:
        """Rechaza el uso de una expresion 'void' donde se necesita un valor."""
        if compat.is_void(type_):
            self._diagnostics.report(
                Code.VOID_AS_VALUE,
                "Una expresion de tipo 'void' no produce un valor utilizable.",
                span,
                actual=VOID,
            )
            return ERROR
        return type_


def _is_switchable(type_: Type) -> bool:
    """Tipos admitidos como selector de un ``switch``.

    Se aceptan los tipos con igualdad por valor. No se exige ``boolean``: eso
    impediria el caso habitual ``switch (numero)``.
    """
    return (
        compat.is_numeric(type_)
        or compat.is_string(type_)
        or compat.is_boolean(type_)
    )


def _literal_value(expression: N.Expression) -> Optional[object]:
    """Valor constante de una expresion literal, si lo tiene."""
    if isinstance(expression, N.IntegerLiteral):
        return ("integer", expression.value)
    if isinstance(expression, N.FloatLiteral):
        return ("float", expression.value)
    if isinstance(expression, N.StringLiteral):
        return ("string", expression.value)
    if isinstance(expression, N.BooleanLiteral):
        return ("boolean", expression.value)
    return None


def _literal_array_length(expression: Optional[N.Expression]) -> Optional[int]:
    if isinstance(expression, N.ArrayLiteral):
        return len(expression.elements)
    return None


def _static_array_length(target: N.Expression, table: SymbolTable) -> Optional[int]:
    """Tamano del arreglo indexado cuando se conoce en tiempo de compilacion."""
    if isinstance(target, N.ArrayLiteral):
        return len(target.elements)
    if isinstance(target, N.Identifier):
        symbol = table.resolve(target.name)
        if isinstance(symbol, VariableSymbol):
            return symbol.array_length
    return None
