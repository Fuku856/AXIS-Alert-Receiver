import os
import sys
import threading
import ctypes

from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PySide6.QtGui import QIcon, QPixmap, QColor, QPainter
from PySide6.QtCore import Qt, QTimer

import ui_manager
import axis_client
import config

APP_ID = config.APP_NAME

# プロセスのAUMID（AppUserModelID）を設定（トースト通知のアイコン表示とタスクバーのグループ化に必要）
if sys.platform == "win32":
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass

def create_fallback_icon():
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor(0, 122, 204))
    painter = QPainter(pixmap)
    painter.setPen(QColor(255, 255, 255))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "A")
    painter.end()
    return QIcon(pixmap)

def get_app_icon():
    icon_paths = []
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        icon_paths.append(os.path.join(exe_dir, "icon.ico"))
        if hasattr(sys, '_MEIPASS'):
            icon_paths.append(os.path.join(sys._MEIPASS, 'icon.ico'))
    else:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        icon_paths.append(os.path.join(script_dir, "icon.ico"))
    
    for icon_path in icon_paths:
        if os.path.exists(icon_path):
            return QIcon(icon_path)
            
    return create_fallback_icon()

def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False) # トレイアイコンで動作するため、ウィンドウを閉じても終了しない
    
    # 循環参照を避けるためのコールバックハック
    callbacks = {"on_message": None, "on_status": None}
    
    def on_message(channel, data):
        if callbacks["on_message"]:
            callbacks["on_message"](channel, data)

    def on_status(status):
        if callbacks["on_status"]:
            callbacks["on_status"](status)

    client = axis_client.AxisClient(on_message, on_status)
    ui = ui_manager.UIManager(client, app)
    
    # 実際のコールバックをバインド
    callbacks["on_message"] = ui.append_log
    callbacks["on_status"] = ui.update_status

    # トレイアイコンのセットアップ
    tray_icon = QSystemTrayIcon(get_app_icon(), app)
    tray_icon.setToolTip(config.APP_NAME)
    ui.tray_icon_update_requested.connect(tray_icon.setIcon)
    tray_icon.setIcon(ui._generate_status_icon("オフライン"))
    
    menu = QMenu()
    
    action_log = menu.addAction("ログを表示")
    action_log.triggered.connect(ui.show_log_window)
    
    action_settings = menu.addAction("設定")
    action_settings.triggered.connect(ui.show_settings_window)
    
    action_quit = menu.addAction("終了")
    def on_quit():
        # トースト表示中にquitするとイベントループ終了が失われることがあるため先に破棄する
        ui.popup_manager.close_all_immediately()
        client.stop()
        tray_icon.hide()
        app.quit()
    action_quit.triggered.connect(on_quit)
    
    tray_icon.setContextMenu(menu)
    tray_icon.show()
    
    def tray_activated(reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            ui.show_log_window()
            
    tray_icon.activated.connect(tray_activated)

    # クライアントの開始（バックグラウンドスレッド）
    client.start()

    # 初回起動時にトークンがなければ設定画面を出す
    if not config.get_token():
        QTimer.singleShot(500, ui.show_settings_window)

    # UIのメインループ開始
    try:
        sys.exit(app.exec())
    except KeyboardInterrupt:
        ui.popup_manager.close_all_immediately()
        client.stop()
        tray_icon.hide()
        sys.exit(0)

if __name__ == "__main__":
    main()
