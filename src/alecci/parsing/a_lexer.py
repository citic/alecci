import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
import ply.lex as lex

from . import globals

reserved = {
    'procedure' : 'PROCEDURE',
    'function' : 'FUNCTION',
    'return' : 'RETURN',
    'end' : 'END',
    # Data types
    'as'  : 'AS',
    'array' : 'ARRAY',
    'pointer' : 'POINTER',
    'record' : 'RECORD',
    'enum' : 'ENUM',
    'of' : 'OF',
    'to' : 'TO',
    'pointed' : 'POINTED',
    'by'    : 'BY',
    # Input/output
    'scan' : 'SCAN',
    'print' : 'PRINT',
    # # Function-like operators
    # 'mod' : 'MOD_FUNCTION',
    # 'log' : 'LOG',
    # 'sqrt' : 'SQRT',
    # Flow control
    'if' : 'IF',
    'then' : 'THEN',
    'else' : 'ELSE',
    'while' : 'WHILE',
    'do' : 'DO',
    'for' : 'FOR',
    'break' : 'BREAK',
    # Variable declarations
    'shared' : 'SHARED',
    'mutable' : 'MUTABLE',
    'const' : 'CONST',
    'atomic' : 'ATOMIC',
    # Concurrency keywords
    'thread' : 'THREAD',
    'semaphore' : 'SEMAPHORE',
    'mutex' : 'MUTEX',
    'barrier' : 'BARRIER',
    # Dynamic typing
    'variant' : 'VARIANT',
    # 'wait' : 'WAIT',     
    # 'signal' : 'SIGNAL',
    # 'join_thread' : 'JOIN_THREAD',
    # 'join_threads' : 'JOIN_THREADS',
}

tokens = [
    'FLOAT',
    'PLUS',
    'MINUS',
    'TIMES',
    'DIVIDE',
    'INT_DIVIDE',
    'EXPONENT',
    'MOD',
    'EQUALS',
    'NEQUALS',
    'LESS',
    'LESS_EQ',
    'GREATER',
    'GREATER_EQ',
    'NOT',
    'AND',
    'OR',
    'BITWISE_NOT',
    'BITWISE_AND',
    'BITWISE_OR',
    'BITWISE_XOR',
    'BITWISE_LSHIFT',
    'BITWISE_RSHIFT',
    'COMMA',
    'LPAREN',
    'RPAREN',
    'LBRACKET',
    'RBRACKET',
    'LBRACE',
    'RBRACE',
    'INTEGER',
    'ASSIGN', 
    'STRING',
    'FORMATTED_STRING',
    'TYPE',
    'REFERENCE',
    'ID'
] + list (reserved.values())



# Regular expression rules for simple tokens
literals = {}

t_REFERENCE = r'@'

# Arithmetic operators
t_PLUS     = r'\+'
t_MINUS    = r'-'
t_TIMES    = r'\*'
t_DIVIDE   = r'\/'
t_INT_DIVIDE   = r'\#'
t_EXPONENT = r'\^'
t_MOD      = r'\%'


# Logic operators
t_EQUALS   = r'='
t_NEQUALS  = r'!='
t_LESS     = r'<'
t_LESS_EQ  = r'<='
t_GREATER  = r'>'
t_GREATER_EQ = r'>='
t_NOT     = r'not'
t_AND     = r'and'
t_OR      = r'or'


# Bitwise operators
t_BITWISE_NOT = r'~'
t_BITWISE_AND = r'&'
t_BITWISE_OR  = r'\|'
t_BITWISE_XOR = r'xor'
t_BITWISE_LSHIFT = r'<<'
t_BITWISE_RSHIFT = r'>>'

t_COMMA    = r','
t_LPAREN   = r'\('
t_RPAREN   = r'\)'
t_LBRACKET = r'\['
t_RBRACKET = r'\]'
t_LBRACE = r'\{'
t_RBRACE = r'\}'
t_ASSIGN   = r':='
t_STRING   = r'\"[^\n\"]*\"'
t_FORMATTED_STRING   = r'\`[^\n\`]*\`'

# Create complex type rule. Move there thread, semaphore, etc
def t_TYPE( t:lex.LexToken):
    r'int|float|bool|char|i8|i16|i32|i64|u8|u16|u32|u64|f32|f64|f128|string'
    return t

def t_COMMENT(t:lex.LexToken) :
    r'//[^\n]*'
    pass

def t_FLOAT( t:lex.LexToken):
    r'((\d+\.\d*)|(\d*\.\d+))([eE][+-]?\d+)?'
    t.value = float(t.value)
    return t

def t_INTEGER( t:lex.LexToken):
    r'\d+'
    t.value = int(t.value)
    return t

def t_ID( t):
    r'[a-zA-Z_][a-zA-Z_0-9]*'
    t.type = reserved.get(t.value,'ID')    # Check for reserved words
    return t


# Define a rule so we can track line numbers
def t_newline( t:lex.LexToken):
    r'\n+'
    t.lexer.lineno += len(t.value)


# A string containing ignored characters (spaces and tabs)
t_ignore  = ' \t'

def t_error( p:lex.LexToken):
    if p:
        # Get the input text from lexer
        data = p.lexer.lexdata
        
        # Find the line with the error
        last_newline = data.rfind('\n', 0, p.lexpos) 
        line_start = last_newline + 1
        next_newline = data.find('\n', p.lexpos)
        if next_newline < 0:
            next_newline = len(data)
        
        # Calculate column position (position within the line)
        column = p.lexpos - line_start
        
        
        print(f"{globals.filename}:{p.lineno}:{column+1}: syntax error: unexpected token '{p.value[0]}'")

    else:
        print("Syntax error at EOF")
    p.lexer.skip(1)


lexer = lex.lex()

# Test it output
def input(data):
    lex.lexer.input(data)
    while True:
            tok = lex.lexer.token()
            if not tok:
                break
            print(tok)
        


if __name__ == "__main__" :
    data = ''
    with open("./examples/create_threads_array.pseudo", "r") as file:
        data = file.read()

    lexer.input(data)
    while True:
        tok = lexer.token()
        if not tok:
            break      # No more input
        print(tok)