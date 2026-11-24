# MoonPie - Lua Interpreter in Python

A Lua interpreter written in Python, implementing core Lua language features.

## Installation

Requires Python 3.11 or newer.

### From PyPI (when published)
```bash
pip install moonpie
```

### From Source
```bash
git clone https://github.com/rhulha/MoonPie.git
cd MoonPie
pip install -e .
```

## Features

### Language Support
- **Data Types**: nil, booleans, numbers, strings, tables, functions
- **Operators**: arithmetic (`+ - * / // % ^`), comparison (`== ~= < <= > >=`, numbers and strings), logical (`and or not`, short-circuit), concatenation (`..`), length (`#`)
- **Variables**: local and global, with proper block scoping and a fresh loop variable per iteration
- **Assignment**: multiple assignment (`a, b = b, a`) and multiple return values
- **Functions**: closures, varargs (`...`), methods (`obj:method()`), `function a.b.c:m()` definitions, `f"str"` / `f{...}` call syntax
- **Control Flow**: if/elseif/else, while, repeat-until, numeric for, generic for (`pairs`, `ipairs`, custom iterators), break
- **Metatables**: `__index`, `__newindex`, `__call`, `__tostring`, arithmetic, `__concat`, `__eq`, `__lt`, `__le`, `__len`, `__unm`, `__pairs`
- **Literals**: decimal, exponent and hex numbers (`1e3`, `0xFF`, `0x1p4`), long strings and comments (`[[...]]`, `[==[...]==]`), all string escapes
- **Errors**: Lua-style messages with `file:line:` positions; `error`, `pcall`, `xpcall`

### Built-in Functions
- **Basic**: print, type, tostring, tonumber, assert, error, pcall, xpcall, select, next, pairs, ipairs, unpack, setmetatable, getmetatable, rawget, rawset, rawequal, rawlen, _G
- **Math**: abs, floor, ceil, sqrt, sin, cos, tan, max, min, pi, huge
- **String**: len, upper, lower, sub, rep, format, find, match, gmatch, gsub (strings also support `s:method()`)
- **Table**: insert, remove, concat, sort, unpack
- **IO**: write

## Architecture

The interpreter follows a classic architecture:

1. **Lexer** (`lexer.py`) - Tokenizes Lua source code
2. **Parser** (`parser.py`) - Builds an Abstract Syntax Tree (AST) from tokens
3. **AST Nodes** (`ast_nodes.py`) - Defines all AST node types
4. **Evaluator** (`evaluator.py`) - Traverses and executes the AST
5. **Object System** (`lua_object.py`) - Lua tables, functions and value helpers
6. **Built-ins** (`lua_builtins.py`) - Provides standard Lua functions
7. **Patterns** (`lua_patterns.py`) - Translates Lua patterns to Python regular expressions

## Usage

### Command Line (after installation)
```bash
moonpie                    # Start interactive REPL
moonpie script.lua         # Execute a Lua file
moonpie examples/examples.lua
```

### Python Module
```bash
python -m moonpie          # Start interactive REPL
python -m moonpie script.lua
```

### As a Library
```python
from moonpie import LuaInterpreter, LuaError

interpreter = LuaInterpreter()
results = interpreter.run("""
    function add(a, b)
        return a + b
    end
    print(add(5, 3))
    return add(1, 2), "done"
""")
print(results)  # [3.0, 'done']

try:
    interpreter.run("error('boom')")
except LuaError as e:
    print(e)  # input:1: boom
```

`run` returns the values returned by the chunk as a list and raises `LuaError`
(or `LuaSyntaxError`) on errors. Lua values map to Python as nil -> `None`,
booleans -> `bool`, numbers -> `float`, strings -> `str`; tables are `LuaTable`.

### Example Code

```lua
-- Variables and arithmetic
local x = 10
local y = 20
print(x + y)  -- 30

-- Functions
function factorial(n)
    if n <= 1 then
        return 1
    else
        return n * factorial(n - 1)
    end
end
print(factorial(5))  -- 120

-- Tables
local person = {name = "John", age = 30}
print(person.name)  -- John

local array = {10, 20, 30}
print(array[1])  -- 10
print(#array)   -- 3

-- Loops
for i = 1, 5 do
    print(i)
end

-- String operations
local greeting = "Hello" .. " " .. "World"
print(greeting)  -- Hello World
```

## Testing

Run the test suite:
```bash
pip install pytest
python -m pytest tests
```

Run examples:
```bash
moonpie examples/examples.lua
```

## Implementation Details

- **Lexer**: Tokenizes keywords, operators, numbers, short and long strings, and comments
- **Parser**: Recursive descent parser using Lua 5.4 operator priorities
- **Evaluator**: Tree-walking interpreter with lexical scopes and metatable-aware operations
- **Numbers**: All numbers are floats (as in Lua 5.1) and print with `%.14g`
- **Recursion**: Up to about 7000 nested Lua calls, then a catchable "stack overflow" error

## Limitations

This is a Lua interpreter for educational purposes. Not implemented:
- Coroutines, `goto` and labels
- Integer subtype and bitwise operators (Lua 5.3+)
- `require`, `load`, file I/O, `os` library, and most of `io`
- `%b` in string patterns
- Proper tail calls
- Strings are Python (Unicode) strings, so `#` counts characters, not bytes

## References

- [Lua 5.4 Reference Manual](https://www.lua.org/manual/5.4/)
- [Writing A Compiler In Go](https://compilerbook.com/)
- [Crafting Interpreters](https://craftinginterpreters.com/)
