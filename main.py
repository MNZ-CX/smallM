#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""悬浮日历备忘 · 单文件版（PyQt6）—— 布局 / 圆点点击 / 滚动列表 三大 Bug 修复版

========================= 本轮针对性修复 =========================
【Bug 1】顶部 5 色圆点点不动
    · 圆点改为真正的 QPushButton（PageDot），带 PointingHandCursor 与 QButtonGroup 互斥；
    · 顶栏拖拽改为"阈值式"：按下只记录起点，移动超过 5px 才进入系统拖拽，
      且子控件（圆点/图标按钮）自身消费鼠标事件，顶栏绝不偷点击。

【Bug 2】画布区域错位、压在月历上
    · 删除全部子控件绝对定位（不使用任何 setGeometry / move 摆放子控件），
      窗口几何动画也一并删除；
    · 层级严格自上而下：顶栏 ➔ 画布 ➔ 可折叠月历 ➔ 日程输入框 ➔ 多条目滚动列表 ➔ 撤销条 ➔ 状态栏；
    · 窗口尺寸固定（按"月历展开"的最大需求预留），展开月历时画布平滑收缩让位，
      下方组件位置稳定不变，任何情况下都不会与月历重叠。

【Bug 3】待办多于 2 条看不到 / 滚不动
    · 列表 = QScrollArea(setWidgetResizable(True)) + 垂直布局，卡片固定高度、自适应宽度；
    · 严格套用规范滚动条 QSS（6px 宽 / #16181d 轨道 / #334155 滑块）；
    · 3 条、5 条乃至 20 条都可滚轮顺滑滚动，最后一条完整可见。

========================= 视觉与交互规范 =========================
主背景 #0d0e11 · 卡片/输入框 #16181d · 边框 #2d3139（聚焦 #3b82f6）· 文字 #e2e8f0
无边框 + 14px 圆角 + 20px 弥散阴影；PureRef 式防打扰（移出 0.35 / 移入 150ms 恢复 1.0）
回车提交后输入框瞬间清空 + 0.8s「已保存 ✓」绿字；删除秒删 + 底部 3 秒悬浮撤销条；
全部数据即时落盘 memos.json，启动秒开恢复。已移除 Git / 剪贴板 / OCR / 文件拖拽。
"""

from __future__ import annotations

import ctypes
import html
import json
import os
import re
import shutil
import subprocess
import sys
from ctypes import wintypes
from datetime import date, datetime, timedelta

from PyQt6.QtCore import (
    QAbstractAnimation,
    QAbstractNativeEventFilter,
    QEasingCurve,
    QEvent,
    QObject,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QGuiApplication,
    QIcon,
    QKeySequence,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QSystemTrayIcon,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# ==========================================================================
# §1 常量与设计令牌
# ==========================================================================
APP_NAME = "悬浮日历备忘"
APP_ID = "FloatingCalendar.Memo"


def application_dir() -> str:
    """数据目录：打包成 exe 后取 exe 所在目录。

    PyInstaller 单文件模式会把脚本解包到临时目录（sys._MEIPASS），
    若把 memos.json 写在 __file__ 旁边，退出时会随临时目录一起被删除，
    因此冻结运行必须改用 sys.executable 所在目录。
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


APP_DIR = application_dir()
DATA_FILE = os.path.join(APP_DIR, "memos.json")
CACHE_DIR = os.path.join(APP_DIR, ".cache")

CANVAS_COUNT = 5
DOT_COLORS = ["#ef4444", "#f59e0b", "#10b981", "#3b82f6", "#8b5cf6"]

WINDOW_W = 420
WINDOW_H_PREFERRED = 820   # 首次启动的默认高度（之后由用户自行调整并记忆）
WINDOW_MIN_W = 380
WINDOW_MIN_H = 460
CANVAS_MIN_H = 88          # 画布最小高度（自适应时会收缩到这个值）
LIST_VIEW_MIN_H = 132      # 日程列表最小高度（其余空间由它吸收）
CARD_H = 38                # 单条日程卡片固定高度（宽自适应）
TOAST_H = 46               # 撤销条高度
STATUS_H = 22              # 底栏高度
BODY_MARGINS = 14          # 主体上下内边距合计
DRAG_THRESHOLD = 5         # 顶栏拖拽触发阈值（像素）
RESIZE_MARGIN = 14         # 无边框窗口边缘可拖拽缩放的范围（透明外边距内）
CAL_CELL_MIN = 20          # 月历日期格最小/最大高度（按可用空间自适应）
CAL_CELL_MAX = 34
AUTOFIT_DEFAULT = True     # 画布高度随内容自适应（用户拖动分割条即自动关闭）

PAGE_FADE_MS = 75          # 单程；切页合计 150ms
CALENDAR_ANIM_MS = 220
TOAST_ANIM_MS = 150
UNDO_TIMEOUT_MS = 3000
SAVED_FLASH_MS = 800       # 「已保存 ✓」绿字时长
FADE_OUT_OPACITY = 0.35
FADE_OUT_MS = 240
FADE_IN_MS = 150
FADE_SKIP_WHEN_TYPING = True
REMINDER_POLL_MS = 10000   # 到点提醒轮询周期（10 秒内必触发）
SNOOZE_MINUTES = 10
HOTKEY = "Alt+Q"

BG = "#0d0e11"
CARD = "#16181d"
BORDER = "#2d3139"
BORDER_HOVER = "#3a4150"
FOCUS = "#3b82f6"
TEXT = "#e2e8f0"
TEXT_DIM = "#94a3b8"
TEXT_FAINT = "#5b6472"
OK = "#10b981"
DANGER = "#ef4444"
SCROLL_HANDLE = "#334155"
GLOW_EDGE = "rgba(140,160,255,0.22)"
FONT_STACK = ('"Microsoft YaHei UI", "Segoe UI", "Segoe UI Emoji", "Segoe UI Symbol", '
              '"PingFang SC", sans-serif')
MONO_STACK = '"Cascadia Mono", "Consolas", monospace'

WEEKDAY_NAMES = ["一", "二", "三", "四", "五", "六", "日"]


def rgba(hex_color: str, alpha: int) -> str:
    """#rrggbb → rgba(r,g,b,a)，用于 QSS 半透明。"""
    color = QColor(hex_color)
    return f"rgba({color.red()},{color.green()},{color.blue()},{alpha})"


# ==========================================================================
# §2 全局样式（强制深色，杜绝任何亮白底）
# ==========================================================================
def build_qss(check_icon: str) -> str:
    return f"""
* {{ outline: 0; }}
QWidget {{
    background: transparent;
    color: {TEXT};
    font-family: {FONT_STACK};
    font-size: 13px;
}}

/* ---- 输入 / 文本 / 列表 / 滚动区：一律强制 #16181d ---- */
QLineEdit, QTextEdit, QPlainTextEdit, QListWidget, QListView, QAbstractItemView,
QScrollArea, QAbstractScrollArea {{
    background-color: {CARD};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 10px;
    selection-background-color: {FOCUS};
    selection-color: #ffffff;
}}
QLineEdit {{ padding: 8px 11px; }}
QTextEdit, QPlainTextEdit {{ padding: 11px 13px; }}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{ border: 1px solid {FOCUS}; }}
QLineEdit:disabled, QTextEdit:disabled {{ color: {TEXT_FAINT}; }}
QScrollArea {{ border: none; background-color: {CARD}; }}
QScrollArea > QWidget {{ background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollArea > QWidget > QScrollBar {{ background: transparent; }}
QAbstractScrollArea::corner {{ background: {CARD}; }}
QStackedWidget {{ background: transparent; }}

/* ---- 外壳：14px 圆角 + 1px 边框（ShadowLayer 只承担阴影，Root 承担内容） ---- */
#ShadowLayer {{ background: {BG}; border: 1px solid {BORDER}; border-radius: 14px; }}
#Root {{ background: {BG}; border: 1px solid {BORDER}; border-radius: 14px; }}
#CaptureRoot {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 14px; }}
#CaptureShadow {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 14px; }}

/* ---- 顶栏 ---- */
#TopBar {{ background: transparent; }}
#IconBtn {{ background: transparent; border: none; color: {TEXT_DIM};
            border-radius: 8px; font-size: 13px; padding: 0px; }}
#IconBtn:hover {{ background: rgba(255,255,255,0.07); color: {TEXT}; }}
#IconBtn[active="true"] {{ background: rgba(59,130,246,0.18); color: #93b4fb; }}
#IconBtn[close="true"]:hover {{ background: rgba(239,68,68,0.18); color: #fca5a5; }}

/* ---- 画布：视觉交给外层卡片，内层 QTextEdit 只负责文字 ----
   （QTextEdit 自带 stylesheet 边框/内边距时，文字与占位符在部分重绘路径下会整体偏移，
     拆分后彻底消除"错位/偏移"问题） */
#CanvasPage {{ background-color: {CARD}; border: 1px solid {BORDER}; border-radius: 14px; }}
#CanvasPage[focused="true"] {{ border: 1px solid {FOCUS}; }}
#Canvas {{ background: transparent; border: none; border-radius: 0px;
           padding: 0px; margin: 0px; font-size: 14px; color: {TEXT}; }}

/* ---- 面板 / 卡片 ---- */
#Panel {{ background-color: {CARD}; border: 1px solid {BORDER}; border-radius: 14px; }}
#PanelTitle {{ color: {TEXT}; font-size: 13px; font-weight: 700; }}
#PanelMeta {{ color: {TEXT_FAINT}; font-size: 11px; }}
#GhostBtn {{ background: transparent; border: none; color: {TEXT_DIM};
             border-radius: 8px; padding: 4px 8px; font-size: 12px; }}
#GhostBtn:hover {{ background: rgba(255,255,255,0.07); color: {TEXT}; }}
#AddBtn {{ background: {FOCUS}; color: #ffffff; border: none; border-radius: 10px;
           padding: 8px 15px; font-weight: 700; }}
#AddBtn:hover {{ background: #2f74e0; }}
#AddBtn:pressed {{ background: #2563eb; }}
#SavedFlash {{ color: {OK}; font-size: 12px; font-weight: 700; }}
#HintText {{ color: {TEXT_FAINT}; font-size: 11px; }}
#EmptyHint {{ color: {TEXT_FAINT}; font-size: 12px; }}

/* ---- 日程卡片 ---- */
#SchedCard {{ background: rgba(255,255,255,0.035); border: 1px solid {BORDER};
              border-radius: 10px; }}
#SchedCard:hover {{ background: rgba(255,255,255,0.062); border-color: {BORDER_HOVER}; }}
#SchedCard[done="true"] {{ background: rgba(255,255,255,0.02); }}
#SchedCard[fresh="true"] {{ background: rgba(59,130,246,0.10); border: 1px solid {FOCUS}; }}
#SchedText {{ color: {TEXT}; font-size: 13px; }}
#SchedText[done="true"] {{ color: {TEXT_FAINT}; }}
#TimeChip {{ background: rgba(59,130,246,0.16); color: #93b4fb; border-radius: 7px;
             padding: 2px 7px; font-family: {MONO_STACK}; font-size: 11px; }}
#TimeChip[plain="true"] {{ background: rgba(255,255,255,0.06); color: {TEXT_DIM}; }}
#TimeChip[overdue="true"] {{ background: rgba(239,68,68,0.16); color: #fca5a5; }}
#DelBtn {{ background: transparent; border: none; color: {TEXT_FAINT};
           border-radius: 7px; font-size: 12px; padding: 0px; }}
#DelBtn:hover {{ background: rgba(239,68,68,0.18); color: #fca5a5; }}

/* ---- 复选框 ---- */
QCheckBox {{ background: transparent; spacing: 0px; }}
QCheckBox::indicator {{ width: 17px; height: 17px; border-radius: 5px;
                        border: 1px solid #3a4150; background-color: #0f1116; }}
QCheckBox::indicator:hover {{ border-color: {FOCUS}; }}
QCheckBox::indicator:checked {{ background-color: {FOCUS}; border: 1px solid {FOCUS};
                                image: url("{check_icon}"); }}
QCheckBox::indicator:checked:hover {{ background-color: #2f74e0; border-color: #2f74e0; }}

/* ---- 底部撤销条 ---- */
#UndoToast {{ background: #1b1f27; border: 1px solid {BORDER}; border-radius: 12px; }}
#UndoText {{ color: {TEXT}; font-size: 12px; }}
#UndoBtn {{ background: rgba(59,130,246,0.18); color: #93b4fb; border: none;
            border-radius: 8px; padding: 5px 12px; font-size: 12px; font-weight: 700; }}
#UndoBtn:hover {{ background: rgba(59,130,246,0.30); }}
#UndoProgress {{ background: {FOCUS}; }}

/* ---- 月历 ---- */
#CalendarPanel {{ background: transparent; }}
#MonthLabel {{ color: {TEXT}; font-size: 13px; font-weight: 700; }}
#WeekLabel {{ color: {TEXT_FAINT}; font-size: 11px; }}
#DayHeader {{ color: {TEXT_FAINT}; font-size: 11px; }}

/* ---- 分割条：画布与下方区域之间，可上下拖动调整 ---- */
QSplitter::handle:vertical {{
    background: transparent; height: 10px; margin: 2px 40px;
    border-radius: 4px;
}}
QSplitter::handle:vertical:hover {{ background: rgba(59,130,246,0.35); }}
QSplitter::handle:vertical:pressed {{ background: rgba(59,130,246,0.6); }}

/* ---- 右下角缩放抓手 ---- */
#ResizeGrip {{ background: transparent; }}
#ResizeGrip:hover {{ background: rgba(59,130,246,0.18); border-radius: 5px; }}

/* ---- 到点提醒：全屏居中覆盖浮层 ---- */
#ReminderOverlay {{ background: rgba(6,8,12,0.74); }}
#ReminderCard {{ background: {CARD}; border: 1px solid {GLOW_EDGE}; border-radius: 16px; }}
#ReminderTitle {{ color: {TEXT}; font-size: 15px; font-weight: 700; }}
#ReminderClock {{ color: #93b4fb; font-size: 24px; font-weight: 700; font-family: {MONO_STACK}; }}
#ReminderMeta {{ color: {TEXT_FAINT}; font-size: 12px; }}
#ReminderItem {{ color: {TEXT}; font-size: 15px; }}
#ReminderItem[done="true"] {{ color: {TEXT_FAINT}; }}
#ReminderHint {{ color: {TEXT_FAINT}; font-size: 11px; }}
#ReminderDivider {{ background: {BORDER}; }}

/* ---- 月历悬停预览浮层 ---- */
#DayPreview {{ background: #1b1f27; border: 1px solid {GLOW_EDGE}; border-radius: 12px; }}
#PreviewTitle {{ color: {TEXT}; font-size: 12px; font-weight: 700; }}
#PreviewMeta {{ color: {TEXT_FAINT}; font-size: 11px; }}
#PreviewItem {{ color: {TEXT}; font-size: 12px; }}
#PreviewItem[done="true"] {{ color: {TEXT_FAINT}; }}
#PreviewEmpty {{ color: {TEXT_FAINT}; font-size: 11px; }}

/* ---- 滚动条：严格按规范（6px / #16181d / #334155） ---- */
QScrollBar:vertical {{
    width: 6px; background: {CARD}; border-radius: 3px; margin: 0px;
}}
QScrollBar::handle:vertical {{
    background: {SCROLL_HANDLE}; border-radius: 3px; min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: #475569; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px; width: 0px; background: none; border: none;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{ height: 6px; background: {CARD}; border-radius: 3px; }}
QScrollBar::handle:horizontal {{ background: {SCROLL_HANDLE}; border-radius: 3px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    height: 0px; width: 0px; background: none; border: none;
}}

/* ---- 菜单 / 提示 ---- */
QMenu {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 6px 20px 6px 14px; border-radius: 7px; color: {TEXT}; }}
QMenu::item:selected {{ background: rgba(59,130,246,0.18); color: #93b4fb; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 5px 8px; }}
QToolTip {{ background: {CARD}; color: {TEXT}; border: 1px solid {BORDER};
            border-radius: 8px; padding: 5px 8px; }}
"""


