"""
証憑ファイル 自動リネームツール（Tesseract OCR版）
完全ローカル処理 - インターネット接続不要・データ外部送信なし

【命名規則】
国内: 日付_書類種別_取引先_識別子_インボイス有無_金額.ext
海外: 日付_Invoice/Receipt_取引先_識別子_金額（通貨付き）.ext

【書類種別】
  請求書  : 国内の請求書
  領収書  : 国内の領収書・レシート（「レシート」表記は使用しない）
  Invoice : 海外の請求書
  Receipt : 海外の領収書
"""

import sys
import os
import re
import json
import subprocess
import tempfile
import shutil
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / "config.json"

# 摘要生成ルールファイル（将来的な拡張用）
# vendor_rules.json が存在すれば追加ルールとして読み込む
VENDOR_RULES_FILE = Path(__file__).parent / "vendor_rules.json"


# ========== 設定 ==========

def load_config() -> dict:
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def get_tesseract_path() -> str:
    config = load_config()
    return config.get("tesseract_path", r"C:\Program Files\Tesseract-OCR\tesseract.exe")


def get_poppler_path() -> str:
    config = load_config()
    return config.get("poppler_path", r"C:\Program Files\poppler\Library\bin")


# ========== OCR ==========

def pdf_to_images(pdf_path: Path, poppler_bin: str) -> list[Path]:
    """popplerのpdftoppmでPDFを画像に変換（最初の3ページのみ）"""
    pdftoppm = Path(poppler_bin) / "pdftoppm.exe"
    if not pdftoppm.exists():
        raise FileNotFoundError(f"pdftoppm.exe が見つかりません: {pdftoppm}")

    tmp_dir = Path(tempfile.mkdtemp())
    out_prefix = tmp_dir / "page"

    cmd = [
        str(pdftoppm),
        "-png",
        "-r", "200",       # 解像度200dpi（精度と速度のバランス）
        "-l", "3",         # 最初の3ページまで
        str(pdf_path),
        str(out_prefix)
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    images = sorted(tmp_dir.glob("*.png"))
    return images


def run_tesseract(image_path: Path, tesseract_exe: str) -> str:
    """Tesseractで画像からテキストを抽出"""
    if not Path(tesseract_exe).exists():
        raise FileNotFoundError(f"Tesseract が見つかりません: {tesseract_exe}")

    with tempfile.NamedTemporaryFile(suffix="", delete=False) as f:
        out_base = f.name  # .txtは自動付与される

    try:
        cmd = [
            tesseract_exe,
            str(image_path),
            out_base,
            "-l", "jpn+eng",   # 日本語＋英語
            "--oem", "3",       # LSTM OCRエンジン
            "--psm", "3",       # 自動ページ分割
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        out_txt = Path(out_base + ".txt")
        if out_txt.exists():
            text = out_txt.read_text(encoding="utf-8", errors="replace")
            out_txt.unlink()
            return text
    finally:
        try:
            Path(out_base).unlink(missing_ok=True)
        except Exception:
            pass
    return ""


def extract_text(file_path: Path) -> str:
    """ファイル種別に応じてテキストを抽出"""
    tesseract_exe = get_tesseract_path()
    poppler_bin   = get_poppler_path()
    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        tmp_images = []
        try:
            tmp_images = pdf_to_images(file_path, poppler_bin)
            if not tmp_images:
                raise ValueError("PDFから画像を生成できませんでした")
            texts = []
            for img in tmp_images[:3]:  # 最大3ページ
                texts.append(run_tesseract(img, tesseract_exe))
            return "\n".join(texts)
        finally:
            # 一時画像を削除
            for img in tmp_images:
                try:
                    img.unlink()
                except Exception:
                    pass
            if tmp_images:
                try:
                    shutil.rmtree(tmp_images[0].parent, ignore_errors=True)
                except Exception:
                    pass

    elif suffix in (".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".gif", ".webp"):
        return run_tesseract(file_path, tesseract_exe)

    else:
        raise ValueError(f"非対応のファイル形式: {suffix}")


# ========== テキスト解析 ==========

def detect_language(text: str) -> str:
    """日本語文字数で国内/海外を判定"""
    jp_chars = re.findall(r"[\u3040-\u30ff\u4e00-\u9fff]", text)
    return "domestic" if len(jp_chars) >= 5 else "overseas"


def parse_document(text: str) -> dict:
    """
    抽出テキストから証憑情報を解析。

    返却キー:
      date        : yyyymmdd
      doc_type    : 請求書 / 領収書 / Invoice / Receipt
      company     : 取引先名
      identifier  : 識別子（領収書番号など）。なければ空文字
      invoice_reg : True/False（国内のみ）
      amount      : 金額文字列
      is_domestic : True=国内 / False=海外
    """
    info = {
        "date": "",
        "doc_type": "",
        "company": "",
        "identifier": "",
        "invoice_reg": False,
        "amount": "",
        "is_domestic": True,
    }

    lang = detect_language(text)
    info["is_domestic"] = (lang == "domestic")

    # ---- 書類種別 ----
    if info["is_domestic"]:
        if re.search(r"領\s*収\s*書|レシート|receipt", text, re.IGNORECASE):
            info["doc_type"] = "領収書"
        elif re.search(r"請\s*求\s*書", text):
            info["doc_type"] = "請求書"
        else:
            info["doc_type"] = "領収書"
    else:
        if re.search(r"\bInvoice\b", text, re.IGNORECASE):
            info["doc_type"] = "Invoice"
        elif re.search(r"\bReceipt\b", text, re.IGNORECASE):
            info["doc_type"] = "Receipt"
        else:
            info["doc_type"] = "Invoice"

    # ---- 発行日 ----
    REIWA_BASE = 2018
    MONTH_MAP = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
    }
    date_patterns = [
        ("jp_era",   r"令和\s*(\d{1,2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"),
        ("jp_era_r", r"R(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{1,2})"),
        ("jp_full",  r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"),
        ("iso",      r"(\d{4})[/\-\.](\d{1,2})[/\-\.](\d{1,2})"),
        ("en_mdy",   r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})"),
        ("en_dmy",   r"(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{4})"),
    ]
    for key, pattern in date_patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if not m:
            continue
        g = m.groups()
        try:
            if key == "jp_era":
                year, month, day = REIWA_BASE + int(g[0]), int(g[1]), int(g[2])
            elif key == "jp_era_r":
                year, month, day = REIWA_BASE + int(g[0]), int(g[1]), int(g[2])
            elif key in ("jp_full", "iso"):
                year, month, day = int(g[0]), int(g[1]), int(g[2])
            elif key == "en_mdy":
                month = MONTH_MAP[g[0][:3].lower()]
                year, day = int(g[2]), int(g[1])
            elif key == "en_dmy":
                month = MONTH_MAP[g[1][:3].lower()]
                year, day = int(g[2]), int(g[0])
            else:
                continue
            if 2000 <= year <= 2099 and 1 <= month <= 12 and 1 <= day <= 31:
                info["date"] = f"{year:04d}{month:02d}{day:02d}"
                break
        except (ValueError, KeyError):
            continue

    # ---- インボイス登録番号（国内のみ）----
    if info["is_domestic"]:
        if re.search(r"T\d{13}", text) or re.search(r"登録番号", text):
            info["invoice_reg"] = True

    # ---- 識別子 ----
    id_patterns = [
        r"領収書\s*No[\.．]?\s*([A-Za-z0-9\-]+)",
        r"領収\s*番号\s*[：:]\s*([A-Za-z0-9\-]+)",
        r"Invoice\s*(?:No|#|Number)[\.:\s]+([A-Za-z0-9\-]+)",
        r"Receipt\s*(?:No|#|Number)[\.:\s]+([A-Za-z0-9\-]+)",
        r"No[\.．]\s*([A-Za-z0-9\-]{3,20})",
    ]
    for pat in id_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            info["identifier"] = m.group(1).strip()
            break

    # ---- 金額 ----
    if info["is_domestic"]:
        amount_label = r"(?:合\s*計|請求\s*金額|お支払|領収\s*金額|税込\s*合計|総\s*合計|お買上)[^\d]*?([\d,，、]+)"
        m = re.search(amount_label, text)
        if m:
            info["amount"] = re.sub(r"[,，、\s]", "", m.group(1)) + "円"
        else:
            candidates = re.findall(r"[¥￥]\s*([\d,，]+)|(\d[\d,，]+)\s*円", text)
            nums = []
            for c in candidates:
                val = re.sub(r"[,，\s]", "", c[0] or c[1])
                if val:
                    nums.append(int(val))
            if nums:
                info["amount"] = str(max(nums)) + "円"
    else:
        foreign_patterns = [
            r"(?:Total|Amount Due|Grand Total)[^\d]*?([\d,\.]+)\s*(USD|EUR|GBP|AUD|CAD|SGD|CNY|HKD)",
            r"\$\s*([\d,\.]+)",
            r"([\d,\.]+)\s*(USD|EUR|GBP|AUD|CAD|SGD|CNY|HKD)",
            r"[£€]\s*([\d,\.]+)",
        ]
        currency_symbols = {"$": "USD", "£": "GBP", "€": "EUR"}
        for pat in foreign_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                g = m.groups()
                num = re.sub(r"[,\s]", "", g[0])
                currency = g[1].upper() if len(g) > 1 and g[1] else ""
                if not currency:
                    sym_m = re.search(r"([\$£€])\s*" + re.escape(g[0]), text)
                    if sym_m:
                        currency = currency_symbols.get(sym_m.group(1), "")
                info["amount"] = f"{num}{currency}" if currency else num
                break

    # ---- 取引先名 ----
    company_patterns = [
        r"^(.+?)\s*(?:御中|様)\s*$",
        r"((?:株式会社|有限会社|合同会社|合資会社)[^\s\n]{1,20})",
        r"([^\s\n]{1,20}(?:株式会社|有限会社|合同会社|（株）|\(株\)))",
        r"([A-Z][A-Za-z0-9\s\-&\.]{2,40}(?:Co\.|Corp\.|Inc\.|Ltd\.|LLC))",
        r"^([A-Z][a-z]+(?:\s[A-Z][a-z]+)+)\s*$",
    ]
    for pat in company_patterns:
        m = re.search(pat, text, re.MULTILINE)
        if m:
            company = re.sub(r"[「」『』【】\[\]]", "", m.group(1)).strip()
            if 2 <= len(company) <= 40:
                info["company"] = company
                break

    return info


def sanitize(text: str) -> str:
    """ファイル名に使えない文字を除去"""
    return re.sub(r'[\\/:*?"<>|\s]', "", text)


def build_filename(info: dict, original_suffix: str) -> str:
    """命名規則に従ってファイル名を生成"""
    date    = info["date"]     or "00000000"
    doc     = info["doc_type"] or ("領収書" if info["is_domestic"] else "Receipt")
    company = sanitize(info["company"]) or "不明"
    ident   = sanitize(info["identifier"])
    amount  = info["amount"] or "0"

    parts = [date, doc, company]
    if ident:
        parts.append(ident)
    if info["is_domestic"]:
        parts.append("インボイス有" if info["invoice_reg"] else "インボイス無")
    parts.append(amount)

    return "_".join(parts) + original_suffix


# ========== 摘要生成 ==========

# 組み込みルール定義
# 将来的に vendor_rules.json へ切り出して外部管理できる構造にしています。
# 各ルールは {"keywords": [...], "content": "摘要名"} の形式です。
_BUILTIN_RULES: list[dict] = [
    {
        "keywords": ["hotel", "hyatt", "hilton", "marriott", "inn", "resort",
                     "宿泊", "ホテル", "旅館"],
        "content": "宿泊費",
    },
    {
        "keywords": ["grab", "taxi", "uber", "lyft", "gojek", "mrtライド",
                     "交通", "タクシー", "電車", "バス", "新幹線", "airfare",
                     "airline", "flight", "airways"],
        "content": "交通費",
    },
    {
        "keywords": ["restaurant", "cafe", "coffee", "starbucks", "mcdonald",
                     "subway", "pizza", "sushi", "ramen", "izakaya",
                     "飲食", "食事", "ランチ", "ディナー", "居酒屋", "レストラン",
                     "カフェ", "コーヒー"],
        "content": "飲食代",
    },
    {
        "keywords": ["openai", "chatgpt", "anthropic", "aws", "amazon web",
                     "google cloud", "gcp", "azure", "microsoft 365",
                     "github", "heroku", "cloudflare", "datadog", "stripe",
                     "subscription", "cloud", "saas", "paas", "iaas",
                     "クラウド", "サブスクリプション"],
        "content": "クラウドサービス利用料",
    },
    {
        "keywords": ["monitor", "keyboard", "mouse", "pc", "laptop", "printer",
                     "scanner", "headphone", "webcam", "cable", "usb",
                     "備品", "消耗品", "文房具", "パソコン", "モニター",
                     "キーボード", "マウス", "プリンター"],
        "content": "備品購入",
    },
    {
        "keywords": ["book", "seminar", "conference", "training", "course",
                     "書籍", "セミナー", "研修", "勉強会", "学会"],
        "content": "教育研修費",
    },
    {
        "keywords": ["advertisement", "advertising", "ad ", "ads", "marketing",
                     "広告", "宣伝", "マーケティング"],
        "content": "広告宣伝費",
    },
    {
        "keywords": ["delivery", "shipping", "fedex", "dhl", "ups", "yamato",
                     "sagawa", "japan post", "ヤマト", "佐川", "郵便", "宅配",
                     "配送", "送料"],
        "content": "送料",
    },
]


def _load_vendor_rules() -> list[dict]:
    """
    vendor_rules.json が存在すれば追加ルールとして読み込む。

    ファイル形式の例:
    [
      {"keywords": ["acme", "acme corp"], "content": "ソフトウェアライセンス料"},
      {"keywords": ["cleaners", "cleaning"], "content": "清掃費"}
    ]

    このファイルが存在しない場合は空リストを返す（エラーにしない）。
    """
    if not VENDOR_RULES_FILE.exists():
        return []
    try:
        with open(VENDOR_RULES_FILE, encoding="utf-8") as f:
            rules = json.load(f)
        if isinstance(rules, list):
            return rules
    except Exception:
        pass
    return []


def _match_rules(lower_text: str, rules: list[dict]) -> str:
    """
    ルールリストに対してテキストをマッチングし、最初にヒットした摘要名を返す。
    ヒットしなければ空文字を返す。
    """
    for rule in rules:
        keywords = rule.get("keywords", [])
        content  = rule.get("content", "")
        if content and any(kw.lower() in lower_text for kw in keywords):
            return content
    return ""


def generate_description(info: dict, text: str) -> str:
    """
    OCR抽出テキストと parse_document() の解析結果から経理入力用の摘要案を生成する。

    摘要形式:
      取引先／内容／国内取引
      取引先／内容／海外取引

    判定優先順位:
      1. vendor_rules.json のカスタムルール（存在する場合）
      2. 組み込みルール（_BUILTIN_RULES）
      3. 書類種別フォールバック（請求書 / Invoice → "請求書"）
      4. デフォルト → "経費"

    Parameters
    ----------
    info : dict
        parse_document() の返却値
    text : str
        OCRで抽出した生テキスト

    Returns
    -------
    str
        摘要案文字列（例: "Grab／交通費／海外取引"）
    """
    company     = info.get("company") or "取引先不明"
    doc_type    = info.get("doc_type") or ""
    is_domestic = info.get("is_domestic", True)
    lower_text  = text.lower()

    # 1. カスタムルール（vendor_rules.json）を優先
    vendor_rules = _load_vendor_rules()
    content = _match_rules(lower_text, vendor_rules)

    # 2. 組み込みルール
    if not content:
        content = _match_rules(lower_text, _BUILTIN_RULES)

    # 3. 書類種別フォールバック
    if not content:
        if doc_type in ("請求書", "Invoice"):
            content = "請求書"
        elif doc_type in ("領収書", "Receipt"):
            content = "経費"
        else:
            content = "経費"

    tax_hint = "国内取引" if is_domestic else "海外取引"
    return f"{company}／{content}／{tax_hint}"


# ========== メイン処理 ==========

def process_file(file_path_str: str) -> tuple[bool, str]:
    """1ファイルを処理してリネーム。(成功, メッセージ) を返す"""
    file_path = Path(file_path_str)
    if not file_path.exists():
        return False, f"ファイルが見つかりません: {file_path}"

    try:
        text = extract_text(file_path)
    except FileNotFoundError as e:
        return False, str(e)
    except Exception as e:
        return False, f"OCRエラー: {e}"

    if not text.strip():
        return False, "テキストを抽出できませんでした（画像が低解像度すぎる可能性があります）"

    info        = parse_document(text)
    description = generate_description(info, text)
    new_name    = build_filename(info, file_path.suffix)
    new_path    = file_path.parent / new_name

    # 同名ファイルが存在する場合は連番
    if new_path.exists() and new_path != file_path:
        stem, suffix = new_path.stem, new_path.suffix
        counter = 2
        while new_path.exists():
            new_path = file_path.parent / f"{stem}_{counter}{suffix}"
            counter += 1

    try:
        file_path.rename(new_path)
    except Exception as e:
        return False, f"リネーム失敗: {e}"

    return True, f"{file_path.name}\n  → {new_path.name}\n  摘要案：{description}"


def show_result_dialog(title: str, message: str):
    """結果をWindowsダイアログで表示"""
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo(title, message)
        root.destroy()
    except Exception:
        print(f"{title}\n{message}")


def main():
    if len(sys.argv) < 2:
        show_result_dialog("エラー", "ファイルを指定してください。\n右クリック→「証憑リネーム」から実行してください。")
        return

    files = sys.argv[1:]
    results, errors = [], []

    for f in files:
        ok, msg = process_file(f)
        (results if ok else errors).append(msg if ok else f"{Path(f).name}: {msg}")

    summary_parts = []
    if results:
        summary_parts.append(f"✅ リネーム完了 ({len(results)}件)\n\n" + "\n\n".join(results))
    if errors:
        summary_parts.append(f"❌ エラー ({len(errors)}件)\n\n" + "\n".join(errors))

    show_result_dialog("証憑リネーム", "\n\n".join(summary_parts) or "処理対象がありません")


if __name__ == "__main__":
    main()
