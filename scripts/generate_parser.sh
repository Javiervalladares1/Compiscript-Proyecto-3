#!/usr/bin/env bash
#
# Regenera el lexer, el parser y el visitor de Compiscript a partir de
# program/Compiscript.g4.
#
# Uso (desde cualquier ubicacion):
#
#   ./scripts/generate_parser.sh
#
# El script equivale a ejecutar, dentro del directorio program/:
#
#   antlr -Dlanguage=Python3 -visitor Compiscript.g4
#
# Dentro del contenedor Docker el comando `antlr` ya existe (ver commands/antlr).
# Fuera del contenedor se usa el JAR incluido en la raiz del repositorio.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GRAMMAR_DIR="${REPO_ROOT}/program"
GRAMMAR="Compiscript.g4"
JAR="${REPO_ROOT}/antlr-4.13.1-complete.jar"

# La version del generador debe coincidir con antlr4-python3-runtime en
# requirements.txt; de lo contrario el runtime aborta con un error de version.
EXPECTED_VERSION="4.13.1"

run_antlr() {
  if command -v antlr >/dev/null 2>&1; then
    antlr "$@"
  elif [ -f "${JAR}" ]; then
    java -jar "${JAR}" "$@"
  else
    echo "ERROR: no se encontro el comando 'antlr' ni el archivo ${JAR}" >&2
    exit 1
  fi
}

if ! command -v java >/dev/null 2>&1; then
  echo "ERROR: se requiere Java para ejecutar ANTLR." >&2
  exit 1
fi

cd "${GRAMMAR_DIR}"

echo ">> Limpiando archivos generados previamente"
rm -f Compiscript.interp Compiscript.tokens \
      CompiscriptLexer.py CompiscriptLexer.interp CompiscriptLexer.tokens \
      CompiscriptParser.py CompiscriptListener.py CompiscriptVisitor.py

echo ">> Generando lexer/parser/visitor con ANTLR (${EXPECTED_VERSION})"
run_antlr -Dlanguage=Python3 -visitor "${GRAMMAR}"

echo ">> Verificando compatibilidad de versiones"
GENERATED_VERSION="$(sed -n 's/^# Generated from .* by ANTLR \([0-9.]*\)$/\1/p' CompiscriptParser.py | head -n 1)"
if [ -n "${GENERATED_VERSION}" ] && [ "${GENERATED_VERSION}" != "${EXPECTED_VERSION}" ]; then
  echo "ADVERTENCIA: el parser se genero con ANTLR ${GENERATED_VERSION} pero" >&2
  echo "             requirements.txt fija antlr4-python3-runtime==${EXPECTED_VERSION}." >&2
fi

echo ">> Listo. Archivos generados en ${GRAMMAR_DIR}:"
ls -1 CompiscriptLexer.py CompiscriptParser.py CompiscriptVisitor.py CompiscriptListener.py
