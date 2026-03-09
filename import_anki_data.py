# import_anki_data.py
import sqlite3
import re
import csv
import os
import sys 
from opencc import OpenCC 

# --- 配置區 ---
DB_NAME = 'jp_db.db' 

# 🚨 詞性代碼映射字典 (處理 Anki 細分類/非標準詞性)
POS_CODE_MAPPER = {
    # 細分類統一到主分類 (對應 app.py MASTER_POS_LIST)
    '自動1': '自動', 
    '自動2': '自動', 
    '自動3': '自動',
    '他動1': '他動', 
    '他動2': '他動', 
    '他動3': '他動',
    
    # 新增 自他動 映射
    '自他動1': '自他動', 
    '自他動2': '自他動', 
    '自他動3': '自他動',
    
    # 🚨 修正 #1: 處理 Anki 數據常見的片假名與其他非標準稱呼
    'イ形': 'い形',   # 片假名 'イ形' 映射到 平假名 'い形'
    'ナ形': 'な形',   # 片假名 'ナ形' 映射到 平假名 'ナ形' (N4、N5檔案中是片假名)
    '形': 'い形',     
    '補動': '動',    
    
    # 非標準或複合詞的統一處理 (如果 Anki 有出現)
    '名詞': '名',     # 處理可能出現的完整名稱
    '接頭': '接頭',   # 確保接頭被正確歸類
    
    # 確保所有 MASTER_POS_LIST 簡稱自己映射到自己
    '名': '名', 
    '專': '專', 
    '數': '數', 
    '代': '代', 
    '動': '動', # 主動詞
    '自動': '自動', 
    '他動': '他動', 
    '自他動': '自他動', 
    'い形': 'い形', 
    'ナ形': 'な形',
    '副': '副', 
    '連体詞': '連体詞', 
    '連体': '連体詞',
    '接': '接續', 
    '感': '感嘆', 
    '助詞': '助詞', 
    '助動詞': '助動詞', 
    '接尾': '接尾', 
    '接頭': '接頭',
    'Other': 'Other', 
}

# 詞性繼承/層次結構規則 (不變)
POS_INHERITANCE_RULES = {
    '自動': '動',
    '他動': '動',
    '自他動': '動',
}


# --- OpenCC 初始化 (繁簡轉換) ---

def initialize_opencc():
    """初始化 OpenCC 轉換器 (s2t)"""
    try:
        # 使用 's2t' (Simplified Chinese to Traditional Chinese)
        print("💡 嘗試初始化 OpenCC 繁簡轉換器...")
        return OpenCC('s2t')
    except Exception as e:
        print("🚨 OpenCC 初始化失敗！請確認已執行 'pip install opencc-python-reimplementation'。")
        print(f"錯誤詳情: {e}")
        return None

# 初始化 OpenCC 轉換器，並將實例儲存為全域變數
s2t_converter = initialize_opencc() 

# -------------------------------


def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

# --- 輔助函數 (get_or_create_category, get_or_create_pos, map_pos_codes 不變) ---
def get_or_create_category(conn, category_name):
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM category_table WHERE name = ?", (category_name,))
    row = cursor.fetchone()
    if row:
        return row[0]
    cursor.execute("INSERT INTO category_table (name) VALUES (?)", (category_name,))
    conn.commit()
    return cursor.lastrowid
    
    
def get_or_create_pos(name, conn):
    if not name: return None
    name = name.strip()
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM pos_master_table WHERE name = ?', (name,))
    pos_id_row = cursor.fetchone()
    if pos_id_row:
        return pos_id_row[0]
    else:
        try:
            cursor.execute('INSERT INTO pos_master_table (name) VALUES (?)', (name,))
            conn.commit() 
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            cursor.execute('SELECT id FROM pos_master_table WHERE name = ?', (name,))
            pos_id_row = cursor.fetchone()
            return pos_id_row[0]
        except Exception as e:
            print(f"   [ERROR] 創建詞性 {name} 失敗: {e}")
            return None


def map_pos_codes(anki_pos_raw):
    """
    將 Anki 原始詞性轉換為簡稱列表，並自動添加父級詞性。
    """
    
    # 0. A: 移除括號/方括號內的內容，以清理雜項分類
    # 範例: 'い形(連体)' -> 'い形'
    anki_pos_raw = re.sub(r'[\(\[].+?[\)\]]', '', anki_pos_raw)
    
    # 0. B: 🚨 新增：移除所有空白字元 (空格、tab、換行等隱藏字元)，以確保字串能準確匹配
    anki_pos_raw = re.sub(r'\s', '', anki_pos_raw) 
    
    # 1. 正規化分隔符號：將 Anki 中常見的分隔符統一為逗號
    anki_pos_raw = anki_pos_raw.replace('・', ',').replace('/', ',').strip()
    
    # 2. 以逗號分隔 Anki 原始詞性，並去除空白
    anki_pos_list = [p.strip() for p in anki_pos_raw.split(',') if p.strip()]
    
    final_pos_set = set() # 使用集合 (Set) 來自動去除重複的詞性
    
    for anki_pos in anki_pos_list:
        
        # 🚨 檢查是否為空，再次清理一次以防萬一
        anki_pos = anki_pos.strip() 
        if not anki_pos: continue
        
        # 關鍵修正：如果找不到 Key，則使用預設值 'Other'
        mapped_code = POS_CODE_MAPPER.get(anki_pos, 'Other') 
        
        if mapped_code == 'Other' and anki_pos != 'Other':
            # 🚨 Debug 行：輸出被強制轉換為 Other 的原始詞性 (可幫助您未來手動擴展 POS_CODE_MAPPER)
            print(f"   [DEBUG] 原始詞性 '{anki_pos}' 未在 POS_CODE_MAPPER 中定義，映射為 'Other'")
        
        # 3. 檢查並添加父級詞性 (繼承邏輯)
        
        # 首先添加詞性本身
        final_pos_set.add(mapped_code)
        
        # 然後檢查繼承規則 
        parent_pos = POS_INHERITANCE_RULES.get(mapped_code)
        if parent_pos:
            final_pos_set.add(parent_pos)
            
    # 4. 確保集合不為空
    if not final_pos_set:
        final_pos_set.add('Other')

    # 5. 返回一個列表 (list)
    return list(final_pos_set) 


