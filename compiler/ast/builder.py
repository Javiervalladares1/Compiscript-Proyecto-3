"""Construccion del AST propio a partir del parse tree de ANTLR.

Es la unica frontera entre ANTLR y el resto del compilador: a partir de aqui
ningun modulo vuelve a tocar contextos de ANTLR.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

from antlr4 import ParserRuleContext
from antlr4.tree.Tree import TerminalNode

from ..parser.antlr_runtime import CompiscriptParser, CompiscriptVisitor
from . import nodes as N


def _span_from_token(token: Any, filename: str) -> N.SourceSpan:
    text = token.text or ""
    length = len(text)
    return N.SourceSpan(
        file=filename,
        line=token.line,
        column=token.column + 1,
        end_line=token.line,
        end_column=token.column + 1 + length,
    )


class ASTBuilder(CompiscriptVisitor):
    """Visitor de ANTLR que produce nodos de :mod:`compiler.ast.nodes`."""

    def __init__(self, filename: str = "<memory>") -> None:
        self.filename = filename

    # --- utilidades -------------------------------------------------------

    def span(self, ctx: ParserRuleContext) -> N.SourceSpan:
        start = ctx.start
        stop = ctx.stop if ctx.stop is not None else ctx.start
        stop_text = stop.text or ""
        return N.SourceSpan(
            file=self.filename,
            line=start.line,
            column=start.column + 1,
            end_line=stop.line,
            end_column=stop.column + 1 + len(stop_text),
        )

    def token_span(self, token: Any) -> N.SourceSpan:
        if isinstance(token, TerminalNode):
            token = token.symbol
        return _span_from_token(token, self.filename)

    @staticmethod
    def _terminal_texts(ctx: ParserRuleContext) -> list[str]:
        return [c.getText() for c in ctx.getChildren() if isinstance(c, TerminalNode)]

    # --- programa y sentencias -------------------------------------------

    def build(self, ctx: CompiscriptParser.ProgramContext) -> N.Program:
        return self.visitProgram(ctx)

    def visitProgram(self, ctx: CompiscriptParser.ProgramContext) -> N.Program:
        statements = [self.visit_statement(s) for s in ctx.statement()]
        return N.Program(span=self.span(ctx), statements=[s for s in statements if s is not None])

    def visit_statement(self, ctx: CompiscriptParser.StatementContext) -> Optional[N.Statement]:
        child = ctx.getChild(0)
        return self.visit(child) if child is not None else None

    def visitBlock(self, ctx: CompiscriptParser.BlockContext) -> N.Block:
        statements = [self.visit_statement(s) for s in ctx.statement()]
        return N.Block(span=self.span(ctx), statements=[s for s in statements if s is not None])

    def visitVariableDeclaration(
        self, ctx: CompiscriptParser.VariableDeclarationContext
    ) -> N.VarDecl:
        keyword = ctx.getChild(0).getText()
        annotation = ctx.typeAnnotation()
        initializer = ctx.initializer()
        return N.VarDecl(
            span=self.span(ctx),
            name=ctx.Identifier().getText(),
            declared_type=self.visit_type(annotation.type_()) if annotation else None,
            initializer=self.visit_expression(initializer.expression()) if initializer else None,
            is_const=False,
            keyword=keyword,
        )

    def visitConstantDeclaration(
        self, ctx: CompiscriptParser.ConstantDeclarationContext
    ) -> N.VarDecl:
        annotation = ctx.typeAnnotation()
        initializer = ctx.expression()
        return N.VarDecl(
            span=self.span(ctx),
            name=ctx.Identifier().getText(),
            declared_type=self.visit_type(annotation.type_()) if annotation else None,
            initializer=self.visit_expression(initializer) if initializer is not None else None,
            is_const=True,
            keyword="const",
        )

    def visitAssignment(self, ctx: CompiscriptParser.AssignmentContext) -> N.AssignStmt:
        expressions = ctx.expression()
        if ctx.Identifier() is not None and len(expressions) == 1:
            # Alternativa 1: Identifier '=' expression ';'
            target: N.Expression = N.Identifier(
                span=self.token_span(ctx.Identifier()), name=ctx.Identifier().getText()
            )
            value = self.visit_expression(expressions[0])
        else:
            # Alternativa 2: expression '.' Identifier '=' expression ';'
            obj = self.visit_expression(expressions[0])
            name_token = ctx.Identifier()
            target = N.PropertyAccess(
                span=N.SourceSpan(
                    file=self.filename,
                    line=obj.span.line,
                    column=obj.span.column,
                    end_line=self.token_span(name_token).end_line,
                    end_column=self.token_span(name_token).end_column,
                ),
                target=obj,
                name=name_token.getText(),
            )
            value = self.visit_expression(expressions[1])
        return N.AssignStmt(span=self.span(ctx), target=target, value=value)

    def visitExpressionStatement(
        self, ctx: CompiscriptParser.ExpressionStatementContext
    ) -> N.ExpressionStmt:
        return N.ExpressionStmt(
            span=self.span(ctx), expression=self.visit_expression(ctx.expression())
        )

    def visitPrintStatement(self, ctx: CompiscriptParser.PrintStatementContext) -> N.PrintStmt:
        return N.PrintStmt(span=self.span(ctx), value=self.visit_expression(ctx.expression()))

    def visitIfStatement(self, ctx: CompiscriptParser.IfStatementContext) -> N.IfStmt:
        blocks = ctx.block()
        return N.IfStmt(
            span=self.span(ctx),
            condition=self.visit_expression(ctx.expression()),
            then_block=self.visitBlock(blocks[0]),
            else_block=self.visitBlock(blocks[1]) if len(blocks) > 1 else None,
        )

    def visitWhileStatement(self, ctx: CompiscriptParser.WhileStatementContext) -> N.WhileStmt:
        return N.WhileStmt(
            span=self.span(ctx),
            condition=self.visit_expression(ctx.expression()),
            body=self.visitBlock(ctx.block()),
        )

    def visitDoWhileStatement(
        self, ctx: CompiscriptParser.DoWhileStatementContext
    ) -> N.DoWhileStmt:
        return N.DoWhileStmt(
            span=self.span(ctx),
            body=self.visitBlock(ctx.block()),
            condition=self.visit_expression(ctx.expression()),
        )

    def visitForStatement(self, ctx: CompiscriptParser.ForStatementContext) -> N.ForStmt:
        initializer: Optional[N.Statement] = None
        condition: Optional[N.Expression] = None
        update: Optional[N.Expression] = None

        # for '(' (variableDeclaration | assignment | ';') expression? ';' expression? ')' block
        index = 2  # se saltan 'for' y '('
        child = ctx.getChild(index)
        if isinstance(child, CompiscriptParser.VariableDeclarationContext):
            initializer = self.visitVariableDeclaration(child)
            index += 1
        elif isinstance(child, CompiscriptParser.AssignmentContext):
            initializer = self.visitAssignment(child)
            index += 1
        else:  # el ';' vacio
            index += 1

        child = ctx.getChild(index)
        if isinstance(child, CompiscriptParser.ExpressionContext):
            condition = self.visit_expression(child)
            index += 1
        index += 1  # ';' separador entre condicion y actualizacion

        child = ctx.getChild(index)
        if isinstance(child, CompiscriptParser.ExpressionContext):
            update = self.visit_expression(child)

        return N.ForStmt(
            span=self.span(ctx),
            initializer=initializer,
            condition=condition,
            update=update,
            body=self.visitBlock(ctx.block()),
        )

    def visitForeachStatement(
        self, ctx: CompiscriptParser.ForeachStatementContext
    ) -> N.ForEachStmt:
        return N.ForEachStmt(
            span=self.span(ctx),
            variable=ctx.Identifier().getText(),
            iterable=self.visit_expression(ctx.expression()),
            body=self.visitBlock(ctx.block()),
        )

    def visitBreakStatement(self, ctx: CompiscriptParser.BreakStatementContext) -> N.BreakStmt:
        return N.BreakStmt(span=self.span(ctx))

    def visitContinueStatement(
        self, ctx: CompiscriptParser.ContinueStatementContext
    ) -> N.ContinueStmt:
        return N.ContinueStmt(span=self.span(ctx))

    def visitReturnStatement(self, ctx: CompiscriptParser.ReturnStatementContext) -> N.ReturnStmt:
        expression = ctx.expression()
        return N.ReturnStmt(
            span=self.span(ctx),
            value=self.visit_expression(expression) if expression is not None else None,
        )

    def visitTryCatchStatement(
        self, ctx: CompiscriptParser.TryCatchStatementContext
    ) -> N.TryCatchStmt:
        blocks = ctx.block()
        return N.TryCatchStmt(
            span=self.span(ctx),
            try_block=self.visitBlock(blocks[0]),
            error_name=ctx.Identifier().getText(),
            catch_block=self.visitBlock(blocks[1]),
            error_span=self.token_span(ctx.Identifier()),
        )

    def visitSwitchStatement(self, ctx: CompiscriptParser.SwitchStatementContext) -> N.SwitchStmt:
        default_ctx = ctx.defaultCase()
        return N.SwitchStmt(
            span=self.span(ctx),
            subject=self.visit_expression(ctx.expression()),
            cases=[self.visitSwitchCase(c) for c in ctx.switchCase()],
            default_case=self.visitDefaultCase(default_ctx) if default_ctx is not None else None,
        )

    def visitSwitchCase(self, ctx: CompiscriptParser.SwitchCaseContext) -> N.SwitchCase:
        statements = [self.visit_statement(s) for s in ctx.statement()]
        return N.SwitchCase(
            span=self.span(ctx),
            test=self.visit_expression(ctx.expression()),
            statements=[s for s in statements if s is not None],
        )

    def visitDefaultCase(self, ctx: CompiscriptParser.DefaultCaseContext) -> N.DefaultCase:
        statements = [self.visit_statement(s) for s in ctx.statement()]
        return N.DefaultCase(
            span=self.span(ctx), statements=[s for s in statements if s is not None]
        )

    def visitFunctionDeclaration(
        self, ctx: CompiscriptParser.FunctionDeclarationContext
    ) -> N.FunctionDecl:
        parameters_ctx = ctx.parameters()
        parameters = (
            [self.visitParameter(p) for p in parameters_ctx.parameter()] if parameters_ctx else []
        )
        type_ctx = ctx.type_()
        return N.FunctionDecl(
            span=self.span(ctx),
            name=ctx.Identifier().getText(),
            parameters=parameters,
            return_type_ref=self.visit_type(type_ctx) if type_ctx is not None else None,
            body=self.visitBlock(ctx.block()),
        )

    def visitParameter(self, ctx: CompiscriptParser.ParameterContext) -> N.Parameter:
        type_ctx = ctx.type_()
        return N.Parameter(
            span=self.span(ctx),
            name=ctx.Identifier().getText(),
            type_ref=self.visit_type(type_ctx) if type_ctx is not None else None,
        )

    def visitClassDeclaration(self, ctx: CompiscriptParser.ClassDeclarationContext) -> N.ClassDecl:
        identifiers = ctx.Identifier()
        name = identifiers[0].getText()
        base_name = identifiers[1].getText() if len(identifiers) > 1 else None
        base_span = self.token_span(identifiers[1]) if len(identifiers) > 1 else None

        members: list[N.Statement] = []
        for member_ctx in ctx.classMember():
            member = self.visit(member_ctx.getChild(0))
            if isinstance(member, N.FunctionDecl):
                member.owner_class = name
            members.append(member)

        return N.ClassDecl(
            span=self.span(ctx),
            name=name,
            base_name=base_name,
            base_span=base_span,
            members=members,
        )

    # --- tipos ------------------------------------------------------------

    def visit_type(self, ctx: CompiscriptParser.TypeContext) -> N.TypeRef:
        base = ctx.baseType().getText()
        dimensions = self._terminal_texts(ctx).count("[")
        return N.TypeRef(span=self.span(ctx), name=base, dimensions=dimensions)

    # --- expresiones ------------------------------------------------------

    def visit_expression(self, ctx: ParserRuleContext) -> N.Expression:
        result = self.visit(ctx)
        if not isinstance(result, N.Expression):  # pragma: no cover - red de seguridad
            raise TypeError(f"Se esperaba una expresion y se obtuvo {type(result).__name__}")
        return result

    def visitExpression(self, ctx: CompiscriptParser.ExpressionContext) -> N.Expression:
        return self.visit_expression(ctx.assignmentExpr())

    def visitAssignExpr(self, ctx: CompiscriptParser.AssignExprContext) -> N.AssignExpr:
        return N.AssignExpr(
            span=self.span(ctx),
            target=self.visit_expression(ctx.lhs),
            value=self.visit_expression(ctx.assignmentExpr()),
        )

    def visitPropertyAssignExpr(
        self, ctx: CompiscriptParser.PropertyAssignExprContext
    ) -> N.AssignExpr:
        obj = self.visit_expression(ctx.lhs)
        name_token = ctx.Identifier()
        target = N.PropertyAccess(
            span=N.SourceSpan(
                file=self.filename,
                line=obj.span.line,
                column=obj.span.column,
                end_line=self.token_span(name_token).end_line,
                end_column=self.token_span(name_token).end_column,
            ),
            target=obj,
            name=name_token.getText(),
        )
        return N.AssignExpr(
            span=self.span(ctx), target=target, value=self.visit_expression(ctx.assignmentExpr())
        )

    def visitExprNoAssign(self, ctx: CompiscriptParser.ExprNoAssignContext) -> N.Expression:
        return self.visit_expression(ctx.conditionalExpr())

    def visitTernaryExpr(self, ctx: CompiscriptParser.TernaryExprContext) -> N.Expression:
        condition = self.visit_expression(ctx.logicalOrExpr())
        expressions = ctx.expression()
        if not expressions:
            return condition
        return N.TernaryExpr(
            span=self.span(ctx),
            condition=condition,
            then_expr=self.visit_expression(expressions[0]),
            else_expr=self.visit_expression(expressions[1]),
        )

    def _binary_chain(self, ctx: ParserRuleContext) -> N.Expression:
        """Construye una cadena binaria asociativa a la izquierda.

        Sirve para todas las reglas con forma ``operando (op operando)*``.
        """
        children = list(ctx.getChildren())
        result = self.visit_expression(children[0])
        index = 1
        while index + 1 < len(children):
            operator = children[index].getText()
            right = self.visit_expression(children[index + 1])
            result = N.BinaryExpr(
                span=N.SourceSpan(
                    file=self.filename,
                    line=result.span.line,
                    column=result.span.column,
                    end_line=right.span.end_line,
                    end_column=right.span.end_column,
                ),
                operator=operator,
                left=result,
                right=right,
            )
            index += 2
        return result

    def visitLogicalOrExpr(self, ctx: CompiscriptParser.LogicalOrExprContext) -> N.Expression:
        return self._binary_chain(ctx)

    def visitLogicalAndExpr(self, ctx: CompiscriptParser.LogicalAndExprContext) -> N.Expression:
        return self._binary_chain(ctx)

    def visitEqualityExpr(self, ctx: CompiscriptParser.EqualityExprContext) -> N.Expression:
        return self._binary_chain(ctx)

    def visitRelationalExpr(self, ctx: CompiscriptParser.RelationalExprContext) -> N.Expression:
        return self._binary_chain(ctx)

    def visitAdditiveExpr(self, ctx: CompiscriptParser.AdditiveExprContext) -> N.Expression:
        return self._binary_chain(ctx)

    def visitMultiplicativeExpr(
        self, ctx: CompiscriptParser.MultiplicativeExprContext
    ) -> N.Expression:
        return self._binary_chain(ctx)

    def visitUnaryExpr(self, ctx: CompiscriptParser.UnaryExprContext) -> N.Expression:
        inner = ctx.unaryExpr()
        if inner is not None:
            return N.UnaryExpr(
                span=self.span(ctx),
                operator=ctx.getChild(0).getText(),
                operand=self.visit_expression(inner),
            )
        return self.visit_expression(ctx.primaryExpr())

    def visitPrimaryExpr(self, ctx: CompiscriptParser.PrimaryExprContext) -> N.Expression:
        if ctx.literalExpr() is not None:
            return self.visitLiteralExpr(ctx.literalExpr())
        if ctx.leftHandSide() is not None:
            return self.visitLeftHandSide(ctx.leftHandSide())
        return self.visit_expression(ctx.expression())

    def visitLiteralExpr(self, ctx: CompiscriptParser.LiteralExprContext) -> N.Expression:
        array_ctx = ctx.arrayLiteral()
        if array_ctx is not None:
            return self.visitArrayLiteral(array_ctx)

        literal = ctx.Literal()
        span = self.span(ctx)
        if literal is not None:
            return self._literal_from_text(literal.getText(), span)

        text = ctx.getText()
        if text == "null":
            return N.NullLiteral(span=span)
        return N.BooleanLiteral(span=span, value=text == "true")

    @staticmethod
    def _literal_from_text(text: str, span: N.SourceSpan) -> N.Expression:
        """Distingue las tres formas del token compuesto ``Literal``.

        La gramatica agrupa ``FloatLiteral | IntegerLiteral | StringLiteral``
        bajo un unico token ``Literal``, por lo que la variante concreta se
        determina aqui a partir del texto.
        """
        if text.startswith('"'):
            return N.StringLiteral(span=span, value=text[1:-1])
        if "." in text:
            return N.FloatLiteral(span=span, value=float(text))
        return N.IntegerLiteral(span=span, value=int(text))

    def visitArrayLiteral(self, ctx: CompiscriptParser.ArrayLiteralContext) -> N.ArrayLiteral:
        return N.ArrayLiteral(
            span=self.span(ctx),
            elements=[self.visit_expression(e) for e in ctx.expression()],
        )

    def visitLeftHandSide(self, ctx: CompiscriptParser.LeftHandSideContext) -> N.Expression:
        result = self.visit_expression(ctx.primaryAtom())
        for suffix in ctx.suffixOp():
            result = self._apply_suffix(result, suffix)
        return result

    def _apply_suffix(self, target: N.Expression, suffix: ParserRuleContext) -> N.Expression:
        span = N.SourceSpan(
            file=self.filename,
            line=target.span.line,
            column=target.span.column,
            end_line=self.span(suffix).end_line,
            end_column=self.span(suffix).end_column,
        )
        if isinstance(suffix, CompiscriptParser.CallExprContext):
            return N.CallExpr(span=span, callee=target, arguments=self._arguments(suffix))
        if isinstance(suffix, CompiscriptParser.IndexExprContext):
            return N.IndexExpr(
                span=span, target=target, index=self.visit_expression(suffix.expression())
            )
        if isinstance(suffix, CompiscriptParser.PropertyAccessExprContext):
            return N.PropertyAccess(span=span, target=target, name=suffix.Identifier().getText())
        raise TypeError(f"Sufijo desconocido: {type(suffix).__name__}")  # pragma: no cover

    def _arguments(self, ctx: ParserRuleContext) -> list[N.Expression]:
        arguments_ctx = ctx.arguments()
        if arguments_ctx is None:
            return []
        return [self.visit_expression(e) for e in arguments_ctx.expression()]

    def visitIdentifierExpr(self, ctx: CompiscriptParser.IdentifierExprContext) -> N.Identifier:
        return N.Identifier(span=self.span(ctx), name=ctx.Identifier().getText())

    def visitNewExpr(self, ctx: CompiscriptParser.NewExprContext) -> N.NewExpr:
        return N.NewExpr(
            span=self.span(ctx),
            class_name=ctx.Identifier().getText(),
            arguments=self._arguments(ctx),
        )

    def visitThisExpr(self, ctx: CompiscriptParser.ThisExprContext) -> N.ThisExpr:
        return N.ThisExpr(span=self.span(ctx))


def build_ast(ctx: CompiscriptParser.ProgramContext, filename: str = "<memory>") -> N.Program:
    """Punto de entrada del modulo."""
    return ASTBuilder(filename).build(ctx)


def iter_nodes(node: N.Node) -> Sequence[N.Node]:
    """Recorrido en preorden del AST (utilidad para pruebas y herramientas)."""
    result: list[N.Node] = [node]
    for child in node.children():
        result.extend(iter_nodes(child))
    return result
