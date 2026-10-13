import json
import os
import socket
import struct

MAX_MESSAGE_SIZE = 16 * 1024 * 1024  # 16MB safety cap to avoid oversized memory allocations


def send_json(sock, data):
    try:
        payload = json.dumps(data, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Data is not JSON serializable: {exc}") from exc

    if len(payload) > MAX_MESSAGE_SIZE:
        raise ValueError(f"Payload exceeds maximum allowed size of {MAX_MESSAGE_SIZE} bytes")

    header = struct.pack('!I', len(payload))
    sock.sendall(header + payload)


def recv_json(sock):
    header = recvall(sock, 4)
    if not header:
        return None

    try:
        msg_len = struct.unpack('!I', header)[0]
    except struct.error:
        return None

    if msg_len == 0 or msg_len > MAX_MESSAGE_SIZE:
        return None

    payload = recvall(sock, msg_len)
    if not payload:
        return None

    try:
        return json.loads(payload.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def recvall(sock, n):
    if not isinstance(n, int) or n <= 0:
        return None

    data = bytearray()
    while len(data) < n:
        try:
            packet = sock.recv(n - len(data))
            if not packet:
                return None
            data.extend(packet)
        except (socket.error, OSError, ValueError):
            return None
    return bytes(data)


def send_file(sock, filename, filepath):
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"File not found: {filepath}")

    filesize = os.path.getsize(filepath)
    send_json(sock, {'type': 'FILE_START', 'filename': filename, 'filesize': filesize})

    with open(filepath, 'rb') as f:
        while True:
            chunk = f.read(4096)
            if not chunk:
                break
            sock.sendall(chunk)

