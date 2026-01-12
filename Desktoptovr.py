#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys, os, json, subprocess, time, base64, webbrowser
import requests
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit, QPushButton, QVBoxLayout,
    QHBoxLayout, QCheckBox, QDialog, QTextEdit, QMessageBox, QFileDialog
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QPalette, QColor, QFont

COOKIE_FILE = "vrchat_session.json"
CONFIG_FILE = "config.json"
USER_AGENT = "ZamVRChatTool/1.0"
INSTANCE_COOLDOWN = 10  # seconds

# -----------------------
# Utility Functions
# -----------------------
def save_cookie(auth, uid=None):
    with open(COOKIE_FILE, "w") as f:
        json.dump({"auth": auth, "user_id": uid}, f)

def load_cookie():
    if os.path.exists(COOKIE_FILE):
        with open(COOKIE_FILE, "r") as f:
            d = json.load(f)
            return d.get("auth"), d.get("user_id")
    return None, None

def test_cookie(cookie):
    try:
        s = requests.Session()
        s.cookies.set("auth", cookie)
        s.headers["User-Agent"] = USER_AGENT
        r = s.get("https://api.vrchat.cloud/api/1/auth/user")
        if r.status_code == 200:
            return True, r.json()
        return False, None
    except:
        return False, None

def find_vrchat_launch_path():
    p = r"E:\SteamLibrary\steamapps\common\VRChat\launch.exe"
    return p if os.path.exists(p) else ""

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}

def save_config(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=4)

# -----------------------
# Login Dialog
# -----------------------
class LoginDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Login to VRChat")
        self.setFixedSize(400, 250)

        layout = QVBoxLayout(self)
        self.user = QLineEdit(placeholderText="Username or Email")
        self.pw = QLineEdit(placeholderText="Password", echoMode=QLineEdit.Password)
        self.status = QLabel("")
        login_btn = QPushButton("Login")

        layout.addWidget(self.user)
        layout.addWidget(self.pw)
        layout.addWidget(self.status)
        layout.addWidget(login_btn)

        login_btn.clicked.connect(self.login)
        self.auth_cookie = None
        self.user_data = None

    def login(self):
        try:
            self.status.setText("Logging in...")
            s = requests.Session()
            auth = base64.b64encode(f"{self.user.text()}:{self.pw.text()}".encode()).decode()
            s.headers.update({"Authorization": f"Basic {auth}", "User-Agent": USER_AGENT})
            r = s.get("https://api.vrchat.cloud/api/1/auth/user")
            if r.status_code != 200:
                self.status.setText("Login failed")
                return
            self.auth_cookie = s.cookies.get("auth")
            self.user_data = r.json()
            save_cookie(self.auth_cookie, self.user_data.get("id"))
            self.accept()
        except Exception as e:
            self.status.setText(str(e))

# -----------------------
# Threads
# -----------------------
class LauncherThread(QThread):
    log_msg = Signal(str)

    def __init__(self, cmd, parent=None):
        super().__init__(parent)
        self.cmd = cmd

    def run(self):
        try:
            self.log_msg.emit(f"[LauncherThread] Running: {self.cmd}")
            subprocess.Popen(self.cmd)
            self.log_msg.emit("[LauncherThread] VRChat launched successfully")
        except Exception as e:
            self.log_msg.emit(f"[LauncherThread] ERROR: {e}")

