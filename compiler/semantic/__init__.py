"""Analisis semantico: declaraciones, tipos, flujo de control y diagnosticos."""

from .analyzer import SemanticAnalyzer, SemanticResult
from .diagnostics import Code, Diagnostic, DiagnosticBag, Phase, Severity

__all__ = [
    "SemanticAnalyzer",
    "SemanticResult",
    "Diagnostic",
    "DiagnosticBag",
    "Severity",
    "Phase",
    "Code",
]
