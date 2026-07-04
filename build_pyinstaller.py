from __future__ import annotations

import dis
import sys

from PyInstaller.__main__ import run
from PyInstaller.lib.modulegraph import util


def iterate_instructions(code_object):
    try:
        yield from (instruction for instruction in dis.get_instructions(code_object) if instruction.opname != "EXTENDED_ARG")
    except IndexError as exc:
        filename = getattr(code_object, "co_filename", "<unknown>")
        name = getattr(code_object, "co_name", "<unknown>")
        print(f"Skipping PyInstaller bytecode scan for {filename}:{name}: {exc}", file=sys.stderr)
        return


util.iterate_instructions = iterate_instructions

COMMON_ARGS = [
    "--clean",
    "--noconfirm",
    "--onefile",
    "--icon",
    r"cc_led\assets\cc_led.ico",
    "--add-data",
    r"cc_led\assets\sounds\F1TR.wav;cc_led\assets\sounds",
    "--exclude-module",
    "PIL.ImageQt",
    "--exclude-module",
    "PyQt5",
    "--exclude-module",
    "PyQt6",
    "--exclude-module",
    "PySide2",
    "--exclude-module",
    "PySide6",
    "--exclude-module",
    "numpy",
    "--exclude-module",
    "matplotlib",
    "--hidden-import",
    "PIL.Image",
    "--hidden-import",
    "PIL.ImageDraw",
    "--hidden-import",
    "PIL.ImageFilter",
    "--hidden-import",
    "PIL.ImageFont",
    "--hidden-import",
    "PIL.ImageTk",
    "main.py",
]


def build(name: str, *, console: bool) -> None:
    args = [
        "--clean",
        "--noconfirm",
        "--onefile",
        "--name",
        name,
    ]
    if not console:
        args.append("--noconsole")
    args.extend(COMMON_ARGS[3:])
    run(args)


build("CC_LED", console=False)
build("CC_LED_Hook", console=True)
