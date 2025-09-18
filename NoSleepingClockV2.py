import time
import pyautogui
import threading
import tkinter as tk
from tkinter import font, messagebox, ttk
import datetime
from lunardate import LunarDate
import requests  # 天气API请求库
from loguru import logger  # 日志库
from PIL import Image, ImageTk, ImageDraw
from io import BytesIO
import ctypes
from functools import wraps
import pystray  # 系统托盘图标库
from pathlib import Path
import os
import sys

# 获取当前ico文件的绝对路径
if getattr(sys, 'frozen', False):
    # nuitka onefile mode
    current_dir = Path(sys._MEIPASS)
else:
    current_dir = Path(__file__).parent
    
icon_path = current_dir / "ICON" / "NoSleepingClock.ico"
icon_path = str(icon_path)
logger.debug(f"icon_path: {icon_path}")


# Windows API：设置系统执行状态
ES_CONTINUOUS = 0x80000000 #（持续生效）
ES_SYSTEM_REQUIRED = 0x00000001 #（系统需要保持活跃）
ES_DISPLAY_REQUIRED = 0x00000002 #（显示器需要保持活跃）

# 配置日志功能
# logger.add(
#     "app.log",
#     format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {process.id}:{thread.id} | {module}:{line} | {message}",
#     rotation="5 MB",
#     retention="3 days",
#     compression="zip",
#     encoding="UTF-8"
# )


