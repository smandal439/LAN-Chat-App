# LAN Chat App

A GUI-based chatting application for PCs that operates over a Local Area Network (LAN). Built with Python, this application allows users to send messages and transfer files easily across a local network.

## Features

*   **Local Area Network (LAN) Chat:** Communicate directly with other users on the same network.
*   **File Transfer:** Share files securely through the chat interface.
*   **Graphical User Interface (GUI):** Simple and intuitive point-and-click interface.
*   **Standalone Executable:** Can be built as a standalone application, requiring no Python installation on target machines.

## Prerequisites

If you are running the application from the source code:
*   Python 3.x
*   Required Python packages (listed in `requirements.txt`)

## Installation & Setup

1.  Clone the repository to your local machine:
    ```bash
    git clone https://github.com/smandal439/LAN-Chat-App.git
    cd LAN-Chat-App
    ```

2.  Install the necessary dependencies:
    ```bash
    pip install -r requirements.txt
    ```

## Usage

To start the chat application, run the main script:
```bash
python main.py
```

## Building a Standalone Executable

To build a standalone `.exe` file that can be distributed and run on Windows PCs without Python installed, you can use the provided build script. Make sure you have the required build tools installed (installed via `requirements.txt`):

```bash
build.bat
```
