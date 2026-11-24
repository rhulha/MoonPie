from .lexer import tokenize
from .lua_object import LuaSyntaxError
from .ast_nodes import (
    Const, Vararg, Name, Index, Call, MethodCall, Function, BinOp, And, Or,
    UnOp, Paren, Table, Block, Local, LocalFunction, Assign, CallStat, Do,
    While, Repeat, If, NumFor, GenFor, Return, Break,
)


# (left, right) priorities, as in the Lua 5.4 reference implementation
BINARY_PRIORITY = {
    'or': (1, 1), 'and': (2, 2),
    '<': (3, 3), '>': (3, 3), '<=': (3, 3), '>=': (3, 3), '~=': (3, 3), '==': (3, 3),
    '..': (9, 8),
    '+': (10, 10), '-': (10, 10),
    '*': (11, 11), '/': (11, 11), '//': (11, 11), '%': (11, 11),
    '^': (14, 13),
}
UNARY_PRIORITY = 12
BLOCK_END = frozenset({'eof', 'end', 'else', 'elseif', 'until'})


class Parser:
    def __init__(self, source: str, chunkname: str = 'input'):
        self.chunkname = chunkname
        self.tokens = tokenize(source, chunkname)
        self.pos = 0
        self.tok = self.tokens[0]
        self.vararg = [True]
        self.loop_depth = [0]

    def advance(self):
        if self.tok.type != 'eof':
            self.pos += 1
            self.tok = self.tokens[self.pos]

    def peek_type(self):
        return self.tokens[min(self.pos + 1, len(self.tokens) - 1)].type

    def error(self, msg):
        raise LuaSyntaxError(f"{self.chunkname}:{self.tok.line}: {msg} near '{self.tok.text()}'")

    def accept(self, type):
        if self.tok.type == type:
            self.advance()
            return True
        return False

    def expect(self, type):
        if self.tok.type != type:
            self.error(f"'{type}' expected")
        self.advance()

    def expect_match(self, what, who, line):
        if self.tok.type != what:
            if line == self.tok.line:
                self.error(f"'{what}' expected")
            self.error(f"'{what}' expected (to close '{who}' at line {line})")
        self.advance()

    def expect_name(self):
        if self.tok.type != 'name':
            self.error("<name> expected")
        name = self.tok.value
        self.advance()
        return name

    # Blocks and statements

    def parse(self):
        body = self.block()
        if self.tok.type != 'eof':
            self.error("'<eof>' expected")
        return Function([], True, body, 'main chunk')

    def block(self):
        stmts = []
        has_locals = False
        while self.tok.type not in BLOCK_END:
            line = self.tok.line
            if self.tok.type == 'return':
                stmt = self.return_stat()
                stmt.line = line
                stmts.append(stmt)
                break
            stmt = self.statement()
            if stmt is not None:
                stmt.line = line
                stmts.append(stmt)
                if stmt.__class__ is Local or stmt.__class__ is LocalFunction:
                    has_locals = True
        return Block(stmts, has_locals, self.chunkname)

    def statement(self):
        t = self.tok.type
        line = self.tok.line
        if t == ';':
            self.advance()
            return None
        if t == 'if':
            return self.if_stat(line)
        if t == 'while':
            return self.while_stat(line)
        if t == 'do':
            self.advance()
            body = self.block()
            self.expect_match('end', 'do', line)
            return Do(body)
        if t == 'for':
            return self.for_stat(line)
        if t == 'repeat':
            return self.repeat_stat(line)
        if t == 'function':
            return self.function_stat(line)
        if t == 'local':
            self.advance()
            if self.accept('function'):
                name = self.expect_name()
                return LocalFunction(name, self.function_body(False, line, name))
            return self.local_stat()
        if t == 'break':
            if self.loop_depth[-1] == 0:
                self.error(f"break outside a loop at line {line}")
            self.advance()
            return Break()
        return self.expr_stat()

    def loop_body(self):
        self.loop_depth[-1] += 1
        body = self.block()
        self.loop_depth[-1] -= 1
        return body

    def if_stat(self, line):
        self.advance()
        tests = [self.expr()]
        self.expect('then')
        blocks = [self.block()]
        while self.tok.type == 'elseif':
            self.advance()
            tests.append(self.expr())
            self.expect('then')
            blocks.append(self.block())
        orelse = self.block() if self.accept('else') else None
        self.expect_match('end', 'if', line)
        return If(tests, blocks, orelse)

    def while_stat(self, line):
        self.advance()
        cond = self.expr()
        self.expect('do')
        body = self.loop_body()
        self.expect_match('end', 'while', line)
        return While(cond, body)

    def repeat_stat(self, line):
        self.advance()
        body = self.loop_body()
        self.expect_match('until', 'repeat', line)
        return Repeat(body, self.expr())

    def for_stat(self, line):
        self.advance()
        first = self.expect_name()
        if self.accept('='):
            start = self.expr()
            self.expect(',')
            stop = self.expr()
            step = self.expr() if self.accept(',') else None
            self.expect('do')
            body = self.loop_body()
            self.expect_match('end', 'for', line)
            return NumFor(first, start, stop, step, body)
        if self.tok.type in (',', 'in'):
            names = [first]
            while self.accept(','):
                names.append(self.expect_name())
            self.expect('in')
            exprs = self.expr_list()
            self.expect('do')
            body = self.loop_body()
            self.expect_match('end', 'for', line)
            return GenFor(names, exprs, body)
        self.error("'=' or 'in' expected")

    def function_stat(self, line):
        self.advance()
        name = self.expect_name()
        target = Name(name)
        is_method = False
        while self.tok.type == '.':
            self.advance()
            key = self.expect_name()
            name += '.' + key
            target = Index(target, Const(key))
        if self.accept(':'):
            key = self.expect_name()
            name += ':' + key
            target = Index(target, Const(key))
            is_method = True
        return Assign([target], [self.function_body(is_method, line, name)])

    def local_stat(self):
        names = [self.expect_name()]
        while self.accept(','):
            names.append(self.expect_name())
        exprs = self.expr_list() if self.accept('=') else []
        return Local(names, exprs)

    def return_stat(self):
        self.advance()
        if self.tok.type in BLOCK_END or self.tok.type == ';':
            exprs = []
        else:
            exprs = self.expr_list()
        self.accept(';')
        return Return(exprs)

    def expr_stat(self):
        expr = self.suffixed_expr()
        if self.tok.type in ('=', ','):
            targets = [expr]
            while self.accept(','):
                targets.append(self.suffixed_expr())
            for target in targets:
                if target.__class__ is not Name and target.__class__ is not Index:
                    self.error("syntax error")
            self.expect('=')
            return Assign(targets, self.expr_list())
        if expr.__class__ is not Call and expr.__class__ is not MethodCall:
            self.error("syntax error")
        return CallStat(expr)

    def function_body(self, is_method, line, name):
        self.expect('(')
        params = ['self'] if is_method else []
        is_vararg = False
        if self.tok.type != ')':
            while True:
                if self.tok.type == '...':
                    self.advance()
                    is_vararg = True
                    break
                params.append(self.expect_name())
                if not self.accept(','):
                    break
        self.expect(')')
        self.vararg.append(is_vararg)
        self.loop_depth.append(0)
        body = self.block()
        self.loop_depth.pop()
        self.vararg.pop()
        self.expect_match('end', 'function', line)
        return Function(params, is_vararg, body, name)

    # Expressions

    def expr_list(self):
        exprs = [self.expr()]
        while self.accept(','):
            exprs.append(self.expr())
        return exprs

    def expr(self, limit=0):
        t = self.tok.type
        if t == 'not' or t == '-' or t == '#':
            self.advance()
            operand = self.expr(UNARY_PRIORITY)
            if t == '-' and operand.__class__ is Const and operand.value.__class__ is float:
                left = Const(-operand.value)
            else:
                left = UnOp(t, operand)
        else:
            left = self.simple_expr()
        while True:
            op = self.tok.type
            priority = BINARY_PRIORITY.get(op)
            if priority is None or priority[0] <= limit:
                return left
            self.advance()
            right = self.expr(priority[1])
            if op == 'and':
                left = And(left, right)
            elif op == 'or':
                left = Or(left, right)
            else:
                left = BinOp(op, left, right)

    def simple_expr(self):
        tok = self.tok
        t = tok.type
        if t == 'number' or t == 'string':
            self.advance()
            return Const(tok.value)
        if t == 'nil':
            self.advance()
            return Const(None)
        if t == 'true':
            self.advance()
            return Const(True)
        if t == 'false':
            self.advance()
            return Const(False)
        if t == '...':
            if not self.vararg[-1]:
                self.error("cannot use '...' outside a vararg function")
            self.advance()
            return Vararg()
        if t == '{':
            return self.table()
        if t == 'function':
            self.advance()
            return self.function_body(False, tok.line, None)
        return self.suffixed_expr()

    def primary_expr(self):
        if self.tok.type == 'name':
            return Name(self.expect_name())
        if self.tok.type == '(':
            line = self.tok.line
            self.advance()
            expr = self.expr()
            self.expect_match(')', '(', line)
            return Paren(expr)
        self.error("unexpected symbol")

    def suffixed_expr(self):
        expr = self.primary_expr()
        while True:
            t = self.tok.type
            if t == '.':
                self.advance()
                expr = Index(expr, Const(self.expect_name()))
            elif t == '[':
                self.advance()
                key = self.expr()
                self.expect(']')
                expr = Index(expr, key)
            elif t == ':':
                self.advance()
                name = self.expect_name()
                line = self.tok.line
                expr = MethodCall(expr, name, self.call_args())
                expr.line = line
            elif t == '(' or t == 'string' or t == '{':
                line = self.tok.line
                expr = Call(expr, self.call_args())
                expr.line = line
            else:
                return expr

    def call_args(self):
        tok = self.tok
        if tok.type == 'string':
            self.advance()
            return [Const(tok.value)]
        if tok.type == '{':
            return [self.table()]
        if tok.type != '(':
            self.error("function arguments expected")
        self.advance()
        args = [] if self.tok.type == ')' else self.expr_list()
        self.expect_match(')', '(', tok.line)
        return args

    def table(self):
        line = self.tok.line
        self.expect('{')
        items = []
        while self.tok.type != '}':
            if self.tok.type == '[':
                self.advance()
                key = self.expr()
                self.expect(']')
                self.expect('=')
                items.append((key, self.expr()))
            elif self.tok.type == 'name' and self.peek_type() == '=':
                key = Const(self.expect_name())
                self.advance()
                items.append((key, self.expr()))
            else:
                items.append((None, self.expr()))
            if not (self.accept(',') or self.accept(';')):
                break
        self.expect_match('}', '{', line)
        return Table(items)


def parse(source: str, chunkname: str = 'input'):
    return Parser(source, chunkname).parse()
