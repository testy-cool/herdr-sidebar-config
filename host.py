"""The platform layer: the only module that chooses an operating system.

Callers use these names and never branch on the platform themselves:

- ``Lock(path)``: an inter-process lock; ``acquire(blocking)``, ``release()``,
  and ``with Lock(path):`` for a blocking critical section.
- ``connect(path, timeout)``: a Herdr API connection with ``sendall`` and
  ``recv``; every step raises ``TimeoutError`` past ``timeout`` seconds.
- ``WakeListener(state)`` / ``wake(state)``: the scheduler's wake channel. A
  wake carries no data; it only makes the scheduler reread its state.
- ``spawn_detached(argv, log)``: start a process that outlives the hook and
  holds none of Herdr's output pipes.
- ``terminal()``: a context manager yielding the popup's terminal with
  ``size()``, ``clear()``, ``draw(y, x, text, style)``, ``refresh()``, and
  ``key()``. Styles are ``None``, ``"bold"``, or ``"reverse"``; keys are
  ``"up"``, ``"down"``, ``"left"``, ``"right"``, ``"enter"``, ``"escape"``,
  ``"backspace"``, ``"resize"``, or one typed character.
- ``entry(name)``: this platform's manifest id for a logical action or pane.
- ``config_home()``, ``font_dir()``, ``ghostty_config()``: default locations;
  ``ghostty_config()`` is ``None`` where setup edits no terminal config.
- ``INTERPRETER_RECORD``: the plugin-config file naming the hook interpreter,
  or ``None`` where the hook launcher finds Python itself.
- ``font_available(family)``: whether ``icons = "auto"`` may use the font.
- ``Fonts(path, family, terminal_config)``: the icon font's platform steps:
  ``files()`` (further managed files), ``release()`` before the font file is
  replaced or removed, ``register()`` returning what ``unregister(prior)``
  later restores, ``checks()`` and ``hints()`` for doctor, and ``notes()``
  shown after installation.
"""
import os
import sys

if os.name == "nt":
    from host_windows import (INTERPRETER_RECORD, Fonts, Lock, WakeListener, config_home,
                              connect, font_available, font_dir, ghostty_config,
                              spawn_detached, terminal, wake)
    PLATFORM = "windows"
else:
    from host_posix import (INTERPRETER_RECORD, Fonts, Lock, WakeListener, config_home,
                            connect, font_available, font_dir, ghostty_config,
                            spawn_detached, terminal, wake)
    PLATFORM = "macos" if sys.platform == "darwin" else "linux"

# Herdr rejects duplicate action/pane ids even when their platforms differ, so
# Windows declares its own. Keep this map and herdr-plugin.toml in step.
_POSIX = {"settings": "settings", "refresh": "refresh", "clear": "clear"}
ENTRIES = {"linux": _POSIX, "macos": _POSIX,
           "windows": {name: name + "-windows" for name in _POSIX}}


def entry(name):
    return ENTRIES[PLATFORM][name]


__all__ = ["ENTRIES", "INTERPRETER_RECORD", "PLATFORM", "Fonts", "Lock", "WakeListener",
           "config_home", "connect", "entry", "font_available", "font_dir", "ghostty_config",
           "spawn_detached", "terminal", "wake"]
