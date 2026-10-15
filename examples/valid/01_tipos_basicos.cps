// Tipos basicos, promocion integer -> float y concatenacion de cadenas.
const PI: float = 3.1416;
let entero: integer = 10;
let decimal: float = 2.5;
let promovido: float = entero;          // integer se promueve a float
let suma: integer = entero + 5;
let mezcla: float = entero + decimal;   // el float domina
let texto: string = "total = " + entero;
let bandera: boolean = true;
let negado: boolean = !bandera;
let logica: boolean = bandera && !negado;
let relacion: boolean = entero < decimal;
let igualdad: boolean = entero == decimal;
let resta: float = decimal - entero;
let producto: integer = entero * 3;
let division: integer = entero / 2;
let modulo: integer = entero % 3;
print(texto + " pi=" + PI + " ok=" + logica + " " + suma + mezcla + relacion + igualdad);
print("" + resta + producto + division + modulo);
