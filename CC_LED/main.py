from __future__ import annotations

import argparse
import sys

from cc_led.app import run_tray_app
from cc_led.config import DEFAULT_PORT
from cc_led.codex_installer import install_codex_hooks, uninstall_codex_hooks
from cc_led.events import HookEvent, LedState
from cc_led.hook_adapter import post_state, run_hook
from cc_led.installer import install_hooks, uninstall_hooks


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cc-led", description="Claude Code tray status light")
    parser.add_argument("--hook", metavar="EVENT", help="run as a Claude Code hook adapter")
    parser.add_argument("--codex-hook", metavar="EVENT", help="run as a Codex hook adapter")
    parser.add_argument("--cc-led-marker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--install-hooks", action="store_true", help="install Claude Code hooks")
    parser.add_argument("--uninstall-hooks", action="store_true", help="uninstall Claude Code hooks")
    parser.add_argument("--install-codex-hooks", action="store_true", help="install Codex hooks")
    parser.add_argument("--uninstall-codex-hooks", action="store_true", help="uninstall Codex hooks")
    parser.add_argument("--settings-path", help="override Claude settings path")
    parser.add_argument("--codex-hooks-path", help="override Codex hooks.json path")
    parser.add_argument("--exe-path", help="override executable path used in installed hooks")
    parser.add_argument("--port", type=int, help="local CC LED server port")
    parser.add_argument("--test-state", choices=[state.value for state in LedState], help="send a test state to the running app")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.hook:
        return run_hook(args.hook, port=args.port)

    if args.codex_hook:
        from cc_led.config import SOURCE_CODEX

        return run_hook(args.codex_hook, port=args.port, source=SOURCE_CODEX)

    if args.install_hooks:
        result = install_hooks(settings_path=args.settings_path, exe_path=args.exe_path)
        print(result.message)
        return 0

    if args.uninstall_hooks:
        result = uninstall_hooks(settings_path=args.settings_path)
        print(result.message)
        return 0

    if args.install_codex_hooks:
        result = install_codex_hooks(hooks_path=args.codex_hooks_path, exe_path=args.exe_path)
        print(result.message)
        return 0

    if args.uninstall_codex_hooks:
        result = uninstall_codex_hooks(hooks_path=args.codex_hooks_path)
        print(result.message)
        return 0

    if args.test_state:
        event = HookEvent(
            source="manual",
            event=f"Test{args.test_state.title()}",
            state=LedState(args.test_state),
            session_id="manual-test",
        )
        ok = post_state(event, port=args.port or DEFAULT_PORT)
        print("posted" if ok else "failed to reach CC LED server")
        return 0 if ok else 1

    return run_tray_app(port=args.port)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
