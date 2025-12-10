# 🎌 日語學習筆記本 (Flask & SQLite)

這個專案是一個基於 Python Flask 框架和 SQLite 資料庫構建的輕量級日語學習筆記本應用程式。它旨在幫助使用者記錄、管理和高效學習日語單字與文法知識點，特別是提供了靈活的單字卡學習和篩選功能。

## 🌟 功能特色

| 區塊 | 功能描述 |
| :--- | :--- |
| **資料管理** | ✏️ **新增與編輯**：可獨立新增、編輯單字/片語及文法項目。 |
| | 📝 **清單瀏覽**：支援單字和文法清單的分頁瀏覽功能。 |
| | 🏷️ **多重分類 (已實作後端架構)**：單字/文法可標註多個分類，便於多維度管理和篩選。 |
| **學習模式** | 🎴 **單字卡學習**：提供專注的單字卡背誦介面。 |
| | ⏯️ **進度記憶**：自動記錄上次背誦進度，可選擇接續或從頭開始。 |
| | 📢 **發音輔助**：單字卡和清單頁面皆支援日語 TTS 語音朗讀功能。 |
| **進階篩選** | 🔍 **多維度篩選**：單字卡模式支援根據「學習內容 (單字/文法)」、「詞性 (僅單字)」和「分類」進行精確篩選。 |

## 🛠️ 技術棧

* **後端框架：** Python / Flask
* **資料庫：** SQLite (使用 `sqlite3` 模組)
* **前端介面：** HTML5 / Bootstrap 5.3 / JavaScript

## 📦 專案結構
jp_test/ ├── app.py # 核心應用程式邏輯 (Flask 路由、DB 互動) ├── jp_db.db # SQLite 資料庫文件 (啟動時自動生成) └── templates/ ├── home.html # 總覽首頁 ├── add_vocab.html # 新增單字表單 ├── add_grammar.html # 新增文法表單 ├── edit_item.html # 編輯單字/文法表單 ├── list_template.html # 清單頁面共用模板 (包含分頁和發音功能) ├── list_vocab.html # 單字清單 ├── list_grammar.html # 文法清單 ├── flashcard_select.html # 單字卡篩選設定頁面 └── flashcard_deck.html # 單字卡學習介面
## 📊 資料庫架構 (多重分類)

為了支援單字/文法的多重分類，專案使用了多對多關係，新增了以下表格：

| 表格名稱 | 主要用途 | 關鍵欄位 |
| :--- | :--- | :--- |
| `vocab_table` | 儲存單字和詞性。 | `id`, `term`, `part_of_speech` |
| `grammar_table` | 儲存文法結構。 | `id`, `term` |
| `categories_table` | 儲存所有唯一的分類名稱。 | `id`, `name` |
| `card_category_mapping` | **多對多關聯表**，連結卡片和分類。 | `card_id`, `category_id`, `item_type` |

## 🚀 安裝與運行

### 1. 環境準備

首先，您需要安裝 Python 和 Flask。建議使用虛擬環境：

```bash
# 建立虛擬環境
python -m venv venv

# 啟用虛擬環境
# Windows:
.\venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# 安裝 Flask
pip install Flask

2. 啟動應用程式
在虛擬環境中，運行您的主程式：

Bash

python app.py
應用程式成功啟動後，請打開瀏覽器，訪問 http://127.0.0.1:5000 即可開始使用。

資料庫初始化： 首次運行時，app.py 會自動執行 init_db() 函數，創建所有必要的表格。