import json
import time
import threading
import requests
import websocket
import config

class AxisClient(threading.Thread):
    def __init__(self, on_message_callback, on_status_change_callback):
        super().__init__(daemon=True)
        self.on_message_callback = on_message_callback
        self.on_status_change_callback = on_status_change_callback
        self.running = True
        self.ws = None
        self.retry_sec = 1
        self.retry_max = 10
        self.retry_count = 0
        self.base_api_url = "https://axis.prioris.jp/api/server/list/"
        self.status = "オフライン"
        self.token = ""
    
    def _set_status(self, new_status):
        self.status = new_status
        if self.on_status_change_callback:
            self.on_status_change_callback(self.status)

    def get_server_url(self):
        self._set_status("サーバ取得中...")
        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            response = requests.get(self.base_api_url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                servers = data.get("servers", [])
                if servers:
                    return servers[0] # 先頭のサーバを選択
                else:
                    self._set_status("エラー: 利用可能なサーバがありません")
            elif response.status_code == 401:
                self._set_status("認証エラー: トークンが無効です")
            else:
                self._set_status(f"エラー: HTTP {response.status_code}")
        except Exception as e:
            self._set_status(f"通信エラー: {str(e)}")
        return None

    def try_refresh_token(self):
        # 1日に1回だけ実行する（ポーリング禁止ルール遵守）
        last_refresh = config.get_last_refresh()
        current_time = time.time()
        if current_time - last_refresh < 86400: # 24時間
            return

        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            res = requests.get("https://axis.prioris.jp/api/token/refresh/", headers=headers, timeout=10)
            config.set_last_refresh(current_time)
            if res.status_code == 200:
                data = res.json()
                new_token = data.get("token")
                if new_token and new_token != self.token:
                    self.token = new_token
                    config.set_token(new_token)
                    self.on_message_callback("システム", "トークンが自動更新（リフレッシュ）されました。")
            elif res.status_code == 402:
                self.on_message_callback("システム", "契約期限切れのため、トークンの自動更新に失敗しました。")
        except Exception as e:
            print(f"Token refresh error: {e}")

    def connect_ws(self, server_url):
        self._set_status(f"接続中: {server_url}")
        websocket.enableTrace(False)
        safe_token = self.token.strip() if self.token else ""
        headers = [f"Authorization: Bearer {safe_token}"]
        
        self.ws = websocket.WebSocketApp(
            f"{server_url}/socket",
            header=headers,
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close
        )
        
        # ping_interval=60 で自動的にHeartbeatを送信
        self.ws.run_forever(ping_interval=60, ping_timeout=10)

    def on_open(self, ws):
        self.retry_sec = 1
        self.retry_count = 0
        self._set_status("接続確立（hello待機中）")

    def on_message(self, ws, message):
        if message == "hello":
            self._set_status("オンライン")
            self.on_message_callback("システム", "AXISサーバとの接続が完了しました。")
            return
        if message == "hb":
            return # Heartbeat
        if message.startswith("error:"):
            self._set_status(f"サーバエラー: {message}")
            return
            
        try:
            data = json.loads(message)
            channel = data.get("channel", "unknown")
            msg_content = data.get("message", {})
            
            # 設定画面でチェックを入れたチャンネルのみ受信する
            subscribed_channels = config.get_channels()
            if channel in subscribed_channels:
                self.on_message_callback(channel, msg_content)
        except json.JSONDecodeError:
            self.on_message_callback("パースエラー", f"不正なフォーマットを受信: {message}")

    def on_error(self, ws, error):
        print(f"WebSocket Error: {error}")

    def on_close(self, ws, close_status_code, close_msg):
        self.ws = None
        if self.running:
            self._set_status(f"切断されました。({close_status_code}: {close_msg}) 再接続を試みます...")
            print(f"WebSocket Closed: {close_status_code} - {close_msg}")

    def run(self):
        while self.running:
            self.token = config.get_token()
            if self.token:
                self.token = self.token.strip()
            if not self.token:
                self._set_status("トークン未設定")
                time.sleep(2)
                continue

            self.try_refresh_token()

            server_url = self.get_server_url()
            if server_url:
                self.connect_ws(server_url)
            
            # 再接続制御 (Exponential Backoff)
            if self.running:
                if self.retry_count < self.retry_max:
                    self.retry_count += 1
                    time.sleep(self.retry_sec)
                    self.retry_sec *= 2 # 指数関数的に増加
                else:
                    self._set_status("再接続上限に達しました。設定から再試行してください。")
                    while self.running and self.token == config.get_token():
                        time.sleep(1) # トークンが更新されるまで待機
                    self.retry_count = 0
                    self.retry_sec = 1
            
    def stop(self):
        self.running = False
        if self.ws:
            self.ws.close()

    def restart(self):
        """トークンが更新された場合などに強制再接続する"""
        if self.ws:
            self.ws.close()
        self.retry_count = 0
        self.retry_sec = 1
