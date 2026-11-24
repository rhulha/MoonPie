import math
import re
import sys
from functools import cmp_to_key

from .lua_object import (
    LuaTable, LuaFunction, LuaBuiltin, LuaError, type_name, tostr, num2str,
    str2number, tonum, truthy, is_number,
)
from .lua_patterns import compile_pattern, has_specials

FORMAT_SPEC = re.compile(r'%([-+ #0]*)(\d{0,2})(?:\.(\d{0,2}))?([diouxXeEfFgGcqs%])')


def first(values):
    return values[0] if values else None


def arg_error(i, fname, msg):
    raise LuaError(f"bad argument #{i} to '{fname}' ({msg})")


def got(args, i):
    return type_name(args[i - 1]) if len(args) >= i else 'no value'


def check_any(args, i, fname):
    if len(args) < i:
        arg_error(i, fname, 'value expected')
    return args[i - 1]


def check_table(args, i, fname):
    v = args[i - 1] if len(args) >= i else None
    if v.__class__ is not LuaTable:
        arg_error(i, fname, f"table expected, got {got(args, i)}")
    return v


def check_number(args, i, fname):
    v = args[i - 1] if len(args) >= i else None
    n = tonum(v) if v is not None else None
    if n is None:
        arg_error(i, fname, f"number expected, got {got(args, i)}")
    return n


def check_int(args, i, fname):
    n = check_number(args, i, fname)
    if not n.is_integer():
        arg_error(i, fname, "number has no integer representation")
    return int(n)


def opt_int(args, i, fname, default):
    if len(args) < i or args[i - 1] is None:
        return default
    return check_int(args, i, fname)


def check_string(args, i, fname):
    v = args[i - 1] if len(args) >= i else None
    if v.__class__ is str:
        return v
    if is_number(v):
        return num2str(v)
    arg_error(i, fname, f"string expected, got {got(args, i)}")


def opt_string(args, i, fname, default):
    if len(args) < i or args[i - 1] is None:
        return default
    return check_string(args, i, fname)


def start_index(i, length):
    """Lua's handling of a string start position."""
    if i > 0:
        return i
    if i == 0:
        return 1
    return max(length + i + 1, 1)


def quote_string(s):
    out = ['"']
    for idx, c in enumerate(s):
        if c in '"\\':
            out.append('\\' + c)
        elif c == '\n':
            out.append('\\\n')
        elif c == '\r':
            out.append('\\r')
        elif c == '\0':
            nxt = s[idx + 1:idx + 2]
            out.append('\\000' if nxt.isdigit() else '\\0')
        elif ord(c) < 32 or ord(c) == 127:
            nxt = s[idx + 1:idx + 2]
            out.append('\\%03d' % ord(c) if nxt.isdigit() else '\\%d' % ord(c))
        else:
            out.append(c)
    out.append('"')
    return ''.join(out)


