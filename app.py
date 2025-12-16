# app.py

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
import sqlite3
import math
from datetime import datetime
import os, random
# import json 
# import re 

app = Flask(__name__)
# 💡 請務必修改為您自己的複雜字串！
app.secret_key = 'your_super_secret_key' 
DB_NAME = 'jp_db.db'
PER_PAGE = 20 # 每頁顯示 20 筆資料
BATCH_SIZE = 50 # 每批載入的卡片數量，已調整為 50 以符合您的 API 函數

# 詞性列表 (用於單字詞性篩選與新增快捷鍵)
MASTER_POS_LIST_RAW = [
    # --- 主要詞類 ---
    '名 (名詞)', 
    '專 (專有名詞)', 
    '數 (數詞)', 
    '代 (代名詞)',  
    
    # --- 動詞類 ---
    '動 (動詞)',      
    '自動 (自動詞)',  
    '他動 (他動詞)',  
    '自他動 (自他動詞)',  
    # --- 形容詞類 ---
    'い形 (い形容詞)',
    'ナ形 (な形容詞)',
    
    # --- 獨立詞類 ---
    '副 (副詞)', 
    '連体詞 (連體詞)',
    '接續 (接續詞)', 
    '感嘆 (感嘆詞)', 
    
    # --- 附屬詞/其他 ---
    '助詞 (助詞)',     
    '助動詞 (助動詞)',  
    '接尾 (接尾詞)',    
    '接頭 (接頭詞)',    
    
    # --- 備用/不常見 ---
    'Other (其他)'     
]
# 預處理詞性列表，只保留縮寫 (例如: '名')
MASTER_POS_LIST = [pos.split(' ')[0].strip() for pos in MASTER_POS_LIST_RAW]

# ----------------- 資料庫工具函數 -----------------

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def get_table_name(data_type):
    return 'vocab_table' if data_type == 'vocab' else 'grammar_table'

# ----------------- 修正點: 資料庫初始化與正規化 -----------------

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. 單字表 (移除 part_of_speech 欄位)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS vocab_table (
            id INTEGER PRIMARY KEY,
            term TEXT NOT NULL,
            explanation TEXT,
            example_sentence TEXT
        )
    ''')
    
    # 2. 文法表 (不變)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS grammar_table (
            id INTEGER PRIMARY KEY,
            term TEXT NOT NULL,
            explanation TEXT,
            example_sentence TEXT
        )
    ''')
    
    # 3. 分類主表 (Normalization - 不變)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS category_table (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE NOT NULL
        )
    ''')

    # 4. 項目-分類 連結表 (Normalization - 不變)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS item_category_table (
            item_id INTEGER NOT NULL,
            item_type TEXT NOT NULL, 
            category_id INTEGER NOT NULL,
            PRIMARY KEY (item_id, item_type, category_id),
            FOREIGN KEY(category_id) REFERENCES category_table(id) ON DELETE CASCADE
        )
    ''')
    
    # 5. 詞性主表 (New Table)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pos_master_table (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE NOT NULL
        )
    ''')
    
    # 6. 項目-詞性 連結表 (New Table)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS item_pos_table (
            item_id INTEGER NOT NULL,
            pos_id INTEGER NOT NULL,
            PRIMARY KEY (item_id, pos_id),
            FOREIGN KEY(item_id) REFERENCES vocab_table(id) ON DELETE CASCADE,
            FOREIGN KEY(pos_id) REFERENCES pos_master_table(id) ON DELETE CASCADE
        )
    ''')
    
    conn.commit()
    
    # 7. 填充 pos_master_table
    # 🚨 關鍵: 確保所有詞性都存在於主表中
    for pos_abbr in MASTER_POS_LIST:
        try:
            cursor.execute('INSERT INTO pos_master_table (name) VALUES (?)', (pos_abbr,))
        except sqlite3.IntegrityError:
            # 詞性已存在，忽略
            pass
            
    conn.commit()
    conn.close()

# ----------------- 詞性處理工具函數 (NEW) -----------------

def get_pos_id(name, conn):
    """取得詞性ID，必須從 pos_master_table 獲得。返回 pos_id"""
    if not name:
        return None
        
    name = name.strip()
    cursor = conn.cursor()
    
    cursor.execute('SELECT id FROM pos_master_table WHERE name = ?', (name,))
    pos_id = cursor.fetchone()
    
    return pos_id[0] if pos_id else None

def update_item_pos(item_id, pos_list, conn):
    """處理一個單字項目的詞性更新，包括刪除舊的並插入新的。"""
    if not conn:
        return

    cursor = conn.cursor()
    
    # 1. 刪除該項目所有舊的詞性連結
    cursor.execute('DELETE FROM item_pos_table WHERE item_id = ?', (item_id,))

    # 2. 處理並插入新的詞性連結
    if pos_list:
        for pos_abbr in set(pos_list): # 使用 set 避免重複
            pos_id = get_pos_id(pos_abbr, conn)
            if pos_id:
                try:
                    cursor.execute(
                        'INSERT INTO item_pos_table (item_id, pos_id) VALUES (?, ?)',
                        (item_id, pos_id)
                    )
                except sqlite3.IntegrityError:
                    pass