class FetchInstanceThread(QThread):
    fetched = Signal(str, str)  # location, world_name
    log_msg = Signal(str)

    def __init__(self, auth_cookie: str, user_id: str):
        super().__init__()
        self.auth_cookie = auth_cookie
        self.user_id = user_id

    def run(self):
        try:
            self.log_msg.emit("[FetchInstanceThread] Fetching user info...")
            s = requests.Session()
            s.cookies.set("auth", self.auth_cookie)
            s.headers["User-Agent"] = USER_AGENT

            r = s.get(f"https://api.vrchat.cloud/api/1/users/{self.user_id}")
            self.log_msg.emit(f"[FetchInstanceThread] Raw User Response: {r.text}")

            if r.status_code == 200:
                data = r.json()
                loc = data.get("location")
                world_id = data.get("worldId") or data.get("presence", {}).get("world")
                if world_id:
                    world_id = world_id.split(":")[0]

                self.log_msg.emit(f"[FetchInstanceThread] Location: {loc}")
                self.log_msg.emit(f"[FetchInstanceThread] World ID: {world_id}")

                world_name = None
                if world_id:
                    self.log_msg.emit(f"[FetchInstanceThread] Fetching world info for {world_id}...")
                    wr = s.get(f"https://api.vrchat.cloud/api/1/worlds/{world_id}")
                    if wr.status_code == 200:
                        wdata = wr.json()
                        world_name = wdata.get("name")
                        self.log_msg.emit(f"[FetchInstanceThread] World Name: {world_name}")
                    else:
                        self.log_msg.emit(f"[FetchInstanceThread] Failed to fetch world info: HTTP {wr.status_code}")

                self.fetched.emit(loc, world_name)
            else:
                self.log_msg.emit(f"[FetchInstanceThread] HTTP {r.status_code}")
                self.fetched.emit(None, None)

        except Exception as e:
            self.log_msg.emit(f"[FetchInstanceThread] ERROR: {e}")
            self.fetched.emit(None, None)

