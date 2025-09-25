import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
import ply.yacc as yacc
from . import a_lexer 
import sys
import json
import pprint

from . import globals

tokens = a_lexer.tokens

# Function to print production objects for debugging
def print_production(p):
    """
    Debug function to print the contents of a production object.
    
    Args:
        p: The production object from PLY parser
    """
    print("Production contents:")
    for i in range(len(p)):
        print(f"  p[{i}] =", repr(p[i]))
    print("  Length =", len(p))

precedence = (
    # Assignment has lowest precedence and is right-associative
    ('right', 'ASSIGN'),
    
    # Logical OR
    ('left', 'OR'),
    
    # Logical AND
    ('left', 'AND'),
    
    # Bitwise OR
    ('left', 'BITWISE_OR'),
    
    # Bitwise XOR
    ('left', 'BITWISE_XOR'),
    
    # Bitwise AND
    ('left', 'BITWISE_AND'),
    
    # Equality operators
    ('nonassoc', 'EQUALS', 'NEQUALS'),
    
    # Relational operators
    ('nonassoc', 'LESS', 'LESS_EQ', 'GREATER', 'GREATER_EQ'),
    
    # Bit shift operators
    ('left', 'BITWISE_LSHIFT', 'BITWISE_RSHIFT'),
    
    # Additive operators
    ('left', 'PLUS', 'MINUS'),
    
    # Multiplicative operators
    ('left', 'TIMES', 'DIVIDE', 'INT_DIVIDE', 'MOD'),
    
    ('right', 'BITWISE_NOT', 'NOT'),  # Unary operators
    
    ('right', 'EXPONENT'),  # Exponentiation is right-associative
    
    # Array access and function calls have highest precedence
    ('left', 'LBRACKET', 'RBRACKET'),
    ('nonassoc', 'LPAREN', 'RPAREN')
)

def p_program(p):
    ''' program : declarations
    '''
    p[0] = {'type': 'program', 'declarations': p[1]}

def p_declarations(p):
    ''' declarations : decl
                     | declarations decl
    '''
    if len(p) == 2:
        p[0] = [p[1]]
    else:
        p[0] = p[1] + [p[2]]

def p_decl(p):
    ''' decl : procedure
                    | function
                    | record
                    | enumeration
    '''
    p[0] = p[1]

def p_body(p):
    ''' body : statement 
            | body statement
    '''
    if len(p) == 2:
        p[0] = [p[1]]
    else:
        p[0] = p[1] + [p[2]]

def p_base_type(p):
    ''' base_type : TYPE '''
    p[0] = p[1]



def p_complex_type(p):
    ''' complex_type : SEMAPHORE
                    | MUTEX
                    | BARRIER
                    | THREAD
                    | ARRAY
                    | VARIANT
                    | base_type
                    | REFERENCE complex_type
                    | pointer_to_sequence complex_type
                    | ID
    '''
    if len(p) == 2:
            p[0] = p[1]
    else:
        if p[1] == '@':
            p[0] = {'type': 'reference_type', 'target': p[2]}
        else:
            p[0] = {'type': 'pointer_type', 'depth': p[1], 'target': p[2]}

def p_statement(p):
    ''' statement : declaration
                |  assignment
                |  func_call
                |  RETURN expression
                |  if_condition
                |  for_loop
                |  while_loop
                |  BREAK WHILE
                |  BREAK FOR
                |  PRINT FORMATTED_STRING
                |  PRINT expression
                |  SCAN FORMATTED_STRING
    '''
    if p[1] == 'return':
        p[0] = {'type': 'return', 'value': p[2]}
    elif p[1] == 'break':
        p[0] = {'type': 'break'}
    elif p[1] == 'print':
        # Check if p[2] is a formatted string (starts with backtick)
        if len(p) > 2 and isinstance(p[2], str) and p[2].startswith('`'):
            p[0] = {'type': 'print', 'format': p[2]}
        else:
            p[0] = {'type': 'print', 'expression': p[2]}
    elif p[1] == 'scan':
        p[0] = {'type': 'scan', 'format': p[2]}
    else:
        p[0] = p[1]  # For declaration, assignment, funcCall, if_condition, for_loop, while_loop

def p_if_condition(p):
    ''' if_condition : IF expression THEN body END IF
                     | IF expression THEN body ELSE body END IF
    '''
    if len(p) == 7:
        p[0] = {'type': 'if', 'condition': p[2], 'then_body': p[4]}
    else:
        p[0] = {'type': 'if', 'condition': p[2], 'then_body': p[4], 'else_body': p[6]}

