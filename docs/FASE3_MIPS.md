# Proyecto 3: codigo intermedio y generacion de MIPS

Esta entrega agrega el recorrido:

```text
archivo.cps -> lexer/parser -> AST -> analisis semantico
            -> codigo de tres direcciones (TAC) -> MIPS32 -> SPIM/MARS
```

El programa fuente conserva la sintaxis **Compiscript** del repositorio. El
PDF de ejemplos usa Decaf para ilustrar las etapas; no hace falta cambiar
de lenguaje ni copiar sus etiquetas o su distribucion de memoria.

## Ejecutar la demostracion

Desde la raiz del proyecto, con Python 3.10 o posterior:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

python program/Driver.py examples/mips/01_factorial.cps \
  --tac out/factorial.tac --mips out/factorial.asm --run
```

La ultima opcion requiere el ejecutable `spim` en `PATH`. En macOS se puede
instalar con `brew install spim`; en Debian/Ubuntu, con `sudo apt install spim`.
La generacion de archivos no requiere instalar un simulador.

La salida del programa es:

```text
120
720
5040
```

Para ejecutar el assembler por separado:

```bash
spim -file out/factorial.asm
```

En MARS: abrir `out/factorial.asm`, ensamblar y ejecutar desde `main`. El codigo
usa las llamadas al sistema comunes a SPIM/MARS: 1 (integer), 2 (float),
4 (string), 9 (heap), 10 (salida) y 17 (salida con error). Las pruebas automatizadas se ejecutan en
**SPIM**; no se ha automatizado la interfaz de MARS. Se incluyen `nop` despues
de saltos para respetar los branch delay slots; no se usa el modo de delayed
loads de SPIM.

Otros casos de demostracion:

```bash
python program/Driver.py examples/mips/02_llamadas_y_parametros.cps \
  --tac out/llamadas.tac --mips out/llamadas.asm --run

python program/Driver.py examples/mips/03_control_y_memoria.cps \
  --tac out/control.tac --mips out/control.asm --run

python program/Driver.py examples/mips/01_factorial.cps \
  --allocation stack --mips out/factorial_pila.asm --run
```

El segundo ejemplo imprime `21`, `55`, `13`. El tercero imprime `suma=12`,
`true`, `3.75000000`, `7`, `1`, cada resultado en una linea. El formato de
los decimales lo decide el simulador.

## Cumplimiento de los tres requisitos

| Requisito | Implementacion | Evidencia |
| --- | --- | --- |
| Secuencias de llamada y retorno | `compiler/backend/mips.py`: `function`, `call`, instrucciones `return` | Factorial, Fibonacci y recursion mutua; prueba de restauracion de registros y pila |
| Asignacion de registros y uso de pila | `compiler/backend/registers.py`: `RegisterAllocator.getReg`, `spill`, `flush` | Presion con 24 argumentos, spills y ejecucion en ambos modos |
| Assembler ejecutable en herramienta externa | `generate_mips`, CLI `--mips` y `--run`, `compiler/backend/simulator.py` | Salidas verificadas por SPIM, errores de assembler y timeout |

## Codigo de tres direcciones

`compiler/ir/model.py` define operandos tipados (`Place`, `Constant`),
instrucciones, funciones y programa. `compiler/ir/generator.py` traduce el AST
ya validado a ese modelo. El backend recibe **IRProgram**, sin recorrer de
nuevo el AST.

Ejemplo conceptual:

```text
_t1 = n
_t2 = _t1 - 1
param _t2
_t3 = call factorial, 1
_t4 = n
_t5 = _t4 * _t3
return _t5
```

El archivo real usa nombres unicos por simbolo y funcion. Los parametros de
llamada se representan juntos en la instruccion IR y se muestran como `param`
en el TAC. Los saltos usan etiquetas e `ifz`; las funciones usan `BeginFunc`,
`call`, `return` y `EndFunc`.

Las lecturas de variables se copian a temporales antes de continuar la
evaluacion. Asi `x + cambiarX()` usa el valor de `x` que habia antes de la
llamada. Los argumentos se evaluan de izquierda a derecha. `&&`, `||` y `?:`
usan saltos y solamente evaluan la rama que corresponde.

## Convencion de llamadas y marcos de pila

La convencion interna toma las categorias de registros de MIPS y usa un area
de argumentos de al menos 16 bytes. No pretende interoperar con bibliotecas
binarias externas ni implementar la ABI hard-float completa.

| Registro | Uso |
| --- | --- |
| `$a0-$a3` | Primeras cuatro palabras de argumentos |
| Pila del llamador | Argumentos desde el quinto, en `4 * indice($sp)` |
| `$v0` | Retorno integer, boolean, string o referencia de arreglo |
| `$f0` | Retorno float |
| `$t0-$t7` | Pool temporal; el llamador sincroniza antes de llamar |
| `$s0-$s7` | Pool preferido para variables; la funcion salva los que utiliza |
| `$t8-$t9` | Scratch reservado para direcciones y comprobaciones |
| `$f2`, `$f4`, `$f6` | Operaciones de precision simple COP1 |
| `$f12` | Argumento del syscall para imprimir float |
| `$fp` | Base estable del marco actual |
| `$sp` | Tope de pila; alineado a 8 bytes |
| `$ra` | Direccion de retorno de `jal` |

Cada valor ocupa una palabra de 4 bytes. Los argumentos float viajan como sus
bits IEEE 754 en palabras de registros/pila; el callee utiliza COP1 para
calcular. La conversion `integer -> float` se emite explicitamente.

El marco de una funcion tiene este orden, desde la direccion baja:

```text
$fp = $sp -> parametros, variables locales y temporales (4 bytes cada uno)
            posible padding para alinear a 8
            registros $s utilizados, guardados
            $fp anterior                       [frame_size - 8]
            $ra anterior                       [frame_size - 4]
            area de argumentos del llamador    [frame_size + ...]
