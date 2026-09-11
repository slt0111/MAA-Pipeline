# MAA 挂机助手 · MAA Pipeline

一键完成「**启动 MuMu 模拟器 → 等待安卓就绪 → 拉起 MAA 自动挂机 → 收工关模拟器**」的 Windows 桌面小工具。

带图形界面、实时运行日志、多时间点定时，以及微信 / QQ / 邮件 / Webhook 多通道完成通知。

> 本工具是**调度器**，只负责按顺序启动和监控，不修改 MAA 与 MuMu 本体。
> 仓库**不包含**任何第三方软件安装包，MAA 与 MuMu 需自行安装。

---

## 特性

| | |
|---|---|
| 🎯 **六阶段流水线** | 环境自检 → 启动模拟器 → 等待安卓就绪 → 确认 ADB 通路 → 拉起 MAA → 收尾归档，任一阶段失败即中断 |
| 👥 **多账号顺序挂机** | 同一 MuMu 实例上按列表跑完账号 A 再切账号 B（MAA「开始唤醒」`account_name`），不是多开模拟器并行 |
| 🖥 **原生桌面窗口** | pywebview 套壳，形态与 MAA 类似；关闭窗口即缩到托盘，挂机与定时继续在后台跑 |
| 📋 **实时运行记录** | 界面实时滚动日志，同时按天落盘到 `logs/YYYY-MM-DD.md`，可一键下载 |
| ⏰ **多时间点定时** | 每天可设多个时间点自动挂机（如 `08:00`、`12:30`、`20:00`），可指定星期几 |
| 🔔 **多通道通知** | 桌面气泡 / 邮件 / Server酱 / PushPlus / WxPusher / Qmsg酱 / 自定义 Webhook，支持「测试」按钮即时验证 |
| 🧩 **三种运行模式** | `full` 全流程 / `emu` 只开模拟器 / `maa` 只跑 MAA |
| 🚪 **收工自动关模拟器** | 仅当确认 MAA 报「任务已全部完成」才关闭，中途手动退出 MAA 不会误杀 |
| 🔌 **不污染 MAA 配置** | 每次运行注入独立的「挂机流水线」配置，结束后还原，你原来的 `Default` 配置一个字节都不会动 |
| 📦 **通用安装包** | 自带安装向导 + 卸载器，支持换机路径自动探测，无需管理员权限 |

---

## 界面

![图标](preview.png)

主界面分为三块：左侧运行控制（模式选择、开始 / 中止），中间实时日志流，右侧设置面板（路径、多账号、定时、通知、托盘）。

---

## 快速开始

### 前置条件

