import json
import hashlib

CHANNEL_TITLES = {
    "jmx-meteorology": "気象情報",
    "jmx-seismology": "地震情報",
    "jmx-volcanology": "火山情報",
    "quake-one": "緊急地震速報(quake-one)",
    "eew": "緊急地震速報",
    "breaking-news": "ニュース速報"
}

CHANNEL_DESCRIPTIONS = {
    "jmx-meteorology": "気象庁電文のうち地震と火山に関するものを除く気象情報",
    "jmx-seismology": "気象庁電文のうち地震に関係する情報",
    "jmx-volcanology": "気象庁電文のうち火山に関係する情報",
    "quake-one": "QUAKE.ONEで提供中の地震概要、震源・震度情報、震度マップ画像",
    "eew": "緊急地震速報 (beta)",
    "breaking-news": "ニュース速報 (beta)"
}

def remove_empty_elements(data):
    """再帰的に辞書やリストから空の要素を削除する"""
    if isinstance(data, dict):
        cleaned = {}
        for k, v in data.items():
            v_cleaned = remove_empty_elements(v)
            if v_cleaned is not None and v_cleaned != "" and v_cleaned != {} and v_cleaned != []:
                cleaned[k] = v_cleaned
        return cleaned if cleaned else None
    elif isinstance(data, list):
        cleaned = []
        for item in data:
            item_cleaned = remove_empty_elements(item)
            if item_cleaned is not None and item_cleaned != "" and item_cleaned != {} and item_cleaned != []:
                cleaned.append(item_cleaned)
        return cleaned if cleaned else None
    else:
        return data

def extract_jma_info(data):
    """JMA形式のデータからTitle, EventID, Headlineを抽出する試み"""
    title = None
    event_id = None
    headline = None

    # Report -> Head または Head などの一般的な構造を探索
    head = data.get("Head") or data.get("Report", {}).get("Head")
    
    if head and isinstance(head, dict):
        title = head.get("Title")
        event_id = head.get("EventID")
        
        # 見出し文の抽出
        hl = head.get("Headline")
        if hl and isinstance(hl, dict):
            text = hl.get("Text")
            if text:
                headline = text

    return title, event_id, headline

def format_message(channel, message_data):
    """
    受信データを解析し、UIで表示しやすいように整形する。
    戻り値: (event_id, display_title, body_text)
    """
    if not isinstance(message_data, dict):
        # 辞書でない場合はそのまま返す
        return str(hash(str(message_data))), CHANNEL_TITLES.get(channel, channel), str(message_data)

    # 1. メタデータの抽出
    title_from_msg = message_data.get("title")
    body_from_msg = message_data.get("body")
    
    jma_title, event_id, headline = extract_jma_info(message_data)

    # 2. タイトルの決定
    # 優先順位: JSON内の明示的なtitle > JMAのTitle > チャンネル名ベース
    display_title = title_from_msg or jma_title or CHANNEL_TITLES.get(channel, "ニュース速報")

    # 3. イベントIDの決定（ポップアップ再利用のキー）
    if not event_id:
        # EventIDがない場合はタイトルでグループ化するか、固有のハッシュを作る
        # 更新されるものは基本タイトルが同じになるため、チャンネル+タイトルをキーにする
        event_id_str = f"{channel}_{display_title}"
        event_id = hashlib.md5(event_id_str.encode('utf-8')).hexdigest()

    # 4. 本文の整形
    if body_from_msg and isinstance(body_from_msg, str) and not jma_title:
        # シンプルなテキストのbodyキーがある場合はそれを使う
        body_text = body_from_msg
    else:
        # 複雑なJSONの場合は不要なデータを消してインデント整形
        cleaned_data = remove_empty_elements(message_data)
        if not cleaned_data:
            cleaned_data = message_data # 全部消えてしまった場合のフォールバック
            
        json_str = json.dumps(cleaned_data, indent=2, ensure_ascii=False)
        
        body_parts = []
        if headline:
            body_parts.append("【見出し】\n" + headline + "\n")
            body_parts.append("【詳細データ】")
            
        body_parts.append(json_str)
        body_text = "\n".join(body_parts)

    return event_id, display_title, body_text
