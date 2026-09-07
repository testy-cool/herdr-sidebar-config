"""One sleeping process per session; wake only at a quiet-workspace deadline."""
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
    from runtime import PLUGIN_ID, herdr_binary, run_herdr
    state = Path(os.environ["HERDR_PLUGIN_STATE_DIR"])
    with os.fdopen(int(sys.argv[1]), "a") as timer_lock, socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as wake:
        path = Path(address(state))
        path.unlink(missing_ok=True)
        wake.bind(str(path))
        path.chmod(0o600)
        while True:
            with (state / "group-headers.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                deadline = read_state(state / "activity.json").get("next_deadline")
                if deadline is None:
                    path.unlink(missing_ok=True)
                    fcntl.flock(timer_lock, fcntl.LOCK_UN)
                    return
            delay = deadline - time.time()
            if delay > 0:
                wake.settimeout(delay)
                try:
                    wake.recv(128)
                    continue
                except socket.timeout:
                    pass
            # Disabled plugins must not repopulate metadata after uninstall.
            plugins = run_herdr(herdr_binary(), "plugin", "list", "--json")["result"]["plugins"]
            if not any(p["plugin_id"] == PLUGIN_ID and p["enabled"] for p in plugins):
                path.unlink(missing_ok=True)
                return
            refresh()


if __name__ == "__main__":
    run()
