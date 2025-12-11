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

# 詞性列表 (用於單字詞性篩選與新增快捷鍵)
MASTER_POS_LIST = [
    # --- 主要詞類 ---
    '名 (名詞)', 
    '專 (專有名詞)', 
    '數 (數詞)', 
    '代 (代名詞)',  
    
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
    '接尾 (接尾詞)',    
    '接頭 (接頭詞)',    # Anki 檔案中出現
    
    # --- 備用/不常見 ---
    'Other (其他)'     
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

@app.route('/list/<data_type>')
def list_page(data_type):
    page = request.args.get('page', 1, type=int)
    category = request.args.get('category', None)
    
    if data_type not in ['vocab', 'grammar']:
        return redirect(url_for('home'))
        
    items, total_items = get_list_data(data_type, page, category)
    total_pages = math.ceil(total_items / PER_PAGE)

    all_categories_list = get_all_categories()
    
    return render_template('list_template.html', 
        items=items, 
        data_type=data_type, 
        current_page=page, 
        total_pages=total_pages,
        total_items=total_items,
        current_category=category,
        all_categories=all_categories_list 
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
@app.route('/flashcard/data', methods=['POST'])
def flashcard_data():
    data = request.get_json()
    data_type = data.get('data_type', 'all')
    category_filter = data.get('category_filter', 'all')
    pos_filter = data.get('pos_filter', 'all')
    max_count = data.get('max_count', 50) 

    # <<<<<<<< 修正點 1: 詞性篩選值正規化 >>>>>>>>
    # 目的：確保 pos_filter 是詞性縮寫 (例如: "N (名詞)" 變成 "N")
    if pos_filter != 'all' and pos_filter:
        # 假設格式為 "縮寫 (名稱)"，使用空格分隔並取第一個部分，這適用於所有 MASTER_POS_LIST 中的項目。
        pos_filter = pos_filter.split(' ')[0].strip()
    # <<<<<<<< 修正點 1 結束 >>>>>>>>

    conn = get_db_connection()
    cursor = conn.cursor()
    
    queries = []
    params = []

    # 1. 處理單字 (vocab)
    if data_type in ['all', 'vocab']:
        vocab_select = "SELECT T1.id, T1.term, T1.part_of_speech, T1.explanation, T1.example_sentence, 'vocab' as type"
        vocab_join = """
            LEFT JOIN item_category_table AS T2 ON T1.id = T2.item_id AND T2.item_type = 'vocab'
            LEFT JOIN category_table AS T3 ON T2.category_id = T3.id
        """
        vocab_where = " WHERE 1=1 "
        vocab_params = []
        
        # 詞性過濾 (使用正規化後的 pos_filter)
        if pos_filter != 'all':
            # 採用最安全的多條件 LIKE 匹配，以應對 "N, V" 這種逗號+空格的分隔格式
            vocab_where += """ 
                AND (
                    T1.part_of_speech = ? OR               -- 1. 只有一個詞性 (e.g., "N")
                    T1.part_of_speech LIKE ? OR            -- 2. 詞性在開頭 (e.g., "N, V")
                    T1.part_of_speech LIKE ? OR            -- 3. 詞性在結尾 (e.g., "V, N")
                    T1.part_of_speech LIKE ?               -- 4. 詞性在中間 (e.g., "V, N, いA")
                )
            """
            # 1. 精確匹配
            vocab_params.append(pos_filter) 
            # 2. 開頭 (例如: "N, %")
            vocab_params.append(f'{pos_filter}, %') 
            # 3. 結尾 (例如: "%, N")
            vocab_params.append(f'%, {pos_filter}') 
            # 4. 中間 (例如: "%, N, %")
            vocab_params.append(f'%, {pos_filter}, %') 
            

        # 分類過濾 (如果不是 'all'，需要 Inner Join)
        if category_filter != 'all':
             vocab_select = "SELECT T1.id, T1.term, T1.part_of_speech, T1.explanation, T1.example_sentence, 'vocab' as type"
             vocab_join = """
                INNER JOIN item_category_table AS T2 ON T1.id = T2.item_id AND T2.item_type = 'vocab'
                INNER JOIN category_table AS T3 ON T2.category_id = T3.id
            """
             vocab_where += " AND T3.name = ?"
             vocab_params.append(category_filter)

        vocab_query = f"""
            {vocab_select}
            FROM vocab_table AS T1
            {vocab_join}
            {vocab_where}
            GROUP BY T1.id
        """
        queries.append(vocab_query)
        params.extend(vocab_params)
        

    # 2. 處理文法 (grammar) (保持不變)
    if data_type in ['all', 'grammar']:
        grammar_select = "SELECT T1.id, T1.term, '' as part_of_speech, T1.explanation, T1.example_sentence, 'grammar' as type"
        grammar_join = """
            LEFT JOIN item_category_table AS T2 ON T1.id = T2.item_id AND T2.item_type = 'grammar'
            LEFT JOIN category_table AS T3 ON T2.category_id = T3.id
        """
        grammar_where = " WHERE 1=1 "
        grammar_params = []
        
        # 分類過濾
        if category_filter != 'all':
             grammar_select = "SELECT T1.id, T1.term, '' as part_of_speech, T1.explanation, T1.example_sentence, 'grammar' as type"
             grammar_join = """
                INNER JOIN item_category_table AS T2 ON T1.id = T2.item_id AND T2.item_type = 'grammar'
                INNER JOIN category_table AS T3 ON T2.category_id = T3.id
            """
             grammar_where += " AND T3.name = ?"
             grammar_params.append(category_filter)

        grammar_query = f"""
            {grammar_select}
            FROM grammar_table AS T1
            {grammar_join}
            {grammar_where}
            GROUP BY T1.id
        """
        queries.append(grammar_query)
        params.extend(grammar_params)
    
    
    # 3. 合併查詢並限制總數
    if not queries:
        return jsonify({'success': False, 'message': '無效的資料類型選擇'}), 400
        
    final_query = " UNION ALL ".join(queries)
    
    # 隨機排序並限制數量
    final_query = f"SELECT * FROM ({final_query}) ORDER BY RANDOM() LIMIT ?"
    params.append(max_count)

    cursor.execute(final_query, params)
    flashcards_data = cursor.fetchall()
    conn.close()

    session['flashcard_data'] = [dict(row) for row in flashcards_data]
    
    if 'last_flashcard_index' in session:
        last_index = session.pop('last_flashcard_index')
    else:
        last_index = 0
        
    session['last_flashcard_filters'] = data
    
    return jsonify({
        'success': True,
        'count': len(flashcards_data),
        'last_index': last_index 
    })
@app.route('/flashcard/deck')
def flashcard_deck():
    action = request.args.get('action', 'resume')

    flashcards_data = session.get('flashcard_data', [])
    filters = session.get('last_flashcard_filters', {})

    if not flashcards_data:
        flash('請先在設定頁面載入單字卡內容。', 'warning')
        return redirect(url_for('flashcard_select'))

    total_count = len(flashcards_data)
    
    current_index = session.get('last_flashcard_index', 0) 

    if action == 'start':
        current_index = 0

    if total_count > 0:
        if current_index >= total_count: 
             current_index = 0
        current_index = max(0, current_index)
        
    else:
        current_index = 0
        flash('載入的單字卡為空，請調整篩選條件。', 'warning')
        return redirect(url_for('flashcard_select'))
        
    current_card = flashcards_data[current_index]
    
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
                           card=current_card, # <--- 修正點
                           current_card=current_card, 
                           current_index=current_index, 
                           total_count=total_count, 
                           filter_summary=summary_text) 

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
        
    flashcards_data = session.get('flashcard_data', [])
    total_count = len(flashcards_data)
    
    if total_count == 0:
        return jsonify({'success': False, 'message': '單字卡為空，無法更新索引'}), 400
        
    if 0 <= new_index < total_count:
        session['last_flashcard_index'] = new_index
        return jsonify({'success': True, 'new_index': new_index})
    elif new_index >= total_count:
        # 到達最後一張後，將索引設為 0 (回到起點)
        session['last_flashcard_index'] = 0
        return jsonify({'success': True, 'new_index': 0, 'finished': True})
    else:
        return jsonify({'success': False, 'message': 'Index out of bounds'}), 400

# ----------------- 啟動應用程式 -----------------

if __name__ == '__main__':
    # 確保資料庫在應用程式啟動時只創建一次
    init_db() 
    app.run(debug=True)