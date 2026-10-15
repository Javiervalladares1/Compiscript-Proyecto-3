// Salida: 120, 720, 5040 (una linea por resultado).
function factorial(n: integer): integer {
  if (n <= 1) { return 1; }
  return n * factorial(n - 1);
}

print(factorial(5));
print(factorial(6));
print(factorial(7));