def dark_palette() -> QPalette:
    """深色调色板兜底：任何未被 QSS 命中的控件也不会露出系统白底。"""
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(BG))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(CARD))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(BG))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(TEXT_FAINT))
    palette.setColor(QPalette.ColorRole.Button, QColor(CARD))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Link, QColor(FOCUS))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(FOCUS))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#0b0d11"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(CARD))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText,
                 QPalette.ColorRole.WindowText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(TEXT_FAINT))
    return palette


# ==========================================================================
# §3 通用小工具
# ==========================================================================
DAY_FMT = "%Y-%m-%d"


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_str() -> str:
    return date.today().strftime(DAY_FMT)


def day_of(stamp: str) -> str:
    return (stamp or "")[:10]


def clear_layout(layout) -> None:
    """彻底销毁布局内控件，杜绝残影与悬挂引用。"""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()


def repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def soft_shadow(widget: QWidget, blur: int = 20, dy: int = 8, alpha: int = 190) -> None:
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, dy)
    effect.setColor(QColor(0, 0, 0, alpha))
    widget.setGraphicsEffect(effect)


def emoji_font(size: int = 13) -> QFont:
    font = QFont()
    font.setFamilies(["Segoe UI Emoji", "Segoe UI Symbol", "Microsoft YaHei UI", "Segoe UI"])
    font.setPixelSize(size)
    return font


def log(message: str) -> None:
    """安全输出：--windowed 打包后 sys.stdout 为 None，直接 print 会抛异常。"""
    try:
        if sys.stdout is not None:
            print(message, flush=True)
    except (AttributeError, OSError, ValueError):
        pass


def play_reminder_sound() -> None:
    """到点提示音（异步，不阻塞界面）。"""
    if os.name == "nt":
        try:
            import winsound

            winsound.PlaySound("SystemExclamation",
                               winsound.SND_ALIAS | winsound.SND_ASYNC)
            return
        except Exception:  # noqa: BLE001 - 播放失败不应影响提醒
            pass
    QApplication.beep()


def ensure_check_icon() -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, "check.png")
    pixmap = QPixmap(17, 17)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor("#ffffff"), 2.1)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.drawLine(4, 9, 7, 12)
    painter.drawLine(7, 12, 13, 5)
    painter.end()
    pixmap.save(path, "PNG")
    return path.replace("\\", "/")


def app_icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(CARD))
    painter.drawRoundedRect(0, 0, 64, 64, 14, 14)
    painter.setBrush(QColor(FOCUS))
    painter.drawRoundedRect(10, 12, 44, 11, 5, 5)
    painter.setBrush(QColor("#232833"))
    painter.drawRoundedRect(10, 29, 44, 23, 5, 5)
    for index, color in enumerate(DOT_COLORS[:3]):
        painter.setBrush(QColor(color))
        painter.drawEllipse(17 + index * 12, 35, 7, 7)
    painter.end()
    return QIcon(pixmap)


# ==========================================================================
# §4 数据层：即时落盘 + 旧数据迁移 + 撤销载荷
# ==========================================================================
class DataStore:
    """memos.json 唯一读写入口；任何改动立即原子写入，无防抖延迟。"""

    def __init__(self, path: str = DATA_FILE):
        self.path = path
        self.data = self._blank()
        self.last_saved = ""
        self.load()

    @staticmethod
    def _blank() -> dict:
        return {
            "version": 6,
            "canvases": [{"color": color, "text": ""} for color in DOT_COLORS],
            "schedules": [],
            "snapshots": {},
            "settings": {
                "active_canvas": 0,
                "selected_date": today_str(),
                "fade_lock": False,
                "window_pos": None,
                "window_size": None,
                "split": None,
                "autofit": AUTOFIT_DEFAULT,
                "tray_hinted": False,
            },
        }

    def load(self) -> None:
        self.data = self._blank()
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except (OSError, json.JSONDecodeError):
            raw = None
        if not isinstance(raw, dict):
            return

        canvases = raw.get("canvases")
        if isinstance(canvases, list):
            for index, item in enumerate(canvases[:CANVAS_COUNT]):
                if isinstance(item, dict):
                    self.data["canvases"][index]["text"] = str(item.get("text") or "")

        rows = raw.get("schedules")
        if not isinstance(rows, list):
            rows = raw.get("todos") if isinstance(raw.get("todos"), list) else []
        for item in rows:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            self.data["schedules"].append({
                "id": int(item.get("id") or 0),
                "text": text,
                "time": str(item.get("time") or ""),
                "date": str(item.get("date") or today_str()),
                "done": bool(item.get("done")),
                "done_at": str(item.get("done_at") or ""),
                "notified": bool(item.get("notified")),
                "created": str(item.get("created") or now_str()),
            })
        next_id = max((row["id"] for row in self.data["schedules"]), default=0) + 1
        for row in self.data["schedules"]:
            if row["id"] <= 0:
                row["id"] = next_id
                next_id += 1
        self._next_id = next_id

        snapshots = raw.get("snapshots")
        if isinstance(snapshots, dict):
            for day, per in snapshots.items():
                if isinstance(per, dict):
                    self.data["snapshots"][str(day)] = {
                        str(key): str(value) for key, value in per.items()
                        if isinstance(value, str) and value.strip()
                    }
        settings = raw.get("settings")
        if isinstance(settings, dict):
            for key in self.data["settings"]:
                if key in settings:
                    self.data["settings"][key] = settings[key]

    def save(self) -> bool:
        tmp = f"{self.path}.tmp"
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(self.data, handle, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except OSError:
            return False
        self.last_saved = datetime.now().strftime("%H:%M:%S")
        return True

    @property
    def settings(self) -> dict:
        return self.data["settings"]

    def set_setting(self, key: str, value) -> None:
        if self.data["settings"].get(key) != value:
            self.data["settings"][key] = value
            self.save()

    # ---------------- 画布 ----------------
    def canvas_text(self, index: int) -> str:
        if 0 <= index < len(self.data["canvases"]):
            return self.data["canvases"][index]["text"]
        return ""

    def set_canvas_text(self, index: int, text: str) -> None:
        if not 0 <= index < len(self.data["canvases"]):
            return
        canvas = self.data["canvases"][index]
        if canvas["text"] == text:
            return
        canvas["text"] = text
        per = self.data["snapshots"].setdefault(today_str(), {})
        key = f"canvas_{index}"
        if text.strip():
            per[key] = text
        else:
            per.pop(key, None)
        self.save()

    # ---------------- 日程 ----------------
    def next_id(self) -> int:
        value = getattr(self, "_next_id", 1)
        self._next_id = value + 1
        return value

    def add_schedule(self, text: str, moment: str = "", day: str = "") -> dict:
        day = day or today_str()
        when = None
        if moment:
            try:
                when = datetime.strptime(f"{day} {moment}", "%Y-%m-%d %H:%M")
            except ValueError:
                when = None
        row = {
            "id": self.next_id(),
            "text": text.strip(),
            "time": moment,
            "date": day,
            "done": False,
            "done_at": "",
            "notified": bool(when and when < datetime.now()),
            "created": now_str(),
        }
        self.data["schedules"].append(row)
        self.save()
        return row

    def find(self, schedule_id: int) -> dict | None:
        return next((row for row in self.data["schedules"] if row["id"] == schedule_id), None)

    def schedules_for(self, day: str) -> list[dict]:
        rows = [row for row in self.data["schedules"] if (row["date"] or today_str()) == day]
        return sorted(rows, key=lambda row: (1 if row["done"] else 0,
                                             row["time"] or "99:99", row["created"]))

    def toggle(self, schedule_id: int, done: bool | None = None) -> dict | None:
        row = self.find(schedule_id)
        if row is None:
            return None
        target = (not row["done"]) if done is None else bool(done)
        row["done"] = target
        row["done_at"] = now_str() if target else ""
        self.save()
        return row

    def delete(self, schedule_id: int) -> dict | None:
        for index, row in enumerate(self.data["schedules"]):
            if row["id"] == schedule_id:
                self.data["schedules"].pop(index)
                self.save()
                return {"kind": "schedule_delete", "index": index, "row": row}
        return None

    def restore(self, payload: dict) -> bool:
        if not payload:
            return False
        kind = payload.get("kind")
        if kind == "schedule_delete":
            index = max(0, min(payload["index"], len(self.data["schedules"])))
            self.data["schedules"].insert(index, payload["row"])
            self.save()
            return True
        if kind == "canvas_text":
            index = payload["index"]
            if not 0 <= index < len(self.data["canvases"]):
                return False
            self.data["canvases"][index]["text"] = payload["previous"]
            per = self.data["snapshots"].setdefault(today_str(), {})
            if payload["previous"].strip():
                per[f"canvas_{index}"] = payload["previous"]
            self.save()
            return True
        return False

    def heat_scores(self) -> dict[str, int]:
        scores: dict[str, int] = {}
        for row in self.data["schedules"]:
            created_day = day_of(row.get("created"))
            if created_day:
                scores[created_day] = scores.get(created_day, 0) + 2
            if row.get("date"):
                scores[row["date"]] = scores.get(row["date"], 0) + 1
            if row.get("done") and row.get("done_at"):
                done_day = day_of(row["done_at"])
                scores[done_day] = scores.get(done_day, 0) + 2
        for day, per in self.data["snapshots"].items():
            if per:
                scores[day] = scores.get(day, 0) + len(per)
        return scores

    def due_schedules(self, pointer: datetime | None = None) -> list[dict]:
        pointer = pointer or datetime.now()
        due = []
        for row in self.data["schedules"]:
            if row["done"] or row["notified"] or not row.get("time"):
                continue
            try:
                when = datetime.strptime(f"{row['date']} {row['time']}", "%Y-%m-%d %H:%M")
            except ValueError:
                continue
            if when <= pointer:
                due.append(row)
        return due

    def mark_notified(self, schedule_id: int) -> None:
        row = self.find(schedule_id)
        if row is not None:
            row["notified"] = True
            self.save()

    def snooze(self, schedule_id: int, minutes: int) -> dict | None:
        row = self.find(schedule_id)
        if row is None:
            return None
        when = datetime.now() + timedelta(minutes=minutes)
        row["date"] = when.strftime(DAY_FMT)
        row["time"] = when.strftime("%H:%M")
        row["notified"] = False
        self.save()
        return row


# ==========================================================================
# §5 自然输入解析
# ==========================================================================
_TIME_RE = re.compile(r"(?<!\d)(\d{1,2})\s*[:：]\s*(\d{2})(?!\d)")
_RELATIVE = {"今天": 0, "明天": 1, "后天": 2, "大后天": 3}
_PM_HINTS = ("下午", "晚上", "傍晚", "夜里")
_DATE_FULL_RE = re.compile(r"(\d{4})\s*[-/年]\s*(\d{1,2})\s*[-/月]\s*(\d{1,2})\s*日?")
_DATE_SHORT_RE = re.compile(r"(?<!\d)(\d{1,2})\s*[-/月]\s*(\d{1,2})\s*日?(?!\d)")


def parse_schedule(raw: str, base_day: str) -> dict:
    """解析一行日程输入 → {"date","time","text","explicit_day"}。"""
    text = (raw or "").strip()
    result = {"date": base_day or today_str(), "time": "", "text": text, "explicit_day": False}
    if not text:
        return result

    spans: list[tuple[int, int]] = []
    day: date | None = None
    relative = next((token for token in _RELATIVE if token in text), None)
    if relative:
        day = date.today() + timedelta(days=_RELATIVE[relative])
        start = text.index(relative)
        spans.append((start, start + len(relative)))
    else:
        match = _DATE_FULL_RE.search(text)
        if match:
            try:
                day = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
                spans.append(match.span())
            except ValueError:
                day = None
        else:
            match = _DATE_SHORT_RE.search(text)
            if match:
                try:
                    day = date(date.today().year, int(match.group(1)), int(match.group(2)))
                    spans.append(match.span())
                except ValueError:
                    day = None

    match = _TIME_RE.search(text)
    if match:
        hour, minute = int(match.group(1)), int(match.group(2))
        if hour <= 23 and minute <= 59:
            if hour <= 12 and any(hint in text for hint in _PM_HINTS):
                hour = hour + 12 if hour < 12 else 12
            result["time"] = f"{hour:02d}:{minute:02d}"
            spans.append(match.span())

    cleaned = text
    for start, end in sorted(spans, reverse=True):
        cleaned = cleaned[:start] + " " + cleaned[end:]
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -—:：,，。.、")
    result["text"] = cleaned or text
    if day is not None:
        result["date"] = day.strftime(DAY_FMT)
        result["explicit_day"] = True
    return result


# ==========================================================================
# §6 Windows 原生通知
# ==========================================================================
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

_TOAST_PS = r"""param([string]$T,[string]$B)
$ErrorActionPreference='Stop'
$aid=$env:MEMO_AUMID; $nm=$env:MEMO_APPNAME
try{
 $k="HKCU:\SOFTWARE\Classes\AppUserModelId\$aid"
 if(-not(Test-Path $k)){New-Item -Path $k -Force|Out-Null
  New-ItemProperty -Path $k -Name 'DisplayName' -Value $nm -PropertyType String -Force|Out-Null}
 [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime]|Out-Null
 [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType=WindowsRuntime]|Out-Null
 $x=@"
<toast scenario="reminder"><visual><binding template="ToastGeneric">
<text>$T</text><text>$B</text></binding></visual>
<audio src="ms-winsoundevent:Notification.Reminder"/></toast>
"@
 $d=New-Object Windows.Data.Xml.Dom.XmlDocument; $d.LoadXml($x)
 $t=New-Object Windows.UI.Notifications.ToastNotification $d
 [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($aid).Show($t)
 exit 0
}catch{exit 1}
"""


class Toaster:
    """系统通知：Windows 原生 Toast 优先，失败回退托盘气泡。"""

    def __init__(self, tray=None):
        self.tray = tray
        self.powershell = shutil.which("powershell.exe") if os.name == "nt" else None
        self.enabled = bool(self.powershell)
        self._script = self._write_script()

    def _write_script(self) -> str | None:
        try:
            os.makedirs(CACHE_DIR, exist_ok=True)
            path = os.path.join(CACHE_DIR, "toast.ps1")
            if not os.path.isfile(path) or open(path, "r", encoding="utf-8").read() != _TOAST_PS:
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(_TOAST_PS)
            return path
        except OSError:
            return None

    def send(self, title: str, body: str = "") -> str:
        if self.enabled and self._script:
            try:
                subprocess.Popen(
                    [self.powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
                     "Bypass", "-File", self._script, "-T", html.escape(title),
                     "-B", html.escape(body)],
                    env=dict(os.environ, MEMO_AUMID=APP_ID, MEMO_APPNAME=APP_NAME),
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=CREATE_NO_WINDOW, cwd=APP_DIR,
                )
                return "windows-toast"
            except OSError:
                pass
        if self.tray is not None:
            self.tray.showMessage(title, body or title,
                                  QSystemTrayIcon.MessageIcon.Information, 6000)
            return "tray"
        return "none"


# ==========================================================================
# §7 全局速记热键（Alt+Q）
# ==========================================================================
WM_HOTKEY = 0x0312
_MOD_ALT, _MOD_CONTROL, _MOD_SHIFT, _MOD_WIN, _MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
_HOTKEY_ID = 0xA11E


def parse_hotkey(combo: str) -> tuple[int, int] | None:
    mods, key = 0, None
    for part in (combo or "").replace(" ", "").split("+"):
        token = part.lower()
        if token == "alt":
            mods |= _MOD_ALT
        elif token in ("ctrl", "control"):
            mods |= _MOD_CONTROL
        elif token == "shift":
            mods |= _MOD_SHIFT
        elif token in ("win", "meta", "super"):
            mods |= _MOD_WIN
        elif len(part) == 1 and part.isalnum():
            key = ord(part.upper())
        elif token.startswith("f") and token[1:].isdigit() and 1 <= int(token[1:]) <= 24:
            key = 0x70 + int(token[1:]) - 1
    return (mods, key) if key is not None else None


class _HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, owner: "GlobalHotkey"):
        super().__init__()
        self._owner = owner

    def nativeEventFilter(self, event_type, message):  # noqa: N802
        try:
            if event_type in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
                msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
                if msg.message == WM_HOTKEY and int(msg.wParam) == self._owner.hotkey_id:
                    self._owner.activated.emit()
        except Exception:  # noqa: BLE001
            pass
        return False, 0


