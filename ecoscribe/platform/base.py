"""The platform contract: everything a platform must provide, and where each one does (dictado-8tf).

Shared code (engine logic, text, meetings, sessions, calendar, crash reports, the window) works on
every platform by itself. What differs per OS is listed here. Each capability names, per platform:

- "module:Name[,Name...]"  where it lives (checked from the source: the file defines those names)
- "file:path"              a file that must exist (packaging scripts)
- ("ticket", "dictado-xxx") not built yet; the ticket must be open and listed in FEATURES.md
- ("not_needed", "reason")  the OS doesn't need it; the reason shows in FEATURES.md

tests/test_platform_contract.py fails when a capability lacks an entry for a platform, when an
entry points at code that isn't there, or when FEATURES.md doesn't list it. Add a capability here
the moment one platform gets something OS-specific, with a ticket for the other.
"""
from __future__ import annotations

PLATFORMS = ("windows", "macos")

CAPABILITIES: dict[str, dict] = {
    "Hotkey (tap / hold / combo, Esc cancel)": {
        "windows": "ecoscribe.platform.windows.hook:HookThread",
        "macos": "ecoscribe.platform.macos.keyhook:HookThread",
    },
    "Language key (dictation key + L picks the next language)": {
        "windows": "ecoscribe.platform.windows.hook:VK_LANG",
        "macos": "ecoscribe.platform.macos.keyhook:KC_LANG,HookThread",  # Right Command + L
    },
    "Take back the last paste (\"scratch that\") and paste it again (dictation key + R)": {
        "windows": "ecoscribe.platform.windows.deliver:undo_paste,foreground_window",  # + hook.VK_REPASTE
        "macos": ("ticket", "dictado-cp1"),
    },
    "Command mode (dictation key + E: say how to change the selection)": {
        "windows": "ecoscribe.platform.windows.deliver:copy_selection",  # + hook.VK_EDIT
        "macos": ("ticket", "dictado-waw"),
    },
    "Command mode keys picked in Settings (the dictation key + a letter, or a combo)": {  # dictado-a1d
        "windows": "ecoscribe.platform.windows.hook:HookThread",  # HookThread.action_keys / edit_combo, --hook-edit
        "macos": ("ticket", "dictado-waw"),  # the Mac has no command mode yet; it takes [text] command_key with it
    },
    "Numpad Enter as a second dictation key": {
        "windows": "ecoscribe.platform.windows.hook:HookThread",  # HookThread.numpad_alias
        "macos": "ecoscribe.platform.macos.keyhook:HookThread",  # HookThread.numpad_alias (keycode 76)
    },
    "No text box at the stop: keep it on the clipboard, say so": {
        "windows": "ecoscribe.platform.windows.context:focus_kind,classify_focus",
        "macos": "ecoscribe.platform.macos.context:focus_kind,classify_focus",  # Accessibility: the focused element's role
    },
    "Dark mode follows the system (Settings > Appearance: Match / Light / Dark)": {  # dictado-u9h
        "windows": "ecoscribe.platform.windows.desktop:system_dark",  # AppsUseLightTheme; the page: prefers-color-scheme
        "macos": "ecoscribe.platform.macos.desktop:system_dark",  # AppleInterfaceStyle
    },
    "Title bar matches the window's light or dark look": {  # dictado-u9h
        "windows": "ecoscribe.platform.windows.desktop:dark_title_bar",  # DWMWA_USE_IMMERSIVE_DARK_MODE
        "macos": ("ticket", "dictado-zkh"),  # follows the system already; a forced theme needs NSApp.appearance
    },
    "Which app gets the paste, read just before it (Style per app)": {  # dictado-h0m
        "windows": "ecoscribe.platform.windows.deliver:foreground_exe",  # + context.foreground_title for a browser tab
        "macos": "ecoscribe.platform.macos.context:foreground_app,app_key,foreground_title",  # bundle id, not the translated name
    },
    "Paste text where the cursor is": {
        "windows": "ecoscribe.platform.windows.deliver:deliver,set_clipboard_text",
        "macos": "ecoscribe.platform.macos.deliver:deliver,set_clipboard_text",
    },
    "Names on your screen": {
        "windows": "ecoscribe.platform.windows.context:window_texts",
        "macos": "ecoscribe.platform.macos.context:window_texts",
    },
    "Speech engine on the GPU": {
        "windows": "ecoscribe.engine:Engine",  # faster-whisper / CTranslate2 on CUDA
        "macos": "ecoscribe.platform.macos.mlx_engine:MlxWhisperModel",  # mlx-whisper on Metal
    },
    "Show a download in its folder": {
        "windows": "ecoscribe.platform.windows.desktop:reveal",
        "macos": "ecoscribe.platform.macos.desktop:reveal",
    },
    "Mic list in Settings": {
        "windows": "ecoscribe.platform.windows.desktop:input_names",
        "macos": "ecoscribe.platform.macos.desktop:input_names",
    },
    "Unmute the mic only while recording": {
        "windows": "ecoscribe.micgate:MicGate",
        "macos": ("not_needed", "macOS mics aren't left muted at volume 0; the option is hidden"),
    },
    "System audio for meetings (the other side of a call)": {
        "windows": "ecoscribe.loopback:Loopback",
        "macos": "ecoscribe.platform.macos.systap:Loopback",  # Core Audio process tap (ecoscribe-systap helper)
    },
    "Call detection (who uses the mic, call windows)": {
        "windows": "ecoscribe.platform.windows.detect:read_consent,window_titles,running_apps,health",
        "macos": "ecoscribe.platform.macos.detect:read_consent,window_titles,running_apps,health",
    },
    "Tray / menu bar, pill and prompt box": {
        "windows": "ecoscribe.platform.windows.shell:Tray,Overlay,PromptWindow",
        "macos": "ecoscribe.platform.macos.shell:Tray,Overlay,PromptWindow",
    },
    "Smooth pill: see-through corners, a soft shadow, the app's font": {
        "windows": "ecoscribe.platform.windows.pillart:dictating,busy,notice,meeting_chip,meeting_open",  # dictado-acm
        "macos": ("ticket", "dictado-vx1"),  # AppKit already draws it smooth; shadow and font to check
    },
    "Live text on the pill while dictating": {
        "windows": "ecoscribe.platform.windows.shell:Overlay",  # Overlay.live: two lines under the timer
        "macos": "ecoscribe.platform.macos.shell:Overlay",  # Overlay.live: a 460x84 box, the newest two lines under the timer
    },
    "Speakers pass during a call (when the GPU has room)": {
        "windows": "ecoscribe.platform.windows.speakers:gpu_room",  # nvidia-smi free memory >= 3 GB
        "macos": ("ticket", "dictado-692"),  # gpu_room() is False: the pass waits for the call to end
    },
    "Start at login": {
        "windows": "ecoscribe.platform.windows.startup:enable,disable,is_enabled",
        "macos": "ecoscribe.platform.macos.startup:enable,disable,is_enabled",
    },
    "Single instance": {
        "windows": "ecoscribe.platform.windows.sysutil:single_instance",
        "macos": "ecoscribe.platform.macos.sysutil:single_instance",
    },
    "Settings saved -> restart signal": {
        "windows": "ecoscribe.platform.windows.ipc:ReloadWatcher",
        "macos": "ecoscribe.platform.macos.ipc:ReloadWatcher",
    },
    "Window buttons -> background app (commands)": {
        "windows": "ecoscribe.platform.windows.commands:Watcher",
        "macos": "ecoscribe.platform.macos.commands:Watcher",
    },
    "Watchdog: watch, restart, kill a frozen app": {
        "windows": "ecoscribe.supervise:WinProc",
        "macos": "ecoscribe.supervise:MacProc",
    },
    "A frozen app can't lag the computer's input": {
        "windows": "ecoscribe.platform.windows.hook:HookClient",  # hooks in their own process
        "macos": ("not_needed", "macOS times out a stuck event tap by itself and Ecoscribe re-enables it"),
    },
    "Speakers + Remember voices (add-on)": {
        "windows": "ecoscribe.platform.windows.speakers:addon_exe",  # the old Dictado Speakers still found
        "macos": "ecoscribe.platform.macos.speakers:addon_exe",  # Ecoscribe Speakers.app (the old Dictado Speakers.app still found), pyannote on MPS
    },
    "Claude Code from the app (summaries, self-corrections)": {
        "windows": "ecoscribe.claude_cli:default_command",  # wsl.exe + bash login shell
        "macos": ("ticket", "dictado-1xg"),  # zsh login shell, not yet tried on the Mac
    },
    "Claude app connection (MCP)": {
        "windows": "ecoscribe.platform.windows.claude_link:config_files",
        "macos": "ecoscribe.platform.macos.claude_link:config_files",  # connect() is shared
    },
    "Word confidence for Insights (clarity, words it wasn't sure of)": {
        "windows": "ecoscribe.engine:Engine",  # Engine.word_confidence: faster-whisper word timestamps, after the paste
        "macos": "ecoscribe.platform.macos.mlx_engine:MlxWhisperModel",  # the dictation's tokens aligned (find_alignment), ~0.56 s
    },
    "Window title at the paste (who a dictation was for: people / AI app)": {
        "windows": "ecoscribe.platform.windows.context:foreground_title",  # GetWindowText of the foreground window
        "macos": "ecoscribe.platform.macos.context:foreground_title",  # AXFocusedWindow's AXTitle (desktop check: dictado-9jc.7)
    },
    "App at the paste by a locale-independent id (people / AI app)": {
        "windows": ("not_needed", "process names (slack.exe) are the same in every language"),
        "macos": "ecoscribe.platform.macos.context:foreground_app",  # bundle id -> the English name coach knows (dictado-uee)
    },
    "Setup: permissions step (first run)": {
        "windows": ("not_needed", "Windows asks for no permission to listen, type or watch the keyboard"),
        "macos": "ecoscribe.platform.macos.permissions:status,open_pane,DICTATION",  # Api.setup_info / open_permission
    },
    "Setup: speech model download with progress": {
        "windows": "ecoscribe.models:ensure_local,prepare,is_ready",  # progress from the HF blobs (dictado-zpz)
        "macos": "ecoscribe.platform.macos.mlx_engine:ensure_mlx,is_cached_mlx",  # bytes from the HF blobs (dictado-kuu)
    },
    "GPU runtime: the CUDA libraries download once, not in every installer": {
        "windows": "ecoscribe.gpu_runtime:ensure,Fetcher,dll_root",  # %LOCALAPPDATA%\\ecoscribe\\runtime\\<version> (dictado-7e1)
        "macos": ("not_needed", "no CUDA: mlx runs on Metal, which comes with macOS"),
    },
    "Install a new version by itself: when idle or at Quit, never in a call (Settings switch, off by default; Home > Install when idle)": {
        "windows": "ecoscribe.selfupdate:SelfUpdater,run_installer,input_idle_s",  # the Inno Setup installer, silent
        "macos": ("ticket", "dictado-6gr"),  # the .dmg: replace Ecoscribe.app; until then Download only
    },
    "Installer": {
        "windows": "file:packaging/windows/ecoscribe.iss",
        "macos": "file:tools/build_mac.py",  # Ecoscribe.app + .dmg, signed so permissions survive updates
    },
}
