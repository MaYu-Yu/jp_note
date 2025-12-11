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
    # 細分類統一到主分類
    '自動1': '自動', 
    '自動2': '自動', 
    '自動3': '自動',
    '他動1': '他動', 
    '他動2': '他動', 
    '他動3': '他動',
    
    # 非標準或複合詞的統一處理 (如果 Anki 有出現)
    '補動': '動',    # 補足動詞 (例如：〜てくれる) -> 歸類為動詞
    '形': 'い形',   # 泛指形容詞 -> 歸類為 い形
    '不': 'Other',   # 不詳
    '英': 'Other',   # 英文
    
    # 確保所有 MASTER_POS_LIST 簡稱自己映射到自己
    '名': '名', '專': '專', '數': '數', '代': '代', 
    '動': '動', '自動': '自動', '他動': '他動', 
    'い形': 'い形', 'ナ形': 'ナ形',
    '副': '副', '連体詞': '連体詞', '接': '接', '感': '感', 
    '助詞': '助詞', '助動詞': '助動詞', '接尾': '接尾', '接頭': '接頭',
}

# 初始化 OpenCC 轉換器 (保持不變)
try:
    s2t = OpenCC('s2t') 
except Exception as e:
    print("OpenCC 初始化失敗！請確認已執行 'pip install opencc-python-reimplementation'。")
    print(f"錯誤信息: {e}")
    # 這裡不 exit(1)，以防系統允許運行，但用戶沒有 opencc 需求
    # sys.exit(1)

def get_db_connection():
    """與 app.py 相同的資料庫連線函數。"""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

# 🚨 修正點：重新加入 get_or_create_category 函數
def get_or_create_category(conn, category_name):
    """
    檢查分類是否存在。如果不存在，則創建它並返回其 ID。
    """
    cursor = conn.cursor()
    # 1. 檢查分類是否已存在
    cursor.execute("SELECT id FROM category_table WHERE name = ?", (category_name,))
    row = cursor.fetchone()
    
    if row:
        return row[0]
    
    # 2. 如果不存在，則創建它
    cursor.execute("INSERT INTO category_table (name) VALUES (?)", (category_name,))
    conn.commit()
    return cursor.lastrowid
# --- 轉換函數 ---
def map_pos_codes(anki_pos_raw):
    """
    將 Anki 檔案中的原始詞性（包含複合詞）轉換為 app.py 可識別的日文簡稱列表。
    """
    # 1. 正規化分隔符號：Anki 檔案可能使用 '・', '/', ',', 或 ' ' 來分隔複合詞性
    anki_pos_raw = anki_pos_raw.replace('・', ',').replace('/', ',').replace(' ', ',').strip()
    
    # 2. 以逗號分隔 Anki 原始詞性，並去除空白
    anki_pos_list = [p.strip() for p in anki_pos_raw.split(',') if p.strip()]
    
    final_pos_set = set() # 使用集合 (Set) 來自動去除重複的詞性
    
    for anki_pos in anki_pos_list:
        
        # 查找映射。如果找不到，則使用它自己作為簡稱。
        mapped_code = POS_CODE_MAPPER.get(anki_pos, anki_pos) 
        
        final_pos_set.add(mapped_code)
            
    # 3. 確保集合不為空，如果為空則給予預設值 'Other'
    if not final_pos_set:
        return 'Other'

    # 4. 根據 app.py 的前端預期格式，以 ', ' 連接 (逗號+空格)
    return ', '.join(sorted(list(final_pos_set))) 


# --- 核心匯入函數 ---

def import_anki_data(filepath):
    """
    從指定的 Anki 檔案匯入單字數據。
    """
    if not os.path.exists(filepath):
        print(f"❌ 檔案未找到：{filepath}")
        return

    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. 提取並創建分類名稱
    base_name = os.path.basename(filepath)
    category_name = os.path.splitext(base_name)[0]
    
    if not category_name:
        category_name = "Imported Vocab"

    # 🚨 修正點：調用 get_or_create_category (現在它已在上方定義)
    category_id = get_or_create_category(conn, category_name)
    print(f"使用的分類名稱：【{category_name}】，分類 ID：{category_id}")
    
    i = 0
    vocab_imported_count = 0
    category_link_count = 0
    
    try:
        # 使用 'r' 模式，並指定 utf-8 編碼來讀取 Anki 檔案
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.reader(f, delimiter='\t')
            
            # 跳過 Anki 文件的開頭標記行 (假設有兩行標頭: #separator:tab, #html:false)
            for _ in range(2): 
                try: next(reader) 
                except StopIteration: return

            for i, row in enumerate(reader):
                if not row or len(row) < 15: 
                    continue
                
                # Anki 欄位索引: 1=Term, 3=POS, 5=Explanation(SC), 10=Example(Raw)
                term_raw = row[1].strip()       
                pos_raw = row[3].strip()        
                explanation_raw = row[5].strip() 
                example_raw = row[10].strip()    
                
                if not term_raw or not explanation_raw:
                    continue 
                
                # --- 數據清理與正規化 ---
                
                # 1. 執行詞性代碼轉換
                pos_cleaned = map_pos_codes(pos_raw) 
                
                # 2. 簡體中文轉換為繁體中文
                explanation_tc = s2t.convert(explanation_raw)
                
                # 3. 清理例句 (去除 Anki 的發音標記 [ ] )
                example_sentence = re.sub(r'\[.+?\]', '', example_raw).strip()
                term = term_raw
                
                # 1. 插入到 vocab_table
                cursor.execute("""
                    INSERT INTO vocab_table (term, part_of_speech, explanation, example_sentence)
                    VALUES (?, ?, ?, ?)
                """, (term, pos_cleaned, explanation_tc, example_sentence)) 
                
                vocab_id = cursor.lastrowid 
                vocab_imported_count += 1
                
                # 2. 插入到 item_category_table (連結分類)
                cursor.execute("""
                    INSERT INTO item_category_table (item_id, category_id, item_type)
                    VALUES (?, ?, ?)
                """, (vocab_id, category_id, 'vocab'))
                category_link_count += 1
                
            conn.commit()
            print("\n----------------------------------------------")
            print(f"✅ 檔案【{category_name}】匯入成功！")
            print(f"   -> 匯入單字總數: {vocab_imported_count} 筆")
            print(f"   -> 連結到分類的項目數: {category_link_count} 筆")
            print("----------------------------------------------")
            
    except Exception as e:
        print(f"\n❌ 匯入檔案【{category_name}】過程中發生錯誤 (第 {i+1} 行): {e}")
        conn.rollback()
    finally:
        conn.close()


if __name__ == '__main__':
    
    # 🚨 修正點：處理多個命令列參數
    if len(sys.argv) > 1:
        # 獲取所有從 sys.argv[1] 開始的檔案路徑
        anki_filepaths = sys.argv[1:] 
        
        print(f"\n檢測到 {len(anki_filepaths)} 個檔案，將依序匯入到 {DB_NAME}...")
        
        for filepath in anki_filepaths:
            import_anki_data(filepath)
            
        print("\n==============================================")
        print("🎉 所有檔案匯入完成！")
        print("==============================================")
        
    else:
        # 處理沒有參數或只有一個參數的情況
        print("\n--- Anki 檔案路徑設定 ---")
        anki_filepath = input(f"請輸入 Anki 匯出檔案的路徑（例如：C:/Users/.../NEW-JLPT__NEW-N5.txt）：")

        print(f"\n開始匯入 Anki 數據 ({anki_filepath}) 到 {DB_NAME}...")
        import_anki_data(anki_filepath)