def setup_builtins(rt):
    G = rt.G

    def register(table, name, fn):
        table.set(name, LuaBuiltin(name, fn))

    # Basic functions

    def lua_print(*args):
        sys.stdout.write('\t'.join(rt.tostring(a) for a in args) + '\n')

    def lua_type(*args):
        return [type_name(check_any(args, 1, 'type'))]

    def lua_tostring(*args):
        return [rt.tostring(check_any(args, 1, 'tostring'))]

    def lua_tonumber(*args):
        if len(args) < 2 or args[1] is None:
            v = check_any(args, 1, 'tonumber')
            if is_number(v):
                return [float(v)]
            if v.__class__ is str:
                return [str2number(v)]
            return [None]
        base = check_int(args, 2, 'tonumber')
        if not 2 <= base <= 36:
            arg_error(2, 'tonumber', 'base out of range')
        s = check_string(args, 1, 'tonumber').strip(' \f\n\r\t\v').lower()
        negative = s.startswith('-')
        if negative:
            s = s[1:]
        if not s or not s.isalnum() or not s.isascii():
            return [None]
        try:
            n = float(int(s, base))
        except ValueError:
            return [None]
        return [-n if negative else n]

    def lua_assert(*args):
        if len(args) == 0:
            arg_error(1, 'assert', 'value expected')
        if truthy(args[0]):
            return list(args)
        if len(args) < 2:
            raise LuaError("assertion failed!")
        raise LuaError(args[1], positioned=True)

    def lua_error(*args):
        value = args[0] if args else None
        level = opt_int(args, 2, 'error', 1)
        if value.__class__ is str and level > 0:
            raise LuaError(value, level=level)
        raise LuaError(value, positioned=True)

    def lua_pcall(*args):
        f = check_any(args, 1, 'pcall')
        try:
            return [True, *rt.call(f, list(args[1:]))]
        except LuaError as e:
            return [False, e.value]
        except RecursionError:
            return [False, "stack overflow"]

    def lua_xpcall(*args):
        f = check_any(args, 1, 'xpcall')
        handler = check_any(args, 2, 'xpcall')
        try:
            return [True, *rt.call(f, list(args[2:]))]
        except LuaError as e:
            return [False, first(rt.call(handler, [e.value]))]
        except RecursionError:
            return [False, first(rt.call(handler, ["stack overflow"]))]

    def lua_select(*args):
        n = args[0] if args else None
        rest = args[1:]
        if n == '#':
            return [float(len(rest))]
        i = check_int(args, 1, 'select')
        if i < 0:
            i = len(rest) + i
            if i < 0:
                arg_error(1, 'select', 'index out of range')
            return list(rest[i:])
        if i == 0:
            arg_error(1, 'select', 'index out of range')
        return list(rest[i - 1:])

    def lua_next(*args):
        t = check_table(args, 1, 'next')
        r = t.next(args[1] if len(args) > 1 else None)
        return [None] if r is None else list(r)

    next_builtin = LuaBuiltin('next', lua_next)

    def lua_pairs(*args):
        t = check_any(args, 1, 'pairs')
        h = rt.getmetamethod(t, '__pairs')
        if h is not None:
            return rt.call(h, [t])[:3]
        check_table(args, 1, 'pairs')
        return [next_builtin, t, None]

    def ipairs_iter(t, i):
        i += 1
        v = rt.index(t, i)
        return [None] if v is None else [i, v]

    ipairs_builtin = LuaBuiltin('ipairs_iterator', ipairs_iter)

    def lua_ipairs(*args):
        return [ipairs_builtin, check_any(args, 1, 'ipairs'), 0.0]

    def lua_rawget(*args):
        return [check_table(args, 1, 'rawget').get(check_any(args, 2, 'rawget'))]

    def lua_rawset(*args):
        t = check_table(args, 1, 'rawset')
        check_any(args, 3, 'rawset')
        t.set(args[1], args[2])
        return [t]

    def lua_rawequal(*args):
        a = check_any(args, 1, 'rawequal')
        b = check_any(args, 2, 'rawequal')
        if is_number(a) and is_number(b):
            return [a == b]
        return [a is b or (a.__class__ is b.__class__ and a.__class__ in (str, bool) and a == b)]

    def lua_rawlen(*args):
        v = args[0] if args else None
        if v.__class__ is LuaTable:
            return [float(v.length())]
        if v.__class__ is str:
            return [float(len(v))]
        arg_error(1, 'rawlen', 'table or string expected')

    def lua_setmetatable(*args):
        t = check_table(args, 1, 'setmetatable')
        mt = args[1] if len(args) > 1 else None
        if len(args) < 2 or (mt is not None and mt.__class__ is not LuaTable):
            arg_error(2, 'setmetatable', 'nil or table expected')
        t.metatable = mt
        return [t]

    def lua_getmetatable(*args):
        return [rt.getmetatable(check_any(args, 1, 'getmetatable'))]

    def lua_unpack(*args):
        t = check_any(args, 1, 'unpack')
        i = opt_int(args, 2, 'unpack', 1)
        j = opt_int(args, 3, 'unpack', None)
        if j is None:
            j = int(rt.length(t))
        if j - i >= 1_000_000:
            raise LuaError("too many results to unpack")
        return [rt.index(t, float(k)) for k in range(i, j + 1)]

    for name, fn in [
        ('print', lua_print), ('type', lua_type), ('tostring', lua_tostring),
        ('tonumber', lua_tonumber), ('assert', lua_assert), ('error', lua_error),
        ('pcall', lua_pcall), ('xpcall', lua_xpcall), ('select', lua_select),
        ('pairs', lua_pairs), ('ipairs', lua_ipairs), ('rawget', lua_rawget),
        ('rawset', lua_rawset), ('rawequal', lua_rawequal), ('rawlen', lua_rawlen),
        ('setmetatable', lua_setmetatable), ('getmetatable', lua_getmetatable),
        ('unpack', lua_unpack),
    ]:
        register(G, name, fn)
    G.set('next', next_builtin)
    G.set('_G', G)

    # math

    def math_fn(name, fn):
        def wrapper(*args):
            x = check_number(args, 1, name)
            try:
                return [float(fn(x))]
            except ValueError:
                return [float('nan')]
            except OverflowError:
                return [x]
        return wrapper

    def math_max(*args):
        best = check_number(args, 1, 'max')
        for i in range(2, len(args) + 1):
            best = max(best, check_number(args, i, 'max'))
        return [best]

    def math_min(*args):
        best = check_number(args, 1, 'min')
        for i in range(2, len(args) + 1):
            best = min(best, check_number(args, i, 'min'))
        return [best]

    math_table = LuaTable()
    for name, fn in [('abs', abs), ('floor', math.floor), ('ceil', math.ceil),
                     ('sqrt', math.sqrt), ('sin', math.sin), ('cos', math.cos),
                     ('tan', math.tan)]:
        register(math_table, name, math_fn(name, fn))
    register(math_table, 'max', math_max)
    register(math_table, 'min', math_min)
    math_table.set('pi', math.pi)
    math_table.set('huge', float('inf'))
    G.set('math', math_table)

    # string

    def str_len(*args):
        return [float(len(check_string(args, 1, 'len')))]

    def str_upper(*args):
        return [check_string(args, 1, 'upper').upper()]

    def str_lower(*args):
        return [check_string(args, 1, 'lower').lower()]

    def str_sub(*args):
        s = check_string(args, 1, 'sub')
        n = len(s)
        i = start_index(opt_int(args, 2, 'sub', 1), n)
        j = opt_int(args, 3, 'sub', -1)
        if j < 0:
            j = n + j + 1
        elif j > n:
            j = n
        return [s[i - 1:j] if i <= j else '']

    def str_rep(*args):
        s = check_string(args, 1, 'rep')
        n = check_int(args, 2, 'rep')
        sep = opt_string(args, 3, 'rep', '')
        if n <= 0:
            return ['']
        if (len(s) + len(sep)) * n > 100_000_000:
            raise LuaError("resulting string too large")
        return [sep.join([s] * n)]

    def str_format(*args):
        fmt = check_string(args, 1, 'format')
        out = []
        argi = 1
        i = 0
        n = len(fmt)
        while i < n:
            j = fmt.find('%', i)
            if j < 0:
                out.append(fmt[i:])
                break
            out.append(fmt[i:j])
            m = FORMAT_SPEC.match(fmt, j)
            if m is None:
                raise LuaError(f"invalid conversion '{fmt[j:j + 5]}' to 'format'")
            i = m.end()
            flags, width, precision, conv = m.groups()
            if conv == '%':
                out.append('%')
                continue
            argi += 1
            if argi > len(args):
                arg_error(argi, 'format', 'no value')
            spec = '%' + flags + width + ('' if precision is None else '.' + precision)
            if conv in 'di':
                out.append((spec + 'd') % check_int(args, argi, 'format'))
            elif conv in 'ouxX':
                out.append((spec + ('d' if conv == 'u' else conv)) % check_int(args, argi, 'format'))
            elif conv == 'c':
                out.append(chr(check_int(args, argi, 'format')))
            elif conv in 'eEfFgG':
                out.append((spec + conv) % check_number(args, argi, 'format'))
            elif conv == 'q':
                v = args[argi - 1]
                if v.__class__ is str:
                    out.append(quote_string(v))
                elif is_number(v):
                    out.append(num2str(v) if float(v).is_integer() else float(v).hex())
                elif v is None or v.__class__ is bool:
                    out.append(tostr(v))
                else:
                    arg_error(argi, 'format', 'value has no literal form')
            else:
                out.append((spec + 's') % rt.tostring(args[argi - 1]))
        return [''.join(out)]

    def str_find_aux(args, fname, find):
        s = check_string(args, 1, fname)
        p = check_string(args, 2, fname)
        init = start_index(opt_int(args, 3, fname, 1), len(s))
        if init > len(s) + 1:
            return [None]
        plain = len(args) > 3 and truthy(args[3])
        if find and (plain or not has_specials(p)):
            idx = s.find(p, init - 1)
            return [None] if idx < 0 else [float(idx + 1), float(idx + len(p))]
        pat = compile_pattern(p)
        rx = pat.regex
        m = rx.match(s, init - 1) if pat.anchored else rx.search(s, init - 1)
        if m is None:
            return [None]
        if find:
            return [float(m.start() + 1), float(m.end()), *pat.captures(m, whole_if_none=False)]
        return pat.captures(m)

    def str_find(*args):
        return str_find_aux(args, 'find', True)

    def str_match(*args):
        return str_find_aux(args, 'match', False)

    def str_gmatch(*args):
        s = check_string(args, 1, 'gmatch')
        p = check_string(args, 2, 'gmatch')
        pat = compile_pattern(p, allow_anchor=False)
        state = {'pos': 0, 'last': -1}

        def step(*_):
            pos = state['pos']
            while pos <= len(s):
                m = pat.regex.search(s, pos)
                if m is None:
                    break
                if m.end() == state['last'] and m.start() == m.end():
                    pos = m.start() + 1
                    continue
                state['pos'] = state['last'] = m.end()
                return pat.captures(m)
            state['pos'] = len(s) + 1
            return [None]

        return [LuaBuiltin('gmatch_iterator', step)]

    def str_gsub(*args):
        s = check_string(args, 1, 'gsub')
        p = check_string(args, 2, 'gsub')
        repl = args[2] if len(args) > 2 else None
        rc = repl.__class__
        if is_number(repl):
            repl = num2str(repl)
            rc = str
        if rc not in (str, LuaTable, LuaFunction, LuaBuiltin):
            arg_error(3, 'gsub', f"string/function/table expected, got {got(args, 3)}")
        max_n = opt_int(args, 4, 'gsub', None)
        pat = compile_pattern(p)
        rx = pat.regex

        def replacement(m):
            whole = m.group(0)
            if rc is str:
                parts = []
                k = 0
                while k < len(repl):
                    c = repl[k]
                    if c != '%':
                        parts.append(c)
                        k += 1
                        continue
                    d = repl[k + 1:k + 2]
                    k += 2
                    if d == '%':
                        parts.append('%')
                    elif d.isdigit():
                        idx = int(d)
                        if idx == 0:
                            parts.append(whole)
                        else:
                            caps = pat.captures(m)
                            if idx > len(caps):
                                raise LuaError(f"invalid capture index %{idx} in replacement string")
                            parts.append(tostr(caps[idx - 1]))
                    else:
                        raise LuaError("invalid use of '%' in replacement string")
                return ''.join(parts)
            caps = pat.captures(m)
            if rc is LuaTable:
                v = rt.index(repl, caps[0])
            else:
                v = first(rt.call(repl, caps))
            if v is None or v is False:
                return whole
            if v.__class__ is str or is_number(v):
                return tostr(v)
            raise LuaError(f"invalid replacement value (a {type_name(v)})")

        out = []
        pos = 0
        last = -1
        count = 0
        while max_n is None or count < max_n:
            m = rx.match(s, pos) if pat.anchored else rx.search(s, pos)
            if m is None:
                break
            if m.end() == last and m.start() == m.end():
                if m.start() >= len(s):
                    break
                out.append(s[pos:m.start() + 1])
                pos = m.start() + 1
                continue
            out.append(s[pos:m.start()])
            out.append(replacement(m))
            count += 1
            pos = last = m.end()
            if pat.anchored:
                break
        out.append(s[pos:])
        return [''.join(out), float(count)]

    string_table = LuaTable()
    for name, fn in [('len', str_len), ('upper', str_upper), ('lower', str_lower),
                     ('sub', str_sub), ('rep', str_rep), ('format', str_format),
                     ('find', str_find), ('match', str_match), ('gmatch', str_gmatch),
                     ('gsub', str_gsub)]:
        register(string_table, name, fn)
    G.set('string', string_table)
    rt.string_meta = LuaTable({'__index': string_table})

    # table

    def tbl_insert(*args):
        t = check_table(args, 1, 'insert')
        e = t.length() + 1
        if len(args) == 2:
            t.set(float(e), args[1])
        elif len(args) == 3:
            pos = check_int(args, 2, 'insert')
            if pos < 1 or pos > e:
                arg_error(2, 'insert', 'position out of bounds')
            for k in range(e, pos, -1):
                t.set(float(k), t.get(float(k - 1)))
            t.set(float(pos), args[2])
        else:
            raise LuaError("wrong number of arguments to 'insert'")

    def tbl_remove(*args):
        t = check_table(args, 1, 'remove')
        size = t.length()
        pos = opt_int(args, 2, 'remove', size)
        if pos != size and not 1 <= pos <= size + 1:
            arg_error(2, 'remove', 'position out of bounds')
        value = t.get(float(pos))
        while pos < size:
            t.set(float(pos), t.get(float(pos + 1)))
            pos += 1
        t.set(float(pos), None)
        return [value]

    def tbl_concat(*args):
        t = check_table(args, 1, 'concat')
        sep = opt_string(args, 2, 'concat', '')
        i = opt_int(args, 3, 'concat', 1)
        j = opt_int(args, 4, 'concat', None)
        if j is None:
            j = t.length()
        parts = []
        for k in range(i, j + 1):
            v = t.get(float(k))
            if v.__class__ is str:
                parts.append(v)
            elif is_number(v):
                parts.append(num2str(v))
            else:
                raise LuaError(f"invalid value (at index {k}) in table for 'concat'")
        return [sep.join(parts)]

    def tbl_sort(*args):
        t = check_table(args, 1, 'sort')
        comp = args[1] if len(args) > 1 else None
        n = t.length()
        values = [t.get(float(k)) for k in range(1, n + 1)]
        if comp is None:
            kinds = {v.__class__ for v in values}
            if kinds <= {float, int} or kinds == {str}:
                values.sort()
            else:
                values.sort(key=cmp_to_key(
                    lambda a, b: -1 if rt.lt(a, b) else (1 if rt.lt(b, a) else 0)))
        else:
            if comp.__class__ not in (LuaFunction, LuaBuiltin):
                arg_error(2, 'sort', f"function expected, got {got(args, 2)}")

            def compare(a, b):
                if truthy(first(rt.call(comp, [a, b]))):
                    return -1
                if truthy(first(rt.call(comp, [b, a]))):
                    return 1
                return 0
            values.sort(key=cmp_to_key(compare))
        for k, v in enumerate(values, 1):
            t.set(float(k), v)

    table_table = LuaTable()
    for name, fn in [('insert', tbl_insert), ('remove', tbl_remove),
                     ('concat', tbl_concat), ('sort', tbl_sort), ('unpack', lua_unpack)]:
        register(table_table, name, fn)
    G.set('table', table_table)

    # io

    def io_write(*args):
        for i, v in enumerate(args, 1):
            if v.__class__ is str:
                sys.stdout.write(v)
            elif is_number(v):
                sys.stdout.write(num2str(v))
            else:
                arg_error(i, 'write', f"string expected, got {type_name(v)}")

    io_table = LuaTable()
    register(io_table, 'write', io_write)
    G.set('io', io_table)