class GlobalHotkey(QObject):
    activated = pyqtSignal()

    def __init__(self, window, combo: str = HOTKEY):
        super().__init__(window)
        self._window = window
        self.combo = combo
        self.hotkey_id = _HOTKEY_ID
        self.registered = False
        self._filter: _HotkeyFilter | None = None
        self._hwnd = None

    def register(self) -> bool:
        if not sys.platform.startswith("win"):
            return False
        parsed = parse_hotkey(self.combo)
        if parsed is None:
            return False
        mods, key = parsed
        user32 = ctypes.windll.user32
        user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        user32.RegisterHotKey.restype = wintypes.BOOL
        self._hwnd = wintypes.HWND(int(self._window.winId()))
        if not user32.RegisterHotKey(self._hwnd, self.hotkey_id, mods | _MOD_NOREPEAT, key):
            return False
        app = QApplication.instance()
        if app is None:
            return False
        self._filter = _HotkeyFilter(self)
        app.installNativeEventFilter(self._filter)
        self.registered = True
        return True

    def unregister(self) -> None:
        if not self.registered:
            return
        try:
            ctypes.windll.user32.UnregisterHotKey(self._hwnd, self.hotkey_id)
        except Exception:  # noqa: BLE001
            pass
        app = QApplication.instance()
        if app is not None and self._filter is not None:
            app.removeNativeEventFilter(self._filter)
        self._filter = None
        self.registered = False


