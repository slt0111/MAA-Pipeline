# MAA 挂机助手 · MAA Pipeline

一键完成「**启动 MuMu 模拟器 → 等待安卓就绪 → 拉起 MAA 自动挂机 → 收工关模拟器**」的桌面小工具。

同一仓库同时支持 **Windows** 与 **macOS**。界面以 **pywebview 原生桌面窗口**为主（与 Windows 相同），仅在 WebView 不可用时退回浏览器。带实时运行日志、多账号顺序挂机、多时间点定时，以及微信 / QQ / 邮件 / Webhook 多通道完成通知。

> 本工具是**调度器**，只负责按顺序启动和监控，不修改 MAA 与 MuMu 本体。
> 仓库**不包含**任何第三方软件安装包，MAA 与 MuMu 需自行安装。平台差异集中在 `plat/`，流水线逻辑共用。

---

## 特性

| | |
|---|---|
| 🎯 **六阶段流水线** | 环境自检 → 启动模拟器 → 等待安卓就绪 → 确认 ADB 通路 → 拉起 MAA → 收尾归档，任一阶段失败即中断 |
| 👥 **多账号顺序挂机** | 同一 MuMu 实例上按列表跑完账号 A 再切账号 B（MAA「开始唤醒」`account_name`），不是多开模拟器并行 |
| 🖥 **原生桌面窗口** | pywebview 套壳，形态与 MAA 类似；关闭窗口即缩到托盘 / 菜单栏，挂机与定时继续跑；二次启动唤起已有实例 |
| 📋 **实时运行记录** | 界面实时滚动日志，同时按天落盘到 `logs/YYYY-MM-DD.md`，可一键下载 |
| ⏰ **多时间点定时** | 每天可设多个时间点自动挂机（如 `08:00`、`12:30`、`20:00`），可指定星期几 |
| 🔔 **多通道通知** | 桌面气泡 / 邮件 / Server酱 / PushPlus / WxPusher / Qmsg酱 / 自定义 Webhook，支持「测试」按钮即时验证 |
| 🧩 **三种运行模式** | `full` 全流程 / `emu` 只开模拟器 / `maa` 只跑 MAA |
| 🚪 **收工自动关模拟器** | 仅当确认 MAA 报「任务已全部完成」才关闭，中途手动退出 MAA 不会误杀 |
| 🔌 **不污染 MAA 配置** | 每次运行注入独立的「挂机流水线」配置，结束后还原，你原来的 `Default` 配置一个字节都不会动 |
| 📦 **安装包** | Windows：安装向导 + 卸载器。macOS：在 Mac 上运行 `python3 build_dmg.py` 生成 `MAA挂机助手.app` / `.dmg`（不附带 MuMu / MAA；签名与公证可选） |

---

## 界面

![图标](preview.png)

主界面分为三块：左侧运行控制（模式选择、开始 / 中止），中间实时日志流，右侧设置面板（路径、多账号、定时、通知、托盘）。

---

## 快速开始

### 前置条件（Windows）