def p_for_loop(p):
    ''' for_loop : FOR ID ASSIGN expression TO expression DO body END FOR
    '''
    p[0] = {
        'type': 'for',
        'iterator': p[2],
        'start': p[4],
        'end': p[6],
        'body': p[8]
    }

def p_while_loop(p):
    ''' while_loop : WHILE expression DO body END WHILE
    '''
    p[0] = {'type': 'while', 'condition': p[2], 'body': p[4]}


def p_init(p):
    ''' init : ASSIGN expression
             | EQUALS expression
             | AS complex_type ASSIGN expression
             | AS complex_type EQUALS expression
             | AS complex_type
    '''
    # print(p[1], p[2])
    #print_production(p)
    if len(p) == 3:  # Datatype or initialization
        if p[1] == ':=' or p[1] == '=':
            p[0] = {'type': 'init', 'var_type': None, 'value': p[2], 'assignment_op': p[1]}
        else:  
            p[0] = {'type': 'init', 'var_type': p[2], 'value': None}
    else:  # Datatype and initialization
        p[0] = {'type': 'init', 'var_type': p[2], 'value': p[4], 'assignment_op': p[3]}



def p_declaration(p):
    ''' declaration : SHARED CONST ID init 
            | SHARED MUTABLE ID init
            | MUTABLE ID init
            | CONST ID init
            | ATOMIC ID init
    '''
    # Create a dictionary to represent the declaration
    declaration = {
        'type': 'declaration',
        'name': None,
        'shared': False,
        'const': False,  # Default to mutable
        'atomic' : False,
        'init': None
    }
    if len(p) == 5:  # SHARED CONST ID init or SHARED MUTABLE ID init
        declaration['shared'] = True
        if p[2] == 'const':
            declaration['const'] = True
        else:  # MUTABLE
            declaration['const'] = False  # Explicitly mark as not constant
        declaration['name'] = p[3]
        declaration['init'] = p[4]
    else:  # MUTABLE ID init or CONST ID init
        if p[1] == 'mutable':
            declaration['const'] = False  # Explicitly mark as not constant
        elif p[1] == 'const':  # CONST
            declaration['const'] = True
        elif p[1] == 'atomic':  # ATOMIC
            declaration['const'] = False  # Atomic variables are mutable
        declaration['name'] = p[2]
        declaration['init'] = p[3]
    
    p[0] = declaration


def p_record_members(p):
    '''record_members : ID AS complex_type
            | record_members ID AS complex_type
    '''
    if len(p) == 4:
        p[0] = [{'name': p[1], 'type': p[3]}]
    else:
        p[0] = p[1] + [{'name': p[2], 'type': p[4]}]
        
def p_record(p):
    ''' record : RECORD ID OF record_members END RECORD
    '''
    p[0] = {'type': 'record', 'name': p[2], 'members': p[4]}

def p_enumeration_members(p):
    '''enumeration_members : ID
            | ID EQUALS INTEGER
            | enumeration_members COMMA ID 
            | enumeration_members COMMA ID EQUALS INTEGER
    '''
    if len(p) == 2:
        p[0] = [{'name': p[1]}]
    elif len(p) == 4 and p[2] == '=':
        p[0] = [{'name': p[1], 'value': p[3]}]
    elif len(p) == 4 and p[2] == ',':
        p[0] = p[1] + [{'name': p[3]}]
    else:
        p[0] = p[1] + [{'name': p[3], 'value': p[5]}]

def p_enumeration(p):
    ''' enumeration : ENUM ID OF enumeration_members END ENUM
    '''
    p[0] = {'type': 'enum', 'name': p[2], 'members': p[4]}

def p_record_initialyzer(p):
    '''record_initialyzer : LBRACE parameters RBRACE
    '''
    p[0] = {'type': 'record_init', 'values': p[2]}

def p_pointed_by_sequence(p):
    '''pointed_by_sequence : POINTED BY
            | POINTED BY pointed_by_sequence 
    '''
    if len(p) == 3:
        p[0] = 1
    else:
        p[0] = 1 + p[3]

def p_pointer_to_sequence(p):
    '''pointer_to_sequence : POINTER TO
            | POINTER TO pointer_to_sequence 
    '''
    if len(p) == 3:
        p[0] = 1
    else:
        p[0] = 1 + p[3]

