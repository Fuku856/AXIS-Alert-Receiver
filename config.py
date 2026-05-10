import json
import os
import threading

CONFIG_FILE = "config.json"
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

def get_token():
    return load_config().get("access_token", "")

def set_token(token):
    config = load_config()
    config["access_token"] = token
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