def get_item_pos_string(item_id):
    """根據 item_id 查詢並返回詞性字串 (名, 動, 自動)"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT T2.name FROM item_pos_table AS T1
        JOIN pos_master_table AS T2 ON T1.pos_id = T2.id
        WHERE T1.item_id = ?
    ''', (item_id,))
    
    pos_list = [row['name'] for row in cursor.fetchall()]
    conn.close()
    return ','.join(pos_list)

# ----------------- 分類處理工具函數 (不變) -----------------

def get_or_create_category(name, conn):
    """取得分類ID，如果不存在則創建它。返回 category_id"""
    if not name:
        return None
        
    name = name.strip()
    cursor = conn.cursor()
    
    # 查詢現有分類
    cursor.execute('SELECT id FROM category_table WHERE name = ?', (name,))
    category_id = cursor.fetchone()

    if category_id:
        return category_id[0]
    else:
        # 創建新分類
        cursor.execute('INSERT INTO category_table (name) VALUES (?)', (name,))
        return cursor.lastrowid

def update_item_categories(item_id, item_type, category_string, conn):
    """處理一個項目的分類更新，包括刪除舊的並插入新的。"""
    if not conn:
        return

    cursor = conn.cursor()
    
    # 1. 刪除該項目所有舊的分類連結 (解決孤兒連結問題)
    cursor.execute('DELETE FROM item_category_table WHERE item_id = ? AND item_type = ?', (item_id, item_type))

    # 2. 處理並插入新的分類連結
    if category_string:
        categories = [c.strip() for c in category_string.split(',') if c.strip()]
        
        for cat_name in set(categories): # 使用 set 避免重複
            category_id = get_or_create_category(cat_name, conn)
            if category_id:
                try:
                    cursor.execute(
                        'INSERT INTO item_category_table (item_id, item_type, category_id) VALUES (?, ?, ?)',
                        (item_id, item_type, category_id)
                    )
                except sqlite3.IntegrityError:
                    pass

def get_item_categories_string(item_id, item_type):
    """根據 item_id 和 item_type 查詢並返回分類字串 (N5, 動詞)"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT T2.name FROM item_category_table AS T1
        JOIN category_table AS T2 ON T1.category_id = T2.id
        WHERE T1.item_id = ? AND T1.item_type = ?
    ''', (item_id, item_type))
    
    categories = [row['name'] for row in cursor.fetchall()]
    conn.close()
    return ', '.join(categories)

# ----------------- 首頁與清單 (不變) -----------------

@app.route('/')
def home():
    return render_template('home.html')

def get_all_categories():
    """獲取所有分類名稱的列表"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT name FROM category_table ORDER BY name')
    categories = [row['name'] for row in cursor.fetchall()]
    conn.close()
    return categories

@app.route('/categories_overview')
def categories_overview():
    categories = get_all_categories_with_counts()
    return render_template('categories_overview.html', categories=categories)

def get_all_categories_with_counts():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT 
            T1.name, 
            COUNT(T2.item_id) AS count
        FROM category_table AS T1
        LEFT JOIN item_category_table AS T2 ON T1.id = T2.category_id
        GROUP BY T1.name
        ORDER BY T1.name
    ''')
    
    categories = [{'name': row['name'], 'count': row['count']} for row in cursor.fetchall()]
    conn.close()
    return categories
@app.route('/api/edit_category/<old_name>', methods=['POST'])
def api_edit_category(old_name):
    """API 路由：編輯分類名稱。"""
    conn = get_db_connection()
    try:
        data = request.get_json()
        new_name = data.get('new_name', '').strip()

        if not new_name:
            return jsonify({'success': False, 'message': '新的分類名稱不能為空'}), 400
        
        if new_name == old_name:
            # 檢查舊名稱是否真的存在
            cursor = conn.cursor()
            cursor.execute('SELECT id FROM category_table WHERE name = ?', (old_name,))
            if cursor.fetchone():
                 return jsonify({'success': True, 'message': '名稱未更改'}), 200 # 無需變更
            else:
                 return jsonify({'success': False, 'message': '原分類不存在'}), 404

        cursor = conn.cursor()
        
        # 檢查新的分類名稱是否已存在 (避免唯一性約束錯誤)
        cursor.execute('SELECT id FROM category_table WHERE name = ?', (new_name,))
        if cursor.fetchone():
            return jsonify({'success': False, 'message': f'分類名稱「{new_name}」已存在。'}), 409

        # 1. 更新 category_table 中的名稱 (item_category_table 會通過外鍵關係保持正確)
        cursor.execute('UPDATE category_table SET name = ? WHERE name = ?', (new_name, old_name))
        
        if cursor.rowcount == 0:
            return jsonify({'success': False, 'message': '分類不存在或無法找到'}), 404

        conn.commit()
        flash(f'分類名稱已從「{old_name}」成功更改為「{new_name}」！', 'success')
        return jsonify({'success': True})
    except sqlite3.Error as e:
        conn.rollback()
        # 由於已檢查，此處主要處理其他可能的資料庫錯誤
        return jsonify({'success': False, 'message': f'資料庫錯誤: {e}'}), 500
    finally:
        conn.close()
