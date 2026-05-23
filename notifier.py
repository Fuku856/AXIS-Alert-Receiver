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
        # icon.ico が存在すれば絶対パスを取得
        icon_path = os.path.join(get_app_path(), "icon.ico")
        if not os.path.exists(icon_path):
            icon_path = ""
            
        app_id = "AXIS Alert Receiver"

        toast = Notification(
            app_id=app_id,
            title=title,
            msg=message,
            icon=icon_path,
            duration="long"
        )
        if url:
            toast.add_actions(label="詳細を見る", launch=url)
            
            # winotifyでは、通知自体のクリックアクション（launchパラメータ）を
            # Notificationクラスのコンストラクタで指定できないため、アクションボタンで対応する。
            toast.launch = url

        # winotifyが内部で実行する powershell.exe が環境変数 PATH に無いと [WinError 2] が発生するため、補完する
        powershell_dir = r"C:\Windows\System32\WindowsPowerShell\v1.0"
        if powershell_dir.lower() not in os.environ.get("PATH", "").lower():
            os.environ["PATH"] += os.pathsep + powershell_dir

        toast.show()
    except Exception as e:
        error_msg = f"Failed to show toast notification: {e}"
        print(error_msg)
        # エラー原因特定のためログファイルに書き出す
        try:
            import config
            log_path = os.path.join(config.get_config_dir(), "notification_error.log")
            with open(log_path, "a", encoding="utf-8") as f:
                import datetime
                now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                f.write(f"[{now}] {error_msg}\n")
        except:
            pass
