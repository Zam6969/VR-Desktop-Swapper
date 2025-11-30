#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys, os, json, subprocess, time, base64
import requests
from typing import Optional
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit, QPushButton, QVBoxLayout,
    QHBoxLayout, QCheckBox, QDialog, QTextEdit, QMessageBox, QFileDialog, QInputDialog
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtGui import QPalette, QColor

COOKIE_FILE = "vrchat_session.json"
USER_AGENT = "ZamVRChatTool/1.0 (contact: VrSWAPPERCuteZam)"

# -----------------------
# Utility Functions
# -----------------------
def save_cookie(auth_cookie, user_id=None):
    data = {"auth": auth_cookie}
    if user_id:
        data["user_id"] = user_id
    with open(COOKIE_FILE, "w") as f:
        json.dump(data, f)

def load_cookie():
    if os.path.exists(COOKIE_FILE):
        with open(COOKIE_FILE, "r") as f:
            data = json.load(f)
            return data.get("auth"), data.get("user_id")
    return None, None

def test_cookie(auth_cookie):
    if not auth_cookie:
        return False
    try:
        session = requests.Session()
        session.cookies.set("auth", auth_cookie)
        session.headers.update({"User-Agent": USER_AGENT})
        res = session.get("https://api.vrchat.cloud/api/1/auth/user")
        return res.status_code == 200
    except:
        return False

def find_vrchat_launch_path():
    default_path = r"E:\SteamLibrary\steamapps\common\VRChat\launch.exe"
    if os.path.exists(default_path):
        return default_path
    return ""

# -----------------------
# Login Dialog with 2FA
# -----------------------
class LoginDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VRChat Login")
        self.setFixedSize(400, 250)
        self.setStyleSheet("background-color: #1E1E2F; color: white; font-size: 14px;")
        layout = QVBoxLayout()

        self.user_input = QLineEdit()
        self.user_input.setPlaceholderText("Username or Email")
        self.pass_input = QLineEdit()
        self.pass_input.setPlaceholderText("Password")
        self.pass_input.setEchoMode(QLineEdit.Password)
        self.status_label = QLabel("")
        self.login_btn = QPushButton("Login")

        layout.addWidget(self.user_input)
        layout.addWidget(self.pass_input)
        layout.addWidget(self.status_label)
        layout.addWidget(self.login_btn)
        self.setLayout(layout)
        self.login_btn.clicked.connect(self.on_login)

        self.auth_cookie = None

    def on_login(self):
        username = self.user_input.text().strip()
        password = self.pass_input.text().strip()
        if not username or not password:
            self.status_label.setText("Enter both username and password!")
            return
        try:
            session = requests.Session()
            auth_string = f"{username}:{password}"
            auth_header = base64.b64encode(auth_string.encode()).decode()
            session.headers.update({"Authorization": f"Basic {auth_header}", "User-Agent": USER_AGENT})

            res = session.get("https://api.vrchat.cloud/api/1/auth/user")
            if res.status_code != 200:
                self.status_label.setText(f"Login failed: {res.status_code}")
                return

            data = res.json()
            # 2FA handling
            if data.get("requiresTwoFactorAuth"):
                code, ok = QInputDialog.getText(self, "2FA Required", "Enter 2FA code:", QLineEdit.Normal)
                if not ok or not code:
                    self.status_label.setText("2FA code required to continue.")
                    return
                twofa_url = "https://api.vrchat.cloud/api/1/auth/twofactorauth/totp/verify"
                res2 = session.post(twofa_url, headers={"User-Agent": USER_AGENT}, json={"code": code})
                if res2.status_code != 200:
                    self.status_label.setText(f"2FA failed: {res2.status_code}")
                    return

            # Save session cookie
            cookie = session.cookies.get("auth")
            if cookie:
                # fetch user id automatically
                user_id = data.get("id")
                save_cookie(cookie, user_id)
                self.auth_cookie = cookie
                self.accept()
            else:
                self.status_label.setText("Failed to get session cookie after login.")
        except Exception as e:
            self.status_label.setText(f"Error: {e}")