@app.route('/api/delete_category/<category_name>', methods=['POST'])
def api_delete_category(category_name):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # 1. 查找分類 ID
        cursor.execute('SELECT id FROM category_table WHERE name = ?', (category_name,))
        category_id = cursor.fetchone()
        
        if not category_id:
            return jsonify({'success': False, 'message': '分類不存在'}), 404
            
        category_id = category_id[0]
        
        # 2. 刪除 item_category_table 中的所有相關連結
        cursor.execute('DELETE FROM item_category_table WHERE category_id = ?', (category_id,))
        
        # 3. 刪除 category_table 中的分類
        cursor.execute('DELETE FROM category_table WHERE id = ?', (category_id,))
        
        conn.commit()
        flash(f'分類「{category_name}」已從所有筆記中移除！', 'success')
        return jsonify({'success': True})
    except sqlite3.Error as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        conn.close()

# ----------------- 新增 (MODIFIED) -----------------

@app.route('/add/<data_type>', methods=['GET', 'POST'])
def add_item(data_type):
    if data_type not in ['vocab', 'grammar']:
        return redirect(url_for('home'))

    conn = get_db_connection()
    all_categories = get_all_categories()
    
    if request.method == 'POST':
        term = request.form['term']
        explanation = request.form['explanation']
        example_sentence = request.form.get('example_sentence', '')

        # 獲取分類數據
        selected_categories = request.form.getlist('selected_categories')
        new_categories_str = request.form.get('new_categories', '')
        combined_categories = selected_categories + [c.strip() for c in new_categories_str.split(',') if c.strip()]
        category_string = ','.join(set(combined_categories))
        
        # 獲取詞性數據 (僅 vocab)
        selected_pos_list = request.form.getlist('selected_pos') # NEW
        
        try:
            cursor = conn.cursor()
            
            if data_type == 'vocab':
                # 🚨 關鍵修改：從 SQL 語句中移除 part_of_speech 欄位
                cursor.execute(
                    'INSERT INTO vocab_table (term, explanation, example_sentence) VALUES (?, ?, ?)',
                    (term, explanation, example_sentence)
                )
            else:
                # grammar
                cursor.execute(
                    'INSERT INTO grammar_table (term, explanation, example_sentence) VALUES (?, ?, ?)',
                    (term, explanation, example_sentence)
                )
            
            item_id = cursor.lastrowid
            
            # 處理分類連結表
            update_item_categories(item_id, data_type, category_string, conn)
            
            # 處理詞性連結表 (僅 vocab)
            if data_type == 'vocab':
                update_item_pos(item_id, selected_pos_list, conn) # NEW
            
            conn.commit()
            flash(f'{data_type}「{term}」已成功新增！', 'success')
            return redirect(url_for(f'add_{data_type}'))
        except sqlite3.Error as e:
            conn.rollback()
            flash(f'新增失敗: {e}', 'danger')
        finally:
            conn.close()

    # GET 請求
    template_name = f'add_{data_type}.html'
    return render_template(template_name, master_pos_list=MASTER_POS_LIST_RAW, all_categories=all_categories)

@app.route('/add/vocab', methods=['GET', 'POST'])
def add_vocab():
    # 🔑 新增：從 URL 參數中讀取分類
    initial_category = request.args.get('category', None)
    
    if request.method == 'POST':
        return add_item('vocab')
    
    return render_template('add_vocab.html', 
                           master_pos_list=MASTER_POS_LIST_RAW,
                           all_categories=get_all_categories(), 
                           initial_category=initial_category 
                          )

@app.route('/add/grammar', methods=['GET', 'POST'])
def add_grammar():
    # 🔑 新增：從 URL 參數中讀取分類
    initial_category = request.args.get('category', None)
    
    if request.method == 'POST':
        return add_item('grammar')

    return render_template('add_grammar.html', 
                           all_categories=get_all_categories(), 
                           # 🔑 傳遞給模板
                           initial_category=initial_category
                          )

# ----------------- 清單頁面 (MODIFIED) -----------------
# ----------------- 分頁輔助類別 (用於滿足 list_template.html 的 Jinja 結構) -----------------
class PaginationMock:
    """模擬 Flask-SQLAlchemy 的 Pagination 物件，以供 list_template.html 模板使用"""
    def __init__(self, page, pages):
        self.page = page
        self.pages = pages
        self.has_prev = page > 1
        self.has_next = page < pages
        self.prev_num = page - 1
        self.next_num = page + 1
    
    # 實現 iter_pages 邏輯，計算前後五個頁碼和 "..."
    def iter_pages(self, left_edge=1, right_edge=1, left_current=5, right_current=5):
        page_set = set()
        
        # 邊緣頁碼 (left_edge)
        for i in range(1, min(self.pages + 1, left_edge + 1)):
            page_set.add(i)

        # 當前頁碼周圍的頁碼 (left_current, right_current)
        for i in range(max(1, self.page - left_current), min(self.pages + 1, self.page + right_current + 1)):
            page_set.add(i)

        # 邊緣頁碼 (right_edge)
        for i in range(max(1, self.pages - right_edge + 1), self.pages + 1):
            page_set.add(i)

        sorted_pages = sorted(list(page_set))
        final_pages = []
        
        # 插入 ... 符號 (None)
        for i, p in enumerate(sorted_pages):
            if i > 0 and p > final_pages[-1] + 1:
                final_pages.append(None)
            final_pages.append(p)
            
        return final_pages

