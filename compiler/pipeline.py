"""API interna del compilador.

Es el unico punto de entrada que necesitan el CLI y el IDE::

    from compiler import compile_source
    result = compile_source(codigo, filename="<editor>")
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from antlr4 import CommonTokenStream, InputStream

from .ast.builder import build_ast
from .backend import generate_mips
from .ir import CodegenError, generate_ir
from .parser.antlr_runtime import CompiscriptLexer, CompiscriptParser
from .parser.error_listener import install_error_listeners
from .result import CompilationResult, CompileOptions
from .semantic.analyzer import SemanticAnalyzer
from .semantic.diagnostics import Code, DiagnosticBag, Phase


def compile_source(
    source: str,
    filename: str = "<memory>",
    options: Optional[CompileOptions] = None,
) -> CompilationResult:
    """Ejecuta el frontend y, opcionalmente, genera TAC y MIPS.

    Fases: analisis lexico, analisis sintactico, construccion del AST,
    construccion de la tabla de simbolos y analisis semantico.
    Con generate_tac/generate_mips continua con las fases de generacion.

    Si el analisis sintactico produce errores no se ejecuta el analisis
    semantico, porque el arbol resultante no es confiable.
    """
    options = options or CompileOptions()
    diagnostics = DiagnosticBag(filename)

    lexer = CompiscriptLexer(InputStream(source))
    token_stream = CommonTokenStream(lexer)
    parser = CompiscriptParser(token_stream)
    install_error_listeners(lexer, parser, diagnostics, filename)

    parse_tree = parser.program()

    result = CompilationResult(
        filename=filename,
        source=source,
        diagnostics=diagnostics.sorted(),
        options=options,
    )

    if diagnostics.has_errors:
        return result

    program = build_ast(parse_tree, filename)
    result.ast = program

    if options.syntax_only:
        return result

    analyzer = SemanticAnalyzer(filename)
    semantic = analyzer.analyze(program)
    diagnostics.extend(semantic.diagnostics.sorted())

    result.diagnostics = diagnostics.sorted()
    result.symbol_table = semantic.table
    if result.success and (options.generate_tac or options.generate_mips):
        try:
            result.ir = generate_ir(program, semantic.table)
            if options.generate_mips:
                result.mips = generate_mips(result.ir, allocation=options.allocation)
        except CodegenError as error:
            diagnostics.report(
                Code.UNSUPPORTED_CODEGEN, str(error), error.span, phase=Phase.CODEGEN
            )
            result.diagnostics = diagnostics.sorted()
    return result


def compile_file(
    path: str | Path,
    options: Optional[CompileOptions] = None,
) -> CompilationResult:
    """Compila un archivo ``.cps`` del disco."""
    file_path = Path(path)
    source = file_path.read_text(encoding="utf-8")
    return compile_source(source, filename=file_path.name, options=options)
