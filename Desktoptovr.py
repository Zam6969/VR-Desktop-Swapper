#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys, os, json, subprocess, time, base64
import requests
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit, QPushButton, QVBoxLayout,
    QHBoxLayout, QCheckBox, QDialog, QTextEdit, QMessageBox, QFileDialog, QInputDialog
)
from PySide6.QtCore import Qt, QThread, Signal, QUrl, QTimer
from PySide6.QtGui import QPalette, QColor, QDesktopServices, QFont

COOKIE_FILE = "vrchat_session.json"
USER_AGENT = "ZamVRChatTool/1.0"
GITHUB_URL = "https://github.com/Zam6969/VR-Desktop-Swapper"

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

def delete_cookie():
    if os.path.exists(COOKIE_FILE):
        os.remove(COOKIE_FILE)

def test_cookie(cookie):
    try:
        s = requests.Session()
        s.cookies.set("auth", cookie)
        s.headers["User-Agent"] = USER_AGENT
        res = s.get("https://api.vrchat.cloud/api/1/auth/user")
        print(f"[DEBUG] Testing cookie, status: {res.status_code}")
        return res.status_code == 200
    except Exception as e:
        print(f"[DEBUG] Cookie test error: {e}")
        return False

def find_vrchat_launch_path():
    p = r"E:\SteamLibrary\steamapps\common\VRChat\launch.exe"
    return p if os.path.exists(p) else ""

# -----------------------
# Login Dialog
# -----------------------
class LoginDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Login to VRChat get instance. -DesktopVrSwap by Zam ❤")
        self.setFixedSize(400, 250)
        self.setStyleSheet("""
            QDialog { background-color: #1c1c1e; }
            QLabel { color: white; font-size: 14px; }
            QLineEdit { background-color: #2c2c2e; border-radius: 10px; padding: 8px; color: white; }
            QPushButton { background-color: #007aff; border-radius: 12px; padding: 8px; color: white; font-weight: bold; }
            QPushButton:hover { background-color: #0051a8; }
        """)

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

    def login(self):
        try:
            self.status.setText("Logging in...")
            print(f"[DEBUG] Attempting login for {self.user.text()}")
            s = requests.Session()
            auth = base64.b64encode(f"{self.user.text()}:{self.pw.text()}".encode()).decode()
            s.headers.update({
                "Authorization": f"Basic {auth}",
                "User-Agent": USER_AGENT
            })

            r = s.get("https://api.vrchat.cloud/api/1/auth/user")
            print(f"[DEBUG] Login response code: {r.status_code}")
            if r.status_code != 200:
                self.status.setText("Login failed")
                print("[DEBUG] Login failed")
                return

            data = r.json()
            if data.get("requiresTwoFactorAuth"):
                print("[DEBUG] 2FA required")
                code, ok = QInputDialog.getText(self, "2FA", "Enter 2FA code")
                if not ok:
                    return
                r2 = s.post(
                    "https://api.vrchat.cloud/api/1/auth/twofactorauth/totp/verify",
                    json={"code": code},
                )
                if r2.status_code != 200:
                    self.status.setText("2FA failed")
                    print(f"[DEBUG] 2FA failed: {r2.status_code}")
                    return
                print("[DEBUG] 2FA success")

            self.auth_cookie = s.cookies.get("auth")
            save_cookie(self.auth_cookie, data.get("id"))
            print(f"[DEBUG] Auth cookie received: {self.auth_cookie}")
            self.accept()

        except Exception as e:
            self.status.setText(str(e))
            print(f"[DEBUG] Login error: {e}")

# -----------------------
# Threads
# -----------------------
class LauncherThread(QThread):
    finished_msg = Signal(str)

    def __init__(self, cmd, parent=None):
        super().__init__(parent)
        self.cmd = cmd

    def run(self):
        try:
            self.parent().log(f"Launching command: {self.cmd}")
            subprocess.Popen(self.cmd)
            self.finished_msg.emit("VRChat launched")
            self.parent().log("VRChat launch subprocess started")
        except Exception as e:
            self.finished_msg.emit(str(e))
            self.parent().log(f"LauncherThread error: {e}")

class FetchInstanceThread(QThread):
    fetched = Signal(dict)  # emit dict with location, worldId

    def __init__(self, auth_cookie: str, parent=None):
        super().__init__(parent)
        self.auth_cookie = auth_cookie

    def run(self):
        try:
            session = requests.Session()
            session.cookies.set("auth", self.auth_cookie)
            session.headers.update({"User-Agent": USER_AGENT})
            res = session.get("https://api.vrchat.cloud/api/1/auth/user")
            if res.status_code == 200:
                data = res.json()
                loc = data.get("presence", {}).get("instance") or data.get("location")
                world_id = data.get("presence", {}).get("world") or data.get("world")
                self.fetched.emit({"location": loc, "world_id": world_id})
                print(f"[DEBUG] Instance fetched: {loc}, World ID: {world_id}")
            else:
                self.fetched.emit({"location": None, "world_id": None})
                print(f"[DEBUG] Failed to fetch instance: {res.status_code}")
        except Exception as e:
            print(f"[DEBUG] FetchInstanceThread error: {e}")
            self.fetched.emit({"location": None, "world_id": None})