def p_assignment(p):
    ''' assignment : ID ASSIGN expression
            | pointed_by_sequence ID ASSIGN expression
            | ID ASSIGN REFERENCE expression
            | ID LBRACKET expression RBRACKET ASSIGN expression
    ''' 
    if len(p) == 4:
        p[0] = {'type': 'assignment', 'target': p[1], 'value': p[3]}
    elif len(p) == 5 and p[3] == '@':
        p[0] = {'type': 'assignment', 'target': p[1], 'value': {'type': 'reference', 'expr': p[4]}}
    elif len(p) == 5 and p[1] == 'pointed_by_sequence':
        p[0] = {'type': 'assignment', 'target': {'type': 'dereference', 'depth': p[1], 'id': p[2]}, 'value': p[4]}
    elif len(p) == 7:  # Array assignment: ID LBRACKET expression RBRACKET ASSIGN expression
        p[0] = {'type': 'assignment', 'target': {'type': 'array_access', 'array': p[1], 'index': p[3]}, 'value': p[6]}

# Fix for signal token
# Preguntar cómo funcionan las variables atómicas a nivel de CPU
def p_func_call(p):
    '''func_call : complex_type LPAREN parameters RPAREN
            |  complex_type LPAREN RPAREN
    '''
    #print(f"funcCall: {p[1]}") 
    if len(p) == 5:
        p[0] = {'type': 'function_call', 'name': p[1], 'arguments': p[3]}
    else:
        p[0] = {'type': 'function_call', 'name': p[1], 'arguments': []}


# TODO: Move function-style operators to library functions. Remove from grammar
def p_expression(p):
    '''expression : INTEGER
            | STRING
            | FLOAT
            | expression PLUS expression
            | expression MINUS expression
            | expression TIMES expression
            | expression DIVIDE expression
            | expression INT_DIVIDE expression
            | expression EXPONENT expression
            | expression MOD expression
            | expression EQUALS expression
            | expression NEQUALS expression
            | expression LESS expression
            | expression LESS_EQ expression
            | expression GREATER expression
            | expression GREATER_EQ expression
            | expression NOT expression
            | expression AND expression
            | expression OR expression
            | expression BITWISE_NOT expression
            | expression BITWISE_AND expression
            | expression BITWISE_OR expression
            | expression BITWISE_XOR expression
            | expression BITWISE_LSHIFT expression
            | expression BITWISE_RSHIFT expression
            | LPAREN expression RPAREN
            | ID LBRACKET expression RBRACKET
            | func_call          
            | pointed_by_sequence ID
            | pointer_to_sequence complex_type
            | record_initialyzer
            | ID
            '''
    if len(p) == 2:
        if type(p[1]) == dict:  # It's already a structured node like funcCall or record_initializer
            p[0] = p[1]
        else:
            p[0] = {'type': 'literal', 'value': p[1]}
    elif len(p) == 3 and p[1] == 'pointed_by_sequence' :
        p[0] = {'type': 'dereference', 'depth': p[1], 'id': p[2]}
    elif len(p) == 3 and p[1] == 'pointer_to_sequence':
        p[0] = {'type': 'pointer_type', 'depth': p[1], 'target': p[2]}
    elif len(p) == 4 and p[1] == '(':
        p[0] = p[2]
    elif len(p) == 5 and p[2] == '[':
        p[0] = {'type': 'array_access', 'array': p[1], 'index': p[3]}
    elif len(p) == 4:
        p[0] = {'type': 'binary_op', 'op': p[2], 'left': p[1], 'right': p[3]}

                  

# TODO: Remove all shared version from arguments
# TODO: Trabajo futuro agregar argumentos por defecto
def p_argument(p):
    '''
    argument : ID
            | REFERENCE ID
            | ID AS complex_type
            | REFERENCE ID AS complex_type
            | CONST ID
            | CONST REFERENCE ID
            | MUTABLE ID
            | MUTABLE REFERENCE ID
            | CONST ID AS complex_type
            | CONST REFERENCE ID AS complex_type
            | MUTABLE ID AS complex_type
            | MUTABLE REFERENCE ID AS complex_type
    '''
    # Creating a dictionary to represent the argument
    arg = {'type': 'argument', 'reference' : False, 'shared': False,'const': True, 'arg_type': None}
    
    idx = 1
    
    # Modifiers
    while idx < len(p) and p[idx] in ['CONST', 'MUTABLE', 'REFERENCE']:
        if p[idx] == 'const':
            arg['const'] = True
        elif p[idx] == 'mutable':
            arg['const'] = False
        elif p[idx] == '@':
            arg['reference'] = True
        idx += 1
    
    # Get ID (should always be present)
    arg['id'] = p[idx]
    idx += 1
    
    # Check for type specification
    if idx < len(p) and p[idx] == 'as':
        arg['arg_type'] = p[idx + 1]
    
    p[0] = arg

