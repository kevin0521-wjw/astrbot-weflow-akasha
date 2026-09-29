# 变更记录 CHANGELOG

本文件记录两轮实践中对 AstrBot × WeFlow 微信桥接的全部改动。

- **阶段 A**（2026-07-24 ~ 2026-09-13）：AstrBot 侧部署期，会话主题「查找白名单群聊管理插件」
- **阶段 B**（2026-07-27 起）：bridge 侧精修期，会话主题「修复微信机器人桥接面板的三个 bug」

图例：✅ 已生效 · ⚠️ 已回滚 · 📌 仅供后续参考

---

## 阶段 A：AstrBot 侧（2026-07-24 ~ 2026-09-13）

### 2026-07-24 · 环境搭建

- 按 B 站教程思路，用 WeFlow + AstrBot + DeepSeek API 部署「微信个人号」机器人。
- 踩坑记录：
  - AstrBot 首次登录默认密码在日志里；升级后密码正确也可能登录失败（看官方 FAQ）。
  - `LLM 请求失败：未找到任何可用的对话模型（提供商）` → 需先在 WebUI 启用模型。
  - WebUI 里聊天能回复 ≠ 微信能回复，两条链路独立。
- 📌 中途一度误入 WeeMessenger 方案（`KilincocomilK/WeeMessenger`），最终确定走 WeFlow + AstrBot + OneBot v11。

### 2026-08-05 · 群聊白名单（A1 / A3）

**需求**：让 bot 只在限定的白名单群聊内生效。

| 项 | 内容 |
|----|------|
| 放弃的方案 | 插件市场找现成「白名单群聊管理插件」——没有合适的；曾临时写过 `grouplist_helper`，已删 |
| 最终方案 | AstrBot 内置 `platform_settings.enable_id_white_list` + `id_whitelist` |
| 配置文件 | `~/.astrbot/data/cmd_config.json` |
| 会话 ID 格式 | `default:GroupMessage:<整数群ID>` |

```jsonc
// ~/.astrbot/data/cmd_config.json 片段
"platform_settings": {
  "enable_id_white_list": true,
  "id_whitelist": [
    "default:GroupMessage:111111111",   // 测试群
    "default:GroupMessage:222222222"     // 某群A
  ]
}
```

**补丁**：白名单开启后私聊也会被拦 → 给 AstrBot `whitelist_check/stage.py` 增加
`FRIEND_MESSAGE`（私聊）直接放行分支。备份：`stage.py.bak_20260805`。

> 语义确认：**空列表 = 不检查（全放行）**，不是「全部拦截」。

### 2026-08-05 · 群 ID 稳定性修复（A2，关键 Bug）

**症状**：bridge 重启后，AstrBot 侧白名单突然全部失效。

**根因**：`bridge/state.py` 用内置 `hash(wxid)` 生成群 ID。
Python 的 `hash(str)` 受 **`PYTHONHASHSEED`** 随机化影响 —— 同一串群名/会话 ID，**每次进程启动得到的整数都不同**，
于是 `default:GroupMessage:<id>` 每次都变，写死在白名单里的 ID 自然失效。

```python
# ❌ 修复前
def _wxid_to_int(wxid: str) -> int:
    return abs(hash(wxid)) % (2**31)

# ✅ 修复后
def _wxid_to_int(wxid: str) -> int:
    import zlib
    return zlib.crc32(wxid.encode("utf-8")) & 0x7FFFFFFF
```

**收益**：群 ID 跨进程、跨重启恒定，白名单/群映射不再随机失效。
备份：`state.py.bak_20260805`。

### 2026-08-05 · Bot 输出简短化（A4）

**需求**：回复简短（≤2 行），内容多时自动分段。

- 提示词层：`cmd_config.json` → `provider_settings.prompt_prefix` 追加【输出要求】——简短两行内、内容多时自动分段（每段 ≤2 行、空行分隔）。
- 目的：从「生成侧」减少长回复，降低后续分段的压力。

### 2026-08-05 · 长文本自动分段（A5）

**需求**：代码层兜底，即使模型输出很长也不会挤成一大坨。

新增 `bridge/ob_protocol.py::_split_long_text(text, max_lines=2)`：

```python
def _split_long_text(text: str, max_lines: int = 2) -> list[str]:
    """将长文本按行拆分，每段最多 max_lines 行（2026-08-05 自定义）。"""
    lines = text.split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if len(lines) <= max_lines:
        return [text] if text.strip() else []
    chunks = []
    for i in range(0, len(lines), max_lines):
        chunk = "\n".join(lines[i:i + max_lines]).strip()
        if chunk:
            chunks.append(chunk)
    return chunks
```

