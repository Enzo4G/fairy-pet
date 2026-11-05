"""Fairy desktop pet.

A frameless, per-pixel-transparent, always-on-top sprite that lives on the
desktop independently of Hana's main window. Everything slow (HTTP to Hana)
runs off the UI thread, so the animation stays at 30 fps.
"""

from __future__ import annotations

import base64
import ctypes
import hashlib
import hmac
import html
import json
import math
import mimetypes
import os
import random
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from ctypes import wintypes
from html import escape

from PySide6.QtCore import QRectF, QObject, QPoint, QPointF, QRect, QRunnable, QSize, Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QAction,
    QDesktopServices,
    QActionGroup,
    QColor,
    QCursor,
    QFont,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QButtonGroup,
    QColorDialog,
    QDialog,
    QSpinBox,
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QLayout,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QSizePolicy,
    QSlider,
    QSystemTrayIcon,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

def _app_dir() -> str:
    """Where the program lives.

    In a frozen build that is the folder holding the exe, so ``FairyPet/`` stays
    beside it instead of inside the single-file unpack directory, which is wiped
    on exit and would silently drop the login and the window position.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


HERE = _app_dir()
# Read-only resources: onefile builds unpack them into sys._MEIPASS.
RESOURCE_DIR = getattr(sys, "_MEIPASS", HERE)
ASSETS = os.path.join(RESOURCE_DIR, "assets")
# Portable on purpose: settings live beside the program instead of %APPDATA%, so
# the folder is the whole install and the pet's spawned environment (which does
# not always inherit APPDATA) always reads the same files.
CONFIG_DIR = os.path.join(HERE, "FairyPet")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
STATE_PATH = os.path.join(CONFIG_DIR, "state.json")
HANA_HOME = os.path.join(os.path.expanduser("~"), ".hanako")
DSH_HOME = os.path.join(os.path.expanduser("~"), ".dsh")

ART = 256                      # source art (reference geometry scaled 1.6x)
TICK_MS = 16                   # ~60 fps
FRAME_SCALE = 1.35              # window vs. disc, leaves room for the halo pulse
WEB = os.path.join(ASSETS, "web")
DEFAULT_SIZE = 160

# Animation speed: three ways to pick one multiplier, never a hidden constant.
SPEED_MODES = [("cpu", "跟 CPU 占用率"), ("gpu", "跟显卡占用率"), ("manual", "手动")]
SPEED_MIN = 0.4
SPEED_MAX = 3.0
SPEED_IDLE = 45.0              # below this the machine counts as quiet: 1x
SPEED_SPAN = 45.0             # 45% -> 90% spans the rest of the range

# Eyelid closing follows one load channel, or nothing at all.
LID_MODES = [
    ("cpu", "跟 CPU 占用率"),
    ("gpu", "跟显卡占用率"),
    ("memory", "跟内存占用率"),
    ("off", "关闭"),
]

INK = "#0a0f16"
LINE = "rgba(126,170,222,0.18)"
TEXT = "#dfe8f2"
DIM = "#7d8fa4"
ACCENT = "#4d8fd6"

# ---------------------------------------------------------------- identity
# Everything that names the project lives here. The About window reads this
# block, so a fork that wants to hide the credits has to edit code instead of
# just deleting a menu entry.
APP_TITLE = "Fairy 桌宠"
APP_VERSION = "2.0.0"
AUTHOR = "（待填）"
PROJECT_URL = ""          # 待定：填上仓库地址后，关于窗口里会出现「打开仓库」
CREDIT_NAME = "Chengzhibense / Fairy-DSH"
CREDIT_URL = "https://github.com/Chengzhibense/Fairy-DSH"
CREDIT_NOTE = "形象设定与动画逻辑参考了该开源项目"
LICENSE_LINE = "个人非商业使用 · 禁止商业用途"

# Build mark. Base64 so it does not read like a greeting from a grep, and so
# anyone who strips the About window still leaves a fingerprint in the source.
_BUILD_MARK = "RmFpcnlQZXQ6djI6b3JpZ2luYWwtYnVpbGQ6bm9uLWNvbW1lcmNpYWw="


def build_mark() -> str:
    try:
        return base64.b64decode(_BUILD_MARK).decode("utf-8", "replace")
    except Exception:
        return ""


def build_id() -> str:
    return hashlib.sha256(_BUILD_MARK.encode("ascii")).hexdigest()[:8].upper()

THINK_LEVELS = ["off", "minimal", "low", "medium", "high", "xhigh", "max"]

DEFAULT_THEME = {
    "bg": INK,
    "bubble": "#1b2b3f",
    "userText": "#cfe0f2",
    "text": "#dfe8f2",
    "accent": "#2b4b6f",
    "tag": "#6f93bd",
    "bodySize": 13,
    "tagSize": 10,
}

PIN_MODES = [
    ("none", "不置顶"),
    ("yield", "不覆盖全屏窗口"),
    ("always", "强行全局置顶"),
]


# -------------------------------------------------------------- dsh bridge


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _listening_ports() -> list[int]:
    """Loopback ports currently in LISTEN, via netstat so no extra dependency is needed."""
    try:
        completed = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True,
            timeout=6,
            creationflags=0x08000000,
        )
    except Exception:
        return []
    # netstat speaks the OEM code page, never UTF-8.
    output = (completed.stdout or b"").decode("mbcs", "replace")
    ports = set()
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 4 or parts[0].upper() != "TCP" or parts[3].upper() != "LISTENING":
            continue
        address = parts[1]
        if not (address.startswith("127.0.0.1:") or address.startswith("[::1]:")):
            continue
        try:
            ports.add(int(address.rsplit(":", 1)[1]))
        except ValueError:
            continue
    return sorted(ports)


class Bridge:
    """Synchronous client for a running dsh runtime (called off the UI thread).

    dsh serves a local HTTP API — ``POST /api/<method>`` — behind a cookie signed
    with the secret kept in ``~/.dsh/.credentials.yaml``. Minting that cookie here
    means the pet reads and steers exactly the sessions the dsh client shows, with
    no Hana and no token to paste.
    """

    def __init__(self) -> None:
        self.port: int | None = None
        self.cookie: str | None = None
        self.current: str | None = None
        self.workspace: str | None = None
        self._seq = 0
        self._seen_text: dict[str, str] = {}
        self._records_cache: dict[tuple[str, int], list[dict]] = {}

    # ------------------------------------------------------------ connection

    def _secret(self) -> bytes:
        path = os.path.join(DSH_HOME, ".credentials.yaml")
        try:
            with open(path, "r", encoding="utf-8") as handle:
                lines = handle.read().splitlines()
        except OSError:
            raise RuntimeError("找不到 dsh 凭据（~/.dsh/.credentials.yaml）") from None
        inside = False
        for line in lines:
            if line.startswith("  client-connection/browser-session:"):
                inside = True
                continue
            if inside:
                stripped = line.strip()
                if stripped.startswith("secret:"):
                    raw = stripped.split(":", 1)[1].strip()
                    return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
                if stripped and not line.startswith("    "):
                    break
        raise RuntimeError("dsh 凭据里没有会话密钥")

    @staticmethod
    def _looks_like_dsh(port: int) -> bool:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=0.4) as response:
                return b"dsh" in response.read(180)
        except urllib.error.HTTPError as error:
            try:
                return b"dsh web" in error.read(180)
            except Exception:
                return False
        except Exception:
            return False

    def _mint(self, port: int) -> str:
        authority = f"127.0.0.1:{port}"
        name = "dsh-auth-" + _b64u(hashlib.sha256(authority.encode()).digest())
        now = int(time.time() * 1000)
        payload = {
            "version": 1,
            "authority": authority,
            "issuedAt": now,
            "expiresAt": now + 7 * 86400 * 1000,
        }
        body = _b64u(json.dumps(payload, separators=(",", ":")).encode())
        signature = _b64u(hmac.new(self._secret(), body.encode(), hashlib.sha256).digest())
        return f"{name}=v1.{body}.{signature}"

    def _ensure(self) -> None:
        if self.port and self.cookie:
            return
        candidates = []
        if self.port:
            candidates.append(self.port)
        candidates.extend(port for port in _listening_ports() if port not in candidates)
        for port in candidates:
            if self._looks_like_dsh(port):
                self.port = port
                self.cookie = self._mint(port)
                return
        self.port = None
        self.cookie = None
        raise RuntimeError("没找到运行中的 dsh，先把 dsh 客户端打开")

    def ready(self) -> bool:
        try:
            self._ensure()
            return True
        except Exception:
            return False

    def _rpc(self, method: str, args: dict | None = None, timeout: float = 14.0):
        self._ensure()
        self._seq += 1
        envelope = {
            "type": "client-request",
            "rpcId": f"pet{self._seq}",
            "method": method,
            "payload": {"args": args or {}},
        }
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/{method}",
            data=json.dumps(envelope).encode("utf-8"),
            headers={
                "Host": f"127.0.0.1:{self.port}",
                "Cookie": self.cookie or "",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = json.loads(response.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as error:
            self.port = None
            self.cookie = None
            if error.code == 401:
                raise RuntimeError("dsh 拒绝授权，重开一次客户端试试") from None
            raise RuntimeError(f"dsh 返回 HTTP {error.code}") from None
        except Exception as error:
            self.port = None
            self.cookie = None
            raise RuntimeError(f"连不上 dsh：{error}") from None
        result = (body or {}).get("result") or {}
        if not result.get("ok"):
            message = (result.get("error") or {}).get("message") or "dsh 拒绝了这个请求"
            raise RuntimeError(message)
        return result.get("value")

    # --------------------------------------------------------------- helpers

    def _rows(self) -> list[dict]:
        value = self._rpc("session/list", {"_request": {}}) or {}
        return value.get("items") or []

    @staticmethod
    def _row(rows: list[dict], session_id: str | None) -> dict | None:
        for row in rows:
            if row.get("sessionId") == session_id:
                return row
        return None

    @staticmethod
    def _values(row: dict | None) -> dict:
        return ((row or {}).get("projections") or {}).get("values") or {}

    @staticmethod
    def _as_of(row: dict | None) -> int:
        return int(((row or {}).get("projections") or {}).get("asOfSeq") or 0)

    def _current_id(self, rows: list[dict]) -> str | None:
        if self.current and self._row(rows, self.current):
            return self.current
        best = None
        for row in rows:
            values = self._values(row)
            blank = (values.get("sessionListMetadata") or {}).get("blank", True)
            key = (0 if not blank else 1, -int(row.get("updatedAt") or 0))
            if best is None or key < best[0]:
                best = (key, row.get("sessionId"))
        if best:
            self.current = best[1]
        return self.current

    def _records(self, session_id: str, as_of: int | None = None) -> list[dict]:
        if as_of is None:
            as_of = self._as_of(self._row(self._rows(), session_id))
        if as_of <= 0:
            return []
        # A poll every 3s used to re-fetch and re-parse the whole transcript.
        # asOfSeq only moves when the session actually grows, so keying on it is
        # enough to skip the traffic.
        key = (session_id, as_of)
        cached = self._records_cache.get(key)
        if cached is not None:
            return cached
        value = self._rpc(
            "session/page",
            {
                "request": {
                    "address": {"kind": "session", "sessionId": session_id},
                    "throughSeq": as_of,
                    "maxMessages": 200,
                }
            },
        ) or {}
        records = value.get("records") or []
        self._records_cache = {k: v for k, v in self._records_cache.items() if k[0] != session_id}
        self._records_cache[key] = records
        return records

    @staticmethod
    def _text_of(message: dict) -> str:
        parts = []
        for block in message.get("content") or []:
            if block.get("type") == "text" and block.get("text"):
                parts.append(str(block["text"]))
        return "\n".join(parts).strip()

    @classmethod
    def _messages(cls, records: list[dict]) -> list[dict]:
        out = []
        for record in records:
            event = record.get("event") or {}
            kind = event.get("type")
            data = event.get("data") or {}
            if kind == "user/message":
                if (data.get("source") or {}).get("kind") != "user":
                    continue
                text = cls._text_of(data)
                if text:
                    out.append({"role": "user", "text": text})
            elif kind == "assistant/message":
                text = cls._text_of(data.get("message") or {})
                if text:
                    out.append({"role": "assistant", "text": text})
        return out

    # ------------------------------------------------------------ public API

    def state(self) -> dict:
        rows = self._rows()
        session_id = self._current_id(rows)
        row = self._row(rows, session_id)
        values = self._values(row)
        running = bool((row or {}).get("running"))
        selection = values.get("modelSelection") or {}
        chosen = selection.get("next") or selection.get("lastUsed") or {}
        bubbles: list[str] = []
        if session_id and not running:
            records = None
            text = ""
            as_of = self._as_of(row)
            if as_of:
                records = self._records(session_id, as_of)
                text = ""
                for message in self._messages(records or []):
                    if message["role"] == "assistant":
                        text = message["text"]
            if text and self._seen_text.get(session_id) != text:
                if session_id in self._seen_text:
                    bubbles.append(text)
                self._seen_text[session_id] = text
        return {
            "working": running,
            "bubbles": bubbles,
            "modelId": chosen.get("model"),
            "thinkingLevel": chosen.get("reasoningEffort"),
            "permission": (values.get("permissions") or {}).get("currentValue"),
            "preset": values.get("agentPreset"),
            "sessionId": session_id,
        }

    def sessions(self) -> dict:
        rows = self._rows()
        out = []
        for row in rows:
            values = self._values(row)
            out.append(
                {
                    "id": row.get("sessionId"),
                    "title": values.get("title") or "未命名对话",
                    "updatedAt": row.get("updatedAt"),
                }
            )
        out.sort(key=lambda item: -int(item.get("updatedAt") or 0))
        return {"sessions": out, "current": self._current_id(rows)}

    def history(self, session_id: str | None = None) -> dict:
        rows = self._rows()
        sid = session_id or self._current_id(rows)
        if not sid:
            return {"messages": [], "running": False}
        row = self._row(rows, sid)
        records = self._records(sid, self._as_of(row))
        return {"messages": self._messages(records), "running": bool((row or {}).get("running"))}

    def select(self, session_id: str) -> dict:
        self.current = session_id
        return {"sessionId": session_id}

    def new_session(self) -> dict:
        request: dict = {}
        if self.workspace:
            request["workspaceId"] = self.workspace
        else:
            request["cwd"] = os.path.expanduser("~")
        value = self._rpc("session/create", {"request": request}) or {}
        session_id = value.get("sessionId")
        if session_id:
            self.current = session_id
        return {"sessionId": session_id}

    def send(self, text: str, images: list | None = None, session_id: str | None = None) -> dict:
        rows = self._rows()
        sid = session_id or self._current_id(rows)
        if not sid:
            sid = self.new_session().get("sessionId")
        if not sid:
            raise RuntimeError("没有可写入的会话")
        content = []
        for image in images or []:
            content.append(
                {
                    "type": "image",
                    "mediaType": image.get("mimeType") or "image/png",
                    "data": image.get("data") or "",
                }
            )
        if text:
            content.append({"type": "text", "text": text})
        if not content:
            return {}
        self._rpc(
            "session/prompt",
            {
                "request": {
                    "requestId": str(uuid.uuid4()),
                    "sessionId": sid,
                    "mode": "queue",
                    "content": content,
                }
            },
        )
        return {"ok": True, "sessionId": sid}

    def models(self) -> dict:
        catalog = self._rpc("session/modelCatalog", {}) or {}
        models = []
        for group in catalog.get("groups") or []:
            for model in group.get("models") or []:
                reasoning = model.get("reasoning") or {}
                models.append(
                    {
                        "id": model.get("id"),
                        "name": model.get("name") or model.get("id"),
                        "provider": group.get("id"),
                        "efforts": [item.get("id") for item in reasoning.get("efforts") or []],
                        "defaultEffort": reasoning.get("defaultEffort"),
                    }
                )
        rows = self._rows()
        row = self._row(rows, self._current_id(rows)) if rows else None
        selection = self._values(row).get("modelSelection") or {}
        chosen = selection.get("next") or selection.get("lastUsed") or catalog.get("default") or {}
        return {
            "models": models,
            "current": {
                "modelId": chosen.get("model"),
                "provider": chosen.get("provider"),
                "effort": chosen.get("reasoningEffort"),
            },
            "default": catalog.get("default") or {},
        }

    def set_model(self, model_id: str, provider: str, effort: str | None = None) -> dict:
        rows = self._rows()
        sid = self._current_id(rows)
        if not sid:
            sid = self.new_session().get("sessionId")
        args = {"sessionId": sid, "provider": provider, "model": model_id}
        if effort:
            args["reasoningEffort"] = effort
        # The gateway wants every single-parameter method wrapped in `request`;
        # a flat body is rejected with "missing request".
        self._rpc("session/selectModel", {"request": args})
        return {"modelId": model_id, "provider": provider, "effort": effort}

    def set_thinking(self, level: str) -> dict:
        info = self.models()
        current = info.get("current") or {}
        default = info.get("default") or {}
        provider = current.get("provider") or default.get("provider")
        model = current.get("modelId") or default.get("model")
        if not (provider and model):
            raise RuntimeError("先选一个模型")
        return self.set_model(model, provider, level)

    def commands(self) -> dict:
        rows = self._rows()
        sid = self._current_id(rows)
        if not sid:
            return {"commands": []}
        value = self._rpc("commands/list", {"agentId": sid}) or []
        return {
            "commands": [
                {"name": item.get("name"), "description": item.get("description") or ""}
                for item in value
            ]
        }

    def compact(self) -> dict:
        return {"ok": True}

    def workspaces(self) -> dict:
        path = os.path.join(DSH_HOME, "storages", "workspace.json")
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception:
            return {"workspaces": [], "current": self.workspace}
        tables = (data.get("tables") or {}).get("workspaces") or {}
        order = (data.get("global") or {}).get("workspaceIds") or []
        spaces = [
            {"id": key, "title": info.get("title") or info.get("path"), "path": info.get("path")}
            for key, info in tables.items()
        ]
        spaces.sort(key=lambda item: order.index(item["id"]) if item["id"] in order else 99)
        if self.workspace is None and spaces:
            self.workspace = spaces[0]["id"]
        return {"workspaces": spaces, "current": self.workspace}

    def set_workspace(self, workspace_id: str) -> dict:
        self.workspace = workspace_id
        return {"workspaceId": workspace_id}

    def create_workspace(self, path: str) -> dict:
        """Register a folder as a workspace (dsh treats an existing path as "created: false")."""
        value = self._rpc("workspace/create", {"request": {"path": path}}) or {}
        workspace = value.get("workspace") or {}
        workspace_id = workspace.get("workspaceId")
        if workspace_id:
            self.workspace = workspace_id
        return {
            "workspaceId": workspace_id,
            "title": workspace.get("title") or os.path.basename(path.rstrip("\\")) or path,
            "path": workspace.get("path") or path,
            "created": bool(value.get("created")),
        }

    def presets(self) -> dict:
        value = self._rpc("agentPresets/list", {}) or {}
        return {"presets": value.get("presets") or []}

    def set_preset(self, preset_id: str) -> dict:
        rows = self._rows()
        sid = self._current_id(rows)
        if not sid:
            raise RuntimeError("先开一个对话")
        self._rpc("agentPresets/select", {"agentId": sid, "agentPreset": preset_id})
        return {"agentPreset": preset_id}


# ------------------------------------------------------------- system metrics


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _cpu_times() -> tuple[int, int]:
    idle = wintypes.FILETIME()
    kernel = wintypes.FILETIME()
    user = wintypes.FILETIME()
    ctypes.windll.kernel32.GetSystemTimes(
        ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
    )

    def ticks(value: wintypes.FILETIME) -> int:
        return (value.dwHighDateTime << 32) | value.dwLowDateTime

    return ticks(idle), ticks(kernel) + ticks(user)


def memory_percent() -> float:
    status = _MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return 0.0
    return float(status.dwMemoryLoad)


def gpu_percent() -> float:
    """NVIDIA only; anything else reports 0 and is simply ignored."""
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=4,
            creationflags=0x08000000,
        )
        values = [int(line) for line in completed.stdout.split() if line.strip().isdigit()]
        return float(max(values)) if values else 0.0
    except Exception:
        return 0.0


class MetricsReader:
    """Samples CPU / memory / GPU; one instance keeps the CPU baseline."""

    def __init__(self) -> None:
        self._last = _cpu_times()

    def sample(self) -> dict:
        idle, total = _cpu_times()
        last_idle, last_total = self._last
        self._last = (idle, total)
        delta_total = max(1, total - last_total)
        delta_idle = max(0, idle - last_idle)
        cpu = 100.0 * (1.0 - delta_idle / delta_total)
        return {
            "cpu": max(0.0, min(100.0, cpu)),
            "memory": memory_percent(),
            "gpu": gpu_percent(),
        }


# ----------------------------------------------------------- deepseek account

DS_CONFIG = os.path.join(CONFIG_DIR, "deepseek.json")
PLATFORM_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Origin": "https://platform.deepseek.com",
    "Referer": "https://platform.deepseek.com/usage",
}
USAGE_RANGES = {
    "today": "当日",
    "week": "近 7 天",
    "month": "本月",
}


def _http_json(url: str, headers: dict, timeout: float = 12.0):
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def _sum_costs(node) -> float:
    total = 0.0
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "cost" and isinstance(value, (int, float)):
                total += float(value)
            elif isinstance(value, (dict, list)):
                total += _sum_costs(value)
    elif isinstance(node, list):
        for item in node:
            total += _sum_costs(item)
    return total


class DeepSeekAccount:
    """Balance and spend, both through the platform console.

    One credential for everything: the web session token from the console. Both
    endpoints answer to it, so a signed-in browser session is all the pet needs.
    """

    def __init__(self) -> None:
        self.data = {}
        try:
            with open(DS_CONFIG, "r", encoding="utf-8") as handle:
                self.data = json.load(handle)
        except Exception:
            self.data = {}
        # Balance and spend both come from the console session now; an ``sk-``
        # key is no longer needed and any stored one is simply ignored.

    def save(self) -> None:
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(DS_CONFIG, "w", encoding="utf-8") as handle:
                json.dump(self.data, handle)
        except Exception:
            pass

    def set(self, key: str | None = None, token: str | None = None) -> None:
        if key is not None:
            self.data["key"] = key.strip()
        if token is not None:
            self.data["token"] = token.strip()
        self.save()

    @property
    def has_token(self) -> bool:
        return bool(self.data.get("token"))

    @property
    def has_key(self) -> bool:
        return bool(self.data.get("key"))

    def balance(self) -> float | None:
        """Balance from the web console — same session as the usage numbers.

        The console exposes it at ``users/get_user_summary``: a legal-tender
        wallet plus a bonus wallet, both in the account currency.
        """
        token = self.data.get("token")
        if not token:
            raise RuntimeError("还没有登录 DeepSeek")
        payload = _http_json(
            "https://platform.deepseek.com/api/v0/users/get_user_summary",
            {**PLATFORM_HEADERS, "Authorization": f"Bearer {token}"},
        )
        code = payload.get("code") if isinstance(payload, dict) else None
        if code:
            if code == 40003:
                raise RuntimeError("登录已过期，打开 DeepSeek 账户重新登录一次")
            raise RuntimeError(f"接口返回 {code}: {payload.get('msg') or '未知错误'}")
        body = (payload.get("data") or {}) if isinstance(payload, dict) else {}
        if body.get("biz_code"):
            raise RuntimeError(f"平台拒绝请求（{body.get('biz_msg') or body.get('biz_code')}）")
        biz = body.get("biz_data") or {}
        total = 0.0
        for wallet in (biz.get("normal_wallets") or []) + (biz.get("bonus_wallets") or []):
            try:
                total += float(wallet.get("balance") or 0.0)
            except (TypeError, ValueError):
                continue
        return total

    def _window(self, key: str) -> tuple[int, int, int]:
        """The platform only accepts day-aligned ends once the range passes a
        day, so every window starts at local midnight and stops at the next
        one — today's partial day simply contributes nothing yet."""
        import datetime

        now = datetime.datetime.now()
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if key == "week":
            start = midnight - datetime.timedelta(days=6)
        elif key == "month":
            start = midnight.replace(day=1)
        else:
            start = midnight
        end = midnight + datetime.timedelta(days=1)
        offset = now.astimezone().utcoffset()
        return int(start.timestamp()), int(end.timestamp()), -int(offset.total_seconds())

    def spent(self, key: str) -> float:
        token = self.data.get("token")
        if not token:
            raise RuntimeError("还没有登录 DeepSeek")
        start, end, tz = self._window(key)
        url = (
            "https://platform.deepseek.com/api/v0/usage/by_api_key/cost"
            f"?start={start}&end={end}&tz={tz}"
        )
        payload = _http_json(url, {**PLATFORM_HEADERS, "Authorization": f"Bearer {token}"})
        code = payload.get("code") if isinstance(payload, dict) else None
        if code:
            if code == 40003:
                raise RuntimeError("令牌失效，请重新登录")
            raise RuntimeError(f"接口返回 {code}: {payload.get('msg') or '未知错误'}")
        body = (payload.get("data") or {}) if isinstance(payload, dict) else {}
        if body.get("biz_code"):
            raise RuntimeError(f"平台拒绝请求（{body.get('biz_msg') or body.get('biz_code')}）")
        biz = body.get("biz_data") or {}
        total = 0.0
        for currency in biz.get("data") or []:
            for series in currency.get("series") or []:
                for bucket in series.get("buckets") or []:
                    total += float(bucket.get("cost") or 0.0)
        return total

    def snapshot(self, key: str) -> dict:
        result = {"range": key, "balance": None, "spent": None, "error": ""}
        errors = []
        try:
            result["balance"] = self.balance()
        except Exception as error:  # noqa: BLE001 - shown in the bar
            errors.append(f"余额: {error}")
        try:
            result["spent"] = self.spent(key)
        except Exception as error:  # noqa: BLE001 - shown in the bar
            errors.append(f"用量: {error}")
        result["error"] = "；".join(errors)
        return result