def p_arguments(p):
    '''arguments : argument
           | arguments COMMA argument
    '''
    if len(p) == 2:
        p[0] = [p[1]]
    else:
        p[0] = p[1] + [p[3]]

def p_parameters(p):
    '''parameters : expression
            | parameters COMMA expression
    '''
    if len(p) == 2:
        p[0] = [p[1]]
    else:
        p[0] = p[1] + [p[3]]

def p_procedure(p):
    ''' procedure : PROCEDURE ID LPAREN arguments RPAREN body END PROCEDURE
                    | PROCEDURE ID LPAREN RPAREN body END PROCEDURE
    '''
    if len(p) == 9:
        p[0] = {'type': 'procedure', 'name': p[2], 'arguments': p[4], 'body': p[6]}
    else:
        p[0] = {'type': 'procedure', 'name': p[2], 'arguments': [], 'body': p[5]}

def p_function(p):
    ''' function : FUNCTION ID LPAREN arguments RPAREN body END FUNCTION
                | FUNCTION ID LPAREN RPAREN body END FUNCTION
    '''
    if len(p) == 9:
        p[0] = {'type': 'function', 'name': p[2], 'arguments': p[4], 'body': p[6]}
    else:
        p[0] = {'type': 'function', 'name': p[2], 'arguments': [], 'body': p[5]}

def p_error(p):
    if p:
        # Get the input text from lexer
        data = p.lexer.lexdata
        
        # Find the line with the error
        last_newline = data.rfind('\n', 0, p.lexpos) 
        line_start = last_newline + 1
        next_newline = data.find('\n', p.lexpos)
        if next_newline < 0:
            next_newline = len(data)
        
        # Get the line content
        error_line = data[line_start:next_newline]
        
        # Calculate column position (position within the line)
        column = p.lexpos - line_start
        
        # Create pointer to error position
        pointer = ' ' * column + '^'
        
        print(f"\n{globals.filename}:{p.lineno}:{column+1}: syntax error: unexpected token '{p.value}'")
        print(f"{error_line}")
        print(pointer)
    else:
        print("Syntax error at EOF")
        


def appendByKey(dictonary, key, value):
  dictonary[key].insert(0,value)
  return dictonary
  
def pretty_print_ast(ast, indent=0):
    """
    Pretty prints an abstract syntax tree (AST) with proper indentation.
    
    Args:
        ast: The AST to print (can be a dictionary, list, or primitive value)
        indent: The current indentation level (default is 0)
    """
    if isinstance(ast, dict):
        print(" " * indent + "{")
        for key, value in ast.items():
            print(" " * (indent + 2) + f"{key}:", end=" ")
            if isinstance(value, (dict, list)):
                print()
                pretty_print_ast(value, indent + 4)
            else:
                print(repr(value))
        print(" " * indent + "}")
    elif isinstance(ast, list):
        print(" " * indent + "[")
        for item in ast:
            pretty_print_ast(item, indent + 2)
        print(" " * indent + "]")
    else:
        print(" " * indent + repr(ast))

 

############# main ############
def toAst(code):
  if globals.DEBUG:
      print(f"Parsing code: {repr(code)}")
  yacc.yacc(debug=False)  # Changed to False to reduce noise
  ast = yacc.parse(code, debug=globals.DEBUG)  # Enable debug based on global flag
  if globals.DEBUG:
      print(f"Parse result: {ast}")
  return ast

if __name__ == "__main__" :
    if len(sys.argv) > 1:
        globals.filename = sys.argv[1]
    else:
        globals.filename = input("Please enter the filename: ")

    try:
        with open(globals.filename, 'r') as file:
            data = file.read()
    except FileNotFoundError:
        print(f"File {globals.filename} not found.")
        sys.exit(1)
    
    pretty_print_ast(toAst(data))
    # toAst(data)