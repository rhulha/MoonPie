import math
import operator
import sys

from .ast_nodes import (
    Const, Vararg, Name, Index, Call, MethodCall, Function, BinOp, And, Or,
    UnOp, Paren, Table, Local, LocalFunction, Assign, CallStat, Do,
    While, Repeat, If, NumFor, GenFor, Return, Break,
)
from .lua_object import (
    LuaTable, LuaFunction, LuaBuiltin, LuaError, type_name, tostr, num2str,
    tonum, truthy,
)

MAX_CALL_DEPTH = 7000
BREAK = object()
INF = float('inf')
NAN = float('nan')


class Scope:
    __slots__ = ('vars', 'parent')

    def __init__(self, parent, vars=None):
        self.vars = {} if vars is None else vars
        self.parent = parent


def lua_div(a, b):
    try:
        return a / b
    except ZeroDivisionError:
        if a == 0 or a != a:
            return NAN
        return math.copysign(INF, a) * math.copysign(1.0, b)


def lua_idiv(a, b):
    try:
        return float(a // b)
    except ZeroDivisionError:
        return lua_div(a, b)


def lua_mod(a, b):
    try:
        return a % b
    except ZeroDivisionError:
        return NAN


def lua_pow(a, b):
    try:
        return math.pow(a, b)
    except OverflowError:
        return INF
    except ValueError:
        return NAN


ARITH = {
    '+': operator.add, '-': operator.sub, '*': operator.mul,
    '/': lua_div, '//': lua_idiv, '%': lua_mod, '^': lua_pow,
}
ARITH_EVENTS = {
    '+': '__add', '-': '__sub', '*': '__mul', '/': '__div',
    '//': '__idiv', '%': '__mod', '^': '__pow',
}


def first(values):
    return values[0] if values else None


class Evaluator:
    def __init__(self):
        self.G = LuaTable()
        self.string_meta = None
        self.line = 0
        self.line_stack = []
        limit = MAX_CALL_DEPTH * 40
        if sys.getrecursionlimit() < limit:
            sys.setrecursionlimit(limit)

        self.ev = {
            Const: self.ev_const, Vararg: self.ev_vararg, Name: self.ev_name,
            Index: self.ev_index, Call: self.ev_call, MethodCall: self.ev_method_call,
            Function: self.ev_function, BinOp: self.ev_binop, And: self.ev_and,
            Or: self.ev_or, UnOp: self.ev_unop, Paren: self.ev_paren,
            Table: self.ev_table,
        }
        self.ex = {
            Local: self.ex_local, LocalFunction: self.ex_local_function,
            Assign: self.ex_assign, CallStat: self.ex_call_stat, Do: self.ex_do,
            While: self.ex_while, Repeat: self.ex_repeat, If: self.ex_if,
            NumFor: self.ex_num_for, GenFor: self.ex_gen_for,
            Return: self.ex_return, Break: self.ex_break,
        }

    # Calls

    def call(self, f, args):
        c = f.__class__
        if c is LuaFunction:
            node = f.node
            params = node.params
            nargs = len(args)
            vars = {p: (args[i] if i < nargs else None) for i, p in enumerate(params)}
            if node.is_vararg:
                vars['...'] = args[len(params):]
            stack = self.line_stack
            if len(stack) >= MAX_CALL_DEPTH:
                raise LuaError("stack overflow")
            stack.append(self.line)
            try:
                r = self.exec_block(node.body, Scope(f.closure, vars))
            finally:
                self.line = stack.pop()
            return r if r.__class__ is list else []
        if c is LuaBuiltin:
            r = f.fn(*args)
            return [] if r is None else r
        h = self.getmetamethod(f, '__call')
        if h is None:
            raise LuaError(f"attempt to call a {type_name(f)} value")
        return self.call(h, [f, *args])

    def is_callable(self, f):
        c = f.__class__
        return c is LuaFunction or c is LuaBuiltin or self.getmetamethod(f, '__call') is not None

    # Blocks

    def exec_block(self, block, scope):
        ex = self.ex
        try:
            for stmt in block.stmts:
                self.line = stmt.line
                r = ex[stmt.__class__](stmt, scope)
                if r is not None:
                    if r.__class__ is Scope:
                        scope = r
                        continue
                    return r
        except LuaError as e:
            if not e.positioned:
                self.add_position(e, block.chunk)
            raise
        return None

    def add_position(self, e, chunk):
        e.positioned = True
        if not isinstance(e.value, str):
            return
        level = e.level
        if level == 1:
            line = self.line
        elif 1 < level <= len(self.line_stack) + 1:
            line = self.line_stack[-(level - 1)]
        else:
            return
        e.value = f"{chunk}:{line}: {e.value}"

    def child(self, block, scope):
        return Scope(scope) if block.has_locals else scope

    # Statements. Each returns None, a new Scope (after redeclaring a local),
    # BREAK, or a list of return values.

    def ex_local(self, stmt, scope):
        exprs = stmt.exprs
        names = stmt.names
        if len(exprs) == 1 and len(names) == 1:
            values = [self.eval(exprs[0], scope)]
        else:
            values = self.eval_multi(exprs, scope)
        new = None
        vars = scope.vars
        for name in names:
            if name in vars:
                new = Scope(scope)
                vars = new.vars
                break
        nvalues = len(values)
        for i, name in enumerate(names):
            vars[name] = values[i] if i < nvalues else None
        return new

    def ex_local_function(self, stmt, scope):
        new = None
        if stmt.name in scope.vars:
            new = scope = Scope(scope)
        scope.vars[stmt.name] = LuaFunction(stmt.func, scope)
        return new

    def ex_assign(self, stmt, scope):
        targets = stmt.targets
        if len(targets) == 1 and len(stmt.exprs) == 1:
            target = targets[0]
            if target.__class__ is Name:
                self.assign_name(target.name, self.eval(stmt.exprs[0], scope), scope)
            else:
                obj = self.eval(target.obj, scope)
                key = self.eval(target.key, scope)
                self.setindex(obj, key, self.eval(stmt.exprs[0], scope), target.obj, scope)
            return None

        refs = []
        for target in targets:
            if target.__class__ is Name:
                refs.append(None)
            else:
                refs.append((self.eval(target.obj, scope), self.eval(target.key, scope)))
        values = self.eval_multi(stmt.exprs, scope)
        nvalues = len(values)
        for i, target in enumerate(targets):
            value = values[i] if i < nvalues else None
            if refs[i] is None:
                self.assign_name(target.name, value, scope)
            else:
                self.setindex(refs[i][0], refs[i][1], value, target.obj, scope)
        return None

    def assign_name(self, name, value, scope):
        s = scope
        while s is not None:
            vars = s.vars
            if name in vars:
                vars[name] = value
                return
            s = s.parent
        G = self.G
        if G.metatable is None:
            G.set(name, value)
        else:
            self.setindex(G, name, value)

    def ex_call_stat(self, stmt, scope):
        call = stmt.call
        if call.__class__ is Call:
            self.ev_call_multi(call, scope)
        else:
            self.ev_method_call_multi(call, scope)
        return None

    def ex_do(self, stmt, scope):
        return self.exec_block(stmt.body, self.child(stmt.body, scope))

    def ex_while(self, stmt, scope):
        body = stmt.body
        cond = stmt.cond
        while True:
            v = self.eval(cond, scope)
            if v is None or v is False:
                return None
            r = self.exec_block(body, self.child(body, scope))
            if r is not None:
                return None if r is BREAK else r

    def ex_repeat(self, stmt, scope):
        body = stmt.body
        while True:
            inner = Scope(scope)
            r = self.exec_block(body, inner)
            if r is not None:
                return None if r is BREAK else r
            v = self.eval(stmt.cond, inner)
            if v is not None and v is not False:
                return None

    def ex_if(self, stmt, scope):
        for test, block in zip(stmt.tests, stmt.blocks):
            v = self.eval(test, scope)
            if v is not None and v is not False:
                return self.exec_block(block, self.child(block, scope))
        if stmt.orelse is not None:
            return self.exec_block(stmt.orelse, self.child(stmt.orelse, scope))
        return None

    def for_number(self, value, what):
        if value.__class__ is float:
            return value
        if value.__class__ is int:
            return float(value)
        n = tonum(value) if value.__class__ is str else None
        if n is None:
            raise LuaError(f"'for' {what} value must be a number")
        return n

    def ex_num_for(self, stmt, scope):
        i = self.for_number(self.eval(stmt.start, scope), 'initial')
        stop = self.for_number(self.eval(stmt.stop, scope), 'limit')
        step = 1.0 if stmt.step is None else self.for_number(self.eval(stmt.step, scope), 'step')
        if step == 0:
            raise LuaError("'for' step is zero")
        body = stmt.body
        var = stmt.var
        exec_block = self.exec_block
        while (i <= stop) if step > 0 else (i >= stop):
            r = exec_block(body, Scope(scope, {var: i}))
            if r is not None:
                return None if r is BREAK else r
            i += step
        return None

    def ex_gen_for(self, stmt, scope):
        values = self.eval_multi(stmt.exprs, scope)
        values += [None] * (3 - len(values))
        f, state, control = values[0], values[1], values[2]
        if not self.is_callable(f):
            raise LuaError(f"attempt to call a {type_name(f)} value (for iterator)")
        names = stmt.names
        count = len(names)
        body = stmt.body
        call = self.call
        while True:
            results = call(f, [state, control])
            if not results or results[0] is None:
                return None
            control = results[0]
            n = len(results)
            vars = {names[i]: (results[i] if i < n else None) for i in range(count)}
            r = self.exec_block(body, Scope(scope, vars))
            if r is not None:
                return None if r is BREAK else r

    def ex_return(self, stmt, scope):
        exprs = stmt.exprs
        if len(exprs) == 1:
            e = exprs[0]
            c = e.__class__
            if c is Call:
                return self.ev_call_multi(e, scope)
            if c is MethodCall:
                return self.ev_method_call_multi(e, scope)
            if c is Vararg:
                return list(self.varargs(scope))
            return [self.eval(e, scope)]
        return self.eval_multi(exprs, scope)

    def ex_break(self, stmt, scope):
        return BREAK

    # Expressions

    def eval(self, node, scope):
        return self.ev[node.__class__](node, scope)

    def eval_multi(self, exprs, scope):
        if not exprs:
            return []
        ev = self.ev
        out = [ev[e.__class__](e, scope) for e in exprs[:-1]]
        last = exprs[-1]
        c = last.__class__
        if c is Call:
            out.extend(self.ev_call_multi(last, scope))
        elif c is MethodCall:
            out.extend(self.ev_method_call_multi(last, scope))
        elif c is Vararg:
            out.extend(self.varargs(scope))
        else:
            out.append(ev[c](last, scope))
        return out

    def ev_const(self, node, scope):
        return node.value

    def varargs(self, scope):
        s = scope
        while s is not None:
            if '...' in s.vars:
                return s.vars['...']
            s = s.parent
        return []

    def ev_vararg(self, node, scope):
        return first(self.varargs(scope))

    def ev_name(self, node, scope):
        name = node.name
        s = scope
        while s is not None:
            vars = s.vars
            if name in vars:
                return vars[name]
            s = s.parent
        G = self.G
        v = G.hash.get(name)
        if v is not None or G.metatable is None:
            return v
        return self.index(G, name)

    def ev_index(self, node, scope):
        obj = self.eval(node.obj, scope)
        key = self.eval(node.key, scope)
        if obj.__class__ is LuaTable:
            v = obj.get(key)
            if v is not None or obj.metatable is None:
                return v
        return self.index(obj, key, node.obj, scope)

    def ev_call(self, node, scope):
        return first(self.ev_call_multi(node, scope))

    def ev_call_multi(self, node, scope):
        f = self.eval(node.func, scope)
        args = self.eval_multi(node.args, scope)
        self.line = node.line
        if not self.is_callable(f):
            raise LuaError(f"attempt to call a {type_name(f)} value{self.describe(node.func, scope)}")
        return self.call(f, args)

    def ev_method_call(self, node, scope):
        return first(self.ev_method_call_multi(node, scope))

    def ev_method_call_multi(self, node, scope):
        obj = self.eval(node.obj, scope)
        f = self.index(obj, node.name, node.obj, scope)
        args = [obj]
        args.extend(self.eval_multi(node.args, scope))
        self.line = node.line
        if not self.is_callable(f):
            raise LuaError(f"attempt to call a {type_name(f)} value (method '{node.name}')")
        return self.call(f, args)

    def ev_function(self, node, scope):
        return LuaFunction(node, scope)

    def ev_binop(self, node, scope):
        op = node.op
        a = self.eval(node.left, scope)
        b = self.eval(node.right, scope)
        if a.__class__ is float and b.__class__ is float:
            if op == '+':
                return a + b
            if op == '-':
                return a - b
            if op == '*':
                return a * b
            if op == '==':
                return a == b
            if op == '<':
                return a < b
            if op == '<=':
                return a <= b
            if op == '>':
                return a > b
            if op == '>=':
                return a >= b
            if op == '~=':
                return a != b
        fn = ARITH.get(op)
        if fn is not None:
            return self.arith(op, a, b)
        if op == '..':
            return self.concat(a, b)
        if op == '==':
            return self.eq(a, b)
        if op == '~=':
            return not self.eq(a, b)
        if op == '<':
            return self.lt(a, b)
        if op == '<=':
            return self.le(a, b)
        if op == '>':
            return self.lt(b, a)
        return self.le(b, a)

    def ev_and(self, node, scope):
        a = self.eval(node.left, scope)
        if a is None or a is False:
            return a
        return self.eval(node.right, scope)

    def ev_or(self, node, scope):
        a = self.eval(node.left, scope)
        if a is not None and a is not False:
            return a
        return self.eval(node.right, scope)

    def ev_unop(self, node, scope):
        op = node.op
        v = self.eval(node.operand, scope)
        if op == 'not':
            return v is None or v is False
        if op == '-':
            n = tonum(v)
            if n is not None:
                return -n
            h = self.getmetamethod(v, '__unm')
            if h is not None:
                return first(self.call(h, [v, v]))
            raise LuaError(f"attempt to perform arithmetic on a {type_name(v)} value"
                           f"{self.describe(node.operand, scope)}")
        return self.length(v, node.operand, scope)

    def ev_paren(self, node, scope):
        return self.eval(node.expr, scope)

    def ev_table(self, node, scope):
        t = LuaTable()
        items = node.items
        last = len(items) - 1
        i = 1
        for idx, (key, value) in enumerate(items):
            if key is None:
                if idx == last and value.__class__ in (Call, MethodCall, Vararg):
                    for v in self.eval_multi([value], scope):
                        t.set(float(i), v)
                        i += 1
                else:
                    t.set(float(i), self.eval(value, scope))
                    i += 1
            else:
                k = self.eval(key, scope)
                t.set(k, self.eval(value, scope))
        return t

    def describe(self, node, scope):
        c = node.__class__
        if c is Name:
            s = scope
            while s is not None:
                if node.name in s.vars:
                    return f" (local '{node.name}')"
                s = s.parent
            return f" (global '{node.name}')"
        if c is Index and node.key.__class__ is Const and node.key.value.__class__ is str:
            return f" (field '{node.key.value}')"
        if c is MethodCall:
            return f" (method '{node.name}')"
        return ''

    # Operations with metamethods

    def getmetatable(self, v):
        if v.__class__ is LuaTable:
            return v.metatable
        if v.__class__ is str:
            return self.string_meta
        return None

    def getmetamethod(self, v, event):
        mt = self.getmetatable(v)
        return None if mt is None else mt.get(event)

    def index(self, obj, key, node=None, scope=None):
        while True:
            if obj.__class__ is LuaTable:
                v = obj.get(key)
                if v is not None:
                    return v
                mt = obj.metatable
                if mt is None:
                    return None
                h = mt.get('__index')
                if h is None:
                    return None
            else:
                h = self.getmetamethod(obj, '__index')
                if h is None:
                    where = self.describe(node, scope) if node is not None else ''
                    raise LuaError(f"attempt to index a {type_name(obj)} value{where}")
            if h.__class__ is LuaFunction or h.__class__ is LuaBuiltin:
                return first(self.call(h, [obj, key]))
            obj = h
            node = None

    def setindex(self, obj, key, value, node=None, scope=None):
        while True:
            if obj.__class__ is LuaTable:
                mt = obj.metatable
                if mt is None or obj.get(key) is not None:
                    obj.set(key, value)
                    return
                h = mt.get('__newindex')
                if h is None:
                    obj.set(key, value)
                    return
            else:
                h = self.getmetamethod(obj, '__newindex')
                if h is None:
                    where = self.describe(node, scope) if node is not None else ''
                    raise LuaError(f"attempt to index a {type_name(obj)} value{where}")
            if h.__class__ is LuaFunction or h.__class__ is LuaBuiltin:
                self.call(h, [obj, key, value])
                return
            obj = h
            node = None

    def binary_metamethod(self, a, b, event):
        h = self.getmetamethod(a, event)
        if h is None:
            h = self.getmetamethod(b, event)
        return h

    def arith(self, op, a, b):
        x = tonum(a)
        y = tonum(b)
        if x is not None and y is not None:
            return ARITH[op](x, y)
        h = self.binary_metamethod(a, b, ARITH_EVENTS[op])
        if h is not None:
            return first(self.call(h, [a, b]))
        bad = b if x is not None else a
        raise LuaError(f"attempt to perform arithmetic on a {type_name(bad)} value")

    def concat(self, a, b):
        ca = a.__class__
        cb = b.__class__
        if (ca is str or ca is float or ca is int) and (cb is str or cb is float or cb is int):
            return (a if ca is str else num2str(a)) + (b if cb is str else num2str(b))
        h = self.binary_metamethod(a, b, '__concat')
        if h is not None:
            return first(self.call(h, [a, b]))
        bad = b if (ca is str or ca is float or ca is int) else a
        raise LuaError(f"attempt to concatenate a {type_name(bad)} value")

    def length(self, v, node=None, scope=None):
        if v.__class__ is str:
            return float(len(v))
        h = self.getmetamethod(v, '__len')
        if h is not None:
            return first(self.call(h, [v]))
        if v.__class__ is LuaTable:
            return float(v.length())
        where = self.describe(node, scope) if node is not None else ''
        raise LuaError(f"attempt to get length of a {type_name(v)} value{where}")

    def eq(self, a, b):
        ca = a.__class__
        cb = b.__class__
        if ca is float or ca is int:
            return (cb is float or cb is int) and a == b
        if a is b:
            return True
        if ca is not cb:
            return False
        if ca is LuaTable:
            h = self.binary_metamethod(a, b, '__eq')
            return h is not None and truthy(first(self.call(h, [a, b])))
        return a == b if ca is str or ca is bool else False

    def compare_error(self, a, b):
        ta, tb = type_name(a), type_name(b)
        if ta == tb:
            raise LuaError(f"attempt to compare two {ta} values")
        raise LuaError(f"attempt to compare {ta} with {tb}")

    def lt(self, a, b):
        ca = a.__class__
        cb = b.__class__
        if (ca is float or ca is int) and (cb is float or cb is int):
            return a < b
        if ca is str and cb is str:
            return a < b
        h = self.binary_metamethod(a, b, '__lt')
        if h is None:
            self.compare_error(a, b)
        return truthy(first(self.call(h, [a, b])))

    def le(self, a, b):
        ca = a.__class__
        cb = b.__class__
        if (ca is float or ca is int) and (cb is float or cb is int):
            return a <= b
        if ca is str and cb is str:
            return a <= b
        h = self.binary_metamethod(a, b, '__le')
        if h is None:
            self.compare_error(a, b)
        return truthy(first(self.call(h, [a, b])))

    def tostring(self, v):
        h = self.getmetamethod(v, '__tostring')
        if h is not None:
            r = first(self.call(h, [v]))
            if r.__class__ is not str:
                raise LuaError("'__tostring' must return a string")
            return r
        return tostr(v)