class JobSignals(QObject):
    ok = Signal(str, object)
    err = Signal(str, str)


class Job(QRunnable):
    def __init__(self, signals: JobSignals, kind: str, fn) -> None:
        super().__init__()
        self.signals = signals
        self.kind = kind
        self.fn = fn

    def run(self) -> None:
        try:
            result = self.fn()
        except Exception as error:  # noqa: BLE001 - surfaced to the UI
            self.signals.err.emit(self.kind, str(error))
            return
        self.signals.ok.emit(self.kind, result)


# -------------------------------------------------------------- win32 plumbing


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", _RECT),
        ("rcWork", _RECT),
        ("dwFlags", wintypes.DWORD),
    ]


_DESKTOP_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Windows.UI.Core.CoreWindow"}


def _window_class(hwnd) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    ctypes.windll.user32.GetClassNameW(hwnd, buffer, 256)
    return buffer.value


def foreground_is_fullscreen(own_handles: set[int]) -> bool:
    """True when someone else's window covers the whole monitor (game, video)."""
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd or int(hwnd) in own_handles:
        return False
    if not user32.IsWindowVisible(hwnd) or _window_class(hwnd) in _DESKTOP_CLASSES:
        return False
    rect = _RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return False
    monitor = user32.MonitorFromWindow(hwnd, 2)
    if not monitor:
        return False
    info = _MONITORINFO()
    info.cbSize = ctypes.sizeof(_MONITORINFO)
    if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return False
    mon = info.rcMonitor
    tol = 2
    return (
        rect.left <= mon.left + tol
        and rect.top <= mon.top + tol
        and rect.right >= mon.right - tol
        and rect.bottom >= mon.bottom - tol
    )