# -----------------------
# Main Window
# -----------------------
class MainWindow(QWidget):
    def __init__(self, cookie, uid):
        super().__init__()
        self.setWindowTitle("VR/Desktop Switcher By Zam")
        self.resize(600, 500)
        self.cookie = cookie
        self.uid = uid
        self.instance = None
        self.world_id = None
        self.fetch_thread = None
        self.launch_thread = None

        self.setStyleSheet("""
            QWidget { background-color: #1c1c1e; color: white; font-family: 'Helvetica Neue'; }
            QPushButton { background-color: #007aff; border-radius: 12px; padding: 10px; font-weight: bold; color: white; }
            QPushButton:hover { background-color: #0051a8; }
            QLineEdit { background-color: #2c2c2e; border-radius: 10px; padding: 10px; color: white; }
            QCheckBox { spacing: 5px; }
            QTextEdit { background-color: #2c2c2e; border-radius: 10px; color: white; padding: 8px; }
            QLabel { color: white; }
        """)

        main = QVBoxLayout(self)

        # Rainbow Username Label
        self.user_label = QLabel("Logged in as: ...")
        self.user_label.setFont(QFont("Helvetica Neue", 16, QFont.Bold))
        main.addWidget(self.user_label)
        self.rainbow_hue = 0
        self.username_timer = QTimer()
        self.username_timer.timeout.connect(self.update_rainbow_username)
        self.username_timer.start(50)

        # Launch Path
        row = QHBoxLayout()
        self.path = QLineEdit(find_vrchat_launch_path())
        browse = QPushButton("Browse")
        row.addWidget(QLabel("Launch Path:"))
        row.addWidget(self.path)
        row.addWidget(browse)
        main.addLayout(row)
        browse.clicked.connect(self.browse)

        # Status & Location
        self.status = QLabel("Fetching instance...")
        self.location = QLabel("Current Location: ...")
        self.world_name_label = QLabel("World Name: ...")
        main.addWidget(self.status)
        main.addWidget(self.location)
        main.addWidget(self.world_name_label)

        # Fetch Instance Button
        self.fetch_btn = QPushButton("Get Current Instance")
        main.addWidget(self.fetch_btn)
        self.fetch_btn.clicked.connect(self.update_instance)

        # Desktop Checkbox
        self.desktop = QCheckBox("Launch in Desktop (No VR)")
        main.addWidget(self.desktop)

        # Launch Buttons
        btns = QHBoxLayout()
        steamvr = QPushButton("Launch SteamVR")
        vrchat = QPushButton("Launch VRChat")
        btns.addWidget(steamvr)
        btns.addWidget(vrchat)
        main.addLayout(btns)
        steamvr.clicked.connect(self.launch_steamvr)
        vrchat.clicked.connect(self.launch_vrchat)

        # Console
        self.console = QTextEdit()
        self.console.setVisible(True)
        main.addWidget(self.console)
        toggle = QPushButton("Hide Console")
        toggle.clicked.connect(lambda: self.console.setVisible(not self.console.isVisible()))
        main.addWidget(toggle)

        # Heart floating button (top-right)
        self.heart_btn = QPushButton("❤️", self)
        self.heart_btn.setToolTip("View on GitHub")
        self.heart_btn.setStyleSheet("""
            QPushButton {
                background-color: #ff2d55;
                border-radius: 25px;    /* round button */
                font-size: 24px;        /* slightly bigger heart, fits button */
                color: white;
            }
            QPushButton:hover {
                background-color: #ff5c8a;
            }
        """)
        self.heart_btn.setFixedSize(50, 50)  # button big enough for heart
        self.heart_btn.move(self.width() - 60, self.height() - 60)  # bottom-right float
        self.heart_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(GITHUB_URL)))
        self.heart_btn.raise_()
        self.heart_btn.show()

        def update_heart_pos(event=None):
            padding = 10
            self.heart_btn.move(self.width() - self.heart_btn.width() - padding, padding)
        self.resizeEvent = lambda event: (update_heart_pos(), QWidget.resizeEvent(self, event))
        update_heart_pos()

        # Fetch instance and display name
        self.update_instance()
        self.fetch_display_name()

    # -----------------------
    def update_rainbow_username(self):
        self.rainbow_hue = (self.rainbow_hue + 1) % 360
        color = QColor.fromHsv(self.rainbow_hue, 255, 255)
        self.user_label.setStyleSheet(f"color: {color.name()}; font-weight: bold;")

    def log(self, msg):
        timestamp = time.strftime("%H:%M:%S")
        self.console.append(f"[{timestamp}] {msg}")
        print(f"[DEBUG {timestamp}] {msg}")

    def fetch_display_name(self):
        try:
            s = requests.Session()
            s.cookies.set("auth", self.cookie)
            s.headers["User-Agent"] = USER_AGENT
            r = s.get("https://api.vrchat.cloud/api/1/auth/user")
            display_name = r.json().get("displayName", "Unknown") if r.status_code == 200 else "Unknown"
            self.user_label.setText(f"Logged in as: {display_name}")
            self.log(f"Display name fetched: {display_name}")
        except Exception as e:
            self.user_label.setText("Logged in as: Unknown")
            self.log(f"Error fetching display name: {e}")

    # -----------------------
    def browse(self):
        p, _ = QFileDialog.getOpenFileName(self, "Select launch.exe", "", "Executable (*.exe)")
        if p:
            self.path.setText(p)
            self.log(f"Selected launch path: {p}")

    def launch_steamvr(self):
        self.log("Launching SteamVR...")
        os.startfile("steam://rungameid/250820")

    def launch_vrchat(self):
        cmd = [self.path.text()]
        if self.desktop.isChecked():
            cmd.append("--no-vr")
        if self.instance:
            cmd.append(f"vrchat://launch?id={self.instance}")

        self.log(f"Launching VRChat with args: {cmd}")
        self.launch_thread = LauncherThread(cmd, self)
        self.launch_thread.finished_msg.connect(self.log)
        self.launch_thread.finished.connect(self.launch_thread.deleteLater)
        self.launch_thread.start()

    # -----------------------
    def update_instance(self):
        self.log("Fetching current instance and world info...")
        self.fetch_thread = FetchInstanceThread(self.cookie, self)
        self.fetch_thread.fetched.connect(self.on_instance_fetched)
        self.fetch_thread.start()

    def on_instance_fetched(self, data):
        self.instance = data.get("location")
        self.world_id = data.get("world_id")
        self.location.setText(f"Current Location: {self.instance or 'None'}")
        self.world_name_label.setText("World Name: ...")
        self.log(f"Current instance: {self.instance or 'None'}")

        if self.instance and self.world_id:
            self.fetch_world_info(self.world_id)
        else:
            self.status.setText("Not Ready")
            self.status.setStyleSheet("color: red; font-weight: bold;")

    def fetch_world_info(self, world_id):
        try:
            s = requests.Session()
            s.cookies.set("auth", self.cookie)
            s.headers["User-Agent"] = USER_AGENT
            r = s.get(f"https://api.vrchat.cloud/api/1/worlds/{world_id}")
            if r.status_code == 200:
                data = r.json()
                self.world_name_label.setText(f"World Name: {data.get('name', 'Unknown')}")
                self.log(f"World info fetched: {data.get('name')}")
                if self.instance and data.get("name"):
                    self.status.setText("Ready")
                    self.status.setStyleSheet("color: lime; font-weight: bold;")
                else:
                    self.status.setText("Not Ready")
                    self.status.setStyleSheet("color: red; font-weight: bold;")
            else:
                self.world_name_label.setText("World Name: Unknown")
                self.status.setText("Not Ready")
                self.status.setStyleSheet("color: red; font-weight: bold;")
                self.log(f"Failed to fetch world info: {r.status_code}")
        except Exception as e:
            self.world_name_label.setText("World Name: Unknown")
            self.status.setText("Not Ready")
            self.status.setStyleSheet("color: red; font-weight: bold;")
            self.log(f"Error fetching world info: {e}")

# -----------------------
# Entry
# -----------------------
def main():
    app = QApplication(sys.argv)

    # Dark palette like iOS
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(28,28,30))
    palette.setColor(QPalette.WindowText, Qt.white)
    palette.setColor(QPalette.Base, QColor(44,44,46))
    palette.setColor(QPalette.Text, Qt.white)
    palette.setColor(QPalette.Button, QColor(0,122,255))
    palette.setColor(QPalette.ButtonText, Qt.white)
    app.setPalette(palette)
    app.setStyle("Fusion")

    cookie, uid = load_cookie()
    if cookie and not test_cookie(cookie):
        QMessageBox.warning(None, "Session Expired", "Please log in again.")
        delete_cookie()
        cookie = None

    if not cookie:
        dlg = LoginDialog()
        if dlg.exec() != QDialog.Accepted:
            sys.exit()
        cookie = dlg.auth_cookie
        s = requests.Session()
        s.cookies.set("auth", cookie)
        s.headers["User-Agent"] = USER_AGENT
        uid = s.get("https://api.vrchat.cloud/api/1/auth/user").json().get("id")

    win = MainWindow(cookie, uid)
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
