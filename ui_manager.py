import sys
import os
import json
import base64
import urllib.request
import threading
import re
import uuid
import webbrowser
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QScrollArea, QTabWidget,
    QCheckBox, QComboBox, QLineEdit, QMessageBox, QFrame,
    QSizePolicy, QStyle
)
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QRect, QPoint, Signal, QObject, Slot, QEasingCurve, QUrl, QByteArray, QBuffer, QIODevice
from PySide6.QtGui import QIcon, QPixmap, QColor, QPalette, QCursor, QTextCursor, QFont, QAction, QDesktopServices, QPainter, QPen, QShortcut, QKeySequence, QTextDocument, QTextCharFormat, QPainterPath

import config
import notifier
import message_formatter
import difflib

def get_app_path():
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        if os.path.exists(os.path.join(exe_dir, "icon.ico")) or os.path.exists(os.path.join(exe_dir, "icon.png")):
            return exe_dir
        if hasattr(sys, '_MEIPASS'):
            return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))

def get_icon():
    app_path = get_app_path()
    ico_path = os.path.join(app_path, "icon.ico")
    png_path = os.path.join(app_path, "icon.png")
    if os.path.exists(ico_path):
        return QIcon(ico_path)
    if os.path.exists(png_path):
        return QIcon(png_path)
    return QIcon()

def _make_search_icon(color_hex: str = "#AAAAAA") -> QIcon:
    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color_hex), 5, Qt.PenStyle.SolidLine,
               Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    # レンズを右上に配置（左右反転）
    painter.drawEllipse(28, 4, 32, 32)
    # グリップを左下方向へ
    painter.drawLine(32, 34, 8, 58)
    painter.end()
    return QIcon(pixmap)

def _make_eye_icon(open_eye: bool, color_hex: str = "#AAAAAA") -> QIcon:
    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color_hex), 4, Qt.PenStyle.SolidLine,
               Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    # アーモンド型の目輪郭（ベジェ曲線）
    path = QPainterPath()
    path.moveTo(4, 32)
    path.quadTo(32, 6, 60, 32)
    path.quadTo(32, 58, 4, 32)
    painter.drawPath(path)
    painter.setBrush(QColor(color_hex))
    painter.drawEllipse(22, 22, 20, 20)
    if not open_eye:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(8, 52, 56, 12)
    painter.end()
    return QIcon(pixmap)

class SignalEmitter(QObject):
    log_appended = Signal(str, object)
    status_updated = Signal(str)
    release_info_updated = Signal(str, str)

