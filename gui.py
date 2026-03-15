import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox
import threading
import os
from network import Server, Client

class ChatApplication:
    def __init__(self, root):
        self.root = root
        self.root.title("LAN Chat App")
        self.root.geometry("600x500")
        
        self.server = None
        self.client = None
        
        self.setup_login_ui()
        
    def setup_login_ui(self):
        # Clear existing widgets
        for widget in self.root.winfo_children():
            widget.destroy()
            
        self.login_frame = ttk.Frame(self.root, padding="20")
        self.login_frame.pack(expand=True, fill=tk.BOTH)
        
        ttk.Label(self.login_frame, text="LAN Chat Application", font=("Helvetica", 16, "bold")).pack(pady=20)
        
        # User details
        details_frame = ttk.LabelFrame(self.login_frame, text="Connection Details", padding="10")
        details_frame.pack(fill=tk.X, pady=10)
        
        ttk.Label(details_frame, text="Username:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.username_var = tk.StringVar(value="User")
        ttk.Entry(details_frame, textvariable=self.username_var).grid(row=0, column=1, sticky=tk.EW, padx=5, pady=5)
        
        ttk.Label(details_frame, text="Port:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.port_var = tk.StringVar(value="5555")
        ttk.Entry(details_frame, textvariable=self.port_var).grid(row=1, column=1, sticky=tk.EW, padx=5, pady=5)
        
        details_frame.columnconfigure(1, weight=1)
        
        # Action Buttons
        action_frame = ttk.Frame(self.login_frame)
        action_frame.pack(fill=tk.X, pady=20)
        
        ttk.Button(action_frame, text="Host a Server", command=self.host_server).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)
        
        join_frame = ttk.LabelFrame(self.login_frame, text="Join Server", padding="10")
        join_frame.pack(fill=tk.X, pady=10)
        
        ttk.Label(join_frame, text="Server IP:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.ip_var = tk.StringVar(value="127.0.0.1")
        ttk.Entry(join_frame, textvariable=self.ip_var).grid(row=0, column=1, sticky=tk.EW, padx=5, pady=5)
        
        ttk.Button(join_frame, text="Join Server", command=self.join_server).grid(row=1, column=0, columnspan=2, pady=10)
        join_frame.columnconfigure(1, weight=1)

    def host_server(self):
        port = int(self.port_var.get())
        username = self.username_var.get().strip()
        
        if not username:
            messagebox.showerror("Error", "Username cannot be empty")
            return
            
        try:
            # Start background server
            self.server = Server(port)
            self.server.start()
            
            # Connect a client to our own server
            self.connect_client('127.0.0.1', port, username)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to start server: {e}")

    def join_server(self):
        port = int(self.port_var.get())
        ip = self.ip_var.get().strip()
        username = self.username_var.get().strip()
        
        if not username or not ip:
            messagebox.showerror("Error", "Username and IP cannot be empty")
            return
            
        self.connect_client(ip, port, username)

    def connect_client(self, ip, port, username):
        self.client = Client(
            callback_msg=self.on_message_received,
            callback_file_progress=self.on_file_progress,
            callback_file_done=self.on_file_done,
            callback_error=self.on_error
        )
        if self.client.connect(ip, port, username):
            self.setup_chat_ui()
            
    def setup_chat_ui(self):
        for widget in self.root.winfo_children():
            widget.destroy()
            
        self.chat_frame = ttk.Frame(self.root, padding="10")
        self.chat_frame.pack(expand=True, fill=tk.BOTH)
        
        # Header
        header_text = f"Logged in as {self.client.username}"
        if self.server:
            import socket
            hostname = socket.gethostname()
            local_ip = socket.gethostbyname(hostname)
            header_text += f" | Hosting on {local_ip}:{self.server.port}"
        
        ttk.Label(self.chat_frame, text=header_text, font=("Helvetica", 10, "italic")).pack(anchor=tk.W, pady=(0, 10))
        
        # Chat area
        self.chat_area = scrolledtext.ScrolledText(self.chat_frame, wrap=tk.WORD, state=tk.DISABLED, font=("Helvetica", 10))
        self.chat_area.pack(expand=True, fill=tk.BOTH, pady=(0, 10))
        
        # Configure tags for chat formatting
        self.chat_area.tag_configure("SYSTEM", foreground="red")
        self.chat_area.tag_configure("ME", foreground="blue")
        self.chat_area.tag_configure("OTHER", foreground="black")
        
        # Input area
        input_frame = ttk.Frame(self.chat_frame)
        input_frame.pack(fill=tk.X)
        
        self.msg_entry = ttk.Entry(input_frame, font=("Helvetica", 10))
        self.msg_entry.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 10))
        self.msg_entry.bind("<Return>", lambda event: self.send_message())
        
        ttk.Button(input_frame, text="Send", command=self.send_message).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(input_frame, text="Send File", command=self.send_file).pack(side=tk.LEFT)
        
        # Footer
        footer_text = f"Files download to: {self.client.download_dir}"
        ttk.Label(self.chat_frame, text=footer_text, font=("Helvetica", 8)).pack(anchor=tk.W, pady=(5, 0))
        
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def write_chat(self, sender, text, tag="OTHER"):
        self.chat_area.config(state=tk.NORMAL)
        if sender == "SYSTEM":
            self.chat_area.insert(tk.END, f"[{sender}] {text}\n", "SYSTEM")
        elif sender == self.client.username:
            self.chat_area.insert(tk.END, f"[{sender}] {text}\n", "ME")
        else:
            self.chat_area.insert(tk.END, f"[{sender}] {text}\n", tag)
        self.chat_area.see(tk.END)
        self.chat_area.config(state=tk.DISABLED)

    def send_message(self):
        text = self.msg_entry.get().strip()
        if text:
            self.client.send_message(text)
            self.write_chat(self.client.username, text)
            self.msg_entry.delete(0, tk.END)

    def send_file(self):
        filepath = filedialog.askopenfilename(title="Select a file to send")
        if filepath:
            self.client.send_file(filepath)
            self.write_chat("SYSTEM", f"Started sending file: {os.path.basename(filepath)}")

    # Callbacks from Client thread must be routed to main thread safely via root.after
    def on_message_received(self, sender, text):
        self.root.after(0, self.write_chat, sender, text)

    def on_file_progress(self, sender, filename, received, total):
        pass # Optional: Could implement a progress bar here

    def on_file_done(self, filepath):
        pass # Message is handled by on_message_received

    def on_error(self, message):
        self.root.after(0, messagebox.showerror, "Network Error", message)
        self.root.after(0, self.setup_login_ui)

    def on_closing(self):
        if self.client:
            self.client.disconnect()
        if self.server:
            self.server.stop()
        self.root.destroy()