```

Secuencia de llamada:

1. Guardar los valores dirty del asignador en sus hogares de memoria.
2. Reservar un area de argumentos, multiplo de 8 y de al menos 16 bytes.
3. Cargar los primeros cuatro argumentos en `$a0-$a3`; guardar el resto en pila.
4. Ejecutar `jal etiqueta` y su delay slot.
5. Recuperar el area de argumentos del caller y obtener `$v0` o `$f0`.

Secuencia de entrada y retorno:

1. Descontar el tamano del marco de `$sp`.
2. Guardar `$ra`, `$fp` y los registros `$s` utilizados.
3. Establecer `$fp` y copiar parametros a sus posiciones locales.
4. Ejecutar el cuerpo; todo `return` coloca el resultado y salta al epilogo unico.
5. Restaurar registros, recuperar `$sp` y ejecutar `jr $ra`.

Una llamada recursiva reserva **otro marco**. Los parametros y temporales de
una activacion no se almacenan en etiquetas globales, por lo que el hijo no
sobrescribe el estado del padre. Las variables de nivel superior si se ubican
en `.data` para permitir modificaciones compartidas entre funciones.

## Algoritmo getReg()

El asignador mantiene un descriptor registro -> operando, su mapa inverso y
el conjunto dirty. Cada variable o temporal tiene un hogar fijo en pila;
las globales tienen una etiqueta en `.data`. Las constantes se rematerializan.

Para cada operando:

1. Si ya tiene registro, reutilizarlo.
2. Buscar uno libre: `$t` para temporales, `$s` para variables, luego el otro pool.
3. Si no hay registros libres, elegir el operando cuyo siguiente uso queda mas
   lejos en el resto del TAC. Los operandos de la instruccion actual se protegen
   con `pinned`.
4. Si la victima esta dirty, emitir `sw` a su hogar antes de reemplazarla.
5. Cargar el operando solicitado con `lw`, `li` o `la`. Una escritura nueva se
   marca dirty sin cargar su valor anterior.

En limites de bloques y antes de llamadas se ejecuta `flush()`: sincroniza
memoria y descarta descriptores. Esto permite unir caminos de control sin
suponer que ambos dejaron los mismos valores en los mismos registros. Las
llamadas tambien pueden modificar globales, por lo que estas se recargan.

`--allocation registers` mantiene valores entre instrucciones dentro del
bloque. `--allocation stack` sincroniza despues de cada instruccion TAC,
usando registros para ejecutar cada operacion y conservando sus resultados en
memoria. Ambos modos usan el mismo marco y la misma convencion de llamadas.

Este algoritmo es conservador: reserva hogar para todos los temporales y hace
spills aunque un valor ya no vuelva a utilizarse. Es una implementacion local
con busqueda de siguiente uso, no un asignador global por coloreo de grafos.

## Alcance y errores explicitos

Se generan: funciones globales, `void`, retornos tempranos, recursion directa y
mutua, llamadas anidadas, mas de cuatro parametros, variables globales y
locales, sombreado, integer, float, boolean, string, null, operaciones
aritmeticas y comparaciones, concatenacion de strings con integer/boolean/null,
arreglos y matrices, indexacion y asignacion a elementos, `foreach`, `if`,
`while`, `do/while`, `for`, `switch` con fall-through, `break` y `continue`.
`print` agrega un salto de linea. Las cadenas usan UTF-8 terminado en NUL y la
igualdad de strings compara contenido.

Los enteros son de 32 bits con signo; suma, resta y multiplicacion conservan
los 32 bits bajos. `/` entero trunca hacia cero; `%` conserva el signo del
dividendo. Los float usan precision simple. La division por cero y los indices
fuera del arreglo se detectan en ejecucion y terminan el programa con mensaje.
Los arreglos y las cadenas creadas se reservan en heap y no se liberan durante
la ejecucion. No hay recolector de basura.

El caso de desbordamiento `-2147483648 / -1` produce `-2147483648` y su modulo
produce `0`, sin depender del comportamiento indefinido de `div`.

El backend reporta **GEN001** con ubicacion para clases/objetos, acceso a
propiedades, closures/funciones anidadas, funciones como valores, `try/catch`,
concatenacion con float, modulo float, impresion directa de arreglos y
literales fuera del rango de MIPS. Los strings no admiten NUL interno.
Los marcos o areas de argumentos que exceden los desplazamientos de 16 bits
tambien se rechazan. Para float, usar `print(valor)` separado de la cadena.

Estas construcciones siguen disponibles en el analisis del frontend.
`program/program.cps` es una demostracion semantica que contiene clases y
`try/catch`; para esta fase usar `examples/mips/`. No se genera assembler
cuando hay errores previos, advertencias con `--strict` o una construccion
fuera del alcance del backend.

El programa ejecuta las sentencias de nivel superior. Una funcion fuente
llamada `main` debe invocarse con `main();`, igual que cualquier otra funcion
de Compiscript. La etiqueta MIPS `main` es el punto de entrada del simulador.

## API Python

```python
from compiler import CompileOptions, compile_source
from compiler.backend.simulator import run_spim