在 `_handle_ob_api` 的 `text` 分支里，发送前先切分、再逐段 `send_text`：

```python
for chunk in _split_long_text(text, max_lines=2):
    if not chunk.strip():
        continue
    sent = await asyncio.to_thread(state.sender_instance.send_text, contact, chunk)
```

备份：`ob_protocol.py.bak_20260805`。

### 2026-08-05 ~ 08-08 · 图片识别落地（A6）

| 项 | 内容 |
|----|------|
| 视觉模型 | 本地 Ollama + `llava:7b`（RTX 5060 8GB 可跑） |
| 安装包 | `OllamaSetup.exe` v0.32.5（含 CUDA 运行时，约 1.46 GB） |
| 国内镜像 | `~/.ollama/config.json` 把 `registry.ollama.ai` 指向 `https://ollama.modelscope.cn` |
| 端口 | 先试 `OLLAMA_HOST=127.0.0.1:61000`，最终统一为默认 `11434` |

**架构澄清（重要）**：主 LLM 用 DeepSeek（纯文本）**不影响**图片识别，
因为看图的是 LLaVA、回复的是 DeepSeek —— 两段式。想提升识别质量**只需换视觉模型**，
不必换主模型（换 qwen-vl 需要改桥接传图格式，工作量大）。

📌 当时的卡点：WeFlow 没启动 → 微信消息进不来 → 整条链路无法触发。

### 2026-08-06 · 新群加入白名单

- 新群会话 ID：`99999999@chatroom`
- `crc32("99999999@chatroom") = 1757289731` → `default:GroupMessage:1757289731`
- 白名单变为 3 个群：测试(111111111)、某群A(222222222)、新群(1757289731)

> ⚠️ 注意：**群 ID 由群名/会话 ID 计算**。如果 WeFlow 之后解析出该群真实群名，ID 会变，需要重新加白名单。

### 2026-08-08 · 服务恢复与运行经验

- bridge / AstrBot 后端 / WeFlow **三者都没有自启**，电脑重启后需手动逐一启动。
- WeFlow 需**用户手动双击**启动（脚本拉起会立即退出）。

### 2026-09-13 12:21 · 阶段收束

- 确认工作流：微信消息 → WeFlow(5031) → bridge → AstrBot(WS 11229) → 「派蒙」人格回复 → 回传微信。
- 核心结论再次确认：**视觉模型翻译图片、文本模型负责回复**的两段式架构。

---

## 阶段 B：bridge 侧（2026-07-27 起）

### 2026-07-27 · 三大功能开发 + 回滚（B7，⚠️ 已回滚）

一次性实现了三个功能，**因引入 bug 影响主链路，全部回滚**：

| 功能 | 实现内容 | 结论 |
|------|----------|------|
| 表情包识别与发送 | 新建 `emoji_map.py`（QQ face ID 0~246 → 中文描述），`ob_protocol.py` 处理 `face`/`mface` | ⚠️ 回滚 |
| 群聊白名单 + 按群回复模式 | `group_whitelist` 配置（群名 → mention/all/batch），新增 `get_group_mode()`，替换 7 处模式判断点 | ⚠️ 回滚 |
| 安全防护 | `SECURITY_SYSTEM_PROMPT` 自动注入 + prompt 注入检测 + 敏感输出过滤 | ⚠️ 回滚 |

回滚方式：从上游仓库重新拉取 `ob_protocol.py` / `bridge_core.py` / `state.py` / `config.py` / `main.py` / `web_panel.py` / `config.example.json`，
删除新增的 `emoji_map.py`。**`config.json` 未受影响。**

复盘见 [docs/07-回滚功能复盘.md](docs/07-回滚功能复盘.md)。

### 2026-07-27 · config 缺字段崩溃修复（B1 / B2 / B3，✅ 已生效）

**症状**：桥接启动即崩。

```
Traceback (most recent call last):
  File "main.py", line 17, in <module>
    import config
  File "config.py", line 36, in <module>
    WE_FLOW_SEND_API = config["weflow_send_api"]
KeyError: 'weflow_send_api'
```

**根因**：`config["xxx"]` 是 dict 直接索引（缺键就抛 `KeyError`），而 `config.json` 里没有 `weflow_send_api` 字段。

```python
# ❌ 修复前
WE_FLOW_SEND_API = config["weflow_send_api"]

# ✅ 修复后（缺字段时从 weflow_base_url 拼默认值）
WE_FLOW_SEND_API = config.get("weflow_send_api", f"{WE_FLOW_BASE_URL}/api/v1/messages")
```

同时纠正 `SEND_METHOD` 默认值，使其匹配实际使用的发送方式：

