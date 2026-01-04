import psutil
import time
import pyautogui
import win32gui
import win32con
import win32api
import os
import configparser
import ctypes
import sys
import traceback
import logging

# 1. 告诉 pyautogui 找不到图片时返回 None，而不是崩溃报错
pyautogui.useImageNotFoundException(False)

# 2. 高分屏 DPI 兼容性处理
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    ctypes.windll.user32.SetProcessDPIAware()

# 3. 日志配置：同时输出到文件和控制台
def setup_logging():
    # 获取 exe 或脚本所在目录
    base_path = os.path.dirname(os.path.realpath(sys.executable if getattr(sys, 'frozen', False) else __file__))
    log_path = os.path.join(base_path, "running_log.txt")
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler(log_path, encoding='utf-8'), # 输出到文件
            logging.StreamHandler(sys.stdout)               # 输出到控制台
        ]
    )
    return logging.getLogger()

logger = setup_logging()

def set_autostart(enable=True):
    """设置或取消开机自启"""
    app_path = os.path.realpath(sys.executable)
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    app_name = "GameAccAutoStopper"

    try:
        key = win32api.RegOpenKeyEx(win32con.HKEY_CURRENT_USER, key_path, 0, win32con.KEY_ALL_ACCESS)
        if enable:
            win32api.RegSetValueEx(key, app_name, 0, win32con.REG_SZ, app_path)
            logger.info(f"✅ 已成功设置开机自启: {app_name}")
        else:
            try:
                win32api.RegDeleteValue(key, app_name)
                logger.info(f"🗑️ 已取消开机自启")
            except: pass
        win32api.RegCloseKey(key)
    except Exception as e:
        logger.error(f"❌ 设置自启失败: {e}")

def show_alert(message, title="自动暂停提醒"):
    ctypes.windll.user32.MessageBoxW(0, message, title, win32con.MB_ICONWARNING | win32con.MB_SETFOREGROUND)

def load_config():
    config = configparser.ConfigParser()
    # 兼容打包后的路径：配置文件应与 exe 在同一目录
    base_dir = os.path.dirname(os.path.realpath(sys.executable if getattr(sys, 'frozen', False) else __file__))
    config_path = os.path.join(base_dir, 'config.ini')
    
    if not os.path.exists(config_path):
        logger.error(f"❌ 找不到配置文件: {config_path}")
        return None
    try:
        config.read(config_path, encoding='utf-8')
        process_list = [p.strip() for p in config.get('Settings', 'game_processes').split(',')]
        strict_mode = config.get('Settings', 'strict_mode', fallback='false').lower() == 'true'
        
        return {
            'game_processes': process_list,
            'acc_title': config.get('Settings', 'acc_title'),
            'check_interval': config.getint('Settings', 'check_interval'),
            'strict_mode': strict_mode
        }
    except Exception as e:
        logger.error(f"❌ 解析配置文件出错: {e}")
        return None

def check_process_running(process_name):
    for proc in psutil.process_iter(['name']):
        try:
            if proc.info['name'].lower() == process_name.lower():
                return True
        except: continue
    return False

def check_any_game_running(process_list):
    for proc in psutil.process_iter(['name']):
        try:
            if proc.info['name'] in process_list:
                return True, proc.info['name']
        except: continue
    return False, None

def get_resource_path(relative_path):
    """处理 PyInstaller 打包后的资源路径"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

def find_and_wake_window(title_keyword):
    target_hwnd = None
    def enum_cb(hwnd, _):
        nonlocal target_hwnd
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title_keyword in title: target_hwnd = hwnd
    win32gui.EnumWindows(enum_cb, None)

    if target_hwnd:
        win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
        win32gui.ShowWindow(target_hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(target_hwnd)
        win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
        return True, target_hwnd
    return False, None

def run_auto_stopper():
    cfg = load_config()
    if not cfg: return

    process_list = cfg['game_processes']
    acc_title = cfg['acc_title']
    interval = cfg['check_interval']
    strict_mode = cfg['strict_mode']

    logger.info(f"【监控启动】模式: {'🔴 严格模式' if strict_mode else '🟢 自动模式'}")
    
    game_was_running = False
    current_running_game = None

    while True:
        try:
            is_running, game_name = check_any_game_running(process_list)

            if is_running and not game_was_running:
                logger.info(f">>> 游戏启动: {game_name}")
                game_was_running = True
                current_running_game = game_name
            
            elif not is_running and game_was_running:
                logger.info(f">>> 游戏 {current_running_game} 已退出！")
                time.sleep(3)

                if strict_mode and check_process_running("AK.exe"):
                    logger.warning("⚠️ 严格模式触发：暂停自动操作，执行弹窗。")
                    show_alert(f"检测到游戏【{current_running_game}】已关闭！\n请手动确认加速器计费状态。", "严格模式提醒")
                else:
                    found, hwnd = find_and_wake_window(acc_title)
                    if found:
                        time.sleep(1.5)
                        l, t, r, b = win32gui.GetWindowRect(hwnd)
                        win_region = (l, t, r - l, b - t)
                        
                        pause_img = get_resource_path('btn_action.png')
                        resume_img = get_resource_path('btn_verify2.png')
                        
                        btn_pos = pyautogui.locateCenterOnScreen(pause_img, confidence=0.8, region=win_region)
                        if btn_pos:
                            pyautogui.click(btn_pos)
                            logger.info("⚡ 已点击【暂停】，正在验证...")
                            time.sleep(4) 
                            
                            success_res = pyautogui.locateOnScreen(resume_img, confidence=0.95, region=win_region)
                            still_pause = pyautogui.locateOnScreen(pause_img, confidence=0.92, region=win_region)
                            
                            if success_res is not None:
                                logger.info("✅ 验证通过：加速器已暂停！")
                                win32gui.PostMessage(hwnd, win32con.WM_SYSCOMMAND, win32con.SC_MINIMIZE, 0)
                            elif still_pause is not None:
                                logger.error("⚠️ 验证失败：按钮状态未改变。")
                                show_alert("自动暂停似乎未生效！")
                            else:
                                logger.info("❓ 识别状态不明确（按钮可能已改变但未识别到新状态）。")
                        else:
                            logger.error("❌ 未定位到暂停按钮图片。")
                    else:
                        logger.error(f"❌ 未找到标题包含【{acc_title}】的窗口。")
                
                game_was_running = False
                current_running_game = None

            time.sleep(interval)
            
        except Exception:
            logger.error(f"运行异常详情:\n{traceback.format_exc()}")
            time.sleep(interval)

if __name__ == "__main__":
    set_autostart(True)
    run_auto_stopper()