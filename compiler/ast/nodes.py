"""Nodos del AST propio de Compiscript.

Este arbol es independiente del parse tree de ANTLR: el analizador semantico,
el serializador, el visualizador y las fases posteriores del compilador
trabajan unicamente sobre estas clases.

Cada nodo conserva su ubicacion de origen (:class:`SourceSpan`) y las
expresiones almacenan el tipo resuelto por el analizador en ``resolved_type``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from ..types.types import Type


@dataclass(frozen=True)
class SourceSpan:
    """Ubicacion de un nodo en el archivo fuente.

    Las lineas y columnas son 1-based (ANTLR entrega la columna 0-based; la
    conversion se realiza al construir el span).
    """

    file: str
    line: int
    column: int
    end_line: Optional[int] = None
    end_column: Optional[int] = None

    def __str__(self) -> str:
        return f"{self.file}:{self.line}:{self.column}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "line": self.line,
            "column": self.column,
            "endLine": self.end_line,
            "endColumn": self.end_column,
        }


@dataclass
class Node:
    """Raiz de la jerarquia. Todos los nodos tienen ubicacion."""

    span: SourceSpan

    @property
    def kind(self) -> str:
        return type(self).__name__

    def children(self) -> list["Node"]:
        """Hijos directos, en orden de aparicion en el codigo fuente."""
        return []

    def label(self) -> str:
        """Etiqueta legible usada por el visualizador."""
        return self.kind

    def to_tree(self, prefix: str = "", is_last: bool = True, is_root: bool = True) -> str:
        """AST como arbol de texto con conectores, para la consola.

        Es la version en texto de lo que ``visualizer.write_dot`` exporta a
        Graphviz: mismos nodos, mismas etiquetas y misma relacion padre/hijo.
        """
        if is_root:
            lines = [f"{self.label()}  [{self.span.line}:{self.span.column}]"]
            child_prefix = ""
        else:
            connector = "└── " if is_last else "├── "
            lines = [f"{prefix}{connector}{self.label()}  [{self.span.line}:{self.span.column}]"]
            child_prefix = prefix + ("    " if is_last else "│   ")

        children = self.children()
        for index, child in enumerate(children):
            lines.append(
                child.to_tree(
                    prefix=child_prefix,
                    is_last=index == len(children) - 1,
                    is_root=False,
                )
            )
        return "\n".join(lines)


# --- Referencias sintacticas de tipo --------------------------------------


@dataclass
class TypeRef(Node):
    """Anotacion de tipo tal como aparece escrita (``integer[][]``).

    La resolucion al objeto :class:`~compiler.types.types.Type` la realiza el
    analizador semantico, que la deposita en ``resolved_type``.
    """

    name: str
    dimensions: int = 0
    resolved_type: Optional[Type] = field(default=None, compare=False)

    def label(self) -> str:
        return f"TypeRef {self.name}{'[]' * self.dimensions}"


# --- Expresiones -----------------------------------------------------------


@dataclass
class Expression(Node):
    """Base de todas las expresiones."""

    resolved_type: Optional[Type] = field(default=None, init=False, compare=False)


@dataclass
class IntegerLiteral(Expression):
    value: int

    def label(self) -> str:
        return f"IntegerLiteral {self.value}"


@dataclass
class FloatLiteral(Expression):
    value: float

    def label(self) -> str:
        return f"FloatLiteral {self.value}"


@dataclass
class StringLiteral(Expression):
    value: str

    def label(self) -> str:
        return f"StringLiteral {self.value!r}"


@dataclass
class BooleanLiteral(Expression):
    value: bool

    def label(self) -> str:
        return f"BooleanLiteral {'true' if self.value else 'false'}"


@dataclass
class NullLiteral(Expression):
    def label(self) -> str:
        return "NullLiteral"


@dataclass
class ArrayLiteral(Expression):
    elements: list[Expression] = field(default_factory=list)

    def children(self) -> list[Node]:
        return list(self.elements)


@dataclass
class Identifier(Expression):
    name: str
    #: Simbolo resuelto por el analizador (util para fases posteriores).
    resolved_symbol: Optional[Any] = field(default=None, init=False, compare=False)

    def label(self) -> str:
        return f"Identifier {self.name}"


@dataclass
class ThisExpr(Expression):
    def label(self) -> str:
        return "This"


@dataclass
class NewExpr(Expression):
    class_name: str
    arguments: list[Expression] = field(default_factory=list)

    def children(self) -> list[Node]:
        return list(self.arguments)

    def label(self) -> str:
        return f"New {self.class_name}"


@dataclass
class CallExpr(Expression):
    callee: Expression
    arguments: list[Expression] = field(default_factory=list)

    def children(self) -> list[Node]:
        return [self.callee, *self.arguments]


@dataclass
class IndexExpr(Expression):
    target: Expression
    index: Expression

    def children(self) -> list[Node]:
        return [self.target, self.index]


@dataclass
class PropertyAccess(Expression):
    target: Expression
    name: str

    def children(self) -> list[Node]:
        return [self.target]

    def label(self) -> str:
        return f"PropertyAccess .{self.name}"


@dataclass
class UnaryExpr(Expression):
    operator: str
    operand: Expression

    def children(self) -> list[Node]:
        return [self.operand]

    def label(self) -> str:
        return f"Unary {self.operator}"


@dataclass
class BinaryExpr(Expression):
    operator: str
    left: Expression
    right: Expression

    def children(self) -> list[Node]:
        return [self.left, self.right]

    def label(self) -> str:
        return f"Binary {self.operator}"


@dataclass
class TernaryExpr(Expression):
    condition: Expression
    then_expr: Expression
    else_expr: Expression

    def children(self) -> list[Node]:
        return [self.condition, self.then_expr, self.else_expr]

    def label(self) -> str:
        return "Ternary ?:"


@dataclass
class AssignExpr(Expression):
    """Asignacion usada como expresion (``a = b`` dentro de otra expresion)."""

    target: Expression
    value: Expression

    def children(self) -> list[Node]:
        return [self.target, self.value]

    def label(self) -> str:
        return "AssignExpr ="


# --- Sentencias ------------------------------------------------------------


@dataclass
class Statement(Node):
    """Base de todas las sentencias."""


@dataclass
class Program(Node):
    statements: list[Statement] = field(default_factory=list)

    def children(self) -> list[Node]:
        return list(self.statements)


@dataclass
class Block(Statement):
    statements: list[Statement] = field(default_factory=list)

    def children(self) -> list[Node]:
        return list(self.statements)


@dataclass
class VarDecl(Statement):
    """Declaracion de variable (``let``/``var``) o de constante (``const``)."""

    name: str
    declared_type: Optional[TypeRef] = None
    initializer: Optional[Expression] = None
    is_const: bool = False
    keyword: str = "let"
    #: Tipo final (declarado o inferido), completado por el analizador.
    resolved_type: Optional[Type] = field(default=None, compare=False)

    def children(self) -> list[Node]:
        result: list[Node] = []
        if self.declared_type is not None:
            result.append(self.declared_type)
        if self.initializer is not None:
            result.append(self.initializer)
        return result

    def label(self) -> str:
        return f"{'ConstDecl' if self.is_const else 'VarDecl'} {self.name}"


@dataclass
class AssignStmt(Statement):
    """Asignacion en forma de sentencia (``a = b;``, ``o.p = b;``)."""

    target: Expression
    value: Expression

    def children(self) -> list[Node]:
        return [self.target, self.value]

    def label(self) -> str:
        return "Assign ="


@dataclass
class Parameter(Node):
    name: str
    type_ref: Optional[TypeRef] = None
    resolved_type: Optional[Type] = field(default=None, compare=False)

    def children(self) -> list[Node]:
        return [self.type_ref] if self.type_ref is not None else []

    def label(self) -> str:
        return f"Parameter {self.name}"


@dataclass
class FunctionDecl(Statement):
    name: str
    parameters: list[Parameter] = field(default_factory=list)
    return_type_ref: Optional[TypeRef] = None
    body: Optional[Block] = None
    #: Nombre de la clase propietaria cuando es un metodo.
    owner_class: Optional[str] = None

    def children(self) -> list[Node]:
        result: list[Node] = list(self.parameters)
        if self.return_type_ref is not None:
            result.append(self.return_type_ref)
        if self.body is not None:
            result.append(self.body)
        return result

    @property
    def is_constructor(self) -> bool:
        return self.owner_class is not None and self.name == "constructor"

    def label(self) -> str:
        prefix = "Method" if self.owner_class else "Function"
        if self.is_constructor:
            prefix = "Constructor"
        return f"{prefix} {self.name}"


@dataclass
class ClassDecl(Statement):
    name: str
    base_name: Optional[str] = None
    base_span: Optional[SourceSpan] = None
    members: list[Statement] = field(default_factory=list)

    def children(self) -> list[Node]:
        return list(self.members)

    def label(self) -> str:
        if self.base_name:
            return f"Class {self.name} : {self.base_name}"
        return f"Class {self.name}"


@dataclass
class IfStmt(Statement):
    condition: Expression
    then_block: Block
    else_block: Optional[Block] = None

    def children(self) -> list[Node]:
        result: list[Node] = [self.condition, self.then_block]
        if self.else_block is not None:
            result.append(self.else_block)
        return result


@dataclass
class WhileStmt(Statement):
    condition: Expression
    body: Block

    def children(self) -> list[Node]:
        return [self.condition, self.body]


@dataclass
class DoWhileStmt(Statement):
    body: Block
    condition: Expression

    def children(self) -> list[Node]:
        return [self.body, self.condition]


@dataclass
class ForStmt(Statement):
    initializer: Optional[Statement] = None
    condition: Optional[Expression] = None
    update: Optional[Expression] = None
    body: Optional[Block] = None

    def children(self) -> list[Node]:
        result: list[Node] = []
        for item in (self.initializer, self.condition, self.update, self.body):
            if item is not None:
                result.append(item)
        return result


@dataclass
class ForEachStmt(Statement):
    variable: str
    iterable: Expression
    body: Block
    #: Tipo del elemento, resuelto por el analizador.
    element_type: Optional[Type] = field(default=None, compare=False)

    def children(self) -> list[Node]:
        return [self.iterable, self.body]

    def label(self) -> str:
        return f"ForEach {self.variable}"


@dataclass
class SwitchCase(Node):
    test: Expression
    statements: list[Statement] = field(default_factory=list)

    def children(self) -> list[Node]:
        return [self.test, *self.statements]


@dataclass
class DefaultCase(Node):
    statements: list[Statement] = field(default_factory=list)

    def children(self) -> list[Node]:
        return list(self.statements)


@dataclass
class SwitchStmt(Statement):
    subject: Expression
    cases: list[SwitchCase] = field(default_factory=list)
    default_case: Optional[DefaultCase] = None

    def children(self) -> list[Node]:
        result: list[Node] = [self.subject, *self.cases]
        if self.default_case is not None:
            result.append(self.default_case)
        return result


@dataclass
class TryCatchStmt(Statement):
    try_block: Block
    error_name: str
    catch_block: Block
    error_span: Optional[SourceSpan] = None

    def children(self) -> list[Node]:
        return [self.try_block, self.catch_block]

    def label(self) -> str:
        return f"TryCatch (catch {self.error_name})"


@dataclass
class BreakStmt(Statement):
    def label(self) -> str:
        return "Break"


@dataclass
class ContinueStmt(Statement):
    def label(self) -> str:
        return "Continue"


@dataclass
class ReturnStmt(Statement):
    value: Optional[Expression] = None

    def children(self) -> list[Node]:
        return [self.value] if self.value is not None else []

    def label(self) -> str:
        return "Return"


@dataclass
class PrintStmt(Statement):
    value: Expression

    def children(self) -> list[Node]:
        return [self.value]

    def label(self) -> str:
        return "Print"


@dataclass
class ExpressionStmt(Statement):
    expression: Expression

    def children(self) -> list[Node]:
        return [self.expression]

    def label(self) -> str:
        return "ExpressionStmt"
