import tkinter as tk
from tkinter import scrolledtext, ttk, messagebox
import config
from datetime import datetime
import json
import notifier
import message_formatter
import difflib
import webbrowser
import os
import sys
import base64
import urllib.request
import threading
import re
import uuid

class UIManager:
    def __init__(self, axis_client):
        self.client = axis_client
        self.root = tk.Tk()
        self.root.withdraw() # メインウィンドウは非表示
        self.root.protocol("WM_DELETE_WINDOW", self.hide_log_window) # 閉じるボタンで非表示

        # ポップアップ管理用辞書: event_id -> {"window": Toplevel, "text_widget": ScrolledText, "last_body": str, "title_label": tk.Label}
        self.active_popups = {}

        # アプリアイコンの設定
        def get_app_path():
            if getattr(sys, 'frozen', False):
                exe_dir = os.path.dirname(sys.executable)
                if os.path.exists(os.path.join(exe_dir, "icon.ico")) or os.path.exists(os.path.join(exe_dir, "icon.png")):
                    return exe_dir
                if hasattr(sys, '_MEIPASS'):
                    return sys._MEIPASS
            return os.path.dirname(os.path.abspath(__file__))
            
        icon_path_ico = os.path.join(get_app_path(), "icon.ico")
        icon_path_png = os.path.join(get_app_path(), "icon.png")
        if os.path.exists(icon_path_ico):
            try:
                self.root.iconbitmap(default=icon_path_ico)
            except Exception as e:
                print(f"Failed to load .ico for UI: {e}")
        elif os.path.exists(icon_path_png):
            try:
                self.icon_photo = tk.PhotoImage(file=icon_path_png)
                self.root.iconphoto(True, self.icon_photo) # Trueで全てのToplevelに適用
            except Exception as e:
                print(f"Failed to load .png for UI: {e}")

        # ログウィンドウの作成
        self.log_window = tk.Toplevel(self.root)
        self.log_window.title(f"{config.APP_NAME} - ログ")
        self.log_window.geometry("600x400")
        self.log_window.protocol("WM_DELETE_WINDOW", self.hide_log_window)
        self.log_window.withdraw() # 初期は非表示

        self.text_area = scrolledtext.ScrolledText(self.log_window, state='disabled', wrap='word')
        self.text_area.pack(expand=True, fill='both', padx=5, pady=5)

        # 設定ダイアログの作成
        self.settings_window = None

        self.is_latest_version = None
        self._update_info_fetched = False
        self.root.after(1000, lambda: self.start_background_update_checker(is_startup=True))

    def append_log(self, channel, message_data):
        def _update():
            self.text_area.configure(state='normal')
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            if channel == "システム":
                text = f"[{timestamp}] [システム] {message_data}\n"
                title = "システム通知"
                body = message_data
                url = None
            elif channel == "パースエラー":
                text = f"[{timestamp}] [エラー] {message_data}\n"
                title = "エラー"
                body = message_data
                url = None
            else:
                # 実際のbreaking-newsデータ
                event_id, title, body = message_formatter.format_message(channel, message_data)
                url = message_data.get("url", None)
                text = f"[{timestamp}] [{channel}]\n{title}\n{body}\n"
                if url:
                    text += f"URL: {url}\n"
                text += "-" * 40 + "\n"
                
                # トースト通知も出す (トーストには短い概要を出す)
                notifier.show_toast(title, f"新しい情報を受信しました\n受信: {timestamp}", url)
                
                # 自動的にログウィンドウを表示
                if config.get_auto_open_log():
                    self.show_log_window()
                
                # さらに目立つように専用のポップアップも出す
                if config.get_show_popup():
                    self.show_alert_popup(event_id, title, body, url, timestamp)

            self.text_area.insert(tk.END, text)
            self.text_area.configure(state='disabled')
            self.text_area.yview(tk.END)
            
        self.root.after(0, _update)

    def update_status(self, status):
        def _update():
            try:
                if self.settings_window and self.settings_window.winfo_exists():
                    if hasattr(self, 'status_label') and self.status_label.winfo_exists():
                        self.status_label.config(text=f"状態: {status}")
            except tk.TclError:
                pass
            except Exception:
                pass
        self.root.after(0, _update)

    def show_log_window(self):
        self.log_window.deiconify()
        self.log_window.lift()

    def hide_log_window(self):
        self.log_window.withdraw()

    def show_alert_popup(self, event_id, title, body, url, timestamp=None):
        # 既に同じイベントのウィンドウが開いているかチェック
        if event_id in self.active_popups:
            popup_data = self.active_popups[event_id]
            alert = popup_data.get("window")
            if alert and alert.winfo_exists():
                # ウィンドウがまだ開いているので差分更新する
                text_widget = popup_data.get("text_widget")
                last_body = popup_data.get("last_body", "")
                
                alert.lift()
                alert.title("【更新】" + title)
                
                title_label = popup_data.get("title_label")
                if title_label and title_label.winfo_exists():
                    title_label.config(text=title)

                time_label = popup_data.get("time_label")
                if time_label and time_label.winfo_exists() and timestamp:
                    time_label.config(text=f"更新: {timestamp}")

                # URLの更新とボタンの表示状態の同期
                popup_data["current_url"] = url
                url_button = popup_data.get("url_button")
                if url_button and url_button.winfo_exists():
                    if url:
                        url_button.pack(side="top", pady=(5, 0))
                    else:
                        url_button.pack_forget()

                text_widget.configure(state='normal')
                text_widget.delete("1.0", tk.END)
                
                # difflibで差分をとってハイライト
                diff = list(difflib.ndiff(last_body.splitlines(), body.splitlines()))
                for line in diff:
                    if line.startswith('+ '):
                        text_widget.insert(tk.END, line[2:] + "\n", "added")
                    elif line.startswith('- '):
                        # 削除された行は表示しない
                        pass
                    elif line.startswith('? '):
                        pass
                    else:
                        text_widget.insert(tk.END, line[2:] + "\n")
                
                text_widget.configure(state='disabled')
                text_widget.yview(tk.END) # 最新部分が見えるようにスクロール
                
                self.root.bell()
                self.active_popups[event_id]["last_body"] = body
                return
            else:
                # 閉じられていたら辞書から削除
                del self.active_popups[event_id]

        # 新規ウィンドウ作成
        alert = tk.Toplevel(self.root)
        alert.title("【速報】" + title)
        alert.geometry("650x500")
        alert.attributes("-topmost", True) # 常に最前面
        
        def on_close():
            if event_id in self.active_popups:
                del self.active_popups[event_id]
            alert.destroy()
            
        alert.protocol("WM_DELETE_WINDOW", on_close)
        
        # ヘッダー領域 (右上に日時)
        header_frame = tk.Frame(alert)
        header_frame.pack(fill="x", padx=10, pady=(5, 0))
        
        time_label = tk.Label(header_frame, text=f"受信: {timestamp}" if timestamp else "", font=("Helvetica", 9), fg="gray")
        time_label.pack(side="right")
        
        # タイトル表示
        title_label = tk.Label(alert, text=title, font=("Helvetica", 14, "bold"), fg="red", wraplength=600)
        title_label.pack(pady=(0, 10))
        
        # 先にボタン領域を下部 (side="bottom") に確保して見切れを防ぐ
        button_frame = ttk.Frame(alert)
        button_frame.pack(side="bottom", fill="x", pady=(0, 10))

        def open_url():
            if event_id in self.active_popups:
                current_url = self.active_popups[event_id].get("current_url")
                if current_url:
                    webbrowser.open(current_url)

        url_button = ttk.Button(button_frame, text="ブラウザで詳細を開く", command=open_url)
        if url:
            url_button.pack(side="top", pady=(5, 0))
            
        close_btn = ttk.Button(button_frame, text="閉じる", command=on_close)
        close_btn.pack(side="top", pady=5)

        # 本文表示 (ScrolledText) - 残りの領域をすべて使用する
        text_frame = ttk.Frame(alert)
        text_frame.pack(side="top", pady=5, padx=10, fill="both", expand=True)
        
        text_widget = scrolledtext.ScrolledText(text_frame, wrap='word', font=("Consolas", 10))
        text_widget.pack(fill="both", expand=True)
        
        # ハイライト用のタグ設定
        text_widget.tag_config("added", background="#e6ffe6", foreground="#006600", font=("Consolas", 10, "bold"))
        
        text_widget.insert(tk.END, body)
        text_widget.configure(state='disabled')
        
        alert.bind("<Escape>", lambda e: on_close())
        
        # 管理用辞書に登録
        self.active_popups[event_id] = {
            "window": alert,
            "text_widget": text_widget,
            "title_label": title_label,
            "time_label": time_label,
            "url_button": url_button,
            "current_url": url,
            "last_body": body
        }
        
        self.root.bell()

    def show_settings_window(self):
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.lift()
            return

        self.settings_window = tk.Toplevel(self.root)
        self.settings_window.title(f"設定 - {config.APP_NAME}")
        self.settings_window.minsize(500, 350)

        # タブコントロールの作成
        notebook = ttk.Notebook(self.settings_window, takefocus=False)
        notebook.pack(expand=True, fill='both', padx=10, pady=10)

        def on_tab_changed(event):
            try:
                if self.settings_window and self.settings_window.winfo_exists():
                    self.settings_window.focus_set()
                    if hasattr(self, 'token_entry') and self.token_entry.winfo_exists():
                        self.token_entry.select_clear()
                        
                    notebook = event.widget
                    try:
                        if hasattr(self, 'tab_updates') and notebook.select() == str(self.tab_updates):
                            if not getattr(self, '_update_info_fetched', False):
                                if config.APP_VERSION.lower() in ("dev", "vdev"):
                                    self._update_release_info("スキップ", "開発バージョンのため、自動取得をスキップしました。")
                                else:
                                    self.check_for_updates()
                    except Exception:
                        pass
            except tk.TclError:
                pass
            except Exception:
                pass
                
        notebook.bind("<<NotebookTabChanged>>", on_tab_changed)

        # --- タブ1: AXISトークン ---
        tab_connection = ttk.Frame(notebook)
        notebook.add(tab_connection, text='AXISトークン')

        ttk.Label(tab_connection, text="AXIS アクセストークン (JWT):").pack(pady=(15, 5), padx=10, anchor='w')
        self.token_entry = ttk.Entry(tab_connection, width=50)
        self.token_entry.pack(pady=5, padx=10)
        self.token_entry.insert(0, config.get_token())

        self.status_label = ttk.Label(tab_connection, text=f"状態: {self.client.status}")
        self.status_label.pack(pady=20, padx=10, anchor='w')

        # --- タブ2: チャンネル設定 ---
        tab_channels = ttk.Frame(notebook)
        notebook.add(tab_channels, text='チャンネル設定')

        ttk.Label(tab_channels, text="受信するチャンネル:").pack(pady=(15, 5), padx=10, anchor='w')
        
        self.channel_vars = {}
        self.channel_widgets = {}
        self.channel_labels = {}
        # チャンネルリストを message_formatter から取得するように一元管理化
        channels = list(message_formatter.CHANNEL_TITLES.keys())
        saved_channels = config.get_channels()

        channels_frame = ttk.Frame(tab_channels)
        channels_frame.pack(padx=20, anchor='w')
        
        for ch in channels:
            var = tk.BooleanVar(value=(ch in saved_channels))
            
            chk = ttk.Checkbutton(channels_frame, text=ch, variable=var, takefocus=False)
            chk.pack(anchor='w', pady=(5, 0) if ch == channels[0] else (2, 0))
            
            # message_formatterから公式のジャンル説明文を取得して改行対応のラベルとして追加
            genre = getattr(message_formatter, "CHANNEL_DESCRIPTIONS", {}).get(ch, message_formatter.CHANNEL_TITLES.get(ch, ""))
            if genre:
                # wraplengthは動的に調整するため、ここでは指定しないか仮値を置く
                desc_lbl = ttk.Label(channels_frame, text=genre, font=("Helvetica", 8), foreground="#555555")
                desc_lbl.pack(anchor='w', padx=(20, 0), pady=(0, 5))
                self.channel_labels[ch] = desc_lbl

            self.channel_vars[ch] = var
            self.channel_widgets[ch] = chk

        # レスポンシブな折り返し幅の調整
        def on_configure(event):
            # パディングを考慮して折り返し幅を計算
            new_wraplength = event.width - 60
            if new_wraplength > 0:
                for lbl in self.channel_labels.values():
                    lbl.configure(wraplength=new_wraplength)
        
        tab_channels.bind("<Configure>", on_configure)

        note_text = "グレーアウトされているチャンネルは、\n設定されているAXISトークンで購読されていません。"
        ttk.Label(tab_channels, text=note_text, font=("Helvetica", 8), foreground="gray").pack(pady=(10, 0), padx=20, anchor='w')

        # --- タブ3: UI設定 ---
        tab_ui = ttk.Frame(notebook)
        notebook.add(tab_ui, text='UI設定')

        ttk.Label(tab_ui, text="通知設定:").pack(pady=(15, 5), padx=10, anchor='w')

        self.show_popup_var = tk.BooleanVar(value=config.get_show_popup())
        popup_chk = ttk.Checkbutton(tab_ui, text="受信時にポップアップウィンドウを表示する", variable=self.show_popup_var, takefocus=False)
        popup_chk.pack(pady=5, padx=20, anchor='w')

        self.auto_open_log_var = tk.BooleanVar(value=config.get_auto_open_log())
        auto_open_log_chk = ttk.Checkbutton(tab_ui, text="受信時にログ画面を自動表示する", variable=self.auto_open_log_var, takefocus=False)
        auto_open_log_chk.pack(pady=5, padx=20, anchor='w')

        ttk.Label(tab_ui, text="更新設定:").pack(pady=(15, 5), padx=10, anchor='w')
        
        self.check_startup_var = tk.BooleanVar(value=config.get_check_update_on_startup())
        startup_chk = ttk.Checkbutton(tab_ui, text="起動時に最新バージョンの更新を確認する", variable=self.check_startup_var, takefocus=False)
        startup_chk.pack(pady=5, padx=20, anchor='w')

        interval_frame = ttk.Frame(tab_ui)
        interval_frame.pack(pady=5, padx=20, anchor='w')
        ttk.Label(interval_frame, text="定期的に更新を確認する間隔:").pack(side='left', padx=(0, 10))
        
        self.interval_var = tk.StringVar()
        interval_options = {"確認しない": 0, "1日おき": 1, "3日おき": 3, "7日おき": 7, "30日おき": 30}
        current_interval = config.get_auto_update_interval_days()
        current_text = next((k for k, v in interval_options.items() if v == current_interval), "1日おき")
        self.interval_var.set(current_text)
        
        interval_combo = ttk.Combobox(interval_frame, textvariable=self.interval_var, values=list(interval_options.keys()), state="readonly", width=10)
        interval_combo.pack(side='left')
        self.interval_options = interval_options

        # トークン入力時にリアルタイムでチェックボックスの状態を更新する
        self.token_entry.bind("<KeyRelease>", self.update_checkboxes_state)
        # 初期状態の反映
        self.update_checkboxes_state()

        # --- タブ4: アプリについて ---
        tab_about = ttk.Frame(notebook)
        notebook.add(tab_about, text='アプリについて')

        about_container = ttk.Frame(tab_about)
        about_container.pack(expand=True, fill='both', padx=20, pady=20)

        self.about_title_lbl = ttk.Label(about_container, text=f"{config.APP_NAME} v{config.APP_VERSION}", font=("Helvetica", 14, "bold"), justify="center", wraplength=420)
        self.about_title_lbl.pack(pady=(10, 5))
        self._update_about_tab_version_label()

        copyright_text = "© 2026 Fuku856 All rights reserved.\nCreated by Fuku856\nLicense: MIT License"
        credit_lbl = ttk.Label(about_container, text=copyright_text, font=("Helvetica", 10), justify="center", wraplength=420)
        credit_lbl.pack(pady=(0, 20))

        repo_lbl = ttk.Label(about_container, text="Repository:", justify="center")
        repo_lbl.pack(pady=(0, 2))

        link_lbl = ttk.Label(about_container, text=config.REPO_URL, foreground="blue", cursor="hand2", justify="center", wraplength=420)
        link_lbl.pack(pady=(0, 20))
        link_lbl.bind("<Button-1>", lambda e: webbrowser.open(config.REPO_URL))

        # --- タブ5: 更新情報 ---
        self.tab_updates = ttk.Frame(notebook)
        notebook.add(self.tab_updates, text='更新情報')

        updates_container = ttk.Frame(self.tab_updates)
        updates_container.pack(expand=True, fill='both', padx=20, pady=20)

        current_version_lbl = ttk.Label(updates_container, text=f"現在のバージョン: v{config.APP_VERSION}", font=("Helvetica", 10))
        current_version_lbl.pack(pady=(0, 10), anchor='w')

        self.latest_version_lbl = ttk.Label(updates_container, text="最新バージョン: (未取得)", font=("Helvetica", 10))
        self.latest_version_lbl.pack(pady=(0, 10), anchor='w')

        self.check_update_btn = ttk.Button(updates_container, text="最新情報を取得する", command=self.check_for_updates)
        self.check_update_btn.pack(pady=(0, 10), anchor='w')

        release_note_lbl = ttk.Label(updates_container, text="リリースノート:", font=("Helvetica", 10))
        release_note_lbl.pack(pady=(0, 5), anchor='w')

        self.release_text_area = scrolledtext.ScrolledText(updates_container, wrap='word', height=10, state='disabled')
        self.release_text_area.pack(expand=True, fill='both')

        # --- 下部のボタン領域 (常に表示) ---
        btn_frame = ttk.Frame(self.settings_window)
        btn_frame.pack(side='bottom', pady=(0, 10))

        test_btn = ttk.Button(btn_frame, text="テスト通知を実行", command=self.send_test_notification)
        test_btn.pack(side='left', padx=5)

        save_btn = ttk.Button(btn_frame, text="保存して再接続", command=self.save_settings)
        save_btn.pack(side='left', padx=5)

    def send_test_notification(self):
        # 疑似的なニュースデータを作成してUIへ送る
        test_data = {
            "title": "テスト速報",
            "body": "これは通知と表示のテストです。正常に動作しています。",
            "url": "https://axis.prioris.jp/"
        }
        self.append_log("breaking-news", test_data)

    def update_checkboxes_state(self, event=None):
        token = self.token_entry.get().strip()
        is_valid_jwt = len(token.split('.')) == 3
        subscribed_in_token = []
        
        if is_valid_jwt:
            try:
                parts = token.split('.')
                payload_b64 = parts[1]
                # Base64パディングを補完
                payload_b64 += "=" * ((4 - len(payload_b64) % 4) % 4)
                payload_json = base64.urlsafe_b64decode(payload_b64).decode('utf-8')
                
                for ch in self.channel_vars.keys():
                    if ch in payload_json:
                        subscribed_in_token.append(ch)
            except Exception:
                pass
                
        for ch, chk_widget in self.channel_widgets.items():
            lbl_widget = getattr(self, 'channel_labels', {}).get(ch)
            
            # 有効なトークンかつ購読されている場合のみ有効化
            is_subscribed = is_valid_jwt and ch in subscribed_in_token
            
            if is_subscribed:
                chk_widget.state(['!disabled'])
                if lbl_widget:
                    lbl_widget.configure(foreground="#555555")
            else:
                chk_widget.state(['disabled'])
                if lbl_widget:
                    lbl_widget.configure(foreground="#aaaaaa")
                # トークンが形式的に有効である場合に限り、購読されていないチャンネルのチェックを外す
                # トークン入力中（一時的に無効な状態）は、ユーザーの選択状態を維持する
                if is_valid_jwt:
                    self.channel_vars[ch].set(False)

    def save_settings(self):
        new_token = self.token_entry.get().strip()
        
        selected_channels = [ch for ch, var in self.channel_vars.items() if var.get()]
        config.set_channels(selected_channels)
        config.set_token(new_token)
        config.set_show_popup(self.show_popup_var.get())
        config.set_auto_open_log(self.auto_open_log_var.get())
        config.set_check_update_on_startup(self.check_startup_var.get())
        config.set_auto_update_interval_days(self.interval_options[self.interval_var.get()])
        
        self.client.restart() # 新しいトークンと設定で強制再接続
        if self.settings_window:
            self.settings_window.destroy()
            self.settings_window = None

    def check_for_updates(self):
        is_dev = config.APP_VERSION.lower() in ("dev", "vdev")
        if is_dev:
            res = messagebox.askokcancel("警告", "ローカル版（開発版）のため、更新確認時に予期せぬエラーが発生する可能性があります。\n\n続行しますか？", parent=self.settings_window)
            if not res:
                return

        try:
            if hasattr(self, 'check_update_btn') and self.check_update_btn.winfo_exists():
                self.check_update_btn.state(['disabled'])
                
            self.latest_version_lbl.config(text="最新バージョン: 取得中...")
            self.release_text_area.configure(state='normal')
            try:
                self.release_text_area.delete("1.0", tk.END)
                self.release_text_area.insert(tk.END, "情報を取得しています...\n")
            finally:
                self.release_text_area.configure(state='disabled')
        except tk.TclError:
            pass

        threading.Thread(target=self._fetch_latest_release, args=(True, is_dev), daemon=True).start()

    def _update_release_info(self, tag_name, body):
        if tag_name != "取得失敗":
            self._update_info_fetched = True
            
        try:
            if tag_name not in ("取得失敗", "スキップ"):
                try:
                    latest_ver = tag_name.lstrip('vV')
                    current_ver = config.APP_VERSION.lstrip('vV')
                    
                    def parse_version(v):
                        res = []
                        for x in v.split('.'):
                            m = re.match(r'\d+', x)
                            if m:
                                res.append(int(m.group()))
                        return res
                    
                    is_latest = parse_version(current_ver) >= parse_version(latest_ver)
                    self.is_latest_version = is_latest
                    self._update_about_tab_version_label()
                    
                    if not is_latest:
                        self.show_update_prompt(tag_name)
                except Exception as e:
                    print(f"Version comparison error: {e}")

            if hasattr(self, 'latest_version_lbl') and self.latest_version_lbl.winfo_exists():
                self.latest_version_lbl.config(text=f"最新バージョン: {tag_name}")
            
            if hasattr(self, 'release_text_area') and self.release_text_area.winfo_exists():
                self.release_text_area.configure(state='normal')
                try:
                    self.release_text_area.delete("1.0", tk.END)
                    self._insert_markdown(self.release_text_area, body)
                finally:
                    self.release_text_area.configure(state='disabled')
                
            if hasattr(self, 'check_update_btn') and self.check_update_btn.winfo_exists():
                self.check_update_btn.state(['!disabled'])
        except tk.TclError:
            pass

    def show_update_prompt(self, tag_name):
        prompt = tk.Toplevel(self.root)
        prompt.title("アップデート通知")
        prompt.attributes("-topmost", True)
        prompt.resizable(False, False)
        
        prompt.update_idletasks()
        width = 350
        height = 130
        
        parent = self.settings_window if self.settings_window and self.settings_window.winfo_exists() else None
        if parent:
            x = parent.winfo_x() + (parent.winfo_width() // 2) - (width // 2)
            y = parent.winfo_y() + (parent.winfo_height() // 2) - (height // 2)
        else:
            x = (prompt.winfo_screenwidth() // 2) - (width // 2)
            y = (prompt.winfo_screenheight() // 2) - (height // 2)
            
        prompt.geometry(f"{width}x{height}+{x}+{y}")

        msg = ttk.Label(prompt, text=f"新しいバージョン ({tag_name}) が利用可能です。\n更新しますか？", justify="center", font=("Helvetica", 10))
        msg.pack(pady=20)
        
        btn_frame = ttk.Frame(prompt)
        btn_frame.pack(pady=5)
        
        def open_release():
            repo_url = config.REPO_URL.rstrip('/')
            webbrowser.open(f"{repo_url}/releases/latest")
            prompt.destroy()
            
        open_btn = ttk.Button(btn_frame, text="リリースページを開く", command=open_release)
        open_btn.pack(side="left", padx=10)
        
        cancel_btn = ttk.Button(btn_frame, text="後で", command=prompt.destroy)
        cancel_btn.pack(side="left", padx=10)
        
        prompt.focus_set()

    def _insert_markdown(self, widget, text):
        widget.tag_configure("h1", font=("Helvetica", 14, "bold"), spacing1=10, spacing3=5)
        widget.tag_configure("h2", font=("Helvetica", 12, "bold"), spacing1=8, spacing3=4)
        widget.tag_configure("h3", font=("Helvetica", 10, "bold"), spacing1=5, spacing3=2)
        widget.tag_configure("bold", font=("Helvetica", 10, "bold"))
        widget.tag_configure("link", foreground="blue", underline=True)

        lines = text.split('\n')
        for line in lines:
            header_match = re.match(r'^(#{1,3})\s+(.*)', line)
            if header_match:
                level = len(header_match.group(1))
                content = header_match.group(2)
                tag = f"h{level}"
                self._parse_inline(widget, content, tags=(tag,))
                widget.insert(tk.END, "\n")
                continue
            
            list_match = re.match(r'^(\s*)[-*]\s+(.*)', line)
            if list_match:
                indent = list_match.group(1)
                content = list_match.group(2)
                widget.insert(tk.END, indent + "• ", ())
                self._parse_inline(widget, content, tags=())
                widget.insert(tk.END, "\n")
                continue
                
            self._parse_inline(widget, line)
            widget.insert(tk.END, "\n")

    def _parse_inline(self, widget, line, tags=()):
        pattern = r'(<img[^>]+src="([^"]+)"[^>]*>)|(!\[.*?\]\([^)]+\))|(\[.*?\]\([^)]+\))|(\*\*.*?\*\*)|(https?://[^\s)\]"\']+)'
        pos = 0
        for match in re.finditer(pattern, line):
            start, end = match.span()
            if pos < start:
                widget.insert(tk.END, line[pos:start], tags)
            
            token = match.group(0)
            if token.startswith('<img'):
                img_url = match.group(2)
                if img_url:
                    self._insert_link(widget, "image", img_url, tags)
            elif token.startswith('!['):
                alt_url = re.match(r'!\[.*?\]\(([^)]+)\)', token)
                if alt_url:
                    url = alt_url.group(1)
                    self._insert_link(widget, "image", url, tags)
            elif token.startswith('['):
                txt_url = re.match(r'\[(.*?)\]\(([^)]+)\)', token)
                if txt_url:
                    txt = txt_url.group(1)
                    url = txt_url.group(2)
                    self._insert_link(widget, txt, url, tags)
            elif token.startswith('**'):
                txt = token[2:-2]
                widget.insert(tk.END, txt, tags + ("bold",))
            elif token.startswith('http'):
                self._insert_link(widget, token, token, tags)
            
            pos = end
            
        if pos < len(line):
            widget.insert(tk.END, line[pos:], tags)

    def _insert_link(self, widget, label, url, base_tags):
        tag_name = f"link_{uuid.uuid4().hex}"
        all_tags = base_tags + ("link", tag_name)
        widget.insert(tk.END, label, all_tags)
        widget.tag_bind(tag_name, "<Button-1>", lambda e, u=url: webbrowser.open(u))
        widget.tag_bind(tag_name, "<Enter>", lambda e: widget.config(cursor="hand2"))
        widget.tag_bind(tag_name, "<Leave>", lambda e: widget.config(cursor=""))

    def start_background_update_checker(self, is_startup=False):
        if is_startup and config.get_check_update_on_startup():
            threading.Thread(target=self._fetch_latest_release, args=(False,), daemon=True).start()
        
        # 1時間ごとに定期チェックをスケジュール
        self.root.after(3600000, lambda: self.start_background_update_checker(is_startup=False))
        
        if not is_startup:
            interval = config.get_auto_update_interval_days()
            if interval > 0:
                last_check_str = config.get_last_update_check_time()
                try:
                    last_check = datetime.fromisoformat(last_check_str) if last_check_str else datetime.min
                    if (datetime.now() - last_check).days >= interval:
                        threading.Thread(target=self._fetch_latest_release, args=(False,), daemon=True).start()
                except Exception:
                    pass

    def _fetch_latest_release(self, is_manual=False, force=False):
        if config.APP_VERSION.lower() in ("dev", "vdev") and not force:
            if is_manual:
                self.root.after(0, lambda: self._update_release_info("スキップ", "開発バージョンのため、最新情報の取得をスキップしました。"))
            return

        try:
            repo_path = "/".join(config.REPO_URL.rstrip('/').split('/')[-2:])
            url = f"https://api.github.com/repos/{repo_path}/releases/latest"
            user_agent = f"{getattr(config, 'APP_NAME', 'AXIS-Alert-Receiver')}/{getattr(config, 'APP_VERSION', '1.0')}"
            req = urllib.request.Request(url, headers={'User-Agent': user_agent})
            
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))
                tag_name = data.get("tag_name", "不明")
                body = data.get("body", "リリースノートがありません。")
                
                # 自動チェックの場合、最終確認日時を更新
                if not is_manual:
                    config.set_last_update_check_time(datetime.now().isoformat())
                    
                self.root.after(0, lambda: self._update_release_info(tag_name, body))
        except Exception as e:
            if is_manual:
                self.root.after(0, lambda: self._update_release_info("取得失敗", f"エラーが発生しました:\n{e}"))
            else:
                print(f"Background update check error: {e}")

    def _update_about_tab_version_label(self):
        try:
            if hasattr(self, 'about_title_lbl') and self.about_title_lbl.winfo_exists():
                base_text = f"{config.APP_NAME} v{config.APP_VERSION}"
                if config.APP_VERSION.lower() in ("dev", "vdev"):
                    self.about_title_lbl.config(text=base_text + " (開発版)")
                elif self.is_latest_version is True:
                    self.about_title_lbl.config(text=base_text + " (最新)")
                elif self.is_latest_version is False:
                    self.about_title_lbl.config(text=base_text + " (アップデートあり)")
                else:
                    self.about_title_lbl.config(text=base_text)
        except Exception:
            pass

    def mainloop(self):
        self.root.mainloop()

    def quit(self):
        self.root.quit()
