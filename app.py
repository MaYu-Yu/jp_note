# app.py

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
import sqlite3
import math
from datetime import datetime
import os 
# 雖然這個版本沒有用到 json 和 re，但保留著不影響
# import json 
# import re 

app = Flask(__name__)
# 💡 請務必修改為您自己的複雜字串！
app.secret_key = 'your_super_secret_key' 
DB_NAME = 'jp_db.db'
PER_PAGE = 20 # 每頁顯示 20 筆資料
BATCH_SIZE = 5 # 每批載入的卡片數量，可根據效能調整

# 詞性列表 (用於單字詞性篩選與新增快捷鍵)
MASTER_POS_LIST = [
    # --- 主要詞類 ---
    '名 (名詞)', 
    '專 (專有名詞)', 
    '數 (數詞)', 
    '代 (代名詞)',  # 根據 Anki 檔案新增
    
    # --- 動詞類 ---
    '動 (動詞)',      # 泛指動詞
    '自動 (自動詞)',  # 自動詞 (自動1, 自動2, 自動3)
    '他動 (他動詞)',  # 他動詞 (他動1, 他動2, 他動3)
    
    # --- 形容詞類 ---
    'い形 (い形容詞)',
    'ナ形 (な形容詞)',
    
    # --- 獨立詞類 ---
    '副 (副詞)', 
    '連体詞 (連體詞)',
    '接 (接續詞)', 
    '感 (感嘆詞)', 
    
    # --- 附屬詞/其他 ---
    '助詞 (助詞)',     
    '助動詞 (助動詞)',  
    '接尾 (接尾詞)',    # 例如: 〜やすい
    '接頭 (接頭詞)',    # 例如: お〜、ご〜 (根據 Anki 檔案新增)
    
    # --- 備用/不常見 ---
    'Other (其他)'     # 確保涵蓋所有不常見或無法分類的標籤
]

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def get_table_name(data_type):
    return 'vocab_table' if data_type == 'vocab' else 'grammar_table'

# ----------------- 修正點: 資料庫初始化與正規化 (保持持久化) -----------------

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. 單字表 (持久化且移除 categories 欄位)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS vocab_table (
            id INTEGER PRIMARY KEY,
            term TEXT NOT NULL,
            part_of_speech TEXT,
            explanation TEXT,
            example_sentence TEXT
        )
    ''')

    # 2. 文法表 (持久化且移除 categories 欄位)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS grammar_table (
            id INTEGER PRIMARY KEY,
            term TEXT NOT NULL,
            explanation TEXT,
            example_sentence TEXT
        )
    ''')
    
    # 3. 分類主表 (Normalization)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS category_table (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE NOT NULL
        )
    ''')

    # 4. 項目-分類 連結表 (Normalization - 確保刪除項目時連結也會被刪除)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS item_category_table (
            item_id INTEGER NOT NULL,
            item_type TEXT NOT NULL, 
            category_id INTEGER NOT NULL,
            PRIMARY KEY (item_id, item_type, category_id),
            FOREIGN KEY(category_id) REFERENCES category_table(id) ON DELETE CASCADE
        )
    ''')
    
    conn.commit()
    conn.close()

# ----------------- 分類處理工具函數 (保持不變) -----------------

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

# ----------------- 首頁與清單 (保持不變) -----------------

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