def _process_exe(pid: int) -> str:
    kernel32 = ctypes.windll.kernel32
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return ""
        return buffer.value
    finally:
        kernel32.CloseHandle(handle)


def bring_dsh_to_front() -> bool:
    """Raise the dsh client window. Matching the title is not enough — a browser
    tab that merely mentions dsh would win — so match the executable."""
    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        if user32.GetWindowTextLengthW(hwnd) <= 0:
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        exe = os.path.basename(_process_exe(pid.value)).lower()
        if exe.startswith("deepseek harness"):
            found.append(hwnd)
        return True

    user32.EnumWindows(visit, 0)
    if not found:
        return False
    hwnd = found[0]
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)
    user32.ShowWindow(hwnd, 5)
    user32.SetForegroundWindow(hwnd)
    return True


# ------------------------------------------------------------------ utilities


def load_config() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return {}


def load_state() -> dict:
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_state(data: dict) -> None:
    """Window geometry lives in its own file, written atomically, so a stray
    config write from another process cannot drag the pet back across the screen."""
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        temp = STATE_PATH + ".tmp"
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        os.replace(temp, STATE_PATH)
    except Exception:
        pass


def save_config(data: dict) -> None:
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
    except Exception:
        pass


def shirt_icon(color: str = TEXT) -> QIcon:
    """A thin-line T-shirt, the usual 'skin' affordance. Drawn per size so it
    stays crisp instead of being scaled up from a single small pixmap."""
    icon = QIcon()
    for size in (16, 20, 24, 28, 32, 40, 48, 64):
        ratio = 2
        pixmap = QPixmap(size * ratio, size * ratio)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.scale(size * ratio / 24.0, size * ratio / 24.0)
        pen = QPen(QColor(color))
        pen.setWidthF(1.7)
        pen.setJoinStyle(Qt.RoundJoin)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        path = QPainterPath()
        path.moveTo(8.8, 3.2)
        path.lineTo(3.6, 5.4)
        path.lineTo(2.0, 10.6)
        path.lineTo(5.8, 12.2)
        path.lineTo(7.4, 10.2)
        path.lineTo(7.4, 20.8)
        path.lineTo(16.6, 20.8)
        path.lineTo(16.6, 10.2)
        path.lineTo(18.2, 12.2)
        path.lineTo(22.0, 10.6)
        path.lineTo(20.4, 5.4)
        path.lineTo(15.2, 3.2)
        path.cubicTo(14.2, 5.6, 9.8, 5.6, 8.8, 3.2)
        painter.drawPath(path)
        painter.end()
        pixmap.setDevicePixelRatio(ratio)
        icon.addPixmap(pixmap)
    return icon


def fairy_glyph(size: int = 22) -> QPixmap:
    """The mascot's own face, small: notched ring, pale inner disc, blue iris."""
    ratio = 3
    pixmap = QPixmap(size * ratio, size * ratio)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.scale(size * ratio / 24.0, size * ratio / 24.0)
    painter.translate(12, 12)

    pen = QPen(QColor("#3f7fc4"))
    pen.setWidthF(2.1)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    for index in range(4):
        painter.drawArc(
            QRectF(-9.0, -9.0, 18.0, 18.0), int((14 + index * 90) * 16), int(66 * 16)
        )

    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#cfe0f2"))
    painter.drawEllipse(QPointF(0, 0), 6.0, 6.0)
    painter.setBrush(QColor("#2f6fb8"))
    painter.drawEllipse(QPointF(0, 0), 4.4, 4.4)
    painter.setBrush(QColor("#08131f"))
    painter.drawEllipse(QPointF(0, 0), 2.4, 2.4)
    painter.setBrush(QColor("#ffffff"))
    painter.drawEllipse(QPointF(1.1, -1.3), 1.0, 1.0)
    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


NPC_ART = os.path.join(os.path.dirname(HERE), "NPC_Fairy.webp")
_NPC_ICONS: dict[int, QPixmap] = {}


def npc_badge(size: int = 24) -> QPixmap:
    """The mascot portrait from NPC_Fairy.webp, cropped to its disc and scaled.

    The source is a square render with a blue backdrop, so the crop is masked
    with a circle: what is left is the glowing disc, which sits on the dark
    header without a rectangle around it.
    """
    if size in _NPC_ICONS:
        return _NPC_ICONS[size]
    for path in (NPC_ART, os.path.join(ASSETS, "npc_fairy.webp")):
        if not os.path.exists(path):
            continue
        art = QPixmap(path)
        if art.isNull():
            continue
        # The disc occupies the middle ~82% of the source; crop to that first so
        # the icon is the character rather than mostly backdrop.
        span = int(round(min(art.width(), art.height()) * 0.86))
        left = (art.width() - span) // 2
        top = (art.height() - span) // 2
        square = art.copy(QRect(left, top, span, span))
        scale = 4
        big = square.scaled(
            size * scale, size * scale, Qt.IgnoreAspectRatio, Qt.SmoothTransformation
        )
        out = QPixmap(big.size())
        out.fill(Qt.transparent)
        painter = QPainter(out)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        disc = QPainterPath()
        disc.addEllipse(QRectF(out.rect()).adjusted(0.5, 0.5, -0.5, -0.5))
        painter.setClipPath(disc)
        painter.drawPixmap(0, 0, big)
        painter.end()
        out.setDevicePixelRatio(scale)
        _NPC_ICONS[size] = out
        return out
    return fairy_glyph(size)


def menu_style() -> str:
    return (
        f"QMenu {{ background:#101a26; color:{TEXT}; border:1px solid {LINE};"
        " border-radius:8px; padding:5px; font-size:12px; }"
        " QMenu::item { padding:6px 22px 6px 14px; border-radius:5px; }"
        " QMenu::item:selected { background: rgba(77,143,214,0.28); }"
        " QMenu::separator { height:1px; background: rgba(126,170,222,0.16); margin:4px 6px; }"
        " QMenu::indicator { width:10px; }"
    )


# -------------------------------------------------------------------- widgets


class Bubble(QWidget):
    def __init__(self) -> None:
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.label = QLabel(self)
        self.label.setWordWrap(True)
        self.label.setStyleSheet(
            f"background: rgba(16,28,44,0.95); color:{TEXT}; border:1px solid {LINE};"
            "border-radius:10px; padding:8px 11px; font-size:12px;"
        )
        self.label.setMaximumWidth(240)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.label)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)

    def pop(self, text: str, anchor: QRect) -> None:
        self.label.setText(text)
        self.adjustSize()
        x = anchor.center().x() - self.width() // 2
        y = anchor.top() - self.height() - 7
        screen = QApplication.screenAt(anchor.center()) or QApplication.primaryScreen()
        if screen:
            area = screen.availableGeometry()
            x = max(area.left() + 4, min(x, area.right() - self.width() - 4))
            y = max(area.top() + 4, y)
        self.move(x, y)
        self.show()
        self.raise_()
        self.timer.start(3400)


class CornerGrip(QWidget):
    """Resize handle for the top-left corner (Qt's own grip only does bottom-right)."""

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self.window = window
        self.setFixedSize(14, 14)
        self.setCursor(Qt.SizeFDiagCursor)
        self._start = None
        self._geo = None

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setPen(QColor(255, 255, 255, 46))
        painter.drawLine(2, 11, 11, 2)
        painter.drawLine(6, 11, 11, 6)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._start = event.globalPosition().toPoint()
            self._geo = self.window.geometry()

    def mouseMoveEvent(self, event) -> None:
        if self._start is None:
            return
        delta = event.globalPosition().toPoint() - self._start
        width = max(self.window.minimumWidth(), self._geo.width() - delta.x())
        height = max(self.window.minimumHeight(), self._geo.height() - delta.y())
        self.window.setGeometry(
            self._geo.right() - width + 1,
            self._geo.bottom() - height + 1,
            width,
            height,
        )

    def mouseReleaseEvent(self, _event) -> None:
        self._start = None


_ACCOUNT_PROFILE: QWebEngineProfile | None = None


def account_profile() -> QWebEngineProfile:
    """The browser profile that keeps the DeepSeek login on disk.

    Qt's *default* profile is off-the-record — cookies and local storage live in
    memory and die with the process — which is why the account window asked for a
    fresh login every single start. This named profile keeps both under
    ``FairyPet/web`` and forces even session cookies to disk. It is created once
    and reused: two profiles with the same storage would fight over the files.
    """
    global _ACCOUNT_PROFILE
    if _ACCOUNT_PROFILE is not None:
        return _ACCOUNT_PROFILE
    store = os.path.join(CONFIG_DIR, "web")
    os.makedirs(store, exist_ok=True)
    profile = QWebEngineProfile("fairy-account")
    profile.setPersistentStoragePath(store)
    profile.setCachePath(os.path.join(store, "cache"))
    profile.setPersistentCookiesPolicy(
        QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
    )
    profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)
    profile.setHttpCacheMaximumSize(64 * 1024 * 1024)
    _ACCOUNT_PROFILE = profile
    return profile