result = compile_source(
    "function doble(n: integer): integer { return n * 2; } print(doble(21));",
    options=CompileOptions(generate_tac=True, generate_mips=True, allocation="registers"),
)
if result.success:
    print(result.tac)
    print(result.mips)
    print(run_spim(result.mips))  # 42
else:
    for diagnostic in result.errors:
        print(diagnostic.format())
```

`result.ir` permite consumir las instrucciones tipadas. `result.tac` y
`result.mips` tambien aparecen en `result.to_dict()`. Las opciones son
optativas: las llamadas existentes a `compile_source()` siguen ejecutando
el frontend.

## Pruebas

```bash
python -m pytest tests/test_mips.py -q
```

Las pruebas de ejecucion requieren SPIM y se marcan como omitidas si no esta
instalado. Incluyen resultados esperados independientes del assembler,
factorial, Fibonacci, recursion mutua, presion con 24 argumentos, valores que
sobreviven llamadas, sombreado, orden de evaluacion, cortocircuito, arrays,
matrices, ciclos, fall-through, floats, strings UTF-8, limites de integer,
errores en ejecucion y CLI. Una prueba instrumenta el punto de entrada para
comparar `$sp`, `$fp` y todos los `$s` antes y despues de una llamada recursiva.

El wrapper de SPIM detecta errores de assembler y ejecucion incluso si SPIM
devuelve codigo de proceso cero. El timeout se puede ajustar con
`--run-timeout SEGUNDOS` (por omision, 10). `--run` y `--diagnostics json` se
usan por separado.

## Referencias de convenciones y syscalls

- [Convencion de llamadas de SPIM](https://www.doc.ic.ac.uk/lab/secondyear/spim/node23.html)
- [Registros de CPU en SPIM](https://www.doc.ic.ac.uk/lab/secondyear/spim/node10.html)
- [Syscalls de MARS](https://dpetersanderson.github.io/Help/SyscallHelp.html)