# ==========================================================================
# §8 顶栏：5 色圆点按钮 + 阈值式拖拽（绝不偷点击）
# ==========================================================================
class PageDot(QPushButton):
    """单个彩色切页圆点：真正的 QPushButton，手型光标，可点、可互斥选中。"""

    def __init__(self, index: int, color: str, parent=None):
        super().__init__(parent)
        self.index = index
        self.setCheckable(True)
        self.setAutoExclusive(False)
        self.setFixedSize(22, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip(f"切到画布 {index + 1} / {CANVAS_COUNT}")
        self.setStyleSheet(f"""
            QPushButton {{
                background: {rgba(color, 150)};
                border: 2px solid transparent;
                border-radius: 11px;
                padding: 0px;
            }}
            QPushButton:hover {{
                background: {color};
                border: 2px solid {rgba('#ffffff', 60)};
            }}
            QPushButton:pressed {{ background: {color}; }}
            QPushButton:checked {{
                background: {color};
                border: 2px solid #ffffff;
            }}
        """)


class TopBar(QFrame):
    """顶栏：按下只记录起点，移动超过阈值才拖拽窗口 —— 单击绝不会被吞掉。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TopBar")
        self.setFixedHeight(48)
        self._press_global: QPoint | None = None
        self._offset: QPoint | None = None

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            # 落在子控件（圆点/图标按钮）上的按下由子控件消费，事件不会走到这里
            self._press_global = event.globalPosition().toPoint()
            self._offset = self._press_global - self.window().frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._press_global is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)
            return
        moved = (event.globalPosition().toPoint() - self._press_global).manhattanLength()
        if moved < DRAG_THRESHOLD:
            return                      # 轻微抖动不算拖拽，避免误吞点击
        handle = self.window().windowHandle()
        if handle is not None and handle.startSystemMove():
            self._press_global = None
            event.accept()
            return
        if self._offset is not None:
            self.window().move(event.globalPosition().toPoint() - self._offset)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._press_global = None
        self._offset = None
        super().mouseReleaseEvent(event)


def icon_button(text: str, tooltip: str = "", size: int = 26, close: bool = False) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("IconBtn")
    button.setFixedSize(size, size)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    if tooltip:
        button.setToolTip(tooltip)
    if close:
        button.setProperty("close", True)
    return button


def ghost_button(text: str, tooltip: str = "") -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("GhostBtn")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    if tooltip:
        button.setToolTip(tooltip)
    return button


# ==========================================================================
# §9 月历（格子高度自适应可用空间；纯布局，无绝对定位）
# ==========================================================================
class DayCell(QFrame):
    clicked = pyqtSignal(str)
    hovered = pyqtSignal(str)        # 鼠标移入：通知日历弹出当天内容预览
    unhovered = pyqtSignal()

    HEADER_H = 30
    WEEKDAY_H = 20
    GRID_SPACING = 2
    MARGINS = 18
    SPACING = 14

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(34)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._day = ""
        self._number = 1
        self._in_month = True
        self._today = False
        self._selected = False
        self._score = 0
        self._hover = False

    def set_state(self, day: str, number: int, in_month: bool,
                  is_today: bool, selected: bool, score: int) -> None:
        self._day, self._number, self._in_month = day, number, in_month
        self._today, self._selected, self._score = is_today, selected, score
        self.setToolTip(f"{day} · {score} 项记录" if score else day)
        self.update()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()
        if self._day:
            self.hovered.emit(self._day)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()
        self.unhovered.emit()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._day:
            self.clicked.emit(self._day)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        axis = self.rect().adjusted(2, 1, -2, -1)

        if self._selected:
            painter.setPen(QPen(QColor(FOCUS), 1))
            painter.setBrush(QColor(59, 130, 246, 46))
            painter.drawRoundedRect(axis, 9, 9)
        elif self._hover and self._in_month:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 13))
            painter.drawRoundedRect(axis, 9, 9)
        elif self._today:
            painter.setPen(QPen(QColor(59, 130, 246, 80), 1))
            painter.setBrush(QColor(255, 255, 255, 8))
            painter.drawRoundedRect(axis, 9, 9)

        if not self._in_month:
            color = QColor(TEXT_FAINT)
        elif self._today or self._selected:
            color = QColor("#93b4fb")
        else:
            color = QColor(TEXT)
        font = QFont(self.font())
        font.setBold(self._today or self._selected)
        painter.setFont(font)
        painter.setPen(color)
        painter.drawText(axis, Qt.AlignmentFlag.AlignCenter, str(self._number))

        if self._in_month and self._score > 0 and axis.height() >= 26:
            dots = 1 if self._score < 3 else (2 if self._score < 7 else 3)
            base_y = axis.bottom() - 3
            start_x = axis.center().x() - (dots - 1) * 3
            painter.setPen(Qt.PenStyle.NoPen)
            for index in range(dots):
                x = start_x + index * 6
                halo = QColor(FOCUS)
                halo.setAlpha(60)
                painter.setBrush(halo)
                painter.drawEllipse(int(x - 3), int(base_y - 3), 6, 6)
                painter.setBrush(QColor(FOCUS))
                painter.drawEllipse(int(x - 1.5), int(base_y - 1.5), 3, 3)
        painter.end()


class CalendarPanel(QFrame):
    """可折叠月历：展开/收起只改变自身高度，由外层垂直布局自然让位，绝不重叠。"""

    dayPicked = pyqtSignal(str)
    collapseRequested = pyqtSignal()
    dayHovered = pyqtSignal(str)      # 悬停某天（带全局锚点矩形），用于浮层预览
    dayUnhovered = pyqtSignal()

    def __init__(self, store: DataStore, parent=None):
        super().__init__(parent)
        self.setObjectName("CalendarPanel")
        self.store = store
        self._cursor = date.today().replace(day=1)
        self._selected = today_str()
        self._cells: list[DayCell] = []
        self._cell_h = 34

        prev_btn = icon_button("‹", "上一月", 24)
        prev_btn.clicked.connect(lambda: self.shift_month(-1))
        next_btn = icon_button("›", "下一月", 24)
        next_btn.clicked.connect(lambda: self.shift_month(1))
        self.month_label = QLabel()
        self.month_label.setObjectName("MonthLabel")
        today_btn = ghost_button("今天", "回到今天")
        today_btn.clicked.connect(self.go_today)
        close_btn = icon_button("▴", "收起月历", 24)
        close_btn.clicked.connect(self.collapseRequested.emit)

        month_row = QHBoxLayout()
        month_row.setContentsMargins(0, 0, 0, 0)
        month_row.setSpacing(6)
        month_row.addWidget(prev_btn)
        month_row.addWidget(self.month_label)
        month_row.addWidget(next_btn)
        month_row.addStretch(1)
        month_row.addWidget(today_btn)
        month_row.addWidget(close_btn)

        weekday_row = QHBoxLayout()
        weekday_row.setContentsMargins(0, 0, 0, 0)
        weekday_row.setSpacing(2)
        for name in WEEKDAY_NAMES:
            label = QLabel(name)
            label.setObjectName("DayHeader")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            weekday_row.addWidget(label, 1)

        self.grid = QGridLayout()
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(DayCell.GRID_SPACING)
        for index in range(42):
            cell = DayCell()
            cell.clicked.connect(self.pick_day)
            cell.hovered.connect(self.dayHovered)
            cell.unhovered.connect(self.dayUnhovered)
            self.grid.addWidget(cell, index // 7, index % 7)
            self._cells.append(cell)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 10)
        layout.setSpacing(7)
        layout.addLayout(month_row)
        layout.addLayout(weekday_row)
        layout.addLayout(self.grid)

        self.set_month(date.today().year, date.today().month)

    # ---------------- 高度自适应 ----------------
    def _chrome_height(self) -> int:
        """月历固定部分（月份行 + 星期行 + 内外边距）的真实高度。

        直接按当前实际布局反推，而不是用硬编码常量估算 ——
        估算偏差会让月历被裁剪或白白浪费高度。
        """
        grid = self._cells[0].height() * 6 + DayCell.GRID_SPACING * 5
        hint = self.layout().sizeHint().height()
        return max(30, hint - grid)

    def fit_height(self, budget: int) -> int:
        """按可用高度预算伸缩日期格，返回面板实际所需总高度（6 行全部可见）。"""
        chrome = self._chrome_height()
        spacing = DayCell.GRID_SPACING * 5
        grid_budget = max(6 * CAL_CELL_MIN + spacing, budget - chrome)
        cell_h = max(CAL_CELL_MIN, min(CAL_CELL_MAX, int((grid_budget - spacing) / 6)))
        for cell in self._cells:
            cell.setFixedHeight(cell_h)
        self._cell_h = cell_h
        return chrome + cell_h * 6 + spacing

    def natural_height(self) -> int:
        return self.fit_height(10 ** 6)

    # ---------------- 月份 ----------------
    def shift_month(self, delta: int) -> None:
        year = self._cursor.year + (self._cursor.month - 1 + delta) // 12
        month = (self._cursor.month - 1 + delta) % 12 + 1
        self.set_month(year, month)

    def go_today(self) -> None:
        self.set_month(date.today().year, date.today().month)
        self.pick_day(today_str())

    def set_month(self, year: int, month: int) -> None:
        self._cursor = date(year, month, 1)
        self.month_label.setText(f"{year} 年 {month} 月")
        self.refresh()

    def pick_day(self, day: str) -> None:
        self._selected = day
        try:
            parsed = datetime.strptime(day, DAY_FMT).date()
        except ValueError:
            return
        if (parsed.year, parsed.month) != (self._cursor.year, self._cursor.month):
            self._cursor = parsed.replace(day=1)
            self.month_label.setText(f"{parsed.year} 年 {parsed.month} 月")
        self.refresh()
        self.dayPicked.emit(day)

    def select(self, day: str) -> None:
        self._selected = day
        self.refresh()

    def refresh(self) -> None:
        scores = self.store.heat_scores()
        first = self._cursor.replace(day=1)
        start = first - timedelta(days=first.weekday())
        days = [start + timedelta(days=offset) for offset in range(42)]
        today = date.today()
        for index, cell in enumerate(self._cells):
            day = days[index]
            key = day.strftime(DAY_FMT)
            cell.set_state(day=key, number=day.day,
                           in_month=(day.month == self._cursor.month),
                           is_today=(day == today), selected=(key == self._selected),
                           score=scores.get(key, 0))


# ==========================================================================
# §9.5 悬停预览浮层 / 右下角缩放抓手
# ==========================================================================
class DayPreview(QFrame):
    """月历悬停预览：鼠标停在某一天时，浮出该天全部待办内容。

    独立小浮窗（Tool + 鼠标穿透）：不参与主窗口布局，也不会抢走鼠标
    导致日历格丢失 hover 状态或触发主窗口淡出。
    """

    MAX_ITEMS = 7
    WIDTH = 250

    def __init__(self, parent=None):
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool
                         | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedWidth(self.WIDTH)

        shadow = QFrame()
        shadow.setObjectName("DayPreview")
        soft_shadow(shadow, blur=18, dy=6, alpha=190)

        card = QFrame()
        card.setObjectName("DayPreview")
        self.title = QLabel()
        self.title.setObjectName("PreviewTitle")
        self.meta = QLabel()
        self.meta.setObjectName("PreviewMeta")
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(5)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 10, 12, 11)
        card_layout.setSpacing(5)
        card_layout.addWidget(self.title)
        card_layout.addWidget(self.meta)
        card_layout.addWidget(self.body)

        holder = QGridLayout(self)          # 阴影层与内容层重叠同一格
        holder.setContentsMargins(9, 9, 9, 11)
        holder.addWidget(shadow, 0, 0)
        holder.addWidget(card, 0, 0)

    def show_for(self, day: str, todos: list[dict]) -> None:
        try:
            parsed = datetime.strptime(day, DAY_FMT).date()
            header = f"{parsed.month} 月 {parsed.day} 日 · 周{WEEKDAY_NAMES[parsed.weekday()]}"
        except ValueError:
            header = day
        self.title.setText(header)

        done = sum(1 for row in todos if row.get("done"))
        if todos:
            self.meta.setText(f"{len(todos) - done} 待办 · {done} 已完成")
        else:
            self.meta.setText("暂无记录")

        clear_layout(self.body_layout)
        if not todos:
            empty = QLabel("这一天还没有日程")
            empty.setObjectName("PreviewEmpty")
            self.body_layout.addWidget(empty)
        for row in todos[: self.MAX_ITEMS]:
            self.body_layout.addWidget(self._row(row))
        if len(todos) > self.MAX_ITEMS:
            more = QLabel(f"…… 另有 {len(todos) - self.MAX_ITEMS} 条")
            more.setObjectName("PreviewEmpty")
            self.body_layout.addWidget(more)

        self.adjustSize()
        self._place_near_cursor()
        self.show()
        self.raise_()

    def _row(self, row: dict) -> QWidget:
        holder = QWidget()
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        if row.get("time"):
            chip = QLabel(row["time"])
            chip.setObjectName("TimeChip")
            if row.get("done"):
                chip.setProperty("plain", True)
            layout.addWidget(chip)
        label = QLabel()
        label.setObjectName("PreviewItem")
        label.setProperty("done", bool(row.get("done")))
        font = label.font()
        font.setStrikeOut(bool(row.get("done")))
        label.setFont(font)
        available = self.WIDTH - 46 - (44 if row.get("time") else 0)
        label.setText(label.fontMetrics().elidedText(row["text"], Qt.TextElideMode.ElideRight,
                                                     max(60, available)))
        label.setToolTip(row["text"])
        layout.addWidget(label, 1)
        return holder

    def _place_near_cursor(self) -> None:
        """贴在鼠标右下方；右侧或底部空间不足时自动翻到另一侧。"""
        cursor = QCursor.pos()
        screen = QGuiApplication.screenAt(cursor) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry() if screen else None
        x, y = cursor.x() + 18, cursor.y() - 12
        if area is not None:
            if x + self.width() > area.right():
                x = cursor.x() - self.width() - 18
            x = max(area.left() + 6, x)
            y = max(area.top() + 6, min(y, area.bottom() - self.height() - 6))
        self.move(x, y)

    def hide_preview(self) -> None:
        if self.isVisible():
            self.hide()


class _ReminderCard(QFrame):
    """提醒卡片：吞掉点击，避免点在卡片上被当成"点击空白处关闭"。"""

    def mousePressEvent(self, event) -> None:  # noqa: N802
        event.accept()


class ReminderOverlay(QWidget):
    """到点提醒：整屏居中覆盖浮层（半透明遮罩 + 居中卡片）。

    · 覆盖所在屏幕全部区域，永远置顶，不依赖系统通知权限；
    · 卡片由布局居中，无任何绝对定位；
    · 只对窗口自身做透明度淡入（不使用 QGraphicsOpacityEffect，避免内容渲染异常）；
    · Esc / 点击卡片外区域 = 知道了；另有延后与标记完成。
    """

    dismissed = pyqtSignal()
    snoozed = pyqtSignal(int)
    completed = pyqtSignal()

    def __init__(self, screen, snooze_minutes: int = SNOOZE_MINUTES):
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool
                         | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setObjectName("ReminderOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # 纯 QWidget 顶层不会绘制 QSS 的 background，必须开 WA_StyledBackground
        # （更稳的做法是直接 paintEvent 填充，见下），否则遮罩不显示却依然挡住点击。
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # 刻意不抢焦点/不激活：否则用户在其它软件里敲回车会误触浮层按钮
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self._screen = screen
        self._snooze_minutes = snooze_minutes

        shadow = QFrame()
        shadow.setObjectName("ReminderCard")
        soft_shadow(shadow, blur=30, dy=10, alpha=210)

        card = _ReminderCard()
        card.setObjectName("ReminderCard")
        card.setFixedWidth(400)

        self.title = QLabel("⏰ 日程提醒")
        self.title.setObjectName("ReminderTitle")
        self.clock = QLabel("")
        self.clock.setObjectName("ReminderClock")
        self.meta = QLabel("")
        self.meta.setObjectName("ReminderMeta")

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(10)
        title_row.addWidget(self.title)
        title_row.addStretch(1)
        title_row.addWidget(self.clock)

        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(7)

        divider = QFrame()
        divider.setObjectName("ReminderDivider")
        divider.setFixedHeight(1)

        hint = QLabel("点击任意位置关闭 · 也可选择延后或标记完成")
        hint.setObjectName("ReminderHint")

        self.complete_btn = ghost_button("标记完成", "把这些日程直接标记为已完成")
        self.complete_btn.clicked.connect(self.completed.emit)
        self.snooze_btn = ghost_button(f"延后 {snooze_minutes} 分钟", "稍后再提醒一次")
        self.snooze_btn.clicked.connect(lambda: self.snoozed.emit(self._snooze_minutes))
        self.ok_btn = QPushButton("知道了")
        self.ok_btn.setObjectName("AddBtn")
        self.ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ok_btn.setMinimumHeight(34)
        self.ok_btn.clicked.connect(self.dismissed.emit)
        # 三个按钮一律不接受键盘焦点：只能用鼠标点，杜绝回车/空格的误触发
        for button in (self.complete_btn, self.snooze_btn, self.ok_btn):
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(8)
        button_row.addWidget(self.complete_btn)
        button_row.addStretch(1)
        button_row.addWidget(self.snooze_btn)
        button_row.addWidget(self.ok_btn)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 18, 20, 16)
        card_layout.setSpacing(10)
        card_layout.addLayout(title_row)
        card_layout.addWidget(self.meta)
        card_layout.addWidget(divider)
        card_layout.addWidget(self.body)
        card_layout.addSpacing(2)
        card_layout.addLayout(button_row)
        card_layout.addWidget(hint)

        holder = QGridLayout()             # 阴影层与卡片重叠同一格（阴影只作用于装饰层）
        holder.setContentsMargins(0, 0, 0, 0)
        holder.addWidget(shadow, 0, 0)
        holder.addWidget(card, 0, 0)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addLayout(holder)
        row.addStretch(1)

        outer = QVBoxLayout(self)
        outer.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(1)

        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(180)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)

    # ---------------- 展示 ----------------
    def paintEvent(self, event) -> None:  # noqa: N802
        """显式绘制整屏暗色遮罩（不依赖 QSS 背景，确保"覆盖整个画面"一定生效）。"""
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(6, 8, 12, 196))
        painter.end()

    def present(self, rows: list[dict]) -> None:
        try:
            parsed = datetime.strptime(rows[0].get("date") or today_str(), DAY_FMT).date()
            day_text = f"{parsed.month} 月 {parsed.day} 日 周{WEEKDAY_NAMES[parsed.weekday()]}"
        except (ValueError, IndexError):
            day_text = today_str()
        if len(rows) == 1:
            self.clock.setText(rows[0].get("time") or "现在")
            self.meta.setText(f"{day_text} · 到点了")
        else:
            self.clock.setText(f"{len(rows)} 条")
            self.meta.setText(f"{day_text} · 共 {len(rows)} 条待办到点")
        self.complete_btn.setVisible(len(rows) == 1)

        clear_layout(self.body_layout)
        for row in rows[:6]:
            self.body_layout.addWidget(self._row(row))
        if len(rows) > 6:
            more = QLabel(f"…… 另有 {len(rows) - 6} 条")
            more.setObjectName("ReminderHint")
            self.body_layout.addWidget(more)

        geometry = self._screen.geometry() if self._screen is not None else None
        if geometry is not None:
            self.setGeometry(geometry)
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()          # 置顶显示，但不抢焦点（避免打断用户正在进行的输入）

        self._fade.stop()
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(1.0)
        self._fade.start()

    def _row(self, row: dict) -> QWidget:
        holder = QWidget()
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)
        if row.get("time"):
            chip = QLabel(row["time"])
            chip.setObjectName("TimeChip")
            layout.addWidget(chip, 0, Qt.AlignmentFlag.AlignTop)
        label = QLabel(row["text"])
        label.setObjectName("ReminderItem")
        label.setProperty("done", bool(row.get("done")))
        label.setWordWrap(True)
        label.setToolTip(row["text"])
        layout.addWidget(label, 1)
        return holder

    def dismiss(self) -> None:
        if self.isVisible():
            self.hide()

    # ---------------- 交互 ----------------
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.dismissed.emit()          # 点击卡片外任意位置 = 知道了
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.dismissed.emit()
        else:
            super().keyPressEvent(event)


class ResizeGrip(QWidget):
    """右下角缩放抓手（可用鼠标拖动改变窗口大小）。"""

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.setObjectName("ResizeGrip")
        self.setFixedSize(18, 18)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self.setToolTip("拖动调整窗口大小")
        self._window = window

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(TEXT_FAINT))
        for offset in (3, 7, 11):
            painter.drawEllipse(15 - offset, 15 - offset, 3, 3)
        painter.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self._window.windowHandle()
            if handle is not None and handle.startSystemResize(
                    Qt.Edge.BottomEdge | Qt.Edge.RightEdge):
                event.accept()
                return
        super().mousePressEvent(event)


# ==========================================================================
# §10 画布页 / 日程卡片 / 底部撤销条（均为布局成员，无绝对定位）
# ==========================================================================
class CanvasPage(QFrame):
    """单张画布：外层卡片负责底色 / 1px 边框 / 14px 圆角与聚焦发光，
    内层 QTextEdit 只负责文字（透明、无边框、零内边距）。

    这样拆分是本次"画布错位"的关键修复：QTextEdit 一旦自带 stylesheet 边框与
    内边距，文字与占位符在部分重绘路径（首次显示、输入首字符）下会整体偏移，
    必须切页回来才恢复正常。视觉与渲染彻底解耦后不再出现。
    """

    def __init__(self, index: int, parent=None):
        super().__init__(parent)
        self.setObjectName("CanvasPage")
        self.setProperty("focused", False)
        self.index = index

        layout = QVBoxLayout(self)
        layout.setContentsMargins(11, 9, 11, 9)
        layout.setSpacing(0)

        self.editor = QTextEdit(self)
        self.editor.setObjectName("Canvas")
        self.editor.setFrameShape(QFrame.Shape.NoFrame)
        self.editor.setAcceptRichText(False)          # 粘贴一律转纯文本，避免带色文字
        self.editor.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.editor.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.editor.installEventFilter(self)
        layout.addWidget(self.editor)

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is self.editor and event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            self.setProperty("focused", event.type() == QEvent.Type.FocusIn)
            repolish(self)
        return super().eventFilter(obj, event)


class ScheduleCard(QFrame):
    """单条日程：复选框 + 时间胶囊 + 文本 + 🗑（固定高度，宽度自适应）。"""

    toggled = pyqtSignal(int)
    deleted = pyqtSignal(int)

    def __init__(self, row: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("SchedCard")
        self.schedule_id = int(row["id"])
        self.setFixedHeight(CARD_H)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        self.check = QCheckBox()
        self.check.setChecked(bool(row["done"]))
        self.check.setCursor(Qt.CursorShape.PointingHandCursor)
        self.check.setFixedSize(19, 19)
        self.check.setToolTip("标记完成 / 取消完成")
        # 只看鼠标：不给键盘焦点，避免在别处打字按空格时误切换本条日程
        self.check.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.check.clicked.connect(lambda: self.toggled.emit(self.schedule_id))

        self.chip = QLabel(row.get("time") or "待办")
        self.chip.setObjectName("TimeChip")
        if not row.get("time"):
            self.chip.setProperty("plain", True)
        if self._is_overdue(row):
            self.chip.setProperty("overdue", True)
        self.chip.setVisible(bool(row.get("time")))

        self.text_label = QLabel()
        self.text_label.setObjectName("SchedText")
        self.text_label.setProperty("done", bool(row["done"]))
        # 水平方向 Ignored：始终占满剩余宽度，避免"省略→sizeHint 变窄→更省略"的塌缩死循环
        self.text_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.text_label.setMinimumWidth(60)
        self._full_text = row["text"]
        self.text_label.setToolTip(row["text"])
        font = self.text_label.font()
        font.setStrikeOut(bool(row["done"]))
        self.text_label.setFont(font)

        remove = QPushButton("🗑")
        remove.setObjectName("DelBtn")
        remove.setFixedSize(24, 22)
        remove.setFont(emoji_font(12))
        remove.setCursor(Qt.CursorShape.PointingHandCursor)
        remove.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        remove.setToolTip("删除这一条（3 秒内可撤销）")
        remove.clicked.connect(lambda: self.deleted.emit(self.schedule_id))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 7, 5)
        layout.setSpacing(8)
        layout.addWidget(self.check)
        layout.addWidget(self.chip)
        layout.addWidget(self.text_label, 1)
        layout.addWidget(remove)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._apply_elide()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_elide()

    def _apply_elide(self) -> None:
        """长文本按可用宽度省略（悬停可见全文）。

        宽度未确定时直接显示全文 —— 避免在极窄宽度下被省略成空字符串，
        这正是"鼠标移开卡片里就没内容"的根因。
        """
        width = self.text_label.width()
        if width < 60:
            self.text_label.setText(self._full_text)
            return
        self.text_label.setText(
            self.text_label.fontMetrics().elidedText(
                self._full_text, Qt.TextElideMode.ElideRight, width))

    def flash(self, milliseconds: int = 900) -> None:
        """新卡片高亮闪一下（改用属性切换，不再使用长效 QGraphicsOpacityEffect）。"""
        self.setProperty("fresh", True)
        repolish(self)
        QTimer.singleShot(milliseconds, self._clear_flash)

    def _clear_flash(self) -> None:
        self.setProperty("fresh", False)
        repolish(self)

    @staticmethod
    def _is_overdue(row: dict) -> bool:
        if row.get("done") or not row.get("time"):
            return False
        try:
            when = datetime.strptime(f"{row['date']} {row['time']}", "%Y-%m-%d %H:%M")
        except (ValueError, KeyError):
            return False
        return when < datetime.now()


class UndoToast(QFrame):
    """底部悬浮撤销条：作为垂直布局的最后一行"滑出"（高度动画），不遮挡任何内容。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("UndoToast")
        self.setMinimumHeight(0)
        self.setMaximumHeight(0)
        self.setVisible(False)
        self._action = None

        # 注意：这里刻意不使用 QGraphicsOpacityEffect（长效效果器会让内容渲染异常），
        # 只用高度动画实现"底部滑出/收起"。
        self.label = QLabel()
        self.label.setObjectName("UndoText")
        self.action_btn = QPushButton("撤销")
        self.action_btn.setObjectName("UndoBtn")
        self.action_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.action_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.action_btn.clicked.connect(self._run_action)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        row.addWidget(self.label, 1)
        row.addWidget(self.action_btn)

        self.progress = QFrame()
        self.progress.setObjectName("UndoProgress")
        self.progress.setFixedHeight(2)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(13, 8, 11, 7)
        layout.setSpacing(6)
        layout.addLayout(row)
        layout.addWidget(self.progress)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide_message)
        self._height = QPropertyAnimation(self, b"maximumHeight", self)
        self._drain = QPropertyAnimation(self.progress, b"maximumWidth", self)

    # ---------------- 展示 ----------------
    def show_message(self, text: str, action_text: str = "", action=None,
                     timeout: int = UNDO_TIMEOUT_MS) -> None:
        self.label.setText(text)
        self._action = action
        visible = bool(action_text and callable(action))
        self.action_btn.setVisible(visible)
        if visible:
            self.action_btn.setText(action_text)

        parent_width = self.parentWidget().width() if self.parentWidget() else WINDOW_W
        self.progress.setMaximumWidth(max(60, parent_width - 60))

        self.setVisible(True)
        self.setMaximumHeight(TOAST_H)

        # 关键：先摘掉上一轮 hide_message 挂上的 finished→收起，否则本次滑出
        # 动画结束时会被旧回调立即收起（表现为"撤销条一闪就没、按钮点不到"）
        self._detach_height_finished()
        self._height.stop()
        self._height.setDuration(TOAST_ANIM_MS)
        self._height.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._height.setStartValue(self.maximumHeight())
        self._height.setEndValue(TOAST_H)
        self._height.start()

        self._drain.stop()
        self._drain.setDuration(timeout)
        self._drain.setStartValue(max(60, parent_width - 60))
        self._drain.setEndValue(0)
        self._drain.start()
        self._hide_timer.start(timeout)

    def _detach_height_finished(self) -> None:
        try:
            self._height.finished.disconnect()
        except TypeError:
            pass

    def hide_message(self) -> None:
        self._hide_timer.stop()
        self._detach_height_finished()
        self._height.stop()
        self._height.setDuration(TOAST_ANIM_MS + 40)
        self._height.setEasingCurve(QEasingCurve.Type.InCubic)
        self._height.setStartValue(self.maximumHeight())
        self._height.setEndValue(0)
        self._height.finished.connect(self._on_collapsed)
        self._height.start()

    def _on_collapsed(self) -> None:
        if self.maximumHeight() <= 1:
            self.setVisible(False)

    def _run_action(self) -> None:
        callback, self._action = self._action, None
        self.hide_message()
        if callable(callback):
            callback()