# ----------------- 新增 (保持不變) -----------------

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

        # 獲取分類數據：舊的分類 (選中的) + 新的分類 (輸入的)
        selected_categories = request.form.getlist('selected_categories')
        new_categories_str = request.form.get('new_categories', '')
        
        # 合併並清理分類字串
        combined_categories = selected_categories + [c.strip() for c in new_categories_str.split(',') if c.strip()]
        category_string = ','.join(set(combined_categories))

        try:
            cursor = conn.cursor()
            
            if data_type == 'vocab':
                # 🚨 關鍵：從前端獲取 part_of_speech 欄位的值 (現在來自隱藏欄位)
                part_of_speech = request.form['part_of_speech'] 
                cursor.execute(
                    'INSERT INTO vocab_table (term, part_of_speech, explanation, example_sentence) VALUES (?, ?, ?, ?)',
                    (term, part_of_speech, explanation, example_sentence)
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
    return render_template(template_name, master_pos_list=MASTER_POS_LIST, all_categories=all_categories)

@app.route('/add/vocab')
def add_vocab():
    return add_item('vocab')

@app.route('/add/grammar')
def add_grammar():
    return add_item('grammar')

# ----------------- 清單頁面 (保持不變) -----------------
@app.route('/<data_type>/list', defaults={'page': 1}, methods=['GET'])
@app.route('/<data_type>/list/page/<int:page>', methods=['GET'])
def list_page(data_type, page):
    if data_type not in ['vocab', 'grammar']:
        flash('無效的資料類型!', 'danger')
        return redirect(url_for('home'))

    conn = get_db_connection()
    table_name = get_table_name(data_type)
    current_category = request.args.get('category')
    search_term = request.args.get('search')
    
    # 1. 處理「顯示全部」的邏輯 (關鍵修正點)
    limit_param = request.args.get('limit')
    
    current_limit = PER_PAGE
    is_show_all = False
    
    # 檢查是否為「顯示全部」的指示
    if limit_param in ['0', 'all']: 
        is_show_all = True
        page = 1           # 顯示全部時，強制頁數為 1
        offset = 0         # 忽略偏移量
    else:
        # 一般分頁模式
        offset = (page - 1) * current_limit
    
    # 2. 構建 WHERE 條件 (確保與 category 和 search 篩選相容)
    where_clauses = []
    params = []
    
    # 假設 Category 篩選的邏輯 (需確認您的 app.py 中是否有這部分)
    if current_category:
        category_row = conn.execute("SELECT id FROM category_table WHERE name = ?", (current_category,)).fetchone()
        if category_row:
            category_id = category_row['id']
            where_clauses.append(f"T.id IN (SELECT item_id FROM item_category_table WHERE category_id = ? AND item_type = ?)")
            params.extend([category_id, data_type])
            
    # 假設 Search 篩選的邏輯 (需確認您的 app.py 中是否有這部分)
    if search_term:
        term_column = 'term' if data_type == 'vocab' else 'grammar_term'
        search_like = f'%{search_term}%'
        # 查詢 term、meaning_zh 和 example_sentence 欄位
        where_clauses.append(f"({term_column} LIKE ? OR meaning_zh LIKE ? OR example_sentence LIKE ?)")
        params.extend([search_like, search_like, search_like])

    where_sql = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""
    
    # 3. 獲取總數
    count_sql = f"SELECT COUNT(*) FROM {table_name} T {where_sql}"
    total_count = conn.execute(count_sql, params).fetchone()[0]
    
    # 4. 執行主要的資料查詢 (處理 LIMIT/OFFSET)
    sql_query = f"SELECT T.* FROM {table_name} T {where_sql} ORDER BY T.id DESC"
    
    query_params = list(params) # 複製參數列表
    
    if is_show_all:
        total_pages = 1
        # 顯示全部模式不添加 LIMIT 和 OFFSET
    else:
        # 一般分頁模式
        total_pages = math.ceil(total_count / current_limit) if total_count > 0 else 1
        page = min(page, total_pages) if total_pages > 0 else 1 # 避免頁碼越界
        offset = (page - 1) * current_limit
        
        # 加上 LIMIT 和 OFFSET
        sql_query += " LIMIT ? OFFSET ?"
        query_params.extend([current_limit, offset])

    # 執行查詢
    items = conn.execute(sql_query, query_params).fetchall()
    conn.close()

    return render_template('list_template.html',
                           data_type=data_type,
                           items=items,
                           current_page=page,
                           total_pages=total_pages,
                           per_page=PER_PAGE, # 傳遞原始分頁大小
                           current_category=current_category,
                           search_term=search_term,
                           show_all_mode=is_show_all # 傳遞新狀態到 template
                           )
def get_list_data(data_type, page, category=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    offset = (page - 1) * PER_PAGE
    table_name = get_table_name(data_type)
    
    params = []
    
    if category:
        base_select = f"SELECT T1.*, GROUP_CONCAT(T3.name) AS categories_string FROM {table_name} AS T1"
        join_clause = f"""
            INNER JOIN item_category_table AS T2 ON T1.id = T2.item_id AND T2.item_type = ?
            INNER JOIN category_table AS T3 ON T2.category_id = T3.id
        """
        where_clause = " WHERE T3.name = ?"
        
        params.extend([data_type, category]) 
        
        count_query = f"""
            SELECT COUNT(DISTINCT T1.id) FROM {table_name} AS T1
            INNER JOIN item_category_table AS T2 ON T1.id = T2.item_id AND T2.item_type = ?
            INNER JOIN category_table AS T3 ON T2.category_id = T3.id
            WHERE T3.name = ?
        """
        cursor.execute(count_query, [data_type, category])
        
    else:
        base_select = f"SELECT T1.*, GROUP_CONCAT(T3.name) AS categories_string FROM {table_name} AS T1"
        join_clause = f"""
            LEFT JOIN item_category_table AS T2 ON T1.id = T2.item_id AND T2.item_type = ?
            LEFT JOIN category_table AS T3 ON T2.category_id = T3.id
        """
        where_clause = ""
        
        params.append(data_type) 
        
        count_query = f'SELECT COUNT(*) FROM {table_name}'
        cursor.execute(count_query)

    total_items = cursor.fetchone()[0]
        
    main_query = f"{base_select} {join_clause} {where_clause} GROUP BY T1.id ORDER BY T1.id DESC LIMIT ? OFFSET ?"
    
    params.extend([PER_PAGE, offset])
    
    cursor.execute(main_query, params)
    items = cursor.fetchall()
    conn.close()
    
    result_items = []
    for item in items:
        item_dict = dict(item)
        item_dict['categories'] = item_dict.pop('categories_string') or ''
        result_items.append(item_dict)

    return result_items, total_items


@app.route('/list/vocab')
def list_vocab():
    return list_page('vocab')

@app.route('/list/grammar')
def list_grammar():
    return list_page('grammar')

# ----------------- 編輯 (保持不變) -----------------

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


        try:
            cursor = conn.cursor()
            
            # 1. 更新主表
            if data_type == 'vocab':
                # 🚨 關鍵：從前端獲取 part_of_speech 欄位的值 (現在來自隱藏欄位)
                part_of_speech = request.form['part_of_speech']
                cursor.execute(
                    f'UPDATE {table_name} SET term=?, part_of_speech=?, explanation=?, example_sentence=? WHERE id=?',
                    (term, part_of_speech, explanation, example_sentence, item_id)
                )
            else:
                cursor.execute(
                    f'UPDATE {table_name} SET term=?, explanation=?, example_sentence=? WHERE id=?',
                    (term, explanation, example_sentence, item_id)
                )

            # 2. 更新分類連結表
            update_item_categories(item_id, data_type, category_string, conn)
            
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
        
    return render_template('edit_item.html', item=item, data_type=data_type, all_categories=all_categories, master_pos_list=MASTER_POS_LIST)

# ----------------- 刪除 (確保刪除連結) -----------------

@app.route('/delete/<data_type>/<int:item_id>', methods=['POST'])
def delete_item(data_type, item_id):
    if data_type not in ['vocab', 'grammar']:
        return redirect(url_for('home'))

    table_name = get_table_name(data_type)
    data_type_display = '單字' if data_type == 'vocab' else '文法'
    conn = get_db_connection()
    
    try:
        cursor = conn.cursor()
        
        # 🚨 關鍵：先刪除 item_category_table 中的連結 (解決孤兒連結問題)
        cursor.execute('DELETE FROM item_category_table WHERE item_id = ? AND item_type = ?', (item_id, data_type))
        
        # 刪除主表中的項目
        cursor.execute(f'DELETE FROM {table_name} WHERE id = ?', (item_id,))
        
        conn.commit()
        flash(f'該筆{data_type_display}已成功刪除。', 'success')
    except sqlite3.Error as e:
        conn.rollback()
        flash(f'刪除失敗: {e}', 'danger')
    finally:
        conn.close()
        
    return redirect(url_for('list_page', data_type=data_type))

# ----------------- 單字卡功能 (最小修正點) -----------------

@app.route('/flashcard/select')
def flashcard_select():
    all_categories = get_all_categories()
    all_pos = MASTER_POS_LIST 
    last_filters = session.get('last_flashcard_filters', {})
    
    return render_template('flashcard_select.html', 
                           all_categories=all_categories, 
                           all_pos=all_pos,
                           last_filters=last_filters)

def get_flashcard_query_parts(data_type, category_filter, pos_filter=None):
    """
    建立 Flashcard 查詢的 FROM, JOIN, WHERE 語句和對應的參數。
    返回: (SQL_FRAGMENT, PARAMS)
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

    join_type = 'LEFT'
    if category_filter and category_filter != 'all':
        join_type = 'INNER'
        
    from_join = f"""
        FROM {table_name} AS T1
        {join_type} JOIN item_category_table AS T2 ON T1.id = T2.item_id AND T2.item_type = '{item_type}'
        {join_type} JOIN category_table AS T3 ON T2.category_id = T3.id
    """
    
    where_clauses = ["1=1"]

    if category_filter and category_filter != 'all':
         where_clauses.append("T3.name = ?")
         params.append(category_filter)

    if data_type == 'vocab' and pos_filter and pos_filter != 'all':
        pos_abbr = pos_filter.split(' ')[0].strip() if ' ' in pos_filter else pos_filter
        
        where_clauses.append(
            """ 
                (
                    T1.part_of_speech = ? OR
                    T1.part_of_speech LIKE ? OR
                    T1.part_of_speech LIKE ? OR
                    T1.part_of_speech LIKE ?
                )
            """
        )
        params.extend([pos_abbr, f'{pos_abbr},%', f'%,{pos_abbr}', f'%,{pos_abbr},%'])

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
    
    # --- 偵錯點 1: 檢查篩選條件和索引 ---
    print(f"--- API DEBUG: 請求索引={index}, 總數={total_count}, 篩選器={filters}")
    
    if not filters or index < 0: 
        print("API DEBUG: 篩選條件無效或索引越界，返回 400")
        return jsonify({'success': False, 'message': '篩選條件無效或索引越界'}), 400
    
    if index >= total_count:
        return jsonify({'success': True, 'cards': []})

    data_type = filters.get('data_type', 'all')
    category_filter = filters.get('category_filter', 'all')
    pos_filter = filters.get('pos_filter', 'all')

    conn = get_db_connection()
    # 設置 row_factory 讓結果可以透過欄位名稱存取 (例如 row['id'])
    conn.row_factory = sqlite3.Row 
    cursor = conn.cursor()
    
    queries = []
    params = []
    
    # 請確保 BATCH_SIZE 已在 app.py 頂部定義為 50 (或您設定的值)
    BATCH_SIZE = 50 

    # 1. 處理單字 (vocab)
    if data_type in ['all', 'vocab']:
        # 🚨 關鍵修正 1：將 T1.reading 替換為 '' AS reading，以匹配文法表並避開不存在的欄位。
        vocab_select = "SELECT T1.id, T1.term, '' AS reading, T1.part_of_speech, T1.explanation, T1.example_sentence, 'vocab' as type"
        vocab_fragment, vocab_params = get_flashcard_query_parts('vocab', category_filter, pos_filter)
        vocab_query = f"{vocab_select} {vocab_fragment} GROUP BY T1.id"
        queries.append(vocab_query)
        params.extend(vocab_params)
        
    # 2. 處理文法 (grammar)
    if data_type in ['all', 'grammar']:
        # 修正：確保這裡的欄位與 vocab_select 完全匹配，並包含 '' AS reading
        grammar_select = "SELECT T1.id, T1.term, '' AS reading, '' as part_of_speech, T1.explanation, T1.example_sentence, 'grammar' as type"
        grammar_fragment, grammar_params = get_flashcard_query_parts('grammar', category_filter)
        grammar_query = f"{grammar_select} {grammar_fragment} GROUP BY T1.id"
        queries.append(grammar_query)
        params.extend(grammar_params)
    
    
    # 3. 合併查詢並使用 OFFSET/LIMIT 獲取一整個批次
    final_query = " UNION ALL ".join(queries)
    
    # 關鍵修正 2: ORDER BY 使用結果集中的欄位名稱 'id' (解決 T1.id 錯誤)
    final_query = f"SELECT * FROM ({final_query}) ORDER BY id ASC LIMIT {BATCH_SIZE} OFFSET ?" 
    params.append(index) 

    # --- 偵錯點 2: 檢查最終 SQL 語句和參數 ---
    print(f"API DEBUG: 最終 SQL 查詢: {final_query}")
    print(f"API DEBUG: 最終 SQL 參數: {params}")

    try:
        cursor.execute(final_query, params)
        card_data_list = cursor.fetchall()
        
        # --- 偵錯點 3: 檢查是否獲取到資料 ---
        print(f"API DEBUG: 成功獲取 {len(card_data_list)} 筆資料。")
        
        # 將 Row 對象轉換為標準字典，方便 jsonify
        cards = [dict(row) for row in card_data_list] 
        conn.close()
        return jsonify({'success': True, 'cards': cards})
        
    except sqlite3.Error as e:
        conn.close()
        # --- 偵錯點 4: SQL 錯誤 ---
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
    
    # ⚠️ 關鍵修改: 移除 current_card 變數
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
        
    # ⚠️ 關鍵修改: 改用 Session 中儲存的總數
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
        # 處理索引 < 0 的情況（繞回最後一張）
        session['last_flashcard_index'] = total_count - 1 
        return jsonify({'success': True, 'new_index': total_count - 1, 'wrapped': True})
# ----------------- 啟動應用程式 -----------------

if __name__ == '__main__':
    # 確保資料庫在應用程式啟動時只創建一次
    init_db() 
    app.run(debug=True)