import os
import sys
from winotify import Notification

def get_app_path():
    """実行ファイルのパスまたはスクリプトのディレクトリを取得（アイコン指定などのため）"""
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))

def show_toast(title, message, url=None):
    """
    Windowsのトースト通知を表示する。
    urlが指定されている場合は、通知クリック時にブラウザで開く。
    """
    try:
        toast = Notification(
            app_id="AXIS Alert Receiver",
            title=title,
            msg=message,
            duration="long"
        )
        if url:
            toast.add_actions(label="詳細を見る", launch=url)
            
            # winotifyでは、通知自体のクリックアクション（launchパラメータ）を
            # Notificationクラスのコンストラクタで指定できないため、アクションボタンで対応する。
            toast.launch = url

        toast.show()
    except Exception as e:
        print(f"Failed to show toast notification: {e}")
