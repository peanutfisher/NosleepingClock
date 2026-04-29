import time
import pyautogui
import threading
import datetime
from lunardate import LunarDate
import requests
from loguru import logger
from PIL import Image
from io import BytesIO
import ctypes
from functools import wraps
from pathlib import Path
import os
import sys

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QPushButton, QCheckBox, 
                             QComboBox, QMessageBox, QSystemTrayIcon, QMenu)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QIcon, QAction, QFont, QPixmap, QImage
from PyQt6.QtNetwork import QSslConfiguration

# Get the absolute path of the current ico file
if getattr(sys, 'frozen', False):
    current_dir = Path(sys._MEIPASS)
else:
    current_dir = Path(__file__).parent
    
icon_path_off = current_dir / "ICON" / "NoSleepingClock.ico"
icon_path_on = current_dir / "ICON" / "NoSleepingClock_ON.ico"
icon_path = str(icon_path_off)
logger.debug(f"icon_path_off: {icon_path_off}")
logger.debug(f"icon_path_on: {icon_path_on}")

# Windows API: Set system execution state
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002

class SignalEmitter(QObject):
    """用于线程安全的信号发射"""
    update_weather_signal = pyqtSignal(str, str, str, str)
    update_status_signal = pyqtSignal()
    update_clock_signal = pyqtSignal()

