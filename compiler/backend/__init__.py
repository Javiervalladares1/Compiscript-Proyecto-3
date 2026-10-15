"""Backend MIPS32 con asignacion de registros y marcos de pila."""

from .mips import generate_mips
from .registers import RegisterAllocator

__all__ = ["generate_mips", "RegisterAllocator"]