def log_function_call(func):
    """配置装饰器记录函数调用"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        logger.debug(f"Calling function: {func.__name__} with args: {args}, kwargs: {kwargs}")
        result = func(*args, **kwargs)
        logger.debug(f"Function {func.__name__} returned: {result}")
        return result
    return wrapper

class NoSleepingClock:
    def __init__(self, root):
        self.root = root
        self.root.title("No Sleeping Clock")
        #self.root.geometry("500x450")  # 增加窗口高度以容纳新控件
        self.root.resizable(False, False)
        self.root.configure(bg="#f0f0f0")

        # 线程锁和状态变量
        self.lock = threading.Lock()
        self.awake_screen_enabled = False
        self.running = True
        self.timer_active = False  # 倒计时状态标志
        self.remaining_time = 0  # 剩余时间（秒）
        self.timer_thread = None  # 倒计时线程

        # 新增状态变量
        self.checkbox_enabled = False  # 是否启用自动停止
        self.checkbox_var = tk.IntVar(value=0) # 复选框变量 - 默认不勾选
        self.selected_hours = tk.StringVar(value="8")  # 默认8小时

        # 天气相关配置
        self.weather_api_key = "d98529ebc7824327abd62335250709"  # 替换为你的WeatherAPI密钥 https://www.weatherapi.com/my/
        self.current_city = "shanghai"  # 默认城市, 也可用https://ipapi.co/json/ 动态获取IP地址对应的城市
        self.weather_data = {"temp": "--", "condition": "Loading..."}

        # 设置字体
        self.time_font = font.Font(family="Microsoft YaHei UI", size=40, weight="bold")
        self.date_font = font.Font(family="Microsoft YaHei UI", size=16)
        self.lunar_font = font.Font(family="Microsoft YaHei UI", size=14)
        self.status_font = font.Font(family="Microsoft YaHei UI", size=13, weight="bold")
        self.weather_font = font.Font(family="Segoe UI Variable", size=11, weight="bold")

        # 设置主窗口图标
        self.root.iconbitmap(icon_path)
    
        # 创建界面
        self.create_widgets()
        
        # 让窗口根据内容调整大小
        self.root.update()  # 更新窗口以计算控件实际大小
        self.root.minsize(self.root.winfo_width(), self.root.winfo_height())  # 设置最小尺寸
        
        # 更新时钟
        self.update_clock()
        self.time_unit = 3600  # 每小时的秒数
        #self.time_unit = 10  # 测试用，每10秒代表1小时
        
        # 启动自动点击线程
        self.awake_thread = threading.Thread(target=self.awake_screen, daemon=True)
        self.awake_thread.start()

        # 启动天气更新线程
        self.weather_thread = threading.Thread(target=self.update_weather, daemon=True)
        self.weather_thread.start()

        # 窗口关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # 创建托盘相关配置
        self.tray_icon = None
        self.minimized_to_tray = False
        self.tray_icon_created = False  # 托盘图标创建标志
        
        # 创建托盘图标事件绑定
        #self.root.protocol("WM_ICONIZE", self.on_minimize) # 窗口最小化事件绑定
        self.root.bind("<Unmap>", self.on_window_unmap) # 另一种最小化事件绑定
        
        # 托盘running hours子菜单初始化时同步初始值
        #self.selected_hour = int(self.selected_hours.get())
        self.selected_hour = None
        self.awake_screen_enabled = False
        
    def create_widgets(self):
        main_frame = tk.Frame(self.root, bg="#f0f0f0")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)

        # 时间显示
        self.time_label = tk.Label(main_frame, font=self.time_font, text="", bg="#f0f0f0", fg="#333333")
        self.time_label.pack(pady=10)

        # 日期和星期显示
        self.date_frame = tk.Frame(main_frame, bg="#f0f0f0")
        self.date_frame.pack()

        self.date_label = tk.Label(self.date_frame, font=self.date_font, text="", bg="#f0f0f0", fg="#555555")
        self.date_label.pack(side=tk.LEFT, padx=10)
        self.weekday_label = tk.Label(self.date_frame, font=self.date_font, text="", bg="#f0f0f0", fg="#555555")
        self.weekday_label.pack(side=tk.LEFT, padx=10)

        # 阴历显示
        self.lunar_label = tk.Label(main_frame, font=self.lunar_font, text="", bg="#f0f0f0", fg="#777777")
        self.lunar_label.pack(pady=5)

        # 天气信息显示
        self.weather_frame = tk.Frame(main_frame, bg="#f0f0f0")
        self.weather_frame.pack(pady=5)
        self.weather_icon = tk.Label(self.weather_frame, text="☀️", font=("SimHei", 14), bg="#f0f0f0")
        self.weather_icon.pack(side=tk.LEFT, padx=5)
        self.weather_label = tk.Label(self.weather_frame, font=self.weather_font, text="", bg="#f0f0f0", fg="#007BFF")
        self.weather_label.pack(side=tk.LEFT, padx=5)

        # 状态显示
        self.status_label = tk.Label(main_frame, text="No sleeping is being Disabled", fg="#666666", bg="#f0f0f0", font=self.status_font)
        self.status_label.pack(pady=5)

        # 控制按钮区域
        control_frame = tk.Frame(main_frame, bg="#f0f0f0")
        control_frame.pack(pady=10)

        # No Sleeping按钮
        self.control_btn = tk.Button(
            control_frame,
            text="No Sleeping",
            command=self.toggle_awake_screen,
            font=font.Font(family="Arial", size=14, weight="bold"),
            width=15, height=1,
            bg="#4CAF50", fg="white",
            relief=tk.RAISED, bd=3
        )
        self.control_btn.pack(side=tk.LEFT, padx=10, pady=10)

        # 自动停止复选框
        self.auto_stop_checkbox = ttk.Checkbutton(
            control_frame,
            text="running for hours:",
            variable=self.checkbox_var,
            onvalue=1,
            offvalue=0, 
            command=self.on_auto_stop_checkbox,
            state=tk.DISABLED
        )
        self.auto_stop_checkbox.pack(side=tk.LEFT)

        # 时间选择下拉框
        self.hours_combobox = ttk.Combobox(
            control_frame,
            textvariable=self.selected_hours,
            font=font.Font(family="Arial", size=12),
            values=[str(i) for i in range(1, 13)],
            state=tk.DISABLED,
            width=4
        )
        self.hours_combobox.pack(side=tk.LEFT, padx=10)

        # 绑定下拉框选择事件
        self.hours_combobox.bind("<<ComboboxSelected>>", self.on_hour_selected)


        
    def update_status_label(self):
        with self.lock:
            if not self.awake_screen_enabled:
                self.status_label.config(text="No sleeping is being disabled", fg="#666666")
                return

            if not self.checkbox_enabled:
                self.status_label.config(text="No sleeping is running now", fg="#d32f2f")
                return

            hours = int(self.remaining_time // 3600)
            minutes = int((self.remaining_time % 3600) // 60)
            seconds = int(self.remaining_time % 60)
            if self.checkbox_enabled:
                if hours == 0:
                    if minutes == 0:
                        self.status_label.config(
                            text=f"No sleeping will stop after {seconds}s",
                            fg="#1976D2"
                        )
                    else:
                        self.status_label.config(
                            text=f"No sleeping will stop after {minutes}m {seconds}s",
                            fg="#1976D2"
                        )
                else:
                    self.status_label.config(
                        text=f"No sleeping will stop after {hours}h {minutes}m {seconds}s",
                        fg="#1976D2"
                    )
            # if int(self.remaining_time % 2) == 0:
            #     logger.debug(f"status_label updated: {self.remaining_time} seconds left")
    
    # 复选框状态变化处理           
    def on_auto_stop_checkbox(self):
        with self.lock:
            self.checkbox_enabled = self.auto_stop_checkbox.instate(['selected'])
        logger.info(f"Auto stop checkbox state changed: {self.checkbox_enabled}")
        
        if self.checkbox_enabled:
            self.hours_combobox.config(state='readonly')
            if self.awake_screen_enabled:
                self.start_timer()
        else:
            self.hours_combobox.config(state='readonly')
            self.stop_timer()   # 强制清理残留timer线程

        self.root.after(0, self.update_status_label)
        self.update_tray_menu()

    # 下拉框选择事件处理
    def on_hour_selected(self, event=None):
        selected_hours = int(self.selected_hours.get())
        self.selected_hour = selected_hours # 同步更新托盘菜单状态
        total_seconds = selected_hours * self.time_unit
        logger.info(f"Selected {selected_hours} hours ({total_seconds} seconds)")
        
        with self.lock:
            self.remaining_time = total_seconds

        if self.checkbox_enabled and self.awake_screen_enabled:
            self.start_timer()

        self.root.after(0, self.update_status_label)
        self.update_tray_menu()
    
    # 启动/停止 No Sleeping 功能
    def toggle_awake_screen(self):
        with self.lock:
            self.awake_screen_enabled = not self.awake_screen_enabled
        logger.debug(f"Toggle awake_screen: {self.awake_screen_enabled}")
        # 更新按钮和状态标签
        if self.awake_screen_enabled: # 按下按钮时
            self.control_btn.config(text="No Sleeping", bg="#f44336")
            self.status_label.config(text="No sleeping is running now", fg="#d32f2f")
            self.auto_stop_checkbox.config(state='!disabled')
            self.checkbox_enabled = self.auto_stop_checkbox.instate(['selected'])
            logger.debug(f"Checkbox enabled: {self.checkbox_enabled}")
            self.hours_combobox.config(state='readonly')  # 下拉框可看
            if self.checkbox_enabled:
                self.start_timer()  # 自动启动倒计时
            logger.info("No Sleeping is running now")
        else: # 按钮取消时
            self.disable_awake_screen()
            logger.info("No Sleeping is being disabled")
            # self.control_btn.config(text="No sleeping", bg="#4CAF50")
            # self.status_label.config(text="No sleeping is being disabled", fg="#666666")
            # self.auto_stop_checkbox.config(state='disabled')
            # self.checkbox_enabled = False
            # self.hours_combobox.config(state='disabled')
            
            #self.stop_timer()  # 确保timer线程被清理
        
        self.root.after(0, self.update_status_label)
        self.update_tray_menu()

    # 维持屏幕唤醒的线程函数
    #@log_function_call
    def awake_screen(self):
        previous_enabled = False  # 初始化状态变量,用于判断按钮点按状态变化的

        while self.running:
            with self.lock:
                enabled = self.awake_screen_enabled

            # 检查状态是否发生变化
            if enabled != previous_enabled:
                if enabled:  # 状态由 False → True
                    try:
                        result = ctypes.windll.kernel32.SetThreadExecutionState(
                            ES_CONTINUOUS | 
                            ES_SYSTEM_REQUIRED | 
                            ES_DISPLAY_REQUIRED
                            )
                        if result == 0:
                            raise ctypes.WinError()
                        logger.debug("Win API SetThreadExecutionState called successfully")

                        # 更新 UI 状态
                        self.root.after(0, lambda: self.status_label.config(
                            text="No sleeping is running now", fg="#1976D2"))
                    except Exception as e:
                        logger.error(f"SetThreadExecutionState failed: {e}")
                        # 备用方案：移动鼠标
                        screen_width, screen_height = pyautogui.size()
                        x, y = pyautogui.position()
                        pyautogui.moveTo(x + 1, y)
                        logger.warning("Using pyautogui as fallback")

                else:  # 状态由 True → False
                    try:
                        result = ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
                        if result == 0:
                            raise ctypes.WinError()
                        logger.debug("Reset execution state to allow sleep")

                        # 更新 UI 状态
                        self.root.after(0, lambda: self.status_label.config(
                            text="No sleeping is being disabled", fg="#2E7D32"))
                    except Exception as e:
                        logger.error(f"Failed to reset execution state: {e}")
                    
                    self.stop_timer()  # 确保timer线程被清理

                # 更新 previous_enabled
                previous_enabled = enabled

            # 功能启用时，每 5 秒执行一次
            if enabled:
                time.sleep(5)
            else:
                time.sleep(1)  # 状态未启用时，降低 CPU 使用率

    @log_function_call
    def start_timer(self):
        """启动倒计时线程"""
        if not self.checkbox_enabled or not self.awake_screen_enabled:
            return
        
        # 先停止任何正在运行的 timer_thread
        if self.timer_thread and self.timer_thread.is_alive():
            logger.debug("Stopping existing timer thread before starting a new one")
            self.stop_timer()
        
        selected_hours = int(self.selected_hours.get())
        total_seconds = selected_hours * self.time_unit
        with self.lock: 
            self.remaining_time = total_seconds
            self.timer_active = True
        
        thread_name = f"TimerThread-{selected_hours}h"
        self.timer_thread = threading.Thread(target=self.run_timer, name=thread_name, daemon=True)
        self.timer_thread.start()
        logger.info(f"Timer started: {thread_name}")

    @log_function_call
    def run_timer(self):
        try:
            while True:
                with self.lock:
                    if not self.timer_active or not self.awake_screen_enabled or self.remaining_time <= 0:
                        break
                    current_time = self.remaining_time
                time.sleep(0.1)  # 更频繁检查状态变化
                
                with self.lock:
                    self.remaining_time = max(0, current_time - 0.1)
                
                # 仅在秒数变化时更新UI，减少UI更新频率
                if int(self.remaining_time) != int(current_time):
                    self.root.after(0, self.update_status_label)
            
            # 倒计时结束，自动关闭功能
            if self.remaining_time <= 0 and self.awake_screen_enabled:
                self.root.after(0, self.disable_awake_screen)
                logger.info("Timer ended, No Sleeping function is being disabled automatically")
        except Exception as e:
            logger.error(f"Timer thread error: {e}")
        finally:
            # run_timer 线程正常/异常退出后，强制清理残留timer线程
            self.stop_timer()

    @log_function_call
    def stop_timer(self):
        logger.debug("Stopping timer is running... ")
        #self.log_active_threads()  # 记录停止前状态

        with self.lock:
            self.timer_active = False

        try:
            # 处理timer_thread的异常退出
            if self.timer_thread and self.timer_thread.is_alive():
                self.timer_thread.join(timeout=0.5)  # 等待 0.5 秒（足够响应 0.1s sleep）

                if self.timer_thread.is_alive():
                    logger.warning(f"Timer thread {self.timer_thread.name} did not exit cleanly, forcing cleanup")

                else:
                    logger.debug(f"Timer thread {getattr(self.timer_thread, 'name', 'unknown')} exited safely")
        except Exception as e:
            logger.error(f"Error stopping timer thread: {e}")
        finally:
            self.timer_thread = None  # 确保引用被清理
            logger.info("ALL Timer has been stopped")    

        self.root.after(0, self.update_status_label)

        self.log_active_threads()  # 记录停止后状态
        logger.debug("Stop Timer done ✅")

    def log_active_threads(self):
        """记录当前所有活跃线程，特别标注 timer_thread"""
        active_threads = threading.enumerate()
        timer_threads = [t for t in active_threads if "TimerThread" in t.name]

        logger.debug(f"Total active threads: {len(active_threads)}")
        logger.debug(f"Active timer threads: {len(timer_threads)}")

        for thread in active_threads:
            if "TimerThread" in thread.name:
                logger.debug(f"  ⏱️  TIMER THREAD: {thread.name} (ID: {thread.ident})")
            else:
                logger.debug(f"     OTHER THREAD: {thread.name} (ID: {thread.ident})")
            
    @log_function_call
    def disable_awake_screen(self):
        with self.lock:
            if self.awake_screen_enabled:
                self.awake_screen_enabled = False
                self.checkbox_enabled = False
                self.timer_active = False

        self.control_btn.config(text="No Sleeping", bg="#4CAF50")
        self.status_label.config(text="No sleeping is being disabled", fg="#2E7D32")
        self.auto_stop_checkbox.config(state='disabled')
        self.hours_combobox.config(state='disabled')

        self.stop_timer()  # 确保timer线程被清理
        self.update_tray_menu()  # 更新托盘菜单

    def update_clock(self):
        now = datetime.datetime.now()
        time_str = now.strftime("%H:%M:%S")
        self.time_label.config(text=time_str)

        date_str = now.strftime("%Y-%m-%d")
        self.date_label.config(text=date_str)

        weekday_str = now.strftime("%A")
        self.weekday_label.config(text=weekday_str)

        # 更新阴历
        try:
            lunar = LunarDate.fromSolarDate(now.year, now.month, now.day)
            #logger.debug(f"year: {now.year}, month: {now.month}, day: {now.day}")
            lunar_month = self.number_to_chinese(lunar.month)
            lunar_day = self.number_to_chinese(lunar.day)
            lunar_str = f"农历: {lunar_month}月{lunar_day}日"
            self.lunar_label.config(text=lunar_str)
        except Exception as e:
            self.lunar_label.config(text="Lunar Calendar CANNOT LOAD...")

        # 每秒更新一次
        self.root.after(1000, self.update_clock)

    def number_to_chinese(self, num):
        chinese_num = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十",
                       "十一", "十二", "十三", "十四", "十五", "十六", "十七",
                       "十八", "十九", "二十", "廿一", "廿二", "廿三", "廿四",
                       "廿五", "廿六", "廿七", "廿八", "廿九", "三十"]
        #logger.debug(f"chinese num: {chinese_num}")
        return chinese_num[num - 1] if 1 <= num <= 30 else str(num)
    
    # 天气API调用（WeatherAPI.com）
    def update_weather(self):
        while self.running:
            try:
                # 获取当前城市
                self.current_city = self.get_city_from_ip()  # 获取IP对应的城市
                logger.debug(f"Current city: {self.current_city}")
                
                # 构造API请求
                url = f"https://api.weatherapi.com/v1/current.json?key={self.weather_api_key}&q={self.current_city}&lang=en"
                response = requests.get(url, timeout=5, verify=False)  # disabled SSL verify
                data = response.json()
                logger.debug(f"API returned data: {data}")

                if data.get("error"):
                    raise Exception(f"WeatherAPI Error: {data['error']['message']}")

                temp = data["current"]["temp_c"]  # 摄氏度
                condition = data["current"]["condition"]["text"]
                icon = data["current"]["condition"]["icon"]
                city = data["location"]["name"]

                # 更新UI（主线程安全）
                self.root.after(0, lambda t=temp, c=condition, i=icon, city=city:
                                self.update_weather_ui(t, c, i, city=city))

            except Exception:
                logger.exception("@_@")
                self.root.after(0, lambda: self.update_weather_ui(
                    "--", "faied to load", "❌"))

            # 天气信息更新的信息完成后返回之前的功能是否使用的状态
            if self.awake_screen_enabled:
                self.status_label.config(text="No sleeping is running now", fg="#d32f2f")
            else:
                self.status_label.config(text="No sleeping is being disabled", fg="#666666")
            
            # 每小时更新一次
            time.sleep(3600)

    def update_weather_ui(self, temp, condition, icon_url, city=""):
        self.weather_label.config(text=f"{city}: {condition} {temp}°C")

        # 补全URL
        full_icon_url = "https:" + icon_url

        # 下载天气图标
        response = requests.get(full_icon_url, timeout=5, verify=False)
        if response.status_code == 200:
            image_data = BytesIO(response.content)
            img = Image.open(image_data)
            img = img.resize((64, 64), Image.LANCZOS) # 调整图片大小
            photo = ImageTk.PhotoImage(img)
            
            # 关键：保持对 photo 的引用，否则会被回收清除
            self.weather_icon.image = photo
            self.weather_icon.config(image=photo)
            #logger.debug("weather icon downloaded")

    def get_city_from_ip(self):
        try:
            # 显示loading信息
            self.root.after(0, lambda: self.status_label.config(text="Loading weather based on IP..."))
            # 如果城市信息获取失败，则重试3次
            for _ in range(3):
                response = requests.get("https://ipinfo.io/json", timeout=5, verify=False)  # 另一个IPinfo地址API
                if response.status_code == 200:
                    data = response.json()
                    logger.debug(f"IP API returned data: {data}")
                    city = data["city"]
                    self.root.after(0, lambda city=city: self.status_label.config(text=f"Loading weather info from {city}..."))
                    return city
                else:
                    logger.warning(f"IP API response status code: {response.status_code} , retrying...")
                time.sleep(20)
            # 获取失败，使用默认城市
            logger.exception("Failed to get city from IP, using default city: shanghai")
            self.root.after(0, lambda: self.status_label.config(text="Cannot locate the city info, use the default city: Shanghai"))
            return self.current_city
        except Exception:
            logger.exception("Failed to get city from IP, using default city: shanghai")
            self.root.after(0, lambda: self.status_label.config(text="Cannot locate the city info, use the default city: Shanghai"))
            return self.current_city

    @log_function_call
    def create_tray_icon(self):
        """创建系统托盘图标"""
        logger.debug("Creating system tray icon")
        try:
            # 确保只创建一次
            if self.tray_icon_created:
                logger.debug("Tray icon already created")
                return
            
            try:
                image = Image.open(icon_path)
            except Exception:    
                # 图标文件读取失败后创建基础图标（使用更简单的图标）
                icon_size = 16  # 使用更小的尺寸
                image = Image.new('RGBA', (icon_size, icon_size), (0, 0, 0, 0))
                dc = ImageDraw.Draw(image)
                dc.rectangle((0, 0, icon_size-1, icon_size-1), outline="blue", fill="lightblue")
                dc.text((3, 2), "NS", fill="black")
            
            # TODO: The double click function is not working
            # 定义双击事件处理函数
            def on_double_click(icon, query):
                logger.debug("Tray icon double-click detected")
                self.restore_window()
            
            # 创建托盘菜单
            self.tray_menu = pystray.Menu(
                pystray.MenuItem(lambda text: "Stop" if self.awake_screen_enabled else "Start", self.toggle_awake_from_tray),
                pystray.MenuItem('Running hours', self.create_time_menu()),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem('Restore', self.restore_window),
                pystray.MenuItem('Quit', self.quit_app)
            )
            
            self.tray_icon = pystray.Icon(
                "NoSleepingClock",
                icon=image,
                title="No Sleeping Clock",
                menu=self.tray_menu
            )
            
            self.tray_icon.on_click = on_double_click
            
            # 启动托盘线程
            self.tray_thread = threading.Thread(target=self.run_tray_icon, daemon=True)
            self.tray_thread.start()
            
            self.tray_icon_created = True
            logger.info("System tray icon created successfully")
        except Exception as e:
            logger.error(f"Failed to create system tray icon: {e}")
            messagebox.showerror("Error", f"Failed to create system tray icon: {e}")

    def create_time_menu(self):
        """创建时间选项子菜单"""           
        def make_menu_item(h):
            self.selected_hour = int(self.selected_hours.get())
            def text_func(_):
                if self.awake_screen_enabled and self.checkbox_enabled and self.selected_hour == h:
                    return f"✓ {h}h"
                else:
                    return f"  {h}h"
                # prefix = "✓" if self.selected_hour == h else "  "
                # return f"{prefix} {h}h"
            return pystray.MenuItem(text_func, lambda _: self.set_time_option(h))
    
        return pystray.Menu(*(make_menu_item(h) for h in range(1, 13)))


    def set_time_option(self, hours):
        """设置时间选项并更新状态"""
        logger.info(f"Setting time option to {hours} hours")
        
        # 1. 更新状态
        self.selected_hour = hours
        self.selected_hours.set(str(hours))
        
        # 2. 同步主窗口状态
        with self.lock:
            self.checkbox_enabled = True  # 强制启用自动停止
            self.awake_screen_enabled = True  # 启动倒计时功能
        
        # 3. 更新主窗口状态
        self.control_btn.config(text="No Sleeping", bg="#f44336")
        self.status_label.config(text="No sleeping is running now", fg="#d32f2f")
        self.auto_stop_checkbox.config(state='!disabled')
        self.hours_combobox.config(state='readonly')  # 下拉框可看
        self.auto_stop_checkbox.state(['selected'])  # 勾选复选框
        
        self.on_hour_selected()  # 触发倒计时初始化
        
        # 4. 启动倒计时
        #self.start_timer()
        
        # 5. 刷新菜单显示
        self.update_tray_menu()
        
        logger.debug("Time option set complete")

    def update_tray_menu(self):
        """更新托盘菜单状态"""
        if self.tray_icon:
            # 重新创建整个菜单
            self.tray_menu = pystray.Menu(
                pystray.MenuItem(lambda text: "Stop" if self.awake_screen_enabled else "Start",self.toggle_awake_from_tray),
                pystray.MenuItem('Running hours', self.create_time_menu()),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem('Restore', self.restore_window),
                pystray.MenuItem('Quit', self.quit_app)
            )
            
            # 更新菜单
            self.tray_icon.menu = self.tray_menu
            self.tray_icon.update_menu()

    def run_tray_icon(self):
        """运行托盘图标"""
        try:
            if self.tray_icon:
                self.tray_icon.run()
        except Exception as e:
            logger.error(f"Tray icon run failed: {e}")


    def on_minimize(self):
        """处理窗口最小化操作"""
        logger.debug("Window is being minimized")
        self.minimized_to_tray = True
        self.root.withdraw()  # 隐藏主窗口
        
        # 确保创建托盘图标
        if not self.tray_icon_created:
            messagebox.showinfo("Minimize to Tray", "No Sleeping Clock is minimized to the Tray")   
            self.create_tray_icon()
        else:
            # 如果已创建，确保图标可见
            if self.tray_icon:
                self.tray_icon.visible = True
                
        return True  # 返回True表示已处理最小化事件

    def on_window_unmap(self, event):
        """处理窗口隐藏事件"""
        #pass
        if event.widget == self.root and not self.root.winfo_ismapped():
            logger.debug("Window is unmapped, triggering minimize handling")
            # 只有在未最小化到托盘的情况下才触发 on_minimize
            if not self.tray_icon_created:
                self.on_minimize()
            if not self.minimized_to_tray:
                self.on_minimize()
                
    def toggle_awake_from_tray(self):
        """通过托盘菜单切换No Sleeping状态"""
        logger.info("Toggle awake screen from tray menu")
        self.toggle_awake_screen()
        # 更新托盘菜单状态
        self.update_tray_menu()


    def quit_app(self):
        """退出应用程序"""
        logger.info("Quitting application through tray menu")
        self.on_close()

    def restore_window(self):
        """恢复窗口"""
        logger.info("Restoring window from system tray")
        self.root.deiconify()  # 显示主窗口
        self.root.lift()      # 置顶窗口
        self.root.focus_force()  # 聚焦窗口
        self.minimized_to_tray = False
        
        # 隐藏托盘图标（可选）
        # if self.tray_icon and self.tray_icon.visible:
        #     self.tray_icon.stop()  # 停止托盘图标
        #     self.tray_icon = None
        #     self.tray_icon_created = False

    # 窗口关闭：
    def on_close(self):
        """覆盖窗口关闭事件"""
        if messagebox.askokcancel("Quit", "Do you want to Quit the Window?"):
            with self.lock:
                self.running = False
                self.timer_active = False
            
            # 停止托盘图标
            if self.tray_icon and self.tray_icon.visible:
                try:
                    self.tray_icon.stop()
                except:
                    pass
            
            # 等待awake_thread线程结束
            if self.awake_thread and self.awake_thread.is_alive():
                self.awake_thread.join(timeout=2.0)
            # 处理timer线程
            self.stop_timer()

            self.root.destroy()


    # main函数
if __name__ == "__main__":
    try:
        root = tk.Tk()
        app = NoSleepingClock(root)
        root.mainloop()
    except Exception:
        logger.exception("OMG! Error Shows!")
        time.sleep(5)