# -*- coding: utf-8 -*-
"""macOS 菜单栏托盘：优先 AppKit（pywebview 在 Mac 上通常已带 pyobjc）。

不调用独立的 rumps/pystray 事件循环，避免和 pywebview 的 Cocoa runloop 抢主线程。
菜单项与 Windows 对齐，并多一个「中止」。
"""

from __future__ import annotations

MENU_SHOW = "显示主界面"
MENU_RUN = "立即挂机"
MENU_ABORT = "中止"
MENU_QUIT = "退出"


def tray_backend_available() -> str | None:
    """返回将使用的后端名，都不可用则 None。"""
    try:
        import AppKit  # noqa: F401
        return "appkit"
    except Exception:
        pass
    try:
        import rumps  # noqa: F401
        return "rumps"
    except Exception:
        pass
    try:
        import pystray  # noqa: F401
        return "pystray"
    except Exception:
        return None


class MacStatusTray:
    """菜单栏图标。hooks: open / run / abort / quit / notify_fallback。"""

    def __init__(self, hooks: dict):
        self.hooks = dict(hooks or {})
        self.active = False
        self.backend = None
        self._item = None
        self._target = None
        self._rumps_app = None

    def start(self):
        kind = tray_backend_available()
        if kind == "appkit":
            self._start_appkit()
        elif kind == "rumps":
            self._start_rumps()
        elif kind == "pystray":
            self._start_pystray()
        else:
            raise RuntimeError("没有可用的 macOS 托盘后端（需要 pyobjc / rumps / pystray）")
        self.backend = kind
        self.active = True

    def notify(self, title: str, body: str):
        fn = self.hooks.get("notify_fallback")
        if callable(fn):
            try:
                fn(title, body)
                return
            except Exception:
                pass
        try:
            from plat.macos import MacOSPlatform
            MacOSPlatform().desktop_notify(title, body)
        except Exception:
            pass

    def stop(self):
        try:
            if self.backend == "appkit" and self._item is not None:
                from AppKit import NSStatusBar
                NSStatusBar.systemStatusBar().removeStatusItem_(self._item)
        except Exception:
            pass
        try:
            if self._rumps_app is not None:
                self._rumps_app.quit()
        except Exception:
            pass
        self.active = False

    # ---------- AppKit ----------

    def _start_appkit(self):
        from AppKit import (  # type: ignore
            NSApplication,
            NSMenu,
            NSMenuItem,
            NSStatusBar,
            NSVariableStatusItemLength,
        )
        from Foundation import NSObject  # type: ignore

        NSApplication.sharedApplication()

        hooks = self.hooks

        class _Target(NSObject):
            def show_(self, _sender):
                _call(hooks, "open")

            def run_(self, _sender):
                _call(hooks, "run")

            def abort_(self, _sender):
                _call(hooks, "abort")

            def quit_(self, _sender):
                _call(hooks, "quit")

        # 必须挂在实例上，防止 ObjC 回调时 Python 对象被回收
        self._target = _Target.alloc().init()
        menu = NSMenu.alloc().init()
        pairs = (
            (MENU_SHOW, "show:"),
            (MENU_RUN, "run:"),
            (MENU_ABORT, "abort:"),
            (None, None),
            (MENU_QUIT, "quit:"),
        )
        for title, action in pairs:
            if title is None:
                menu.addItem_(NSMenuItem.separatorItem())
                continue
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, "")
            item.setTarget_(self._target)
            menu.addItem_(item)

        bar = NSStatusBar.systemStatusBar()
        self._item = bar.statusItemWithLength_(NSVariableStatusItemLength)
        self._item.setTitle_("MAA")
        self._item.setToolTip_("MAA 一键挂机")
        self._item.setMenu_(menu)

    def _start_rumps(self):
        import rumps  # type: ignore

        hooks = self.hooks

        class _App(rumps.App):
            @rumps.clicked(MENU_SHOW)
            def show(self, _):
                _call(hooks, "open")

            @rumps.clicked(MENU_RUN)
            def run_now(self, _):
                _call(hooks, "run")

            @rumps.clicked(MENU_ABORT)
            def abort(self, _):
                _call(hooks, "abort")

            @rumps.clicked(MENU_QUIT)
            def quit_app(self, _):
                _call(hooks, "quit")

        self._rumps_app = _App("MAA", quit_button=None)
        # 不调用 run()：pywebview 已经占着 Cocoa 主循环，只创建状态项
        try:
            self._rumps_app.status_bar_item  # rumps 1.x 在 init 后即可用
        except Exception:
            pass

    def _start_pystray(self):
        import threading
        import pystray  # type: ignore
        from PIL import Image, ImageDraw

        hooks = self.hooks
        image = Image.new("RGB", (16, 16), "#185FA5")
        draw = ImageDraw.Draw(image)
        draw.rectangle((3, 3, 12, 12), fill="#F5F4F0")

        menu = pystray.Menu(
            pystray.MenuItem(MENU_SHOW, lambda *_: _call(hooks, "open"), default=True),
            pystray.MenuItem(MENU_RUN, lambda *_: _call(hooks, "run")),
            pystray.MenuItem(MENU_ABORT, lambda *_: _call(hooks, "abort")),
            pystray.MenuItem(MENU_QUIT, lambda *_: _call(hooks, "quit")),
        )
        icon = pystray.Icon("maa-pipeline", image, "MAA 一键挂机", menu)
        self._item = icon
        threading.Thread(target=icon.run, daemon=True).start()


def _call(hooks: dict, key: str):
    fn = (hooks or {}).get(key)
    if callable(fn):
        fn()


def menu_labels() -> list:
    return [MENU_SHOW, MENU_RUN, MENU_ABORT, MENU_QUIT]
