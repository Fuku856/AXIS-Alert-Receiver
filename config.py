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
    # CWD依存を避け、スクリプトと同じディレクトリに固定する
    CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config_dev.json")
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

_config_lock = threading.RLock()

def _load_config_unlocked():
    if not os.path.exists(CONFIG_FILE):
        return {"access_token": ""}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"access_token": ""}

def load_config():
    with _config_lock:
        return _load_config_unlocked()

def _save_config_unlocked(config_data):
    # 書き込み途中のクラッシュで設定(トークン含む)が破損しないよう、
    # 一時ファイルへ書き出してからアトミックに置き換える。
    tmp_path = CONFIG_FILE + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=4, ensure_ascii=False)
        os.replace(tmp_path, CONFIG_FILE)
    except Exception as e:
        print(f"Error saving config: {e}")
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass

def save_config(config_data):
    with _config_lock:
        _save_config_unlocked(config_data)

def _update_config(key, value):
    # 読み込みから書き込みまでを同一ロック内で行い、
    # UIスレッドと受信スレッドの同時保存による更新消失を防ぐ。
    with _config_lock:
        config_data = _load_config_unlocked()
        config_data[key] = value
        _save_config_unlocked(config_data)

# DPAPIで暗号化したトークンに付与する目印。平文と暗号文を確実に区別するために使う。
_DPAPI_PREFIX = "DPAPI:"

def encrypt_data(data_str):
    if not data_str:
        return data_str
    if not win32crypt:
        # DPAPIが使えない環境ではトークンが平文でディスクに保存される。
        # config.json流出時の露出リスクをユーザーへ知らせるため警告する。
        print("Warning: win32crypt is unavailable. The access token will be stored WITHOUT encryption.")
        return data_str
    try:
        data_bytes = data_str.encode('utf-8')
        encrypted_bytes = win32crypt.CryptProtectData(data_bytes, None, None, None, None, 0)
        return _DPAPI_PREFIX + base64.b64encode(encrypted_bytes).decode('utf-8')
    except Exception as e:
        print(f"Encryption error: {e}. The access token will be stored WITHOUT encryption.")
        return data_str

def decrypt_data(encrypted_b64):
    if not win32crypt or not encrypted_b64:
        return encrypted_b64
    # 新形式はDPAPIプレフィックス付き。旧形式(プレフィックスなし)も後方互換で復号を試みる。
    raw = encrypted_b64[len(_DPAPI_PREFIX):] if encrypted_b64.startswith(_DPAPI_PREFIX) else encrypted_b64
    try:
        encrypted_bytes = base64.b64decode(raw)
        _, decrypted_bytes = win32crypt.CryptUnprotectData(encrypted_bytes, None, None, None, 0)
        return decrypted_bytes.decode('utf-8')
    except Exception:
        # 暗号化されていない古い平文トークンなどの場合はそのまま返す
        return encrypted_b64

def is_token_encrypted():
    """保存中のトークンがDPAPIで暗号化されているかを返す(未設定時はTrue扱い)。"""
    token = load_config().get("access_token", "")
    if not token:
        return True
    return token.startswith(_DPAPI_PREFIX)

def get_token():
    token = load_config().get("access_token", "")
    # 復号後の前後空白を除去して返す(比較・送信時のブレを防ぐ)。
    return decrypt_data(token).strip()

def set_token(token):
    _update_config("access_token", encrypt_data(token))

def get_last_refresh():
    return load_config().get("last_refresh_time", 0.0)

def set_last_refresh(timestamp):
    _update_config("last_refresh_time", timestamp)

def get_channels():
    # デフォルトでbreaking-newsのみ有効とする
    return load_config().get("channels", ["breaking-news"])

def set_channels(channels_list):
    _update_config("channels", channels_list)

def get_show_popup():
    return load_config().get("show_popup", True)

def set_show_popup(show):
    _update_config("show_popup", show)

def get_check_update_on_startup():
    return load_config().get("check_update_on_startup", True)

def set_check_update_on_startup(check):
    _update_config("check_update_on_startup", check)

def get_auto_update_interval_days():
    return load_config().get("auto_update_interval_days", 1)

def set_auto_update_interval_days(days):
    _update_config("auto_update_interval_days", days)

def get_last_update_check_time():
    return load_config().get("last_update_check_time", "")

def set_last_update_check_time(time_str):
    _update_config("last_update_check_time", time_str)

def get_auto_open_log():
    return load_config().get("auto_open_log", False)

def set_auto_open_log(auto_open):
    _update_config("auto_open_log", auto_open)

def get_theme_mode():
    return load_config().get("theme_mode", "dark").lower()

def set_theme_mode(mode):
    _update_config("theme_mode", mode)

def get_popup_timeout():
    return load_config().get("popup_timeout", 10)

def set_popup_timeout(seconds):
    _update_config("popup_timeout", seconds)