class AboutWindow(QDialog):
    """Who made this, where it lives, and what you may not do with it.

    Deliberately boring: one panel, no tabs, nothing to click except the links
    and close. It is also where the embedded build mark surfaces, so a stripped
    fork shows up as a missing identifier rather than a hidden one.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("关于")
        self.setModal(True)
        self.setFixedWidth(470)
        self.setStyleSheet(
            f"QDialog {{ background:{INK}; }}"
            f" QLabel {{ color:{TEXT}; font-size:12px; }}"
            f" QLabel#title {{ color:{TEXT}; font-size:19px; font-weight:600; }}"
            f" QLabel#version {{ color:{ACCENT}; font-size:12px; }}"
            f" QLabel#label {{ color:{DIM}; font-size:11px; }}"
            f" QLabel#body {{ color:#b8c8da; font-size:11px; }}"
            f" QLabel#fine {{ color:#6b7d92; font-size:10px; }}"
            f" QFrame#rule {{ background:{LINE}; max-height:1px; border:0; }}"
            f" QPushButton {{ background: rgba(77,143,214,0.16); border:1px solid {LINE};"
            f" border-radius:7px; color:#a9c8ea; font-size:12px; padding:6px 16px; }}"
            f" QPushButton:hover {{ background: rgba(77,143,214,0.3); color:#ddebfa; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(9)

        head = QHBoxLayout()
        head.setSpacing(12)
        icon = QLabel()
        icon.setFixedSize(44, 44)
        icon.setPixmap(QIcon(os.path.join(ASSETS, "icon.png")).pixmap(44, 44))
        head.addWidget(icon)
        titles = QVBoxLayout()
        titles.setSpacing(1)
        name = QLabel(APP_TITLE)
        name.setObjectName("title")
        titles.addWidget(name)
        version = QLabel(f"版本 {APP_VERSION}    ·    构建标识 {build_id()}")
        version.setObjectName("version")
        titles.addWidget(version)
        head.addLayout(titles)
        head.addStretch(1)
        layout.addLayout(head)
        layout.addWidget(self._rule())

        layout.addLayout(self._row("作者", AUTHOR))
        layout.addLayout(self._row("项目地址", PROJECT_URL or "待定"))
        layout.addLayout(
            self._row(
                "特别鸣谢",
                f'<a style="color:{ACCENT}; text-decoration:none;" href="{CREDIT_URL}">{escape(CREDIT_NAME)}</a>'
                f'<span style="color:{DIM};"> — {escape(CREDIT_NOTE)}</span>',
                rich=True,
            )
        )
        layout.addWidget(self._rule())

        for heading, body in (
            (
                "免责声明",
                "本程序为个人桌面宠物实验，与 DeepSeek、HanaAgent 官方无关，也未获其背书。"
                "它通过本机接口与客户端通信，不收集、不上传任何数据；账号令牌只保存在"
                "本目录的 FairyPet\\ 下。使用本程序产生的任何后果由使用者自行承担。",
            ),
            (
                "版权声明",
                f"© 2026 {AUTHOR}。保留所有权利。{LICENSE_LINE}；"
                "未经书面许可，不得用于商业产品、付费分发或作为服务出售。"
                "形象设定与动画素材版权归原作者所有，详见鸣谢链接。",
            ),
        ):
            caption = QLabel(heading)
            caption.setObjectName("label")
            layout.addWidget(caption)
            text = QLabel(body)
            text.setObjectName("body")
            text.setWordWrap(True)
            text.setTextInteractionFlags(Qt.TextSelectableByMouse)
            layout.addWidget(text)

        layout.addWidget(self._rule())
        fine = QLabel(f"构建水印：{build_mark() or '—'} · 移除该标识不改变许可条款")
        fine.setObjectName("fine")
        fine.setWordWrap(True)
        layout.addWidget(fine)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        if PROJECT_URL:
            open_action = QPushButton("打开仓库")
            open_action.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(PROJECT_URL)))
            buttons.addWidget(open_action)
        thanks = QPushButton("素材来源")
        thanks.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(CREDIT_URL)))
        buttons.addWidget(thanks)
        buttons.addStretch(1)
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.accept)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

    @staticmethod
    def _rule() -> QFrame:
        rule = QFrame()
        rule.setObjectName("rule")
        rule.setFrameShape(QFrame.HLine)
        return rule

    @staticmethod
    def _row(caption: str, value: str, rich: bool = False) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        key = QLabel(caption)
        key.setObjectName("label")
        key.setFixedWidth(64)
        row.addWidget(key)
        text = QLabel(value)
        text.setWordWrap(True)
        if rich:
            text.setTextFormat(Qt.RichText)
            text.setOpenExternalLinks(True)
        text.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        row.addWidget(text, 1)
        return row


class AccountWindow(QDialog):
    """The DeepSeek console, inside the pet.

    The session is a normal browser session on a *persistent* profile, so a
    single login survives restarts. The console token is lifted from
    localStorage on every load and cached in ``deepseek.json`` for the balance
    and usage figures.
    """

    PORTAL = "https://platform.deepseek.com/"
    USAGE = "https://platform.deepseek.com/usage"
    TOPUP = "https://platform.deepseek.com/top_up"

    def __init__(self, account: "DeepSeekAccount") -> None:
        super().__init__(None)
        self.account = account
        self.setWindowTitle("DeepSeek 账户")
        self.resize(920, 660)
        self.setStyleSheet(
            f"QDialog {{ background:{INK}; }}"
            f" QLabel {{ color:{TEXT}; font-size:11px; }}"
            f" QLabel#note {{ color:{DIM}; font-size:11px; }}"
            f" QLineEdit {{ background: rgba(255,255,255,0.05); border:1px solid {LINE};"
            f" border-radius:7px; color:{TEXT}; padding:6px 9px; font-size:11px; }}"
            f" QPushButton {{ background: rgba(77,143,214,0.16); border:1px solid {LINE};"
            f" border-radius:7px; color:#a9c8ea; font-size:11px; padding:5px 14px; }}"
            f" QPushButton:hover {{ background: rgba(77,143,214,0.3); color:#ddebfa; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.view = QWebEngineView(self)
        self.view.setPage(QWebEnginePage(account_profile(), self.view))
        self.view.setUrl(QUrl(self.USAGE))
        self.view.loadFinished.connect(self._on_loaded)
        layout.addWidget(self.view, 1)

        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(8)
        self.note = QLabel("登录一次就够了，会话存在本机；充值、用量都能在这里开")
        self.note.setObjectName("note")
        row.addWidget(self.note, 1)
        for label, url in (
            ("用量", self.USAGE),
            ("充值", self.TOPUP),
            ("API 主页", self.PORTAL),
        ):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, target=url: self.view.setUrl(QUrl(target)))
            row.addWidget(button)
        layout.addWidget(bar)

    # ------------------------------------------------------------------ inner

    def _on_loaded(self, ok: bool) -> None:
        if ok:
            self._lift()

    def _lift(self) -> None:
        script = (
            "(function(){try{var raw=localStorage.getItem('userToken');"
            "if(!raw)return '';var parsed=JSON.parse(raw);"
            "return parsed&&parsed.value?parsed.value:'';}catch(e){return '';}})()"
        )
        self.view.page().runJavaScript(script, self._got_token)

    def _got_token(self, value) -> None:
        text = str(value or "").strip()
        if not text:
            self.note.setText("还没登录——在上面登录一次，之后会自动记住")
            return
        if text != self.account.data.get("token"):
            self.account.set(token=text)
            self.note.setText("已读取登录状态，余额与电费可以刷新了")
        else:
            self.note.setText("登录状态有效")


THINK_FIELDS = [
    ("bg", "背景颜色"),
    ("bubble", "用户气泡"),
    ("userText", "用户文字"),
    ("text", "我的文字"),
    ("accent", "回答竖线"),
    ("tag", "名字标签"),
]


class SettingsDialog(QDialog):
    """Colours and font sizes for the transcript."""

    def __init__(self, theme: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("界面设置")
        self.setFixedWidth(380)
        self.setStyleSheet(
            f"QDialog {{ background:{INK}; }}"
            f" QLabel {{ color:{TEXT}; font-size:12px; }}"
            f" QPushButton {{ background: rgba(255,255,255,0.05); border:1px solid {LINE};"
            f" border-radius:6px; color:{TEXT}; font-size:12px; padding:4px 10px; }}"
            f" QPushButton:hover {{ border:1px solid rgba(126,170,222,0.4); }}"
        )
        self._drag = None
        self._press_global = None
        self._moved_window = False
        self.theme = dict(DEFAULT_THEME)
        self.theme.update(theme or {})
        self._swatches = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(8)

        note = QLabel("点色块改颜色，拖滑块调字号")
        note.setStyleSheet(f"color:{DIM}; font-size:11px;")
        note.setCursor(Qt.ArrowCursor)
        layout.addWidget(note)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(7)
        grid.setColumnMinimumWidth(0, 76)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)

        for index, (key, label) in enumerate(THINK_FIELDS):
            name = QLabel(label)
            name.setFixedWidth(76)
            name.setCursor(Qt.ArrowCursor)
            swatch = QPushButton()
            swatch.setFixedSize(46, 22)
            swatch.setCursor(Qt.PointingHandCursor)
            swatch.clicked.connect(lambda _checked=False, k=key: self._pick(k))
            self._swatches[key] = swatch
            grid.addWidget(name, index, 0)
            grid.addWidget(swatch, index, 1, Qt.AlignLeft)

        def size_row(label_text: str, low: int, high: int, value: int):
            holder = QWidget()
            row_holder = QHBoxLayout(holder)
            row_holder.setContentsMargins(0, 0, 0, 0)
            row_holder.setSpacing(8)
            slider = QSlider(Qt.Horizontal)
            slider.setRange(low, high)
            slider.setSingleStep(1)
            slider.setValue(value)
            slider.setFixedWidth(120)
            slider.setCursor(Qt.PointingHandCursor)
            slider.setStyleSheet(
                "QSlider::groove:horizontal { height:3px; background: rgba(126,170,222,0.25);"
                " border-radius:2px; }"
                f"QSlider::handle:horizontal {{ width:11px; height:11px; margin:-4px 0;"
                f" border-radius:5px; background:{ACCENT}; }}"
            )
            readout = QLabel(str(value))
            readout.setFixedWidth(22)
            readout.setCursor(Qt.ArrowCursor)
            readout.setStyleSheet(f"color:{TEXT}; font-size:12px;")
            slider.valueChanged.connect(lambda v: readout.setText(str(v)))
            row_holder.addWidget(slider)
            row_holder.addWidget(readout)
            return holder, slider

        row = len(THINK_FIELDS)
        body_label = QLabel("正文字号")
        body_label.setFixedWidth(76)
        body_label.setCursor(Qt.ArrowCursor)
        body_holder, self.body_size = size_row(
            "正文字号", 9, 20, int(self.theme.get("bodySize") or 12)
        )
        grid.addWidget(body_label, row, 0)
        grid.addWidget(body_holder, row, 1, Qt.AlignLeft)

        tag_label = QLabel("标签字号")
        tag_label.setFixedWidth(76)
        tag_label.setCursor(Qt.ArrowCursor)
        tag_holder, self.tag_size = size_row(
            "标签字号", 7, 16, int(self.theme.get("tagSize") or 9)
        )
        grid.addWidget(tag_label, row + 1, 0)
        grid.addWidget(tag_holder, row + 1, 1, Qt.AlignLeft)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        reset = QPushButton("恢复默认")
        reset.clicked.connect(self._reset)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        save = QPushButton("保存")
        save.clicked.connect(self.accept)
        buttons.addWidget(reset)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

        self._paint_swatches()

    def _paint_swatches(self) -> None:
        for key, swatch in self._swatches.items():
            color = str(self.theme.get(key) or "#000000")
            swatch.setStyleSheet(
                f"QPushButton {{ background:{color}; border:1px solid rgba(255,255,255,0.18);"
                " border-radius:6px; }"
            )
            swatch.setText("")

    def _pick(self, key: str) -> None:
        start = QColor(str(self.theme.get(key) or "#000000"))
        color = QColorDialog.getColor(start, self, "选择颜色")
        if not color.isValid():
            return
        self.theme[key] = color.name()
        self._paint_swatches()

    def _reset(self) -> None:
        self.theme = dict(DEFAULT_THEME)
        self.body_size.setValue(int(DEFAULT_THEME["bodySize"]))
        self.tag_size.setValue(int(DEFAULT_THEME["tagSize"]))
        self._paint_swatches()

    def values(self) -> dict:
        data = dict(self.theme)
        data["bodySize"] = int(self.body_size.value())
        data["tagSize"] = int(self.tag_size.value())
        return data


class CostBar(QWidget):
    """Bottom strip: balance on the left, spend for the picked window on the right."""

    rangeChanged = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(28)
        self._range = "today"
        self.setStyleSheet(
            f"CostBar {{ background: rgba(255,255,255,0.02); border-top:1px solid {LINE}; }}"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 8, 0)
        layout.setSpacing(6)

        self.balance = QLabel("余额 —")
        self.balance.setStyleSheet(f"color:{TEXT}; font-size:11px;")
        self.spent = QLabel("电费 —")
        self.spent.setStyleSheet(f"color:{ACCENT}; font-size:11px;")
        layout.addWidget(self.balance)
        layout.addWidget(self.spent)
        layout.addStretch(1)

        self.buttons = {}
        group = QButtonGroup(self)
        group.setExclusive(True)
        for key, label in (("today", "当日"), ("week", "7 天"), ("month", "本月")):
            button = QToolButton()
            button.setText(label)
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setStyleSheet(
                f"QToolButton {{ background:transparent; color:{DIM}; border:1px solid transparent;"
                f" border-radius:5px; padding:2px 7px; font-size:11px; }}"
                f" QToolButton:hover {{ color:{TEXT}; }}"
                f" QToolButton:checked {{ color:#cfe4fa; background: rgba(77,143,214,0.18); }}"
            )
            button.clicked.connect(lambda _checked=False, k=key: self._pick(k))
            group.addButton(button)
            layout.addWidget(button)
            self.buttons[key] = button
        self.buttons["today"].setChecked(True)

    def _pick(self, key: str) -> None:
        if key == self._range:
            return
        self._range = key
        self.spent.setText("电费 …")
        self.rangeChanged.emit(key)

    def current_range(self) -> str:
        return self._range

    def set_usage(self, balance, spent, error: str = "") -> None:
        if isinstance(balance, (int, float)):
            self.balance.setText(f"余额 ¥{balance:,.2f}")
            self.balance.setStyleSheet(f"color:{TEXT}; font-size:10px;")
        else:
            self.balance.setText("余额 —")
            self.balance.setStyleSheet(f"color:{DIM}; font-size:11px;")
        if isinstance(spent, (int, float)):
            self.spent.setText(f"电费 ¥{spent:.2f}")
            self.spent.setStyleSheet(f"color:{ACCENT}; font-size:10px;")
        else:
            self.spent.setText("电费 —")
            self.spent.setStyleSheet(f"color:{DIM}; font-size:11px;")
        self.setToolTip(error or "")


class ChatWindow(QWidget):
    closed = Signal()
    sendRequested = Signal(str, object)
    sessionRequested = Signal(str)
    newRequested = Signal()
    attachRequested = Signal()
    commandRequested = Signal()
    filesDropped = Signal(object)
    modelsRequested = Signal()
    thinkingRequested = Signal(str)
    workspacesRequested = Signal()
    presetsRequested = Signal()
    usageRangeRequested = Signal(str)
    settingsChanged = Signal(dict)
    movedByUser = Signal()
    resized = Signal()

    def __init__(self, theme: dict | None = None) -> None:
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.theme = dict(DEFAULT_THEME)
        self.theme.update(theme or {})
        self._messages = []
        self._working = False
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAcceptDrops(True)
        self.resize(400, 560)
        self.setMinimumSize(320, 380)
        self._drag = None
        self._signature = None
        self._last_scroll_at_bottom = True

        shell = QFrame(self)
        shell.setObjectName("shell")
        self.shell = shell
        shell.setStyleSheet(
            f"#shell {{ background:{self.theme['bg']}; border:1px solid {LINE}; border-radius:14px; }}"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(shell)

        root = QVBoxLayout(shell)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- header
        header = QWidget()
        header.setFixedHeight(48)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(12, 8, 8, 8)
        hl.setSpacing(6)
        title = QLabel()
        title.setPixmap(npc_badge(24))
        title.setFixedWidth(30)
        title.setToolTip("FAIRY")
        title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.picker = QComboBox()
        self.picker.setStyleSheet(
            f"QComboBox {{ background: rgba(255,255,255,0.04); border:1px solid {LINE};"
            f" border-radius:7px; color:{TEXT}; padding:4px 8px; font-size:12px; }}"
            f" QComboBox QAbstractItemView {{ background:#101a26; color:{TEXT}; border:1px solid {LINE};"
            " selection-background-color: rgba(77,143,214,0.35); outline:none; }"
            f" QComboBox::drop-down {{ border:0; width:16px; }}"
        )
        self.picker.currentIndexChanged.connect(self._on_pick)
        new_button = self._mini("＋", "新建对话")
        new_button.clicked.connect(self.newRequested.emit)
        gear = self._mini("⚙", "界面设置（颜色 / 字号）")
        gear.clicked.connect(self.open_settings)
        close_button = self._mini("✕", "关闭")
        close_button.clicked.connect(self.close)
        hl.addWidget(title)
        hl.addWidget(self.picker, 1)
        hl.addWidget(new_button)
        hl.addWidget(gear)
        hl.addWidget(close_button)
        root.addWidget(header)

        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background:{LINE};")
        root.addWidget(divider)

        # ---- transcript
        self.view = QTextBrowser()
        self.view.setFrameShape(QFrame.NoFrame)
        self.view.setOpenExternalLinks(True)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.view.setStyleSheet(
            "QTextBrowser { background: transparent; border: 0; padding: 10px 12px; }"
            "QScrollBar:vertical { background: transparent; width: 8px; margin: 4px 2px; }"
            "QScrollBar::handle:vertical { background: rgba(126,170,222,0.22);"
            " border-radius: 4px; min-height: 24px; }"
            "QScrollBar::handle:vertical:hover { background: rgba(126,170,222,0.4); }"
            "QScrollBar::add-line, QScrollBar::sub-line { height: 0; }"
            "QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }"
        )
        self.view.document().setDocumentMargin(0)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._view_menu)
        root.addWidget(self.view, 1)

        # ---- composer (dsh layout: workspace + preset above, actions below)
        composer = QFrame()
        composer.setObjectName("composer")
        composer.setStyleSheet(
            f"#composer {{ background: rgba(255,255,255,0.045); border:1px solid {LINE};"
            f" border-radius:13px; }}"
        )
        cl = QVBoxLayout(composer)
        cl.setContentsMargins(10, 8, 10, 8)
        cl.setSpacing(3)

        top = QHBoxLayout()
        top.setSpacing(2)
        self.ws_button = self._chip("工作区")
        self.ws_button.clicked.connect(self.popup_workspaces)
        self.preset_button = self._chip("标准模式")
        self.preset_button.clicked.connect(self.popup_presets)
        top.addWidget(self.ws_button)
        top.addWidget(self.preset_button)
        top.addStretch(1)
        cl.addLayout(top)

        self.attachments = QLabel("")
        self.attachments.setStyleSheet(f"color:{DIM}; font-size:11px; padding-left:5px;")
        self.attachments.hide()
        cl.addWidget(self.attachments)

        self.input = QLineEdit()
        self.input.setPlaceholderText("描述你想构建的内容，/ 调用指令，@ 文件或对话")
        self.input.setMinimumHeight(34)
        self.input.setStyleSheet(
            f"QLineEdit {{ background: transparent; border:0; color:{TEXT};"
            " padding: 4px 5px; font-size:13px; }"
        )
        self.input.setContextMenuPolicy(Qt.CustomContextMenu)
        self.input.customContextMenuRequested.connect(self._input_menu)
        self.input.returnPressed.connect(self._submit)
        cl.addWidget(self.input)

        bottom = QHBoxLayout()
        bottom.setSpacing(4)
        self.plus_button = self._round("＋", "附件、指令")
        self.plus_button.clicked.connect(self.commandRequested.emit)
        self.perm_button = self._chip("权限")
        self.perm_button.clicked.connect(self._show_permission_note)
        bottom.addWidget(self.plus_button)
        bottom.addWidget(self.perm_button)
        bottom.addStretch(1)
        self.model_button = self._chip("模型")
        self.model_button.clicked.connect(self.modelsRequested.emit)
        self.effort_button = self._chip("High")
        self.effort_button.clicked.connect(self.popup_effort)
        self.send_button = self._round("↑", "发送")
        self.send_button.setFixedSize(30, 30)
        self.send_button.setStyleSheet(
            f"QPushButton {{ background: rgba(77,143,214,0.85); border:0; border-radius:15px;"
            f" color:#eaf3ff; font-size:14px; font-weight:600; }}"
            f" QPushButton:hover {{ background: rgba(97,163,234,0.95); }}"
        )
        self.send_button.clicked.connect(self._submit)
        bottom.addWidget(self.model_button)
        bottom.addWidget(self.effort_button)
        bottom.addWidget(self.send_button)
        cl.addLayout(bottom)
        root.addWidget(composer)

        self.grip = CornerGrip(self)
        self.grip.move(4, 4)
        self.grip.raise_()

        self.hint = QLabel("")
        self.hint.setStyleSheet(f"color:{DIM}; font-size:11px; padding:0 14px 8px;")
        root.addWidget(self.hint)

        self.cost_bar = CostBar()
        self.cost_bar.rangeChanged.connect(self.usageRangeRequested.emit)
        root.addWidget(self.cost_bar)

        self._thinking_level = None
        self._model_label = "模型"
        self._preset = None
        self._permission_label = ""
        self._effort = None
        self._efforts: list[str] = []

    # ------------------------------------------------------------- cosmetics

    def _mini(self, text: str, tip: str) -> QPushButton:
        button = QPushButton(text)
        button.setFixedSize(26, 26)
        button.setToolTip(tip)
        button.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{DIM}; border:1px solid {LINE};"
            f" border-radius:6px; font-size:13px; }} QPushButton:hover {{ color:{TEXT}; }}"
        )
        return button

    def _tool(self, text: str, tip: str) -> QToolButton:
        button = QToolButton()
        button.setText(text)
        button.setToolTip(tip)
        button.setCursor(Qt.PointingHandCursor)
        button.setStyleSheet(
            f"QToolButton {{ background:transparent; color:{DIM}; border:1px solid transparent;"
            f" border-radius:6px; padding:4px 9px; font-size:12px; }}"
            f" QToolButton:hover {{ color:{TEXT}; background: rgba(255,255,255,0.05); }}"
            f" QToolButton:checked {{ color:{TEXT}; }}"
        )
        return button

    # ------------------------------------------------------------------ drag

    def mousePressEvent(self, event) -> None:
        # Interactive children (buttons, fields, the transcript) swallow their
        # own presses, so anything that reaches the window is empty space: drag
        # from there, not just from the 46px header strip.
        if event.button() == Qt.LeftButton:
            self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._press_global = event.globalPosition().toPoint()
            self._moved_window = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag is not None and event.buttons() & Qt.LeftButton:
            current = event.globalPosition().toPoint()
            if (current - self._press_global).manhattanLength() > 4:
                self._moved_window = True
            self.move(current - self._drag)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        drag = self._drag
        self._drag = None
        super().mouseReleaseEvent(event)
        if drag is not None and getattr(self, "_moved_window", False):
            self._moved_window = False
            self.movedByUser.emit()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "grip"):
            self.grip.move(4, 4)
            self.grip.raise_()
        self.resized.emit()

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.filesDropped.emit(paths)
            event.acceptProposedAction()

    # --------------------------------------------------------------- actions

    def _submit(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self.sendRequested.emit(text, None)

    def _on_pick(self, index: int) -> None:
        if index >= 0:
            session_id = self.picker.itemData(index)
            if session_id:
                self.sessionRequested.emit(session_id)

    def show_attachment(self, names: list[str]) -> None:
        if names:
            self.attachments.setText("附件：" + "、".join(names))
            self.attachments.show()
        else:
            self.attachments.hide()

    def popup_commands(self, commands: list[dict]) -> None:
        """The plus menu: attachments on top, dsh slash commands below."""
        menu = QMenu(self)
        menu.setStyleSheet(menu_style())
        attach = menu.addAction("附件…")
        attach.triggered.connect(self.attachRequested.emit)
        menu.addSeparator()
        if commands:
            for item in commands[:16]:
                name = item.get("name") or ""
                label = "/" + name
                desc = item.get("description") or ""
                if desc:
                    label = f"{label}   {desc[:28]}"
                action = menu.addAction(label)
                action.triggered.connect(lambda _checked=False, value=name: self._run_command("/" + value + " "))
            menu.addSeparator()
        new_action = menu.addAction("新建对话")
        new_action.triggered.connect(lambda: self.newRequested.emit())
        clear_action = menu.addAction("清空输入")
        clear_action.triggered.connect(self.input.clear)
        menu.exec(QCursor.pos())

    def _run_command(self, value: str) -> None:
        if value == "__new__":
            self.newRequested.emit()
        elif value == "__clear__":
            self.input.clear()
        else:
            self.input.setText(value)
            self.input.setFocus()

    # ---- dsh-style chips

    def _chip(self, text: str) -> QPushButton:
        button = QPushButton(text)
        button.setCursor(Qt.PointingHandCursor)
        button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        button.setStyleSheet(
            f"QPushButton {{ background: transparent; color:{DIM}; border:0;"
            " border-radius:7px; padding: 4px 7px; font-size:12px; text-align:left; }"
            f" QPushButton:hover {{ color:{TEXT}; background: rgba(255,255,255,0.06); }}"
        )
        return button

    def _round(self, text: str, tip: str) -> QPushButton:
        button = QPushButton(text)
        button.setFixedSize(26, 26)
        button.setToolTip(tip)
        button.setCursor(Qt.PointingHandCursor)
        button.setStyleSheet(
            f"QPushButton {{ background: rgba(255,255,255,0.06); border:1px solid {LINE};"
            f" border-radius:13px; color:{DIM}; font-size:13px; }}"
            f" QPushButton:hover {{ color:{TEXT}; background: rgba(255,255,255,0.1); }}"
        )
        return button

    def popup_workspaces(self) -> None:
        self.workspacesRequested.emit()

    def popup_presets(self) -> None:
        self.presetsRequested.emit()

    def _show_permission_note(self) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(menu_style())
        current = menu.addAction(f"当前：{self._permission_label or '未知'}")
        current.setEnabled(False)
        note = menu.addAction("权限在 dsh 客户端里改")
        note.setEnabled(False)
        menu.exec(QCursor.pos())

    def show_workspaces(self, spaces: list[dict], current: str | None) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(menu_style())
        if not spaces:
            menu.addAction("还没有工作区").setEnabled(False)
        for space in spaces:
            label = str(space.get("title") or space.get("path") or "工作区")
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(space.get("id") == current)
            action.setToolTip(str(space.get("path") or ""))
            action.triggered.connect(lambda _checked=False, value=space.get("id"): self.sendRequested.emit("__workspace__", value))
        menu.addSeparator()
        add_action = menu.addAction("添加工作区…")
        add_action.triggered.connect(lambda: self.sendRequested.emit("__addworkspace__", None))
        menu.exec(QCursor.pos())

    def show_presets(self, presets: list[dict], current: str | None) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(menu_style())
        names = {"standard": "标准模式", "ptc": "PTC 模式", "minimal": "精简模式", "cordis": "Cordis 模式"}
        if not presets:
            menu.addAction("没有可选模式").setEnabled(False)
        for preset in presets:
            key = preset.get("id") or ""
            action = menu.addAction(names.get(key, key))
            action.setCheckable(True)
            action.setChecked(key == current)
            action.triggered.connect(lambda _checked=False, value=key: self.sendRequested.emit("__preset__", value))
        menu.exec(QCursor.pos())

    def popup_effort(self) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(menu_style())
        for level in self._efforts or THINK_LEVELS[:4]:
            action = menu.addAction(level.capitalize())
            action.setCheckable(True)
            action.setChecked(level == self._effort)
            action.triggered.connect(lambda _checked=False, value=level: self.sendRequested.emit("__effort__", value))
        if not self._efforts:
            menu.addSeparator()
            note = menu.addAction("先选个模型")
            note.setEnabled(False)
        menu.exec(QCursor.pos())

    def set_workspace_label(self, name: str | None) -> None:
        self.ws_button.setText(f"◈ {name}" if name else "◈ 工作区")

    def set_preset_label(self, preset: str | None) -> None:
        names = {"standard": "标准模式", "ptc": "PTC 模式", "minimal": "精简模式", "cordis": "Cordis 模式"}
        self._preset = preset
        self.preset_button.setText(f"◎ {names.get(preset or '', preset or '模式')}")

    def set_permission_label(self, value: str | None) -> None:
        names = {
            "workspace-write": "工作区内修改",
            "read-only": "只读",
            "auto": "自动",
            "full": "完全访问",
        }
        self._permission_label = names.get(value or "", value or "")
        self.perm_button.setText(f"{self._permission_label or '权限'}⌄")
        self.perm_button.setEnabled(bool(value))

    def set_effort_label(self, level: str | None, efforts: list[str] | None = None) -> None:
        self._effort = level
        if efforts:
            self._efforts = list(efforts)
        self.effort_button.setText(level.capitalize() if level else "High")

    def set_thinking_menu(self, level: str | None) -> None:
        self.set_effort_label(level)

    def popup_thinking(self) -> None:
        self.popup_effort()

    def set_model_label(self, name: str | None) -> None:
        self._model_label = name or ""
        self.model_button.setText(name or "模型")
        self.model_button.setToolTip(f"当前模型：{name}" if name else "选择模型")

    def popup_models(self, models: list[dict], current: dict | None) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(menu_style())
        if not models:
            menu.addAction("没有可用模型").setEnabled(False)
        for model in models:
            label = f"{model.get('name') or model.get('id')}"
            action = menu.addAction(label)
            action.setCheckable(True)
            same = (
                current
                and current.get("modelId") == model.get("id")
                and current.get("provider") == model.get("provider")
            )
            action.setChecked(bool(same))
            action.triggered.connect(
                lambda _checked=False, m=model: self._pick_model(m)
            )
        menu.exec(QCursor.pos())

    def _pick_model(self, model: dict) -> None:
        self.sendRequested.emit("__model__", model)

    # --------------------------------------------------------------- render

    def set_sessions(self, sessions: list[dict], current: str | None) -> None:
        self.picker.blockSignals(True)
        self.picker.clear()
        for session in sessions:
            label = str(session.get("title") or "未命名对话")
            if len(label) > 24:
                label = label[:23] + "…"
            self.picker.addItem(label, session.get("id"))
        if current:
            position = self.picker.findData(current)
            if position >= 0:
                self.picker.setCurrentIndex(position)
        if self.picker.count() == 0:
            self.picker.addItem("未选择对话", None)
        self.picker.blockSignals(False)

    def _view_menu(self, position) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(menu_style())
        copy = menu.addAction("复制")
        copy.setEnabled(bool(self.view.textCursor().hasSelection()))
        copy.triggered.connect(self.view.copy)
        select_all = menu.addAction("全选")
        select_all.triggered.connect(self.view.selectAll)
        menu.exec(self.view.mapToGlobal(position))

    def _input_menu(self, position) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(menu_style())
        has_text = bool(self.input.text())
        cut = menu.addAction("剪切")
        cut.setEnabled(bool(self.input.selectedText()))
        cut.triggered.connect(self.input.cut)
        copy = menu.addAction("复制")
        copy.setEnabled(bool(self.input.selectedText()))
        copy.triggered.connect(self.input.copy)
        paste = menu.addAction("粘贴")
        paste.setEnabled(bool(self.input.canPaste()))
        paste.triggered.connect(self.input.paste)
        menu.addSeparator()
        clear = menu.addAction("清空")
        clear.setEnabled(has_text)
        clear.triggered.connect(self.input.clear)
        menu.exec(self.input.mapToGlobal(position))

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.theme, self)
        if dialog.exec() != QDialog.Accepted:
            return
        self.theme = dialog.values()
        self._apply_theme()
        self.settingsChanged.emit(dict(self.theme))

    def _apply_theme(self) -> None:
        self.shell.setStyleSheet(
            f"#shell {{ background:{self.theme['bg']}; border:1px solid {LINE}; border-radius:14px; }}"
        )
        self._signature = None
        self._render()

    def set_messages(self, messages: list[dict], working: bool) -> None:
        self._messages = [dict(m) for m in (messages or [])]
        self._working = bool(working)
        signature = json.dumps(self._messages, ensure_ascii=False) + ("|w" if working else "")
        if signature == self._signature:
            return
        self._signature = signature
        self._render()

    def _render(self) -> None:
        messages = self._messages
        working = self._working
        bar = self.view.verticalScrollBar()
        stick = bar.value() >= bar.maximum() - 40
        keep = bar.value()

        if not messages and not working:
            messages = [{"role": "assistant", "text": "这只眼睛只有一个任务：听你说话。"}]

        rows = []
        for message in messages:
            rows.append(self._block(str(message.get("role")), str(message.get("text", ""))))
        if working:
            rows.append(self._block("assistant", "思考中…", dim=True))

        self.view.setHtml(
            "<html><body style=\"margin:0;\">" + "".join(rows) + "</body></html>"
        )
        if stick:
            QTimer.singleShot(0, self.scroll_to_bottom)
        elif keep:
            QTimer.singleShot(0, lambda: self.view.verticalScrollBar().setValue(keep))

    def scroll_to_bottom(self) -> None:
        bar = self.view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _block(self, role: str, text: str, dim: bool = False) -> str:
        theme = self.theme
        body = escape(text).replace("\n", "<br/>")
        who = "你" if role == "user" else "FAIRY"
        tag_size = int(theme.get("tagSize") or 9)
        body_size = int(theme.get("bodySize") or 12)
        tag_color = theme.get("tag") or "#6f93bd"
        if role == "user":
            return (
                "<table width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" style=\"margin:8px 0;\">"
                "<tr><td align=\"right\">"
                f"<span style=\"color:{tag_color}; font-size:{tag_size}px; letter-spacing:1px;\">{who}</span>"
                "</td></tr>"
                "<tr><td align=\"right\">"
                f"<table cellspacing=\"0\" cellpadding=\"7\" bgcolor=\"{theme.get('bubble')}\">"
                f"<tr><td style=\"color:{theme.get('userText')}; font-size:{body_size}px;\">{body}</td></tr>"
                "</table></td></tr></table>"
            )
        color = DIM if dim else (theme.get("text") or "#dfe8f2")
        return (
            "<table width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" style=\"margin:8px 0;\">"
            "<tr>"
            f"<td width=\"2\" bgcolor=\"{theme.get('accent')}\"></td>"
            "<td style=\"padding-left:9px;\">"
            f"<span style=\"color:{tag_color}; font-size:{tag_size}px; letter-spacing:1px;\">FAIRY</span>"
            f"<div style=\"color:{color}; font-size:{body_size}px;\">{body}</div>"
            "</td></tr></table>"
        )

    def closeEvent(self, event) -> None:
        self.closed.emit()
        super().closeEvent(event)


class Sprite(QWidget):
    def __init__(self) -> None:
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)

        self.config = load_config()
        self.size_px = int(self.config.get("size") or DEFAULT_SIZE)
        self.frame_px = int(round(self.size_px * FRAME_SCALE))
        self.gaze_enabled = bool(self.config.get("gaze", True))
        self.pin_mode = str(self.config.get("pin") or "yield")
        if self.pin_mode not in {key for key, _label in PIN_MODES}:
            self.pin_mode = "yield"
        self.anim_speed = 1.0       # last value sent to the page, for change detection
        self.speed_mode = str(self.config.get("speedMode") or "cpu")
        self.manual_speed = float(self.config.get("manualSpeed") or 1.0)
        self.cpu_load = 0.0
        self.gpu_load = 0.0
        self.mem_load = 0.0
        self.lid_mode = str(self.config.get("lidMode") or "cpu")
        self.setFixedSize(self.frame_px, self.frame_px)
        self.setCursor(Qt.PointingHandCursor)
        self._clamp_to_screens()

        self.web = QWebEngineView(self)
        self.web.setGeometry(0, 0, self.frame_px, self.frame_px)
        self.web.setAttribute(Qt.WA_TranslucentBackground, True)
        self.web.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.web.page().setBackgroundColor(QColor(0, 0, 0, 0))
        self.web.load(QUrl.fromLocalFile(os.path.join(WEB, "fairy.html")))
        self.web.loadFinished.connect(self._on_web_loaded)

        # live animation state
        self.t = 0.0
        self.gaze_target = (0.0, 0.0)
        self.last_gaze = (99.0, 99.0)
        self.flash = 0.0
        self.squint = 0.0

        self.mode = "idle"          # idle | work | waiting
        self.transient = None       # done | poked
        self.transient_left = 0.0

        self._press_pos = None
        self._drag_offset = None
        self._moved = False
        self._working = False
        self._user_hidden = False
        self._auto_hidden = False

        self.state = load_state()
        screen = QApplication.primaryScreen().availableGeometry()
        pos = self.state.get("pos") or self.config.get("pos") or {}
        self.move(
            int(pos.get("x", screen.right() - self.frame_px - 30)),
            int(pos.get("y", screen.bottom() - self.frame_px - 60)),
        )

        self.bubble = Bubble()
        self.chat_window: ChatWindow | None = None
        self.pending_images: list[dict] = []
        self.current_models: list[dict] = []
        self._workspace_title = ""
        self._preset: str | None = None

        self.bridge = Bridge()
        self.signals = JobSignals()
        self.signals.ok.connect(self._on_job_ok)
        self.signals.err.connect(self._on_job_err)
        self.pool = QThreadPool.globalInstance()
        self.pool.setMaxThreadCount(2)
        self.inflight: set[str] = set()

        self.anim = QTimer(self)
        self.anim.timeout.connect(self._advance)
        self.anim.setSingleShot(False)

        self.gaze_timer = QTimer(self)
        self.gaze_timer.timeout.connect(self._track_cursor)
        self.gaze_timer.start(50)

        self.poll = QTimer(self)
        self.poll.timeout.connect(self._poll_state)
        self.poll.start(1600)


        self.account = DeepSeekAccount()
        self.usage_range = "today"
        self.usage_cache = {}

        self.metrics = MetricsReader()
        self.load_ratio = 0.0
        self.metrics_timer = QTimer(self)
        self.metrics_timer.timeout.connect(self._poll_metrics)
        self.metrics_timer.start(1500)

        self.usage_timer = QTimer(self)
        self.usage_timer.timeout.connect(lambda: self.refresh_usage())
        self.usage_timer.start(120000)

        self.setAcceptDrops(True)

        if "--chat" in sys.argv:
            QTimer.singleShot(1500, self.open_chat)

        self.foreground_check = QTimer(self)
        self.foreground_check.timeout.connect(self.watch_foreground)
        self.foreground_check.start(900)
        QTimer.singleShot(0, lambda: self.apply_pin(self.pin_mode))

    # ---------------------------------------------------------- job plumbing

    def run_job(self, kind: str, fn, replace: bool = True) -> None:
        if replace and kind in self.inflight:
            return
        self.inflight.add(kind)
        self.pool.start(Job(self.signals, kind, fn))

    def _on_job_ok(self, kind: str, payload) -> None:
        self.inflight.discard(kind)
        if kind == "state":
            self.state_failures = 0
        if kind == "usage":
            if isinstance(payload, dict) and self.chat_window:
                key = payload.get("range") or self.usage_range
                record = (time.monotonic(), payload.get("balance"), payload.get("spent"), payload.get("error") or "")
                self.usage_cache[key] = record
                if key == self.chat_window.cost_bar.current_range():
                    self.chat_window.cost_bar.set_usage(record[1], record[2], record[3])
            return
        if kind == "metrics":
            if not isinstance(payload, dict):
                return
            cpu = float(payload.get("cpu") or 0.0)
            gpu = float(payload.get("gpu") or 0.0)
            mem = float(payload.get("memory") or 0.0)
            # Light smoothing: GPU samples jump around a lot on a laptop, and a
            # raw reading makes the beat visibly stutter between polls.
            self.cpu_load += (cpu - self.cpu_load) * 0.5
            self.gpu_load += (gpu - self.gpu_load) * 0.35
            self.mem_load += (mem - self.mem_load) * 0.5
            # Under 60% the eye stays open; above it, the lid closes down
            # gradually and reaches a half-lid at full load.
            if self.lid_mode == "off":
                ratio = 0.0
            else:
                load = {"gpu": self.gpu_load, "memory": self.mem_load}.get(self.lid_mode, self.cpu_load)
                ratio = max(0.0, min(1.0, (load - 60.0) / 40.0))
            if abs(ratio - self.load_ratio) > 0.02:
                self.load_ratio = ratio
                self.js(f"pet.setLoad({ratio:.3f})")
            speed = self._speed()
            if abs(speed - self.anim_speed) > 0.02:
                self.anim_speed = speed
                self.apply_speed()
            return
        if kind == "state":
            self._apply_state(payload or {})
        elif kind == "sessions":
            if self.chat_window:
                self.chat_window.set_sessions(payload.get("sessions") or [], payload.get("current"))
        elif kind == "history":
            if self.chat_window:
                self.chat_window.set_messages(payload.get("messages") or [], self._working)
        elif kind == "send":
            self._working = True
            if self.chat_window:
                self.chat_window.hint.setText("")
                self.run_job("history", lambda: self.bridge.history())
        elif kind == "models":
            models = payload.get("models") or []
            current = payload.get("current") or {}
            if self.chat_window:
                self.current_models = models
                self.chat_window.set_model_label(self._model_name(current))
                effort = current.get("effort")
                efforts = None
                for model in models:
                    if model.get("id") == current.get("modelId") and model.get("provider") == current.get("provider"):
                        efforts = model.get("efforts")
                        effort = effort or model.get("defaultEffort")
                        break
                self.chat_window.set_effort_label(effort, efforts)
                self.chat_window.popup_models(models, current)
        elif kind == "addworkspace":
            if self.chat_window:
                title = payload.get("title") or payload.get("path") or ""
                self._workspace_title = str(title)
                self.chat_window.set_workspace_label(self._workspace_title)
                note = "工作区已添加" if payload.get("created") else "这个工作区已经有了"
                self.chat_window.hint.setText(f"{note}，下一个对话在它里面建")
                QTimer.singleShot(2400, lambda: self.chat_window.hint.setText(""))
        elif kind == "wscurrent":
            spaces = payload.get("workspaces") or []
            current = payload.get("current")
            for space in spaces:
                if space.get("id") == current:
                    self._workspace_title = str(space.get("title") or space.get("path") or "")
                    self._workspace_path = str(space.get("path") or "") or None
                    break
            if self.chat_window:
                self.chat_window.set_workspace_label(self._workspace_title)
        elif kind == "modelslabel":
            models = payload.get("models") or []
            current = payload.get("current") or {}
            if self.chat_window:
                self.current_models = models
                name = None
                efforts = None
                effort = current.get("effort")
                for model in models:
                    if model.get("id") == current.get("modelId") and model.get("provider") == current.get("provider"):
                        name = model.get("name")
                        efforts = model.get("efforts")
                        effort = effort or model.get("defaultEffort")
                        break
                self.chat_window.set_model_label(name or self._model_name(current))
                self.chat_window.set_effort_label(effort, efforts)
        elif kind == "workspaces":
            if self.chat_window:
                self.chat_window.show_workspaces(payload.get("workspaces") or [], payload.get("current"))
        elif kind == "presets":
            if self.chat_window:
                self.chat_window.show_presets(payload.get("presets") or [], self._preset)
        elif kind == "setworkspace":
            if self.chat_window:
                self.chat_window.set_workspace_label(self._workspace_title)
                self.chat_window.hint.setText("工作区已切换，下一个对话生效")
                QTimer.singleShot(2000, lambda: self.chat_window.hint.setText(""))
        elif kind == "setpreset":
            if self.chat_window:
                self.chat_window.set_preset_label(payload.get("agentPreset"))
                self.chat_window.hint.setText("模式已切换")
                QTimer.singleShot(1600, lambda: self.chat_window.hint.setText(""))
        elif kind == "setmodel":
            if self.chat_window:
                self.chat_window.hint.setText("模型已切换")
                QTimer.singleShot(1800, lambda: self.chat_window.hint.setText(""))
        elif kind == "thinking":
            pass
        elif kind == "compact":
            if self.chat_window:
                self.chat_window.hint.setText("上下文已压缩")
                QTimer.singleShot(2000, lambda: self.chat_window.hint.setText(""))
        elif kind == "commands":
            if self.chat_window:
                self.chat_window.popup_commands((payload or {}).get("commands") or [])
        elif kind == "select" or kind == "new":
            if self.chat_window:
                self.chat_window.set_messages([], False)
            self.run_job("sessions", self.bridge.sessions)
            self.run_job("history", lambda: self.bridge.history())

    def _on_job_err(self, kind: str, message: str) -> None:
        self.inflight.discard(kind)
        if kind == "state":
            # Hana owns this process; when its server stops answering, quit.
            self.state_failures = getattr(self, "state_failures", 0) + 1
            if self.state_failures >= 12:
                QApplication.quit()
                return
            self._working = False
            if self.transient is None:
                self.mode = "idle"
            return
        if kind == "usage":
            if self.chat_window:
                self.chat_window.cost_bar.set_usage(None, None, message)
            return
        if self.chat_window and kind in ("send", "select", "new", "setmodel", "thinking", "history"):
            self.chat_window.hint.setText(f"{message}")
        elif kind in ("setmodel", "thinking"):
            self.say("这个开关没被授权，去 Hana 设置里给桌宠开一下。")

    # ----------------------------------------------------------------- paint

    def _on_web_loaded(self, ok: bool) -> None:
        self.js(f"pet.setSpeed({self._speed():.3f})")
        self._sync_state()

    def js(self, code: str) -> None:
        try:
            # The page is still loading for a moment after the widget appears;
            # guard here instead of throwing on every early call.
            self.web.page().runJavaScript(f"if (window.pet) {{ {code} }}")
        except Exception:
            pass

    def _sync_state(self) -> None:
        self.js(f"pet.setExpression('{ {'work': 'working', 'waiting': 'waiting'}.get(self.mode, 'idle') }')")

    def _speed(self) -> float:
        """One multiplier for the eye beat and the lash rotation.

        Manual mode pins it; otherwise the chosen load channel maps 45% -> 1x and
        90% -> 3x, so a quiet machine looks calm and a busy one looks alert.
        """
        if self.speed_mode == "manual":
            return max(SPEED_MIN, min(SPEED_MAX, self.manual_speed))
        load = self.gpu_load if self.speed_mode == "gpu" else self.cpu_load
        return 1.0 + 2.0 * max(0.0, min(1.0, (load - SPEED_IDLE) / SPEED_SPAN))

    def set_speed_mode(self, key: str) -> None:
        if key not in dict(SPEED_MODES):
            return
        if key == "manual" and self.speed_mode != "manual":
            # Take over from wherever the automatic curve had left it.
            self.manual_speed = max(SPEED_MIN, min(SPEED_MAX, self.anim_speed))
        self.speed_mode = key
        self.config["speedMode"] = key
        save_config(self.config)
        self.anim_speed = self._speed()
        self.apply_speed()

    def set_lid_mode(self, key: str) -> None:
        if key not in dict(LID_MODES):
            return
        self.lid_mode = key
        self.config["lidMode"] = key
        save_config(self.config)
        # Apply at once instead of waiting up to a second and a half for a poll.
        load = 0.0 if key == "off" else {
            "gpu": self.gpu_load,
            "memory": self.mem_load,
        }.get(key, self.cpu_load)
        ratio = 0.0 if key == "off" else max(0.0, min(1.0, (load - 60.0) / 40.0))
        self.load_ratio = ratio
        self.js(f"pet.setLoad({ratio:.3f})")

    def set_manual_speed(self, value: float, save: bool = True) -> None:
        self.manual_speed = max(SPEED_MIN, min(SPEED_MAX, float(value)))
        self.speed_mode = "manual"
        self.anim_speed = self.manual_speed
        self.apply_speed()
        if save:
            self.config["speedMode"] = "manual"
            self.config["manualSpeed"] = round(self.manual_speed, 2)
            save_config(self.config)

    def apply_speed(self) -> None:
        self.js(f"pet.setSpeed({self._speed():.3f})")

    def _advance(self) -> None:
        dt = TICK_MS / 1000.0
        self.t += dt
        if self.transient:
            self.transient_left -= dt
            if self.transient_left <= 0:
                self.transient = None

        tx, ty = self.gaze_target
        if not self.gaze_enabled:
            tx = ty = 0.0
        if abs(tx - self.last_gaze[0]) > 0.25 or abs(ty - self.last_gaze[1]) > 0.25:
            self.last_gaze = (tx, ty)
            self.js(f"pet.setGaze({tx:.2f}, {ty:.2f})")

    def paintEvent(self, _event) -> None:
        """Everything visual is painted by the embedded page."""
        return

    # ------------------------------------------------------------------ look

    def _track_cursor(self) -> None:
        dt = 0.05
        if self.transient:
            self.transient_left -= dt
            if self.transient_left <= 0:
                self.transient = None

        if not self.gaze_enabled:
            self.gaze_target = (0.0, 0.0)
            if self.last_gaze != (0.0, 0.0):
                self.last_gaze = (0.0, 0.0)
                self.js("pet.setGaze(0, 0)")
            return
        # gaze: point the eye at the cursor, a little further than before, but
        # never into the sclera edge. Two units per 20px, capped at 8.5.
        center = self.geometry().center()
        cursor = QCursor.pos()
        dx = cursor.x() - center.x()
        dy = cursor.y() - center.y()
        length = max(1.0, (dx * dx + dy * dy) ** 0.5)
        reach = min(8.5, length / 90.0 * 8.5)
        self.gaze_target = (dx / length * reach, dy / length * reach)
        tx, ty = self.gaze_target
        if abs(tx - self.last_gaze[0]) > 0.25 or abs(ty - self.last_gaze[1]) > 0.25:
            self.last_gaze = (tx, ty)
            self.js(f"pet.setGaze({tx:.2f}, {ty:.2f})")

    # ---------------------------------------------------------------- states

    def set_mode(self, mode: str) -> None:
        if self.mode != mode:
            self.mode = mode
            self._sync_state()
            self.apply_speed()

    def play(self, state: str) -> None:
        if state == "done":
            self.js("pet.fault('blocks')")
            self.js("pet.blink()")
            self.transient = "done"
            self.transient_left = 0.9
        elif state == "poked":
            self.js("pet.blink(true)")
            self.transient = "poked"
            self.transient_left = 0.45

    def say(self, text: str) -> None:
        if not self.isVisible():
            return
        self.bubble.pop(text, self.geometry())
        self.play("poked")

    def _apply_state(self, state: dict) -> None:
        working = bool(state.get("working"))
        # The mini window reads one conversation, and only when it is open.
        # Never read while a turn is running: Hana rewrites the session file over
        # and over then, and a read landing on its atomic rename breaks the save
        # (EPERM). Read once, after the turn has finished and the write settled.
        if working != self._working and not working:
            if self.chat_window and self.chat_window.isVisible():
                # turn finished — wait for the final write to land, then read once
                QTimer.singleShot(2500, self._history_after_turn)
        if working and not self._working:
            self.set_mode("work")
        elif not working and self._working:
            self.set_mode("idle")
            self.play("done")
        self._working = working
        # while idle nothing but a new turn can change anything; ask less often then
        interval = 1600 if working else 3000
        if self.poll.interval() != interval:
            self.poll.setInterval(interval)
        if not working and self.mode == "work":
            self.set_mode("idle")
        for text in state.get("bubbles") or []:
            self.say(str(text))
        if self.chat_window and self.chat_window.isVisible():
            self.chat_window.set_thinking_menu(state.get("thinkingLevel"))
            self.chat_window.set_permission_label(state.get("permission"))
            self.chat_window.set_preset_label(state.get("preset"))
            model_id = state.get("modelId")
            if model_id and self.chat_window.model_button.text() in ("模型", ""):
                self.chat_window.set_model_label(str(model_id).split("/")[-1])

    def _poll_state(self) -> None:
        self.run_job("state", self.bridge.state)

    def _save_theme(self, theme: dict) -> None:
        self.config["theme"] = theme
        save_config(self.config)

    def on_usage_range(self, key: str) -> None:
        self.usage_range = key
        self.refresh_usage(force=True)

    def refresh_usage(self, force: bool = False) -> None:
        """Read balance + spend for the picked window, cached for a minute."""
        if not (self.chat_window and self.chat_window.isVisible()):
            return
        now = time.monotonic()
        cached = self.usage_cache.get(self.usage_range)
        if not force and cached and now - cached[0] < 90:
            self.chat_window.cost_bar.set_usage(*cached[1:])
            return
        self.run_job(
            "usage",
            lambda: self.account.snapshot(self.usage_range),
            replace=False,
        )

    def _poll_metrics(self) -> None:
        # Nothing to draw while the pet is hidden behind a fullscreen app.
        if not self.isVisible():
            return
        self.run_job("metrics", self.metrics.sample, replace=False)

    def _history_after_turn(self) -> None:
        if self._working:
            return
        if not (self.chat_window and self.chat_window.isVisible()):
            return
        self.run_job("history", lambda: self.bridge.history())

    # ------------------------------------------------------------ positioning

    def own_handles(self) -> set[int]:
        handles = {int(self.winId())}
        if self.chat_window:
            handles.add(int(self.chat_window.winId()))
        handles.add(int(self.bubble.winId()))
        return handles

    def watch_foreground(self) -> None:
        if self.pin_mode != "yield":
            return
        try:
            fullscreen = foreground_is_fullscreen(self.own_handles())
        except Exception:
            return
        if fullscreen:
            if self.isVisible():
                self._auto_hidden = True
                self.hide()
            self.bubble.hide()
            if self.chat_window and self.chat_window.isVisible():
                self.chat_window.hide()
        elif self._auto_hidden and not self._user_hidden:
            self._auto_hidden = False
            self.show()

    def remember_position(self) -> None:
        self.state["pos"] = {"x": self.x(), "y": self.y()}
        save_state(self.state)

    def _clamp_to_screens(self) -> None:
        rect = QRect(self.x(), self.y(), self.width(), self.height())
        for screen in QApplication.screens():
            if screen.availableGeometry().intersects(rect):
                return
        area = QApplication.primaryScreen().availableGeometry()
        self.move(
            area.right() - self.frame_px - 30,
            area.bottom() - self.frame_px - 30,
        )

    def apply_pin(self, mode: str | None = None) -> None:
        """none = ordinary window, yield = on top but steps aside for fullscreen,
        always = topmost even over a fullscreen app."""
        if mode is not None:
            self.pin_mode = mode
            self.config["pin"] = mode
            save_config(self.config)
        topmost = self.pin_mode != "none"
        targets = [self, self.bubble]
        if self.chat_window:
            targets.append(self.chat_window)
        for widget in targets:
            flags = widget.windowFlags()
            if bool(flags & Qt.WindowStaysOnTopHint) == topmost:
                continue
            was_visible = widget.isVisible()
            widget.setWindowFlag(Qt.WindowStaysOnTopHint, topmost)
            if was_visible:
                widget.show()
        if topmost:
            self.raise_()
        if self.pin_mode == "always" and self._auto_hidden:
            self._auto_hidden = False
            if not self._user_hidden:
                self.show()

    def set_visible(self, visible: bool, user: bool = True) -> None:
        if visible:
            self._user_hidden = False
            self._auto_hidden = False
            self.show()
            self.raise_()
        else:
            if user:
                self._user_hidden = True
            self.hide()
            self.bubble.hide()

    def apply_size(self, size: int, save: bool = True) -> None:
        size = max(90, min(300, int(size)))
        self.size_px = size
        self.frame_px = int(round(size * FRAME_SCALE))
        self.setFixedSize(self.frame_px, self.frame_px)
        if hasattr(self, "web"):
            self.web.setGeometry(0, 0, self.frame_px, self.frame_px)
        self.config["size"] = size
        if save:
            save_config(self.config)
        if self.chat_window and self.chat_window.isVisible():
            self.place_chat()
        self.update()

    # -------------------------------------------------------------- interact

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._press_pos = event.globalPosition().toPoint()
            self._drag_offset = self._press_pos - self.pos()
            self._moved = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            current = event.globalPosition().toPoint()
            if (current - self._press_pos).manhattanLength() > 4:
                self._moved = True
            self.move(current - self._drag_offset)
            if self.chat_window and self.chat_window.isVisible():
                self.place_chat()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            if not self._moved:
                self.toggle_chat()
            else:
                self.remember_position()
            self._drag_offset = None
        super().mouseReleaseEvent(event)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if not paths:
            return
        self.open_chat()
        self._load_attachments(paths)
        event.acceptProposedAction()

    def ask_credentials(self) -> None:
        """One window: log in once inside the pet, the session is kept on disk."""
        dialog = AccountWindow(self.account)
        if self.pin_mode != "none":
            dialog.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        dialog.exec()
        self.usage_cache.clear()
        self.refresh_usage(force=True)

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(menu_style())

        about_action = menu.addAction("关于")
        menu.addSeparator()

        gaze_action = menu.addAction("看向鼠标")
        gaze_action.setCheckable(True)
        gaze_action.setChecked(self.gaze_enabled)

        pin_menu = menu.addMenu("置顶")
        pin_menu.setStyleSheet(menu_style())
        pin_group = QActionGroup(pin_menu)
        pin_group.setExclusive(True)
        self._pin_actions = {}
        for key, label in PIN_MODES:
            action = pin_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(self.pin_mode == key)
            action.triggered.connect(lambda _checked=False, value=key: self.apply_pin(value))
            pin_group.addAction(action)
            self._pin_actions[key] = action

        speed_menu = menu.addMenu("动画速度")
        speed_menu.setStyleSheet(menu_style())
        speed_group = QActionGroup(speed_menu)
        speed_group.setExclusive(True)
        for key, label in SPEED_MODES:
            action = speed_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(self.speed_mode == key)
            action.triggered.connect(lambda _checked=False, value=key: self.set_speed_mode(value))
            speed_group.addAction(action)

        lid_menu = menu.addMenu("眯眼")
        lid_menu.setStyleSheet(menu_style())
        lid_group = QActionGroup(lid_menu)
        lid_group.setExclusive(True)
        for key, label in LID_MODES:
            action = lid_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(self.lid_mode == key)
            action.triggered.connect(lambda _checked=False, value=key: self.set_lid_mode(value))
            lid_group.addAction(action)

        speed_box = QWidget()
        speed_layout = QVBoxLayout(speed_box)
        speed_layout.setContentsMargins(12, 4, 12, 6)
        speed_layout.setSpacing(2)
        speed_label = QLabel()
        speed_label.setStyleSheet(f"color:{DIM}; font-size:11px;")
        speed_label.setCursor(Qt.ArrowCursor)
        speed_slider = QSlider(Qt.Horizontal)
        speed_slider.setRange(int(SPEED_MIN * 100), int(SPEED_MAX * 100))
        speed_slider.setSingleStep(5)
        speed_slider.setPageStep(20)
        speed_slider.setValue(int(round(self.manual_speed * 100)))
        speed_slider.setFixedWidth(190)
        speed_slider.setStyleSheet(
            "QSlider::groove:horizontal { height:3px; background: rgba(126,170,222,0.25); border-radius:2px; }"
            f"QSlider::handle:horizontal {{ width:11px; height:11px; margin:-4px 0; border-radius:5px; background:{ACCENT}; }}"
        )

        def speed_caption(value: float) -> str:
            if self.speed_mode == "manual":
                return f"速度  {value:.2f}×（手动）"
            source = "显卡" if self.speed_mode == "gpu" else "CPU"
            return f"速度  {value:.2f}×（跟 {source}）"

        speed_label.setText(speed_caption(self._speed()))

        def on_speed(value: int) -> None:
            speed = value / 100.0
            speed_label.setText(speed_caption(speed))
            self.set_manual_speed(speed, save=False)

        speed_slider.valueChanged.connect(on_speed)
        speed_slider.sliderReleased.connect(lambda: self.set_manual_speed(self.manual_speed, save=True))
        speed_layout.addWidget(speed_label)
        speed_layout.addWidget(speed_slider)
        speed_action = QWidgetAction(menu)
        speed_action.setDefaultWidget(speed_box)
        menu.addAction(speed_action)

        size_box = QWidget()
        size_layout = QVBoxLayout(size_box)
        size_layout.setContentsMargins(12, 4, 12, 6)
        size_layout.setSpacing(2)
        size_label = QLabel(f"大小  {self.size_px}px")
        size_label.setStyleSheet(f"color:{DIM}; font-size:11px;")
        size_label.setCursor(Qt.ArrowCursor)
        size_slider = QSlider(Qt.Horizontal)
        size_slider.setRange(90, 300)
        size_slider.setSingleStep(2)
        size_slider.setPageStep(20)
        size_slider.setValue(self.size_px)
        size_slider.setFixedWidth(190)
        size_slider.setStyleSheet(
            "QSlider::groove:horizontal { height:3px; background: rgba(126,170,222,0.25); border-radius:2px; }"
            f"QSlider::handle:horizontal {{ width:11px; height:11px; margin:-4px 0; border-radius:5px; background:{ACCENT}; }}"
        )

        def on_size(value: int) -> None:
            size_label.setText(f"大小  {value}px")
            self.apply_size(value, save=False)
            QTimer.singleShot(500, lambda: self.apply_size(self.size_px, save=True))

        size_slider.valueChanged.connect(on_size)
        size_slider.sliderReleased.connect(lambda: self.apply_size(self.size_px, save=True))
        size_layout.addWidget(size_label)
        size_layout.addWidget(size_slider)
        size_action = QWidgetAction(menu)
        size_action.setDefaultWidget(size_box)
        menu.addAction(size_action)

        menu.addSeparator()
        account_action = menu.addAction("DeepSeek 账户…")
        menu.addSeparator()
        hide_action = menu.addAction("隐藏")
        hana_action = menu.addAction("打开 dsh 客户端")
        menu.addSeparator()
        quit_action = menu.addAction("退出")

        chosen = menu.exec(event.globalPos())
        if chosen == about_action:
            dialog = AboutWindow(None)
            if self.pin_mode != "none":
                dialog.setWindowFlag(Qt.WindowStaysOnTopHint, True)
            dialog.exec()
        elif chosen == gaze_action:
            self.gaze_enabled = gaze_action.isChecked()
            self.config["gaze"] = self.gaze_enabled
            save_config(self.config)
        elif chosen == account_action:
            self.ask_credentials()
        elif chosen == hide_action:
            self.set_visible(False)
        elif chosen == hana_action:
            if not bring_dsh_to_front():
                self.say("没找到 dsh 的窗口。")
        elif chosen == quit_action:
            QApplication.quit()

    # ------------------------------------------------------------------ chat

    def place_chat(self) -> None:
        if not self.chat_window:
            return
        offset = self.state.get("chatOffset")
        if isinstance(offset, dict) and "dx" in offset and "dy" in offset:
            x = self.x() + int(offset.get("dx", 0))
            y = self.y() + int(offset.get("dy", 0))
        else:
            x = self.x() + self.width() + 10
            y = self.y() + self.height() - self.chat_window.height()
        screen = QApplication.screenAt(self.pos()) or QApplication.primaryScreen()
        if screen:
            area = screen.availableGeometry()
            x = max(area.left() + 6, min(x, area.right() - self.chat_window.width() - 6))
            y = max(area.top() + 6, min(y, area.bottom() - self.chat_window.height() - 6))
        self.chat_window.move(x, y)

    def remember_chat_offset(self) -> None:
        if not self.chat_window:
            return
        self.state["chatOffset"] = {
            "dx": self.chat_window.x() - self.x(),
            "dy": self.chat_window.y() - self.y(),
        }
        save_state(self.state)

    def remember_chat_size(self) -> None:
        if not self.chat_window:
            return
        if not hasattr(self, "_size_timer"):
            self._size_timer = QTimer(self)
            self._size_timer.setSingleShot(True)
            self._size_timer.timeout.connect(self._save_chat_size)
        self._size_timer.start(450)

    def _save_chat_size(self) -> None:
        if not self.chat_window:
            return
        self.state["chatSize"] = {
            "w": self.chat_window.width(),
            "h": self.chat_window.height(),
        }
        save_state(self.state)

    def open_chat(self) -> None:
        if not self.chat_window:
            window = ChatWindow(self.config.get("theme"))
            window.sendRequested.connect(self._on_chat_send)
            window.sessionRequested.connect(self._on_select)
            window.newRequested.connect(self._on_new)
            window.attachRequested.connect(self._on_attach)
            window.filesDropped.connect(self._load_attachments)
            window.modelsRequested.connect(lambda: self.run_job("models", self.bridge.models))
            window.thinkingRequested.connect(self._on_thinking)
            window.commandRequested.connect(self._on_commands)
            window.workspacesRequested.connect(lambda: self.run_job("workspaces", self.bridge.workspaces, replace=False))
            window.presetsRequested.connect(lambda: self.run_job("presets", self.bridge.presets, replace=False))
            # Resizing from the top-left grip must not fight the placement logic:
            # re-anchoring on every resize made the window jitter against the
            # cursor. It is re-placed only when the pet itself moves.
            window.resized.connect(self.remember_chat_size)
            window.movedByUser.connect(self.remember_chat_offset)
            size = self.state.get("chatSize") or {}
            width = int(size.get("w") or 0)
            height = int(size.get("h") or 0)
            if width > 260 and height > 220:
                window.resize(width, height)
            window.usageRangeRequested.connect(self.on_usage_range)
            window.settingsChanged.connect(self._save_theme)
            self.chat_window = window
        self.chat_window.set_messages([], False)
        self.run_job("sessions", self.bridge.sessions)
        if self._working:
            # the turn is mid-write: wait until it settles, then read once
            QTimer.singleShot(1200, self._history_after_turn)
        else:
            self.run_job("history", lambda: self.bridge.history())
        self.js("pet.blink()")
        if self.chat_window:
            self.chat_window.show()
            self.chat_window.raise_()
            self.chat_window.activateWindow()
            self.place_chat()
            self.chat_window.input.setFocus()
            self.run_job("wscurrent", self.bridge.workspaces, replace=False)
            self.run_job("modelslabel", self.bridge.models, replace=False)
            self.refresh_usage()

    def toggle_chat(self) -> None:
        if self.chat_window and self.chat_window.isVisible():
            self.chat_window.hide()
        else:
            self.open_chat()

    def _model_name(self, current: dict | None) -> str | None:
        if not current:
            return None
        model_id = current.get("modelId")
        if not model_id:
            return None
        return str(model_id).split("/")[-1]

    def _on_chat_send(self, text: str, payload) -> None:
        self.js("pet.blink()")
        if text == "__model__" and isinstance(payload, dict):
            model_id = str(payload.get("id"))
            provider = str(payload.get("provider"))
            effort = payload.get("defaultEffort")
            self.run_job("setmodel", lambda: self.bridge.set_model(model_id, provider, effort))
            return
        if text == "__workspace__" and payload:
            self._workspace_title = self._workspace_name(str(payload))
            self.run_job("setworkspace", lambda: self.bridge.set_workspace(str(payload)))
            return
        if text == "__preset__" and payload:
            self._preset = str(payload)
            self.run_job("setpreset", lambda: self.bridge.set_preset(str(payload)))
            return
        if text == "__effort__" and payload:
            self.run_job("thinking", lambda: self.bridge.set_thinking(str(payload)))
            if self.chat_window:
                self.chat_window.set_effort_label(str(payload))
            return
        if text == "__addworkspace__":
            self._pick_workspace()
            return
        if text == "__compact__":
            self.run_job("compact", self.bridge.compact)
            return
        images = self.pending_images or None
        self.pending_images = []
        if self.chat_window:
            self.chat_window.show_attachment([])
        self.run_job("send", lambda: self.bridge.send(text, images))

    def _pick_workspace(self) -> None:
        """Register a new workspace: pick a folder, hand the path to dsh.

        The dialog is top-level on purpose: a modal child of the frameless tool
        window can be created without ever being shown on Windows.
        """
        start = getattr(self, "_workspace_path", None) or os.path.expanduser("~")
        path = QFileDialog.getExistingDirectory(None, "选择工作区目录", start)
        if not path:
            return
        self.run_job("addworkspace", lambda: self.bridge.create_workspace(path))

    def _workspace_name(self, workspace_id: str) -> str:
        try:
            for space in (self.bridge.workspaces().get("workspaces") or []):
                if space.get("id") == workspace_id:
                    return str(space.get("title") or space.get("path") or "")
        except Exception:
            pass
        return ""

    def _on_select(self, session_id: str) -> None:
        self.run_job("select", lambda: self.bridge.select(session_id))

    def _on_new(self) -> None:
        self.run_job("new", self.bridge.new_session)

    def _on_thinking(self, level: str) -> None:
        self.run_job("thinking", lambda: self.bridge.set_thinking(level))
        if self.chat_window:
            self.chat_window.set_thinking_menu(level)

    def _on_commands(self) -> None:
        self.run_job("commands", self.bridge.commands)

    def _on_attach(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self.chat_window, "选择图片", "", "图片 (*.png *.jpg *.jpeg *.webp *.gif)"
        )
        if paths:
            self._load_attachments(paths)

    def _load_attachments(self, paths: list[str]) -> None:
        loaded = []
        names = []
        for path in paths[:4]:
            try:
                with open(path, "rb") as handle:
                    data = handle.read()
                mime = mimetypes.guess_type(path)[0] or ""
                if not mime.startswith("image/"):
                    continue
                loaded.append({"data": base64.b64encode(data).decode("ascii"), "mimeType": mime})
                names.append(os.path.basename(path))
            except Exception:
                continue
        if loaded:
            self.pending_images = loaded
            if self.chat_window:
                self.chat_window.show_attachment(names)
                self.chat_window.input.setFocus()


class Tray(QSystemTrayIcon):
    def __init__(self, sprite: Sprite) -> None:
        super().__init__()
        self.setIcon(QIcon(os.path.join(ASSETS, "icon.png")))
        self.setToolTip("Fairy 桌宠")
        menu = QMenu()
        menu.setStyleSheet(menu_style())
        show_action = menu.addAction("显示宠物")
        chat_action = menu.addAction("打开对话")
        quit_action = menu.addAction("退出")
        show_action.triggered.connect(lambda: sprite.set_visible(True))
        chat_action.triggered.connect(lambda: (sprite.set_visible(True), sprite.open_chat()))
        quit_action.triggered.connect(QApplication.quit)
        self.setContextMenu(menu)
        self.activated.connect(self._activated)
        self.sprite = sprite

    def _activated(self, reason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            self.sprite.set_visible(True)


def acquire_single_instance() -> bool:
    """True when this process owns the pet slot; a second copy exits at once."""
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, "Global\\FairyPetDshSingleInstance")
    if not handle:
        return True
    ERROR_ALREADY_EXISTS = 183
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        return False
    globals()["_PET_MUTEX"] = handle
    return True


def write_pet_pid() -> None:
    """Leave a pid behind so the launcher can kill this instance even after it
    forgets about us (Hana restarting, a stale launcher entry, taskkill by hand).
    pythonw.exe in the venv is a redirector, so the child pid is written too."""
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(os.path.join(CONFIG_DIR, "pet.pid"), "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
    except Exception:
        pass


def main() -> int:
    from PySide6.QtCore import QCoreApplication

    if not acquire_single_instance():
        return 0

    os.environ.setdefault(
        "QTWEBENGINE_CHROMIUM_FLAGS",
        "--disable-background-timer-throttling "
        "--disable-renderer-backgrounding "
        "--disable-backgrounding-occluded-windows "
        "--disable-features=CalculateNativeWinOcclusion",
    )
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("FairyPet")
    app.setFont(QFont("Microsoft YaHei UI", 9))
    app.setStyleSheet(
        "QMenu { background:#101a26; color:#dfe8f2;"
        " border:1px solid rgba(126,170,222,0.24); padding:5px; border-radius:8px; }"
        "QMenu::item { padding:6px 22px 6px 14px; border-radius:5px; }"
        "QMenu::item:selected { background: rgba(77,143,214,0.35); }"
        "QMenu::separator { height:1px; background: rgba(126,170,222,0.18); margin:4px 6px; }"
        "QMenu::indicator { width:10px; }"
        "QWidget { selection-background-color: rgba(77,143,214,0.55); selection-color:#ffffff; }"
        "QToolTip { background:#101a26; color:#dfe8f2; border:1px solid rgba(126,170,222,0.24); }"
    )

    sprite = Sprite()
    sprite.show()
    write_pet_pid()
    tray = Tray(sprite)
    tray.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
