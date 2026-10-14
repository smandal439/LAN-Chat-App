import json
import os
import socket
import struct
import threading
import time
from contextlib import ExitStack

from protocol import recv_json, recvall, send_json


class Server:
    def __init__(self, port):
        self.port = port
        self.host = '0.0.0.0'
        self.server_socket = None
        self.clients = {}  # Map socket to username
        self.client_send_locks = {}
        self.running = False

    def start(self):
        if not isinstance(self.port, int) or not 0 <= self.port <= 65535:
            raise ValueError('Port must be an integer between 0 and 65535.')

        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.server_socket.bind((self.host, self.port))
            self.port = self.server_socket.getsockname()[1]
            self.server_socket.listen(5)
            self.running = True
            threading.Thread(target=self.accept_clients, daemon=True).start()
            return True
        except OSError as exc:
            self.server_socket.close()
            self.server_socket = None
            raise OSError(f'Unable to bind to port {self.port}: {exc}') from exc

    def accept_clients(self):
        while self.running:
            try:
                self.server_socket.settimeout(0.5)
                client_sock, _ = self.server_socket.accept()
                self.clients[client_sock] = None
                self.client_send_locks[client_sock] = threading.Lock()
                threading.Thread(target=self.handle_client, args=(client_sock,), daemon=True).start()
            except socket.timeout:
                continue
            except OSError:
                break
            except Exception:
                break

    def _remove_client(self, client_sock):
        if client_sock in self.clients:
            del self.clients[client_sock]
        try:
            client_sock.close()
        except OSError:
            pass
        self.broadcast_user_list()

    def _send_to_sockets(self, sockets, data):
        for client in list(sockets):
            try:
                with self.client_send_locks[client]:
                    client.sendall(data)
            except (OSError, ConnectionError, ValueError):
                self._remove_client(client)

    def broadcast_user_list(self):
        users = [u for u in self.clients.values() if isinstance(u, str) and u.strip()]
        msg = {'type': 'USER_LIST', 'users': users}
        payload = json.dumps(msg, separators=(',', ':')).encode('utf-8')
        header = struct.pack('!I', len(payload))
        self._send_to_sockets(list(self.clients.keys()), header + payload)

    def _sanitize_username(self, username):
        if not isinstance(username, str):
            return None
        username = username.strip()
        if not username:
            return None
        return username[:32]

    def handle_client(self, client_sock):
        while self.running:
            try:
                header_data = recvall(client_sock, 4)
                if not header_data:
                    break

                msg_len = struct.unpack('!I', header_data)[0]
                payload = recvall(client_sock, msg_len)
                if not payload:
                    break

                msg = json.loads(payload.decode('utf-8'))
                if not isinstance(msg, dict):
                    break

                msg_type = msg.get('type')
                if msg_type == 'JOIN':
                    username = self._sanitize_username(msg.get('username'))
                    if username is None:
                        break
                    self.clients[client_sock] = username
                    self._send_to_sockets(
                        [sock for sock in self.clients if sock != client_sock],
                        header_data + payload,
                    )
                    self.broadcast_user_list()
                    continue

                recipient = msg.get('recipient', 'All')
                if not isinstance(recipient, str):
                    recipient = 'All'

                if msg_type == 'CALL_SIGNAL':
                    sender = self.clients.get(client_sock)
                    call_id = msg.get('call_id')
                    action = msg.get('action')
                    if (
                        not sender
                        or recipient == 'All'
                        or not isinstance(call_id, str)
                        or len(call_id) != 32
                        or not isinstance(action, str)
                        or action not in ('offer', 'answer', 'reject', 'hangup')
                    ):
                        continue
                    if action in ('offer', 'answer') and not isinstance(msg.get('sdp'), dict):
                        continue
                    msg['username'] = sender
                    payload = json.dumps(msg, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
                    header_data = struct.pack('!I', len(payload))

                target_sockets = []
                if recipient == 'All':
                    target_sockets = [sock for sock in self.clients if sock != client_sock]
                else:
                    target_sockets = [
                        sock for sock, username in self.clients.items()
                        if sock != client_sock and username == recipient
                    ]

                if msg_type == 'FILE_START':
                    filesize = msg.get('filesize', 0)
                    if not isinstance(filesize, int) or filesize < 0:
                        break
                    received = 0
                    failed_targets = []
                    incomplete = False
                    with ExitStack() as send_locks:
                        for target in sorted(target_sockets, key=id):
                            send_locks.enter_context(self.client_send_locks[target])
                        for target in target_sockets:
                            try:
                                target.sendall(header_data + payload)
                            except (OSError, ConnectionError, ValueError):
                                failed_targets.append(target)

                        while received < filesize:
                            chunk_size = min(4096, filesize - received)
                            chunk = recvall(client_sock, chunk_size)
                            if not chunk:
                                incomplete = True
                                break
                            received += len(chunk)
                            for target in target_sockets:
                                if target in failed_targets:
                                    continue
                                try:
                                    target.sendall(chunk)
                                except (OSError, ConnectionError, ValueError):
                                    failed_targets.append(target)

                    for target in failed_targets:
                        self._remove_client(target)
                    if incomplete:
                        break
                    continue

                self._send_to_sockets(target_sockets, header_data + payload)
            except (json.JSONDecodeError, OSError, UnicodeDecodeError, ValueError, struct.error):
                break

        self._remove_client(client_sock)

    def stop(self):
        self.running = False
        if self.server_socket is not None:
            try:
                self.server_socket.close()
            except OSError:
                pass
            self.server_socket = None
        for client in list(self.clients.keys()):
            self._remove_client(client)


class Client:
    def __init__(
        self,
        callback_msg,
        callback_file_progress,
        callback_file_done,
        callback_error,
        callback_user_list=None,
        callback_call_signal=None,
    ):
        self.sock = None
        self.running = False
        self.username = ''
        self.callback_msg = callback_msg
        self.callback_file_progress = callback_file_progress
        self.callback_file_done = callback_file_done
        self.callback_error = callback_error
        self.callback_user_list = callback_user_list
        self.callback_call_signal = callback_call_signal
        self.send_lock = threading.Lock()
        self.download_dir = os.path.join(os.path.expanduser('~'), 'Downloads', 'LANChat')
        os.makedirs(self.download_dir, exist_ok=True)

    def _sanitize_username(self, username):
        if not isinstance(username, str):
            return None
        username = username.strip()
        if not username:
            return None
        return username[:32]

    def connect(self, host, port, username):
        self.disconnect()
        self.username = self._sanitize_username(username)
        if self.username is None:
            raise ValueError('Username cannot be empty.')

        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5)
            self.sock.connect((host, int(port)))
            self.sock.settimeout(None)
            self.running = True
            threading.Thread(target=self.receive_loop, daemon=True).start()
            send_json(self.sock, {'type': 'JOIN', 'username': self.username})
            return True
        except (OSError, TypeError, ValueError) as exc:
            self.disconnect()
            if callable(self.callback_error):
                self.callback_error(f'Connection failed: {exc}')
            return False

    def send_message(self, text, recipient='All'):
        if not self.running or self.sock is None:
            return

        text = str(text).strip() if text is not None else ''
        if not text:
            return
        if not isinstance(recipient, str):
            recipient = 'All'

        try:
            with self.send_lock:
                send_json(self.sock, {'type': 'MSG', 'username': self.username, 'text': text, 'recipient': recipient})
        except Exception as exc:
            if callable(self.callback_error):
                self.callback_error(f'Send failed: {exc}')

    def send_call_signal(self, recipient, call_id, action, sdp=None, video=None):
        if not self.running or self.sock is None:
            return
        message = {
            'type': 'CALL_SIGNAL',
            'username': self.username,
            'recipient': recipient,
            'call_id': call_id,
            'action': action,
        }
        if sdp is not None:
            message['sdp'] = sdp
        if video is not None:
            message['video'] = bool(video)
        try:
            with self.send_lock:
                send_json(self.sock, message)
        except (OSError, ValueError) as exc:
            if callable(self.callback_error):
                self.callback_error(f'Call signaling failed: {exc}')

    def send_file(self, filepath, recipient='All'):
        if not self.running or self.sock is None:
            return

        if not os.path.isfile(filepath):
            if callable(self.callback_error):
                self.callback_error(f'File send failed: file not found: {filepath}')
            return

        def _send():
            try:
                filename = os.path.basename(filepath)
                filesize = os.path.getsize(filepath)
                with self.send_lock:
                    send_json(self.sock, {'type': 'FILE_START', 'username': self.username, 'filename': filename, 'filesize': filesize, 'recipient': recipient})
                    with open(filepath, 'rb') as f:
                        while True:
                            chunk = f.read(4096)
                            if not chunk:
                                break
                            self.sock.sendall(chunk)
            except Exception as exc:
                if callable(self.callback_error):
                    self.callback_error(f'File send failed: {exc}')

        threading.Thread(target=_send, daemon=True).start()

    def receive_loop(self):
        while self.running:
            try:
                msg = recv_json(self.sock)
                if not msg:
                    break

                if not isinstance(msg, dict):
                    continue

                msg_type = msg.get('type')
                sender = msg.get('username', 'Unknown')

                if msg_type == 'MSG':
                    recipient = msg.get('recipient', 'All')
                    text = msg.get('text', '')
                    if not isinstance(text, str):
                        text = str(text)
                    if callable(self.callback_msg):
                        self.callback_msg(sender, text, recipient)
                elif msg_type == 'JOIN':
                    if callable(self.callback_msg):
                        self.callback_msg('SYSTEM', f'{sender} joined the chat.')
                elif msg_type == 'USER_LIST':
                    users = msg.get('users', [])
                    if callable(self.callback_user_list):
                        self.callback_user_list(users)
                elif msg_type == 'CALL_SIGNAL':
                    if callable(self.callback_call_signal):
                        self.callback_call_signal(msg)
                elif msg_type == 'FILE_START':
                    filename = msg.get('filename', 'received_file.bin')
                    filesize = msg.get('filesize')
                    if not isinstance(filename, str) or not filename.strip():
                        filename = 'received_file.bin'
                    if not isinstance(filesize, int) or filesize < 0:
                        if callable(self.callback_error):
                            self.callback_error('Received an invalid file transfer request.')
                        break

                    safe_name = os.path.basename(filename)
                    save_path = os.path.join(self.download_dir, f'{int(time.time())}_{safe_name}')
                    received = 0

                    try:
                        with open(save_path, 'wb') as f:
                            while received < filesize:
                                chunk_size = min(4096, filesize - received)
                                chunk = recvall(self.sock, chunk_size)
                                if not chunk:
                                    break
                                f.write(chunk)
                                received += len(chunk)
                                if callable(self.callback_file_progress):
                                    self.callback_file_progress(sender, safe_name, received, filesize)
                    except OSError as exc:
                        if callable(self.callback_error):
                            self.callback_error(f'Failed to save file: {exc}')
                        break

                    if received < filesize:
                        if callable(self.callback_error):
                            self.callback_error(f'File transfer from {sender} was incomplete.')
                        break

                    if callable(self.callback_msg):
                        self.callback_msg('SYSTEM', f"Received file '{safe_name}' from {sender}. Saved to {self.download_dir}")
                    if callable(self.callback_file_done):
                        self.callback_file_done(save_path)
            except (json.JSONDecodeError, OSError, ValueError, TypeError):
                if self.running and callable(self.callback_error):
                    self.callback_error('Disconnected from server.')
                break

        self.running = False
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    def disconnect(self):
        self.running = False
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None