# ==========================================================================
# §11 主窗口（纯 QVBoxLayout 垂直层级）
# ==========================================================================
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.store = DataStore()
        self.settings = self.store.settings
        self.toaster = Toaster()
        self.hotkey: GlobalHotkey | None = None
        self.tray: QSystemTrayIcon | None = None

        self._page = max(0, min(int(self.settings.get("active_canvas") or 0), CANVAS_COUNT - 1))
        self._selected_date = str(self.settings.get("selected_date") or today_str())
        self._fade_enabled = not bool(self.settings.get("fade_lock"))
        self._autofit = bool(self.settings.get("autofit", AUTOFIT_DEFAULT))
        self._calendar_open = False
        self._calendar_target_h = 0
        self._adjusting_split = False
        self._hover_day = ""
        self._overlays: list[ReminderOverlay] = []      # 到点提醒浮层（每屏一个）
        self._active_reminders: list[dict] = []          # 当前正在提醒的日程
        self._loading = False
        self._anims: list = []
        self._flash_timer: QTimer | None = None
        self._status_timer: QTimer | None = None

        self.setMouseTracking(True)          # 无边框窗口边缘缩放需要
        self.setMinimumSize(WINDOW_MIN_W, WINDOW_MIN_H)

        # 自适应画布高度的防抖计时器
        self._autofit_timer = QTimer(self)
        self._autofit_timer.setSingleShot(True)
        self._autofit_timer.timeout.connect(self._apply_autofit)

        # 月历悬停预览（延迟一点，避免扫过时闪烁）
        self._preview = DayPreview()
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._show_day_preview)

        self._build_ui()
        self._apply_pin()            # 先定窗口标志（会重建原生窗口），再定位
        self._place_window()
        self._load_canvases()
        self._refresh_calendar()
        self._refresh_schedule_list()
        self._update_status()

        QTimer.singleShot(0, self._restore_split)

        self.reminder_timer = QTimer(self)
        self.reminder_timer.timeout.connect(self._poll_reminders)
        self.reminder_timer.start(REMINDER_POLL_MS)
        QTimer.singleShot(1500, self._poll_reminders)

        self.hotkey = GlobalHotkey(self, HOTKEY)
        self.hotkey.activated.connect(self._show_capture)
        if not self.hotkey.register():
            QShortcut(QKeySequence(HOTKEY), self).activated.connect(self._show_capture)

        self._build_tray()
        self._update_status()
        # 启动焦点固定在当前画布：即便用户在别处打字误触键盘，也只是往画布里输入字符，
        # 不会误切换日程复选框
        self.editors[self._page].setFocus()

    # ==================================================== 构建 UI（严格自上而下）
    def _build_ui(self) -> None:
        # ⚠ 阴影层与内容层是"重叠的兄弟控件"：20px 弥散阴影只挂在纯装饰的
        #   ShadowLayer 上，真正承载文字的内容树完全不经过离屏位图，
        #   从根本上避免 QGraphicsDropShadowEffect 造成的整体错位/重绘异常。
        self.shadow_layer = QFrame()
        self.shadow_layer.setObjectName("ShadowLayer")
        soft_shadow(self.shadow_layer, blur=20, dy=8, alpha=190)

        self.root = QFrame()
        self.root.setObjectName("Root")

        root_layout = QVBoxLayout(self.root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ---------- ① 顶栏：5 色圆点 + 图标按钮 ----------
        self.top_bar = TopBar()
        self.dot_group = QButtonGroup(self)
        self.dot_group.setExclusive(True)
        self.dots: list[PageDot] = []

        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(14, 5, 10, 3)
        top_layout.setSpacing(9)
        for index in range(CANVAS_COUNT):
            dot = PageDot(index, DOT_COLORS[index])
            dot.clicked.connect(lambda _checked=False, i=index: self.switch_page(i))
            self.dot_group.addButton(dot, index)
            self.dots.append(dot)
            top_layout.addWidget(dot)
        top_layout.addStretch(1)

        self.calendar_btn = icon_button("📅", "展开 / 收起月历（点日期切换下方清单）")
        self.calendar_btn.setFont(emoji_font(13))
        self.calendar_btn.clicked.connect(lambda: self.toggle_calendar())
        self.autofit_btn = icon_button("⇕", "画布高度随内容自适应（点击切换）")
        self.autofit_btn.clicked.connect(self.toggle_autofit)
        self.autofit_btn.setProperty("active", self._autofit)
        self.lock_btn = icon_button("🔒", "锁定常显（关闭鼠标移出淡出）")
        self.lock_btn.setFont(emoji_font(12))
        self.lock_btn.clicked.connect(self.toggle_fade_lock)
        self.lock_btn.setProperty("active", not self._fade_enabled)
        minimize_btn = icon_button("—", "最小化到托盘")
        minimize_btn.clicked.connect(self.hide)
        close_btn = icon_button("✕", "退到托盘（提醒继续生效）", close=True)
        close_btn.clicked.connect(self.close)
        for button in (self.autofit_btn, self.calendar_btn, self.lock_btn,
                       minimize_btn, close_btn):
            top_layout.addWidget(button)
        root_layout.addWidget(self.top_bar)

        # ---------- ② 画布（上） / ③④⑤ 月历 + 日程（下）：垂直分割条自由调节 ----------
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(15, 5, 15, 8)
        body_layout.setSpacing(0)

        self.stack = QStackedWidget()
        self.stack.setMinimumHeight(CANVAS_MIN_H)
        self.stack.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.pages: list[CanvasPage] = []
        self.editors: list[QTextEdit] = []
        for index in range(CANVAS_COUNT):
            page = CanvasPage(index)
            page.editor.setPlaceholderText(
                f"画布 {index + 1} · 随手写点什么，输入即自动保存")
            page.editor.textChanged.connect(lambda idx=index: self._on_canvas_edited(idx))
            page.editor.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            page.editor.customContextMenuRequested.connect(
                lambda pos, idx=index: self._canvas_menu(idx, pos))
            self.pages.append(page)
            self.editors.append(page.editor)
            self.stack.addWidget(page)

        canvas_host = QWidget()
        canvas_layout = QVBoxLayout(canvas_host)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.addWidget(self.stack)

        # ---------- ③ 可折叠月历 ----------
        self.calendar = CalendarPanel(self.store)
        self.calendar.dayPicked.connect(self._on_day_picked)
        self.calendar.collapseRequested.connect(lambda: self.toggle_calendar(False))
        self.calendar.dayHovered.connect(self._on_day_hovered)
        self.calendar.dayUnhovered.connect(self._on_day_unhovered)
        self.calendar.setMinimumHeight(0)
        self.calendar.setMaximumHeight(0)
        self.calendar.setVisible(False)
        self.calendar.natural_height()      # 预先测量（格子高度就位）

        self.lower = QWidget()
        lower_layout = QVBoxLayout(self.lower)
        lower_layout.setContentsMargins(0, 0, 0, 0)
        lower_layout.setSpacing(9)
        lower_layout.addWidget(self.calendar)

        # ---------- ④⑤ 日程面板：单行输入 + 多条目滚动列表 ----------
        self.schedule_panel = QFrame()
        self.schedule_panel.setObjectName("Panel")
        panel_layout = QVBoxLayout(self.schedule_panel)
        panel_layout.setContentsMargins(12, 10, 12, 12)
        panel_layout.setSpacing(8)

        self.panel_title = QLabel("⏰ 今日日程")
        self.panel_title.setObjectName("PanelTitle")
        self.panel_meta = QLabel("")
        self.panel_meta.setObjectName("PanelMeta")
        self.flash_label = QLabel("已保存 ✓")
        self.flash_label.setObjectName("SavedFlash")
        self.flash_label.setVisible(False)
        self.export_btn = ghost_button("导出", "一键把该日全部待办整理成编号列表复制到剪贴板，可直接粘贴")
        self.export_btn.clicked.connect(self._export_day)
        self.back_today_btn = ghost_button("回到今天", "清单切回今天")
        self.back_today_btn.clicked.connect(self._back_to_today)
        self.back_today_btn.setVisible(False)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        title_row.addWidget(self.panel_title)
        title_row.addWidget(self.panel_meta)
        title_row.addStretch(1)
        title_row.addWidget(self.flash_label)
        title_row.addWidget(self.back_today_btn)
        title_row.addWidget(self.export_btn)
        panel_layout.addLayout(title_row)

        self.input = QLineEdit()
        self.input.setObjectName("ScheduleInput")
        self.input.returnPressed.connect(self._submit_schedule)
        add_btn = QPushButton("添加")
        add_btn.setObjectName("AddBtn")
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.setFixedHeight(34)
        add_btn.setToolTip("回车或点击添加；提交后输入框立刻清空")
        add_btn.clicked.connect(self._submit_schedule)

        input_row = QHBoxLayout()
        input_row.setContentsMargins(0, 0, 0, 0)
        input_row.setSpacing(8)
        input_row.addWidget(self.input, 1)
        input_row.addWidget(add_btn)
        panel_layout.addLayout(input_row)

        # 多条目滚动列表：QScrollArea + setWidgetResizable(True)
        self.schedule_host = QWidget()
        self.schedule_host.setObjectName("ScheduleHost")
        self.schedule_host.setAutoFillBackground(False)
        self.schedule_layout = QVBoxLayout(self.schedule_host)
        self.schedule_layout.setContentsMargins(0, 0, 0, 0)
        self.schedule_layout.setSpacing(6)

        self.schedule_scroll = QScrollArea()
        self.schedule_scroll.setObjectName("ScheduleScroll")
        self.schedule_scroll.setWidgetResizable(True)
        self.schedule_scroll.setWidget(self.schedule_host)
        # 列表高度改为弹性（占满分割区剩余空间）：条目越多越高，超出即滚动
        self.schedule_scroll.setMinimumHeight(LIST_VIEW_MIN_H)
        self.schedule_scroll.setSizePolicy(QSizePolicy.Policy.Preferred,
                                           QSizePolicy.Policy.Expanding)
        self.schedule_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.schedule_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.schedule_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.schedule_scroll.viewport().setAutoFillBackground(False)
        self.schedule_scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        panel_layout.addWidget(self.schedule_scroll, 1)
        lower_layout.addWidget(self.schedule_panel, 1)

        # ---------- 垂直分割条：画布 ↔ 月历/日程 可自由拖动 ----------
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setObjectName("BodySplitter")
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(10)
        self.splitter.addWidget(canvas_host)
        self.splitter.addWidget(self.lower)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.splitterMoved.connect(self._on_splitter_moved)
        body_layout.addWidget(self.splitter)

        root_layout.addWidget(body, 1)

        # ---------- 撤销条（布局最后一行，滑出式） ----------
        self.undo_toast = UndoToast(self.root)
        root_layout.addWidget(self.undo_toast)

        # ---------- 状态栏 ----------
        self.status_label = QLabel("")
        self.status_label.setObjectName("HintText")
        self.count_label = QLabel("")
        self.count_label.setObjectName("HintText")
        self.resize_grip = ResizeGrip(self)
        status_row = QHBoxLayout()
        status_row.setContentsMargins(16, 3, 8, 5)
        status_row.setSpacing(10)
        status_row.addWidget(self.status_label, 1)
        status_row.addWidget(self.count_label)
        status_row.addWidget(self.resize_grip)
        root_layout.addLayout(status_row)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 22, 22, 26)
        stack_layer = QGridLayout()          # 两层重叠在同一格：阴影在下、内容在上
        stack_layer.setContentsMargins(0, 0, 0, 0)
        stack_layer.addWidget(self.shadow_layer, 0, 0)
        stack_layer.addWidget(self.root, 0, 0)
        outer.addLayout(stack_layer)

        self.capture_bar = CaptureBar()
        self._sync_input_placeholder()
        self._sync_dots()

    # ==================================================== 窗口尺寸/位置（可自由调整）
    def _apply_pin(self) -> None:
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

    def _default_size(self) -> tuple[int, int]:
        screen = QApplication.primaryScreen()
        available = screen.availableGeometry() if screen else None
        width = WINDOW_W
        height = WINDOW_H_PREFERRED
        # 极少数情况下（启动瞬间屏幕尚未就绪）会拿到不合常理的尺寸，
        # 此时保持默认尺寸，避免窗口一上来就被压到最小值。
        if available is not None and available.width() >= 400 and available.height() >= 400:
            width = min(width, max(WINDOW_MIN_W, available.width() - 80))
            height = min(height, max(WINDOW_MIN_H, available.height() - 70))
        return width, height

    def _place_window(self) -> None:
        """恢复上次的窗口尺寸与位置（默认尺寸只是首次启动的初值）。"""
        available = QApplication.primaryScreen().availableGeometry() \
            if QApplication.primaryScreen() else None
        width, height = self._default_size()
        size = self.settings.get("window_size")
        if isinstance(size, list) and len(size) == 2:
            width = max(WINDOW_MIN_W, int(size[0]))
            height = max(WINDOW_MIN_H, int(size[1]))
        if available is not None and available.width() >= 400 and available.height() >= 400:
            width = min(width, available.width() - 20)
            height = min(height, available.height() - 20)
        self.resize(width, height)

        position = self.settings.get("window_pos")
        if isinstance(position, list) and len(position) == 2:
            x, y = int(position[0]), int(position[1])
        elif available:
            x, y = available.right() - width - 70, available.top() + 70
        else:
            x, y = 100, 100
        if available:
            x = max(available.left(), min(x, available.right() - width))
            y = max(available.top(), min(y, available.bottom() - height))
        self.move(x, y)

    def _remember_position(self) -> None:
        self.settings["window_pos"] = [self.x(), self.y()]
        self.settings["window_size"] = [self.width(), self.height()]
        self.store.save()

    # ==================================================== 无边框窗口边缘缩放
    def _edges_at(self, pos: QPoint):
        """判断鼠标是否落在窗口边缘（用于无边框缩放）。"""
        margin = RESIZE_MARGIN
        edges = Qt.Edge(0)
        if pos.x() <= margin:
            edges |= Qt.Edge.LeftEdge
        elif pos.x() >= self.width() - margin:
            edges |= Qt.Edge.RightEdge
        if pos.y() <= margin:
            edges |= Qt.Edge.TopEdge
        elif pos.y() >= self.height() - margin:
            edges |= Qt.Edge.BottomEdge
        return None if edges == Qt.Edge(0) else edges

    @staticmethod
    def _cursor_for(edges):
        left = bool(edges & Qt.Edge.LeftEdge)
        right = bool(edges & Qt.Edge.RightEdge)
        top = bool(edges & Qt.Edge.TopEdge)
        bottom = bool(edges & Qt.Edge.BottomEdge)
        if (left and top) or (right and bottom):
            return Qt.CursorShape.SizeFDiagCursor
        if (right and top) or (left and bottom):
            return Qt.CursorShape.SizeBDiagCursor
        if left or right:
            return Qt.CursorShape.SizeHorCursor
        return Qt.CursorShape.SizeVerCursor

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        edges = self._edges_at(event.position().toPoint())
        if edges is not None:
            self.setCursor(self._cursor_for(edges))
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            edges = self._edges_at(event.position().toPoint())
            if edges is not None:
                handle = self.windowHandle()
                if handle is not None and handle.startSystemResize(edges):
                    event.accept()
                    return
        super().mousePressEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.unsetCursor()
        QTimer.singleShot(90, self._maybe_fade_out)
        super().leaveEvent(event)

    # ==================================================== 分割条 / 画布自适应
    def _split_total(self) -> int:
        return max(0, self.splitter.height() - self.splitter.handleWidth())

    def _set_split(self, canvas_h: int, lower_h: int) -> None:
        """程序化设置分割比例（加锁避免误判为用户手动拖动而关掉自适应）。"""
        total = self._split_total()
        if total <= 0:
            return
        canvas_h = max(CANVAS_MIN_H, min(int(canvas_h), total - 40))
        self._adjusting_split = True
        try:
            self.splitter.setSizes([canvas_h, max(40, total - canvas_h)])
        finally:
            self._adjusting_split = False

    def _on_splitter_moved(self, _pos: int, _index: int) -> None:
        """用户手动拖动分割条 → 关闭"画布随内容自适应"，尊重用户选择。"""
        if self._adjusting_split:
            return
        if self._autofit:
            self._autofit = False
            self.store.set_setting("autofit", False)
            self.autofit_btn.setProperty("active", False)
            repolish(self.autofit_btn)
            self._status("已切换为手动调节画布高度")
        sizes = self.splitter.sizes()
        if sizes:
            self.settings["split"] = sizes[0]
            self.store.save()

    def _restore_split(self) -> None:
        saved = self.settings.get("split")
        total = self._split_total()
        if total <= 0:
            return
        if isinstance(saved, int) and saved > 0 and not self._autofit:
            self._set_split(saved, total - saved)
        else:
            self._apply_autofit(force=True)

    def _schedule_autofit(self) -> None:
        if self._autofit:
            self._autofit_timer.start(180)

    def _apply_autofit(self, force: bool = False) -> None:
        """画布高度随文字内容自适应；富余空间让给下方日程列表。"""
        if not (self._autofit or force) or not hasattr(self, "splitter"):
            return
        total = self._split_total()
        if total <= 0:
            return
        panel_min = self.schedule_panel.minimumSizeHint().height()
        lower_min = panel_min + (self._calendar_target_h if self._calendar_open else 0)
        page = self.pages[self._page]
        doc_h = page.editor.document().size().height()
        needed = int(doc_h) + 36                     # 文档高度 + 卡片/编辑器内边距
        canvas_h = max(CANVAS_MIN_H, min(needed, max(CANVAS_MIN_H, total - lower_min)))
        self._set_split(canvas_h, total - canvas_h)

    def toggle_autofit(self) -> None:
        self._autofit = not self._autofit
        self.store.set_setting("autofit", self._autofit)
        self.autofit_btn.setProperty("active", self._autofit)
        repolish(self.autofit_btn)
        if self._autofit:
            self._apply_autofit()
            self._status("画布高度随内容自适应")
        else:
            self._status("画布高度改由手动拖动调节（拖动中间分割条）")

    # ==================================================== 画布
    def _load_canvases(self) -> None:
        self._loading = True
        try:
            for index, editor in enumerate(self.editors):
                editor.setPlainText(self.store.canvas_text(index))
        finally:
            self._loading = False
        self.stack.setCurrentIndex(self._page)
        self._sync_dots()

    def _sync_dots(self) -> None:
        for index, dot in enumerate(self.dots):
            dot.setChecked(index == self._page)

    def _on_canvas_edited(self, index: int) -> None:
        if self._loading:
            return
        self.store.set_canvas_text(index, self.editors[index].toPlainText())
        self._schedule_autofit()
        self._update_status()

    def switch_page(self, index: int, animate: bool = True) -> None:
        if not 0 <= index < CANVAS_COUNT:
            self._sync_dots()
            return
        if index == self._page:
            self._sync_dots()
            return
        previous = self._page
        self._page = index
        self._sync_dots()
        self.store.set_setting("active_canvas", index)

        if not animate:
            self.stack.setCurrentIndex(index)
        else:
            # 两段式淡入淡出各 75ms（合计 150ms）。
            # 关键：透明度效果器只在过渡期间临时挂载，动画一结束立刻摘掉，
            # 否则长效 QGraphicsOpacityEffect 会让文字/内容渲染错位或空白。
            def phase_in() -> None:
                self.stack.setCurrentIndex(index)
                self._fade_widget(self.pages[index], 0.0, 1.0, PAGE_FADE_MS,
                                  QEasingCurve.Type.OutCubic)

            self._fade_widget(self.pages[previous], 1.0, 0.0, PAGE_FADE_MS,
                              QEasingCurve.Type.InCubic, on_done=phase_in)
        self.editors[index].setFocus()
        self._schedule_autofit()
        self._update_status()

    def _fade_widget(self, widget: QWidget, start: float, end: float, duration: int,
                     easing=QEasingCurve.Type.OutCubic, on_done=None) -> None:
        """临时淡入淡出：动画结束后立刻摘除 effect，保证常规渲染路径干净。"""
        effect = QGraphicsOpacityEffect(widget)
        effect.setOpacity(start)
        widget.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(duration)
        animation.setStartValue(start)
        animation.setEndValue(end)
        animation.setEasingCurve(easing)
        self._remember(animation)

        def finish() -> None:
            animation.stop()
            if widget.graphicsEffect() is effect:
                widget.setGraphicsEffect(None)   # 恢复常规渲染（关键）
            if callable(on_done):
                on_done()

        animation.finished.connect(lambda: QTimer.singleShot(0, finish))
        animation.start()

    def _remember(self, animation) -> None:
        """持有动画引用防 GC；同时避免长会话无限增长。"""
        self._anims.append(animation)
        if len(self._anims) > 24:
            for old in self._anims[:-24]:
                old.stop()
                old.deleteLater()
            del self._anims[:-24]

    def _canvas_menu(self, index: int, pos: QPoint) -> None:
        menu = QMenu(self)
        menu.addAction("复制全部内容", lambda: self._copy_canvas(index))
        menu.addSeparator()
        menu.addAction("清空本页（可撤销）", lambda: self._clear_canvas(index))
        menu.exec(self.editors[index].mapToGlobal(pos))

    def _copy_canvas(self, index: int) -> None:
        QApplication.clipboard().setText(self.store.canvas_text(index))
        self._status("已复制到剪贴板")

    def _clear_canvas(self, index: int) -> None:
        previous = self.store.canvas_text(index)
        if not previous.strip():
            self._status("本页已经是空的")
            return
        self.store.set_canvas_text(index, "")
        self._loading = True
        self.editors[index].setPlainText("")
        self._loading = False
        self._schedule_autofit()
        self.undo_toast.show_message(
            f"已清空画布 {index + 1}", "撤销",
            lambda: self._undo({"kind": "canvas_text", "index": index, "previous": previous}),
            UNDO_TIMEOUT_MS)
        self._refresh_calendar()
        self._update_status()

    # ==================================================== 日程输入闭环
    def _submit_schedule(self) -> None:
        raw = self.input.text().strip()
        if not raw:
            self._status("先写点什么，再回车添加")
            self.input.setFocus()
            return

        parsed = parse_schedule(raw, self._selected_date)
        row = self.store.add_schedule(parsed["text"], parsed["time"], parsed["date"])

        # ① 输入框瞬间清空，可立即输入下一条
        self.input.clear()
        # 输入里带了别的日期（如"明天 10:00 评审"）则自动切到那天
        if parsed["date"] != self._selected_date:
            self._selected_date = parsed["date"]
            self.store.set_setting("selected_date", self._selected_date)
            self.calendar.select(self._selected_date)
            self._sync_input_placeholder()
        # ② 0.8 秒绿字提示
        self._flash_saved(parsed)
        # ③ 清单立即追加（新卡片淡入）
        self._refresh_schedule_list(highlight_id=row["id"])
        self._refresh_calendar()
        self._update_status()
        self.input.setFocus()

    def _flash_saved(self, parsed: dict) -> None:
        suffix = f" · {parsed['time']}" if parsed["time"] else (
            f" · {parsed['date'][5:]}" if parsed["explicit_day"] else "")
        self.flash_label.setText(f"已保存 ✓{suffix}")
        self.flash_label.setVisible(True)
        self._fade_widget(self.flash_label, 0.0, 1.0, 120)   # 临时效果器，用完即摘
        if self._flash_timer is None:
            self._flash_timer = QTimer(self)
            self._flash_timer.setSingleShot(True)
            self._flash_timer.timeout.connect(self._hide_flash)
        self._flash_timer.start(SAVED_FLASH_MS)

    def _hide_flash(self) -> None:
        self.flash_label.setVisible(False)
        self.flash_label.setGraphicsEffect(None)

    def _refresh_schedule_list(self, highlight_id: int | None = None) -> None:
        """按当前选中日期重建清单（旧控件彻底销毁，绝无残影；卡片高度固定，超出即滚动）。"""
        clear_layout(self.schedule_layout)
        rows = self.store.schedules_for(self._selected_date)
        if not rows:
            empty = QLabel("这一天还没有日程 · 上面输入后回车即可添加")
            empty.setObjectName("EmptyHint")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.schedule_layout.addWidget(empty)
        for row in rows:
            card = ScheduleCard(row)
            card.toggled.connect(self._toggle_schedule)
            card.deleted.connect(self._delete_schedule)
            self.schedule_layout.addWidget(card)
            if highlight_id is not None and row["id"] == highlight_id:
                # 新卡片高亮闪一下（属性切换，不用透明度效果器 —— 避免卡片空白/不可见）
                card.flash()
        self.schedule_layout.addStretch(1)
        self.schedule_scroll.verticalScrollBar().setValue(0)

        done = sum(1 for row in rows if row["done"])
        self.panel_meta.setText(f"{len(rows) - done} 待办 · {done} 已完成" if rows else "")
        prefix = "⏰ 今日日程" if self._selected_date == today_str() else "🗂 历史日程"
        self.panel_title.setText(f"{prefix} · {self._date_label(self._selected_date)}")
        self.back_today_btn.setVisible(self._selected_date != today_str())

    @staticmethod
    def _date_label(day: str) -> str:
        try:
            parsed = datetime.strptime(day, DAY_FMT).date()
        except ValueError:
            return day
        return f"{parsed.month} 月 {parsed.day} 日 周{WEEKDAY_NAMES[parsed.weekday()]}"

    def _toggle_schedule(self, schedule_id: int) -> None:
        if self.store.toggle(schedule_id) is None:
            return
        # 勾选后划线并沉底（排序键已把已完成排到最后）
        self._refresh_schedule_list()
        self._refresh_calendar()
        self._update_status()

    def _delete_schedule(self, schedule_id: int) -> None:
        row = self.store.find(schedule_id)
        payload = self.store.delete(schedule_id)
        if payload is None:
            return
        self._refresh_schedule_list()
        self._refresh_calendar()
        self._update_status()
        text = (row["text"] if row else "")[:16]
        self.undo_toast.show_message(f"已删除「{text}」", "撤销",
                                     lambda: self._undo(payload), UNDO_TIMEOUT_MS)

    def _undo(self, payload: dict) -> None:
        if not self.store.restore(payload):
            self._status("没有可撤销的操作")
            return
        if payload.get("kind") == "canvas_text":
            index = payload["index"]
            self._loading = True
            self.editors[index].setPlainText(self.store.canvas_text(index))
            self._loading = False
        self._refresh_schedule_list()
        self._refresh_calendar()
        self._update_status()
        self.undo_toast.show_message("已撤销，数据已恢复", timeout=1500)

    def _back_to_today(self) -> None:
        self._on_day_picked(today_str())

    def _sync_input_placeholder(self) -> None:
        if self._selected_date == today_str():
            self.input.setPlaceholderText("输入日程，例如：15:00 部门例会，回车添加")
        else:
            self.input.setPlaceholderText(
                f"添加到 {self._date_label(self._selected_date)}，例如：10:00 复盘，回车添加")

    # ==================================================== 月历展开（只改自身高度）
    def _lower_spacing(self) -> int:
        """下方区块内月历与日程面板之间的布局间距（预算必须计入，否则月历被压缩）。"""
        layout = self.lower.layout()
        return layout.spacing() if layout is not None else 0

    def _calendar_budget(self) -> int:
        """月历最多能占用的高度：下方可用空间（可从画布借）+ 保持日程列表最小高度。"""
        total = self._split_total()
        if total <= 0:
            return self.calendar.natural_height()
        panel_min = self.schedule_panel.minimumSizeHint().height()
        lower_max = max(0, total - CANVAS_MIN_H)         # 月历能拿到的上限（画布保底）
        return max(150, lower_max - panel_min - self._lower_spacing())

    def toggle_calendar(self, open_state: bool | None = None) -> None:
        target = (not self._calendar_open) if open_state is None else bool(open_state)
        if target == self._calendar_open:
            return
        self._calendar_open = target
        self.calendar_btn.setProperty("active", target)
        repolish(self.calendar_btn)

        panel_min = self.schedule_panel.minimumSizeHint().height()
        spacing = self._lower_spacing()
        if target:
            # ① 先算出月历需要多高（空间不够时自动压缩日期格，不裁剪任何一行）
            total_h = self.calendar.fit_height(self._calendar_budget())
            self._calendar_target_h = total_h
            # ② 把"月历 + 间距 + 日程面板最小高度"一起交给下方区块，画布平滑收缩让位
            total = self._split_total()
            lower_target = total_h + panel_min + spacing
            self._set_split(total - lower_target, lower_target)
            self.calendar.setVisible(True)
            self._refresh_calendar()
            start, end = self.calendar.maximumHeight(), total_h
        else:
            prev = self._calendar_target_h
            self._calendar_target_h = 0
            start, end = self.calendar.maximumHeight(), 0
            # 收起后把空间还给画布
            sizes = self.splitter.sizes()
            if sizes:
                self._set_split(sizes[0] + prev + spacing, sizes[1] - prev - spacing)

        animation = QPropertyAnimation(self.calendar, b"maximumHeight", self)
        animation.setDuration(CALENDAR_ANIM_MS)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.setStartValue(start)
        animation.setEndValue(end)
        if not target:
            animation.finished.connect(lambda: self.calendar.setVisible(False))
            self._preview_timer.stop()
            self._preview.hide_preview()
        animation.start()
        self._remember(animation)

    # ==================================================== 月历悬停预览
    def _on_day_hovered(self, day: str) -> None:
        self._hover_day = day
        self._preview_timer.start(220)          # 轻微延迟，扫过时不闪烁

    def _on_day_unhovered(self) -> None:
        self._preview_timer.stop()
        self._hover_day = ""
        self._preview.hide_preview()

    def _show_day_preview(self) -> None:
        if not self._hover_day or not self._calendar_open or not self.isVisible():
            return
        self._preview.show_for(self._hover_day, self.store.schedules_for(self._hover_day))

    # ==================================================== 一键导出（编号列表 → 剪贴板）
    def _export_day(self) -> None:
        """把选中日期的全部待办整理成 1. 2. 3. 编号列表复制到剪贴板，直接可粘贴。

        不写任何文件：纯文本格式，粘到聊天窗口、邮件、文档里都整齐。
        """
        day = self._selected_date
        rows = self.store.schedules_for(day)
        if not rows:
            self._status(f"{self._date_label(day)} 没有日程可复制")
            return

        lines = [f"{self._date_label(day)} 日程 · 共 {len(rows)} 条", ""]
        for index, row in enumerate(rows, start=1):
            moment = f"[{row['time']}] " if row.get("time") else ""
            mark = "（已完成）" if row["done"] else ""
            lines.append(f"{index}. {moment}{row['text']}{mark}")
        QApplication.clipboard().setText("\n".join(lines))

        message = f"已复制 {len(rows)} 条日程（编号列表，可直接粘贴）"
        self._status(message)
        self.undo_toast.show_message(message, timeout=3000)

    def _on_day_picked(self, day: str) -> None:
        self._selected_date = day
        self.store.set_setting("selected_date", day)
        self.calendar.select(day)
        self._sync_input_placeholder()
        self._refresh_schedule_list()
        self._update_status()

    def _refresh_calendar(self) -> None:
        self.calendar.select(self._selected_date)

    # ==================================================== 到点提醒（全屏居中浮层）
    def _poll_reminders(self) -> None:
        now = datetime.now()
        due: list[dict] = []
        for row in self.store.due_schedules(now):
            self.store.mark_notified(row["id"])
            try:
                when = datetime.strptime(f"{row['date']} {row['time']}", "%Y-%m-%d %H:%M")
            except ValueError:
                when = None
            if when is not None and (now - when) > timedelta(hours=12):
                continue                     # 超过 12 小时的陈旧日程静默跳过，避免启动刷屏
            due.append(row)
        if not due:
            return
        self._refresh_schedule_list()
        self._refresh_calendar()
        self._update_status()
        self._show_reminder_overlay(due)

    def _show_reminder_overlay(self, rows: list[dict]) -> None:
        """全屏居中覆盖提醒：每块屏幕一个浮层，到点必现、不依赖系统通知权限。"""
        for row in rows:
            if all(row["id"] != item["id"] for item in self._active_reminders):
                self._active_reminders.append(row)
        if not self._overlays:
            screens = QGuiApplication.screens() or [QApplication.primaryScreen()]
            for screen in screens:
                overlay = ReminderOverlay(screen, SNOOZE_MINUTES)
                overlay.dismissed.connect(self._on_reminder_dismissed)
                overlay.snoozed.connect(self._on_reminder_snoozed)
                overlay.completed.connect(self._on_reminder_completed)
                self._overlays.append(overlay)
        for overlay in self._overlays:
            overlay.present(self._active_reminders)
        play_reminder_sound()

    def _close_overlays(self) -> None:
        for overlay in self._overlays:
            overlay.dismiss()
        self._active_reminders = []

    def _on_reminder_dismissed(self) -> None:
        count = len(self._active_reminders)
        self._close_overlays()
        if count:
            self._status(f"已知晓 {count} 条日程提醒")

    def _on_reminder_snoozed(self, minutes: int) -> None:
        count = len(self._active_reminders)
        for row in list(self._active_reminders):
            self.store.snooze(row["id"], minutes)
        self._close_overlays()
        self._refresh_schedule_list()
        self._refresh_calendar()
        self._update_status()
        if count:
            self._status(f"已延后 {count} 条（{minutes} 分钟后再次提醒）")

    def _on_reminder_completed(self) -> None:
        count = len(self._active_reminders)
        for row in list(self._active_reminders):
            self.store.toggle(row["id"], True)
        self._close_overlays()
        self._refresh_schedule_list()
        self._refresh_calendar()
        self._update_status()
        if count:
            self._status(f"已完成 {count} 条日程")

    # ==================================================== 淡出
    def _fade_to(self, target: float, duration: int) -> None:
        animation = getattr(self, "_fade_anim", None)
        if animation is None:
            animation = QPropertyAnimation(self, b"windowOpacity", self)
            animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
            self._fade_anim = animation
        running = animation.state() == QAbstractAnimation.State.Running
        if running:
            if abs(float(animation.endValue()) - target) < 0.01:
                return
        elif abs(self.windowOpacity() - target) < 0.01:
            return
        animation.stop()
        animation.setDuration(duration)
        animation.setStartValue(self.windowOpacity())
        animation.setEndValue(target)
        animation.start()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._fade_to(1.0, FADE_IN_MS)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        QTimer.singleShot(90, self._maybe_fade_out)
        super().leaveEvent(event)

    def _maybe_fade_out(self) -> None:
        if not self._fade_enabled or not self.isVisible():
            return
        if QApplication.activePopupWidget() is not None:
            return
        if self.capture_bar.isVisible() or self.undo_toast.isVisible():
            return
        focus = QApplication.focusWidget()
        if FADE_SKIP_WHEN_TYPING and isinstance(focus, (QLineEdit, QTextEdit)):
            return
        if self.underMouse():
            return
        self._fade_to(FADE_OUT_OPACITY, FADE_OUT_MS)

    def toggle_fade_lock(self) -> None:
        self._fade_enabled = not self._fade_enabled
        self.store.set_setting("fade_lock", not self._fade_enabled)
        self.lock_btn.setProperty("active", not self._fade_enabled)
        self.lock_btn.setToolTip("已锁定常显（鼠标移出不再淡出）" if not self._fade_enabled
                                 else "锁定常显（关闭鼠标移出淡出）")
        repolish(self.lock_btn)
        if not self._fade_enabled:
            self._fade_to(1.0, FADE_IN_MS)
        self._status("已锁定常显" if not self._fade_enabled else "已开启鼠标移出淡出")

    # ==================================================== 状态 / 托盘
    def _update_status(self) -> None:
        stamp = self.store.last_saved or datetime.now().strftime("%H:%M:%S")
        self.status_label.setText(
            f"已保存 {stamp} · 画布 {self._page + 1}/{CANVAS_COUNT}")
        pending = sum(1 for row in self.store.schedules_for(self._selected_date)
                      if not row["done"])
        self.count_label.setText(f"{self._date_label(self._selected_date)} · 待办 {pending}")

    def _status(self, message: str) -> None:
        self.status_label.setText(message)
        if self._status_timer is None:
            self._status_timer = QTimer(self)
            self._status_timer.setSingleShot(True)
            self._status_timer.timeout.connect(self._update_status)
        self._status_timer.start(2400)

    def _build_tray(self) -> None:
        icon = app_icon()
        self.setWindowIcon(icon)
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        menu = QMenu()
        menu.addAction("显示 / 隐藏窗口", self._toggle_visibility)
        menu.addAction(f"极速速记（{HOTKEY}）", self._show_capture)
        menu.addSeparator()
        menu.addAction("测试系统通知", self._test_notification)
        menu.addAction("打开数据目录", self._open_data_dir)
        menu.addSeparator()
        menu.addAction("退出", self._quit)

        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setContextMenu(menu)
        self.tray.setToolTip(f"{APP_NAME} · 速记 {HOTKEY}")
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()
        self.toaster.tray = self.tray

    def _test_notification(self) -> None:
        channel = self.toaster.send(f"{APP_NAME} · 通知自检", "看到这条通知说明提醒链路正常。")
        self._status({"windows-toast": "已通过 Windows 原生通知发送",
                      "tray": "已通过托盘通知发送"}.get(channel, "通知通道不可用"))

    def _open_data_dir(self) -> None:
        try:
            os.startfile(APP_DIR)  # type: ignore[attr-defined]
        except OSError:
            self._status("无法打开数据目录")

    def _toggle_visibility(self) -> None:
        if self.isVisible():
            self._remember_position()
            self.hide()
        else:
            self._fade_to(1.0, FADE_IN_MS)
            self.show()
            self.raise_()
            self.activateWindow()

    def _on_tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self._toggle_visibility()

    # ==================================================== 速记条
    def _show_capture(self) -> None:
        self.capture_bar.popup(self._page)

    def _on_capture_submit(self, text: str) -> None:
        target = self._page
        match = re.match(r"^@([1-5])\s+(.*)$", text)
        if match:
            target = int(match.group(1)) - 1
            text = match.group(2).strip()
        if not text:
            self.capture_bar.flash("内容为空")
            return
        parsed = parse_schedule(text, self._selected_date)
        if parsed["time"] or parsed["explicit_day"]:
            self.store.add_schedule(parsed["text"], parsed["time"], parsed["date"])
            if parsed["date"] != self._selected_date:
                self._on_day_picked(parsed["date"])
            else:
                self._refresh_schedule_list()
            self._refresh_calendar()
            self._update_status()
            self.capture_bar.flash(f"已建日程 {parsed['time'] or parsed['date'][5:]}")
            return
        current = self.store.canvas_text(target)
        separator = "" if (not current or current.endswith("\n")) else "\n"
        self.store.set_canvas_text(target, f"{current}{separator}{text}")
        self._loading = True
        self.editors[target].setPlainText(self.store.canvas_text(target))
        self._loading = False
        if target != self._page:
            self.switch_page(target, animate=False)
        self._refresh_calendar()
        self._update_status()
        self.capture_bar.flash(f"已记入画布 {target + 1}")

    # ==================================================== 生命周期
    def _quit(self) -> None:
        self._remember_position()
        self.store.save()
        self._preview.hide_preview()
        self._close_overlays()
        if self.hotkey is not None:
            self.hotkey.unregister()
        if self.tray is not None:
            self.tray.hide()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._remember_position()
        self._preview.hide_preview()
        if self.tray is None:
            self._quit()
            event.accept()
            return
        event.ignore()
        self.hide()
        if not self.settings.get("tray_hinted"):
            self.store.set_setting("tray_hinted", True)
            self.tray.showMessage(APP_NAME,
                                  f"已退到托盘，日程提醒照常触发。\n{HOTKEY} 可随时随手速记。",
                                  QSystemTrayIcon.MessageIcon.Information, 4000)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._preview.hide_preview()
        self._schedule_autofit()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._preview.hide_preview()
        super().hideEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            if self.capture_bar.isVisible():
                self.capture_bar.hide()
            elif self._calendar_open:
                self.toggle_calendar(False)
            else:
                super().keyPressEvent(event)
        else:
            super().keyPressEvent(event)


