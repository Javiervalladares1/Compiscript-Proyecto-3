"""Ejecucion real de MIPS en SPIM, con timeout y diagnosticos de simulador."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


class SimulatorError(Exception):
    pass


def run_spim(assembly: str, timeout: float = 10.0) -> str:
    executable = shutil.which("spim")
    if executable is None:
        raise SimulatorError("No se encontro SPIM en PATH. Instale SPIM o abra el .asm en MARS/QtSPIM.")
    if timeout <= 0:
        raise SimulatorError("El timeout debe ser mayor que cero.")
    with tempfile.TemporaryDirectory(prefix="compiscript-mips-") as directory:
        path = Path(directory) / "program.asm"
        path.write_text(assembly, encoding="utf-8")
        try:
            process = subprocess.run(
                [executable, "-file", str(path)], capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=timeout,
            )
        except subprocess.TimeoutExpired as error:
            raise SimulatorError(f"SPIM excedio el limite de {timeout:g} segundos.") from error
        except OSError as error:
            raise SimulatorError(f"No se pudo ejecutar SPIM: {error}") from error
    output = process.stdout
    lines = output.splitlines(keepends=True)
    loaded = next((i for i, line in enumerate(lines) if line.startswith("Loaded:")), None)
    if loaded is not None:
        output = "".join(lines[loaded + 1:])
    failures = ("spim: (parser)", "Exception occurred at", "Attempt to execute",
                "Instruction references undefined symbol", "Memory address out of bounds")
    # Los mensajes del programa pueden contener cualquier texto, incluso las
    # palabras usadas por el simulador. Los errores propios salen con exit2(1).
    if process.returncode != 0 or any(marker in process.stderr for marker in failures):
        raise SimulatorError((output + process.stderr).strip() or "SPIM termino con error.")
    return output
