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
    # ------------------------------------------------------------------
    # 旅費交通費：宿泊
    # ------------------------------------------------------------------
    {
        "keywords": [
            "hotel", "hyatt", "hilton", "marriott", "sheraton", "westin",
            "apa", "dormy inn", "toyoko inn", "東横イン", "ルートイン",
            "inn", "resort", "lodge",
            "宿泊", "ホテル", "旅館", "民宿",
        ],
        "content": "宿泊費",
    },
    # ------------------------------------------------------------------
    # 旅費交通費：交通
    # ------------------------------------------------------------------
    {
        "keywords": [
            "taxi", "タクシー", "cab",
            "uber", "grab", "lyft", "didi", "go タクシー",
            "jr ", "新幹線", "特急", "乗車券", "定期券", "suica", "pasmo",
            "東京メトロ", "都営", "私鉄", "近鉄", "阪急", "阪神", "京急",
            "バス", "高速バス", "路線バス",
            "airfare", "airline", "flight", "airways", "ana ", "jal ",
            "駐車場", "パーキング", "高速料金", "etc ",
            "旅費", "交通費",
        ],
        "content": "旅費交通費",
    },
    # ------------------------------------------------------------------
    # 接待交際費
    # ------------------------------------------------------------------
    {
        "keywords": [
            "接待", "交際", "手土産", "ご祝儀", "御祝", "お中元", "お歳暮",
            "冠婚葬祭", "香典", "祝儀",
            "golf", "ゴルフ", "ゴルフ場",
            "クラブ", "バー", "bar ", "ラウンジ", "lounge",
        ],
        "content": "接待交際費",
    },
    # ------------------------------------------------------------------
    # 会議費・飲食
    # ------------------------------------------------------------------
    {
        "keywords": [
            "restaurant", "レストラン", "食堂", "定食",
            "cafe", "カフェ", "coffee", "コーヒー", "スターバックス", "starbucks",
            "ドトール", "コメダ", "タリーズ",
            "pizza", "ピザ", "sushi", "寿司", "ramen", "ラーメン",
            "居酒屋", "izakaya", "焼肉", "しゃぶしゃぶ", "天ぷら",
            "弁当", "仕出し", "ケータリング", "catering",
            "会議費", "昼食", "ランチ", "ディナー", "飲食", "食事",
        ],
        "content": "会議費",
    },
    # ------------------------------------------------------------------
    # 通信費
    # ------------------------------------------------------------------
    {
        "keywords": [
            "ntt", "docomo", "ドコモ", "au ", "kddi", "softbank", "ソフトバンク",
            "rakuten mobile", "楽天モバイル", "iijmio", "mineo",
            "インターネット", "光回線", "フレッツ", "wi-fi", "wifi",
            "電話", "携帯", "スマートフォン", "スマホ", "通話料",
            "zoom", "slack", "chatwork", "teams", "line works",
            "通信費", "回線",
        ],
        "content": "通信費",
    },
    # ------------------------------------------------------------------
    # 水道光熱費
    # ------------------------------------------------------------------
    {
        "keywords": [
            "東京電力", "関西電力", "中部電力", "九州電力", "東北電力",
            "電力", "電気料金", "電気代",
            "東京ガス", "大阪ガス", "東邦ガス", "ガス料金", "ガス代",
            "水道", "上下水道", "水道料金",
            "電気", "ガス", "光熱費",
        ],
        "content": "水道光熱費",
    },
    # ------------------------------------------------------------------
    # 地代家賃
    # ------------------------------------------------------------------
    {
        "keywords": [
            "家賃", "賃料", "地代", "賃貸", "テナント",
            "管理費", "共益費", "駐車場代", "月極",
            "rent", "lease",
        ],
        "content": "地代家賃",
    },
    # ------------------------------------------------------------------
    # 保険料
    # ------------------------------------------------------------------
    {
        "keywords": [
            "保険料", "保険", "損保", "生命保険", "火災保険", "自動車保険",
            "損害保険", "東京海上", "損保ジャパン", "三井住友海上",
            "あいおいニッセイ", "共済",
            "insurance",
        ],
        "content": "保険料",
    },
    # ------------------------------------------------------------------
    # 消耗品費
    # ------------------------------------------------------------------
    {
        "keywords": [
            "コンビニ", "セブンイレブン", "ファミリーマート", "ローソン",
            "文房具", "コピー用紙", "トナー", "インク", "インクカートリッジ",
            "ボールペン", "ノート", "封筒", "クリアファイル",
            "洗剤", "清掃用品", "ゴミ袋", "トイレットペーパー",
            "コーヒー豆", "お茶", "飲料水", "ウォーターサーバー",
            "消耗品", "雑費",
        ],
        "content": "消耗品費",
    },
    # ------------------------------------------------------------------
    # 備品・器具費（単価10万円未満の物品）
    # ------------------------------------------------------------------
    {
        "keywords": [
            "monitor", "モニター", "ディスプレイ",
            "keyboard", "キーボード", "mouse", "マウス",
            "pc", "パソコン", "laptop", "ノートpc", "タブレット",
            "printer", "プリンター", "scanner", "スキャナー",
            "headphone", "ヘッドフォン", "webcam", "ウェブカメラ",
            "hard disk", "hdd", "ssd", "usb", "ケーブル",
            "椅子", "デスク", "チェア", "シュレッダー",
            "備品",
        ],
        "content": "備品費",
    },
    # ------------------------------------------------------------------
    # 修繕費
    # ------------------------------------------------------------------
    {
        "keywords": [
            "修理", "修繕", "メンテナンス", "保守", "点検",
            "オーバーホール", "部品交換", "補修",
            "repair", "maintenance",
        ],
        "content": "修繕費",
    },
    # ------------------------------------------------------------------
    # 外注費・業務委託
    # ------------------------------------------------------------------
    {
        "keywords": [
            "外注", "業務委託", "委託", "請負", "下請",
            "コンサルティング", "コンサル", "consulting",
            "システム開発", "web制作", "デザイン料", "翻訳",
            "outsourcing", "freelance", "フリーランス",
        ],
        "content": "外注費",
    },
    # ------------------------------------------------------------------
    # 広告宣伝費
    # ------------------------------------------------------------------
    {
        "keywords": [
            "広告", "宣伝", "チラシ", "パンフレット", "カタログ",
            "名刺", "印刷", "デザイン",
            "google ads", "yahoo広告", "facebook ads", "instagram",
            "advertisement", "advertising", "marketing", "マーケティング",
            "pr ", "プレスリリース",
        ],
        "content": "広告宣伝費",
    },
    # ------------------------------------------------------------------
    # 新聞図書費
    # ------------------------------------------------------------------
    {
        "keywords": [
            "書籍", "本", "雑誌", "新聞", "日経", "朝日新聞", "読売新聞",
            "日本経済新聞", "週刊", "月刊",
            "amazon", "kindle", "楽天ブックス",
            "book", "magazine", "newspaper",
            "図書", "電子書籍",
        ],
        "content": "新聞図書費",
    },
    # ------------------------------------------------------------------
    # 教育研修費
    # ------------------------------------------------------------------
    {
        "keywords": [
            "セミナー", "研修", "勉強会", "講習", "資格",
            "eラーニング", "オンライン講座", "udemy", "schoo",
            "学会", "conference", "seminar", "training", "workshop",
            "受講料", "受験料", "検定",
        ],
        "content": "教育研修費",
    },
    # ------------------------------------------------------------------
    # 福利厚生費
    # ------------------------------------------------------------------
    {
        "keywords": [
            "福利厚生", "慶弔", "健康診断", "人間ドック",
            "社員旅行", "懇親会", "忘年会", "新年会", "歓迎会", "送別会",
            "社食", "社員食堂", "フィットネス", "スポーツクラブ",
        ],
        "content": "福利厚生費",
    },
    # ------------------------------------------------------------------
    # クラウド・ソフトウェア利用料
    # ------------------------------------------------------------------
    {
        "keywords": [
            "openai", "chatgpt", "anthropic", "claude",
            "aws", "amazon web services", "google cloud", "gcp",
            "azure", "microsoft 365", "office 365",
            "github", "gitlab", "bitbucket",
            "salesforce", "hubspot", "freee", "マネーフォワード",
            "弥生", "kintone", "cybozu", "notion", "figma",
            "heroku", "cloudflare", "datadog", "twilio",
            "subscription", "サブスクリプション", "ライセンス", "license",
            "クラウド", "saas",
        ],
        "content": "クラウドサービス利用料",
    },
    # ------------------------------------------------------------------
    # 郵便・運送費
    # ------------------------------------------------------------------
    {
        "keywords": [
            "郵便", "ゆうパック", "ゆうメール", "日本郵便", "japan post",
            "ヤマト運輸", "クロネコ", "yamato", "佐川急便", "sagawa",
            "fedex", "dhl", "ups", "delivery", "shipping",
            "宅配", "配送", "送料", "運賃",
        ],
        "content": "荷造運賃",
    },
    # ------------------------------------------------------------------
    # 支払手数料
    # ------------------------------------------------------------------
    {
        "keywords": [
            "振込手数料", "振込", "銀行手数料", "送金手数料",
            "クレジット手数料", "決済手数料", "paypal", "stripe",
            "手数料", "fee", "commission",
        ],
        "content": "支払手数料",
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
      取引先／内容／YYYYMM

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
        摘要案文字列（例: "Grab／交通費／202401"）
    """
    company    = info.get("company") or "取引先不明"
    doc_type   = info.get("doc_type") or ""
    lower_text = text.lower()

    # 1. カスタムルール（vendor_rules.json）を優先
    vendor_rules = _load_vendor_rules()
    content = _match_rules(lower_text, vendor_rules)

    # 2. 組み込みルール
    if not content:
        content = _match_rules(lower_text, _BUILTIN_RULES)

    # 3. キーワードが何もヒットしなければ「経費」に統一
    if not content:
        content = "経費"

    # 発行日から YYYYMM を取得（日付不明の場合は「不明」）
    raw_date = info.get("date") or ""
    if len(raw_date) == 8 and raw_date != "00000000":
        yyyymm = raw_date[:6]   # "20240120" → "202401"
    else:
        yyyymm = "不明"

    return f"{company}/{content}/{yyyymm}"


# ========== メイン処理 ==========

def process_file(file_path_str: str) -> dict:
    """
    1ファイルを処理してリネーム。結果を辞書で返す。

    返却キー:
      ok          : bool   処理成功かどうか
      original    : str    元のファイル名
      renamed     : str    リネーム後のファイル名（成功時のみ）
      description : str    摘要案（成功時のみ）
      error       : str    エラーメッセージ（失敗時のみ）
    """
    file_path = Path(file_path_str)
    base = {"original": file_path.name, "renamed": "", "description": "", "error": ""}

    if not file_path.exists():
        return {**base, "ok": False, "error": f"ファイルが見つかりません: {file_path}"}

    try:
        text = extract_text(file_path)
    except FileNotFoundError as e:
        return {**base, "ok": False, "error": str(e)}
    except Exception as e:
        return {**base, "ok": False, "error": f"OCRエラー: {e}"}

    if not text.strip():
        return {**base, "ok": False,
                "error": "テキストを抽出できませんでした（画像が低解像度すぎる可能性があります）"}

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
        return {**base, "ok": False, "error": f"リネーム失敗: {e}"}

    return {**base, "ok": True, "renamed": new_path.name, "description": description}


def show_result_dialog(results: list[dict]):
    """
    処理結果をカスタムウィンドウで表示する。
    - リネーム前後のファイル名をプレビュー表示
    - 摘要案はテキストエリアに表示してコピー可能
    """
    try:
        import tkinter as tk
        from tkinter import ttk, font as tkfont

        root = tk.Tk()
        root.title("証憑リネーム 処理結果")
        root.resizable(True, True)

        # ウィンドウサイズをファイル数に応じて調整（最大900x700）
        win_h = min(200 + len(results) * 130, 700)
        root.geometry(f"820x{win_h}")
        root.minsize(640, 300)

        FONT_LABEL  = ("Yu Gothic UI", 10)
        FONT_BOLD   = ("Yu Gothic UI", 10, "bold")
        FONT_MONO   = ("Consolas", 9)
        COLOR_OK    = "#1a7a3c"
        COLOR_ERR   = "#c0392b"
        COLOR_MUTED = "#666666"
        COLOR_BG    = "#f8f9fa"
        COLOR_CARD  = "#ffffff"
        COLOR_BORDER= "#dee2e6"

        root.configure(bg=COLOR_BG)

        # ---- ヘッダー ----
        ok_count  = sum(1 for r in results if r["ok"])
        err_count = len(results) - ok_count
        header_text = f"✅ 完了 {ok_count}件"
        if err_count:
            header_text += f"　❌ エラー {err_count}件"

        tk.Label(root, text="証憑リネーム 処理結果", font=("Yu Gothic UI", 13, "bold"),
                 bg=COLOR_BG).pack(anchor="w", padx=20, pady=(16, 2))
        tk.Label(root, text=header_text, font=FONT_LABEL, bg=COLOR_BG,
                 fg=COLOR_OK if not err_count else COLOR_ERR).pack(anchor="w", padx=20, pady=(0, 10))

        ttk.Separator(root, orient="horizontal").pack(fill="x", padx=20, pady=(0, 10))

        # ---- スクロール可能なカードエリア ----
        canvas = tk.Canvas(root, bg=COLOR_BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(root, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y", padx=(0, 8))
        canvas.pack(side="left", fill="both", expand=True, padx=(20, 0))

        frame = tk.Frame(canvas, bg=COLOR_BG)
        canvas_window = canvas.create_window((0, 0), window=frame, anchor="nw")

        def _on_frame_configure(e):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(e):
            canvas.itemconfig(canvas_window, width=e.width)

        frame.bind("<Configure>", _on_frame_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        # マウスホイールスクロール
        def _on_mousewheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # ---- 各ファイルのカード ----
        for r in results:
            card = tk.Frame(frame, bg=COLOR_CARD, relief="flat",
                            highlightbackground=COLOR_BORDER, highlightthickness=1)
            card.pack(fill="x", pady=6, padx=4, ipady=10, ipadx=12)

            if r["ok"]:
                # ステータスバッジ
                tk.Label(card, text="✅ リネーム完了", font=FONT_BOLD,
                         fg=COLOR_OK, bg=COLOR_CARD).grid(row=0, column=0, sticky="w")

                # 元ファイル名
                tk.Label(card, text="変更前", font=FONT_LABEL, fg=COLOR_MUTED,
                         bg=COLOR_CARD).grid(row=1, column=0, sticky="w", pady=(6, 0))
                tk.Label(card, text=r["original"], font=FONT_MONO,
                         bg=COLOR_CARD, wraplength=700, justify="left").grid(
                             row=2, column=0, sticky="w")

                # 矢印
                tk.Label(card, text="　↓", font=FONT_LABEL, fg=COLOR_MUTED,
                         bg=COLOR_CARD).grid(row=3, column=0, sticky="w")

                # リネーム後ファイル名
                tk.Label(card, text="変更後", font=FONT_LABEL, fg=COLOR_MUTED,
                         bg=COLOR_CARD).grid(row=4, column=0, sticky="w")
                tk.Label(card, text=r["renamed"], font=FONT_MONO, fg=COLOR_OK,
                         bg=COLOR_CARD, wraplength=700, justify="left").grid(
                             row=5, column=0, sticky="w")

                # 摘要案ラベル＋コピーボタン
                desc_row = tk.Frame(card, bg=COLOR_CARD)
                desc_row.grid(row=6, column=0, sticky="ew", pady=(10, 0))

                tk.Label(desc_row, text="摘要案", font=FONT_BOLD,
                         bg=COLOR_CARD).pack(side="left")

                def _make_copy(desc=r["description"]):
                    root.clipboard_clear()
                    root.clipboard_append(desc)

                tk.Button(desc_row, text="📋 コピー", font=("Yu Gothic UI", 8),
                          relief="flat", bg="#e8f0fe", fg="#1a73e8",
                          padx=6, pady=2,
                          command=_make_copy).pack(side="left", padx=(8, 0))

                # 摘要テキストエリア（選択・コピー可能）
                desc_text = tk.Text(card, font=FONT_MONO, height=1,
                                    relief="flat", bg="#f0f4ff",
                                    wrap="none", cursor="xterm")
                desc_text.insert("1.0", r["description"])
                desc_text.configure(state="normal")   # 選択可能・編集不可にしたい場合は"disabled"
                desc_text.grid(row=7, column=0, sticky="ew", pady=(2, 0))
                card.columnconfigure(0, weight=1)

            else:
                # エラーカード
                tk.Label(card, text="❌ エラー", font=FONT_BOLD,
                         fg=COLOR_ERR, bg=COLOR_CARD).grid(row=0, column=0, sticky="w")
                tk.Label(card, text=r["original"], font=FONT_MONO,
                         bg=COLOR_CARD).grid(row=1, column=0, sticky="w", pady=(4, 0))
                tk.Label(card, text=r["error"], font=FONT_LABEL, fg=COLOR_ERR,
                         bg=COLOR_CARD, wraplength=700, justify="left").grid(
                             row=2, column=0, sticky="w", pady=(4, 0))
                card.columnconfigure(0, weight=1)

        # ---- 閉じるボタン ----
        tk.Button(root, text="閉じる", command=root.destroy,
                  font=FONT_LABEL, relief="flat", bg="#e0e0e0",
                  padx=16, pady=6).pack(pady=16)

        root.mainloop()

    except Exception as e:
        # tkinter が使えない環境ではコンソール出力にフォールバック
        for r in results:
            if r["ok"]:
                print(f"✅ {r['original']} → {r['renamed']}")
                print(f"   摘要案: {r['description']}")
            else:
                print(f"❌ {r['original']}: {r['error']}")


def main():
    if len(sys.argv) < 2:
        show_result_dialog([{
            "ok": False, "original": "", "renamed": "", "description": "",
            "error": "ファイルを指定してください。\n右クリック→「証憑リネーム」から実行してください。"
        }])
        return

    files = sys.argv[1:]
    results = [process_file(f) for f in files]
    show_result_dialog(results)


if __name__ == "__main__":
    main()
