# AstrBot × WeFlow 微信桥接 · 优化版

把**微信个人号**接入大模型（LLM），通过 **OneBot v11** 协议与 AstrBot 通信。

> 本仓库是 [alingalingling/Akasha-WeChat](https://github.com/alingalingling/Akasha-WeChat) 的**个人实践优化版**：
> 保留了上游的桥接思路与 MIT 许可，沉淀了两个阶段（2026-07-24 ~ 09-13 的 AstrBot 侧部署期、2026-07-27 起的 bridge 侧精修期）
> 踩过的坑与修复方案。**所有改动均来自真实运行环境，非理论推演。**

---

## 一、整体架构

```
                 ┌──────────────────────────────┐
   微信群/好友   │  微信个人号（PC 微信，需登录） │
                 └───────────────┬──────────────┘
                                 │ WeFlow 抓取消息
                                 ▼
                 ┌──────────────────────────────┐
                 │  WeFlow  (127.0.0.1:5031)     │
                 │  · SSE 推送新消息             │
                 │  · 发送 API / 附件下载         │
                 └───────────────┬──────────────┘
                                 │ SSE 长连接
                                 ▼
                 ┌──────────────────────────────┐
                 │  bridge (wechat-weflow-bridge-ob11) │
                 │  · 缓冲合并消息（buffer_seconds）   │
                 │  · 图片 → 视觉模型转文字描述        │
                 │  · Web 控制面板 (127.0.0.1:8766)   │
                 └───────────────┬──────────────┘
                                 │ WebSocket 客户端
                                 │ ws://127.0.0.1:11229/ws
                                 ▼
                 ┌──────────────────────────────┐
                 │  AstrBot (aiocqhttp / OneBot v11) │
                 │  · 人格（如「派蒙」）              │
                 │  · 白名单 / 插件 / 提示词          │
                 └───────────────┬──────────────┘
                                 │
                                 ▼
                         DeepSeek / 其他文本 LLM

   回程：AstrBot --(send_group_msg / send_private_msg)--> bridge --UIA 键盘模拟--> 微信
```

### 两段式图片识别的关键认知

**主 LLM 是纯文本模型（如 DeepSeek）并不影响图片识别**：

| 环节 | 模型 | 职责 |
|------|------|------|
| 看图 | 本地 Ollama + LLaVA 7B（或 OpenAI 兼容多模态 API） | 把图片「翻译」成一段文字描述 |
| 回复 | DeepSeek（纯文本） | 只读文字描述，按人格风格回复 |

所以**不需要**把主模型换成多模态模型。

---

## 二、优化总览

### 阶段 A：AstrBot 侧部署与调优（2026-07-24 ~ 2026-09-13）

| # | 优化项 | 解决的问题 | 落地位置 |
|---|--------|-----------|----------|
| A1 | 群聊白名单（内置方案） | 只想让 bot 在指定群里生效 | AstrBot `cmd_config.json` → `platform_settings.enable_id_white_list` + `id_whitelist` |
| A2 | **群 ID 稳定性修复** | `hash()` 受 PYTHONHASHSEED 影响，重启后白名单全失效 | `bridge/state.py::_wxid_to_int` |
| A3 | 私聊放行补丁 | 白名单开启后私聊也被拦 | AstrBot `whitelist_check/stage.py` |
| A4 | Bot 输出简短化 | 回复又长又碎，刷屏 | 提示词 `provider_settings.prompt_prefix` |
| A5 | **长文本自动分段** | 一大段文字全塞进一条消息 | `bridge/ob_protocol.py::_split_long_text` |
| A6 | 图片识别落地 | DeepSeek 不认图 | Ollama + `llava:7b`（国内镜像） |

### 阶段 B：bridge 侧精修（2026-07-27 起）

| # | 优化项 | 解决的问题 | 落地位置 | 状态 |
|---|--------|-----------|----------|------|
| B1 | **config 缺字段崩溃修复** | `KeyError: 'weflow_send_api'` 启动即挂 | `bridge/config.py` | ✅ 已生效 |
| B2 | 发送方式默认值纠正 | 面板显示 `weflow_api`，实际用 UIA | `bridge/config.py` | ✅ 已生效 |
| B3 | 配置自动初始化 | 首次部署缺 config.json | `bridge/config.py` | ✅ 已生效 |
| B4 | **UIA 发送器自愈** | 启动时没抓到微信窗口 → 永久「未就绪」 | `bridge/uia_sender.py` | ✅ 已生效 |
| B5 | 发送结果日志纠偏 | 实际没发出去却打「已发送」 | `bridge/ob_protocol.py` | ✅ 已生效 |
| B6 | 管理员权限插件 | 需要给他人管理员权限 | `astrbot_plugin_admin_manager/` | ✅ 已交付 |
| B7 | 表情包识别 / 按群回复模式 / 安全防护 | —— | —— | ⚠️ **已回滚**（见下） |

> **关于 B7**：这三个功能曾完整实现（`emoji_map.py` QQ 表情 ID 映射表、`group_whitelist` 按群回复模式、`SECURITY_SYSTEM_PROMPT` + prompt 注入检测 + 敏感输出过滤），
> 但实测引入 bug 影响主链路，**已全部回滚到原始状态**。详细复盘见 [docs/07-回滚功能复盘.md](docs/07-回滚功能复盘.md)，供后续重做时避坑。

### 详细文档

| 文档 | 内容 |
|------|------|
| [docs/01-架构与数据流.md](docs/01-架构与数据流.md) | 消息收发全链路、字段说明 |
| [docs/02-群聊白名单与稳定群ID.md](docs/02-群聊白名单与稳定群ID.md) | 白名单机制 + crc32 群 ID 修复 |
| [docs/03-图片识别与表情处理.md](docs/03-图片识别与表情处理.md) | Ollama / OpenAI 双后端描述链路 |
| [docs/04-输出简短与自动分段.md](docs/04-输出简短与自动分段.md) | 提示词 + 代码双层控制 |
| [docs/05-UIA发送器与稳定性修复.md](docs/05-UIA发送器与稳定性修复.md) | 窗口自愈 + 日志纠偏 |
| [docs/06-管理员权限插件.md](docs/06-管理员权限插件.md) | AstrBot 插件安装与指令 |
| [docs/07-回滚功能复盘.md](docs/07-回滚功能复盘.md) | 表情包 / 按群模式 / 安全防护的失败复盘 |
| [CHANGELOG.md](CHANGELOG.md) | 逐条变更时间线 |

---

## 三、快速开始

```bash
# 1. 依赖
cd bridge
pip install -r requirements.txt

# 2. 配置（首次运行会自动从 config.example.json 生成 config.json）
#    必改：access_token（WeFlow 的）、bot_nicknames、astrbot_attachments
#    可选：config.json 已被 .gitignore 排除，不会误提交

# 3. 前置服务
#    - PC 微信已登录并保持窗口打开（UIA 发送依赖窗口句柄）
#    - WeFlow 已启动，监听 127.0.0.1:5031
#    - AstrBot 已启动，aiocqhttp 适配器监听 ws://127.0.0.1:11229/ws

# 4. 启动
start.bat            # 或 python main.py
```

控制面板：<http://127.0.0.1:8766/>

---

## 四、许可与致谢

- 本项目基于 [alingalingling/Akasha-WeChat](https://github.com/alingalingling/Akasha-WeChat) 的桥接实现二次开发，遵循 **MIT License**。
- 上游版权声明保留在 [`bridge/LICENSE`](bridge/LICENSE)。
- 本仓库包含的改动由使用者自己的运行环境验证，**不保证与上游版本兼容**。