# -----------------------
# Main Window
# -----------------------
class MainWindow(QWidget):
    def __init__(self, cookie, user_data):
        super().__init__()
        self.setWindowTitle("VR/Desktop Switcher By Zam")
        self.resize(600, 500)

        self.cookie = cookie
        self.user_data = user_data
        self.uid = user_data.get("id")
        self.instance = None
        self.config = load_config()

        main = QVBoxLayout(self)

        # --- Top row with user label and buttons ---
        top_row = QHBoxLayout()
        display = user_data.get("displayName", "Unknown")
        self.user_label = QLabel(f"Logged in as {display}")
        self.user_label.setFont(QFont("Helvetica Neue", 16, QFont.Bold))
        self.user_label.setAlignment(Qt.AlignCenter)
        top_row.addWidget(self.user_label, stretch=1)

        kofi_btn = QPushButton("❤️ Ko-fi")
        kofi_btn.clicked.connect(lambda: webbrowser.open("https://ko-fi.com/cutezam"))
        github_btn = QPushButton("Source")
        github_btn.clicked.connect(lambda: webbrowser.open("https://github.com/Zam6969/VR-Desktop-Swapper/"))

        top_row.addWidget(kofi_btn)
        top_row.addWidget(github_btn)
        main.addLayout(top_row)

        # --- Launch path row ---
        row = QHBoxLayout()
        saved_path = self.config.get("launch_path") or find_vrchat_launch_path()
        self.path = QLineEdit(saved_path)
        browse = QPushButton("Browse")
        row.addWidget(QLabel("Launch Path:"))
        row.addWidget(self.path)
        row.addWidget(browse)
        main.addLayout(row)
        browse.clicked.connect(self.browse_path)

        # --- Status and location ---
        self.status = QLabel("Starting...")
        self.location = QLabel("Current Location: ...")
        self.world_name_label = QLabel("World Name: ...")
        main.addWidget(self.status)
        main.addWidget(self.location)
        main.addWidget(self.world_name_label)

        # --- Instance fetch button ---
        self.fetch_btn = QPushButton("Get Current Instance")
        main.addWidget(self.fetch_btn)
        self.fetch_btn.clicked.connect(self.update_instance)

        # Timer for cooldown
        self.cooldown_timer = QTimer()
        self.cooldown_timer.timeout.connect(self.update_cooldown)
        self.cooldown_remaining = 0

        self.desktop = QCheckBox("Launch in Desktop (No VR)")
        main.addWidget(self.desktop)

        btns = QHBoxLayout()
        steamvr = QPushButton("Launch SteamVR")
        vrchat = QPushButton("Launch VRChat")
        btns.addWidget(steamvr)
        btns.addWidget(vrchat)
        main.addLayout(btns)

        steamvr.clicked.connect(self.launch_steamvr)
        vrchat.clicked.connect(self.launch_vrchat)

        self.console = QTextEdit()
        self.console.setVisible(True)
        main.addWidget(self.console)

        toggle = QPushButton("Show Console")
        toggle.clicked.connect(lambda: self.console.setVisible(not self.console.isVisible()))
        main.addWidget(toggle)

        self.log("Application started")
        self.update_instance()

    # -----------------------
    def browse_path(self):
        p, _ = QFileDialog.getOpenFileName(self, "Select launch.exe", "", "Executable (*.exe)")
        if p:
            self.path.setText(p)
            self.config["launch_path"] = p
            save_config(self.config)
            self.log(f"Launch path set to: {p}")

    def update_instance(self):
        if self.cooldown_remaining > 0:
            return  # ignore clicks during cooldown
        self.status.setText("Fetching instance...")
        self.fetch_thread = FetchInstanceThread(self.cookie, self.uid)
        self.fetch_thread.log_msg.connect(self.log)
        self.fetch_thread.fetched.connect(self.on_instance)
        self.fetch_thread.start()
        self.start_cooldown()

    def start_cooldown(self):
        self.cooldown_remaining = INSTANCE_COOLDOWN
        self.fetch_btn.setEnabled(False)
        self.cooldown_timer.start(1000)
        self.fetch_btn.setText(f"Wait {self.cooldown_remaining}s")

    def update_cooldown(self):
        self.cooldown_remaining -= 1
        if self.cooldown_remaining > 0:
            self.fetch_btn.setText(f"Wait {self.cooldown_remaining}s")
        else:
            self.cooldown_timer.stop()
            self.fetch_btn.setText("Get Current Instance")
            self.fetch_btn.setEnabled(True)

    def on_instance(self, loc, world_name):
        self.instance = loc
        if loc:
            self.location.setText(f"Current Location: {loc}")
            self.world_name_label.setText(f"World Name: {world_name or 'Unknown'}")
            self.status.setText("Ready")
        else:
            self.location.setText("Current Location: None")
            self.world_name_label.setText("World Name: None")
            self.status.setText("Not Ready")

    def launch_steamvr(self):
        self.log("Launching SteamVR...")
        os.startfile("steam://rungameid/250820")

    def launch_vrchat(self):
        if not self.instance:
            self.log("Launch blocked: no valid instance")
            QMessageBox.warning(self, "Not Ready", "No valid instance to launch.")
            return
        cmd = [self.path.text()]
        if self.desktop.isChecked():
            cmd.append("--no-vr")
        cmd.append(f"vrchat://launch?id={self.instance}")

        self.log(f"Launching VRChat with: {cmd}")
        self.launch_thread = LauncherThread(cmd, self)
        self.launch_thread.log_msg.connect(self.log)
        self.launch_thread.start()

    def log(self, msg):
        ts = time.strftime("%H:%M:%S")
        self.console.append(f"[{ts}] {msg}")
        self.console.ensureCursorVisible()
        print(msg)

    def closeEvent(self, event):
        try:
            if hasattr(self, 'fetch_thread') and self.fetch_thread.isRunning():
                self.fetch_thread.terminate()
                self.fetch_thread.wait()
            if hasattr(self, 'launch_thread') and self.launch_thread.isRunning():
                self.launch_thread.terminate()
                self.launch_thread.wait()
            event.accept()
        except Exception:
            event.accept()

# -----------------------
# Entry
# -----------------------
def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(28, 28, 30))
    palette.setColor(QPalette.WindowText, Qt.white)
    app.setPalette(palette)

    cookie, _ = load_cookie()
    valid, user_data = test_cookie(cookie) if cookie else (False, None)

    if not valid:
        dlg = LoginDialog()
        if dlg.exec() != QDialog.Accepted:
            sys.exit()
        cookie = dlg.auth_cookie
        user_data = dlg.user_data

    win = MainWindow(cookie, user_data)
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
