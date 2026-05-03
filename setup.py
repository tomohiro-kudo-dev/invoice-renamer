"""
セットアップスクリプト（Tesseract OCR版）
- Tesseract / Poppler のパス設定
- Windowsレジストリへの右クリックメニュー登録
"""

import sys
import os
import json
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path

SCRIPT_DIR  = Path(__file__).parent.resolve()
RENAME_SCRIPT = SCRIPT_DIR / "rename_invoice.py"
CONFIG_FILE   = SCRIPT_DIR / "config.json"
MENU_LABEL    = "証憑リネーム（ローカルOCR）"

SUPPORTED_EXTS = [".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".gif", ".webp"]

# Tesseract / Poppler のデフォルトインストールパス
DEFAULT_TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
DEFAULT_POPPLER   = r"C:\Program Files\poppler\Library\bin"


def load_config() -> dict:
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_config(config: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def check_tesseract(path: str) -> bool:
    try:
        result = subprocess.run([path, "--version"], capture_output=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False


def check_poppler(bin_dir: str) -> bool:
    return (Path(bin_dir) / "pdftoppm.exe").exists()


def get_command() -> str:
    python = sys.executable
    script = str(RENAME_SCRIPT)
    return f'"{python}" "{script}" "%1"'


def register_context_menu() -> list:
    import winreg
    command = get_command()
    errors = []
    for ext in SUPPORTED_EXTS:
        try:
            try:
                with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, ext) as k:
                    prog_id, _ = winreg.QueryValueEx(k, "")
            except Exception:
                prog_id = None
            targets = [ext] + ([prog_id] if prog_id else [])
            for target in targets:
                key_path = rf"{target}\shell\{MENU_LABEL}\command"
                with winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, key_path) as k:
                    winreg.SetValueEx(k, "", 0, winreg.REG_SZ, command)
        except PermissionError:
            errors.append(ext)
        except Exception as e:
            errors.append(f"{ext}: {e}")
    try:
        key_path = rf"*\shell\{MENU_LABEL}\command"
        with winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, key_path) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, command)
    except Exception as e:
        errors.append(f"*(全ファイル): {e}")
    return errors


def unregister_context_menu():
    import winreg
    def delete_key(base, path):
        try:
            winreg.DeleteKey(base, path + r"\command")
        except Exception:
            pass
        try:
            winreg.DeleteKey(base, path)
        except Exception:
            pass
    for ext in SUPPORTED_EXTS:
        delete_key(winreg.HKEY_CLASSES_ROOT, rf"{ext}\shell\{MENU_LABEL}")
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, ext) as k:
                prog_id, _ = winreg.QueryValueEx(k, "")
            if prog_id:
                delete_key(winreg.HKEY_CLASSES_ROOT, rf"{prog_id}\shell\{MENU_LABEL}")
        except Exception:
            pass
    delete_key(winreg.HKEY_CLASSES_ROOT, rf"*\shell\{MENU_LABEL}")


# ========== GUI ==========

class SetupApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("証憑リネーム セットアップ（Tesseract OCR版）")
        self.resizable(False, False)
        self.geometry("580x520")
        self.build_ui()
        self.load_current()

    def build_ui(self):
        tk.Label(self, text="証憑ファイル 自動リネームツール", font=("Yu Gothic UI", 14, "bold")).pack(pady=(20, 2))
        tk.Label(self, text="完全ローカルOCR処理 ― データはPC外に送信されません",
                 font=("Yu Gothic UI", 9), fg="#1a7a3c").pack()

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=20, pady=12)

        # --- Tesseract パス ---
        self.make_path_row("Tesseract OCR 実行ファイル (.exe)", "tesseract")

        tk.Label(self, text="　※ 未インストールの場合: https://github.com/UB-Mannheim/tesseract/wiki",
                 font=("Yu Gothic UI", 8), fg="#777", anchor="w").pack(fill="x", padx=24)

        tk.Label(self, text="　　インストール時「Japanese」言語パックを必ず選択してください",
                 font=("Yu Gothic UI", 8), fg="#c00", anchor="w").pack(fill="x", padx=24, pady=(0, 8))

        # --- Poppler パス ---
        self.make_path_row("Poppler bin フォルダ（PDF処理用）", "poppler")

        tk.Label(self, text="　※ 未インストールの場合: https://github.com/oschwartz10612/poppler-windows/releases",
                 font=("Yu Gothic UI", 8), fg="#777", anchor="w").pack(fill="x", padx=24, pady=(0, 8))

        # --- ボタン ---
        btn_frame = tk.Frame(self)
        btn_frame.pack(pady=10)

        tk.Button(btn_frame, text="✅ パスを保存・確認", command=self.save_and_check,
                  bg="#1a73e8", fg="white", font=("Yu Gothic UI", 10),
                  relief="flat", padx=12, pady=6).pack(side="left", padx=6)

        tk.Button(btn_frame, text="📋 右クリックメニューに登録",
                  command=self.do_register, font=("Yu Gothic UI", 10),
                  relief="flat", padx=12, pady=6).pack(side="left", padx=6)

        tk.Button(btn_frame, text="🗑 登録解除",
                  command=self.do_unregister, font=("Yu Gothic UI", 10),
                  relief="flat", padx=12, pady=6).pack(side="left", padx=6)

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=20, pady=8)

        self.status_var = tk.StringVar(value="")
        tk.Label(self, textvariable=self.status_var, font=("Yu Gothic UI", 9),
                 fg="#333", wraplength=520, justify="left").pack(padx=20, pady=4)

        hint = (
            "【使い方】\n"
            "① Tesseract と Poppler をインストールし、パスを保存\n"
            "② 「右クリックメニューに登録」をクリック（管理者権限が必要）\n"
            "③ PDF・画像ファイルを右クリック →「証憑リネーム（ローカルOCR）」を選択\n\n"
            "⚠ ファイルはすべてPC内で処理されます。外部サーバーへの送信は一切ありません。"
        )
        tk.Label(self, text=hint, font=("Yu Gothic UI", 9), fg="#444",
                 justify="left", anchor="w").pack(fill="x", padx=20, pady=(0, 16))

    def make_path_row(self, label: str, key: str):
        tk.Label(self, text=label, font=("Yu Gothic UI", 10, "bold"), anchor="w").pack(fill="x", padx=20, pady=(4, 2))
        row = tk.Frame(self)
        row.pack(fill="x", padx=20, pady=(0, 2))
        entry = tk.Entry(row, font=("Consolas", 9), width=60)
        entry.pack(side="left", fill="x", expand=True)
        setattr(self, f"_{key}_entry", entry)

        def browse(k=key, e=entry):
            if k == "tesseract":
                path = filedialog.askopenfilename(
                    title="tesseract.exe を選択",
                    filetypes=[("実行ファイル", "*.exe")]
                )
            else:
                path = filedialog.askdirectory(title="Poppler の bin フォルダを選択")
            if path:
                e.delete(0, tk.END)
                e.insert(0, path)

        tk.Button(row, text="参照", command=browse, relief="flat",
                  font=("Yu Gothic UI", 9), padx=6).pack(side="left", padx=(4, 0))

    def load_current(self):
        config = load_config()
        self._tesseract_entry.insert(0, config.get("tesseract_path", DEFAULT_TESSERACT))
        self._poppler_entry.insert(0,   config.get("poppler_path",   DEFAULT_POPPLER))

    def save_and_check(self):
        tess = self._tesseract_entry.get().strip()
        popl = self._poppler_entry.get().strip()

        msgs = []
        tess_ok = check_tesseract(tess)
        popl_ok = check_poppler(popl)

        msgs.append(f"Tesseract: {'✅ 検出OK' if tess_ok else '❌ 見つかりません'} → {tess}")
        msgs.append(f"Poppler:   {'✅ 検出OK' if popl_ok else '❌ 見つかりません'} → {popl}")

        if not tess_ok:
            msgs.append("\n⚠ Tesseractが見つかりません。インストール後に正しいパスを指定してください。")
        if not popl_ok:
            msgs.append("⚠ Popplerが見つかりません。PDFを処理する場合は必要です。")

        config = load_config()
        config["tesseract_path"] = tess
        config["poppler_path"]   = popl
        save_config(config)

        self.status_var.set("\n".join(msgs))

    def do_register(self):
        import ctypes
        if not ctypes.windll.shell32.IsUserAnAdmin():
            messagebox.showwarning("管理者権限が必要",
                "右クリックメニューの登録には管理者権限が必要です。\n"
                "このスクリプトを右クリック →「管理者として実行」で起動してください。")
            return
        errors = register_context_menu()
        if errors:
            self.status_var.set(f"⚠️ 一部登録失敗: {', '.join(errors)}")
        else:
            self.status_var.set("✅ 右クリックメニューへの登録完了！\nエクスプローラーを再起動すると反映されます。")

    def do_unregister(self):
        import ctypes
        if not ctypes.windll.shell32.IsUserAnAdmin():
            messagebox.showwarning("管理者権限が必要", "管理者として実行してください。")
            return
        unregister_context_menu()
        self.status_var.set("🗑 右クリックメニューの登録を解除しました。")


if __name__ == "__main__":
    app = SetupApp()
    app.mainloop()
