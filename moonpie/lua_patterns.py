"""Translate Lua patterns into Python regular expressions."""

import re
import string
from functools import lru_cache

from .lua_object import LuaError

CLASSES = {
    'a': string.ascii_letters,
    'c': ''.join(map(chr, range(32))) + '\x7f',
    'd': string.digits,
    'g': ''.join(map(chr, range(33, 127))),
    'l': string.ascii_lowercase,
    'p': string.punctuation,
    's': ' \t\n\r\f\v',
    'u': string.ascii_uppercase,
    'w': string.ascii_letters + string.digits,
    'x': string.hexdigits,
}
ALL_CHARS = frozenset(map(chr, range(256)))
SPECIALS = frozenset('^$*+?.([%-')
QUANTIFIERS = {'*': '*', '+': '+', '-': '*?', '?': '?'}


class Pattern:
    __slots__ = ('regex', 'anchored', 'ncaptures', 'position_captures')

    def __init__(self, regex, anchored, ncaptures, position_captures):
        self.regex = regex
        self.anchored = anchored
        self.ncaptures = ncaptures
        self.position_captures = position_captures

    def captures(self, m, whole_if_none=True):
        if self.ncaptures == 0:
            return [m.group(0)] if whole_if_none else []
        pos = self.position_captures
        return [float(m.start(g) + 1) if g in pos else m.group(g)
                for g in range(1, self.ncaptures + 1)]


def has_specials(p):
    return any(c in SPECIALS for c in p)


def _escape_set(chars):
    out = []
    for c in sorted(chars):
        out.append('\\' + c if c in '\\]^-[' else c)
    return ''.join(out)


def _char_set(chars, negate=False):
    if not chars:
        return '[\\s\\S]' if negate else '(?!)'
    return ('[^' if negate else '[') + _escape_set(chars) + ']'


def _class_chars(c):
    """Characters matched by %c inside a [set], limited to 0..255."""
    lower = c.lower()
    if lower in CLASSES:
        chars = frozenset(CLASSES[lower])
        return ALL_CHARS - chars if c.isupper() else chars
    return frozenset(c)


def _class_atom(c):
    lower = c.lower()
    if lower in CLASSES:
        return _char_set(frozenset(CLASSES[lower]), negate=c.isupper())
    return re.escape(c)


def _parse_set(p, i):
    """Parse a [set] starting at p[i] == '['; return (regex, next index)."""
    i += 1
    negate = False
    if i < len(p) and p[i] == '^':
        negate = True
        i += 1
    chars = set()
    first = True
    while True:
        if i >= len(p):
            raise LuaError("malformed pattern (missing ']')")
        c = p[i]
        if c == ']' and not first:
            i += 1
            break
        first = False
        if c == '%':
            if i + 1 >= len(p):
                raise LuaError("malformed pattern (missing ']')")
            chars |= _class_chars(p[i + 1])
            i += 2
        elif i + 2 < len(p) and p[i + 1] == '-' and p[i + 2] != ']':
            chars |= {chr(k) for k in range(ord(c), ord(p[i + 2]) + 1)}
            i += 3
        else:
            chars.add(c)
            i += 1
    return _char_set(chars, negate), i


@lru_cache(maxsize=256)
def compile_pattern(p, allow_anchor=True):
    i = 0
    n = len(p)
    out = []
    anchored = False
    if allow_anchor and p.startswith('^'):
        anchored = True
        i = 1
    ncaptures = 0
    open_captures = []
    closed = set()
    position_captures = set()
    while i < n:
        c = p[i]
        if c == '(':
            ncaptures += 1
            if p.startswith('()', i):
                position_captures.add(ncaptures)
                closed.add(ncaptures)
                out.append('()')
                i += 2
            else:
                open_captures.append(ncaptures)
                out.append('(')
                i += 1
            continue
        if c == ')':
            if not open_captures:
                raise LuaError("invalid pattern capture")
            closed.add(open_captures.pop())
            out.append(')')
            i += 1
            continue
        if c == '$' and i == n - 1:
            out.append('\\Z')
            i += 1
            continue
        if c == '%':
            if i + 1 >= n:
                raise LuaError("malformed pattern (ends with '%')")
            e = p[i + 1]
            if e == 'b':
                raise LuaError("pattern item '%b' is not supported")
            if e == 'f':
                i += 2
                if i >= n or p[i] != '[':
                    raise LuaError("missing '[' after '%f' in pattern")
                charset, i = _parse_set(p, i)
                out.append(f'(?<!{charset})(?={charset})')
                continue
            if e.isdigit():
                d = int(e)
                if d == 0 or d not in closed:
                    raise LuaError(f"invalid capture index %{d}")
                out.append(f'(?:\\{d})')
                i += 2
                continue
            atom = _class_atom(e)
            i += 2
        elif c == '.':
            atom = '.'
            i += 1
        elif c == '[':
            atom, i = _parse_set(p, i)
        else:
            atom = re.escape(c)
            i += 1
        if i < n and p[i] in QUANTIFIERS:
            atom += QUANTIFIERS[p[i]]
            i += 1
        out.append(atom)
    if open_captures:
        raise LuaError("unfinished capture")
    try:
        regex = re.compile(''.join(out), re.DOTALL)
    except re.error as e:
        raise LuaError(f"malformed pattern ({e})")
    return Pattern(regex, anchored, ncaptures, frozenset(position_captures))
