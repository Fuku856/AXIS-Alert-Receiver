import json
import os
import threading
import keyring

KEYRING_SERVICE_NAME = "AXIS_Breaking_News"
KEYRING_ACCOUNT_NAME = "access_token"

CONFIG_FILE = "config.json"
_config_lock = threading.Lock()

def load_config():
    with _config_lock:
        if not os.path.exists(CONFIG_FILE):
            return {}
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

def save_config(config_data):
    with _config_lock:
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving config: {e}")

def get_token():
    try:
        token = keyring.get_password(KEYRING_SERVICE_NAME, KEYRING_ACCOUNT_NAME)
        return token if token is not None else ""
    except Exception as e:
        print(f"Error getting token from keyring: {e}")
        return ""

def set_token(token):
    try:
        if token:
            keyring.set_password(KEYRING_SERVICE_NAME, KEYRING_ACCOUNT_NAME, token)
        else:
            try:
                keyring.delete_password(KEYRING_SERVICE_NAME, KEYRING_ACCOUNT_NAME)
            except keyring.errors.PasswordDeleteError:
                pass
    except Exception as e:
        print(f"Error setting token to keyring: {e}")

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