# ----------------- 查詢組件生成函數 (用於處理 JOIN 和 WHERE 條件) -----------------
def _get_query_components(data_type, category, search_term, sort_by_pos=False): 
    """
    根據參數生成基礎查詢的 SELECT/FROM, WHERE 子句和參數列表。
    """
    
    table_name = get_table_name(data_type) 
    
    if data_type not in ['vocab', 'grammar']:
        return None, None, None, None

    term_column = 'term' 

    # 基礎 SELECT 和 FROM
    select_clause = f"T1.id, T1.{term_column}, T1.explanation, T1.example_sentence"
    from_clause = f"FROM {table_name} AS T1"
    where_clauses = []
    params = []
    is_distinct = False

    # 處理分類條件: 必須 JOIN item_category_table 和 category_table
    if category:
        from_clause += """
            JOIN item_category_table AS T2 ON T1.id = T2.item_id 
            JOIN category_table AS T3 ON T2.category_id = T3.id
        """
        # 確保只篩選當前 data_type 的項目
        where_clauses.append("T3.name = ? AND T2.item_type = ?")
        params.extend([category, data_type])
        
        # 由於 JOIN 會產生重複行，必須使用 DISTINCT
        is_distinct = True
        
    # 處理詞性排序條件: 僅在 vocab 模式且需要按詞性排序時加入 JOIN 
    # 由於一個單字可能有多個詞性，這裡使用 LEFT JOIN 並將 T_POS_M.name 加入 SELECT 子句
    if data_type == 'vocab' and sort_by_pos:
        # LEFT JOIN 確保沒有詞性的單字也能被包含
        from_clause += """
            LEFT JOIN item_pos_table AS T_POS ON T1.id = T_POS.item_id 
            LEFT JOIN pos_master_table AS T_POS_M ON T_POS.pos_id = T_POS_M.id
        """
        # 將詞性名稱加入 SELECT 子句，以便排序 (注意：GROUP BY T1.id 會確保單字不重複)
        # 我們將使用 T_POS_M.name 進行排序，並將其包含在 SELECT 中
        select_clause += ", GROUP_CONCAT(T_POS_M.name) AS pos_string_for_sort" 
        
        is_distinct = True # GROUP_CONCAT 需要 GROUP BY

    # 處理搜尋條件 (搜尋範圍涵蓋 term, explanation, example_sentence)
    if search_term:
        # 使用 T1.欄位名稱來避免歧義
        search_query = f"(T1.{term_column} LIKE ? OR T1.explanation LIKE ? OR T1.example_sentence LIKE ?)"
        where_clauses.append(search_query)
        search_param = f"%{search_term}%"
        params.extend([search_param, search_param, search_param])
    
    # 組合 WHERE 子句
    where_clause_str = ""
    if where_clauses:
        where_clause_str = " WHERE " + " AND ".join(where_clauses)
    
    if is_distinct:
        # 如果有 JOIN 且沒有 GROUP BY，則使用 DISTINCT。如果使用了 GROUP_CONCAT，則需要 GROUP BY。
        if sort_by_pos:
            return select_clause, from_clause, where_clause_str, params
        else:
            select_clause = "DISTINCT " + select_clause
        
    return select_clause, from_clause, where_clause_str, params
def _get_base_query_and_params(data_type, category, search_term, sort_by, sort_order):
    """根據參數生成基礎 SQL 查詢和參數列表"""
    if data_type == 'vocab':
        table_name = 'vocab_list'
        term_column = 'term'
    elif data_type == 'grammar':
        table_name = 'grammar_list'
        term_column = 'grammar_rule'
    else:
        return None, None, None

    query = f"SELECT * FROM {table_name}"
    where_clauses = []
    params = []

    if search_term:
        where_clauses.append(f"({term_column} LIKE ? OR explanation LIKE ? OR example_sentence LIKE ?)")
        search_param = f"%{search_term}%"
        params.extend([search_param, search_param, search_param])

    if category:
        where_clauses.append("categories LIKE ?")
        params.append(f"%{category}%")

    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)

    allowed_sorts = {'id': 'id', 'term': term_column, 'timestamp': 'timestamp'}
    sort_column = allowed_sorts.get(sort_by, 'id')
    sort_order = 'DESC' if sort_order.lower() == 'desc' else 'ASC'
    query += f" ORDER BY {sort_column} {sort_order}"

    return query, params, table_name
