class Node:
    __slots__ = ('line',)

    def __init__(self, *args):
        for name, value in zip(self.__slots__, args):
            setattr(self, name, value)
        self.line = 0

    def __repr__(self):
        fields = ', '.join(repr(getattr(self, n)) for n in self.__slots__)
        return f"{type(self).__name__}({fields})"


# Expressions

class Const(Node):
    __slots__ = ('value',)


class Vararg(Node):
    __slots__ = ()


class Name(Node):
    __slots__ = ('name',)


class Index(Node):
    __slots__ = ('obj', 'key')


class Call(Node):
    __slots__ = ('func', 'args')


class MethodCall(Node):
    __slots__ = ('obj', 'name', 'args')


class Function(Node):
    __slots__ = ('params', 'is_vararg', 'body', 'name')


class BinOp(Node):
    __slots__ = ('op', 'left', 'right')


class And(Node):
    __slots__ = ('left', 'right')


class Or(Node):
    __slots__ = ('left', 'right')


class UnOp(Node):
    __slots__ = ('op', 'operand')


class Paren(Node):
    __slots__ = ('expr',)


class Table(Node):
    __slots__ = ('items',)  # list of (key_expr or None, value_expr)


# Statements

class Block(Node):
    __slots__ = ('stmts', 'has_locals', 'chunk')


class Local(Node):
    __slots__ = ('names', 'exprs')


class LocalFunction(Node):
    __slots__ = ('name', 'func')


class Assign(Node):
    __slots__ = ('targets', 'exprs')


class CallStat(Node):
    __slots__ = ('call',)


class Do(Node):
    __slots__ = ('body',)


class While(Node):
    __slots__ = ('cond', 'body')


class Repeat(Node):
    __slots__ = ('body', 'cond')


class If(Node):
    __slots__ = ('tests', 'blocks', 'orelse')


class NumFor(Node):
    __slots__ = ('var', 'start', 'stop', 'step', 'body')


class GenFor(Node):
    __slots__ = ('names', 'exprs', 'body')


class Return(Node):
    __slots__ = ('exprs',)


class Break(Node):
    __slots__ = ()
