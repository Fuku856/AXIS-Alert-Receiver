import json
import ssl
import time
import threading
import requests
import websocket
import config
import security_utils

# 受信を許可する1メッセージの最大バイト数(過大メッセージによるメモリ枯渇を防ぐ)
MAX_MESSAGE_BYTES = 1 * 1024 * 1024  # 1MB
# リフレッシュAPIを叩くしきい値(残りこれ未満のときだけ)。公式は残り7日未満のみ許可。
REFRESH_THRESHOLD_SEC = 7 * 86400
# アプリレベルハートビートの送信間隔(公式は60秒に1回程度を推奨)
HEARTBEAT_INTERVAL_SEC = 30

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
        self._heartbeat_timer = None
        self._restart_requested = False
    
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
                    return servers[0] # 先頭のサーバーを選択
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
        # 公式仕様: トークンの残り日数が7日以上ある場合、リフレッシュAPIへのアクセスは禁止
        # （頻繁なアクセスはアカウント停止対象）。残り7日未満のときだけリフレッシュする。
        seconds_remaining = security_utils.get_token_seconds_remaining(self.token)
        if seconds_remaining is None:
            # expが読み取れないトークンは安全側に倒し、リフレッシュAPIを叩かない。
            return
        if seconds_remaining >= REFRESH_THRESHOLD_SEC:
            return

        # 残り7日未満。さらにポーリング防止のため1日に1回までに制限する。
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
        # サーバから受け取った接続先を信頼せず検証する。
        # wss:// 以外(平文ws://等)や想定外ホストへの接続はトークン漏洩につながるため拒否。
        if not security_utils.is_trusted_ws_url(server_url):
            self._set_status("エラー: 安全でない接続先のため接続を中止しました")
            return

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

        # ping_interval=60 でプロトコルレベルのHeartbeatを送信。
        # sslopt でTLS証明書検証を明示(中間者対策)。
        self.ws.run_forever(
            ping_interval=60,
            ping_timeout=10,
            sslopt={"cert_reqs": ssl.CERT_REQUIRED}
        )

    def on_open(self, ws):
        self.retry_sec = 1
        self.retry_count = 0
        self._set_status("接続確立（hello待機中）")
        # 公式仕様に従い、アプリレベルのハートビート('hb')を定期送信して接続を維持する。
        self._schedule_heartbeat(ws)

    def _schedule_heartbeat(self, ws):
        self._cancel_heartbeat()
        if not self.running or self.ws is not ws:
            return
        timer = threading.Timer(HEARTBEAT_INTERVAL_SEC, self._send_heartbeat, args=(ws,))
        timer.daemon = True
        self._heartbeat_timer = timer
        timer.start()

    def _send_heartbeat(self, ws):
        if not self.running or self.ws is not ws:
            return
        try:
            ws.send("hb")
        except Exception:
            return
        self._schedule_heartbeat(ws)

    def _cancel_heartbeat(self):
        if self._heartbeat_timer is not None:
            self._heartbeat_timer.cancel()
            self._heartbeat_timer = None

    def on_message(self, ws, message):
        # 過大なメッセージはメモリ枯渇(DoS)につながるため破棄する。
        if message is not None and len(message) > MAX_MESSAGE_BYTES:
            self._set_status("警告: 過大なメッセージを受信したため破棄しました")
            return
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
        self._cancel_heartbeat()
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
                    self.retry_sec = min(self.retry_sec * 2, 60) # 指数関数的に増加(上限60秒)
                else:
                    self._set_status("再接続上限に達しました。設定から再試行してください。")
                    # トークンの更新、または設定画面からのrestart()要求まで待機する
                    self._restart_requested = False
                    while (self.running and not self._restart_requested
                           and self.token == config.get_token()):
                        time.sleep(1)
                    self._restart_requested = False
                    self.retry_count = 0
                    self.retry_sec = 1

    def stop(self):
        self.running = False
        self._cancel_heartbeat()
        if self.ws:
            self.ws.close()

    def restart(self):
        """トークンが更新された場合などに強制再接続する"""
        # 再接続上限到達後の待機ループはトークンの「変更」しか監視しないため、
        # 同一トークンのまま保存された場合でも抜けられるようフラグで通知する。
        self._restart_requested = True
        if self.ws:
            self.ws.close()
        self.retry_count = 0
        self.retry_sec = 1
