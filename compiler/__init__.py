"""Compilador de Compiscript: frontend y generacion TAC/MIPS opcional.

Expone la API interna reutilizable por el CLI (``program/Driver.py``) y por el
IDE (``ide/app.py``).
"""

from .pipeline import compile_file, compile_source
from .result import CompilationResult, CompileOptions

__all__ = ["compile_source", "compile_file", "CompilationResult", "CompileOptions"]
__version__ = "1.0.0"