| 依赖 | 说明 |
|---|---|
| **MuMu 模拟器 12** | 官网 <https://mumu.163.com/> ，默认安装路径即可 |
| **MAA** | 从 [MAA 官方 Release](https://github.com/MaaAssistantArknights/MaaAssistantArknights/releases) 下载 Windows 版并解压，**至少手动运行一次**完成初始化 |
| **Windows 10/11** | 建议装有 WebView2 运行时（Win11 自带；缺失时程序会自动改用浏览器界面） |

### 前置条件（macOS）

| 依赖 | 说明 |
|---|---|
| **MuMu 模拟器（macOS）** | 官网 <https://mumu.163.com/mac/> ，**1.5.4+**（需带开发者命令行 `mumutool`）。菜单：开发者 → 打开命令行工具 / 打开 ADB。说明：<https://www.mumuplayer.com/help/mac/developer-support-function.html> |
| **MAA.app**（推荐） | [官方 Release](https://github.com/MaaAssistantArknights/MaaAssistantArknights/releases) 的 macOS 包，或 `brew install --cask maa`。**至少手动打开一次**以生成 `gui.new.json`。本工具按与 Windows 相同的方式注入「挂机流水线」并用 `--config` 拉起 |
| **maa-cli**（备选） | `brew install MaaAssistantArknights/tap/maa-cli`。能跑通 `full` / 自检；多账号同样写入 StartUp `account_name`（`tasks/pipeline_farm.json`），失败跳过仍有效。能装 MAA.app 时请优先走 GUI |
| **Python 3.10+** | `python3 -m pip install -r requirements-macos.txt`（`pywebview` + Cocoa 菜单栏托盘）。没有 WebView 时自动 `--browser` |

ADB 端口**不是** `16384 + 32 × 索引`，请留空让程序读 `mumutool info`，或在设置里填菜单「打开 ADB」显示的地址（例如 `127.0.0.1:26624`）。

**桌面体验**：默认打开 pywebview 窗口（与 Windows 相同）。点关闭 = 隐藏到菜单栏，进程继续跑定时 / 挂机。托盘菜单：显示主界面 / 立即挂机 / 中止 / 退出。第二次启动会唤起已有实例。仅当 WebView / pywebview 不可用时才打开浏览器。

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

# 依赖（原生窗口需要 pywebview）
python3 -m pip install pywebview
# macOS 桌面窗口 + 菜单栏托盘：
#   python3 -m pip install -r requirements-macos.txt
# Windows 打包另需：pyinstaller pillow

# 直接运行（会自动打开原生窗口）
python3 pipeline.py
# macOS / Linux 也可用：
#   chmod +x start-pipeline.sh && ./start-pipeline.sh

# 环境自检：只检查路径 / MAA 配置 / 模拟器状态，不启动界面
python3 pipeline.py --selftest
```

首次运行会按**当前操作系统**自动寻找 MuMu 与 MAA 的安装位置并写入配置；找不到时在界面右侧「设置」里手动填路径即可。已有的 `pipeline_config.json` 不会被 Mac 默认路径覆盖。

### 方式三：自己打包（Windows exe / macOS dmg）

```bash
# Windows
python build_exe.py            # 先自检再打包 → dist\MAA挂机助手.exe（约 13.6 MB）
python make_icon.py --preview  # 重新生成图标 app.ico
python build_installer.py               # 精简版安装包
python build_installer.py --with-maa    # 完整版安装包（内置 MAA）

# macOS（必须在 Mac 上执行；Linux CI 只能 --check / --dry-run）
python3 -m pip install -r requirements-macos.txt pyinstaller
python3 build_dmg.py           # → dist/MAA挂机助手.app 与 dist/MAA挂机助手.dmg
# 或：chmod +x scripts/build_dmg.sh && ./scripts/build_dmg.sh
python3 build_dmg.py --check   # 任意平台：检查脚本完整性
```

`.dmg` **不附带** MuMu / MAA，需本机已安装。默认打**未签名**包；若要 codesign，设置环境变量 `MAA_CODESIGN_ID`（Developer ID Application: …）。**公证（notarytool）本脚本不提交**，需要 Apple 开发者账号时请自行 `xcrun notarytool submit`。Gatekeeper 可能拦截未签名应用：右键「打开」，或在系统设置里放行。

> 打包用的解释器默认取「当前运行脚本的 Python」，需要指定虚拟环境时设环境变量 `MAA_BUILD_PYTHON`。

---

## 工作原理

### 六阶段流水线

| 阶段 | 做什么 | 失败即中断 |
|---|---|---|
| `env` | 校验 MuMu CLI、adb、MAA 是否就位；确认 MAA 未在运行 | ✅ |
| `launch` | Windows：`mumu-cli control launch`；Mac：`mumutool open <索引>` | ✅ |
| `ready` | 轮询规范化后的 `is_android_started`，最长等待 180 秒 | ✅ |
| `adb` | Windows：`127.0.0.1:16384`（= `16384 + 32 × 实例号`）；Mac：读 `mumutool info` 的端口或你填的地址 | ✅ |
| `maa` | GUI：`MAA --config 挂机流水线`；maa-cli：`maa -p pipeline run pipeline_farm`。两套后端都按账号写入 StartUp `account_name`。实时镜像日志；「任务已全部完成」后按延迟关 MAA（cli 则进程自行退出）。单号失败跳过 | 单号跳过 |
| `wrap` | 归档日志；确认 MAA 报「任务已全部完成」后按设置关闭模拟器实例（可选连 MuMu 管理器一起关） | — |

### 为什么不用改你的 MAA 配置

程序在启动前会往 `MAA\config\gui.new.json` 里**注入一个独立配置**「挂机流水线」
（`RunDirectly = true`，即启动即开始任务），退出后把 `Current` 还原回 `Default`。
改动前会备份为 `gui.new.json.pipeline.bak`，你的原有配置不受影响。

配置了多个账号时，每一号开跑前都会重新注入同一套流水线配置，并把该号的
`account_name` 写进「开始唤醒」任务（以及兼容字段）。这是 MAA 官方支持的切号方式：
只切到**客户端里已经登录过**的账号，用登录名的唯一片段匹配（官服手机号掩码、B 服昵称等）。

**两条 MAA 后端都会切号**（失败跳过同样生效）：

| 后端 | 何时使用 | 切号怎么写 |
|---|---|---|
| **GUI**（`MAA.exe` / `MAA.app`） | Windows 默认；Mac 探测到 `.app` 时优先 | `gui.new.json` 的开始唤醒 `AccountName` |
| **maa-cli**（`maa` / `maa-cli`） | Mac 只装了 Homebrew maa-cli，或设置里把主程序指到 `maa` | `$MAA_CONFIG_DIR/tasks/pipeline_farm.json` 的 `StartUp.params.account_name`，连接写在 `profiles/pipeline.json` |

maa-cli 配置目录优先级：设置里的「maa-cli 配置目录」→ 环境变量 `MAA_CONFIG_DIR` → `maa dir config` → `~/Library/Application Support/com.loong.maa/config` 或 `~/.config/maa`。

### 单实例保护

第二次双击不会起两个程序：新实例会先探测端口，若发现是「自己人」的本地服务，就唤起已有窗口后退出。
（Windows 上 `SO_REUSEADDR` 是端口抢占语义，用它做守卫会失效，因此这里用 `connect` 探测 + 接口身份校验。）

---

## 配置说明

配置文件为程序目录下的 `pipeline_config.json`，界面上的所有设置都保存在这里。主要字段：

```jsonc
{
  "mumu": {
    "cli": "...\\nx_main\\mumu-cli.exe",   // Windows: mumu-cli.exe；Mac: mumutool
    "adb": "...\\nx_main\\adb.exe",        // Mac 常见 /opt/homebrew/bin/adb 或模拟器自带
    "vm_index": 0,                          // 实例序号，0 开始
    "ready_timeout": 180,                   // 等待安卓就绪最长时间（秒）
    "shutdown_after_complete": true,        // 挂机完成后关模拟器实例
    "close_manager": true                   // 连 MuMu 管理器窗口一起关掉
  },
  "maa": {
    "exe": "...\\MAA\\MAA.exe",          // Mac: /Applications/MAA.app 或 maa-cli
    "profile": "挂机流水线",                 // GUI 注入的配置名（cli 固定用 pipeline）
    "cli_config_dir": "",                   // maa-cli 配置目录，留空自动探测
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
├── plat/                  # 平台适配：路径 / 模拟器 / ADB / MAA 进程 / 窗口
│   ├── windows.py
│   ├── macos.py
│   ├── linux.py           # CI 用，不驱动真实模拟器
│   ├── maa_cli.py         # maa-cli 切号与 pipeline_farm 任务
│   └── tray_macos.py      # macOS 菜单栏托盘（AppKit / rumps / pystray）
├── ui.html                # 界面（SSE 实时推日志与状态）
├── start-pipeline.sh      # macOS / Linux 源码启动
├── build_dmg.py           # macOS：PyInstaller .app + hdiutil .dmg
├── scripts/build_dmg.sh   # 同上的薄封装
├── requirements-macos.txt # Mac 源码 / 托盘依赖
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
程序会按当前操作系统的常见安装位置自动探测。Windows：各盘符的 `Program Files\Netease`、`MAA` 等。macOS：`/Applications/MuMuPlayer.app` 里的 `mumutool`、`/Applications/MAA.app`、Homebrew 的 `maa`。探测不到就在界面「设置」里手动填绝对路径。

**Q：Mac 上 ADB 连不上？**
不要套用 Windows 的 `16384 + 32 × 索引`。在 MuMu 菜单「开发者 → 打开 ADB」看端口，填到设置的「ADB 地址」，或留空让程序读 `mumutool info`。文档：<https://www.mumuplayer.com/help/mac/connect-adb.html>

**Q：挂机没开始就结束了？**
检查 MAA 目录下 `debug\asst.log`。常见原因是 MAA 首次运行尚未初始化（手动启动一次 MAA 完成初始化），
或模拟器实例序号填错（多开时第 2 个实例是 `1`，对应端口 `16416`）。

**Q：exe 图标是空白？**
那是历史版本的图标编码问题，v1.2.0 已修复（小尺寸改用 DIB 帧）。若仍显示旧图标，刷新一下图标缓存或重启资源管理器。

**Q：换台电脑还能用吗？**
可以。程序所有路径基于自身所在目录和自动探测，不写死安装位置。用安装包分发最省事。

**Q：为什么窗口关了程序还在跑？**
这是设计如此——关窗后挂机与定时继续在后台生效。Windows 缩到托盘；macOS 缩到菜单栏（需 `pyobjc-framework-Cocoa`，打进 `.app` 后自带）。再次运行会唤起已有实例。要真正退出请用界面「退出程序」或托盘 / 菜单栏里的「退出」。

**Q：Mac 和 Windows 差在哪？**
同一套阶段 / 多账号 / 定时 / 通知 / 原生窗口。Mac 用 `mumutool`（不是 `mumu-cli.exe`），MAA 优先走官方 GUI + `gui.new.json` 注入（连接配置 `CompatMac`）；若主程序指到 `maa` 则走 maa-cli，**同样按账号切号**。dmg 需在 Mac 上用 `build_dmg.py` 生成（本仓库的 Linux 构建机打不出签名包）。不要把 Windows 的 `pipeline_config.json` 原样拷到 Mac（路径无效）；程序会在路径失效时重新探测。

**Q：怎么一次挂多个账号？**
在设置里「多账号」添加账号，填显示名和 MAA 能用来匹配的登录名片段，保持启用，保存后再点一键挂机。
**前提**：这些号必须已经在该模拟器的客户端里登录过；本工具不会帮你输入密码。
同一实例上顺序执行：A 报「任务已全部完成」→ 关 MAA → 切到 B 再拉起。某一号没跑完会**记失败并继续下一号**；全部号都跑完后汇总「完成 N/M，失败：…」。有失败则整轮不算成功，模拟器也按保护机制保留。点「中止」仍会停掉整轮。上一号的 MAA 关不掉时无法切号，会短重试后整轮失败。
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