def log_function_call(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        logger.debug(f"Calling function: {func.__name__} with args: {args}, kwargs: {kwargs}")
        result = func(*args, **kwargs)
        logger.debug(f"Function {func.__name__} returned: {result}")
        return result
    return wrapper

class NoSleepingClock(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("No Sleeping Clock")
        self.setFixedSize(500, 450)
        
        # Thread lock and state variables
        self.lock = threading.Lock()
        self.awake_screen_enabled = False
        self.running = True
        self.timer_active = False
        self.remaining_time = 0
        self.timer_thread = None
        
        # Checkbox related variables
        self.checkbox_enabled = False
        self.selected_hours = "8"
        
        # Weather-related configuration
        self.weather_api_key = "d98529ebc7824327abd62335250709"
        self.current_city = "shanghai"
        self.weather_data = {"temp": "--", "condition": "Loading..."}
        
        # Signal emitter for thread-safe UI updates
        self.signal_emitter = SignalEmitter()
        self.signal_emitter.update_weather_signal.connect(self.update_weather_ui)
        self.signal_emitter.update_status_signal.connect(self.update_status_label)
        self.signal_emitter.update_clock_signal.connect(self.update_clock)
        
        # Create UI
        self.create_widgets()
        
        # Set window icon
        self.setWindowIcon(QIcon(str(icon_path_off)))
        
        # Update clock
        self.time_unit = 3600
        
        # Start auto-click thread
        self.awake_thread = threading.Thread(target=self.awake_screen, daemon=True)
        self.awake_thread.start()
        
        # Start weather update thread
        self.weather_thread = threading.Thread(target=self.update_weather, daemon=True)
        self.weather_thread.start()
        
        # Create system tray icon
        self.tray_icon = None
        self.minimized_to_tray = False
        self.create_tray_icon()
        
        # Clock timer
        self.clock_timer = QTimer()
        self.clock_timer.timeout.connect(self.update_clock)
        self.clock_timer.start(1000)
        
        # Window close event
        self.closeEvent = self.on_close
        
    def create_widgets(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # Time label
        self.time_label = QLabel()
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        time_font = QFont("Microsoft YaHei UI", 40, QFont.Weight.Bold)
        self.time_label.setFont(time_font)
        main_layout.addWidget(self.time_label)
        
        # Date and weekday labels
        date_layout = QHBoxLayout()
        date_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.date_label = QLabel()
        date_font = QFont("Microsoft YaHei UI", 20)
        self.date_label.setFont(date_font)
        self.weekday_label = QLabel()
        self.weekday_label.setFont(date_font)
        date_layout.addWidget(self.date_label)
        date_layout.addWidget(self.weekday_label)
        main_layout.addLayout(date_layout)
        
        # Lunar label
        self.lunar_label = QLabel()
        lunar_font = QFont("Microsoft YaHei UI", 18)
        self.lunar_label.setFont(lunar_font)
        self.lunar_label.setStyleSheet("color: #777777;")
        self.lunar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.lunar_label)
        
        # Weather information
        weather_layout = QHBoxLayout()
        weather_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.weather_icon = QLabel("☀️")
        self.weather_icon.setFont(QFont("SimHei", 14))
        self.weather_label = QLabel()
        weather_font = QFont("Segoe UI Variable", 11, QFont.Weight.Bold)
        self.weather_label.setFont(weather_font)
        self.weather_label.setStyleSheet("color: #007BFF;")
        weather_layout.addWidget(self.weather_icon)
        weather_layout.addWidget(self.weather_label)
        main_layout.addLayout(weather_layout)
        
        # Status label
        self.status_label = QLabel("No sleeping is being Disabled")
        status_font = QFont("Microsoft YaHei UI", 13, QFont.Weight.Bold)
        self.status_label.setFont(status_font)
        self.status_label.setStyleSheet("color: #666666;")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.status_label)
        
        # Control frame
        control_layout = QHBoxLayout()
        control_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        control_layout.setSpacing(10)
        
        # No Sleeping button
        self.control_btn = QPushButton("No Sleeping")
        self.control_btn.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        self.control_btn.setFixedSize(150, 40)
        self.control_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: 3px solid #4CAF50;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        self.control_btn.clicked.connect(self.toggle_awake_screen)
        control_layout.addWidget(self.control_btn)
        
        # Checkbox
        self.auto_stop_checkbox = QCheckBox("running for hours:")
        self.auto_stop_checkbox.setFont(QFont("Arial", 12))
        self.auto_stop_checkbox.setEnabled(False)
        control_layout.addWidget(self.auto_stop_checkbox)
        self.auto_stop_checkbox.stateChanged.connect(self.on_auto_stop_checkbox)
        
        # Combobox
        self.hours_combobox = QComboBox()
        self.hours_combobox.addItems([str(i) for i in range(1, 13)])
        self.hours_combobox.setCurrentText("8")
        self.hours_combobox.setEnabled(False)
        self.hours_combobox.setFixedWidth(60)
        self.hours_combobox.currentTextChanged.connect(self.on_hour_selected)
        control_layout.addWidget(self.hours_combobox)
        
        main_layout.addLayout(control_layout)
        
    def update_clock(self):
        now = datetime.datetime.now()
        time_str = now.strftime("%H:%M:%S")
        self.time_label.setText(time_str)
        
        date_str = now.strftime("%Y-%m-%d")
        self.date_label.setText(date_str)
        
        weekday_str = now.strftime("%A")
        self.weekday_label.setText(weekday_str)
        
        # Update lunar calendar
        try:
            lunar = LunarDate.fromSolarDate(now.year, now.month, now.day)
            lunar_month = self.number_to_chinese(lunar.month)
            lunar_day = self.number_to_chinese(lunar.day)
            lunar_str = f"农历: {lunar_month}月{lunar_day}日"
            self.lunar_label.setText(lunar_str)
        except Exception as e:
            self.lunar_label.setText("Lunar Calendar CANNOT LOAD...")
    
    def number_to_chinese(self, num):
        chinese_num = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十",
                       "十一", "十二", "十三", "十四", "十五", "十六", "十七",
                       "十八", "十九", "二十", "廿一", "廿二", "廿三", "廿四",
                       "廿五", "廿六", "廿七", "廿八", "廿九", "三十"]
        return chinese_num[num - 1] if 1 <= num <= 30 else str(num)
    
    def on_auto_stop_checkbox(self, state):
        with self.lock:
            self.checkbox_enabled = (state == 2)  # 2 = checked
        logger.info(f"Auto stop checkbox state changed: {self.checkbox_enabled}")
        
        if self.checkbox_enabled:
            self.hours_combobox.setEnabled(True)
            if self.awake_screen_enabled:
                self.start_timer()
        else:
            self.hours_combobox.setEnabled(True)
            self.stop_timer()
        
        self.signal_emitter.update_status_signal.emit()
        self.update_tray_menu()
    
    def on_hour_selected(self, text):
        selected_hours = int(text)
        self.selected_hour = selected_hours
        total_seconds = selected_hours * self.time_unit
        logger.info(f"Selected {selected_hours} hours ({total_seconds} seconds)")
        
        with self.lock:
            self.remaining_time = total_seconds
        
        if self.checkbox_enabled and self.awake_screen_enabled:
            self.start_timer()
        
        self.signal_emitter.update_status_signal.emit()
        self.update_tray_menu()
    
    def toggle_awake_screen(self):
        with self.lock:
            self.awake_screen_enabled = not self.awake_screen_enabled
        logger.debug(f"Toggle awake_screen: {self.awake_screen_enabled}")
        
        if self.awake_screen_enabled:
            self.control_btn.setText("No Sleeping")
            self.control_btn.setStyleSheet("""
                QPushButton {
                    background-color: #f44336;
                    color: white;
                    border: 3px solid #f44336;
                    border-radius: 5px;
                }
                QPushButton:hover {
                    background-color: #da190b;
                }
            """)
            self.status_label.setText("No sleeping is running now")
            self.status_label.setStyleSheet("color: #d32f2f;")
            self.auto_stop_checkbox.setEnabled(True)
            self.checkbox_enabled = self.auto_stop_checkbox.isChecked()
            logger.debug(f"Checkbox enabled: {self.checkbox_enabled}")
            self.hours_combobox.setEnabled(True)
            if self.checkbox_enabled:
                self.start_timer()
            logger.info("No Sleeping is running now")
        else:
            self.disable_awake_screen()
            logger.info("No Sleeping is being disabled")
        
        self.signal_emitter.update_status_signal.emit()
        self.update_tray_menu()
        self.update_tray_icon()
    
    def awake_screen(self):
        previous_enabled = False
        
        while self.running:
            with self.lock:
                enabled = self.awake_screen_enabled
            
            if enabled != previous_enabled:
                if enabled:
                    try:
                        result = ctypes.windll.kernel32.SetThreadExecutionState(
                            ES_CONTINUOUS | 
                            ES_SYSTEM_REQUIRED | 
                            ES_DISPLAY_REQUIRED
                        )
                        if result == 0:
                            raise ctypes.WinError()
                        logger.debug("Win API SetThreadExecutionState called successfully")
                    except Exception as e:
                        logger.error(f"SetThreadExecutionState failed: {e}")
                        screen_width, screen_height = pyautogui.size()
                        x, y = pyautogui.position()
                        pyautogui.moveTo(x + 1, y)
                        logger.warning("Using pyautogui as fallback")
                else:
                    try:
                        result = ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
                        if result == 0:
                            raise ctypes.WinError()
                        logger.debug("Reset execution state to allow sleep")
                    except Exception as e:
                        logger.error(f"Failed to reset execution state: {e}")
                    self.stop_timer()
                
                previous_enabled = enabled
            
            if enabled:
                time.sleep(5)
            else:
                time.sleep(1)
    
    def start_timer(self):
        if not self.checkbox_enabled or not self.awake_screen_enabled:
            return
        
        if self.timer_thread and self.timer_thread.is_alive():
            logger.debug("Stopping existing timer thread before starting a new one")
            self.stop_timer()
        
        selected_hours = int(self.hours_combobox.currentText())
        total_seconds = selected_hours * self.time_unit
        with self.lock:
            self.remaining_time = total_seconds
            self.timer_active = True
        
        thread_name = f"TimerThread-{selected_hours}h"
        self.timer_thread = threading.Thread(target=self.run_timer, name=thread_name, daemon=True)
        self.timer_thread.start()
        logger.info(f"Timer started: {thread_name}")
    
    def run_timer(self):
        try:
            while True:
                with self.lock:
                    if not self.timer_active or not self.awake_screen_enabled or self.remaining_time <= 0:
                        break
                    current_time = self.remaining_time
                time.sleep(0.1)
                
                with self.lock:
                    self.remaining_time = max(0, current_time - 0.1)
                
                if int(self.remaining_time) != int(current_time):
                    self.signal_emitter.update_status_signal.emit()
            
            if self.remaining_time <= 0 and self.awake_screen_enabled:
                # Use QTimer to call disable_awake_screen on main thread
                QTimer.singleShot(0, self.disable_awake_screen)
                logger.info("Timer ended, No Sleeping function is being disabled automatically")
        except Exception as e:
            logger.error(f"Timer thread error: {e}")
        finally:
            self.stop_timer()
    
    def stop_timer(self):
        logger.debug("Stopping timer is running...")
        
        with self.lock:
            self.timer_active = False
        
        try:
            if self.timer_thread and self.timer_thread.is_alive():
                self.timer_thread.join(timeout=0.5)
        except Exception as e:
            logger.error(f"Error stopping timer thread: {e}")
        finally:
            self.timer_thread = None
            logger.info("ALL Timer has been stopped")
        
        self.signal_emitter.update_status_signal.emit()
        logger.debug("Stop Timer done ✅")
    
    def disable_awake_screen(self):
        with self.lock:
            if self.awake_screen_enabled:
                self.awake_screen_enabled = False
                self.checkbox_enabled = False
                self.timer_active = False
        
        self.control_btn.setText("No Sleeping")
        self.control_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: 3px solid #4CAF50;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        self.status_label.setText("No sleeping is being disabled")
        self.status_label.setStyleSheet("color: #2E7D32;")
        self.auto_stop_checkbox.setEnabled(False)
        self.hours_combobox.setEnabled(False)
        
        self.stop_timer()
        self.update_tray_menu()
    
    def update_status_label(self):
        with self.lock:
            if not self.awake_screen_enabled:
                self.status_label.setText("No sleeping is being disabled")
                self.status_label.setStyleSheet("color: #666666;")
                return
            
            if not self.checkbox_enabled:
                self.status_label.setText("No sleeping is running now")
                self.status_label.setStyleSheet("color: #d32f2f;")
                return
            
            hours = int(self.remaining_time // 3600)
            minutes = int((self.remaining_time % 3600) // 60)
            seconds = int(self.remaining_time % 60)
            
            if hours == 0:
                if minutes == 0:
                    self.status_label.setText(f"No sleeping will stop after {seconds}s")
                else:
                    self.status_label.setText(f"No sleeping will stop after {minutes}m {seconds}s")
            else:
                self.status_label.setText(f"No sleeping will stop after {hours}h {minutes}m {seconds}s")
            
            self.status_label.setStyleSheet("color: #1976D2;")
    
    def update_weather(self):
        while self.running:
            try:
                self.current_city = self.get_city_from_ip()
                logger.debug(f"Current city: {self.current_city}")
                
                url = f"https://api.weatherapi.com/v1/current.json?key={self.weather_api_key}&q={self.current_city}&lang=en"
                response = requests.get(url, timeout=5, verify=False)
                data = response.json()
                logger.debug(f"API returned data: {data}")
                
                if data.get("error"):
                    raise Exception(f"WeatherAPI Error: {data['error']['message']}")
                
                temp = data["current"]["temp_c"]
                condition = data["current"]["condition"]["text"]
                icon = data["current"]["condition"]["icon"]
                city = data["location"]["name"]
                
                self.signal_emitter.update_weather_signal.emit(str(temp), condition, icon, city)
                
            except Exception:
                logger.exception("@_@")
                self.signal_emitter.update_weather_signal.emit("--", "failed to load", "❌", "")
            
            time.sleep(3600)
    
    def update_weather_ui(self, temp, condition, icon_url, city):
        self.weather_label.setText(f"{city}: {condition} {temp}°C")
        
        if icon_url and icon_url != "❌":
            try:
                full_icon_url = "https:" + icon_url
                response = requests.get(full_icon_url, timeout=5, verify=False)
                if response.status_code == 200:
                    image_data = response.content
                    qimage = QImage.fromData(image_data)
                    if not qimage.isNull():
                        pixmap = QPixmap.fromImage(qimage)
                        self.weather_icon.setPixmap(pixmap)
                    else:
                        logger.error("Failed to create QImage from weather icon data")
            except Exception as e:
                logger.error(f"Failed to load weather icon: {e}")
    
    def get_city_from_ip(self):
        try:
            for _ in range(3):
                response = requests.get("https://ipinfo.io/json", timeout=5, verify=False)
                if response.status_code == 200:
                    data = response.json()
                    logger.debug(f"IP API returned data: {data}")
                    city = data["city"]
                    return city
                else:
                    logger.warning(f"IP API response status code: {response.status_code}, retrying...")
                time.sleep(20)
            logger.exception("Failed to get city from IP, using default city: shanghai")
            return self.current_city
        except Exception:
            logger.exception("Failed to get city from IP, using default city: shanghai")
            return self.current_city
    
    def create_tray_icon(self):
        logger.debug("Creating system tray icon")
        try:
            self.tray_icon = QSystemTrayIcon(self)
            self.tray_icon.setIcon(QIcon(str(icon_path_off)))
            self.tray_icon.setToolTip("No Sleeping Clock")
            
            # Create tray menu
            self.tray_menu = QMenu()
            
            self.start_stop_action = QAction("Start", self)
            self.start_stop_action.triggered.connect(self.toggle_awake_from_tray)
            self.tray_menu.addAction(self.start_stop_action)
            
            self.running_hours_menu = self.tray_menu.addMenu("Running hours")
            self.create_time_menu()
            
            self.tray_menu.addSeparator()
            
            restore_action = QAction("Restore", self)
            restore_action.triggered.connect(self.restore_window)
            self.tray_menu.addAction(restore_action)
            
            quit_action = QAction("Quit", self)
            quit_action.triggered.connect(self.quit_app)
            self.tray_menu.addAction(quit_action)
            
            self.tray_icon.setContextMenu(self.tray_menu)
            
            # Double-click to restore window
            self.tray_icon.activated.connect(self.on_tray_icon_activated)
            
            self.tray_icon.show()
            logger.info("System tray icon created successfully")
        except Exception as e:
            logger.error(f"Failed to create system tray icon: {e}")
            QMessageBox.critical(self, "Error", f"Failed to create system tray icon: {e}")
    
    def create_time_menu(self):
        self.running_hours_menu.clear()
        for h in range(1, 13):
            action = QAction(f"{h}h", self)
            if hasattr(self, 'selected_hour') and self.selected_hour == h and self.awake_screen_enabled and self.checkbox_enabled:
                action.setText(f"✓ {h}h")
            action.triggered.connect(lambda checked, hours=h: self.set_time_option(hours))
            self.running_hours_menu.addAction(action)
    
    def set_time_option(self, hours):
        logger.info(f"Setting time option to {hours} hours")
        
        self.selected_hour = hours
        self.hours_combobox.setCurrentText(str(hours))
        
        with self.lock:
            self.checkbox_enabled = True
            self.awake_screen_enabled = True
        
        self.control_btn.setText("No Sleeping")
        self.control_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                border: 3px solid #f44336;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #da190b;
            }
        """)
        self.status_label.setText("No sleeping is running now")
        self.status_label.setStyleSheet("color: #d32f2f;")
        self.auto_stop_checkbox.setEnabled(True)
        self.auto_stop_checkbox.setChecked(True)
        self.hours_combobox.setEnabled(True)
        
        self.on_hour_selected(str(hours))
        self.update_tray_menu()
        
        logger.debug("Time option set complete")
    
    def update_tray_menu(self):
        if self.tray_icon:
            self.start_stop_action.setText("Stop" if self.awake_screen_enabled else "Start")
            self.create_time_menu()
    
    def update_tray_icon(self):
        if self.tray_icon:
            icon_path_to_use = str(icon_path_on) if self.awake_screen_enabled else str(icon_path_off)
            self.tray_icon.setIcon(QIcon(icon_path_to_use))
            logger.info(f"Tray icon updated to: {icon_path_to_use}")
    
    def on_tray_icon_activated(self, reason):
        """Handle tray icon activation (including double-click)"""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            logger.debug("Tray icon double-click detected")
            self.restore_window()
    
    def toggle_awake_from_tray(self):
        logger.info("Toggle awake screen from tray menu")
        self.toggle_awake_screen()
        self.update_tray_menu()
    
    def quit_app(self):
        logger.info("Quitting application through tray menu")
        self.on_close()
    
    def restore_window(self):
        logger.info("Restoring window from system tray")
        self.showNormal()
        self.setWindowState(Qt.WindowState.WindowActive)
        self.raise_()
        self.activateWindow()
        self.minimized_to_tray = False
    
    def changeEvent(self, event):
        if event.type() == event.Type.WindowStateChange:
            if self.windowState() & Qt.WindowState.WindowMinimized:
                logger.debug("Window is being minimized")
                self.minimized_to_tray = True
                self.hide()
        super().changeEvent(event)
    
    def on_close(self, event):
        reply = QMessageBox.question(self, 'Quit',
                                     'Do you want to Quit the Window?',
                                     QMessageBox.StandardButton.Yes |
                                     QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            with self.lock:
                self.running = False
                self.timer_active = False

            # Stop all threads
            if self.awake_thread and self.awake_thread.is_alive():
                self.awake_thread.join(timeout=2.0)

            if self.weather_thread and self.weather_thread.is_alive():
                self.weather_thread.join(timeout=2.0)

            self.stop_timer()

            # Stop tray icon
            if self.tray_icon:
                self.tray_icon.hide()

            # Quit application
            QApplication.instance().quit()

            event.accept()
        else:
            event.ignore()

if __name__ == "__main__":
    try:
        app = QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(False)  # Don't quit when window is closed (tray icon keeps running)
        
        window = NoSleepingClock()
        window.show()
        
        sys.exit(app.exec())
    except Exception:
        logger.exception("OMG! Error Shows!")
        time.sleep(5)
