# 証憑ファイル 自動リネームツール（Tesseract OCR版）

**完全ローカル処理** ― ファイルはPCの外に一切送信されません。

PDF・画像ファイルを右クリックするだけで、Tesseract OCR が内容を読み取り、
以下の命名規則でファイル名を自動変換します。

```
【国内】 yyyymmdd_書類種別_取引先_識別子_インボイス有無_金額円.pdf
【海外】 yyyymmdd_Invoice/Receipt_取引先_識別子_金額USD.pdf
```

**例:**
```
20240115_領収書_セブンイレブン_インボイス有_550円.jpg
20240210_請求書_株式会社サンプル_No001_インボイス有_110000円.pdf
20240120_Receipt_Starbucks_5.50USD.pdf
```

---

## 必要なソフトウェア

| ソフト | 用途 | 費用 |
|--------|------|------|
| Python 3.8以上 | スクリプト実行 | 無料 |
| Tesseract OCR | 画像・PDFのテキスト抽出 | 無料 |
| Poppler | PDFを画像に変換（PDF処理時のみ必要） | 無料 |

追加のPythonライブラリは不要です（標準ライブラリのみ）。

---

## インストール手順

### 1. Python のインストール
https://www.python.org/ からダウンロード・インストール。
インストール時「**Add Python to PATH**」にチェックを入れてください。

### 2. Tesseract OCR のインストール

1. 以下からインストーラーをダウンロード:  
   https://github.com/UB-Mannheim/tesseract/wiki

2. インストール時の重要設定:
   - 「Additional language data」→ **Japanese** を必ず選択 ✅
   - インストール先はデフォルト推奨:  
     `C:\Program Files\Tesseract-OCR\`

### 3. Poppler のインストール（PDF処理に必要）

1. 以下からWindows版をダウンロード（最新のRelease）:  
   https://github.com/oschwartz10612/poppler-windows/releases

2. ZIPを解凍して任意の場所に配置:  
   例: `C:\Program Files\poppler\`

3. フォルダ内に `Library\bin\pdftoppm.exe` があることを確認

---

## セットアップ手順

1. このフォルダ（`invoice_renamer_tesseract`）をわかりやすい場所に置く  
   例: `C:\Tools\invoice_renamer_tesseract\`

2. **`setup.py` を右クリック →「管理者として実行」**

3. セットアップ画面で:
   - Tesseract・Popplerのパスを確認（「参照」ボタンで変更可）
   - 「パスを保存・確認」をクリック → ✅ が出ればOK
   - 「右クリックメニューに登録」をクリック

4. エクスプローラーを再起動 → 完了！

---

## 使い方

1. PDF または画像ファイルを **右クリック**
2. **「証憑リネーム（ローカルOCR）」** を選択
3. OCR処理後、結果ダイアログが表示されてファイル名が変わります

複数ファイルを選択して一括リネームも可能です。

---

## 対応ファイル形式

`.pdf` `.png` `.jpg` `.jpeg` `.tiff` `.tif` `.bmp` `.gif` `.webp`

---

## 命名規則

| 項目 | 内容 |
|------|------|
| 日付 | 文書内の発行日（yyyymmdd）。不明な場合は `00000000` |
| 書類種別 | 請求書 / 領収書（レシートも含む） / Invoice / Receipt |
| 取引先 | 御中・様の前の社名、または会社形態を含む文字列 |
| 識別子 | 領収書No・Invoice No.（なければ省略） |
| インボイス有無 | T番号または「登録番号」があれば「インボイス有」（国内のみ） |
| 金額 | 合計金額（国内は「円」付き、海外は通貨コード付き） |

---

## 摘要自動生成機能

リネームと同時に、**経理入力用の摘要案**を自動生成します。  
処理完了ダイアログに摘要案が表示されます。

**出力形式:**
```
取引先／内容／国内取引
取引先／内容／海外取引
```

**出力例:**
```
HYATT REGENCY KL MIDTOWN／宿泊費／海外取引
Grab／交通費／海外取引
OpenAI／クラウドサービス利用料／海外取引
セブンイレブン／消耗品購入／国内取引
```

### 組み込みルール一覧

OCRテキスト内のキーワードから内容を自動判定します。

| 判定内容 | キーワード例 |
|----------|-------------|
| 宿泊費 | hotel, hyatt, hilton, inn, 宿泊, ホテル |
| 交通費 | taxi, uber, grab, 交通, タクシー, airline, flight |
| 飲食代 | restaurant, cafe, coffee, starbucks, 飲食, 食事 |
| クラウドサービス利用料 | openai, aws, azure, google cloud, github, subscription |
| 備品購入 | monitor, keyboard, mouse, pc, 備品, 消耗品 |
| 教育研修費 | seminar, training, book, 書籍, セミナー, 研修 |
| 広告宣伝費 | advertising, 広告, 宣伝, マーケティング |
| 送料 | delivery, shipping, fedex, dhl, 配送, 送料 |
| 請求書 | いずれも該当しない請求書・Invoice |
| 経費 | 上記いずれにも該当しない場合 |

### 摘要ルールのカスタマイズ（vendor_rules.json）

独自のキーワードルールを追加したい場合は、スクリプトと同じフォルダに
`vendor_rules.json` を作成してください。  
組み込みルールより**優先的に**評価されます。

**vendor_rules.json の書き方:**
```json
[
  {
    "keywords": ["acme", "acme corp"],
    "content": "ソフトウェアライセンス料"
  },
  {
    "keywords": ["cleaners", "cleaning service", "清掃"],
    "content": "清掃費"
  }
]
```

| 項目 | 説明 |
|------|------|
| `keywords` | OCRテキスト内で検索するキーワード（小文字・大文字を区別しない） |
| `content` | キーワードが見つかった場合に使用する摘要名 |

- ファイルがない場合は組み込みルールのみで動作します（エラーにはなりません）
- 複数のルールがある場合、リストの上から順に評価され、最初にヒットしたものが使われます

---

## OCR精度について

| 書類の状態 | 精度の目安 |
|------------|------------|
| デジタルPDF・鮮明な印刷物 | ◎ 高精度 |
| きれいなスキャン（200dpi以上） | ○ 良好 |
| コンビニレシート（感熱紙） | △ やや苦手 |
| 手書き・傾き・低解像度 | △ 苦手 |

精度が低い場合は手動でリネームしてください。

---

## トラブルシューティング

**「Tesseractが見つかりません」**  
→ setup.py でパスを正しく指定してください。デフォルト:  
`C:\Program Files\Tesseract-OCR\tesseract.exe`

**日本語が認識されない**  
→ Tesseractインストール時に「Japanese」言語パックを選択しましたか？  
後から追加する場合は Tesseract の「Languages」フォルダに `jpn.traineddata` を置いてください。

**PDFが処理できない**  
→ Popplerがインストールされているか、パスが正しいか確認してください。

**右クリックメニューが表示されない**  
→ エクスプローラーを再起動（タスクマネージャーで `explorer.exe` を再起動）

---

## ファイル構成

```
invoice_renamer_tesseract/
├── rename_invoice.py  # メイン処理（リネーム＋摘要生成）
├── setup.py           # セットアップ・右クリックメニュー登録
├── config.json        # パス設定（自動生成）
├── vendor_rules.json  # カスタム摘要ルール（任意・手動作成）
└── README.md          # このファイル
```

---

## セキュリティについて

- すべての処理はPC内で完結します
- インターネット接続は一切使用しません
- 書類データが外部サーバーに送信されることはありません
- Google・Microsoft・OpenAI等のクラウドAPIは使用しません
