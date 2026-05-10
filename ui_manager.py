import tkinter as tk
from tkinter import scrolledtext, ttk
import config
from datetime import datetime
import json
import notifier

class UIManager:
    def __init__(self, axis_client):
        self.client = axis_client
        self.root = tk.Tk()
        self.root.withdraw() # メインウィンドウは非表示
        self.root.protocol("WM_DELETE_WINDOW", self.hide_log_window) # 閉じるボタンで非表示

        # ログウィンドウの作成
        self.log_window = tk.Toplevel(self.root)
        self.log_window.title("AXIS Breaking News - ログ")
        self.log_window.geometry("600x400")
        self.log_window.protocol("WM_DELETE_WINDOW", self.hide_log_window)
        self.log_window.withdraw() # 初期は非表示

        self.text_area = scrolledtext.ScrolledText(self.log_window, state='disabled', wrap='word')
        self.text_area.pack(expand=True, fill='both', padx=5, pady=5)

        # 設定ダイアログの作成
        self.settings_window = None

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
                title = message_data.get("title", "ニュース速報")
                body = message_data.get("body", json.dumps(message_data, ensure_ascii=False))
                url = message_data.get("url", None)
                text = f"[{timestamp}] [{channel}]\n{title}\n{body}\n"
                if url:
                    text += f"URL: {url}\n"
                text += "-" * 40 + "\n"
                
                # トースト通知も出す
                notifier.show_toast(title, body, url)
                
                # 自動的にログウィンドウを表示
                self.show_log_window()
                
                # さらに目立つように専用のポップアップも出す
                self.show_alert_popup(title, body, url)

            self.text_area.insert(tk.END, text)
            self.text_area.configure(state='disabled')
            self.text_area.yview(tk.END)
            
        self.root.after(0, _update)

    def update_status(self, status):
        def _update():
            if self.settings_window and self.settings_window.winfo_exists():
                self.status_label.config(text=f"状態: {status}")
        self.root.after(0, _update)

    def show_log_window(self):
        self.log_window.deiconify()
        self.log_window.lift()

    def hide_log_window(self):
        self.log_window.withdraw()

    def show_alert_popup(self, title, body, url):
        # ニュース受信時に自動でポップアップするウィンドウ
        alert = tk.Toplevel(self.root)
        alert.title("【速報】" + title)
        alert.geometry("500x250")
        alert.attributes("-topmost", True) # 常に最前面
        
        # タイトル表示
        tk.Label(alert, text=title, font=("Helvetica", 14, "bold"), fg="red", wraplength=480).pack(pady=10)
        
        # 本文表示
        tk.Label(alert, text=body, font=("Helvetica", 10), wraplength=480, justify="left").pack(pady=10, padx=10, fill="both", expand=True)
        
        if url:
            import webbrowser
            btn = ttk.Button(alert, text="ブラウザで詳細を開く", command=lambda: webbrowser.open(url))
            btn.pack(pady=5)
            
        close_btn = ttk.Button(alert, text="閉じる", command=alert.destroy)
        close_btn.pack(pady=10)
        
        # 音を鳴らす（Windows標準のエラー音等）
        self.root.bell()

    def show_settings_window(self):
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.lift()
            return

        self.settings_window = tk.Toplevel(self.root)
        self.settings_window.title("設定 - AXIS Breaking News")
        self.settings_window.geometry("450x350")
        self.settings_window.resizable(False, False)

        ttk.Label(self.settings_window, text="AXIS アクセストークン (JWT):").pack(pady=5, padx=10, anchor='w')
        self.token_entry = ttk.Entry(self.settings_window, width=50)
        self.token_entry.pack(pady=5, padx=10)
        self.token_entry.insert(0, config.get_token())

        ttk.Label(self.settings_window, text="受信するチャンネル:").pack(pady=5, padx=10, anchor='w')
        
        self.channel_vars = {}
        self.channel_widgets = {}
        channels = ["breaking-news", "jmx-meteorology", "jmx-seismology", "jmx-volcanology", "quake-one", "eew"]
        saved_channels = config.get_channels()
        
        channels_frame = ttk.Frame(self.settings_window)
        channels_frame.pack(padx=20, anchor='w')
        
        for ch in channels:
            var = tk.BooleanVar(value=(ch in saved_channels))
            chk = ttk.Checkbutton(channels_frame, text=ch, variable=var)
            chk.pack(anchor='w')
            self.channel_vars[ch] = var
            self.channel_widgets[ch] = chk

        # トークン入力時にリアルタイムでチェックボックスの状態を更新する
        self.token_entry.bind("<KeyRelease>", self.update_checkboxes_state)
        # 初期状態の反映
        self.update_checkboxes_state()

        self.status_label = ttk.Label(self.settings_window, text=f"状態: {self.client.status}")
        self.status_label.pack(pady=10, padx=10, anchor='w')

        btn_frame = ttk.Frame(self.settings_window)
        btn_frame.pack(pady=10)

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
                import base64
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
            if is_valid_jwt and ch not in subscribed_in_token:
                chk_widget.state(['disabled'])
                self.channel_vars[ch].set(False) # 未購読ならチェックも外す
            else:
                chk_widget.state(['!disabled'])

    def save_settings(self):
        new_token = self.token_entry.get().strip()
        
        selected_channels = [ch for ch, var in self.channel_vars.items() if var.get()]
        config.set_channels(selected_channels)
        config.set_token(new_token)
        
        from tkinter import messagebox
        messagebox.showinfo(
            "確認", 
            "設定を保存しました。\n\n"
            "AXISダッシュボード (https://axis.prioris.jp/manage/channel/) でも、"
            "ここでチェックを入れたチャンネルを【確実に購読】しているか確認してください。\n"
            "ダッシュボード側で購読していないチャンネルは、アプリ側でチェックを入れても受信できません。"
        )

        self.client.restart() # 新しいトークンと設定で強制再接続
        if self.settings_window:
            self.settings_window.destroy()

    def mainloop(self):
        self.root.mainloop()

    def quit(self):
        self.root.quit()
