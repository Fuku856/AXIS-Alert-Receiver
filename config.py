import json
import os
import sys
import threading
import base64

try:
    import win32crypt   
except ImportError:
    win32crypt = None

APP_NAME = "AXIS Alert Receiver"
APP_VERSION = "dev"
REPO_URL = "https://github.com/Fuku856/AXIS-Alert-Receiver"
def get_config_dir():
    app_data = os.environ.get('APPDATA')
    if not app_data:
        app_data = os.path.expanduser('~')
    app_dir = os.path.join(app_data, 'AXIS-Alert-Receiver')
    if not os.path.exists(app_dir):
        os.makedirs(app_dir)
    return app_dir

CONFIG_FILE = os.path.join(get_config_dir(), "config.json")

if APP_VERSION.lower() in ("dev", "vdev"):
    CONFIG_FILE = os.path.abspath("config_dev.json")
    # 起動時に前回のファイルが残っていればリセット（削除）する
    if os.path.exists(CONFIG_FILE):
        try:
            os.remove(CONFIG_FILE)
        except Exception:
            pass
            
    import atexit
    def cleanup_dev_config():
        if os.path.exists(CONFIG_FILE):
            try:
                os.remove(CONFIG_FILE)
            except Exception:
                pass
    atexit.register(cleanup_dev_config)

_config_lock = threading.Lock()

def load_config():
    with _config_lock:
        if not os.path.exists(CONFIG_FILE):
            return {"access_token": ""}
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"access_token": ""}

def save_config(config_data):
    with _config_lock:
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving config: {e}")

def encrypt_data(data_str):
    if not win32crypt or not data_str:
        return data_str
    try:
        data_bytes = data_str.encode('utf-8')
        encrypted_bytes = win32crypt.CryptProtectData(data_bytes, None, None, None, None, 0)
        return base64.b64encode(encrypted_bytes).decode('utf-8')
    except Exception as e:
        print(f"Encryption error: {e}")
        return data_str

def decrypt_data(encrypted_b64):
    if not win32crypt or not encrypted_b64:
        return encrypted_b64
    try:
        encrypted_bytes = base64.b64decode(encrypted_b64)
        _, decrypted_bytes = win32crypt.CryptUnprotectData(encrypted_bytes, None, None, None, 0)
        return decrypted_bytes.decode('utf-8')
    except Exception:
        # 暗号化されていない古い平文トークンなどの場合はそのまま返す
        return encrypted_b64

def get_token():
    token = load_config().get("access_token", "")
    return decrypt_data(token)

def set_token(token):
    config = load_config()
    config["access_token"] = encrypt_data(token)
    save_config(config)

def get_last_refresh():
    return load_config().get("last_refresh_time", 0.0)

def set_last_refresh(timestamp):
    config = load_config()
    config["last_refresh_time"] = timestamp
    save_config(config)

def get_channels():
    # デフォルトでbreaking-newsのみ有効とする
    return load_config().get("channels", ["breaking-news"])

def set_channels(channels_list):
    config = load_config()
    config["channels"] = channels_list
    save_config(config)

def get_show_popup():
    return load_config().get("show_popup", True)

def set_show_popup(show):
    config = load_config()
    config["show_popup"] = show
    save_config(config)

def get_check_update_on_startup():
    return load_config().get("check_update_on_startup", True)

def set_check_update_on_startup(check):
    config = load_config()
    config["check_update_on_startup"] = check
    save_config(config)

def get_auto_update_interval_days():
    return load_config().get("auto_update_interval_days", 1)

def set_auto_update_interval_days(days):
    config = load_config()
    config["auto_update_interval_days"] = days
    save_config(config)

def get_last_update_check_time():
    return load_config().get("last_update_check_time", "")

def set_last_update_check_time(time_str):
    config = load_config()
    config["last_update_check_time"] = time_str
    save_config(config)

def get_auto_open_log():
    return load_config().get("auto_open_log", False)

def set_auto_open_log(auto_open):
    config = load_config()
    config["auto_open_log"] = auto_open
    save_config(config)

