import json
from datetime import datetime
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .collection import CollectionError, list_platforms, open_platform_login, worker_entry
from .diagnostics import configure_logging, export_diagnostics, record_event
from .engine import Cancelled, JobRunner
from .models import PLATFORMS, Settings
from .runtime import default_runtime_paths
from .runtime_update import install_runtime_zip, RuntimePackageError


APP_DIR = Path.home() / ".fast-p"
SETTINGS_FILE = APP_DIR / "settings.json"
MODE_NAMES = {
    "collect": "只采集",
    "screenshot": "只截图",
    "all": "采集并截图",
}


def default_settings():
    runtime = default_runtime_paths()
    return {
        **runtime,
        "chrome_profile": os.environ.get("CHROME_PROFILE") or str(Path.home() / ".fast-scrape-cli" / "chrome-profile"),
        "output": str(Path.home() / "Desktop" / "比价截图"),
        "platforms": [platform for platform, _ in PLATFORMS],
    }


def load_settings():
    settings = default_settings()
    try:
        settings.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        pass
    return settings


def save_settings(settings):
    APP_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


class FastPApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Fast-P 比价截图工具")
        self.geometry("900x680")
        self.minsize(780, 600)
        self.events = queue.Queue()
        self.cancel_event = threading.Event()
        self.worker = None
        self.last_output = None
        self.last_error = ""
        self.logger = configure_logging(APP_DIR)
        settings = load_settings()
        try:
            self.available_platforms = list_platforms(settings["node"], settings["fast_cli"])
        except CollectionError as exc:
            self.available_platforms = PLATFORMS
            self.logger.warning("读取 fast-cli 平台列表失败，使用内置列表：%s", exc)
        self.platform_names = dict(self.available_platforms)

        self.excel = tk.StringVar()
        self.output = tk.StringVar(value=settings["output"])
        self.node = tk.StringVar(value=settings["node"])
        self.fast_cli = tk.StringVar(value=settings["fast_cli"])
        self.chrome = tk.StringVar(value=settings["chrome"])
        self.chrome_profile = tk.StringVar(value=settings["chrome_profile"])
        selected = set(settings.get("platforms", []))
        self.platforms = {
            platform: tk.BooleanVar(value=platform in selected)
            for platform, _ in self.available_platforms
        }
        self.status = tk.StringVar(value="请选择 Excel 并检查运行环境")
        self._build()
        self.logger.info("Fast-P 已启动")
        self.after(100, self._poll_events)

    def _build(self):
        root = ttk.Frame(self, padding=18)
        root.pack(fill="both", expand=True)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(9, weight=1)

        ttk.Label(root, text="比价截图任务", font=("Microsoft YaHei UI", 18, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 16)
        )
        self._path_row(root, 1, "Excel 文件", self.excel, self._choose_excel)
        self._path_row(root, 2, "输出目录", self.output, self._choose_output)
        self._path_row(root, 3, "fast-cli 目录", self.fast_cli, self._choose_fast_cli)
        self._path_row(root, 4, "Node", self.node, lambda: self._choose_file(self.node))
        self._path_row(root, 5, "Chrome", self.chrome, lambda: self._choose_file(self.chrome))
        self._path_row(root, 6, "Chrome Profile", self.chrome_profile, self._choose_profile)

        ttk.Label(root, text="平台（按下列顺序优先）").grid(row=7, column=0, sticky="nw", pady=10)
        self.platform_frame = ttk.Frame(root)
        self.platform_frame.grid(row=7, column=1, columnspan=2, sticky="w", pady=10)
        self._draw_platforms()

        action_frame = ttk.Frame(root)
        action_frame.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(4, 12))
        self.start_buttons = []
        for mode, label in MODE_NAMES.items():
            button = ttk.Button(action_frame, text=label, command=lambda value=mode: self._start(value))
            button.pack(side="left", padx=(0, 8))
            self.start_buttons.append(button)
        self.cancel_button = ttk.Button(action_frame, text="取消", command=self._cancel, state="disabled")
        self.cancel_button.pack(side="left")
        self.open_button = ttk.Button(action_frame, text="打开导出目录", command=self._open_output, state="disabled")
        self.open_button.pack(side="left", padx=8)
        ttk.Button(action_frame, text="登录平台", command=self._login_platforms).pack(side="left")
        ttk.Button(action_frame, text="导出诊断包", command=self._export_diagnostics).pack(side="right")
        ttk.Button(action_frame, text="更新 fast-cli", command=self._import_fast_cli).pack(side="right", padx=8)

        progress_frame = ttk.Frame(root)
        progress_frame.grid(row=9, column=0, columnspan=3, sticky="nsew")
        progress_frame.columnconfigure(0, weight=1)
        progress_frame.rowconfigure(2, weight=1)
        ttk.Label(progress_frame, textvariable=self.status).grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(progress_frame, mode="determinate")
        self.progress.grid(row=1, column=0, sticky="ew", pady=(6, 10))
        self.log = tk.Text(progress_frame, height=18, state="disabled", wrap="word")
        self.log.grid(row=2, column=0, sticky="nsew")
        ttk.Label(
            progress_frame,
            text="提示：只截图时，Excel 需要包含“商品链接”列，不需要选择平台或 fast-cli。",
        ).grid(row=3, column=0, sticky="w", pady=(6, 0))

    def _draw_platforms(self):
        for child in self.platform_frame.winfo_children():
            child.destroy()
        for index, (platform, name) in enumerate(self.available_platforms):
            ttk.Checkbutton(
                self.platform_frame,
                text=f"{index + 1}. {name}",
                variable=self.platforms[platform],
            ).grid(row=index // 6, column=index % 6, sticky="w", padx=(0, 12), pady=2)

    def _refresh_platforms(self):
        selected = set(self._selected_platforms())
        try:
            available = list_platforms(self.node.get().strip(), self.fast_cli.get().strip())
        except CollectionError as exc:
            messagebox.showerror("平台列表读取失败", str(exc))
            return False
        self.available_platforms = available
        self.platform_names = dict(available)
        self.platforms = {
            platform: tk.BooleanVar(value=platform in selected)
            for platform, _ in available
        }
        self._draw_platforms()
        return True

    @staticmethod
    def _path_row(parent, row, label, variable, command):
        ttk.Label(parent, text=label, width=16).grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=(0, 8), pady=4)
        ttk.Button(parent, text="选择", command=command).grid(row=row, column=2, pady=4)

    def _choose_excel(self):
        path = filedialog.askopenfilename(filetypes=[("Excel", "*.xlsx *.xlsm"), ("所有文件", "*.*")])
        if path:
            self.excel.set(path)
            if not self.output.get():
                self.output.set(str(Path(path).parent / "比价截图"))

    def _choose_output(self):
        path = filedialog.askdirectory()
        if path:
            self.output.set(path)

    def _choose_profile(self):
        path = filedialog.askdirectory()
        if path:
            self.chrome_profile.set(path)

    def _choose_fast_cli(self):
        path = filedialog.askdirectory()
        if path:
            self.fast_cli.set(path)
            self._refresh_platforms()

    def _choose_file(self, variable):
        path = filedialog.askopenfilename(filetypes=[("可执行文件", "*.exe *.cmd *.bat *"), ("所有文件", "*.*")])
        if path:
            variable.set(path)

    def _import_fast_cli(self):
        if self.worker and self.worker.is_alive():
            messagebox.showerror("无法更新", "请先等待当前任务结束")
            return
        path = filedialog.askopenfilename(filetypes=[("fast-cli 更新包", "*.zip"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            installed = install_runtime_zip(
                Path(path),
                APP_DIR / "runtime" / "fast-cli",
                Path(self.node.get()).expanduser(),
            )
        except RuntimePackageError as exc:
            messagebox.showerror("更新失败", str(exc))
            return
        self.fast_cli.set(str(installed))
        self._refresh_platforms()
        settings = load_settings()
        settings["fast_cli"] = str(installed)
        settings["node"] = self.node.get().strip()
        save_settings(settings)
        messagebox.showinfo("更新完成", f"已启用：{installed.parent.name}")

    def _runtime_settings(self):
        return Settings(
            node=self.node.get().strip(),
            fast_cli=self.fast_cli.get().strip(),
            chrome=self.chrome.get().strip(),
            chrome_profile=self.chrome_profile.get().strip(),
        )

    def _login_platforms(self):
        if self.worker and self.worker.is_alive():
            messagebox.showerror("无法登录", "请先等待当前任务结束")
            return
        try:
            settings = self._runtime_settings()
            if not Path(settings.node).expanduser().is_file():
                raise ValueError("请选择有效的 Node 可执行文件")
            worker_entry(settings.fast_cli)
            if not Path(settings.chrome).expanduser().is_file():
                raise ValueError("请选择有效的 Chrome 可执行文件")
        except Exception as exc:
            messagebox.showerror("无法登录", str(exc))
            return

        def run():
            try:
                open_platform_login(settings)
                self.after(0, lambda: messagebox.showinfo(
                    "登录平台", "登录页已打开，请在浏览器中完成登录和验证码后再开始任务。",
                ))
            except Exception as exc:
                self.logger.exception("打开平台登录页失败")
                self.after(0, lambda error=str(exc): messagebox.showerror("登录失败", error))

        threading.Thread(target=run, daemon=True).start()

    def _selected_platforms(self):
        return [
            platform for platform, _ in self.available_platforms
            if self.platforms[platform].get()
        ]

    def _validate(self, mode):
        excel = Path(self.excel.get()).expanduser()
        if not excel.is_file():
            raise ValueError("请选择有效的 Excel 文件")
        output = Path(self.output.get()).expanduser()
        if not self.output.get().strip():
            raise ValueError("请选择输出目录")
        platforms = self._selected_platforms() if mode != "screenshot" else []
        if mode != "screenshot":
            if not platforms:
                raise ValueError("至少选择一个平台")
            if not self.node.get().strip() or not Path(self.node.get()).expanduser().is_file():
                raise ValueError("请选择有效的 Node 可执行文件")
            try:
                worker_entry(self.fast_cli.get().strip())
            except Exception as exc:
                raise ValueError(str(exc)) from exc
        if not Path(self.chrome.get()).expanduser().is_file():
            raise ValueError("请选择有效的 Chrome 可执行文件")
        if not self.chrome_profile.get().strip():
            raise ValueError("请选择专用 Chrome Profile")
        return excel, output, platforms

    def _start(self, mode):
        try:
            excel, output_root, platforms = self._validate(mode)
        except ValueError as exc:
            messagebox.showerror("无法开始", str(exc))
            return

        output = output_root / f"{excel.stem}_结果"
        settings = self._runtime_settings()
        save_settings({
            "node": settings.node,
            "fast_cli": settings.fast_cli,
            "chrome": settings.chrome,
            "chrome_profile": settings.chrome_profile,
            "output": str(output_root),
            "platforms": self._selected_platforms(),
        })
        self.cancel_event.clear()
        for button in self.start_buttons:
            button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.open_button.configure(state="disabled")
        self.progress["value"] = 0
        self.status.set("正在启动任务…")
        self.last_error = ""
        record_event(APP_DIR, {"type": "started", "mode": mode, "phase": mode})
        self._append_log(f"模式：{MODE_NAMES[mode]}")
        self._append_log(f"Excel：{excel}")
        if platforms:
            self._append_log(f"平台：{' → '.join(self.platform_names[p] for p in platforms)}")
        self.last_output = output

        def run():
            try:
                result = JobRunner(settings, self.events.put, self.cancel_event).run(
                    excel, output, platforms, mode,
                )
                self.events.put({"type": "finished", "result": [str(path) for path in result]})
            except Cancelled as exc:
                self.events.put({"type": "cancelled", "message": str(exc)})
            except Exception as exc:
                self.logger.exception("任务执行失败")
                self.events.put({"type": "failed", "message": str(exc)})

        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()

    def _cancel(self):
        self.cancel_event.set()
        self.status.set("正在取消，将在当前平台操作结束后停止…")
        self.cancel_button.configure(state="disabled")

    def _poll_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                try:
                    record_event(APP_DIR, event)
                except OSError:
                    self.logger.exception("保存任务进度失败")
                event_type = event.get("type")
                if event_type in {"finished", "failed", "cancelled"}:
                    self._finish(event)
                else:
                    self._progress(event)
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

    def _progress(self, event):
        phase = event.get("phase")
        if "current" in event and event.get("total"):
            current, total = event["current"], event["total"]
            self.progress["maximum"] = total
            self.progress["value"] = current
            label = {"collect": "采集", "screenshot": "截图", "export": "导出", "done": "完成"}.get(phase, phase)
            message = f"{label} {current}/{total}"
            if event.get("model"):
                message += f" · {event['model']}"
            if event.get("status"):
                message += f" · {event['status']}"
            self.status.set(message)
            self._append_log(message)
        elif event.get("platform"):
            self.status.set(
                f"采集 {event.get('model')} · {self.platform_names.get(event['platform'], event['platform'])}"
            )

    def _finish(self, event):
        for button in self.start_buttons:
            button.configure(state="normal")
        self.cancel_button.configure(state="disabled")
        if event["type"] == "finished":
            self.status.set("任务完成，可以打开导出目录")
            self._append_log(f"导出完成：{event['result'][-1]}")
            self.open_button.configure(state="normal")
            messagebox.showinfo("任务完成", f"结果已保存到：\n{self.last_output}")
        elif event["type"] == "cancelled":
            self.status.set(event["message"])
            self._append_log(event["message"])
        else:
            self.status.set("任务失败")
            self.last_error = event["message"]
            self._append_log(f"失败：{event['message']}")
            messagebox.showerror("任务失败", event["message"])

    def _append_log(self, message):
        message = str(message)
        self.logger.info(message)
        self.log.configure(state="normal")
        self.log.insert("end", message + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _export_diagnostics(self):
        initial = self.last_output if self.last_output and self.last_output.exists() else Path.home() / "Desktop"
        path = filedialog.asksaveasfilename(
            initialdir=str(initial),
            initialfile=f"Fast-P-诊断包-{datetime.now():%Y%m%d-%H%M%S}.zip",
            defaultextension=".zip",
            filetypes=[("ZIP 压缩包", "*.zip")],
        )
        if not path:
            return
        try:
            archive = export_diagnostics(
                Path(path), APP_DIR, self._runtime_settings(), self.last_output, self.last_error,
            )
            messagebox.showinfo("诊断包已导出", f"请将此文件发给开发人员：\n{archive}")
        except Exception as exc:
            self.logger.exception("导出诊断包失败")
            messagebox.showerror("导出失败", str(exc))

    def _open_output(self):
        if not self.last_output or not self.last_output.exists():
            return
        if os.name == "nt":
            os.startfile(self.last_output)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(self.last_output)])
        else:
            subprocess.Popen(["xdg-open", str(self.last_output)])


def main():
    app = FastPApp()
    app.mainloop()
