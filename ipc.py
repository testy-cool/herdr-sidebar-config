"""Bounded, direct Herdr socket requests; no subprocess per display update."""
import json
import os
import socket


def call(method, params):
    path = os.environ.get("HERDR_SOCKET_PATH")
    if not path:
        raise RuntimeError("Herdr did not provide this session's socket path.")
    request = {"id": "sidebar", "method": method, "params": params}
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(2)
        client.connect(path)
        client.sendall((json.dumps(request) + "\n").encode())
        response = bytearray()
        while b"\n" not in response:
            data = client.recv(65536)
            if not data:
                raise RuntimeError("Herdr closed the request without a reply.")
            response.extend(data)
            if len(response) > 4 * 1024 * 1024:
                raise RuntimeError("Herdr reply exceeded the display request limit.")
    reply = json.loads(response.split(b"\n", 1)[0])
    if "error" in reply:
        raise RuntimeError(f"{method}: {reply['error'].get('message', reply['error'])}")
    return reply["result"]
