#!/usr/bin/env python3
"""Punto de entrada tradicional del compilador de Compiscript.

Uso:

    python3 Driver.py program.cps
    python3 Driver.py program.cps --ast ast.dot
    python3 Driver.py program.cps --symbols symbols.json
    python3 Driver.py program.cps --diagnostics json
    python3 Driver.py program.cps --strict

Toda la logica vive en el paquete ``compiler``; este archivo solo localiza la
raiz del repositorio y delega en el CLI.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from compiler.cli import main  # noqa: E402


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
