# Compiscript — Proyecto 3: TAC y MIPS

Compilador de Compiscript en Python y ANTLR 4.13.1, con generación de código de
tres direcciones y assembler MIPS32 para SPIM/MARS.

## División de la entrega

El proyecto se distribuye en dos partes, por cantidad de archivos:

| Parte | Archivos del proyecto | Contenido |
| --- | ---: | --- |
| Primera, publicada inicialmente | 60 | Frontend completo, IR/TAC, backend MIPS, getReg(), marcos de pila y factorial ejecutable |
| Segunda, entregada en ZIP | 59 | IDE web actualizado, pruebas, documentación y ejemplos restantes |
| Total al integrar las dos | 119 | Proyecto completo |

La primera parte se puede ejecutar por sí sola desde la línea de comandos.
Para habilitar el IDE y la batería completa, integra la segunda parte en las
rutas originales de la raíz. El ZIP contiene un script `integrar.py`, un
manifiesto de hashes y las instrucciones para hacerlo.

## Requisitos

- Python 3.10 o posterior.
- SPIM en PATH para ejecutar MIPS desde el CLI.
- Java 11 o posterior únicamente para regenerar el parser; ya está generado.
- Graphviz es opcional para exportar imágenes del AST.

## Inicio rápido de la primera parte

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python program/Driver.py examples/mips/01_factorial.cps \
  --tac out/factorial.tac --mips out/factorial.asm --run
```

La salida esperada es `120`, `720`, `5040`, cada número en una línea.
Si no tienes SPIM, omite `--run` y abre el `.asm` en MARS/QtSPIM.
También puedes ejecutar el assembler directamente:

```bash
spim -file out/factorial.asm
```

Para usar la estrategia de pila:

```bash
python program/Driver.py examples/mips/01_factorial.cps \
  --allocation stack --mips out/factorial_pila.asm --run
```

Para conservar las funciones del frontend:

```bash
python program/Driver.py program/program.cps --symbols
python program/Driver.py examples/valid/01_tipos_basicos.cps --ast-json out/ast.json
python program/Driver.py examples/invalid/14_sintaxis.cps
```

El último comando debe terminar con código 1 por el error de sintaxis.

## Algoritmos de esta fase

- `compiler/ir/`: representación tipada y traducción del AST a TAC.
- `compiler/backend/mips.py`: marcos de pila, llamadas, parámetros y retornos.
- `compiler/backend/registers.py`: `getReg()`, descriptores, selección por
  siguiente uso y spill de registros a memoria.
- `compiler/backend/simulator.py`: ejecución real en SPIM con timeout.

Los temporales prefieren `$t0–$t7` y las variables `$s0–$s7`. Cada activación
reserva su propio marco; conserva `$ra`, `$fp` y los registros `$s` utilizados.
Los primeros cuatro argumentos viajan en `$a0–$a3` y el resto en pila.
`--allocation stack` guarda los resultados después de cada instrucción TAC.

La [guía de la fase 3](docs/FASE3_MIPS.md) explica la implementación, la API y
los límites del backend. Los ejemplos segundo y tercero de esa guía se
incorporan con la segunda parte.

## Después de integrar la segunda parte

```bash
bash scripts/start_ide.sh
```

Abre http://127.0.0.1:5001. El IDE muestra el AST, símbolos, TAC, MIPS y la
salida del simulador. Incluye selector de ejemplos y asignación por registros
 o por pila.

Para verificar el proyecto completo:

```bash
python -m pytest tests -q
```

La segunda parte incluye el guion del video y los scripts de demostración.
Los videos, audios, entornos virtuales y resultados generados se conservan
aparte; `out/` está excluida de Git.

## Alcance del backend

Se admiten funciones globales, recursión directa y mutua, llamadas anidadas,
retornos tempranos, tipos escalares, arreglos, matrices y control de flujo.
Clases, closures, `try/catch`, concatenación con float y otras construcciones
fuera del alcance producen un diagnóstico `GEN001` al solicitar MIPS. El
frontend mantiene su análisis semántico de esas construcciones.

Los aportes reales del equipo se documentan en `CONTRIBUTIONS.md` al integrar
la segunda parte. Cada persona conserva su propia configuración de Git.
