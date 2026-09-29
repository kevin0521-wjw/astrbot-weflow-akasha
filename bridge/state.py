"""
微信 ↔ AstrBot 桥接（OneBot v11 版）
=====================================
消息接收：WeFlow SSE 推送
AI 服务：AstrBot 通过 aiocqhttp (OneBot v11) 接入
消息发送：bridge 接收 AstrBot 的 API 调用 → WeFlow API / UIA

架构：
  WeFlow ──SSE──→ bridge.py ──WS 客户端──→ AstrBot (aiocqhttp 服务端)
                   ↑ 连接 ws://127.0.0.1:19777  ↑ 监听端口，等待客户端连入
                   发送 OneBot 事件             返回 API 响应
"""

# 共享状态：所有模块通过 import state 访问这些变量
import threading
from typing import Optional

# ============ 状态控制 ============

running = False
paused = threading.Event()
paused.clear()
run_lock = threading.Lock()
bridge_thread = None

# ============ OneBot WebSocket 客户端管理 ============

_ob_ws = None          # WebSocket 连接实例
_ob_ws_loop = None     # 事件循环
_ob_ws_ready = threading.Event()
_self_id_int = 0       # 启动时从 config 初始化


def _wxid_to_int(wxid: str) -> int:
    """将微信 wxid 映射为稳定的整数 ID。

    使用 zlib.crc32 代替内置 hash()：
    - 内置 hash(str) 受 PYTHONHASHSEED 影响，进程重启后结果会变化，
      导致 OneBot 会话 ID 不稳定、白名单失效。
    - crc32 是确定性算法，跨进程/跨重启结果一致。
    """
    import zlib

    return zlib.crc32(wxid.encode("utf-8")) & 0x7FFFFFFF


# ============ 桥接实例 / 发送器 ============

bridge_instance = None
bridge_lock = threading.Lock()
sender_instance = None
_ob_id_to_contact: dict[int, str] = {}  # OneBot user_id/group_id → 微信联系名
ob_client_started = False

# 群聊回复模式（运行时可变，启动时从 config 初始化）
group_reply_mode = "mention"
