"""Windows platform layer: byte-range locks, named pipes, localhost UDP, VT console.

Herdr on Windows writes ``HERDR_SOCKET_PATH`` as a small text file and listens
on the named pipe ``\\\\.\\pipe\\`` followed by that full path. Pipe I/O is
overlapped so every step has the same bounded timeout as the POSIX socket.
"""
import _winapi
from contextlib import contextmanager
import ctypes
import errno
import msvcrt
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time
import winreg

ERROR_BROKEN_PIPE = 109
ERROR_PIPE_BUSY = 231
ERROR_IO_PENDING = 997
WAIT_TIMEOUT = 258
POLL = 0.01


class Lock:
    """Locks one byte at offset zero.

    Closing a handle releases its lock only "in an unspecified time", so close
    unlocks explicitly: a scheduler started right after a probe must find the
    lock free.
    """

    def __init__(self, path):
        self._fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_BINARY, 0o666)
        self._held = False

    def acquire(self, blocking=True):
        while True:
            os.lseek(self._fd, 0, os.SEEK_SET)
            try:
                msvcrt.locking(self._fd, msvcrt.LK_NBLCK, 1)
                self._held = True
                return True
            except OSError as error:
                if error.errno not in (errno.EACCES, errno.EDEADLOCK):
                    raise
                if not blocking:
                    return False
            # msvcrt's own blocking mode gives up after ten seconds.
            time.sleep(POLL)

    def release(self):
        os.lseek(self._fd, 0, os.SEEK_SET)
        msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
        self._held = False

    def close(self):
        if self._fd is not None:
            if self._held:
                self.release()
            os.close(self._fd)
            self._fd = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.close()


class _Pipe:
    def __init__(self, name, timeout):
        self._timeout = timeout
        deadline = time.monotonic() + timeout
        while True:
            try:
                self._handle = _winapi.CreateFile(
                    name, _winapi.GENERIC_READ | _winapi.GENERIC_WRITE, 0, _winapi.NULL,
                    _winapi.OPEN_EXISTING, _winapi.FILE_FLAG_OVERLAPPED, _winapi.NULL)
                return
            except OSError as error:
                if error.winerror != ERROR_PIPE_BUSY:
                    raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Herdr's API pipe stayed busy.")
            try:
                _winapi.WaitNamedPipe(name, max(1, int(remaining * 1000)))
            except OSError:
                pass  # Timed out or vanished; the next attempt says which.

    def _finish(self, overlapped, pending):
        if pending:
            result = _winapi.WaitForMultipleObjects([overlapped.event], False,
                                                    int(self._timeout * 1000))
            if result == WAIT_TIMEOUT:
                overlapped.cancel()
                try:
                    overlapped.GetOverlappedResult(True)
                except OSError:
                    pass
                raise TimeoutError("Herdr did not answer in time.")
        return overlapped.GetOverlappedResult(True)

    def sendall(self, data):
        view = memoryview(data)
        while view:
            overlapped, error = _winapi.WriteFile(self._handle, view, overlapped=True)
            written, _ = self._finish(overlapped, error == ERROR_IO_PENDING)
            view = view[written:]

    def recv(self, size):
        try:
            overlapped, error = _winapi.ReadFile(self._handle, size, overlapped=True)
            self._finish(overlapped, error == ERROR_IO_PENDING)
        except BrokenPipeError:
            return b""
        except OSError as error:
            if error.winerror == ERROR_BROKEN_PIPE:
                return b""
            raise
        return overlapped.getbuffer()

    def close(self):
        if self._handle is not None:
            _winapi.CloseHandle(self._handle)
            self._handle = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def connect(path, timeout):
    return _Pipe("\\\\.\\pipe\\" + str(path), timeout)


def _port_file(state):
    return Path(state) / "deadline.port"


class WakeListener:
    """A localhost UDP socket whose port is published in the state directory.

    Any local process could send to it; a wake only triggers a state reread,
    so a forged datagram is harmless.
    """

    def __init__(self, state):
        self._file = _port_file(state)
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self._socket.bind(("127.0.0.1", 0))
            temporary = self._file.with_suffix(".tmp")
            temporary.write_text(str(self._socket.getsockname()[1]), encoding="utf-8")
            temporary.replace(self._file)
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
            self._file.unlink(missing_ok=True)
            self._socket.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def wake(state):
    try:
        port = int(_port_file(state).read_text(encoding="utf-8"))
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            client.sendto(b"refresh", ("127.0.0.1", port))
    except (OSError, ValueError):
        pass  # A starting scheduler reads the newest state after binding.


def spawn_detached(argv, log):
    # Only the log handle is inherited: holding Herdr's output pipes would keep
    # the hook "running" and occupy one of Herdr's concurrent plugin slots.
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    with open(log, "a", encoding="utf-8") as stream:
        return subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=stream, stderr=stream,
                                creationflags=flags, close_fds=True)


ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
STD_OUTPUT_HANDLE = -11
SCAN_KEYS = {"H": "up", "P": "down", "K": "left", "M": "right"}
KEYS = {"\r": "enter", "\n": "enter", "\x1b": "escape", "\x03": "escape", "\b": "backspace"}
STYLES = {None: "", "bold": "\x1b[1m", "reverse": "\x1b[7m"}


