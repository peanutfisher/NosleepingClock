# No Sleeping Clock

一个防止电脑进入睡眠状态的时钟程序，同时提供时间显示、农历日期、天气信息等功能。

## 功能特性

### 核心功能
- **防止系统睡眠**: 通过调用Windows API保持系统和显示器处于活跃状态
- **实时时间显示**: 显示当前时间、日期、星期和农历日期
- **天气信息**: 自动获取基于IP地址的城市天气信息
- **倒计时功能**: 可设置自动停止时间（1-12小时）
- **系统托盘**: 最小化到系统托盘，支持托盘菜单操作

### 界面功能
- 直观的图形用户界面
- 实时状态显示
- 可配置的自动停止选项
- 美观的UI设计和布局

## 技术实现

### 主要方法

#### 防止睡眠机制
程序使用Windows API `SetThreadExecutionState`来防止系统进入睡眠状态：

```python
ctypes.windll.kernel32.SetThreadExecutionState(
    ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
)
```
当功能关闭时，重置为默认状态：
```
ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
```
#### 多线程架构
程序采用多线程设计以确保UI响应性和功能独立性：

- 主UI线程: 处理GUI更新和用户交互
- 屏幕保持线程 (awake_screen): 定期调用Windows API防止睡眠
- 天气更新线程 (update_weather): 定期获取和更新天气信息
- 倒计时线程 (run_timer): 处理自动停止功能的倒计时
- 系统托盘线程 (run_tray_icon): 管理系统托盘图标和菜单
- 线程间通过threading.Lock进行同步，确保数据一致性。

#### 系统托盘集成
使用pystray库实现系统托盘功能：

- 最小化时自动隐藏到托盘
- 托盘菜单支持启动/停止、设置运行时间、恢复窗口和退出
- 双击托盘图标可恢复窗口
- 托盘菜单与主程序状态实时同步，提供一致的用户体验。

#### 天气信息获取
通过WeatherAPI服务获取天气数据：

- 使用ipinfo.io获取当前城市信息
- 调用api.weatherapi.com获取天气详情
- 支持图标显示和温度、天气状况展示

#### 状态管理
程序维护多个状态变量确保功能正确运行：

- awake_screen_enabled: 屏幕保持功能开关状态
- checkbox_enabled: 自动停止功能开关状态
- timer_active: 倒计时线程活动状态
- running: 程序整体运行状态

#### 线程安全
所有线程间共享的数据访问都通过threading.Lock进行保护，确保线程安全：

```python
with self.lock:
    enabled = self.awake_screen_enabled
```
#### 异常处理
程序包含全面的异常处理机制：

- API调用失败的备用方案（如使用pyautogui移动鼠标）
- 网络请求超时处理
- 线程安全的错误日志记录
- 用户友好的错误提示

#### 使用说明
- 运行程序后，点击"No Sleeping"按钮启动防睡眠功能
- 可选启用自动停止功能，设置运行时间（1-12小时）
- 程序会自动获取并显示天气信息
- 点击窗口关闭按钮或使用托盘菜单退出程序
- 最小化窗口时会自动隐藏到系统托盘

#### 依赖库
- tkinter: GUI界面
- pyautogui: 鼠标控制（备用方案）
- lunardate: 农历日期计算
- requests: 网络请求
- loguru: 日志记录
- PIL (Pillow): 图像处理
- pystray: 系统托盘
- ctypes: Windows API调用

#### 配置
程序支持以下配置：

- WeatherAPI密钥（用于天气信息获取）
- 默认城市（当IP定位失败时使用）
- 字体和界面样式设置

#### 日志记录
使用loguru库进行日志记录，便于调试和问题追踪。

#### 打包和部署
程序支持Nuitka打包为独立可执行文件，包含图标资源的正确路径处理。
打包命令如下：
```
python -m nuitka ^   --standalone ^    --onefile ^    --windows-console-mode=disable ^    --enable-plugin=tk-inter ^    --include-package=PIL ^   --include-package=pystray ^    --include-package=pyautogui ^    --include-package=requests ^    --include-package=loguru ^    --include-package=lunardate ^    --output-dir=dist ^    --output-filename=NoSleepingClock ^    --windows-icon-from-ico=ICON\NoSleepingClock.ico  ^  --include-data-file=./ICON/NoSleepingClock.ico=ICON/NoSleepingClock.ico ^  --nofollow-import-to=PIL.JpegImagePlugin ^ --jobs=8 ^  --prefer-source-code ^ NoSleepingClockV2.py
```