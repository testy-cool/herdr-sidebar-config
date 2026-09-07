"""One scheduler: quiet deadlines plus optional, working-only animation frames."""
import fcntl
import os
import hashlib
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time


def address(state):
    key = hashlib.sha256(str(state.resolve()).encode()).hexdigest()[:20]
    return str(Path(tempfile.gettempdir()) / f"hs-{os.getuid()}-{key}.sock")


def ensure_timer(state, start=True):
    lock = (state / "deadline.lock").open("a")
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as client:
                try:
                    client.setblocking(False)
                    client.sendto(b"refresh", address(state))
                except OSError:
                    pass  # A starting timer reads the newest state after bind.
            return
        if not start:
            return
        with (state / "deadline.log").open("a") as log:
            subprocess.Popen([sys.executable, str(Path(__file__).resolve()), str(lock.fileno())],
                             pass_fds=(lock.fileno(),), stdin=subprocess.DEVNULL,
                             stdout=log, stderr=log, start_new_session=True)
    finally:
        # The child inherits the same locked file description.
        lock.close()


def run():
    from sidebar import read_state, refresh
    from runtime import PLUGIN_ID
    from ipc import call
    from animation import INTERVAL, publish_frame
    state = Path(os.environ["HERDR_PLUGIN_STATE_DIR"])
    with os.fdopen(int(sys.argv[1]), "a") as timer_lock, socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as wake:
        path = Path(address(state))
        path.unlink(missing_ok=True)
        wake.bind(str(path))
        path.chmod(0o600)
        next_frame = time.monotonic() + INTERVAL
        while True:
            with (state / "group-headers.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                cached = read_state(state / "activity.json")
                deadline = cached.get("next_deadline")
                rows = cached.get("animation_rows") or []
                if deadline is None and not rows:
                    path.unlink(missing_ok=True)
                    fcntl.flock(timer_lock, fcntl.LOCK_UN)
                    return
                # The same lock protects lifecycle refreshes and frame writes.
                # Once a refresh clears a row, no old frame can put it back.
                if rows and time.monotonic() >= next_frame:
                    if not publish_frame(rows, time.monotonic()):
                        path.unlink(missing_ok=True)
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
                wake.settimeout(delay)
                try:
                    wake.recv(128)
                except socket.timeout:
                    pass
                continue
            # Disabled plugins must not repopulate metadata after uninstall.
            plugins = call("plugin.list", {"plugin_id": PLUGIN_ID})["plugins"]
            if not any(p["plugin_id"] == PLUGIN_ID and p["enabled"] for p in plugins):
                path.unlink(missing_ok=True)
                return
            refresh()


if __name__ == "__main__":
    try:
        run()
    except (OSError, RuntimeError, ValueError) as error:
        # A failed server request ends the worker instead of spinning retries.
        # A later lifecycle event can start a fresh worker.
        print(f"Sidebar scheduler stopped: {error}", file=sys.stderr)
