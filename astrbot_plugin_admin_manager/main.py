"""
管理员权限管理插件 - AstrBot Plugin

功能：
  - /admin list          —— 查看所有管理员
  - /admin add <wxid>    —— 添加管理员（仅管理员可执行）
  - /admin remove <wxid> —— 移除管理员（仅管理员可执行）
  - /ping                —— 测试连通性（所有人可用）
  - /reload              —— 重载插件配置（仅管理员可执行）

权限机制：
  使用 AstrBot 自带的 @filter.permission_type(filter.PermissionType.ADMIN) 装饰器
  进行权限校验，管理员列表配置在 AstrBot WebUI → 设置 → 管理员配置 中。
  
  同时插件在本地维护一份 admin_users.json 作为辅助，支持运行时动态管理。

安装方式：
  1. AstrBot WebUI → 插件管理 → 从文件安装 → 选择本插件打包的 zip
  2. 或解压到 ~/.astrbot/data/plugins/astrbot_plugin_admin_manager/
"""

import json
import os
from typing import Optional

from astrbot.api import logger
from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star, register

PLUGIN_NAME = "astrbot_plugin_admin_manager"
PLUGIN_AUTHOR = "Akasha Bridge"
PLUGIN_DESC = "管理员权限管理：添加/删除/查看管理员用户"
PLUGIN_VERSION = "v1.0.0"

# 本地管理员列表文件（辅助存储）
ADMIN_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "admin_users.json",
)


def _load_admin_users() -> list[str]:
    """从本地 JSON 文件加载管理员列表"""
    if not os.path.exists(ADMIN_FILE):
        return []
    try:
        with open(ADMIN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            return data.get("admins", []) if isinstance(data, dict) else []
    except Exception as e:
        logger.warning(f"[AdminManager] 加载管理员列表失败: {e}")
        return []


def _save_admin_users(users: list[str]):
    """保存管理员列表到本地 JSON 文件"""
    try:
        with open(ADMIN_FILE, "w", encoding="utf-8") as f:
            json.dump({"admins": users}, f, ensure_ascii=False, indent=2)
        logger.info(f"[AdminManager] 管理员列表已保存: {len(users)} 人")
    except Exception as e:
        logger.error(f"[AdminManager] 保存管理员列表失败: {e}")


def _get_sender_identifier(event: AstrMessageEvent) -> str:
    """获取消息发送者的唯一标识符（优先 wxid，其次 user_id）"""
    sender_id = event.get_sender_id()
    if sender_id:
        return str(sender_id)
    # 部分平台可以通过 message_obj 获取更多信息
    if hasattr(event, "message_obj") and event.message_obj:
        if hasattr(event.message_obj, "sender") and event.message_obj.sender:
            return str(event.message_obj.sender.user_id)
    return "unknown"


@register(PLUGIN_NAME, PLUGIN_AUTHOR, PLUGIN_DESC, PLUGIN_VERSION)
class AdminManagerPlugin(Star):
    """管理员权限管理插件"""

    def __init__(self, context: Context):
        super().__init__(context)
        # 初始化管理员列表
        self.admin_users = _load_admin_users()
        logger.info(f"[AdminManager] 已加载 {len(self.admin_users)} 个管理员")

    # ================================================================
    # 基础指令（所有人可用）
    # ================================================================

    @filter.command("ping")
    async def ping(self, event: AstrMessageEvent):
        """测试连通性——所有人可用"""
        sender = _get_sender_identifier(event)
        is_admin = sender in self.admin_users
        role = "管理员" if is_admin else "普通用户"
        yield event.plain_result(
            f"🏓 Pong!\n"
            f"  · 发送者: {sender}\n"
            f"  · 角色: {role}\n"
            f"  · 插件版本: {PLUGIN_VERSION}"
        )

    # ================================================================
    # 管理员指令（仅管理员可执行）
    # ================================================================

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("admin")
    async def admin(self, event: AstrMessageEvent):
        """查看全部管理员列表"""
        if not self.admin_users:
            yield event.plain_result("📋 当前没有配置任何本地管理员。\n"
                                      "请通过 AstrBot WebUI → 设置 → 管理员配置 添加。")
            return

        lines = ["📋 管理员列表（共 {} 人）:".format(len(self.admin_users))]
        for i, uid in enumerate(self.admin_users, 1):
            lines.append(f"  {i}. {uid}")
        yield event.plain_result("\n".join(lines))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("admin add")
    async def admin_add(self, event: AstrMessageEvent, wxid: Optional[str] = None):
        """添加管理员   用法: /admin add <wxid>"""
        if not wxid:
            yield event.plain_result("❌ 用法: /admin add <wxid>\n"
                                      "例如: /admin add wxid_xxxxxxxx")
            return

        if wxid in self.admin_users:
            yield event.plain_result(f"⚠️ {wxid} 已经是管理员了。")
            return

        self.admin_users.append(wxid)
        _save_admin_users(self.admin_users)
        logger.info(f"[AdminManager] 管理员已添加: {wxid} (操作者: {_get_sender_identifier(event)})")
        yield event.plain_result(f"✅ 已添加管理员: {wxid}\n当前共 {len(self.admin_users)} 人")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("admin remove")
    async def admin_remove(self, event: AstrMessageEvent, wxid: Optional[str] = None):
        """移除管理员   用法: /admin remove <wxid>"""
        if not wxid:
            yield event.plain_result("❌ 用法: /admin remove <wxid>\n"
                                      "例如: /admin remove wxid_xxxxxxxx")
            return

        if wxid not in self.admin_users:
            yield event.plain_result(f"⚠️ {wxid} 不在管理员列表中。")
            return

        self.admin_users.remove(wxid)
        _save_admin_users(self.admin_users)
        logger.info(f"[AdminManager] 管理员已移除: {wxid} (操作者: {_get_sender_identifier(event)})")
        yield event.plain_result(f"✅ 已移除管理员: {wxid}\n当前共 {len(self.admin_users)} 人")

    # ================================================================
    # 工具指令
    # ================================================================

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("reload")
    async def reload_config(self, event: AstrMessageEvent):
        """重载管理员列表配置"""
        old_count = len(self.admin_users)
        self.admin_users = _load_admin_users()
        new_count = len(self.admin_users)
        yield event.plain_result(
            f"🔄 管理员列表已重载\n"
            f"  · 之前: {old_count} 人\n"
            f"  · 现在: {new_count} 人"
        )
