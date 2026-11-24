from .parser import parse
from .evaluator import Evaluator
from .lua_object import LuaFunction
from .lua_builtins import setup_builtins


class LuaInterpreter:
    """Runs Lua code. Errors raise LuaError (LuaSyntaxError for parse errors)."""

    def __init__(self):
        self.runtime = Evaluator()
        setup_builtins(self.runtime)
        self.globals = self.runtime.G

    def compile(self, source: str, chunkname: str = 'input') -> LuaFunction:
        return LuaFunction(parse(source, chunkname), None)

    def call(self, func, *args) -> list:
        return self.runtime.call(func, list(args))

    def run(self, source: str, chunkname: str = 'input') -> list:
        """Execute a chunk and return the list of values it returns."""
        return self.call(self.compile(source, chunkname))

    def run_file(self, filename: str) -> list:
        with open(filename, 'r', encoding='utf-8') as f:
            source = f.read()
        return self.run(source, filename)