@app.route('/list/<data_type>', methods=['GET'])
def list_page(data_type):
    page = request.args.get('page', 1, type=int)
    category = request.args.get('category')
    search_term = request.args.get('search')
    sort_by = request.args.get('sort_by', 'id')
    sort_order = request.args.get('sort_order', 'asc')
    
    sort_by_pos = (data_type == 'vocab' and sort_by == 'pos') # 🚨 判斷是否需要按詞性排序
    
    # 1. 獲取查詢組件 (傳入 sort_by_pos)
    select_clause, from_clause, where_clause_str, params = _get_query_components(data_type, category, search_term, sort_by_pos)
    
    if not select_clause:
        flash('錯誤: 無效的資料類型', 'danger')
        return redirect(url_for('home'))

    conn = get_db_connection()
    items = []
    total_items = 0
    total_pages = 1
    pagination = None
    
    try:
        # 2. 計算總筆數 (使用 COUNT(DISTINCT T1.id) 確保計數正確)
        # 由於 COUNT 只計數 ID，我們可以直接使用 T1.id
        count_query_optimized = f"SELECT COUNT(DISTINCT T1.id) FROM {get_table_name(data_type)} AS T1"
        
        # 重新計算 COUNT 所需的 JOIN/WHERE 子句
        # 這裡需要一個僅用於 COUNT 的 SELECT/FROM/WHERE 組件，它不包含 GROUP_CONCAT 或 DISTINCT
        _, count_from_clause, count_where_clause_str, count_params = _get_query_components(data_type, category, search_term, False)
        count_query_optimized = f"SELECT COUNT(DISTINCT T1.id) {count_from_clause} {count_where_clause_str}"
        
        total_items = conn.execute(count_query_optimized, count_params).fetchone()[0]
        
        if total_items > 0:
            total_pages = math.ceil(total_items / PER_PAGE)
            
            # 確保頁碼有效性
            if page < 1:
                page = 1
            elif page > total_pages:
                page = total_pages
            
            # 3. 處理排序
            allowed_sorts = {
                'id': 'T1.id',
                'term': 'T1.term',
                'timestamp': 'T1.id', 
                'pos': 'pos_string_for_sort', # 🚨 關鍵: 按詞性排序
            }
            sort_column = allowed_sorts.get(sort_by, 'T1.id') 
            
            # 處理詞性排序 (NULLs first/last)
            if sort_by == 'pos':
                # 讓沒有詞性的項目排在最後 (NULLS LAST)
                order_by_clause = f" ORDER BY {sort_column} IS NULL ASC, {sort_column} "
                sort_order_sql = 'DESC' if sort_order.lower() == 'desc' else 'ASC'
                order_by_clause += sort_order_sql
            else:
                sort_order_sql = 'DESC' if sort_order.lower() == 'desc' else 'ASC'
                order_by_clause = f" ORDER BY {sort_column} {sort_order_sql}"
            
            # 4. 執行分頁查詢 (LIMIT/OFFSET)
            offset = (page - 1) * PER_PAGE
            
            # 完整的 ITEMS 查詢
            items_query = f"SELECT {select_clause} {from_clause} {where_clause_str}"
            
            if sort_by_pos:
                # 如果按詞性排序，必須加上 GROUP BY T1.id
                items_query += " GROUP BY T1.id" 

            items_query += f" {order_by_clause} LIMIT ? OFFSET ?"
            
            items_raw = conn.execute(items_query, params + [PER_PAGE, offset]).fetchall()
            
            # 5. 處理項目詳細信息 (分類和詞性)
            items = []
            # 必須使用您原有的工具函數來獲取分類和詞性字串
            for item_row in items_raw:
                item_dict = dict(item_row)
                item_id = item_dict['id']
                
                # 獲取分類字串 (需要 get_item_categories_string 函數存在)
                item_dict['categories'] = get_item_categories_string(item_id, data_type)
                
                if data_type == 'vocab':
                    # 獲取詞性字串 (需要 get_item_pos_string 函數存在)
                    # 即使查詢中已經有 pos_string_for_sort，我們仍使用原函數以確保邏輯一致
                    item_dict['pos_string'] = get_item_pos_string(item_id)
                    
                items.append(item_dict)

            # 6. 創建模擬的分頁物件
            pagination = PaginationMock(page=page, pages=total_pages)
        else:
            page = 1 

    except Exception as e:
        # 打印錯誤以便調試
        print(f"資料庫查詢錯誤: {e}") 
        flash(f'資料庫查詢失敗: {e}', 'danger')
        total_items = 0
        total_pages = 1
        page = 1
        pagination = None # 確保錯誤時不顯示分頁 UI

    finally:
        conn.close()

    # 7. 渲染模板
    return render_template('list_template.html', 
        data_type=data_type,
        items=items,
        pagination=pagination,       
        current_page=page,           
        total_pages=total_pages,     
        total_items=total_items,     
        current_category=category,
        search_term=search_term,
        sort_by=sort_by,
        sort_order=sort_order,
        per_page=PER_PAGE            
    )
# ----------------- 編輯 (MODIFIED) -----------------

