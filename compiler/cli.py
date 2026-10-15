"""Interfaz de linea de comandos del compilador.

``program/Driver.py`` delega aqui para preservar el uso tradicional::

    python3 Driver.py program.cps
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence, TextIO

from .ast.serializer import ast_to_json
from .ast.visualizer import graphviz_available, render_image, write_dot
from .backend.simulator import SimulatorError, run_spim
from .pipeline import compile_file
from .result import CompilationResult, CompileOptions
from .semantic.diagnostics import Severity

_DESCRIPTION = "Compilador de Compiscript: frontend, TAC y MIPS32 (SPIM/MARS)."

#: Archivo DOT que se genera cuando se pasa ``--ast`` sin argumento.
DEFAULT_AST_DOT = "ast.dot"

#: Centinela de ``--symbols`` sin argumento: la tabla va a la consola, no a
#: un archivo JSON. Es un valor imposible como nombre de archivo.
SYMBOLS_TO_STDOUT = "\0stdout"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="Driver.py", description=_DESCRIPTION)
    parser.add_argument("source", help="Archivo fuente .cps a analizar")
    parser.add_argument("--tac", metavar="ARCHIVO.tac", help="Exporta codigo de tres direcciones")
    parser.add_argument("--mips", metavar="ARCHIVO.asm", help="Exporta assembler MIPS32 para SPIM/MARS")
    parser.add_argument("--allocation", choices=("registers", "stack"), default="registers",
                        help="Asignacion con getReg o respaldo en pila en cada operacion")
    parser.add_argument("--run", action="store_true", help="Genera MIPS y lo ejecuta en SPIM")
    parser.add_argument("--run-timeout", type=float, default=10.0, metavar="SEGUNDOS",
                        help="Limite de ejecucion SPIM (por omision: 10 segundos)")
    parser.add_argument(
        "--ast",
        nargs="?",
        const=DEFAULT_AST_DOT,
        metavar="ARCHIVO.dot",
        help=(
            "Exporta el AST en formato Graphviz DOT. Sin argumento escribe "
            f"'{DEFAULT_AST_DOT}' e imprime el arbol en la consola"
        ),
    )
    parser.add_argument(
        "--ast-json",
        metavar="ARCHIVO.json",
        help="Exporta el AST como JSON jerarquico",
    )
    parser.add_argument(
        "--ast-image",
        metavar="ARCHIVO.png",
        help="Renderiza el AST a PNG/SVG (requiere Graphviz; se omite si no esta)",
    )
    parser.add_argument(
        "--symbols",
        nargs="?",
        const=SYMBOLS_TO_STDOUT,
        metavar="ARCHIVO.json",
        help=(
            "Exporta la tabla de simbolos como JSON. Sin argumento imprime el "
            "arbol de ambitos en la consola"
        ),
    )
    parser.add_argument(
        "--symbols-text",
        action="store_true",
        help="Imprime la tabla de simbolos en formato tabular",
    )
    parser.add_argument(
        "--diagnostics",
        choices=("human", "json"),
        default="human",
        help="Formato de los diagnosticos (por omision: human)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Trata las advertencias como errores",
    )
    parser.add_argument(
        "--syntax-only",
        action="store_true",
        help="Ejecuta solo el analisis lexico y sintactico",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="No imprime el mensaje de exito",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None, stream: Optional[TextIO] = None) -> int:
    """Ejecuta el CLI y devuelve el codigo de salida."""
    argv = list(sys.argv[1:] if argv is None else argv)
    out = stream or sys.stdout

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.syntax_only and (args.tac or args.mips or args.run):
        parser.error("--syntax-only no se puede combinar con --tac, --mips o --run")
    if args.run_timeout <= 0:
        parser.error("--run-timeout debe ser mayor que cero")
    if args.run and args.diagnostics == "json":
        parser.error("use --run y --diagnostics json en ejecuciones separadas")

    source_path = Path(args.source)
    if not source_path.is_file():
        print(f"error: no se encontro el archivo '{args.source}'", file=sys.stderr)
        return 2

    options = CompileOptions(
        strict=args.strict, syntax_only=args.syntax_only,
        generate_tac=bool(args.tac), generate_mips=bool(args.mips or args.run),
        allocation=args.allocation,
    )
    result = compile_file(source_path, options)

    _write_outputs(result, args, out)

    if args.diagnostics == "json":
        json.dump(result.to_dict(), out, indent=2, ensure_ascii=False)
        out.write("\n")
    else:
        _print_human(result, args, out)

    if args.run and result.success and result.mips is not None:
        try:
            out.write(run_spim(result.mips, timeout=args.run_timeout))
        except SimulatorError as error:
            print(f"error de simulador: {error}", file=sys.stderr)
            return 1
    return result.exit_code


def _write_outputs(result: CompilationResult, args: argparse.Namespace, out: TextIO) -> None:
    """Genera los archivos solicitados aunque existan errores semanticos."""
    if result.success:
        for destination, content, label in (
            (args.tac, result.tac, "TAC"), (args.mips, result.mips, "MIPS")
        ):
            if destination and content is not None:
                target = Path(destination)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                if args.diagnostics != "json":
                    out.write(f"{label} escrito en {target}\n")
    if result.ast is not None and args.ast:
        path = write_dot(result.ast, args.ast, graph_name=result.filename)
        if args.ast == DEFAULT_AST_DOT:
            # `--ast` sin argumento: ademas del DOT se muestra el arbol en la
            # consola, para poder inspeccionarlo sin abrir Graphviz.
            out.write("\n" + result.ast.to_tree() + "\n")
        out.write(f"AST (DOT) escrito en {path}\n")

    if result.ast is not None and args.ast_json:
        target = Path(args.ast_json)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(ast_to_json(result.ast), encoding="utf-8")
        out.write(f"AST (JSON) escrito en {target}\n")

    if result.ast is not None and args.ast_image:
        dot_path = Path(args.ast or Path(args.ast_image).with_suffix(".dot"))
        if not args.ast:
            write_dot(result.ast, dot_path, graph_name=result.filename)
        image = render_image(dot_path, args.ast_image)
        if image is None:
            reason = (
                "Graphviz no esta instalado"
                if not graphviz_available()
                else "el comando 'dot' fallo"
            )
            out.write(f"Aviso: no se genero la imagen del AST ({reason}); el DOT si se genero.\n")
        else:
            out.write(f"Imagen del AST escrita en {image}\n")

    if result.symbol_table is not None and args.symbols == SYMBOLS_TO_STDOUT:
        # `--symbols` sin argumento: arbol de ambitos en la consola.
        out.write("\n" + result.symbol_table.to_tree() + "\n\n")
    elif result.symbol_table is not None and args.symbols:
        target = Path(args.symbols)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(result.symbols_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        out.write(f"Tabla de simbolos escrita en {target}\n")

    if result.symbol_table is not None and args.symbols_text:
        out.write("\n" + result.symbol_table.to_text() + "\n\n")


def _print_human(result: CompilationResult, args: argparse.Namespace, out: TextIO) -> None:
    for diagnostic in result.diagnostics:
        marker = "error" if diagnostic.severity is Severity.ERROR else "aviso"
        out.write(f"{marker}: {diagnostic.format()}\n")

    errors = result.error_count
    warnings = result.warning_count

    if result.success:
        if not args.quiet:
            summary = f"Compilacion exitosa: {result.filename}"
            if warnings:
                summary += f" ({warnings} advertencia(s))"
            out.write(summary + "\n")
        return

    parts = []
    if errors:
        parts.append(f"{errors} error(es)")
    if warnings:
        parts.append(f"{warnings} advertencia(s)")
    out.write(f"Compilacion fallida: {', '.join(parts)}.\n")
