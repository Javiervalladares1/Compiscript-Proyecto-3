"""Pasadas de declaracion previas a la verificacion de cuerpos.

Estas pasadas registran nombres y firmas antes de analizar el codigo, lo que
permite recursion directa, recursion mutua y el uso de una clase antes de su
declaracion textual.

Orden de ejecucion:

1. :meth:`DeclarationCollector.collect_classes` — nombres de clases.
2. :meth:`DeclarationCollector.resolve_inheritance` — base existente y ciclos.
3. :meth:`DeclarationCollector.collect_class_members` — atributos, metodos, constructor.
4. :meth:`DeclarationCollector.collect_functions` — firmas de funciones globales.
"""

from __future__ import annotations

from typing import Optional, Sequence

from ..ast import nodes as N
from ..symbols.scope import Scope, ScopeKind
from ..symbols.symbols import (
    ClassSymbol,
    FunctionSymbol,
    ParameterInfo,
    SymbolCategory,
    VariableSymbol,
)
from ..symbols.table import SymbolTable
from ..types.types import ERROR, VOID, ClassType, Type
from .diagnostics import Code, DiagnosticBag
from .type_resolver import TypeResolver


class DeclarationCollector:
    """Construye los simbolos de clases y funciones antes del chequeo."""

    def __init__(
        self,
        table: SymbolTable,
        diagnostics: DiagnosticBag,
        resolver: TypeResolver,
    ) -> None:
        self._table = table
        self._diagnostics = diagnostics
        self._resolver = resolver

    # --- pasada 1: nombres de clases -------------------------------------

    def collect_classes(self, program: N.Program) -> None:
        for statement in program.statements:
            if not isinstance(statement, N.ClassDecl):
                continue
            symbol = ClassSymbol(
                name=statement.name,
                category=SymbolCategory.CLASS,
                type=ClassType(statement.name),
                span=statement.span,
                ast_node=statement,
                base_name=statement.base_name,
                base_span=statement.base_span,
            )
            if not self._table.global_scope.declare(symbol):
                self._diagnostics.report(
                    Code.DUPLICATE_DECLARATION,
                    f"'{statement.name}' ya esta declarado en el ambito global.",
                    statement.span,
                )
                continue
            self._table.register_class(symbol)

    # --- pasada 2: herencia ----------------------------------------------

    def resolve_inheritance(self) -> None:
        for class_symbol in self._table.classes:
            base = class_symbol.base_name
            if base is None:
                continue
            if self._table.classes.get(base) is None:
                self._diagnostics.report(
                    Code.UNKNOWN_BASE_CLASS,
                    f"La clase base '{base}' no esta declarada.",
                    class_symbol.base_span or class_symbol.span,
                )
                class_symbol.base_name = None
                continue
            if self._has_cycle(class_symbol.name):
                self._diagnostics.report(
                    Code.INHERITANCE_CYCLE,
                    f"Ciclo de herencia detectado en la clase '{class_symbol.name}'.",
                    class_symbol.base_span or class_symbol.span,
                )
                # Se rompe el ciclo para que el resto del analisis sea estable.
                class_symbol.base_name = None

    def _has_cycle(self, class_name: str) -> bool:
        seen: set[str] = set()
        current: Optional[str] = class_name
        while current is not None:
            if current in seen:
                return True
            seen.add(current)
            symbol = self._table.classes.get(current)
            current = symbol.base_name if symbol is not None else None
        return False

    # --- pasada 3: miembros de clase -------------------------------------

    def collect_class_members(self, program: N.Program) -> None:
        for statement in program.statements:
            if isinstance(statement, N.ClassDecl):
                self._collect_members_of(statement)

    def _collect_members_of(self, declaration: N.ClassDecl) -> None:
        class_symbol = self._table.classes.get(declaration.name)
        if class_symbol is None:
            return

        class_scope = self._table.push_scope(f"class {declaration.name}", ScopeKind.CLASS)
        class_symbol.class_scope = class_scope
        try:
            for member in declaration.members:
                if isinstance(member, N.VarDecl):
                    self._declare_field(class_symbol, member, class_scope)
                elif isinstance(member, N.FunctionDecl):
                    self._declare_method(class_symbol, member, class_scope)
        finally:
            self._table.pop_scope()

        self._check_overrides(class_symbol)

    def _declare_field(
        self, class_symbol: ClassSymbol, member: N.VarDecl, class_scope: Scope
    ) -> None:
        if member.name in class_symbol.fields or member.name in class_symbol.methods:
            self._diagnostics.report(
                Code.DUPLICATE_MEMBER,
                f"El miembro '{member.name}' ya esta declarado en la clase "
                f"'{class_symbol.name}'.",
                member.span,
            )
            return

        declared = (
            self._resolver.resolve(member.declared_type)
            if member.declared_type is not None
            else None
        )
        if declared is None:
            # Los atributos sin anotacion no pueden inferirse en esta pasada
            # (su inicializador se analiza mas tarde); se marcan como error
            # controlado para no encadenar diagnosticos.
            if member.declared_type is None and member.initializer is None:
                self._diagnostics.report(
                    Code.CANNOT_INFER_TYPE,
                    f"No se puede determinar el tipo del atributo '{member.name}'; "
                    "agregue una anotacion de tipo.",
                    member.span,
                )
            declared = ERROR

        symbol = VariableSymbol(
            name=member.name,
            category=SymbolCategory.CONSTANT if member.is_const else SymbolCategory.FIELD,
            type=declared,
            span=member.span,
            ast_node=member,
            mutable=not member.is_const,
            initialized=member.initializer is not None,
            owner_class=class_symbol.name,
        )
        member.resolved_type = declared
        class_symbol.fields[member.name] = symbol
        class_scope.declare(symbol)

    def _declare_method(
        self, class_symbol: ClassSymbol, member: N.FunctionDecl, class_scope: Scope
    ) -> None:
        is_constructor = member.name == "constructor"
        if member.name in class_symbol.methods or member.name in class_symbol.fields:
            self._diagnostics.report(
                Code.DUPLICATE_MEMBER,
                f"El miembro '{member.name}' ya esta declarado en la clase "
                f"'{class_symbol.name}'.",
                member.span,
            )
            return
        if is_constructor and class_symbol.constructor is not None:
            self._diagnostics.report(
                Code.DUPLICATE_MEMBER,
                f"La clase '{class_symbol.name}' declara mas de un constructor.",
                member.span,
            )
            return

        symbol = self._build_function_symbol(
            member,
            category=SymbolCategory.CONSTRUCTOR if is_constructor else SymbolCategory.METHOD,
            owner_class=class_symbol.name,
        )
        if is_constructor:
            # El constructor no devuelve valor.
            symbol.return_type = VOID
            symbol.return_type_inferred = False
            symbol.refresh_type()
            class_symbol.constructor = symbol
        else:
            class_symbol.methods[member.name] = symbol
        class_scope.declare(symbol)

    def _check_overrides(self, class_symbol: ClassSymbol) -> None:
        """Valida que las sobrescrituras conserven una firma compatible."""
        base_name = class_symbol.base_name
        if base_name is None:
            return
        for name, method in class_symbol.methods.items():
            inherited = self._table.classes.lookup_method(base_name, name)
            if inherited is None:
                continue
            if not self._signatures_compatible(inherited, method):
                self._diagnostics.report(
                    Code.INCOMPATIBLE_OVERRIDE,
                    f"El metodo '{name}' sobrescribe a '{base_name}.{name}' con una firma "
                    f"incompatible: se esperaba '{inherited.signature}'.",
                    method.span,
                    expected=inherited.return_type,
                    actual=method.return_type,
                )

    def _signatures_compatible(self, base: FunctionSymbol, override: FunctionSymbol) -> bool:
        if base.arity != override.arity:
            return False
        for base_param, override_param in zip(base.parameters, override.parameters):
            if base_param.type != override_param.type:
                return False
        return base.return_type == override.return_type

    # --- pasada 4: funciones globales ------------------------------------

    def collect_functions(self, program: N.Program) -> None:
        self.hoist_functions(program.statements, self._table.global_scope)

    def hoist_functions(self, statements: Sequence[N.Statement], scope: Scope) -> None:
        """Registra las firmas de las funciones declaradas en ``statements``.

        Se aplica tanto al programa como al cuerpo de cada bloque, de forma que
        dos funciones hermanas puedan llamarse mutuamente.
        """
        for statement in statements:
            if not isinstance(statement, N.FunctionDecl):
                continue
            symbol = self._build_function_symbol(statement, category=SymbolCategory.FUNCTION)
            enclosing = scope.enclosing_function_scope()
            symbol.enclosing_function = enclosing.name if enclosing is not None else None
            if not scope.declare(symbol):
                self._diagnostics.report(
                    Code.DUPLICATE_DECLARATION,
                    f"La funcion '{statement.name}' ya esta declarada en este ambito "
                    "(Compiscript no admite sobrecarga).",
                    statement.span,
                )

    # --- construccion de firmas ------------------------------------------

    def _build_function_symbol(
        self,
        declaration: N.FunctionDecl,
        category: SymbolCategory,
        owner_class: Optional[str] = None,
    ) -> FunctionSymbol:
        parameters: list[ParameterInfo] = []
        seen: set[str] = set()
        for index, parameter in enumerate(declaration.parameters):
            parameter_type: Type = (
                self._resolver.resolve(parameter.type_ref)
                if parameter.type_ref is not None
                else ERROR
            )
            if parameter.type_ref is None:
                self._diagnostics.report(
                    Code.CANNOT_INFER_TYPE,
                    f"El parametro '{parameter.name}' necesita una anotacion de tipo.",
                    parameter.span,
                )
            parameter.resolved_type = parameter_type
            if parameter.name in seen:
                self._diagnostics.report(
                    Code.DUPLICATE_PARAMETER,
                    f"El parametro '{parameter.name}' esta duplicado en la funcion "
                    f"'{declaration.name}'.",
                    parameter.span,
                )
            else:
                seen.add(parameter.name)
                parameters.append(
                    ParameterInfo(
                        name=parameter.name,
                        type=parameter_type,
                        index=index,
                        span=parameter.span,
                    )
                )

        if declaration.return_type_ref is not None:
            return_type = self._resolver.resolve(declaration.return_type_ref)
            inferred = False
        else:
            return_type = infer_return_type_placeholder(declaration)
            inferred = True

        return FunctionSymbol(
            name=declaration.name,
            category=category,
            type=ERROR,  # se sustituye por la FunctionType en __post_init__
            span=declaration.span,
            ast_node=declaration,
            parameters=parameters,
            return_type=return_type,
            return_type_inferred=inferred,
            owner_class=owner_class,
        )


def infer_return_type_placeholder(declaration: N.FunctionDecl) -> Type:
    """Tipo de retorno provisional de una funcion sin anotacion.

    Politica documentada: una funcion sin ``: tipo`` es ``void`` si su cuerpo
    no contiene ningun ``return`` con valor. Si contiene alguno, el tipo se
    marca como ``unknown`` y lo concreta el verificador de cuerpos a partir de
    las expresiones efectivamente retornadas.
    """
    from ..types.types import UNKNOWN

    return UNKNOWN if _has_value_return(declaration.body) else VOID


def _has_value_return(node: Optional[N.Node]) -> bool:
    if node is None:
        return False
    for child in node.children():
        if isinstance(child, N.ReturnStmt):
            if child.value is not None:
                return True
            continue
        if isinstance(child, (N.FunctionDecl, N.ClassDecl)):
            continue  # pertenece a otra funcion
        if _has_value_return(child):
            return True
    return False