@app.route('/edit/<data_type>/<int:item_id>', methods=['GET', 'POST'])
def edit_item(data_type, item_id):
    if data_type not in ['vocab', 'grammar']:
        return redirect(url_for('home'))

    table_name = get_table_name(data_type)
    data_type_display = '單字' if data_type == 'vocab' else '文法'
    conn = get_db_connection()
    all_categories = get_all_categories()
    
    if request.method == 'POST':
        term = request.form['term']
        explanation = request.form['explanation']
        example_sentence = request.form.get('example_sentence', '')

        selected_categories = request.form.getlist('selected_categories')
        new_categories_str = request.form.get('new_categories', '')
        
        combined_categories = selected_categories + [c.strip() for c in new_categories_str.split(',') if c.strip()]
        category_string = ','.join(set(combined_categories))
        
        # 獲取詞性數據 (僅 vocab)
        selected_pos_list = request.form.getlist('selected_pos') # NEW

        try:
            cursor = conn.cursor()
            
            # 1. 更新主表
            if data_type == 'vocab':
                # 🚨 關鍵修改：從 UPDATE 語句中移除 part_of_speech
                cursor.execute(
                    f'UPDATE {table_name} SET term=?, explanation=?, example_sentence=? WHERE id=?',
                    (term, explanation, example_sentence, item_id)
                )
            else:
                cursor.execute(
                    f'UPDATE {table_name} SET term=?, explanation=?, example_sentence=? WHERE id=?',
                    (term, explanation, example_sentence, item_id)
                )

            # 2. 更新分類連結表
            update_item_categories(item_id, data_type, category_string, conn)
            
            # 3. 更新詞性連結表 (僅 vocab)
            if data_type == 'vocab':
                update_item_pos(item_id, selected_pos_list, conn) # NEW
            
            conn.commit()
            flash(f'{data_type_display}「{term}」已成功更新！', 'success')
            return redirect(url_for('list_page', data_type=data_type))
        except sqlite3.Error as e:
            conn.rollback()
            flash(f'更新失敗: {e}', 'danger')
        finally:
            conn.close()

    # GET 請求
    cursor = conn.cursor()
    cursor.execute(f'SELECT * FROM {table_name} WHERE id = ?', (item_id,))
    item = cursor.fetchone()
    conn.close()

    if item is None:
        flash(f'找不到 ID 為 {item_id} 的 {data_type_display}。', 'danger')
        return redirect(url_for('list_page', data_type=data_type))

    item = dict(item) 
    item['categories'] = get_item_categories_string(item_id, data_type)
    
    # 🚨 關鍵：獲取詞性字串並轉換為列表，以便在前端預選
    if data_type == 'vocab':
        pos_string = get_item_pos_string(item_id)
        item['selected_pos_list'] = [p.strip() for p in pos_string.split(',') if p.strip()] # NEW
    
    # 傳遞完整的 MASTER_POS_LIST_RAW 給前端，因為前端需要顯示括號內的中文
    return render_template('edit_item.html', item=item, data_type=data_type, all_categories=all_categories, master_pos_list=MASTER_POS_LIST_RAW)

# ----------------- 刪除 (MODIFIED) -----------------

@app.route('/delete/<data_type>/<int:item_id>', methods=['POST'])
def delete_item(data_type, item_id):
    if data_type not in ['vocab', 'grammar']:
        return redirect(url_for('home'))

    table_name = get_table_name(data_type)
    data_type_display = '單字' if data_type == 'vocab' else '文法'
    conn = get_db_connection()
    
    try:
        cursor = conn.cursor()
        
        # 1. 刪除 item_category_table 中的連結
        cursor.execute('DELETE FROM item_category_table WHERE item_id = ? AND item_type = ?', (item_id, data_type))
        
        # 2. 刪除 item_pos_table 中的連結 (僅 vocab)
        if data_type == 'vocab':
            cursor.execute('DELETE FROM item_pos_table WHERE item_id = ?', (item_id,)) # NEW
        
        # 3. 刪除主表中的項目
        cursor.execute(f'DELETE FROM {table_name} WHERE id = ?', (item_id,))
        
        conn.commit()
        flash(f'該筆{data_type_display}已成功刪除。', 'success')
    except sqlite3.Error as e:
        conn.rollback()
        flash(f'刪除失敗: {e}', 'danger')
    finally:
        conn.close()
        
    return redirect(url_for('list_page', data_type=data_type))

# ----------------- 單字卡功能 (MODIFIED) -----------------

@app.route('/flashcard/select')
def flashcard_select():
    all_categories = get_all_categories()
    all_pos = MASTER_POS_LIST_RAW # 傳遞完整列表給前端顯示
    last_filters = session.get('last_flashcard_filters', {})
    
    return render_template('flashcard_select.html', 
                           all_categories=all_categories, 
                           all_pos=all_pos,
                           last_filters=last_filters)

