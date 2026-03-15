import struct
import json
import socket

def send_json(sock, data):
    # Serialize JSON to bytes
    payload = json.dumps(data).encode('utf-8')
    # Create 4-byte length prefix
    header = struct.pack('!I', len(payload))
    sock.sendall(header + payload)

def recv_json(sock):
    # Receive 4-byte length prefix
    header = recvall(sock, 4)
    if not header:
        return None
    msg_len = struct.unpack('!I', header)[0]
    # Receive the actual payload
    payload = recvall(sock, msg_len)
    if not payload:
        return None
    return json.loads(payload.decode('utf-8'))

def recvall(sock, n):
    # Helper function to recv n bytes or return None if EOF is hit
    data = bytearray()
    while len(data) < n:
        try:
            packet = sock.recv(n - len(data))
            if not packet:
                return None
            data.extend(packet)
        except Exception:
            return None
    return bytes(data)

def send_file(sock, filename, filepath):
    import os
    filesize = os.path.getsize(filepath)
    # Send metadata
    send_json(sock, {'type': 'FILE_START', 'filename': filename, 'filesize': filesize})
    
    # Send file data in chunks
    with open(filepath, 'rb') as f:
        while True:
            chunk = f.read(4096)
            if not chunk:
                break
            sock.sendall(chunk)

