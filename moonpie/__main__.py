#!/usr/bin/env python3
"""
MoonPie command line interface.

    moonpie <file.lua>    Execute a Lua file
    moonpie               Start the interactive REPL
"""

import argparse
import os
import sys

from . import __version__
from .lua_interpreter import LuaInterpreter
from .lua_object import LuaError, LuaSyntaxError


def start_repl():
    interpreter = LuaInterpreter()

    print(f"MoonPie {__version__} - Lua interpreter in Python")
    print("Type 'exit' or press Ctrl+C to quit")
    print()

    while True:
        try:
            line = input("> ")
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            break

        if line.strip() in ('exit', 'quit'):
            print("Goodbye!")
            break
        if not line.strip():
            continue

        try:
            try:
                func = interpreter.compile('return ' + line, 'stdin')
            except LuaSyntaxError:
                func = interpreter.compile(line, 'stdin')
            results = interpreter.call(func)
            if results:
                print('\t'.join(interpreter.runtime.tostring(v) for v in results))
        except LuaError as e:
            print(e, file=sys.stderr)
        except KeyboardInterrupt:
            print("interrupted", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        prog='moonpie',
        description='MoonPie - A Lua interpreter written in Python',
        epilog='Examples:\n  moonpie script.lua    # Execute file\n  moonpie               # Start REPL',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        'file',
        nargs='?',
        help='Lua file to execute. If omitted, starts interactive REPL.'
    )
    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
    parser.add_argument('-v', '--verbose', action='store_true', help='Print a Python traceback on errors')
    args = parser.parse_args()

    if not args.file:
        start_repl()
        return

    if not os.path.isfile(args.file):
        print(f"moonpie: cannot open {args.file}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(args.file, 'r', encoding='utf-8') as f:
            code = f.read()
    except (OSError, UnicodeDecodeError) as e:
        print(f"moonpie: cannot read {args.file}: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        LuaInterpreter().run(code, args.file)
    except LuaError as e:
        sys.stdout.flush()
        print(f"moonpie: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
