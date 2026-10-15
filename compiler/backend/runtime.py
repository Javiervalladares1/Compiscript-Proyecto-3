"""Rutinas auxiliares para SPIM/MARS. Son leaf y preservan todos los $s."""

RUNTIME_DATA = '''
_cs_newline: .byte 10, 0
_cs_true: .asciiz "true"
_cs_false: .asciiz "false"
_cs_null: .asciiz "null"
_cs_div_message: .asciiz "Error de ejecucion: division por cero\\n"
_cs_bounds_message: .asciiz "Error de ejecucion: indice fuera del arreglo\\n"
'''

RUNTIME_TEXT = '''
# Comparacion de strings por contenido; null solamente equivale a null.
_cs_streq:
    beq $a0, $a1, _cs_streq_yes
    nop
    beq $a0, $zero, _cs_streq_no
    nop
    beq $a1, $zero, _cs_streq_no
    nop
_cs_streq_loop:
    lbu $t0, 0($a0)
    lbu $t1, 0($a1)
    bne $t0, $t1, _cs_streq_no
    nop
    beq $t0, $zero, _cs_streq_yes
    nop
    addiu $a0, $a0, 1
    addiu $a1, $a1, 1
    b _cs_streq_loop
    nop
_cs_streq_yes:
    li $v0, 1
    jr $ra
    nop
_cs_streq_no:
    move $v0, $zero
    jr $ra
    nop

# a0 + a1 -> v0; nueva cadena en heap (syscall 9).
_cs_concat:
    bne $a0, $zero, _cs_concat_left
    nop
    la $a0, _cs_null
_cs_concat_left:
    bne $a1, $zero, _cs_concat_right
    nop
    la $a1, _cs_null
_cs_concat_right:
    move $t0, $a0
    move $t1, $a1
    move $t2, $a0
    move $t3, $a1
    li $t4, 1
_cs_concat_count1:
    lbu $t5, 0($t0)
    beq $t5, $zero, _cs_concat_count2
    nop
    addiu $t4, $t4, 1
    addiu $t0, $t0, 1
    b _cs_concat_count1
    nop
_cs_concat_count2:
    lbu $t5, 0($t1)
    beq $t5, $zero, _cs_concat_alloc
    nop
    addiu $t4, $t4, 1
    addiu $t1, $t1, 1
    b _cs_concat_count2
    nop
_cs_concat_alloc:
    move $a0, $t4
    li $v0, 9
    syscall
    move $t0, $v0
_cs_concat_copy1:
    lbu $t5, 0($t2)
    beq $t5, $zero, _cs_concat_copy2
    nop
    sb $t5, 0($t0)
    addiu $t2, $t2, 1
    addiu $t0, $t0, 1
    b _cs_concat_copy1
    nop
_cs_concat_copy2:
    lbu $t5, 0($t3)
    sb $t5, 0($t0)
    beq $t5, $zero, _cs_concat_done
    nop
    addiu $t3, $t3, 1
    addiu $t0, $t0, 1
    b _cs_concat_copy2
    nop
_cs_concat_done:
    jr $ra
    nop

# Entero con signo a0 -> string v0. Trabaja con negativos para INT_MIN.
_cs_itoa:
    move $t0, $a0
    slt $t1, $t0, $zero
    bne $t1, $zero, _cs_itoa_alloc
    nop
    subu $t0, $zero, $t0
_cs_itoa_alloc:
    li $a0, 12
    li $v0, 9
    syscall
    addiu $t2, $v0, 11
    sb $zero, 0($t2)
    li $t3, 10
_cs_itoa_digits:
    div $zero, $t0, $t3
    mfhi $t4
    mflo $t0
    li $t5, 48
    subu $t4, $t5, $t4
    addiu $t2, $t2, -1
    sb $t4, 0($t2)
    bne $t0, $zero, _cs_itoa_digits
    nop
    beq $t1, $zero, _cs_itoa_done
    nop
    addiu $t2, $t2, -1
    li $t4, 45
    sb $t4, 0($t2)
_cs_itoa_done:
    move $v0, $t2
    jr $ra
    nop

_cs_divzero:
    la $a0, _cs_div_message
    b _cs_runtime_error
    nop
_cs_bounds:
    la $a0, _cs_bounds_message
_cs_runtime_error:
    li $v0, 4
    syscall
    li $a0, 1
    li $v0, 17
    syscall
'''
