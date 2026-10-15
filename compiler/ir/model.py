"""Representacion tipada de codigo de tres direcciones (TAC)."""

from __future__ import annotations

from dataclasses import dataclass, field
import json

from ..ast.nodes import SourceSpan
from ..types.types import Type, VOID


@dataclass(frozen=True)
class Place:
    name: str
    type: Type
    storage: str = "temporary"

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True)
class Constant:
    value: int | float | str | bool | None
    type: Type

    def __str__(self) -> str:
        if self.value is None:
            return "null"
        return json.dumps(self.value, ensure_ascii=False)


Operand = Place | Constant


@dataclass
class Instruction:
    op: str
    result: Place | None = None
    args: tuple[Operand, ...] = ()
    target: str = ""
    span: SourceSpan | None = None

    def __str__(self) -> str:
        a = [str(arg) for arg in self.args]
        lhs = f"{self.result} = " if self.result else ""
        if self.op == "label":
            return f"{self.target}:"
        if self.op == "jump":
            return f"goto {self.target}"
        if self.op == "ifz":
            return f"ifz {a[0]} goto {self.target}"
        if self.op == "call":
            params = "".join(f"param {arg}\n    " for arg in a)
            return f"{params}{lhs}call {self.target}, {len(a)}"
        if self.op == "return":
            return "return" + (f" {a[0]}" if a else "")
        if self.op == "copy":
            return lhs + a[0]
        if len(a) == 2 and self.op in {"+", "-", "*", "/", "%", "<", "<=", ">", ">=", "==", "!="}:
            return f"{lhs}{a[0]} {self.op} {a[1]}"
        return lhs + self.op + (" " + ", ".join(a) if a else "")


@dataclass
class IRFunction:
    name: str
    return_type: Type = VOID
    parameters: list[Place] = field(default_factory=list)
    places: list[Place] = field(default_factory=list)
    instructions: list[Instruction] = field(default_factory=list)


@dataclass
class IRProgram:
    globals: list[Place] = field(default_factory=list)
    functions: list[IRFunction] = field(default_factory=list)

    def to_text(self) -> str:
        lines = ["# Compiscript - codigo de tres direcciones"]
        for place in self.globals:
            lines.append(f"global {place}: {place.type}")
        for function in self.functions:
            lines.extend(["", f"{function.name}:", "    BeginFunc"])
            for index, parameter in enumerate(function.parameters):
                lines.append(f"    {parameter} = argument {index}")
            for instruction in function.instructions:
                prefix = "" if instruction.op == "label" else "    "
                lines.append(prefix + str(instruction))
            lines.append("    EndFunc")
        return "\n".join(lines) + "\n"
