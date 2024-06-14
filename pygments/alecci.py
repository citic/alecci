# Adapted from https://github.com/cprieto/pygments-pseudocode
import re
from pygments.lexer import RegexLexer, words, default
from pygments.style import Style
from pygments.token import Token, Comment, Keyword, Name, String, Number, Operator, Punctuation

class AlEcci(Style):
    styles = {
        Token:                  '',
        Comment:                'italic #888',
        Keyword:                'bold #005',
        Name:                   '#f00',
        Name.Class:             'bold #0f0',
        Name.Function:          '#0f0',
        String:                 'bg:#eee #111'
    }

KEYWORDS=(
    'break',
    'case',
    'catch',
    'close',
    'const',
    'continue',
    'do',
    'else',
    'end',
    'enum',
    'f128',
    'f32',
    'f64',
    'false',
    'float',
    'for',
    'foreach',
    'from',
    'function',
    'if',
    'in',
    'input',
    'join',
    'mutable',
    'mutex',
    'new',
    'of',
    'open',
    'output',
    'print',
    'procedure',
    'read',
    'record',
    'return',
    's16',
    's32',
    's64',
    's8',
    'scan',
    'seek',
    'semaphore',
    'shared',
    'signal',
    'signed',
    'then',
    'thread',
    'throw',
    'to',
    'true',
    'try',
    'u16',
    'u32',
    'u64',
    'u8',
    'unsigned',
    'wait',
    'when',
    'while',
    'write',
)

FUNCTIONS=(
    'abs',
    'arccos',
    'arcsin',
    'arctan',
    'arctan2',
    'cos',
    'div',
    'len',
    'ln',
    'log',
    'log2',
    'max',
    'min',
    'mod',
    'pow',
    'rand',
    'round',
    'sin',
    'sgn',
    'sort',
    'sqrt',
    'tan',
)

class AlEcciLexer(RegexLexer):
    name = 'AlEcci'
    aliases = ['pseudo', 'pseudocode', 'algorithm', 'algo']
    filenames = ['*.ecci', '*.alecci', '*.algo', '*.pseudo']
    mimetypes = ['text/x-algo']

    flags = re.MULTILINE | re.IGNORECASE

    name_variable = r'[a-z_]\w*'
    name_function = r'[A-Z]\w*'
    name_constant = r'[A-Z_][A-Z0-9_]*'

    tokens = {
       'root': [
            # Text
            (r'[ \t]+', Text),
            (r'\.\.\n', Text),
            # Data
            ('"', String.Double),
            # Numbers
            (r'[0-9]+\.[0-9]*(?!\.)', Number.Float),
            (r'\.[0-9]*(?!\.)', Number.Float),
            (r'[0-9]+', Number.Integer),
            (r'(?:(?:(:)?([ \t]*)(:?%s|([+\-*/&@|~]))|or|and|not|[=<>^]|:=))', Operator),
            (r'[(){}!#,.:\[\]]', Punctuation),
            (r'(?i)\b(?:null|true|false)\b', Name.Builtin),
            # keywords
            (words(KEYWORDS, prefix=r'\b', suffix=r'\b'), Keyword.Reserved),
            (rf'{name_constant}\b', Name.Constant),
            (rf'{name_function}\b', Name.Function),
            (rf'{name_variable}\b', Name.Variable),
            # built-in funtions
            (rf'\b({FUNCTIONS})\s*\b', Name.Builtin)
       ],
       'funcname': [
            (rf'(?i){name_function}\b', Name.Function),
            (r'\s+', Text),
            (r'\(', Punctuation, 'variables'),
            (r'\)', Punctuation, '#pop')
        ],
       'variables': [
            (rf'{name_constant}\b', Name.Constant),
            (rf'{name_variable}\b', Name.Variable),
            (r'\s+', Text),
            (r',', Punctuation, '#push'),
            default('#pop')
        ],
    }
