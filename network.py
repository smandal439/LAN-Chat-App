import socket
import threading
import os
import time
import struct
import json
from protocol import send_json, recv_json, recvall

class Server:
    def __init__(self, port):
        self.port = port
        self.host = '0.0.0.0'
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.clients = {}  # Map socket to username
        self.running = False

    def start(self):
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(5)
        self.running = True
        threading.Thread(target=self.accept_clients, daemon=True).start()

    def accept_clients(self):
        while self.running:
            try:
                client_sock, addr = self.server_socket.accept()
                self.clients[client_sock] = None
                threading.Thread(target=self.handle_client, args=(client_sock,), daemon=True).start()
            except Exception:
                break

    def _send_to_sockets(self, sockets, data):
        for client in sockets:
            try:
                client.sendall(data)
            except Exception:
                pass

    def broadcast_user_list(self):
        users = [u for u in self.clients.values() if u is not None]
        msg = {'type': 'USER_LIST', 'users': users}
        payload = json.dumps(msg).encode('utf-8')
        header = struct.pack('!I', len(payload))
        self._send_to_sockets(self.clients.keys(), header + payload)

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
                msg_type = msg.get('type')
                
                if msg_type == 'JOIN':
                    self.clients[client_sock] = msg.get('username')
                    # Broadcast JOIN to others
                    self._send_to_sockets(
                        [s for s in self.clients if s != client_sock], 
                        header_data + payload
                    )
                    self.broadcast_user_list()
                    continue
                
                recipient = msg.get('recipient', 'All')
                target_sockets = []
                if recipient == 'All':
                    target_sockets = [s for s in self.clients if s != client_sock]
                else:
                    target_sockets = [s for s, u in self.clients.items() if u == recipient and s != client_sock]
                
                # Forward the message header and payload
                self._send_to_sockets(target_sockets, header_data + payload)
                
                if msg_type == 'FILE_START':
                    filesize = msg.get('filesize', 0)
                    received = 0
                    while received < filesize:
                        chunk_size = min(4096, filesize - received)
                        chunk = client_sock.recv(chunk_size)
                        if not chunk:
                            break
                        self._send_to_sockets(target_sockets, chunk)
                        received += len(chunk)
            except Exception:
                break
        
        if client_sock in self.clients:
            del self.clients[client_sock]
            self.broadcast_user_list()
        try:
            client_sock.close()
        except:
            pass

    def stop(self):
        self.running = False
        try:
            self.server_socket.close()
        except:
            pass
        for client in self.clients.keys():
            try:
                client.close()
            except:
                pass

class Client:
    def __init__(self, callback_msg, callback_file_progress, callback_file_done, callback_error, callback_user_list=None):
        self.sock = None
        self.running = False
        self.username = ""
        self.callback_msg = callback_msg
        self.callback_file_progress = callback_file_progress
        self.callback_file_done = callback_file_done
        self.callback_error = callback_error
        self.callback_user_list = callback_user_list
        self.download_dir = os.path.join(os.path.expanduser("~"), "Downloads", "LANChat")
        os.makedirs(self.download_dir, exist_ok=True)

    def connect(self, host, port, username):
        self.username = username
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.sock.connect((host, port))
            self.running = True
            threading.Thread(target=self.receive_loop, daemon=True).start()
            send_json(self.sock, {'type': 'JOIN', 'username': self.username})
            return True
        except Exception as e:
            self.callback_error(f"Connection failed: {e}")
            return False

    def send_message(self, text, recipient='All'):
        if self.running and self.sock:
            try:
                send_json(self.sock, {'type': 'MSG', 'username': self.username, 'text': text, 'recipient': recipient})
            except Exception as e:
                self.callback_error(f"Send failed: {e}")

    def send_file(self, filepath, recipient='All'):
        if self.running and self.sock:
            def _send():
                try:
                    filename = os.path.basename(filepath)
                    filesize = os.path.getsize(filepath)
                    send_json(self.sock, {'type': 'FILE_START', 'username': self.username, 'filename': filename, 'filesize': filesize, 'recipient': recipient})
                    
                    with open(filepath, 'rb') as f:
                        while True:
                            chunk = f.read(4096)
                            if not chunk:
                                break
                            self.sock.sendall(chunk)
                except Exception as e:
                    self.callback_error(f"File send failed: {e}")
            threading.Thread(target=_send, daemon=True).start()

    def receive_loop(self):
        while self.running:
            try:
                msg = recv_json(self.sock)
                if not msg:
                    break
                
                msg_type = msg.get('type')
                sender = msg.get('username', 'Unknown')
                
                if msg_type == 'MSG':
                    self.callback_msg(sender, msg.get('text', ''), msg.get('recipient', 'All'))
                elif msg_type == 'JOIN':
                    self.callback_msg("SYSTEM", f"{sender} joined the chat.")
                elif msg_type == 'USER_LIST':
                    if self.callback_user_list:
                        self.callback_user_list(msg.get('users', []))
                elif msg_type == 'FILE_START':
                    filename = msg.get('filename')
                    filesize = msg.get('filesize')
                    
                    received = 0
                    save_path = os.path.join(self.download_dir, f"{int(time.time())}_{filename}")
                    
                    with open(save_path, 'wb') as f:
                        while received < filesize:
                            chunk_size = min(4096, filesize - received)
                            # Using recvall instead of raw recv to handle slow networking
                            chunk = recvall(self.sock, chunk_size)
                            if not chunk:
                                break
                            f.write(chunk)
                            received += len(chunk)
                            self.callback_file_progress(sender, filename, received, filesize)
                    
                    self.callback_msg("SYSTEM", f"Received file '{filename}' from {sender}. Saved to {self.download_dir}")
                    self.callback_file_done(save_path)
            except Exception as e:
                if self.running:
                    self.callback_error(f"Disconnected: {e}")
                break

        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except:
                pass

    def disconnect(self):
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
