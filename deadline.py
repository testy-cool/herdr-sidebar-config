"""One scheduler: quiet deadlines plus optional, working-only animation frames."""
import os
from pathlib import Path
import sys
import time

from host import Lock, WakeListener, spawn_detached, wake


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


def code_updated(started, stamp, now):
    """True once the code differs from the start and has not changed for a second."""
    return stamp != started and all(now - mtime / 1e9 >= 1 for _, _, mtime in stamp)


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
    from sidebar import read_state, refresh
    from runtime import PLUGIN_ID
    from ipc import call
    from animation import INTERVAL, publish_frame
    state = Path(os.environ["HERDR_PLUGIN_STATE_DIR"])
    timer = Lock(state / "deadline.lock")
    if not timer.acquire(blocking=False):
        return  # Another scheduler already owns the deadlines.
    # A wake sent before this bind is lost, but the loop below reads the
    # newest state first.
    with WakeListener(state) as listener:
        next_frame = time.monotonic() + INTERVAL
        # Setup links the plugin from its checkout, so a git pull changes the
        # code under this long-lived process. Once the new code has settled,
        # hand the deadlines to a fresh scheduler that runs it.
        started, checked = code_stamp(), time.monotonic()
        while True:
            if time.monotonic() - checked >= 1:
                checked = time.monotonic()
                if code_updated(started, code_stamp(), time.time()):
                    print("Sidebar scheduler: plugin code changed, restarting", file=sys.stderr, flush=True)
                    listener.close()
                    timer.release()
                    spawn_detached([sys.executable, str(Path(__file__).resolve())], state / "deadline.log")
                    return
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