def get_flashcard_query_parts(data_type, category_filter, pos_filter=None):
    """
    建立 Flashcard 查詢的 FROM, JOIN, WHERE 語句和對應的參數。
    返回: (SQL_FRAGMENT, PARAMS)
    
    🚨 關鍵修改: 調整單字表的詞性過濾邏輯以使用 item_pos_table
    """
    
    params = []
    
    if data_type == 'vocab':
        table_name = 'vocab_table'
        item_type = 'vocab'
    elif data_type == 'grammar':
        table_name = 'grammar_table'
        item_type = 'grammar'
    else:
        return ("", [])

    from_join_parts = [f"FROM {table_name} AS T1"]
    where_clauses = ["1=1"]
    
    # 1. Category 過濾
    if category_filter and category_filter != 'all':
        # 使用 INNER JOIN 確保只有包含該分類的項目被選中
        from_join_parts.append(
            f"""INNER JOIN item_category_table AS T2 ON T1.id = T2.item_id AND T2.item_type = '{item_type}'
               INNER JOIN category_table AS T3 ON T2.category_id = T3.id"""
        )
        where_clauses.append("T3.name = ?")
        params.append(category_filter)
    else:
        # 如果不過濾分類，使用 LEFT JOIN (或根本不 JOIN) 以獲取所有項目
        pass # 基礎查詢中暫時不加入 category JOIN，避免 COUNT 重複計算。將過濾邏輯放在 WHERE 條件中 (如果需要)。

    # 2. POS 過濾 (僅針對 vocab)
    if data_type == 'vocab' and pos_filter and pos_filter != 'all':
        pos_abbr = pos_filter.split(' ')[0].strip() if ' ' in pos_filter else pos_filter
        
        # 使用 INNER JOIN item_pos_table 進行詞性過濾
        from_join_parts.append(
            f"""INNER JOIN item_pos_table AS T_POS ON T1.id = T_POS.item_id
               INNER JOIN pos_master_table AS T_POS_M ON T_POS.pos_id = T_POS_M.id"""
        )
        where_clauses.append("T_POS_M.name = ?")
        params.append(pos_abbr)

    # 重新處理 FROM/JOIN 語句
    from_join = " ".join(from_join_parts)
    where_sql = " WHERE " + " AND ".join(where_clauses)
    
    return (f"{from_join} {where_sql}", params)
    
@app.route('/flashcard/data', methods=['POST'])
def flashcard_data():
    data = request.get_json()
    data_type = data.get('data_type', 'all')
    category_filter = data.get('category_filter', 'all')
    pos_filter = data.get('pos_filter', 'all')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    total_count = 0
    count_jobs = [] 

    # 1. 處理單字 (vocab)
    if data_type in ['all', 'vocab']:
        vocab_fragment, vocab_params = get_flashcard_query_parts('vocab', category_filter, pos_filter)
        # 使用 COUNT(DISTINCT T1.id) 避免 JOIN 導致重複計算
        vocab_count_query = f"SELECT COUNT(DISTINCT T1.id) {vocab_fragment}"
        count_jobs.append({'query': vocab_count_query, 'params': vocab_params})
        
    # 2. 處理文法 (grammar)
    if data_type in ['all', 'grammar']:
        grammar_fragment, grammar_params = get_flashcard_query_parts('grammar', category_filter)
        grammar_count_query = f"SELECT COUNT(DISTINCT T1.id) {grammar_fragment}"
        count_jobs.append({'query': grammar_count_query, 'params': grammar_params})
    
    if not count_jobs:
        conn.close()
        return jsonify({'success': False, 'message': '無效的資料類型選擇'}), 400
        
    try:
        for job in count_jobs:
            cursor.execute(job['query'], job['params'])
            total_count += cursor.fetchone()[0] 
    except sqlite3.Error as e:
        conn.close()
        print(f"Database error during count: {e}") 
        return jsonify({'success': False, 'message': f'資料庫查詢錯誤: {e}'}), 500

    conn.close()

    session['last_flashcard_filters'] = data
    session['flashcard_total_count'] = total_count
    session.pop('flashcard_data', None) # 關鍵: 移除大數據

    last_index = session.get('last_flashcard_index', 0)
    if last_index >= total_count:
        last_index = 0
        session['last_flashcard_index'] = 0

    return jsonify({
        'success': True,
        'count': total_count,
        'last_index': last_index 
    })
    