class PopupManager(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.active_popups = {} # event_id -> ToastNotification
        
    def show_popup(self, event_id, title, body, url, timestamp):
        timeout_sec = config.get_popup_timeout()
        if event_id in self.active_popups:
            toast = self.active_popups[event_id]
            toast.update_content(title, body, url, timestamp)
            return

        toast = ToastNotification(event_id, title, body, url, timestamp, self, timeout_sec)
        self.active_popups[event_id] = toast
        toast.show_animated()
        self.reposition_popups()

    def remove_popup(self, event_id):
        if event_id in self.active_popups:
            del self.active_popups[event_id]
            self.reposition_popups()

    def reposition_popups(self):
        screen = QApplication.primaryScreen().availableGeometry()
        margin_right = 20
        margin_top = 20
        spacing = 15
        
        current_y = margin_top
        for event_id, toast in list(self.active_popups.items()):
            if getattr(toast, "is_closing", False) or not toast.isVisible():
                continue
            
            x = screen.right() - toast.width() - margin_right
            y = current_y
            
            target_pos = QPoint(x, y)
            
            # Animate movement
            toast.move_to(target_pos)
            
            current_y += toast.height() + spacing

class ToastNotification(QWidget):
    def __init__(self, event_id, title, body, url, timestamp, manager, timeout_sec=0):
        super().__init__()
        self.event_id = event_id
        self.manager = manager
        self.current_url = url
        self.last_body = body
        
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Determine current theme to set fixed colors
        is_dark = config.get_theme_mode() == "dark"
        bg_color = "#2D2D30" if is_dark else "#FFFFFF"
        fg_color = "#E0E0E0" if is_dark else "#000000"
        border_color = "#0078D7" if is_dark else "#0A84FF"
        time_color = "#AAAAAA" if is_dark else "#555555"

        # The actual styled container is a QFrame to support translucent background + QSS properly
        self.setStyleSheet(f"""
            QFrame#ToastRoot {{
                background-color: {bg_color};
                color: {fg_color};
                border: 2px solid {border_color};
                border-radius: 12px;
            }}
            QLabel#TitleLabel {{
                background-color: transparent;
                color: #FF3B30;
                font-weight: bold;
                font-size: 14px;
            }}
            QLabel#TimeLabel {{
                background-color: transparent;
                color: {time_color};
                font-size: 10px;
            }}
            QPushButton {{
                background-color: {border_color};
                color: white;
                border: none;
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #005A9E;
            }}
            QPushButton#CloseButton {{
                background-color: transparent;
                color: {fg_color};
                font-weight: bold;
                font-size: 20px;
                border-radius: 16px;
                padding: 0px;
            }}
            QPushButton#CloseButton:hover {{
                background-color: transparent;
                color: #FF3B30;
            }}
            QTextEdit {{
                background-color: transparent;
                border: none;
                color: {fg_color};
                font-family: Consolas, monospace;
            }}
        """)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        self.container = QFrame(self)
        self.container.setObjectName("ToastRoot")
        main_layout.addWidget(self.container)
        
        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        
        # Header
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        
        self.title_label = QLabel("【速報】" + title)
        self.title_label.setObjectName("TitleLabel")
        self.title_label.setWordWrap(True)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        
        self.time_label = QLabel(f"受信: {timestamp}" if timestamp else "")
        self.time_label.setObjectName("TimeLabel")
        
        close_btn = QPushButton("×")
        close_btn.setObjectName("CloseButton")
        close_btn.setFixedSize(32, 32)
        close_btn.clicked.connect(self.close_toast)
        
        header_layout.addWidget(self.title_label)
        header_layout.addWidget(self.time_label)
        header_layout.addWidget(close_btn)
        
        layout.addLayout(header_layout)
        
        # Body
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.text_edit.setPlainText(body)
        self.text_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        layout.addWidget(self.text_edit)
        
        # Footer
        footer_layout = QHBoxLayout()
        self.url_button = QPushButton("ブラウザで詳細を開く")
        self.url_button.clicked.connect(self.open_url)
        if not url:
            self.url_button.hide()
        
        footer_layout.addStretch()
        footer_layout.addWidget(self.url_button)
        layout.addLayout(footer_layout)
        
        self.setFixedWidth(400)
        self.timeout_sec = timeout_sec
        self._close_timer = None
        self._remaining_ms = 0

        # Animations
        self.anim = QPropertyAnimation(self, b"pos")
        self.anim.setDuration(300)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.opacity_effect = None # QGraphicsOpacityEffect doesn't always work nicely on top-level frameless windows in Windows. Will just use pos animation.

    def update_content(self, title, body, url, timestamp):
        self.title_label.setText("【更新】" + title)
        if timestamp:
            self.time_label.setText(f"更新: {timestamp}")
        
        self.current_url = url
        if url:
            self.url_button.show()
        else:
            self.url_button.hide()
            
        # Diff update
        diff = list(difflib.ndiff(self.last_body.splitlines(), body.splitlines()))
        
        self.text_edit.clear()
        cursor = self.text_edit.textCursor()
        
        is_dark = config.get_theme_mode() == "dark"
        add_color = "#00FF00" if is_dark else "#006600"
        
        for line in diff:
            if line.startswith('+ '):
                fmt = QTextCharFormat()
                fmt.setForeground(QColor(add_color))
                fmt.setFontWeight(QFont.Weight.Bold)
                cursor.insertText(line[2:] + "\n", fmt)
            elif line.startswith('- '):
                pass
            elif line.startswith('? '):
                pass
            else:
                fmt = QTextCharFormat()
                cursor.insertText(line[2:] + "\n", fmt)
        
        self.text_edit.moveCursor(QTextCursor.MoveOperation.End)
        self.last_body = body
        QApplication.beep()

    def show_animated(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.setMaximumHeight(screen.height() // 3)
        start_pos = QPoint(screen.right() + 10, self.pos().y())
        self.move(start_pos)
        self.show()
        self.adjustSize()
        QApplication.beep()
        if self.timeout_sec > 0:
            self._close_timer = QTimer(self)
            self._close_timer.setSingleShot(True)
            self._close_timer.timeout.connect(self.close_toast)
            self._close_timer.start(self.timeout_sec * 1000)

    def move_to(self, target_pos):
        if self.pos() != target_pos:
            self.anim.stop()
            self.anim.setStartValue(self.pos())
            self.anim.setEndValue(target_pos)
            self.anim.start()

    def enterEvent(self, event):
        if self._close_timer and self._close_timer.isActive():
            self._remaining_ms = self._close_timer.remainingTime()
            self._close_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self._close_timer and self._remaining_ms > 0:
            self._close_timer.start(self._remaining_ms)
            self._remaining_ms = 0
        super().leaveEvent(event)

    def open_url(self):
        if self.current_url:
            webbrowser.open(self.current_url)

    def close_toast(self):
        self.is_closing = True
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        
        # 移動アニメーションなど他のアニメーションが実行中の場合は停止して競合を防ぐ
        if hasattr(self, 'anim') and self.anim.state() == QPropertyAnimation.State.Running:
            self.anim.stop()
            
        self.manager.reposition_popups()
        
        screen = QApplication.primaryScreen().availableGeometry()
        # 右上（閉じるボタンの右上方向）に向かって消えるように、xを右に、yを上にずらす
        target_pos = QPoint(screen.right() + 20, self.pos().y() - 100)
        
        self.close_pos_anim = QPropertyAnimation(self, b"pos")
        self.close_pos_anim.setDuration(250)
        self.close_pos_anim.setEasingCurve(QEasingCurve.Type.OutCubic) # 滑らかに減速する
        self.close_pos_anim.setStartValue(self.pos())
        self.close_pos_anim.setEndValue(target_pos)
        
        self.close_opacity_anim = QPropertyAnimation(self, b"windowOpacity")
        self.close_opacity_anim.setDuration(250)
        self.close_opacity_anim.setStartValue(1.0)
        self.close_opacity_anim.setEndValue(0.0)
        
        self.close_pos_anim.finished.connect(self._on_close_anim_finished)
        
        self.close_pos_anim.start()
        self.close_opacity_anim.start()

    def _on_close_anim_finished(self):
        self.hide()
        self.manager.remove_popup(self.event_id)
        self.deleteLater()

class LogWindow(QMainWindow):
    def __init__(self, manager):
        super().__init__()
        self.manager = manager
        self.setWindowTitle(f"{config.APP_NAME} - ログ")
        self.resize(700, 500)
        self.setWindowIcon(get_icon())

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # ツールバー行
        toolbar = QWidget()
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(0, 0, 0, 0)
        tb_layout.setSpacing(6)

        self.clear_btn = QPushButton("クリア")
        self.clear_btn.setFixedWidth(64)
        self.clear_btn.clicked.connect(self._clear_log)
        tb_layout.addWidget(self.clear_btn)

        tb_layout.addStretch()

        # 検索エリア（初期非表示）
        self.search_widget = QWidget()
        sw_layout = QHBoxLayout(self.search_widget)
        sw_layout.setContentsMargins(0, 0, 0, 0)
        sw_layout.setSpacing(4)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("検索...")
        self.search_box.setMinimumWidth(100)
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._on_search_changed)
        self.search_box.returnPressed.connect(lambda: self._search_text(1))
        sw_layout.addWidget(self.search_box)

        self.prev_btn = QPushButton()
        self.prev_btn.setIcon(QApplication.style().standardIcon(QStyle.StandardPixmap.SP_ArrowUp))
        self.prev_btn.setFixedSize(28, 28)
        self.prev_btn.setToolTip("前の結果")
        self.prev_btn.setProperty("navbtn", True)
        self.prev_btn.clicked.connect(lambda: self._search_text(-1))
        sw_layout.addWidget(self.prev_btn)

        self.next_btn = QPushButton()
        self.next_btn.setIcon(QApplication.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown))
        self.next_btn.setFixedSize(28, 28)
        self.next_btn.setToolTip("次の結果")
        self.next_btn.setProperty("navbtn", True)
        self.next_btn.clicked.connect(lambda: self._search_text(1))
        sw_layout.addWidget(self.next_btn)

        self.match_label = QLabel("")
        self.match_label.setFixedWidth(72)
        sw_layout.addWidget(self.match_label)

        tb_layout.addWidget(self.search_widget)
        self.search_widget.hide()

        self.search_toggle_btn = QPushButton()
        self.search_toggle_btn.setIcon(_make_search_icon())
        self.search_toggle_btn.setFixedSize(32, 32)
        self.search_toggle_btn.setToolTip("検索 (Ctrl+F)")
        self.search_toggle_btn.setProperty("navbtn", True)
        self.search_toggle_btn.clicked.connect(self._toggle_search)
        tb_layout.addWidget(self.search_toggle_btn)

        layout.addWidget(toolbar)

        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.text_edit.setFont(QFont("Consolas", 10))
        layout.addWidget(self.text_edit)

        self._search_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        self._search_shortcut.activated.connect(self._toggle_search)
        self._nav_query = ""

    def _toggle_search(self):
        if self.search_widget.isVisible():
            self.search_widget.hide()
            self.search_box.clear()
            self.text_edit.setExtraSelections([])
            self.match_label.setText("")
            self._nav_query = ""
        else:
            self.search_widget.show()
            self.search_box.setFocus()

    def _clear_log(self):
        self.text_edit.clear()
        self._nav_query = ""

    def _on_search_changed(self, query):
        self._nav_query = ""
        self._highlight_all(query)

    def _highlight_all(self, query):
        self.text_edit.setExtraSelections([])
        if not query:
            self.match_label.setText("")
            return

        fmt = QTextCharFormat()
        fmt.setBackground(QColor("#FFC107"))
        fmt.setForeground(QColor("#000000"))

        doc = self.text_edit.document()
        cursor = doc.find(query)
        selections = []
        while not cursor.isNull():
            sel = QTextEdit.ExtraSelection()
            sel.format = fmt
            sel.cursor = cursor
            selections.append(sel)
            cursor = doc.find(query, cursor)

        self.text_edit.setExtraSelections(selections)
        count = len(selections)
        self.match_label.setText(f"{count}件" if count > 0 else "なし")

    def _search_text(self, direction):
        query = self.search_box.text()
        if not query:
            return

        if self._nav_query != query:
            # クエリが変わった（または初回ナビゲーション）: 先頭/末尾からスキャン開始
            cursor = self.text_edit.textCursor()
            if direction == 1:
                cursor.movePosition(QTextCursor.MoveOperation.Start)
            else:
                cursor.movePosition(QTextCursor.MoveOperation.End)
            self.text_edit.setTextCursor(cursor)
            self._nav_query = query

        if direction == 1:
            found = self.text_edit.find(query)
        else:
            found = self.text_edit.find(query, QTextDocument.FindFlag.FindBackward)
        if not found:
            cursor = self.text_edit.textCursor()
            if direction == 1:
                cursor.movePosition(QTextCursor.MoveOperation.Start)
            else:
                cursor.movePosition(QTextCursor.MoveOperation.End)
            self.text_edit.setTextCursor(cursor)
            if direction == 1:
                self.text_edit.find(query)
            else:
                self.text_edit.find(query, QTextDocument.FindFlag.FindBackward)
        self._highlight_all(query)
        # ナビゲーション時は現在位置/合計件数 形式で上書き
        current_start = self.text_edit.textCursor().selectionStart()
        doc = self.text_edit.document()
        idx = 0
        total = 0
        c = doc.find(query)
        while not c.isNull():
            total += 1
            if c.selectionStart() == current_start:
                idx = total
            c = doc.find(query, c)
        self.match_label.setText(f"{idx}/{total}件" if total > 0 else "なし")

    def append_entry(self, text, color_hex=None):
        self.text_edit.moveCursor(QTextCursor.MoveOperation.End)
        cursor = self.text_edit.textCursor()
        fmt = QTextCharFormat()
        if color_hex:
            fmt.setForeground(QColor(color_hex))
        cursor.setCharFormat(fmt)
        cursor.insertText(text)
        self.text_edit.moveCursor(QTextCursor.MoveOperation.End)
        self._trim_log()

    def _trim_log(self):
        doc = self.text_edit.document()
        if doc.blockCount() > 5000:
            cursor = QTextCursor(doc)
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            cursor.movePosition(
                QTextCursor.MoveOperation.NextBlock,
                QTextCursor.MoveMode.KeepAnchor,
                500
            )
            cursor.removeSelectedText()

    def closeEvent(self, event):
        event.ignore()
        self.hide()

class SettingsWindow(QMainWindow):
    def __init__(self, manager):
        super().__init__()
        self.manager = manager
        self.setWindowTitle(f"設定 - {config.APP_NAME}")
        self.setMinimumSize(550, 400)
        self.setWindowIcon(get_icon())
        
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        
        self._setup_connection_tab()
        self._setup_channels_tab()
        self._setup_ui_tab()
        self._setup_about_tab()
        self._setup_updates_tab()
        
        self.tabs.currentChanged.connect(self._on_tab_changed)
        
        btn_layout = QHBoxLayout()
        test_btn = QPushButton("テスト通知を実行")
        test_btn.clicked.connect(self.manager.send_test_notification)
        
        save_btn = QPushButton("保存して再接続")
        save_btn.clicked.connect(self.save_settings)
        save_btn.setProperty("primary", True)
        
        btn_layout.addWidget(test_btn)
        btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)

    def _setup_connection_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        layout.addWidget(QLabel("AXIS アクセストークン (JWT):"))
        token_row = QHBoxLayout()
        self.token_entry = QLineEdit(config.get_token())
        self.token_entry.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_entry.textChanged.connect(self._update_checkboxes_state)
        token_row.addWidget(self.token_entry)
        self.token_visibility_btn = QPushButton()
        self.token_visibility_btn.setIcon(_make_eye_icon(False))
        self.token_visibility_btn.setFixedSize(32, 32)
        self.token_visibility_btn.setToolTip("トークンを表示/非表示")
        self.token_visibility_btn.setProperty("navbtn", True)
        self.token_visibility_btn.setCheckable(True)
        self.token_visibility_btn.toggled.connect(self._toggle_token_visibility)
        token_row.addWidget(self.token_visibility_btn)
        layout.addLayout(token_row)
        
        self.status_label = QLabel(f"状態: {self.manager.client.status}")
        layout.addWidget(self.status_label)
        
        layout.addStretch()
        self.tabs.addTab(tab, "AXISトークン")

    def _toggle_token_visibility(self, show: bool):
        self.token_entry.setEchoMode(
            QLineEdit.EchoMode.Normal if show else QLineEdit.EchoMode.Password
        )
        fg = "#D4D4D4" if config.get_theme_mode() == "dark" else "#000000"
        self.token_visibility_btn.setIcon(_make_eye_icon(show, fg))

    def _setup_channels_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        layout.addWidget(QLabel("受信するチャンネル:"))
        
        self.channel_vars = {}
        self.channel_widgets = {}
        self.channel_labels = {}
        
        channels = list(message_formatter.CHANNEL_TITLES.keys())
        saved_channels = config.get_channels()
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        
        for ch in channels:
            chk = QCheckBox(ch)
            chk.setChecked(ch in saved_channels)
            scroll_layout.addWidget(chk)
            
            genre = getattr(message_formatter, "CHANNEL_DESCRIPTIONS", {}).get(ch, message_formatter.CHANNEL_TITLES.get(ch, ""))
            if genre:
                lbl = QLabel(genre)
                lbl.setWordWrap(True)
                lbl.setStyleSheet("color: gray; font-size: 11px;")
                lbl.setContentsMargins(20, 0, 0, 10)
                scroll_layout.addWidget(lbl)
                self.channel_labels[ch] = lbl
                
            self.channel_widgets[ch] = chk
            self.channel_vars[ch] = chk
            
        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)
        
        note_lbl = QLabel("グレーアウトされているチャンネルは、\n設定されているAXISトークンで購読されていません。")
        note_lbl.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(note_lbl)
        
        self.tabs.addTab(tab, "チャンネル設定")
        self._update_checkboxes_state()

    def _setup_ui_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        layout.addWidget(QLabel("通知設定:"))
        self.show_popup_var = QCheckBox("受信時にポップアップウィンドウを表示する")
        self.show_popup_var.setChecked(config.get_show_popup())
        layout.addWidget(self.show_popup_var)
        
        self.auto_open_log_var = QCheckBox("受信時にログ画面を自動表示する")
        self.auto_open_log_var.setChecked(config.get_auto_open_log())
        layout.addWidget(self.auto_open_log_var)

        timeout_layout = QHBoxLayout()
        timeout_layout.addWidget(QLabel("ポップアップ自動クリア:"))
        self.timeout_combo = QComboBox()
        self.timeout_options = {"なし": 0, "5秒": 5, "10秒": 10, "30秒": 30}
        self.timeout_combo.addItems(list(self.timeout_options.keys()))
        current_timeout = config.get_popup_timeout()
        current_text = next((k for k, v in self.timeout_options.items() if v == current_timeout), "10秒")
        self.timeout_combo.setCurrentText(current_text)
        timeout_layout.addWidget(self.timeout_combo)
        timeout_layout.addStretch()
        layout.addLayout(timeout_layout)

        layout.addSpacing(10)
        layout.addWidget(QLabel("テーマ設定:"))
        
        theme_layout = QHBoxLayout()
        theme_layout.addWidget(QLabel("テーマモード:"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Dark", "Light"])
        self.theme_combo.setCurrentText(config.get_theme_mode())
        # Theme is applied on save
        theme_layout.addWidget(self.theme_combo)
        theme_layout.addStretch()
        layout.addLayout(theme_layout)

        layout.addSpacing(10)
        layout.addWidget(QLabel("更新設定:"))
        
        self.check_startup_var = QCheckBox("起動時に最新バージョンの更新を確認する")
        self.check_startup_var.setChecked(config.get_check_update_on_startup())
        layout.addWidget(self.check_startup_var)
        
        interval_layout = QHBoxLayout()
        interval_layout.addWidget(QLabel("定期的に更新を確認する間隔:"))
        self.interval_combo = QComboBox()
        self.interval_options = {"なし": 0, "1日": 1, "3日": 3, "7日": 7, "30日": 30}
        self.interval_combo.addItems(list(self.interval_options.keys()))
        
        current_interval = config.get_auto_update_interval_days()
        current_text = next((k for k, v in self.interval_options.items() if v == current_interval), "1日")
        self.interval_combo.setCurrentText(current_text)
        
        interval_layout.addWidget(self.interval_combo)
        interval_layout.addStretch()
        layout.addLayout(interval_layout)
        
        layout.addStretch()
        self.tabs.addTab(tab, "UI設定")

    def _setup_about_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.about_title_lbl = QLabel()
        self.about_title_lbl.setFont(QFont("Helvetica", 14, QFont.Weight.Bold))
        self.about_title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.about_title_lbl)
        self.update_about_tab_version_label()
        
        copyright_lbl = QLabel("© 2026 Fuku856 All rights reserved.\nCreated by Fuku856\nLicense: MIT License")
        copyright_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(copyright_lbl)
        
        repo_lbl = QLabel("Repository:")
        repo_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(repo_lbl)
        
        link_lbl = QLabel(f'<a href="{config.REPO_URL}">{config.REPO_URL}</a>')
        link_lbl.setOpenExternalLinks(True)
        link_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(link_lbl)
        
        self.tabs.addTab(tab, "アプリについて")

    def _setup_updates_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        self.current_version_lbl = QLabel(f"現在のバージョン: v{config.APP_VERSION}")
        layout.addWidget(self.current_version_lbl)
        
        self.latest_version_lbl = QLabel("最新バージョン: (未取得)")
        layout.addWidget(self.latest_version_lbl)
        
        self.check_update_btn = QPushButton("最新情報を取得する")
        self.check_update_btn.clicked.connect(self.manager.check_for_updates)
        layout.addWidget(self.check_update_btn)
        
        layout.addWidget(QLabel("リリースノート:"))
        
        self.release_text_area = QTextEdit()
        self.release_text_area.setReadOnly(True)
        layout.addWidget(self.release_text_area)
        
        self.updates_tab_index = self.tabs.addTab(tab, "更新情報")

    def _on_tab_changed(self, index):
        if index == self.updates_tab_index:
            if not self.manager._update_info_fetched:
                if config.APP_VERSION.lower() in ("dev", "vdev"):
                    self.manager.emitter.release_info_updated.emit("スキップ", "開発バージョンのため、自動取得をスキップしました。")
                else:
                    self.manager.check_for_updates()

    def _update_checkboxes_state(self, *args):
        token = self.token_entry.text().strip()
        is_valid_jwt = len(token.split('.')) == 3
        subscribed_in_token = []
        
        if is_valid_jwt:
            try:
                parts = token.split('.')
                payload_b64 = parts[1]
                payload_b64 += "=" * ((4 - len(payload_b64) % 4) % 4)
                payload_json = base64.urlsafe_b64decode(payload_b64).decode('utf-8')
                
                for ch in self.channel_widgets.keys():
                    if ch in payload_json:
                        subscribed_in_token.append(ch)
            except Exception:
                pass
                
        for ch, chk_widget in self.channel_widgets.items():
            is_subscribed = is_valid_jwt and ch in subscribed_in_token
            
            chk_widget.setEnabled(is_subscribed)
            lbl_widget = self.channel_labels.get(ch)
            
            if is_subscribed:
                if lbl_widget: lbl_widget.setStyleSheet("color: #888888; font-size: 11px;")
            else:
                if lbl_widget: lbl_widget.setStyleSheet("color: #555555; font-size: 11px;")
                if is_valid_jwt:
                    chk_widget.setChecked(False)

    def save_settings(self):
        new_token = self.token_entry.text().strip()
        selected_channels = [ch for ch, w in self.channel_widgets.items() if w.isChecked()]
        
        config.set_channels(selected_channels)
        config.set_token(new_token)
        config.set_show_popup(self.show_popup_var.isChecked())
        config.set_auto_open_log(self.auto_open_log_var.isChecked())
        config.set_popup_timeout(self.timeout_options[self.timeout_combo.currentText()])
        config.set_check_update_on_startup(self.check_startup_var.isChecked())
        
        selected_interval = self.interval_combo.currentText()
        config.set_auto_update_interval_days(self.interval_options[selected_interval])
        
        config.set_theme_mode(self.theme_combo.currentText())
        self.manager.apply_theme() # Apply theme immediately
        
        self.manager.client.restart()
        self.hide()

    def update_about_tab_version_label(self):
        base_text = f"{config.APP_NAME} v{config.APP_VERSION}"
        if config.APP_VERSION.lower() in ("dev", "vdev"):
            self.about_title_lbl.setText(base_text + " (開発版)")
        elif self.manager.is_latest_version is True:
            self.about_title_lbl.setText(base_text + " (最新)")
        elif self.manager.is_latest_version is False:
            self.about_title_lbl.setText(base_text + " (アップデートあり)")
        else:
            self.about_title_lbl.setText(base_text)

    def closeEvent(self, event):
        event.ignore()
        self.hide()


class UIManager(QObject):
    tray_icon_update_requested = Signal(QIcon)

    def __init__(self, axis_client, app):
        super().__init__()
        self.client = axis_client
        self.app = app
        
        self.emitter = SignalEmitter()
        self.emitter.log_appended.connect(self._handle_append_log)
        self.emitter.status_updated.connect(self._handle_status_update)
        self.emitter.release_info_updated.connect(self._handle_release_info)
        
        self.popup_manager = PopupManager(self)
        
        self.log_window = LogWindow(self)
        self.settings_window = SettingsWindow(self)
        
        self.apply_theme()
        
        self.is_latest_version = None
        self._update_info_fetched = False
        
        QTimer.singleShot(1000, lambda: self.start_background_update_checker(is_startup=True))

    def _generate_checkmark_file(self, color_hex, filename):
        path = os.path.join(config.get_config_dir(), filename).replace('\\', '/')
        if os.path.exists(path):
            return path
            
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(color_hex))
        pen.setWidth(2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawLine(4, 8, 7, 11)
        painter.drawLine(7, 11, 12, 6)
        painter.end()
        
        pixmap.save(path, "PNG")
        return path

    def apply_theme(self):
        mode = config.get_theme_mode()
        
        # High visibility blue accent
        accent_color = "#0A84FF" if mode == "dark" else "#0078D7"
        
        if mode == "dark":
            bg_color = "#1E1E1E"
            fg_color = "#D4D4D4"
            base_color = "#2D2D30"
            border_color = "#3E3E42"
            hover_color = border_color
            disabled_fg = "#777777"
            disabled_bg = "#2A2A2A"
            disabled_border = "#444444"
        else:
            bg_color = "#F3F3F3"
            fg_color = "#000000"
            base_color = "#FFFFFF"
            border_color = "#CCCCCC"
            hover_color = "#D6E8FA"
            disabled_fg = "#AAAAAA"
            disabled_bg = "#EAEAEA"
            disabled_border = "#CCCCCC"
            
        chk_path = self._generate_checkmark_file("#FFFFFF", "axis_chk_active.png")
        chk_dis_path = self._generate_checkmark_file("#888888", "axis_chk_disabled.png")
            
        qss = f"""
        QWidget {{
            background-color: {bg_color};
            color: {fg_color};
            font-family: "Segoe UI", sans-serif;
            font-size: 13px;
        }}
        QMainWindow, QDialog {{
            background-color: {bg_color};
        }}
        QTextEdit, QLineEdit, QComboBox, QScrollArea {{
            background-color: {base_color};
            color: {fg_color};
            border: 1px solid {border_color};
            border-radius: 4px;
            padding: 4px;
        }}
        QPushButton {{
            background-color: {base_color};
            color: {fg_color};
            border: 1px solid {border_color};
            border-radius: 4px;
            padding: 6px 15px;
        }}
        QPushButton:hover {{
            background-color: {hover_color};
        }}
        QPushButton[primary="true"] {{
            background-color: {accent_color};
            color: white;
            border: none;
        }}
        QPushButton[primary="true"]:hover {{
            background-color: #005A9E;
        }}
        QTabWidget::pane {{
            border: 1px solid {border_color};
            border-radius: 4px;
            top: -1px;
        }}
        QTabBar::tab {{
            background-color: {bg_color};
            border: 1px solid {border_color};
            border-bottom: none;
            border-top-left-radius: 4px;
            border-top-right-radius: 4px;
            padding: 6px 12px;
            margin-right: 2px;
        }}
        QTabBar::tab:selected {{
            background-color: {base_color};
            border-bottom: 2px solid {accent_color};
        }}
        QCheckBox::indicator {{
            width: 16px;
            height: 16px;
            border: 1px solid {border_color};
            border-radius: 3px;
            background-color: {base_color};
        }}
        QCheckBox::indicator:disabled {{
            background-color: {disabled_bg};
            border-color: {disabled_border};
        }}
        QCheckBox:disabled {{
            color: {disabled_fg};
        }}
        QCheckBox::indicator:checked {{
            background-color: {accent_color};
            border-color: {accent_color};
            image: url("{chk_path}");
        }}
        QCheckBox::indicator:checked:disabled {{
            background-color: {disabled_border};
            border-color: {disabled_border};
            image: url("{chk_dis_path}");
        }}
        QMenu {{
            background-color: {base_color};
            color: {fg_color};
            border: 1px solid {border_color};
        }}
        QMenu::item:selected {{
            background-color: {accent_color};
            color: white;
        }}
        QPushButton[navbtn="true"] {{
            padding: 2px;
        }}
        """
        self.app.setStyleSheet(qss)

        if hasattr(self, 'log_window'):
            self.log_window.search_toggle_btn.setIcon(_make_search_icon(fg_color))
        if hasattr(self, 'settings_window'):
            is_visible = self.settings_window.token_visibility_btn.isChecked()
            self.settings_window.token_visibility_btn.setIcon(
                _make_eye_icon(is_visible, fg_color)
            )

        # In case active popups need a style refresh, it's easier to recreate them, but here we just let them use their own inline styles which we evaluate on creation.

    def append_log(self, channel, message_data):
        self.emitter.log_appended.emit(channel, message_data)

    def update_status(self, status):
        self.emitter.status_updated.emit(status)

    @Slot(str, object)
    def _handle_append_log(self, channel, message_data):
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
            event_id, title, body = message_formatter.format_message(channel, message_data)
            url = message_data.get("url", None) if isinstance(message_data, dict) else None
            text = f"[{timestamp}] [{channel}]\n{title}\n{body}\n"
            if url:
                text += f"URL: {url}\n"
            text += "-" * 40 + "\n"
            
            # Windowsネイティブ通知 (右下)
            notifier.show_toast(title, f"新しい情報を受信しました\n受信: {timestamp}", url)
            
            if config.get_auto_open_log():
                self.show_log_window()
                
            # PySide6 カスタムポップアップ (右上)
            if config.get_show_popup():
                self.popup_manager.show_popup(event_id, title, body, url, timestamp)

        self.log_window.append_entry(text, self._get_channel_color(channel))

    @Slot(str)
    def _handle_status_update(self, status):
        if self.settings_window.isVisible():
            self.settings_window.status_label.setText(f"状態: {status}")
        self.tray_icon_update_requested.emit(self._generate_status_icon(status))

    def _get_channel_color(self, channel: str) -> str:
        mode = config.get_theme_mode()
        colors_dark = {
            "breaking-news": "#FF6B6B",
            "システム": "#9E9E9E",
            "パースエラー": "#FFA726",
        }
        colors_light = {
            "breaking-news": "#C62828",
            "システム": "#757575",
            "パースエラー": "#E65100",
        }
        colors = colors_dark if mode == "dark" else colors_light
        return colors.get(channel, "#4FC3F7" if mode == "dark" else "#1565C0")

    def _generate_status_icon(self, status: str) -> QIcon:
        if "オンライン" in status:
            dot_color = "#4CAF50"
        elif any(k in status for k in ("サーバ取得中", "接続中", "接続確立", "切断されました")):
            dot_color = "#FFC107"
        else:
            dot_color = "#F44336"

        base_icon = get_icon()
        if not base_icon.isNull():
            base_pixmap = base_icon.pixmap(64, 64)
        else:
            base_pixmap = QPixmap(64, 64)
            base_pixmap.fill(QColor("#0078D7"))
            p = QPainter(base_pixmap)
            p.setPen(QColor("#FFFFFF"))
            p.setFont(QFont("Arial", 28, QFont.Weight.Bold))
            p.drawText(base_pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "A")
            p.end()

        result = QPixmap(64, 64)
        result.fill(Qt.GlobalColor.transparent)
        painter = QPainter(result)
        painter.drawPixmap(0, 0, base_pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        dot_size = 18
        x = 64 - dot_size - 2
        y = 64 - dot_size - 2
        border_color = "#1E1E1E" if config.get_theme_mode() == "dark" else "#F3F3F3"
        painter.setBrush(QColor(border_color))
        painter.drawEllipse(x - 2, y - 2, dot_size + 4, dot_size + 4)
        painter.setBrush(QColor(dot_color))
        painter.drawEllipse(x, y, dot_size, dot_size)
        painter.end()
        return QIcon(result)

    def show_log_window(self):
        self.log_window.showNormal()
        self.log_window.raise_()
        self.log_window.activateWindow()

    def show_settings_window(self):
        self.settings_window.showNormal()
        self.settings_window.raise_()
        self.settings_window.activateWindow()

    def send_test_notification(self):
        from datetime import datetime
        test_data = {
            "title": f"テスト速報 ({datetime.now().strftime('%H:%M:%S')})",
            "body": "これは通知と表示のテストです。正常に動作しています。",
            "url": "https://axis.prioris.jp/"
        }
        self.append_log("breaking-news", test_data)

    def start_background_update_checker(self, is_startup=False):
        if is_startup and config.get_check_update_on_startup():
            threading.Thread(target=self._fetch_latest_release, args=(False,), daemon=True).start()
        
        QTimer.singleShot(3600000, lambda: self.start_background_update_checker(is_startup=False))
        
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

    def check_for_updates(self):
        is_dev = config.APP_VERSION.lower() in ("dev", "vdev")
        if is_dev:
            res = QMessageBox.warning(
                self.settings_window, 
                "警告", 
                "ローカル版（開発版）のため、更新確認時に予期せぬエラーが発生する可能性があります。\n\n続行しますか？",
                QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel
            )
            if res != QMessageBox.StandardButton.Ok:
                return

        self.settings_window.check_update_btn.setEnabled(False)
        self.settings_window.latest_version_lbl.setText("最新バージョン: 取得中...")
        self.settings_window.release_text_area.setPlainText("情報を取得しています...\n")

        threading.Thread(target=self._fetch_latest_release, args=(True, is_dev), daemon=True).start()

    def _fetch_latest_release(self, is_manual=False, force=False):
        if config.APP_VERSION.lower() in ("dev", "vdev") and not force:
            if is_manual:
                self.emitter.release_info_updated.emit("スキップ", "開発バージョンのため、最新情報の取得をスキップしました。")
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
                
                if not is_manual:
                    config.set_last_update_check_time(datetime.now().isoformat())
                    
                self.emitter.release_info_updated.emit(tag_name, body)
        except Exception as e:
            if is_manual:
                self.emitter.release_info_updated.emit("取得失敗", f"エラーが発生しました:\n{e}")

    @Slot(str, str)
    def _handle_release_info(self, tag_name, body):
        if tag_name != "取得失敗":
            self._update_info_fetched = True
            
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
                self.settings_window.update_about_tab_version_label()
                
                if not is_latest:
                    self.show_update_prompt(tag_name)
            except Exception as e:
                print(f"Version comparison error: {e}")

        self.settings_window.latest_version_lbl.setText(f"最新バージョン: {tag_name}")
        self.settings_window.release_text_area.setMarkdown(body)
        self.settings_window.check_update_btn.setEnabled(True)

    def show_update_prompt(self, tag_name):
        msg_box = QMessageBox(self.settings_window)
        msg_box.setWindowTitle("アップデート通知")
        msg_box.setText(f"新しいバージョン ({tag_name}) が利用可能です。\n更新しますか？")
        msg_box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        
        open_btn = msg_box.addButton("リリースページを開く", QMessageBox.ButtonRole.ActionRole)
        cancel_btn = msg_box.addButton("後で", QMessageBox.ButtonRole.RejectRole)
        
        msg_box.exec()
        
        if msg_box.clickedButton() == open_btn:
            repo_url = config.REPO_URL.rstrip('/')
            webbrowser.open(f"{repo_url}/releases/latest")
