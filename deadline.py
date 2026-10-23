"""One scheduler: quiet deadlines plus optional, working-only animation frames."""
import os
from pathlib import Path
import subprocess
import sys
import time


def code_stamp(root=Path(__file__).resolve().parent):
    """Name, size and change time of each module, so an update can be noticed."""
    stamp = []
    for path in sorted(root.glob("*.py")):
        try:
            info = path.stat()
        except OSError:
            continue  # Removed while a checkout is being updated.
        stamp.append((path.name, info.st_size, info.st_mtime_ns))
    return stamp


# Taken before any other plugin module loads, so a change made while this
# scheduler starts still counts as newer than the code it runs.
STARTED = code_stamp() if __name__ == "__main__" else None

from host import Lock, WakeListener, spawn_detached, wake  # noqa: E402


class CodeWatch:
    """Notices that the plugin's code changed and then stayed the same.

    Setup links the plugin from its checkout, so a git pull changes the code
    under a long-lived scheduler. The time is the monotonic clock, so a wall
    clock correction cannot hold a handover back.
    """

    def __init__(self, started, now):
        self.started = self.seen = started
        self.since = now
        self.rejected = None

    def settled(self, stamp, now):
        if stamp != self.seen:
            self.seen, self.since = stamp, now
            return False
        return stamp not in (self.started, self.rejected) and now - self.since >= 1


def load():
    """Everything the scheduler needs from the rest of the plugin."""
    from sidebar import read_state, refresh
    from runtime import PLUGIN_ID
    from ipc import call
    from animation import INTERVAL, publish_frame
    return read_state, refresh, PLUGIN_ID, call, INTERVAL, publish_frame


def imports_cleanly(root=Path(__file__).resolve().parent):
    """Whether the updated checkout loads what a scheduler needs, so a broken
    one never takes over."""
    try:
        return subprocess.run([sys.executable, "-c", "import deadline; deadline.load()"],
                              cwd=root, capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def ensure_timer(state, start=True):
    # Probe only: the scheduler takes the lock itself, so no locked handle has
    # to cross a process boundary. A probe racing a starting scheduler is
    # harmless; the extra scheduler fails to lock and exits.
    timer = Lock(state / "deadline.lock")
    try:
        if not timer.acquire(blocking=False):
            wake(state)
            return
    finally:
        timer.close()
    if start:
        spawn_detached([sys.executable, str(Path(__file__).resolve())], state / "deadline.log")


def run():
    read_state, refresh, PLUGIN_ID, call, INTERVAL, publish_frame = load()
    state = Path(os.environ["HERDR_PLUGIN_STATE_DIR"])
    timer = Lock(state / "deadline.lock")
    if not timer.acquire(blocking=False):
        return  # Another scheduler already owns the deadlines.
    # A wake sent before this bind is lost, but the loop below reads the
    # newest state first.
    with WakeListener(state) as listener:
        next_frame = time.monotonic() + INTERVAL
        # Once updated code has settled and loads, hand the deadlines to a
        # fresh scheduler that runs it. A checkout that fails to load is
        # skipped until it changes again. Should the new scheduler still fail
        # to start, the next lifecycle refresh starts one, as after any stop.
        watch = CodeWatch(STARTED or code_stamp(), time.monotonic())
        checked = time.monotonic()
        while True:
            if time.monotonic() - checked >= 1:
                checked = time.monotonic()
                stamp = code_stamp()
                if watch.settled(stamp, checked):
                    # A change during the check leaves its result about older code.
                    if imports_cleanly() and code_stamp() == stamp:
                        print("Sidebar scheduler: plugin code changed, restarting", file=sys.stderr, flush=True)
                        listener.close()
                        timer.release()
                        spawn_detached([sys.executable, str(Path(__file__).resolve())], state / "deadline.log")
                        return
                    elif code_stamp() == stamp:
                        watch.rejected = stamp
            with Lock(state / "group-headers.lock"):
                cached = read_state(state / "activity.json")
                deadline = cached.get("next_deadline")
                rows = cached.get("animation_rows") or []
                if deadline is None and not rows:
                    listener.close()
                    timer.release()
                    return
                # The same lock protects lifecycle refreshes and frame writes.
                # Once a refresh clears a row, no old frame can put it back.
                if rows and time.monotonic() >= next_frame:
                    if not publish_frame(rows, time.monotonic()):
                        return
                    next_frame = time.monotonic() + INTERVAL
                elif not rows:
                    next_frame = time.monotonic() + INTERVAL
                waits = []
                if deadline is not None:
                    waits.append(deadline - time.time())
                if rows:
                    waits.append(next_frame - time.monotonic())
                delay = max(0, min(waits))
            if delay > 0:
                listener.wait(delay)
                continue
            # Disabled plugins must not repopulate metadata after uninstall.
            plugins = call("plugin.list", {"plugin_id": PLUGIN_ID})["plugins"]
            if not any(p["plugin_id"] == PLUGIN_ID and p["enabled"] for p in plugins):
                return
            refresh()


if __name__ == "__main__":
    sys.stderr.reconfigure(encoding="utf-8")
    try:
        run()
    except (OSError, RuntimeError, ValueError) as error:
        # A failed server request ends the worker instead of spinning retries.
        # A later lifecycle event can start a fresh worker.
        print(f"Sidebar scheduler stopped: {error}", file=sys.stderr)