@app.route('/api/get_flashcard/<int:index>', methods=['GET'])
def api_get_flashcard(index):
    """根據 Session 中的篩選條件和指定索引獲取一整個批次卡片。"""
    
    filters = session.get('last_flashcard_filters')
    total_count = session.get('flashcard_total_count', 0)
    
    if not filters or index < 0: 
        return jsonify({'success': False, 'message': '篩選條件無效或索引越界'}), 400
    
    if index >= total_count:
        return jsonify({'success': True, 'cards': []})

    data_type = filters.get('data_type', 'all')
    category_filter = filters.get('category_filter', 'all')
    pos_filter = filters.get('pos_filter', 'all')

    conn = get_db_connection()
    conn.row_factory = sqlite3.Row 
    cursor = conn.cursor()
    
    queries = []
    params = []
    BATCH_SIZE = 20 

    # 1. 處理單字 (vocab)
    if data_type in ['all', 'vocab']:
        # 🚨 關鍵修改 1：移除 T1.part_of_speech，並在前端補上。
        vocab_select = "SELECT T1.id, T1.term, '' AS reading, T1.explanation, T1.example_sentence, 'vocab' as type"
        vocab_fragment, vocab_params = get_flashcard_query_parts('vocab', category_filter, pos_filter)
        vocab_query = f"{vocab_select} {vocab_fragment} GROUP BY T1.id"
        queries.append(vocab_query)
        params.extend(vocab_params)
        
    # 2. 處理文法 (grammar)
    if data_type in ['all', 'grammar']:
        # 修正：確保這裡的欄位與 vocab_select 完全匹配
        grammar_select = "SELECT T1.id, T1.term, '' AS reading, T1.explanation, T1.example_sentence, 'grammar' as type"
        grammar_fragment, grammar_params = get_flashcard_query_parts('grammar', category_filter)
        grammar_query = f"{grammar_select} {grammar_fragment} GROUP BY T1.id"
        queries.append(grammar_query)
        params.extend(grammar_params)
    
    
    # 3. 合併查詢並使用 OFFSET/LIMIT 獲取一整個批次
    final_query = " UNION ALL ".join(queries)
    
    final_query = f"SELECT * FROM ({final_query}) ORDER BY id ASC LIMIT {BATCH_SIZE} OFFSET ?" 
    params.append(index) 

    try:
        cursor.execute(final_query, params)
        card_data_list = cursor.fetchall()
        
        # 4. 🚨 關鍵：手動將詞性資訊附加回單字卡數據中
        cards = []
        for row in card_data_list:
            card_dict = dict(row)
            if card_dict['type'] == 'vocab':
                card_dict['part_of_speech'] = get_item_pos_string(card_dict['id']) # NEW
            else:
                card_dict['part_of_speech'] = ''
            cards.append(card_dict)
            
        conn.close()
        return jsonify({'success': True, 'cards': cards})
        
    except sqlite3.Error as e:
        conn.close()
        print(f"!!! API ERROR: 資料庫查詢錯誤: {e}")
        return jsonify({'success': False, 'message': f'資料庫查詢錯誤: {e}'}), 500
    except Exception as e:
        conn.close()
        print(f"!!! API ERROR: 一般錯誤: {e}")
        return jsonify({'success': False, 'message': f'一般錯誤: {e}'}), 500
        
@app.route('/flashcard/deck')
def flashcard_deck():
    action = request.args.get('action', 'resume')
    
    filters = session.get('last_flashcard_filters', {})
    total_count = session.get('flashcard_total_count', 0) 
    if total_count == 0: 
        flash('請先在設定頁面載入單字卡內容。', 'warning')
        return redirect(url_for('flashcard_select'))

    current_index = session.get('last_flashcard_index', 0) 

    if action == 'start':
        current_index = 0
        session['last_flashcard_index'] = 0

    if total_count > 0:
        if current_index >= total_count: 
             current_index = 0
        current_index = max(0, current_index)
        session['last_flashcard_index'] = current_index
    
    # 建立篩選條件的總結文字 (不變)
    data_map = {'all': '所有內容', 'vocab': '僅單字', 'grammar': '僅文法'}
    type_str = data_map.get(filters.get('data_type'), '未知內容')
    
    parts = [f"內容: {type_str}"]
    
    pos_filter = filters.get('pos_filter')
    if pos_filter and pos_filter != 'all' and filters.get('data_type') != 'grammar':
        parts.append(f"詞性: {pos_filter}")
        
    category_filter = filters.get('category_filter')
    if category_filter and category_filter != 'all':
        parts.append(f"分類: {category_filter}")
        
    summary_text = " | ".join(parts)
    
    return render_template('flashcard_deck.html', 
                           current_index=current_index, 
                           total_count=total_count, 
                           filter_summary=summary_text)
# -------------------------------------------------------------

@app.route('/api/update_index', methods=['POST'])
def update_flashcard_index():
    """接收新的單字卡索引並更新 Session 中的記憶點。"""
    
    data = request.get_json()
    new_index = data.get('index') 
    
    if new_index is None:
        return jsonify({'success': False, 'message': 'Missing index in request body'}), 400
        
    try:
        new_index = int(new_index) 
    except ValueError:
        return jsonify({'success': False, 'message': 'Invalid index type'}), 400
        
    total_count = session.get('flashcard_total_count', 0)
    
    if total_count == 0:
        return jsonify({'success': False, 'message': '單字卡為空，無法更新索引'}), 400
        
    if 0 <= new_index < total_count:
        session['last_flashcard_index'] = new_index
        return jsonify({'success': True, 'new_index': new_index})
    elif new_index >= total_count:
        session['last_flashcard_index'] = 0
        return jsonify({'success': True, 'new_index': 0, 'wrapped': True})
    else: 
        session['last_flashcard_index'] = total_count - 1 
        return jsonify({'success': True, 'new_index': total_count - 1, 'wrapped': True})
# ----------------- 啟動應用程式 -----------------

if __name__ == '__main__':
    # 確保資料庫在應用程式啟動時只創建一次
    init_db() 
    app.run(debug=True)