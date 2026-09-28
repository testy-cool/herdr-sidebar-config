"""Platform layer contracts, exercised with this platform's real primitives."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from unittest.mock import patch

import host
from ipc import call

ROOT = Path(__file__).resolve().parents[1]
HOLDER = """
import sys
sys.path.insert(0, sys.argv[1])
from host import Lock
lock = Lock(sys.argv[2])
lock.acquire()
print("locked", flush=True)
sys.stdin.readline()
"""


class LockTests(unittest.TestCase):
    def test_two_processes_exclude_each_other(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "test.lock")
            holder = subprocess.Popen([sys.executable, "-c", HOLDER, str(ROOT), str(path)],
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(holder.stdout.readline().strip(), "locked")
                lock = host.Lock(path)
                try:
                    self.assertFalse(lock.acquire(blocking=False))
                    holder.stdin.write("\n")
                    holder.stdin.flush()
                    holder.wait(10)
                    self.assertTrue(lock.acquire(blocking=False))
                finally:
                    lock.close()
            finally:
                holder.kill()
                holder.wait()
                holder.stdin.close()
                holder.stdout.close()

    def test_blocking_acquire_waits_for_release(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "test.lock")
            first = host.Lock(path)
            self.assertTrue(first.acquire())
            threading.Timer(0.2, first.release).start()
            with host.Lock(path) as second:
                self.assertFalse(first.acquire(blocking=False))
            first.close()

    def test_close_frees_the_lock_at_once(self):
        # The scheduler's non-blocking acquire runs right after a probe closes.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "test.lock")
            for _ in range(20):
                probe = host.Lock(path)
                self.assertTrue(probe.acquire(blocking=False))
                probe.close()
                other = host.Lock(path)
                try:
                    self.assertTrue(other.acquire(blocking=False))
                finally:
                    other.close()


class WakeTests(unittest.TestCase):
    def test_wake_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            with host.WakeListener(directory) as listener:
                self.assertFalse(listener.wait(0.05))
                host.wake(directory)
                self.assertTrue(listener.wait(5))

    def test_wake_without_listener_is_harmless(self):
        with tempfile.TemporaryDirectory() as directory:
            host.wake(directory)
            with host.WakeListener(directory):
                pass
            host.wake(directory)


class SpawnTests(unittest.TestCase):
    def test_detached_process_writes_to_log(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory, "worker.log")
            worker = host.spawn_detached([sys.executable, "-c", "print('worker ran')"], log)
            self.assertEqual(worker.wait(10), 0)
            self.assertIn("worker ran", log.read_text(encoding="utf-8"))


def reply_to(line):
    request = json.loads(line)
    return (json.dumps({"id": request["id"], "result": {"echo": request}}) + "\n").encode()


class PosixServer:
    def __init__(self, directory, answer):
        import socket
        self.path = str(Path(directory, "herdr.sock"))
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(self.path)
        self.server.listen(1)
        self.answer = answer
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self):
        connection, _ = self.server.accept()
        with connection:
            data = b""
            while b"\n" not in data:
                data += connection.recv(4096)
            if self.answer:
                connection.sendall(reply_to(data.split(b"\n")[0]))
            else:
                time.sleep(3)

    def close(self):
        self.thread.join(5)
        self.server.close()


class WindowsServer:
    def __init__(self, directory, answer):
        import _winapi
        self.winapi = _winapi
        self.path = f"{directory}\\herdr-{uuid.uuid4().hex}.sock"
        self.handle = _winapi.CreateNamedPipe(
            "\\\\.\\pipe\\" + self.path, _winapi.PIPE_ACCESS_DUPLEX, _winapi.PIPE_WAIT,
            1, 65536, 65536, 0, _winapi.NULL)
        self.answer = answer
        self.release = threading.Event()
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self):
        try:
            self.winapi.ConnectNamedPipe(self.handle)
        except OSError:
            pass  # The client connected before the server waited.
        data = b""
        while b"\n" not in data:
            chunk, _ = self.winapi.ReadFile(self.handle, 4096)
            data += chunk
        if self.answer:
            self.winapi.WriteFile(self.handle, reply_to(data.split(b"\n")[0]))
        else:
            self.release.wait(10)

    def close(self):
        self.release.set()
        self.thread.join(5)
        self.winapi.CloseHandle(self.handle)


Server = WindowsServer if os.name == "nt" else PosixServer


class TransportTests(unittest.TestCase):
    def test_request_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            server = Server(directory, answer=True)
            try:
                with patch.dict(os.environ, {"HERDR_SOCKET_PATH": server.path}):
                    result = call("plugin.list", {"plugin_id": "工作区"})
            finally:
                server.close()
        self.assertEqual(result["echo"]["method"], "plugin.list")
        self.assertEqual(result["echo"]["params"], {"plugin_id": "工作区"})

    def test_silent_server_times_out(self):
        with tempfile.TemporaryDirectory() as directory:
            server = Server(directory, answer=False)
            try:
                started = time.monotonic()
                with self.assertRaises(TimeoutError):
                    with host.connect(server.path, timeout=0.5) as client:
                        client.sendall(b'{"id": "x"}\n')
                        client.recv(1024)
                self.assertLess(time.monotonic() - started, 2.5)
            finally:
                server.close()

    def test_missing_server_raises_os_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(OSError):
                host.connect(str(Path(directory, "absent.sock")), timeout=0.5)


if __name__ == "__main__":
    unittest.main()
