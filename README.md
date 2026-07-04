# CC LED

CC LED is a Claude Code and Codex hook-driven desktop status light. It shows a topmost, draggable traffic-light overlay and a tray icon so you can see whether the agent is working, waiting for approval, done, or in error.

The project was inspired by Clawd on Desk, but CC LED keeps the core status logic local and lightweight: Claude/Codex hooks send lifecycle events to a local HTTP server, the reducer aggregates all sessions, then the overlay and tray icon update.

## Status Rules

The floating light has three circles from top to bottom:

| Light | Meaning | Behavior |
| --- | --- | --- |
| Red | approval, user attention, or error | approval/attention blinks; error stays solid |
| Yellow | Claude or Codex is working | blinks at a steady 1 Hz rhythm |
| Green | complete / idle | solid |

Typical event mapping:

| Event | State |
| --- | --- |
| `SessionStart`, `SessionEnd`, `Stop` | idle / green |
| `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `SubagentStart`, `SubagentStop`, `PreCompact`, automatic `PostCompact` | busy / yellow |
| `PermissionRequest`, `Elicitation` | approval / blinking red |
| `Notification`, question-like `Stop` output | short user-attention red reminder |
| `PostToolUseFailure`, `StopFailure`, API error | error / solid red |

Real approval events use a longer timeout so they stay visible while you approve. Short attention reminders expire back to green automatically.

## UI

The main UI is a topmost floating traffic light:

- drag with the left mouse button
- use the mouse wheel to resize
- right-click to change visual effect, vertical/horizontal layout, size, opacity, hook installation, or exit
- double-click to cycle through green/yellow/red for a quick visual test

Four overlay effects are available:

- `Classic`: dark rounded traffic-light look
- `Apple Glass`: neutral glass capsule with soft internal glow
- `Real LED`: dark base, metal rings, glossy LED lenses
- `Pixel`: blocky pixel lamps with a rectangular frame

Approval and completion use short custom WAV tones generated under `%APPDATA%\CC LED\sounds`. CC LED does not call Windows system alert sounds.

Bundled sound presets live under `cc_led/assets/sounds/`. User-selected sound settings are stored locally under `%APPDATA%\CC LED\sound_settings.json`.

## Architecture

```text
Claude Code / Codex
  -> hook command: python main.py --hook <event>
  -> hook adapter reads stdin JSON
  -> POST http://127.0.0.1:32333/state
  -> SessionStore reducer aggregates sessions
  -> overlay + tray icon update
```

Local endpoints:

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | current aggregate state |
| `POST /state` | hook adapter state events |
| `POST /permission` | approval notification endpoint |

## Privacy

Logs are written to:

```text
%APPDATA%\CC LED\cc-led.log
```

The log records hook summaries, state changes, and install/uninstall results. It does not store full prompts, full tool inputs, or transcript contents.

## Install

```powershell
python -m pip install -r requirements.txt
```

## Run

```powershell
python main.py
```

This starts the floating overlay, tray icon, local state server, and health monitor.

## Claude Hooks

Install or update Claude Code hooks:

```powershell
python main.py --install-hooks
```

Uninstall only CC LED's Claude hook entries:

```powershell
python main.py --uninstall-hooks
```

The installer updates `~/.claude/settings.json` safely: it appends CC LED hooks, updates existing CC LED entries by marker, and leaves unrelated user hooks in place.

## Codex Hooks

Install or update Codex hooks:

```powershell
python main.py --install-codex-hooks
```

Uninstall only CC LED's Codex hook entries:

```powershell
python main.py --uninstall-codex-hooks
```

Codex reads hook configuration when a session starts, so after installing or changing hooks, open a new Codex window/session for the change to apply.

## Smoke Tests

Start the app first:

```powershell
python main.py
```

Claude hook smoke test:

```powershell
'{"session_id":"smoke","cwd":"C:\\Projects\\demo"}' | python main.py --hook UserPromptSubmit
```

Codex hook smoke test:

```powershell
'{"hook_event_name":"PreToolUse","session_id":"smoke","tool_name":"shell_command"}' | python main.py --codex-hook PreToolUse
```

Direct manual state tests:

```powershell
python main.py --test-state busy
python main.py --test-state idle
python main.py --test-state error
python main.py --test-state approval
```

Check the live state:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:32333/health
```

## Troubleshooting

If the light does not change color:

1. Make sure CC LED is running: `python main.py`.
2. Reinstall hooks after moving or editing the project.
3. For Codex, start a new Codex session after hook changes.
4. Run a direct test: `python main.py --test-state busy`.
5. Check `%APPDATA%\CC LED\cc-led.log`.

Useful log examples:

```text
hook ... source=codex event=UserPromptSubmit state=busy session=... posted=True
state=busy event=UserPromptSubmit sessions=1
```

If `posted=False`, the hook ran but CC LED's local server was unreachable. If there is no hook line, Claude/Codex did not run CC LED's hook entry.

## Development

Run tests:

```powershell
python -m pytest -q
```

Build the Windows executable:

```powershell
python -B build_pyinstaller.py
```

The executable is written to `dist/CC_LED.exe`. The `dist/` and `build/` directories are ignored by git; publish the executable as a GitHub Release asset instead of committing it to the source repository.

Project structure:

```text
CC_LED/
  README.md
  requirements.txt
  build_pyinstaller.py
  main.py
  cc_led/
    app.py
    config.py
    events.py
    reducer.py
    server.py
    hook_adapter.py
    installer.py
    codex_installer.py
    health.py
    sound.py
    assets/
      sounds/
        F1TR.wav
    ui/
      effects.py
      icons.py
      overlay.py
      tray.py
  tests/
```
