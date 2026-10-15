"""Generacion y representacion de codigo intermedio."""

from .model import Constant, Instruction, IRFunction, IRProgram, Place
from .generator import CodegenError, generate_ir

__all__ = ["Constant", "Instruction", "IRFunction", "IRProgram", "Place", "CodegenError", "generate_ir"]
