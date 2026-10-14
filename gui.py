import os
import socket
import base64
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from media import CallManager
from network import Client, Server


class ChatApplication:
    def __init__(self, root):
        self.root = root
        self.root.title('LAN Chat App')
        self.root.geometry('800x500')
        self.root.minsize(600, 400)

        self.server = None
        self.client = None
        self.call_manager = None
        self.video_window = None
        self.video_image = None
        self.setup_login_ui()

    def _get_port_value(self):
        raw_value = self.port_var.get().strip()
        if not raw_value:
            raise ValueError('Port cannot be empty.')
        port = int(raw_value)
        if not 0 <= port <= 65535:
            raise ValueError('Port must be between 0 and 65535.')
        return port

    def setup_login_ui(self):
        for widget in self.root.winfo_children():
            widget.destroy()

        self.login_frame = ttk.Frame(self.root, padding='20')
        self.login_frame.pack(expand=True, fill=tk.BOTH)

        ttk.Label(self.login_frame, text='LAN Chat Application', font=('Helvetica', 16, 'bold')).pack(pady=20)

        details_frame = ttk.LabelFrame(self.login_frame, text='Connection Details', padding='10')
        details_frame.pack(fill=tk.X, pady=10)

        ttk.Label(details_frame, text='Username:').grid(row=0, column=0, sticky=tk.W, pady=5)
        self.username_var = tk.StringVar(value='User')
        ttk.Entry(details_frame, textvariable=self.username_var).grid(row=0, column=1, sticky=tk.EW, padx=5, pady=5)

        ttk.Label(details_frame, text='Port:').grid(row=1, column=0, sticky=tk.W, pady=5)
        self.port_var = tk.StringVar(value='5555')
        ttk.Entry(details_frame, textvariable=self.port_var).grid(row=1, column=1, sticky=tk.EW, padx=5, pady=5)

        details_frame.columnconfigure(1, weight=1)

        action_frame = ttk.Frame(self.login_frame)
        action_frame.pack(fill=tk.X, pady=20)
        ttk.Button(action_frame, text='Host a Server', command=self.host_server).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)

        join_frame = ttk.LabelFrame(self.login_frame, text='Join Server', padding='10')
        join_frame.pack(fill=tk.X, pady=10)

        ttk.Label(join_frame, text='Server IP:').grid(row=0, column=0, sticky=tk.W, pady=5)
        self.ip_var = tk.StringVar(value='127.0.0.1')
        ttk.Entry(join_frame, textvariable=self.ip_var).grid(row=0, column=1, sticky=tk.EW, padx=5, pady=5)

        ttk.Button(join_frame, text='Join Server', command=self.join_server).grid(row=1, column=0, columnspan=2, pady=10)
        join_frame.columnconfigure(1, weight=1)

    def host_server(self):
        username = self.username_var.get().strip()
        if not username:
            messagebox.showerror('Error', 'Username cannot be empty')
            return

        try:
            port = self._get_port_value()
            self.server = Server(port)
            self.server.start()
            self.connect_client('127.0.0.1', port, username)
        except ValueError as exc:
            messagebox.showerror('Error', str(exc))
        except OSError as exc:
            messagebox.showerror('Error', f'Failed to start server: {exc}')

    def join_server(self):
        ip = self.ip_var.get().strip()
        username = self.username_var.get().strip()
        if not username or not ip:
            messagebox.showerror('Error', 'Username and IP cannot be empty')
            return

        try:
            port = self._get_port_value()
            self.connect_client(ip, port, username)
        except ValueError as exc:
            messagebox.showerror('Error', str(exc))

    def connect_client(self, ip, port, username):
        self.client = Client(
            callback_msg=self.on_message_received,
            callback_file_progress=self.on_file_progress,
            callback_file_done=self.on_file_done,
            callback_error=self.on_error,
            callback_user_list=self.on_user_list_received,
            callback_call_signal=self.on_call_signal,
        )
        if self.client.connect(ip, port, username):
            self.setup_chat_ui()

    def setup_chat_ui(self):
        for widget in self.root.winfo_children():
            widget.destroy()

        self.main_paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.main_paned.pack(expand=True, fill=tk.BOTH, padx=10, pady=10)

        self.chat_frame = ttk.Frame(self.main_paned)
        self.main_paned.add(self.chat_frame, weight=3)

        self.users_frame = ttk.Frame(self.main_paned)
        self.main_paned.add(self.users_frame, weight=1)

        header_text = f'Logged in as {self.client.username}'
        if self.server:
            local_ip = socket.gethostbyname(socket.gethostname())
            header_text += f' | Hosting on {local_ip}:{self.server.port}'

        header_frame = ttk.Frame(self.chat_frame)
        header_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(header_frame, text=header_text, font=('Helvetica', 10, 'italic')).pack(side=tk.LEFT)
        ttk.Button(header_frame, text='Clear Chat', command=self.clear_chat).pack(side=tk.RIGHT)

        self.chat_area = scrolledtext.ScrolledText(self.chat_frame, wrap=tk.WORD, state=tk.DISABLED, font=('Helvetica', 10))
        self.chat_area.pack(expand=True, fill=tk.BOTH, pady=(0, 10))

        self.chat_area.tag_configure('SYSTEM', foreground='red')
        self.chat_area.tag_configure('ME', foreground='blue')
        self.chat_area.tag_configure('OTHER', foreground='black')
        self.chat_area.tag_configure('DM', foreground='purple')

        input_frame = ttk.Frame(self.chat_frame)
        input_frame.pack(fill=tk.X)

        self.msg_entry = ttk.Entry(input_frame, font=('Helvetica', 10))
        self.msg_entry.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 10))
        self.msg_entry.bind('<Return>', lambda event: self.send_message())

        ttk.Button(input_frame, text='Send', command=self.send_message).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(input_frame, text='Send File', command=self.send_file).pack(side=tk.LEFT)

        call_frame = ttk.Frame(self.chat_frame)
        call_frame.pack(fill=tk.X, pady=(5, 0))
        ttk.Button(call_frame, text='Voice Call', command=lambda: self.start_call(False)).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(call_frame, text='Video Call', command=lambda: self.start_call(True)).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(call_frame, text='End Call', command=self.end_call).pack(side=tk.LEFT)
        self.call_status_var = tk.StringVar(value='Not in a call')
        ttk.Label(call_frame, textvariable=self.call_status_var).pack(side=tk.LEFT, padx=10)

        footer_text = f'Files download to: {self.client.download_dir}'
        ttk.Label(self.chat_frame, text=footer_text, font=('Helvetica', 8)).pack(anchor=tk.W, pady=(5, 0))

        ttk.Label(self.users_frame, text='Online Users', font=('Helvetica', 12, 'bold')).pack(anchor=tk.W, pady=(0, 5))

        self.users_listbox = tk.Listbox(self.users_frame, font=('Helvetica', 10), selectmode=tk.SINGLE)
        self.users_listbox.pack(expand=True, fill=tk.BOTH)

        send_to_frame = ttk.Frame(self.users_frame)
        send_to_frame.pack(fill=tk.X, pady=(10, 0))

        ttk.Label(send_to_frame, text='Send To:').pack(side=tk.LEFT)
        self.recipient_var = tk.StringVar(value='All')
        self.recipient_combo = ttk.Combobox(send_to_frame, textvariable=self.recipient_var, state='readonly')
        self.recipient_combo['values'] = ('All',)
        self.recipient_combo.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(5, 0))

        self.call_manager = CallManager(
            send_signal=self.client.send_call_signal,
            on_status=self.on_call_status,
            on_video_frame=self.on_video_frame,
        )
        self.root.protocol('WM_DELETE_WINDOW', self.on_closing)

    def start_call(self, video):
        if not self.client or not self.call_manager:
            return
        recipient = self.recipient_var.get()
        if recipient == 'All':
            messagebox.showerror('Call', 'Select an online user from Send To before starting a call.')
            return
        self.call_manager.start_call(recipient, video)

    def end_call(self):
        if self.call_manager:
            self.call_manager.end_call()

    def on_call_signal(self, message):
        self.root.after(0, self.handle_call_signal, message)

    def handle_call_signal(self, message):
        if not self.call_manager:
            return
        if message.get('action') == 'offer':
            if not self.call_manager.handle_signal(message):
                return
            mode = 'video' if message.get('video') is True else 'voice'
            if messagebox.askyesno('Incoming call', f"{message.get('username', 'Someone')} is calling ({mode}). Accept?"):
                self.call_manager.accept(message)
            else:
                self.call_manager.reject()
            return
        self.call_manager.handle_signal(message)

    def on_call_status(self, status, peer):
        self.root.after(0, self.update_call_status, status, peer)

    def update_call_status(self, status, peer):
        if not hasattr(self, 'call_status_var'):
            return
        self.call_status_var.set('Incoming call...' if status.startswith('incoming:') else status)
        if (
            status == 'Call ended.'
            or status == 'No answer. Call ended.'
            or status.startswith('Call setup failed:')
            or status.endswith('the call.')
        ) and self.video_window is not None:
            self.video_window.destroy()
            self.video_window = None
            self.video_image = None

    def on_video_frame(self, frame):
        self.root.after(0, self.render_video_frame, frame)

    def render_video_frame(self, frame):
        if not self.call_manager or self.call_manager.call_id is None:
            return
        if self.video_window is None or not self.video_window.winfo_exists():
            self.video_window = tk.Toplevel(self.root)
            self.video_window.title('Incoming video')
            self.video_window.protocol('WM_DELETE_WINDOW', self.end_call)
            self.video_label = ttk.Label(self.video_window)
            self.video_label.pack()
        height, width, _ = frame.shape
        ppm = f'P6 {width} {height} 255\n'.encode('ascii') + frame.tobytes()
        encoded = base64.b64encode(ppm).decode('ascii')
        self.video_image = tk.PhotoImage(data=encoded, format='PPM')
        self.video_label.configure(image=self.video_image)

    def clear_chat(self):
        if hasattr(self, 'chat_area'):
            self.chat_area.config(state=tk.NORMAL)
            self.chat_area.delete(1.0, tk.END)
            self.chat_area.config(state=tk.DISABLED)

    def write_chat(self, sender, text, recipient='All'):
        if not hasattr(self, 'chat_area'):
            return

        self.chat_area.config(state=tk.NORMAL)
        tag = 'OTHER'
        if sender == 'SYSTEM':
            tag = 'SYSTEM'
        elif sender == self.client.username:
            tag = 'ME'
            if recipient != 'All':
                text = f'(DM to {recipient}) {text}'
                tag = 'DM'
        else:
            if recipient != 'All':
                text = f'(DM from {sender}) {text}'
                tag = 'DM'

        self.chat_area.insert(tk.END, f'[{sender}] {text}\n', tag)
        self.chat_area.see(tk.END)
        self.chat_area.config(state=tk.DISABLED)

    def send_message(self):
        if not hasattr(self, 'msg_entry') or not self.client:
            return

        text = self.msg_entry.get().strip()
        recipient = self.recipient_var.get()
        if text:
            self.client.send_message(text, recipient)
            self.write_chat(self.client.username, text, recipient)
            self.msg_entry.delete(0, tk.END)

    def send_file(self):
        if not self.client:
            return

        filepath = filedialog.askopenfilename(title='Select a file to send')
        recipient = self.recipient_var.get()
        if filepath:
            self.client.send_file(filepath, recipient)
            target = f'to {recipient}' if recipient != 'All' else 'to All'
            self.write_chat('SYSTEM', f'Started sending file: {os.path.basename(filepath)} {target}')

    def on_message_received(self, sender, text, recipient='All'):
        self.root.after(0, self.write_chat, sender, text, recipient)

    def on_user_list_received(self, users):
        self.root.after(0, self.update_user_list, users)

    def update_user_list(self, users):
        if not hasattr(self, 'users_listbox'):
            return

        self.users_listbox.delete(0, tk.END)
        combo_values = ['All']
        for user in users:
            display_name = str(user)
            if user == self.client.username:
                display_name += ' (You)'
            self.users_listbox.insert(tk.END, display_name)
            if user != self.client.username:
                combo_values.append(user)

        self.recipient_combo['values'] = tuple(combo_values)
        if self.recipient_var.get() not in combo_values:
            self.recipient_var.set('All')

    def on_file_progress(self, sender, filename, received, total):
        pass

    def on_file_done(self, filepath):
        pass

    def on_error(self, message):
        self.root.after(0, self.handle_network_error, message)

    def handle_network_error(self, message):
        if self.call_manager:
            self.call_manager.close(notify_peer=False)
            self.call_manager = None
        messagebox.showerror('Network Error', message)
        self.setup_login_ui()

    def on_closing(self):
        if self.call_manager:
            self.call_manager.close()
        if self.client:
            self.client.disconnect()
        if self.server:
            self.server.stop()
        self.root.destroy()


def main():
    root = tk.Tk()
    ChatApplication(root)
    root.mainloop()


if __name__ == '__main__':
    main()