```python
# ❌ 修复前：默认 weflow_api，但实际用 UIA 纯键盘
SEND_METHOD = config.get("send_method", "weflow_api")

# ✅ 修复后
SEND_METHOD = config.get("send_method", "uia")
```

并新增**配置自动初始化**（首次部署不再因缺 `config.json` 而挂）：

```python
if not os.path.exists(CONFIG_FILE):
    if os.path.exists(EXAMPLE_FILE):
        import shutil
        shutil.copy2(EXAMPLE_FILE, CONFIG_FILE)
        print("[配置] 检测到 config.json 不存在，已从 config.example.json 自动创建")
    else:
        raise FileNotFoundError("既没有 config.json，也没有 config.example.json")
```

### 2026-07-27 · UIA 发送器自愈（B4，✅ 已生效）

**症状**：日志里反复出现

```
[ERROR] UIA Sender 未就绪
[INFO] [OB11] 文字已发送至 某群A: 喵呜~！...
```

**根因 1**：`_ensure_window()` 开头写死 `if not self._ready: return False`。
只要**启动瞬间**没抓到微信窗口（最小化到托盘、标题一时不匹配），`_ready` 就永远是 `False`，**后续所有发送永久失败**。

```python
# ❌ 修复前
def _ensure_window(self) -> bool:
    if not self._ready:          # 初始失败 = 终身失败
        return False
    if self._window and self._window.Exists(0.2):
        return True
    self._find_window()
    ...
```

```python
# ✅ 修复后：延迟初始化 —— 每次都尝试重新定位窗口
def _ensure_window(self) -> bool:
    """确保窗口可用（延迟初始化：首次失败后也会重试）"""
    if self._window and self._window.Exists(0.2):
        self._ready = True
        return True
    self._find_window()          # 每次发送前都重试
    if not self._window:
        log.warning("微信窗口未找到，请确保微信已登录并处于打开状态")
        self._ready = False
        return False
    self._ready = True
    log.info(f"微信窗口已重新定位: '{self._window.Name}'")
    return True
```

### 2026-07-27 · 发送结果日志纠偏（B5，✅ 已生效）

**根因 2**：原代码把日志写在返回值判断外面 —— 不管发没发成功都打「已发送」，
所以看到「未就绪」的 ERROR 之后紧跟一句「文字已发送至」，**实际上消息根本没发出去**。

```python
# ❌ 修复前
await asyncio.to_thread(state.sender_instance.send_text, contact, text)
log.info(f"[OB11] 文字已发送至 {contact}: {text[:50]}")

# ✅ 修复后
sent = await asyncio.to_thread(state.sender_instance.send_text, contact, chunk)
if sent:
    log.info(f"[OB11] 文字已发送至 {contact}: {chunk[:50]}")
else:
    log.warning(f"[OB11] 文字发送失败 {contact}: {chunk[:50]}")
```

### 2026-07-29 · 管理员权限插件（B6，✅ 已交付）

产出 AstrBot 插件 `astrbot_plugin_admin_manager`（源码 + 打包 zip），
提供 `/ping`、`/admin`、`/admin add`、`/admin remove`、`/reload`。
权限校验走 AstrBot 原生 `@filter.permission_type(filter.PermissionType.ADMIN)`。
详见 [docs/06-管理员权限插件.md](docs/06-管理员权限插件.md)。

### 2026-07-27 · 图片描述链路梳理（📌 仅供参考）

确认全链路已可用，无需改代码，只需配好参数：

```
微信收到图片
  → WeFlow SSE: {content: "[图片]", sessionId: ...}
  → bridge.add_to_buffer() 识别 [图片]
  → process_image_message()
      ├─ _fetch_wechat_image(sessionId)   从 WeFlow 下载图片到 astrbot_attachments/wechat_images/
      └─ caption_image_via_ollama(path)   视觉模型生成描述（ollama / OpenAI 兼容双后端）
  → 描述文本以 [图片: xxx] 注入缓冲区 → 作为文字消息推给 AstrBot
```

---

## 附：本仓库相对上游源码的改动文件清单

| 文件 | 改动 |
|------|------|
| `bridge/state.py` | `_wxid_to_int` 改用 `zlib.crc32` |
| `bridge/config.py` | `.get()` 兜底、`SEND_METHOD` 默认 `uia`、config 自动初始化 |
| `bridge/ob_protocol.py` | 新增 `_split_long_text` 分段发送；发送结果日志纠偏 |
| `bridge/uia_sender.py` | `_ensure_window` 延迟初始化 / 窗口自愈 |
| `bridge/config.example.json` | 补充 `send_method` / `weflow_send_api` 等字段 |
| `astrbot_plugin_admin_manager/` | 新增（插件） |
