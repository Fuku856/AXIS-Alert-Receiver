"""セキュリティ関連の共通ユーティリティ。

URLスキーム検証、WebSocket接続先の検証、JWTペイロード解析など、
複数モジュールで共有する処理をここに集約する。
"""

import re
import json
import base64
import time
import urllib.parse

# WebSocketサーバとして許可するホストのサフィックス。
# AXIS公式の server list API は wss://<host>/ 形式のURLを返す。
ALLOWED_WS_HOST_SUFFIXES = ("prioris.jp",)


def is_safe_web_url(url):
    """ブラウザ起動などに使えるhttp/https URLかどうかを判定する。"""
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def is_trusted_ws_url(url):
    """WebSocket接続先として信頼できるURL(wss://かつ許可ホスト)かを判定する。

    公式仕様では server list API は完全な wss:// URL を返す。平文(ws://)への
    ダウングレードや想定外ホストへの接続を防ぐため、スキームとホストを検証する。
    """
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return False
    if parsed.scheme != "wss":
        return False
    host = parsed.hostname
    if not host:
        return False
    return any(host == suffix or host.endswith("." + suffix)
               for suffix in ALLOWED_WS_HOST_SUFFIXES)


def decode_jwt_payload(token):
    """JWTのペイロード部をデコードして辞書で返す。失敗時はNone。

    署名の検証は行わない(表示・有効期限判定など非セキュアな用途専用)。
    """
    if not token or not isinstance(token, str):
        return None
    parts = token.strip().split('.')
    if len(parts) != 3:
        return None
    try:
        payload_b64 = parts[1]
        payload_b64 += "=" * ((4 - len(payload_b64) % 4) % 4)
        payload_json = base64.urlsafe_b64decode(payload_b64).decode('utf-8')
        payload = json.loads(payload_json)
        if isinstance(payload, dict):
            return payload
    except Exception:
        return None
    return None


def collect_string_tokens(data):
    """ネストしたdict/list内の文字列値を再帰的に集合で返す。

    空白・カンマ区切りの文字列は分割した要素も含める。チャンネル名の
    完全一致判定に使う(JSON全体への部分文字列マッチによる誤検出を防ぐ)。
    """
    tokens = set()

    def _collect(value):
        if isinstance(value, str):
            tokens.add(value)
            for part in re.split(r"[\s,]+", value):
                if part:
                    tokens.add(part)
        elif isinstance(value, dict):
            for v in value.values():
                _collect(v)
        elif isinstance(value, (list, tuple)):
            for v in value:
                _collect(v)

    _collect(data)
    return tokens


def get_token_seconds_remaining(token):
    """JWTの有効期限(exp)まで残り何秒かを返す。expが無い/不正ならNone。"""
    payload = decode_jwt_payload(token)
    if not payload:
        return None
    exp = payload.get("exp")
    if not isinstance(exp, (int, float)):
        return None
    return exp - time.time()
