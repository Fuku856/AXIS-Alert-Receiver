import os
import sys
from winotify import Notification

def get_app_path():
    """実行ファイルのパスまたはスクリプトのディレクトリを取得（アイコン指定などのため）"""
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))

def setup_shortcut(app_id, icon_path):
    """
    Windowsの仕様により、通知タイトル左のアプリアイコンを表示するには、
    スタートメニューにアイコン付きのショートカットが存在する必要があります。
    """
    if not icon_path or not os.path.exists(icon_path):
        return

    programs_path = os.path.join(os.environ["APPDATA"], "Microsoft", "Windows", "Start Menu", "Programs")
    shortcut_path = os.path.join(programs_path, f"{app_id}.lnk")
    
    # ターゲットパスの決定（exe化されている場合はそのexe、スクリプトの場合はpython.exe）
    target_path = sys.executable

    try:
        import pythoncom
        from win32com.shell import shell, shellcon
        from win32com.propsys import propsys, pscon
        
        pythoncom.CoInitialize()
        try:
            # IShellLinkオブジェクトの作成
            shell_link = pythoncom.CoCreateInstance(
                shell.CLSID_ShellLink, None,
                pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink
            )
            
            shell_link.SetPath(target_path)
            shell_link.SetIconLocation(icon_path, 0)
                
            # IPropertyStoreインターフェースの取得
            property_store = shell_link.QueryInterface(propsys.IID_IPropertyStore)
            
            # AppUserModelIDの設定
            property_key = propsys.PSGetPropertyKeyFromName("System.AppUserModel.ID")
            property_store.SetValue(property_key, app_id)
            property_store.Commit()
            
            # IPersistFileインターフェースを使って保存
            persist_file = shell_link.QueryInterface(pythoncom.IID_IPersistFile)
            persist_file.Save(shortcut_path, True)
            
        finally:
            pythoncom.CoUninitialize()
            
    except ImportError:
        print("pywin32 module is not available. Falling back to VBScript.")
        # pywin32がない場合はVBScript方式にフォールバック
        vbs_script = f"""
Set ws = WScript.CreateObject("WScript.Shell")
Set s = ws.CreateShortcut("{shortcut_path}")
s.TargetPath = "{target_path}"
s.IconLocation = "{icon_path}"
s.Save
"""
        vbs_path = os.path.join(os.environ["TEMP"], "axis_shortcut.vbs")
        try:
            with open(vbs_path, "w", encoding="utf-8") as f:
                f.write(vbs_script)
            os.system(f'cscript //nologo "{vbs_path}"')
        except Exception as e:
            print(f"Failed to create shortcut using VBScript: {e}")
            
    except Exception as e:
        print(f"Failed to create shortcut: {e}")

def show_toast(title, message, url=None):
    """
    Windowsのトースト通知を表示する。
    urlが指定されている場合は、通知クリック時にブラウザで開く。
    """
    try:
        # icon.ico が存在すれば絶対パスを取得
        icon_path = os.path.join(get_app_path(), "icon.ico")
        if not os.path.exists(icon_path):
            icon_path = None
            
        # 通知を送る前にショートカットをセットアップ（アイコンをOSに認識させる）
        app_id = "AXIS Alert Receiver"
        setup_shortcut(app_id, icon_path)

        toast = Notification(
            app_id=app_id,
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