# ==========================================================================
# §12 全局速记条（独立悬浮窗口，Alt+Q 唤起）
# ==========================================================================
class CaptureBar(QWidget):
    submitted = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(560, 78)

        shadow = QFrame()
        shadow.setObjectName("CaptureShadow")
        soft_shadow(shadow, blur=24, dy=9, alpha=200)

        frame = QFrame()
        frame.setObjectName("CaptureRoot")

        self.dot = QLabel()
        self.dot.setFixedSize(10, 10)
        self.dot.setStyleSheet(f"background: {DOT_COLORS[0]}; border-radius: 5px;")
        self.input = QLineEdit()
        self.input.setObjectName("CaptureInput")
        self.input.setPlaceholderText(
            "随手记一笔…  回车保存　·　\"15:30 例会\" 直接建日程　·　\"@3\" 指定画布")
        self.input.returnPressed.connect(self._submit)
        hint = QLabel("Esc")
        hint.setObjectName("HintText")

        inner = QHBoxLayout(frame)
        inner.setContentsMargins(16, 0, 16, 0)
        inner.setSpacing(11)
        inner.addWidget(self.dot)
        inner.addWidget(self.input, 1)
        inner.addWidget(hint)

        # 阴影层与输入层重叠同一格：效果器只作用于装饰层，输入框渲染保持干净
        holder = QGridLayout()
        holder.setContentsMargins(0, 0, 0, 0)
        holder.addWidget(shadow, 0, 0)
        holder.addWidget(frame, 0, 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addLayout(holder)
        self._frame = frame

        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._slide = QPropertyAnimation(self, b"pos", self)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

    def popup(self, page_index: int) -> None:
        color = DOT_COLORS[page_index % len(DOT_COLORS)]
        self.dot.setStyleSheet(f"background: {color}; border-radius: 5px;")
        screen = QApplication.primaryScreen()
        area = screen.availableGeometry() if screen else None
        if area is not None:
            x = area.center().x() - self.width() // 2
            y = area.top() + 150
        else:
            x, y = 100, 100
        self.setWindowOpacity(0.0)
        self.move(x, y - 14)
        self.input.clear()
        self.input.setReadOnly(False)
        self._frame.setStyleSheet("")
        self.show()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()

        self._fade.stop()
        self._fade.setDuration(130)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()
        self._slide.stop()
        self._slide.setDuration(170)
        self._slide.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._slide.setStartValue(QPoint(x, y - 14))
        self._slide.setEndValue(QPoint(x, y))
        self._slide.start()

    def flash(self, message: str) -> None:
        self._frame.setStyleSheet(f"#CaptureRoot {{ border: 1px solid {OK}; }}")
        self.input.setText(message)
        self.input.setReadOnly(True)
        self._hide_timer.start(560)

    def hideEvent(self, event) -> None:  # noqa: N802
        self._frame.setStyleSheet("")
        self.input.setReadOnly(False)
        super().hideEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)

    def _submit(self) -> None:
        text = self.input.text().strip()
        if text:
            self.submitted.emit(text)


# ==========================================================================
# §13 入口
# ==========================================================================
def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    app.setPalette(dark_palette())
    app.setStyleSheet(build_qss(ensure_check_icon()))

    window = MainWindow()
    window.show()
    window.raise_()
    window.activateWindow()
    log(
        f"[OK] {APP_NAME} 已启动 | 数据: {DATA_FILE} | 画布: {CANVAS_COUNT} 张 | "
        f"窗口: {window.width()}x{window.height()} | "
        f"速记热键: {HOTKEY} ({'全局生效' if window.hotkey.registered else '应用内回退'}) | "
        f"通知: {'Windows 原生 Toast' if window.toaster.enabled else '托盘气泡'}",
    )
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
