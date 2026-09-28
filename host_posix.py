"""POSIX platform layer: flock, Unix sockets, a new session per worker, curses."""
from contextlib import contextmanager
import fcntl
import hashlib
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile


class Lock:
    def __init__(self, path):
        self._fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o666)

    def acquire(self, blocking=True):
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            return False
        return True

    def release(self):
        fcntl.flock(self._fd, fcntl.LOCK_UN)

    def close(self):
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.close()


def connect(path, timeout):
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.settimeout(timeout)
        client.connect(path)
    except BaseException:
        client.close()
        raise
    return client


def _address(state):
    key = hashlib.sha256(str(Path(state).resolve()).encode()).hexdigest()[:20]
    return str(Path(tempfile.gettempdir()) / f"hs-{os.getuid()}-{key}.sock")


class WakeListener:
    def __init__(self, state):
        self._path = Path(_address(state))
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            self._path.unlink(missing_ok=True)
            self._socket.bind(str(self._path))
            self._path.chmod(0o600)
        except BaseException:
            self._socket.close()
            raise

    def wait(self, timeout):
        """Return True when woken, False when ``timeout`` seconds passed."""
        self._socket.settimeout(timeout)
        try:
            self._socket.recv(128)
        except socket.timeout:
            return False
        return True

    def close(self):
        if self._socket.fileno() != -1:
            self._path.unlink(missing_ok=True)
            self._socket.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def wake(state):
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as client:
        try:
            client.setblocking(False)
            client.sendto(b"refresh", _address(state))
        except OSError:
            pass  # A starting scheduler reads the newest state after binding.


def spawn_detached(argv, log):
    with open(log, "a", encoding="utf-8") as stream:
        return subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=stream, stderr=stream,
                                start_new_session=True)


class _Curses:
    def __init__(self, curses, screen):
        self._curses, self._screen = curses, screen
        self._styles = {None: 0, "bold": curses.A_BOLD, "reverse": curses.A_REVERSE}
        self._keys = {curses.KEY_UP: "up", curses.KEY_DOWN: "down", curses.KEY_LEFT: "left",
                      curses.KEY_RIGHT: "right", curses.KEY_ENTER: "enter", "\n": "enter",
                      "\r": "enter", "\x1b": "escape", curses.KEY_BACKSPACE: "backspace",
                      "\x7f": "backspace", "\b": "backspace", curses.KEY_RESIZE: "resize"}

    def size(self):
        return self._screen.getmaxyx()

    def clear(self):
        self._screen.erase()

    def draw(self, y, x, text, style=None):
        try:
            self._screen.addstr(y, x, text, self._styles[style])
        except self._curses.error:
            pass  # Writing the last cell moves the cursor off screen.

    def refresh(self):
        self._screen.refresh()

    def key(self):
        key = self._screen.get_wch()
        if key in self._keys:
            return self._keys[key]
        return key if isinstance(key, str) else ""


@contextmanager
def terminal():
    import curses

    screen = curses.initscr()
    try:
        curses.noecho()
        curses.cbreak()
        screen.keypad(True)
        curses.curs_set(0)
        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, -1, -1)
            screen.bkgd(" ", curses.color_pair(1))
        yield _Curses(curses, screen)
    finally:
        screen.keypad(False)
        curses.nocbreak()
        curses.echo()
        curses.endwin()


def _xdg():
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))


def config_home():
    return _xdg() / "herdr"


def font_dir():
    return Path.home() / ("Library/Fonts" if sys.platform == "darwin" else ".local/share/fonts")


def ghostty_config():
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/com.mitchellh.ghostty/config"
    return _xdg() / "ghostty/config"


INTERPRETER_RECORD = None  # run.sh finds python3 on PATH.


def font_available(family):
    command = shutil.which("fc-match")
    if command:
        result = subprocess.run([command, "--format", "%{family}", family],
                                capture_output=True, text=True, timeout=5)
        return result.returncode == 0 and family in result.stdout.split(",")
    return False


class Fonts:
    """A font file refreshed with fc-cache and mapped in Ghostty's config."""

    def __init__(self, path, family, terminal_config):
        self._path, self._ghostty = path, terminal_config

    def _ghostty_text(self):
        return self._ghostty.read_bytes().decode("utf-8") if self._ghostty.exists() else ""

    def files(self):
        from configuration import ghostty_mapping
        return {self._ghostty: ghostty_mapping(self._ghostty_text()).encode("utf-8")}

    def _cache(self):
        if shutil.which("fc-cache"):
            subprocess.run(["fc-cache", "-f", str(self._path.parent)], check=True, timeout=30)

    def release(self):
        pass

    def register(self):
        self._cache()

    def unregister(self, prior):
        self._cache()

    def checks(self):
        from configuration import GHOSTTY_MAPPING
        return {"ghostty_mapping": GHOSTTY_MAPPING in self._ghostty_text().splitlines()}

    def notes(self):
        return ["Open a fresh Ghostty process to load the icon font. Herdr sessions keep running."]

    def hints(self):
        return {}