# --- 核心匯入函數 (import_anki_data) ---

def import_anki_data(filepath):
    if not os.path.exists(filepath):
        print(f"❌ 檔案未找到：{filepath}")
        return

    conn = get_db_connection()
    cursor = conn.cursor()

    base_name = os.path.basename(filepath)
    category_name = os.path.splitext(base_name)[0]
    
    if not category_name:
        category_name = "Imported Vocab"

    category_id = get_or_create_category(conn, category_name)
    print(f"使用的分類名稱：【{category_name}】，分類 ID：{category_id}")
    
    i = 0
    vocab_imported_count = 0
    category_link_count = 0
    pos_link_count = 0
    
    # 🚨 使用全域 OpenCC 變數 (s2t_converter)
    global s2t_converter
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.reader(f, delimiter='\t')
            
            # 跳過 Anki 導出的前兩行 (通常是標籤或卡片名稱)
            for _ in range(2): 
                try: next(reader) 
                except StopIteration: return

            for i, row in enumerate(reader):
                if not row or len(row) < 15: 
                    continue
                
                term_raw = row[1].strip()       
                pos_raw = row[3].strip()        
                explanation_raw = row[5].strip() 
                example_raw = row[10].strip()    
                
                if not term_raw or not explanation_raw:
                    continue 
                
                # --- 數據清理與正規化 (修改區) ---
                
                # 1. 先取得純淨的單字 (移除原始可能存在的 [...])
                term_cleaned = re.sub(r'\[.+?\]', '', term_raw).strip() 
                
                # 2. 取得讀音 (New-N5.txt 中讀音在 index 4)
                reading_raw = row[4].strip()
                
                # 3. 智能組裝 Term + [Reading]
                # 過濾掉：讀音為空、讀音與單字相同(純假名)、讀音是詞源說明(以左括號開頭)
                if reading_raw and reading_raw != term_cleaned and not reading_raw.startswith('('):
                    term = f"{term_cleaned}[{reading_raw}]"
                else:
                    term = term_cleaned
                
                # ----------------------------------
                
                pos_list_cleaned = map_pos_codes(pos_raw) 
                
                # 確保使用 s2t_converter 進行轉換
                explanation_tc = explanation_raw
                if s2t_converter:
                    explanation_tc = s2t_converter.convert(explanation_raw)
                
                example_sentence = re.sub(r'\[.+?\]', '', example_raw).strip()
                
                # 1. 插入到 vocab_table
                cursor.execute("""
                    INSERT INTO vocab_table (term, explanation, example_sentence)
                    VALUES (?, ?, ?)
                """, (term, explanation_tc, example_sentence)) # 注意這裡使用的是修正後的 term
                
                vocab_id = cursor.lastrowid 
                vocab_imported_count += 1
                
                # 2. 插入到 item_category_table (連結分類)
                cursor.execute("""
                    INSERT INTO item_category_table (item_id, category_id, item_type)
                    VALUES (?, ?, ?)
                """, (vocab_id, category_id, 'vocab'))
                category_link_count += 1
                
                # 3. 處理詞性連結表 (item_pos_table)
                for pos_abbr in pos_list_cleaned:
                    pos_id = get_or_create_pos(pos_abbr, conn) 
                    if pos_id:
                        try:
                            cursor.execute(
                                'INSERT INTO item_pos_table (item_id, pos_id) VALUES (?, ?)',
                                (vocab_id, pos_id)
                            )
                            pos_link_count += 1
                        except sqlite3.IntegrityError:
                            pass
                
            conn.commit()
            print("\n----------------------------------------------")
            print(f"✅ 檔案【{category_name}】匯入成功！")
            print(f"   -> 匯入單字總數: {vocab_imported_count} 筆")
            print(f"   -> 分類連結數: {category_link_count} 筆")
            print(f"   -> 詞性連結數: {pos_link_count} 筆") 
            print("----------------------------------------------")
            
    except Exception as e:
        print(f"\n❌ 匯入檔案【{category_name}】過程中發生錯誤 (第 {i+1} 行): {e}")
        conn.rollback()
    finally:
        conn.close()


if __name__ == '__main__':
    
    if len(sys.argv) > 1:
        anki_filepaths = sys.argv[1:] 
        
        print(f"\n檢測到 {len(anki_filepaths)} 個檔案，將依序匯入到 {DB_NAME}...")
        
        for filepath in anki_filepaths:
            import_anki_data(filepath)
            
        print("\n==============================================")
        print("🎉 所有檔案匯入完成！")
        print("==============================================")
        
    else:
        print("\n--- Anki 檔案路徑設定 ---")
        anki_filepath = input(f"請輸入 Anki 匯出檔案的路徑（例如：C:/Users/.../NEW-JLPT__NEW-N5.txt）：")

        print(f"\n開始匯入 Anki 數據 ({anki_filepath}) 到 {DB_NAME}...")
        import_anki_data(anki_filepath)