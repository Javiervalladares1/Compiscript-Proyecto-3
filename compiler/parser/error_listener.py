"""ErrorListener personalizado para el lexer y el parser de ANTLR.

Sustituye por completo a los listeners por defecto (que escriben en stderr con
un formato propio) y traduce los errores de ANTLR a :class:`Diagnostic`.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from antlr4.error.ErrorListener import ErrorListener

from ..semantic.diagnostics import Code, DiagnosticBag, Phase, Severity


#: Traducciones de los mensajes que produce ANTLR, para no exponer el ingles
#: interno del generador.
_TOKEN_RE = re.compile(r"^(?:'(?P<quoted>.*)'|<(?P<special>[^>]+)>)$")


def _describe_token(text: str) -> str:
    match = _TOKEN_RE.match(text.strip())
    if match is None:
        return text
    if match.group("quoted") is not None:
        return f"'{match.group('quoted')}'"
    special = match.group("special")
    if special == "EOF":
        return "el final del archivo"
    return special


def _translate(message: str) -> str:
    """Convierte el mensaje de ANTLR a un texto comprensible en espanol."""
    patterns: list[tuple[str, str]] = [
        (r"^mismatched input (\S+) expecting (.+)$", "Se encontro {0} y se esperaba {1}."),
        (r"^missing (.+) at (\S+)$", "Falta {0} antes de {1}."),
        (r"^extraneous input (\S+) expecting (.+)$", "Token inesperado {0}; se esperaba {1}."),
        (r"^no viable alternative at input (.+)$", "Construccion invalida cerca de {0}."),
        (r"^token recognition error at: (.+)$", "Caracter no reconocido: {0}."),
    ]
    for pattern, template in patterns:
        match = re.match(pattern, message)
        if match is None:
            continue
        groups = [_describe_expected(g) for g in match.groups()]
        return template.format(*groups)
    return message


def _describe_expected(text: str) -> str:
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        inner = [_describe_token(part.strip()) for part in text[1:-1].split(",")]
        if len(inner) > 4:
            inner = inner[:4] + ["..."]
        return " o ".join(inner)
    return _describe_token(text)


class CollectingErrorListener(ErrorListener):
    """Acumula errores lexicos y sintacticos en un :class:`DiagnosticBag`."""

    def __init__(self, diagnostics: DiagnosticBag, filename: str, phase: Phase) -> None:
        super().__init__()
        self._diagnostics = diagnostics
        self._filename = filename
        self._phase = phase

    @property
    def code(self) -> str:
        return Code.LEXICAL if self._phase is Phase.LEXICAL else Code.SYNTAX

    def syntaxError(  # noqa: N802 - firma impuesta por ANTLR
        self,
        recognizer: Any,
        offending_symbol: Any,
        line: int,
        column: int,
        msg: str,
        e: Optional[Exception],
    ) -> None:
        from ..semantic.diagnostics import Diagnostic

        self._diagnostics.add(
            Diagnostic(
                code=self.code,
                severity=Severity.ERROR,
                message=_translate(msg),
                file=self._filename,
                line=line,
                column=column + 1,  # ANTLR entrega la columna 0-based
                phase=self._phase,
            )
        )


def install_error_listeners(
    lexer: Any,
    parser: Any,
    diagnostics: DiagnosticBag,
    filename: str,
) -> None:
    """Reemplaza los listeners por defecto de ANTLR por los del compilador."""
    lexer.removeErrorListeners()
    lexer.addErrorListener(CollectingErrorListener(diagnostics, filename, Phase.LEXICAL))
    parser.removeErrorListeners()
    parser.addErrorListener(CollectingErrorListener(diagnostics, filename, Phase.SYNTACTIC))
