"""getReg(): descriptores de registros, eleccion de victima y spill a pila.

Los temporales prefieren $t0-$t7; las variables prefieren $s0-$s7.
$t8/$t9 quedan reservados para direcciones y comprobaciones del backend.
Cada Place tiene un hogar en memoria. El descriptor dirty indica si ese
hogar debe actualizarse antes de reutilizar el registro.
"""

from __future__ import annotations

from collections.abc import Callable

from ..ir.model import IRFunction, Operand, Place


TEMPORARY_REGISTERS = tuple(f"$t{i}" for i in range(8))
SAVED_REGISTERS = tuple(f"$s{i}" for i in range(8))


class RegisterAllocator:
    def __init__(self, function: IRFunction, emit: Callable[[str], None],
                 load: Callable[[str, Operand], None], store: Callable[[str, Place], None]):
        self.function = function
        self.emit = emit
        self.load = load
        self.store = store
        self.registers: dict[str, Operand] = {}
        self.locations: dict[Operand, str] = {}
        self.dirty: set[str] = set()
        self.used_saved: set[str] = set()
        self.position = 0
        self.spills = 0

    def next_use(self, value: Operand) -> float:
        for index in range(self.position + 1, len(self.function.instructions)):
            instruction = self.function.instructions[index]
            if value in instruction.args:
                return float(index)
            if instruction.result == value:
                break
        return float("inf")

    def getReg(self, value: Operand, *, write: bool = False,
               pinned: tuple[str, ...] = ()) -> str:
        """Reutiliza, toma un registro libre o derrama la victima mas lejana.

        pinned protege los operandos de la instruccion actual. Los registros
        reservados, argumentos y resultados nunca pertenecen al pool.
        """
        register = self.locations.get(value)
        if register is None:
            is_variable = isinstance(value, Place) and value.storage != "temporary"
            preferred = SAVED_REGISTERS if is_variable else TEMPORARY_REGISTERS
            secondary = TEMPORARY_REGISTERS if is_variable else SAVED_REGISTERS
            candidates = [reg for reg in (*preferred, *secondary) if reg not in pinned]
            register = next((reg for reg in candidates if reg not in self.registers), None)
            if register is None:
                register = max(candidates, key=lambda reg: self.next_use(self.registers[reg]))
                self.spill(register)
            self.registers[register] = value
            self.locations[value] = register
            if register in SAVED_REGISTERS:
                self.used_saved.add(register)
            if not write:
                self.load(register, value)
        if write:
            self.dirty.add(register)
        return register

    def spill(self, register: str) -> None:
        value = self.registers[register]
        if register in self.dirty:
            assert isinstance(value, Place)
            self.emit(f"# spill {value} desde {register}")
            self.store(register, value)
            self.spills += 1
        self.dirty.discard(register)
        del self.locations[value]
        del self.registers[register]

    def flush(self) -> None:
        """Sincroniza memoria y olvida descriptores en llamadas y aristas CFG."""
        for register in list(self.registers):
            self.spill(register)
