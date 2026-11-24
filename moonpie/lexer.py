from .lua_object import LuaSyntaxError, str2number, num2str


KEYWORDS = frozenset({
    'and', 'break', 'do', 'else', 'elseif', 'end', 'false', 'for', 'function',
    'if', 'in', 'local', 'nil', 'not', 'or', 'repeat', 'return', 'then', 'true',
    'until', 'while',
})

OPERATORS_3 = ('...',)
OPERATORS_2 = ('==', '~=', '<=', '>=', '//', '..')
OPERATORS_1 = frozenset('+-*/%^#<>=(){}[];:,.')

NAME_START = frozenset('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_')
NAME_CHARS = NAME_START | frozenset('0123456789')
DIGITS = frozenset('0123456789')
HEX_DIGITS = frozenset('0123456789abcdefABCDEF')
SPACE = frozenset(' \t\r\n\f\v')

SIMPLE_ESCAPES = {
    'a': '\a', 'b': '\b', 'f': '\f', 'n': '\n', 'r': '\r', 't': '\t',
    'v': '\v', '\\': '\\', '"': '"', "'": "'", '\n': '\n',
}


class Token:
    __slots__ = ('type', 'value', 'line')

    def __init__(self, type, value, line):
        self.type = type
        self.value = value
        self.line = line

    def text(self):
        if self.type == 'eof':
            return '<eof>'
        if self.type == 'number':
            return num2str(self.value)
        return self.value

    def __repr__(self):
        return f"Token({self.type!r}, {self.value!r}, line {self.line})"


class Lexer:
    def __init__(self, source: str, chunkname: str = 'input'):
        self.src = source
        self.chunkname = chunkname
        self.pos = 0
        self.line = 1
        if source.startswith('#'):
            end = source.find('\n')
            self.pos = len(source) if end < 0 else end

    def error(self, msg, near=None):
        where = f" near '{near}'" if near is not None else ''
        raise LuaSyntaxError(f"{self.chunkname}:{self.line}: {msg}{where}")

    def tokenize(self):
        tokens = []
        src = self.src
        n = len(src)
        while True:
            self.skip_space_and_comments()
            if self.pos >= n:
                tokens.append(Token('eof', '<eof>', self.line))
                return tokens
            c = src[self.pos]
            line = self.line

            if c in NAME_START:
                start = self.pos
                i = start + 1
                while i < n and src[i] in NAME_CHARS:
                    i += 1
                word = src[start:i]
                self.pos = i
                tokens.append(Token(word if word in KEYWORDS else 'name', word, line))
            elif c in DIGITS or (c == '.' and self.pos + 1 < n and src[self.pos + 1] in DIGITS):
                tokens.append(Token('number', self.read_number(), line))
            elif c == '"' or c == "'":
                tokens.append(Token('string', self.read_string(c), line))
            elif c == '[' and self.long_bracket_level() is not None:
                tokens.append(Token('string', self.read_long_bracket(), line))
            else:
                op = None
                for candidate in OPERATORS_3 + OPERATORS_2:
                    if src.startswith(candidate, self.pos):
                        op = candidate
                        break
                if op is None and c in OPERATORS_1:
                    op = c
                if op is None:
                    self.error("unexpected symbol", c)
                self.pos += len(op)
                tokens.append(Token(op, op, line))

    def skip_space_and_comments(self):
        src = self.src
        n = len(src)
        while self.pos < n:
            c = src[self.pos]
            if c in SPACE:
                if c == '\n':
                    self.line += 1
                self.pos += 1
            elif c == '-' and src.startswith('--', self.pos):
                self.pos += 2
                if self.pos < n and src[self.pos] == '[' and self.long_bracket_level() is not None:
                    self.read_long_bracket()
                else:
                    end = src.find('\n', self.pos)
                    self.pos = n if end < 0 else end
            else:
                return

    def long_bracket_level(self):
        """If a long bracket ([[, [==[ ...) starts at pos, return its level."""
        src = self.src
        i = self.pos + 1
        while i < len(src) and src[i] == '=':
            i += 1
        if i < len(src) and src[i] == '[':
            return i - self.pos - 1
        if i > self.pos + 1:
            self.error("invalid long string delimiter", src[self.pos:i])
        return None

    def read_long_bracket(self):
        src = self.src
        level = self.long_bracket_level()
        start = self.pos + level + 2
        close = ']' + '=' * level + ']'
        end = src.find(close, start)
        if end < 0:
            self.error("unfinished long string/comment", '<eof>')
        text = src[start:end]
        self.line += text.count('\n')
        self.pos = end + len(close)
        if text.startswith('\r\n') or text.startswith('\n\r'):
            text = text[2:]
        elif text.startswith('\n') or text.startswith('\r'):
            text = text[1:]
        return text

    def read_number(self):
        src = self.src
        n = len(src)
        start = i = self.pos
        exponent = 'Ee'
        if src.startswith(('0x', '0X'), i):
            exponent = 'Pp'
            i += 2
        while i < n:
            c = src[i]
            if c in exponent and i + 1 < n and src[i + 1] in '+-':
                i += 2
            elif c in NAME_CHARS or c == '.':
                i += 1
            else:
                break
        text = src[start:i]
        self.pos = i
        value = str2number(text)
        if value is None:
            self.error("malformed number", text)
        return value

    def read_string(self, quote):
        src = self.src
        n = len(src)
        i = self.pos + 1
        parts = []
        while True:
            if i >= n:
                self.error("unfinished string", '<eof>')
            c = src[i]
            if c == quote:
                break
            if c == '\n':
                self.error("unfinished string", src[self.pos:i])
            if c != '\\':
                j = i
                while j < n and src[j] not in (quote, '\\', '\n'):
                    j += 1
                parts.append(src[i:j])
                i = j
                continue

            i += 1
            e = src[i] if i < n else ''
            if e in SIMPLE_ESCAPES:
                if e == '\n':
                    self.line += 1
                parts.append(SIMPLE_ESCAPES[e])
                i += 1
            elif e == 'x':
                digits = src[i + 1:i + 3]
                if len(digits) != 2 or not all(d in HEX_DIGITS for d in digits):
                    self.error("hexadecimal digit expected", '\\x' + digits)
                parts.append(chr(int(digits, 16)))
                i += 3
            elif e == 'z':
                i += 1
                while i < n and src[i] in SPACE:
                    if src[i] == '\n':
                        self.line += 1
                    i += 1
            elif e in DIGITS:
                j = i
                while j < n and j < i + 3 and src[j] in DIGITS:
                    j += 1
                code = int(src[i:j])
                if code > 255:
                    self.error("decimal escape too large", '\\' + src[i:j])
                parts.append(chr(code))
                i = j
            elif e == 'u' and src.startswith('{', i + 1):
                end = src.find('}', i + 2)
                digits = src[i + 2:end] if end > 0 else ''
                if not digits or not all(d in HEX_DIGITS for d in digits):
                    self.error("hexadecimal digit expected", '\\u{' + digits)
                parts.append(chr(int(digits, 16)))
                i = end + 1
            else:
                self.error("invalid escape sequence", '\\' + e)
        self.pos = i + 1
        return ''.join(parts)


def tokenize(source: str, chunkname: str = 'input'):
    return Lexer(source, chunkname).tokenize()
