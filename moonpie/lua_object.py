"""Lua runtime values.

Lua values map onto Python values: nil -> None, booleans -> bool,
numbers -> float, strings -> str. Tables and functions use the classes below.
"""

import re


class LuaError(Exception):
    """A Lua runtime error. `value` is the Lua error object (usually a string).

    Errors raised without position information get "chunk:line:" prepended
    by the evaluator; `level` says which call level the position refers to.
    """

    def __init__(self, value, level=1, positioned=False):
        super().__init__(value)
        self.value = value
        self.level = level
        self.positioned = positioned

    def __str__(self):
        v = self.value
        if isinstance(v, str):
            return v
        if is_number(v):
            return num2str(v)
        return f"(error object is a {type_name(v)} value)"


class LuaSyntaxError(LuaError):
    def __init__(self, message):
        super().__init__(message, positioned=True)


class _BoolKey:
    """Table key stand-in for booleans, since True == 1 in Python."""
    __slots__ = ('value',)

    def __init__(self, value):
        self.value = value


_TRUE = _BoolKey(True)
_FALSE = _BoolKey(False)


def _norm(key):
    if key is True:
        return _TRUE
    if key is False:
        return _FALSE
    return key


def _denorm(key):
    if key.__class__ is _BoolKey:
        return key.value
    return key


class LuaTable:
    __slots__ = ('hash', 'metatable', '_n', '_keys', '_key_index')

    def __init__(self, items=None):
        self.hash = {}
        self.metatable = None
        self._n = 0
        self._keys = None
        self._key_index = None
        if items:
            for k, v in items.items():
                self.set(k, v)

    def get(self, key):
        if key is True or key is False:
            key = _norm(key)
        return self.hash.get(key)

    def set(self, key, value):
        if key is True or key is False:
            key = _norm(key)
        elif key is None:
            raise LuaError("table index is nil")
        elif key != key:
            raise LuaError("table index is NaN")
        h = self.hash
        if value is None:
            h.pop(key, None)
        else:
            if self._keys is not None and key not in h:
                self._keys = None
            h[key] = value

    def length(self):
        h = self.hash
        n = self._n
        if n > 0 and n not in h:
            while n > 0 and n not in h:
                n -= 1
        else:
            while (n + 1) in h:
                n += 1
        self._n = n
        return n

    def next(self, key):
        """Return (key, value) following `key`, or None at the end."""
        h = self.hash
        if self._keys is None:
            self._keys = list(h)
            self._key_index = None
        keys = self._keys
        if key is None:
            i = 0
        else:
            if self._key_index is None:
                self._key_index = {k: i for i, k in enumerate(keys)}
            i = self._key_index.get(_norm(key))
            if i is None:
                raise LuaError("invalid key to 'next'")
            i += 1
        while i < len(keys):
            k = keys[i]
            if k in h:
                return _denorm(k), h[k]
            i += 1
        return None


class LuaFunction:
    """A Lua closure: a Function AST node plus the scope it was created in."""
    __slots__ = ('node', 'closure')

    def __init__(self, node, closure):
        self.node = node
        self.closure = closure


class LuaBuiltin:
    """A function implemented in Python. `fn(*args)` returns a list or None."""
    __slots__ = ('name', 'fn')

    def __init__(self, name, fn):
        self.name = name
        self.fn = fn


def is_number(v):
    c = v.__class__
    return c is float or c is int


def type_name(v):
    if v is None:
        return 'nil'
    c = v.__class__
    if c is bool:
        return 'boolean'
    if c is float or c is int:
        return 'number'
    if c is str:
        return 'string'
    if c is LuaTable:
        return 'table'
    if c is LuaFunction or c is LuaBuiltin:
        return 'function'
    return 'userdata'


def num2str(n):
    if n != n:
        return 'nan'
    if n == float('inf'):
        return 'inf'
    if n == float('-inf'):
        return '-inf'
    return '%.14g' % n


def tostr(v):
    """tostring() without metamethods."""
    if v is None:
        return 'nil'
    c = v.__class__
    if c is str:
        return v
    if c is bool:
        return 'true' if v else 'false'
    if c is float or c is int:
        return num2str(v)
    if c is LuaTable:
        return 'table: 0x%08x' % id(v)
    if c is LuaFunction or c is LuaBuiltin:
        return 'function: 0x%08x' % id(v)
    return str(v)


_DEC_RE = re.compile(r'[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?')
_HEX_RE = re.compile(r'[+-]?0[xX](?:[0-9a-fA-F]+\.?[0-9a-fA-F]*|\.[0-9a-fA-F]+)(?:[pP][+-]?[0-9]+)?')
_LUA_SPACE = ' \f\n\r\t\v'


def str2number(s):
    """Convert a string to a number using Lua's rules; None if not numeric."""
    s = s.strip(_LUA_SPACE)
    if _DEC_RE.fullmatch(s):
        return float(s)
    if _HEX_RE.fullmatch(s):
        return float.fromhex(s)
    return None


def tonum(v):
    """Coerce a value to a number for arithmetic; None if not possible."""
    c = v.__class__
    if c is float:
        return v
    if c is int:
        return float(v)
    if c is str:
        return str2number(v)
    return None


def truthy(v):
    return v is not None and v is not False
