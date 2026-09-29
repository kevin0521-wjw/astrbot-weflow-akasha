# 05 · UIA 发送器与稳定性修复

发送方式是 **UIA 纯键盘模拟**（Windows UI Automation + 剪贴板），不走 WeFlow 的发送 API。

## 发送流程

```
send_text(contact, text)
  ├─ 加锁（self._lock）—— 全局串行，避免并发操作剪贴板/窗口
  ├─ _ensure_window()        确保能定位到微信窗口
  ├─ _activate()             把微信窗口切到前台
  ├─ 剪贴板写入 text
  ├─ Ctrl+F → 输入 contact → Enter   进入目标会话
  ├─ Ctrl+V → Enter                  粘贴并发送
  └─ return True / False
```

## Bug 1：`UIA Sender 未就绪` —— 一次失败 = 终身失败

### 症状

```
[OB11] API: send_group_msg echo={'seq': 10}
[OB11] 已回响应: send_group_msg
[ERROR] UIA Sender 未就绪
[INFO] [OB11] 文字已发送至 某群A: 喵呜~！你好呀～！
```

注意矛盾之处：**一边报「未就绪」，一边说「已发送」**——实际消息根本没发出去（第二个 bug，见下）。

### 根因

```python
# ❌ 修复前
def _ensure_window(self) -> bool:
    """确保窗口可用"""
    if not self._ready:                 # ← 启动时没抓到窗口，_ready 就永远 False
        return False
    if self._window and self._window.Exists(0.2):
        return True
    self._find_window()
    if not self._window:
        log.warning("微信窗口未找到")
        self._ready = False
        return False
    return True
```

`_ready` 是**一次性初始化**结果：只要**进程启动瞬间**没匹配到微信窗口，
（例如微信最小化到托盘、窗口标题与 `WECHAT_TITLES` 关键词不匹配、微信还没完全起来），
后续**每一次发送都会直接 `return False`**，再也不会重试 —— 表现为「永远发不出消息」。

### 修复：延迟初始化 + 窗口自愈

```python
# ✅ 修复后
def _ensure_window(self) -> bool:
    """确保窗口可用（延迟初始化：首次失败后也会重试）"""
    # 如果窗口已知且仍存在 → OK
    if self._window and self._window.Exists(0.2):
        self._ready = True
        return True
    # 尝试重新查找窗口（首次初始化失败后也能恢复）
    self._find_window()
    if not self._window:
        log.warning("微信窗口未找到，请确保微信已登录并处于打开状态")
        self._ready = False
        return False
    self._ready = True
    log.info(f"微信窗口已重新定位: '{self._window.Name}'")
    return True
```

要点：
- **不再用 `_ready` 做门禁**，改为「先看缓存的窗口句柄还在不在」；
- 句柄失效/不存在 → **每次都重新 `_find_window()`**；
- 一旦找回，把 `_ready` 置回 `True` 并打一条 `微信窗口已重新定位: '<窗口标题>'`，便于确认自愈是否发生。

同样地，`send_image` 里原本写死的 `if not self._ready: return False` 也一并去掉，统一走 `_ensure_window()`。

## Bug 2：日志「假成功」误导排查

### 根因

```python
# ❌ 修复前
await asyncio.to_thread(state.sender_instance.send_text, contact, text)
log.info(f"[OB11] 文字已发送至 {contact}: {text[:50]}")   # 无视返回值，永远打 INFO
```

日志写在返回值判断**外面**，所以：
- 实际返回 `False`（没发出去）→ 日志照样打 `已发送`；
- 于是出现「ERROR 未就绪」+「INFO 已发送」并存的诡异画面，**把排查方向带偏**。

### 修复

```python
# ✅ 修复后
sent = await asyncio.to_thread(state.sender_instance.send_text, contact, chunk)
if sent:
    log.info(f"[OB11] 文字已发送至 {contact}: {chunk[:50]}")
else:
    log.warning(f"[OB11] 文字发送失败 {contact}: {chunk[:50]}")
```

`图片已发送` 同理。

> **教训**：只要日志与实际动作之间夹了「无条件语句」，日志就可能变成谎言。
> 凡是「已发送 / 已完成」这类结论性日志，必须挂在真实返回值上。

## 排查清单

| 现象 | 检查 |
|------|------|
| 持续 `UIA Sender 未就绪` | 微信是否登录？窗口是否被最小化到托盘？`WECHAT_TITLES` 关键词是否匹配当前版本窗口标题？ |
| 偶发失败后自动恢复 | 正常，说明自愈生效（日志可见 `微信窗口已重新定位`） |
| 日志说发了但微信没收到 | 搜 `文字发送失败`；确认发送期间微信窗口没被手动切走 |
| 发到错误的会话 | `Ctrl+F` 搜索命中同名/相似联系人；建议 contact 用较完整名称 |
| 首次运行必须预热 | 手动在微信里 `Ctrl+F` 搜索目标群 2~3 次使其进入搜索候选，可提高命中率 |

## 运行前提（务必确认）

1. PC 微信**已登录**，且窗口能被 UIA 识别（不要只留托盘图标）；
2. 运行期间尽量**不要同时手动操作微信**（会抢焦点）；
3. 端口/进程无冲突：`bridge.pid` 存在且进程存活时，`main.py` 会拒绝二次启动。