| 依赖 | 说明 |
|---|---|
| **MuMu 模拟器 12** | 官网 <https://mumu.163.com/> ，默认安装路径即可 |
| **MAA** | 从 [MAA 官方 Release](https://github.com/MaaAssistantArknights/MaaAssistantArknights/releases) 下载 Windows 版并解压，**至少手动运行一次**完成初始化 |
| **Windows 10/11** | 建议装有 WebView2 运行时（Win11 自带；缺失时程序会自动改用浏览器界面） |

### 方式一：使用安装包（推荐）

在 [Releases](../../releases) 页下载安装包，双击运行：

- **`MAA挂机助手-安装包.exe`**（约 27 MB）—— 不含 MAA 本体，装完后程序首次运行会自动探测已安装的 MAA
- **`MAA挂机助手-安装包-完整版.exe`**（约 285 MB）—— 内置 MAA 本体与挂机配置，装完即用

安装向导会检测 MuMu / WebView2 环境，可选择安装目录（默认 `%LOCALAPPDATA%\MAA-Pipeline`，免管理员），
并自动创建桌面与开始菜单快捷方式。卸载走控制面板「应用」或安装目录下的 `uninstall.exe`。

### 方式二：从源码运行

```bash
git clone <本仓库地址>
cd MAA-Pipeline

# 依赖（仅打包时需要，纯运行只需 Python 标准库）
python -m pip install pywebview pyinstaller pillow

# 直接运行（会自动打开原生窗口）
python pipeline.py

# 环境自检：只检查路径 / MAA 配置 / 模拟器状态，不启动界面
python pipeline.py --selftest
```

首次运行会自动寻找 MuMu 与 MAA 的安装位置并写入配置；找不到时在界面右侧「设置」里手动填路径即可。

### 方式三：自己打包成 exe

```bash
python build_exe.py            # 先自检再打包 → dist\MAA挂机助手.exe（约 13.6 MB）
python make_icon.py --preview  # 重新生成图标 app.ico

python build_installer.py               # 精简版安装包
python build_installer.py --with-maa    # 完整版安装包（内置 MAA）
```

> 打包用的解释器默认取「当前运行脚本的 Python」，需要指定虚拟环境时设环境变量 `MAA_BUILD_PYTHON`。

---

## 工作原理

### 六阶段流水线

| 阶段 | 做什么 | 失败即中断 |
|---|---|---|
| `env` | 校验 MuMu CLI、adb、MAA 是否就位；确认 MAA 未在运行 | ✅ |
| `launch` | `mumu-cli control launch` 启动指定实例 | ✅ |
| `ready` | 轮询 `is_android_started`，最长等待 180 秒，再用 `adb` 校验 `sys.boot_completed=1` | ✅ |
| `adb` | 确认 `127.0.0.1:16384`（= `16384 + 32 × 实例号`）通路正常 | ✅ |
| `maa` | 以 `MAA.exe --config 挂机流水线` 启动，实时镜像日志到界面；一旦出现「任务已全部完成」，等待「关闭延迟」秒后关掉 MAA。配置了多个账号时，会按顺序改写开始唤醒的切号字段、关 MAA、再拉起下一号 | ✅ |
| `wrap` | 归档日志；确认 MAA 报「任务已全部完成」后按设置关闭模拟器实例（可选连 MuMu 管理器一起关） | — |

### 为什么不用改你的 MAA 配置

程序在启动前会往 `MAA\config\gui.new.json` 里**注入一个独立配置**「挂机流水线」
（`RunDirectly = true`，即启动即开始任务），退出后把 `Current` 还原回 `Default`。
改动前会备份为 `gui.new.json.pipeline.bak`，你的原有配置不受影响。

配置了多个账号时，每一号开跑前都会重新注入同一套流水线配置，并把该号的
`account_name` 写进「开始唤醒」任务（以及兼容字段）。这是 MAA 官方支持的切号方式：
只切到**客户端里已经登录过**的账号，用登录名的唯一片段匹配（官服手机号掩码、B 服昵称等）。

### 单实例保护

第二次双击不会起两个程序：新实例会先探测端口，若发现是「自己人」的本地服务，就唤起已有窗口后退出。
（Windows 上 `SO_REUSEADDR` 是端口抢占语义，用它做守卫会失效，因此这里用 `connect` 探测 + 接口身份校验。）

---

## 配置说明

配置文件为程序目录下的 `pipeline_config.json`，界面上的所有设置都保存在这里。主要字段：

```jsonc
{
  "mumu": {
    "cli": "...\\nx_main\\mumu-cli.exe",   // 模拟器命令行工具
    "adb": "...\\nx_main\\adb.exe",
    "vm_index": 0,                          // 实例序号，0 开始
    "ready_timeout": 180,                   // 等待安卓就绪最长时间（秒）
    "shutdown_after_complete": true,        // 挂机完成后关模拟器实例
    "close_manager": true                   // 连 MuMu 管理器窗口一起关掉
  },
  "maa": {
    "exe": "...\\MAA\\MAA.exe",
    "profile": "挂机流水线",                 // 运行时注入的配置名
    "mirror_logs": true,                    // 把 MAA 日志镜像到界面
    "close_after_complete": true,           // 报「任务已全部完成」后自动关掉 MAA
    "close_delay": 10,                      // 关闭前的宽限秒数
    "accounts": [                           // 可空：空/未填 = 单账号，行为与以前相同
      {"name": "官服主号", "account_name": "4567", "enabled": true},
      {"name": "B服小号", "account_name": "张三", "enabled": true}
    ]
  },
  "schedule": {
    "enabled": true,
    "times": ["08:00", "12:30", "20:00"],   // 每天多个时间点
    "days": [0, 1, 2, 3, 4, 5, 6],          // 0=周一
    "only_if_idle": true                    // 正在跑就跳过本次
  },
  "notify": {
    "desktop": true,                         // 桌面气泡（默认开）
    "serverchan": { "enabled": false, "sendkey": "" },
    "pushplus":   { "enabled": false, "token": "" },
    "wxpusher":   { "enabled": false, "app_token": "", "uids": "" },
    "qmsg":       { "enabled": false, "key": "", "qq": "", "type": "send" },
    "email":      { "enabled": false, "smtp_host": "", "smtp_port": 465,
                    "use_ssl": true, "username": "", "password": "", "to": "" },
    "webhook":    { "enabled": false, "url": "", "format": "通用 JSON" }
  },
  "tray": { "enabled": true }
}
```

各通知渠道的申请与填写方式见 **[docs/使用说明.md](docs/使用说明.md#通知渠道配置)**。

---

## 目录结构

```
MAA-Pipeline/
├── pipeline.py            # 主程序：HTTP 服务 + 流水线引擎 + 定时器 + 托盘 + 通知
├── ui.html                # 界面（SSE 实时推日志与状态）
├── installer.py           # 通用安装器（安装向导 + 卸载逻辑）
├── installer_ui.html      # 安装向导界面
├── build_exe.py           # 一键打包主程序 exe
├── build_installer.py     # 一键生成安装包（安装器 exe + 尾部附加 payload.zip）
├── make_icon.py           # 生成多尺寸 app.ico
├── make_shortcut.py       # 创建桌面快捷方式（ctypes 直调 IShellLink）
├── version_info.py        # exe 版本信息（PyInstaller --version-file）
├── start-pipeline.vbs     # 备用启动器（源码方式，静默启动）
├── tools_pe_icon_check.py # 诊断：检查 exe 内嵌图标帧格式
├── tools_icon_extract.py  # 诊断：把 exe/ico 里的图标导出成 PNG 查看
├── test_installer.py      # 回归：安装逻辑装到临时目录验证
├── test_installer_gui.py  # 回归：验证安装向导窗口能正常弹出
└── tests/                 # 单元测试：调度 / 通知 / HTTP 接口 / 界面配置回填 / 多账号切号
```

---

## 常见问题

**Q：提示找不到模拟器 / MAA？**
程序会按常见安装位置自动探测（各盘符的 `Program Files\Netease`、`MAA` 等）。探测不到就在界面「设置」里手动填绝对路径。
MuMu 的具体路径一般是 `<安装盘>\Program Files\Netease\MuMu\nx_main\`。

**Q：挂机没开始就结束了？**
检查 MAA 目录下 `debug\asst.log`。常见原因是 MAA 首次运行尚未初始化（手动启动一次 MAA 完成初始化），
或模拟器实例序号填错（多开时第 2 个实例是 `1`，对应端口 `16416`）。

**Q：exe 图标是空白？**
那是历史版本的图标编码问题，v1.2.0 已修复（小尺寸改用 DIB 帧）。若仍显示旧图标，刷新一下图标缓存或重启资源管理器。

**Q：换台电脑还能用吗？**
可以。程序所有路径基于自身所在目录和自动探测，不写死安装位置。用安装包分发最省事。

**Q：为什么窗口关了程序还在跑？**
这是设计如此——关窗等于最小化到托盘，定时任务继续在后台生效。要真正退出请用托盘菜单或界面里的「退出程序」。

**Q：怎么一次挂多个账号？**
在设置里「多账号」添加账号，填显示名和 MAA 能用来匹配的登录名片段，保持启用，保存后再点一键挂机。
**前提**：这些号必须已经在该模拟器的客户端里登录过；本工具不会帮你输入密码。
同一实例上顺序执行：A 报「任务已全部完成」→ 关 MAA → 切到 B 再拉起。某一号没跑完会**立刻停**，后面的号不跑，模拟器也按保护机制保留。
列表留空或只留一个号，行为和以前的单账号完全一样。

---

## 免责声明

- 本项目是第三方辅助工具，**与 MAA、MuMu 官方无关**，未获得其背书。
- 请遵守《明日方舟》用户协议及相关平台规则，自行承担使用风险。
- 仓库内不含任何游戏本体、第三方程序安装包或破解内容，仅提供调度与界面代码。

## 致谢

- [MaaAssistantArknights](https://github.com/MaaAssistantArknights/MaaAssistantArknights) —— 明日方舟小助手
- [MuMu 模拟器](https://mumu.163.com/) —— 安卓模拟器
- [pywebview](https://pywebview.flowrl.com/) · [PyInstaller](https://pyinstaller.org/) —— 窗口与打包

## 许可

[MIT](LICENSE)