# -----------------------
# Launcher Thread
# -----------------------
class LauncherThread(QThread):
    finished = Signal(str)
    def __init__(self, cmd: list):
        super().__init__()
        self.cmd = cmd
    def run(self):
        try:
            subprocess.Popen(self.cmd, shell=False)
            self.finished.emit("Launched successfully!")
        except Exception as e:
            self.finished.emit(f"Failed: {e}")

# -----------------------
# Fetch Instance Thread
# -----------------------
class FetchInstanceThread(QThread):
    fetched = Signal(str)
    def __init__(self, auth_cookie: str, user_id: str):
        super().__init__()
        self.auth_cookie = auth_cookie
        self.user_id = user_id

    def run(self):
        try:
            session = requests.Session()
            session.cookies.set("auth", self.auth_cookie)
            session.headers.update({"User-Agent": USER_AGENT})
            url = f"https://api.vrchat.cloud/api/1/users/{self.user_id}"
            res = session.get(url)
            if res.status_code == 200:
                data = res.json()
                loc = data.get("location", "")
                self.fetched.emit(loc)
            else:
                self.fetched.emit("None")
        except:
            self.fetched.emit("None")

# -----------------------
# Main Window
# -----------------------
class MainWindow(QWidget):
    def __init__(self, cookie: str, user_id: str):
        super().__init__()
        self.setWindowTitle("VR/Desktop Switcher By Zam")
        self.resize(600, 450)
        self.setStyleSheet("""
            QWidget { background-color: #1E1E2F; color: white; font-size: 14px; }
            QPushButton { background-color: #3C3C55; border-radius: 10px; padding: 8px; }
            QPushButton:hover { background-color: #5C5C80; }
            QLineEdit { background-color: #2A2A40; border-radius: 5px; padding: 5px; color: white; }
            QCheckBox { spacing: 5px; }
            QTextEdit { background-color: #2A2A40; border-radius: 5px; color: white; }
            QLabel#status { font-weight: bold; }
        """)
        self.auth_cookie = cookie
        self.user_id = user_id
        self.current_instance = None

        layout = QVBoxLayout()

        # Launch path
        path_layout = QHBoxLayout()
        self.path_input = QLineEdit(find_vrchat_launch_path())
        self.browse_btn = QPushButton("Browse")
        path_layout.addWidget(QLabel("Launch Path:"))
        path_layout.addWidget(self.path_input)
        path_layout.addWidget(self.browse_btn)
        layout.addLayout(path_layout)

        # Status
        self.status_label = QLabel("Fetching instance...")
        self.status_label.setObjectName("status")
        layout.addWidget(self.status_label)

        # Current instance
        self.instance_label = QLabel("Current Location: fetching...")
        layout.addWidget(self.instance_label)

        # Fetch instance button
        self.fetch_instance_btn = QPushButton("Get Current Instance")
        layout.addWidget(self.fetch_instance_btn)
        self.fetch_instance_btn.clicked.connect(self.update_instance)

        # Desktop toggle
        self.desktop_check = QCheckBox("Launch in Desktop (No VR)")
        layout.addWidget(self.desktop_check)

        # Buttons
        btn_layout = QHBoxLayout()
        self.launch_vr_btn = QPushButton("Launch VR")
        self.launch_vrchat_btn = QPushButton("Launch VRChat")
        btn_layout.addWidget(self.launch_vr_btn)
        btn_layout.addWidget(self.launch_vrchat_btn)
        layout.addLayout(btn_layout)

        # Console
        self.console_area = QTextEdit()
        self.console_area.setVisible(False)
        self.console_toggle_btn = QPushButton("Show Console")
        layout.addWidget(self.console_toggle_btn)
        layout.addWidget(self.console_area)

        self.setLayout(layout)

        # Connections
        self.browse_btn.clicked.connect(self.browse_path)
        self.launch_vr_btn.clicked.connect(self.launch_vr)
        self.launch_vrchat_btn.clicked.connect(self.launch_vrchat)
        self.console_toggle_btn.clicked.connect(self.toggle_console)

        # Start fetching instance automatically
        self.update_instance()

    # -----------------------
    # Methods
    # -----------------------
    def browse_path(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select VRChat launch.exe", os.path.expanduser("~"), "Executable Files (*.exe)")
        if path:
            self.path_input.setText(path)

    def log(self, msg: str):
        timestamp = time.strftime("%H:%M:%S")
        self.console_area.append(f"[{timestamp}] {msg}")

    def toggle_console(self):
        self.console_area.setVisible(not self.console_area.isVisible())

    def launch_vr(self):
        uri = "steam://rungameid/250820"
        self.log(f"Launching VR mode via Steam URI: {uri}")
        try:
            os.startfile(uri)
        except Exception as e:
            self.log(f"Failed: {e}")

    def launch_vrchat(self):
        path = self.path_input.text().strip()
        if not os.path.exists(path):
            QMessageBox.warning(self, "Error", "Invalid VRChat launch path.")
            return
        cmd = [path]
        if self.desktop_check.isChecked():
            cmd.append("--no-vr")
        if self.current_instance and self.current_instance != "None":
            cmd.append(f"vrchat://launch?id={self.current_instance}")
        self.log(f"Launching VRChat: {' '.join(cmd)}")
        self.thread = LauncherThread(cmd)
        self.thread.finished.connect(self.log)
        self.thread.start()

    # -----------------------
    # Instance fetching
    # -----------------------
    def update_instance(self):
        if not self.user_id:
            self.current_instance = None
            self.instance_label.setText("Current Location: None")
            self.status_label.setText("Not Ready!")
            self.status_label.setStyleSheet("color: red; font-weight: bold;")
            return
        self.log(f"Fetching current instance for {self.user_id}...")
        self.fetch_thread = FetchInstanceThread(self.auth_cookie, self.user_id)
        self.fetch_thread.fetched.connect(self.on_instance_fetched)
        self.fetch_thread.start()

    def on_instance_fetched(self, loc):
        if loc and loc != "":
            self.current_instance = loc
            self.instance_label.setText(f"Current Location: {self.current_instance}")
            self.status_label.setText("Ready!")
            self.status_label.setStyleSheet("color: lime; font-weight: bold;")
            save_cookie(self.auth_cookie, self.user_id)
        else:
            self.current_instance = None
            self.instance_label.setText("Current Location: None")
            self.status_label.setText("Not Ready!")
            self.status_label.setStyleSheet("color: red; font-weight: bold;")
            QTimer.singleShot(10000, self.update_instance)  # retry

# -----------------------
# Entry Point
# -----------------------
def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(30,30,47))
    palette.setColor(QPalette.WindowText, Qt.white)
    palette.setColor(QPalette.Base, QColor(42,42,64))
    palette.setColor(QPalette.Text, Qt.white)
    palette.setColor(QPalette.Button, QColor(60,60,85))
    palette.setColor(QPalette.ButtonText, Qt.white)
    app.setPalette(palette)

    cookie, saved_user_id = load_cookie()
    if cookie and test_cookie(cookie):
        # fetch user id from auth endpoint if not saved
        if not saved_user_id:
            try:
                session = requests.Session()
                session.cookies.set("auth", cookie)
                session.headers.update({"User-Agent": USER_AGENT})
                res = session.get("https://api.vrchat.cloud/api/1/auth/user")
                if res.status_code == 200:
                    saved_user_id = res.json().get("id")
                    save_cookie(cookie, saved_user_id)
            except:
                saved_user_id = None
        main_win = MainWindow(cookie, saved_user_id)
    else:
        login = LoginDialog()
        if login.exec() == QDialog.Accepted:
            # fetch user id from auth endpoint
            session = requests.Session()
            session.cookies.set("auth", login.auth_cookie)
            session.headers.update({"User-Agent": USER_AGENT})
            try:
                res = session.get("https://api.vrchat.cloud/api/1/auth/user")
                if res.status_code == 200:
                    user_id = res.json().get("id")
                else:
                    user_id = None
            except:
                user_id = None
            save_cookie(login.auth_cookie, user_id)
            main_win = MainWindow(login.auth_cookie, user_id)
        else:
            sys.exit()

    main_win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
