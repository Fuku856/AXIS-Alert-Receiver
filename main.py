import os
import sys
import threading
import ctypes

import pystray
from PIL import Image, ImageDraw, UnidentifiedImageError

import ui_manager
import axis_client
import config

APP_ID = "AXIS Alert Receiver"

# プロセスのAUMID（AppUserModelID）を設定（トースト通知のアイコン表示とタスクバーのグループ化に必要）
if sys.platform == "win32":
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass

def create_image():
    # icon.ico を探す候補パスを定義
    
    icon_paths = []
    
    if getattr(sys, 'frozen', False):
        # 1. 実行可能ファイルと同じディレクトリ (インストーラーで {app} に配置されたものなど)
        exe_dir = os.path.dirname(sys.executable)
        icon_paths.append(os.path.join(exe_dir, "icon.ico"))
        
        # 2. PyInstallerの一時展開先ディレクトリ (sys._MEIPASS)
        if hasattr(sys, '_MEIPASS'):
            icon_paths.append(os.path.join(sys._MEIPASS, 'icon.ico'))
    else:
        # 3. 開発環境 (スクリプトと同じディレクトリ)
        script_dir = os.path.dirname(os.path.abspath(__file__))
        icon_paths.append(os.path.join(script_dir, "icon.ico"))
    
    # 最初に見つかった有効なアイコンを読み込む
    for icon_path in icon_paths:
        if os.path.exists(icon_path):
            try:
                with Image.open(icon_path) as img:
                    return img.copy()
            except (UnidentifiedImageError, OSError):
                pass

    # 見つからない場合は動的アイコンを生成 (64x64の青い四角形にAの文字)
    image = Image.new('RGBA', (64, 64), color=(0, 122, 204, 255))
    dc = ImageDraw.Draw(image)
    dc.text((20, 20), "A", fill=(255, 255, 255, 255))
    return image

def setup_tray(ui, client):
    def on_show_log(icon, item):
        ui.show_log_window()

    def on_show_settings(icon, item):
        ui.show_settings_window()

    def on_quit(icon, item):
        client.stop()
        icon.stop()
        ui.quit()

    menu = pystray.Menu(
        pystray.MenuItem("ログを表示", on_show_log, default=True),
        pystray.MenuItem("設定", on_show_settings),
        pystray.MenuItem("終了", on_quit)
    )

    icon = pystray.Icon("AXIS-Alert-Receiver", create_image(), "AXIS Alert Receiver", menu)
    return icon

def main():
    # axis_clientは初期化時にコールバックを要求するので、
    # 循環参照を避けるためにui_managerを先に作成し、ダミーコールバックを渡す
    
    # 後からコールバックをセットするためのリストハック
    callbacks = {"on_message": None, "on_status": None}
    
    def on_message(channel, data):
        if callbacks["on_message"]:
            callbacks["on_message"](channel, data)

    def on_status(status):
        if callbacks["on_status"]:
            callbacks["on_status"](status)

    client = axis_client.AxisClient(on_message, on_status)
    ui = ui_manager.UIManager(client)
    
    # 実際のコールバックをバインド
    callbacks["on_message"] = ui.append_log
    callbacks["on_status"] = ui.update_status

    # クライアントの開始（バックグラウンドスレッド）
    client.start()

    # トレイアイコンのセットアップと開始（バックグラウンドスレッド）
    icon = setup_tray(ui, client)
    threading.Thread(target=icon.run, daemon=True).start()

    # 初回起動時にトークンがなければ設定画面を出す
    if not config.get_token():
        ui.root.after(500, ui.show_settings_window)

    # UIのメインループ開始（メインスレッドをブロック）
    try:
        ui.mainloop()
    except KeyboardInterrupt:
        client.stop()
        icon.stop()
        sys.exit(0)

if __name__ == "__main__":
    main()