class _Console:
    """msvcrt reads keys; VT sequences draw. Polls the size to notice resizes."""

    def __init__(self, stream):
        self._stream, self._buffer = stream, []
        self._size = self._measure()

    def _measure(self):
        columns, lines = shutil.get_terminal_size()
        return lines, columns

    def size(self):
        self._size = self._measure()
        return self._size

    def clear(self):
        self._buffer.append("\x1b[H\x1b[2J")

    def draw(self, y, x, text, style=None):
        self._buffer.append(f"\x1b[{y + 1};{x + 1}H{STYLES[style]}{text}\x1b[0m")

    def refresh(self):
        self._stream.write("".join(self._buffer))
        self._stream.flush()
        self._buffer = []

    def key(self):
        while not msvcrt.kbhit():
            if self._measure() != self._size:
                return "resize"
            time.sleep(0.05)
        char = msvcrt.getwch()
        if char in ("\x00", "\xe0"):
            return SCAN_KEYS.get(msvcrt.getwch(), "")
        return KEYS.get(char, char)


@contextmanager
def terminal():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
    mode = ctypes.c_uint32()
    console = bool(kernel32.GetConsoleMode(handle, ctypes.byref(mode)))
    if console:
        kernel32.SetConsoleMode(handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)
    stream = sys.stdout
    stream.write("\x1b[?1049h\x1b[?25l")
    try:
        yield _Console(stream)
    finally:
        stream.write("\x1b[0m\x1b[?25h\x1b[?1049l")
        stream.flush()
        if console:
            kernel32.SetConsoleMode(handle, mode.value)


def config_home():
    return Path(os.environ["APPDATA"]) / "herdr"


def font_dir():
    return Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "Windows" / "Fonts"


def ghostty_config():
    return None


# Hooks prefer the interpreter setup ran with; see run.cmd.
INTERPRETER_RECORD = "python-path.txt"
FONTS_KEY = r"Software\Microsoft\Windows NT\CurrentVersion\Fonts"


def _registrations(family):
    """Yield (hive, value name, file) for every registration of ``family``."""
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            key = winreg.OpenKey(hive, FONTS_KEY)
        except OSError:
            continue
        with key:
            for index in range(winreg.QueryInfoKey(key)[1]):
                name, value, _ = winreg.EnumValue(key, index)
                face = name.rsplit(" (", 1)[0]
                if isinstance(value, str) and (face == family or face.startswith(family + " ")):
                    yield hive, name, value


def font_available(family):
    # Machine-wide registrations name a file in the Windows fonts directory.
    windows = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    return any((windows / value).is_file() for _, _, value in _registrations(family))


def _value_name(family):
    return family + " Regular (TrueType)"


def register_font(path, family):
    """Register ``path`` for this user; return the value it replaced, if any."""
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, FONTS_KEY) as key:
        try:
            prior = winreg.QueryValueEx(key, _value_name(family))[0]
        except FileNotFoundError:
            prior = None
        winreg.SetValueEx(key, _value_name(family), 0, winreg.REG_SZ, str(path))
    return prior


def unregister_font(path, family, prior=None):
    """Put back ``prior``, or drop a registration naming ``path``."""
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, FONTS_KEY) as key:
        if prior is not None:
            winreg.SetValueEx(key, _value_name(family), 0, winreg.REG_SZ, prior)
            return
        try:
            current = winreg.QueryValueEx(key, _value_name(family))[0]
        except FileNotFoundError:
            return
        if os.path.normcase(current) == os.path.normcase(str(path)):
            winreg.DeleteValue(key, _value_name(family))


def font_registered(path, family):
    return any(hive == winreg.HKEY_CURRENT_USER and
               os.path.normcase(value) == os.path.normcase(str(path))
               for hive, _, value in _registrations(family))


def _terminal_settings():
    local = Path(os.environ["LOCALAPPDATA"])
    packages = local / "Packages"
    return [packages / "Microsoft.WindowsTerminal_8wekyb3d8bbwe" / "LocalState" / "settings.json",
            packages / "Microsoft.WindowsTerminalPreview_8wekyb3d8bbwe" / "LocalState" / "settings.json",
            local / "Microsoft" / "Windows Terminal" / "settings.json"]


def terminal_fallback(family):
    """Read-only: does any Windows Terminal font face list ``family``?"""
    face = re.compile(r'"(?:face|fontFace)"\s*:\s*"[^"]*' + re.escape(family))
    for path in _terminal_settings():
        try:
            if face.search(path.read_text(encoding="utf-8-sig")):
                return True
        except OSError:
            continue
    return False


class Fonts:
    """A per-user font registration. Setup never writes Windows Terminal's
    settings.json (JSONC, user-owned); doctor only reads it."""

    def __init__(self, path, family, terminal_config=None):
        self._path, self._family = path, family

    def files(self):
        return {}

    def release(self):
        # Windows' font cache holds a registered file open; it lets go about
        # a second after the registration disappears.
        unregister_font(self._path, self._family)

    def register(self):
        return register_font(self._path, self._family)

    def unregister(self, prior):
        unregister_font(self._path, self._family, prior)

    def checks(self):
        return {"font_registered": font_registered(self._path, self._family),
                "windows_terminal_fallback": terminal_fallback(self._family)}

    def notes(self):
        return [f'Windows Terminal: append ", {self._family}" to each profile\'s font face '
                "(Settings > Profile > Appearance > Font face), then open a new Windows "
                "Terminal window. Herdr sessions keep running."]

    def hints(self):
        return {"windows_terminal_fallback": self.notes()[0]}
