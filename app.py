# app.py

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
import sqlite3

app = Flask(__name__)
# 設置 Secret Key 來啟用 session (用於儲存記憶點)
app.secret_key = 'your_super_secret_key' # 請自行修改為一個複雜的字串
DB_NAME = 'jp_db.db'
PER_PAGE = 20 # 每頁顯示 20 筆資料

# --- 資料庫操作 ---
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # 🚨 注意: 如果您運行過舊版，需手動在資料庫中為 vocab_table 和 grammar_table 增加 categories 欄位
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS vocab_table (
            id INTEGER PRIMARY KEY,
            term TEXT NOT NULL,
            part_of_speech TEXT,
            explanation TEXT,
            example_sentence TEXT,
            categories TEXT -- 分類欄位
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS grammar_table (
            id INTEGER PRIMARY KEY,
            term TEXT NOT NULL,
            explanation TEXT,
            example_sentence TEXT,
            categories TEXT -- 分類欄位
        )
    ''')
    conn.commit()
    conn.close()

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

# 新增輔助函數：獲取所有唯一分類
def get_all_categories():
    conn = get_db_connection()
    vocab_categories = conn.execute("SELECT DISTINCT categories FROM vocab_table WHERE categories IS NOT NULL AND categories != ''").fetchall()
    grammar_categories = conn.execute("SELECT DISTINCT categories FROM grammar_table WHERE categories IS NOT NULL AND categories != ''").fetchall()
    conn.close()

    all_categories = set()
    for row in vocab_categories + grammar_categories:
        if row['categories']:
            for cat in row['categories'].split(','):
                cleaned_cat = cat.strip()
                if cleaned_cat:
                    all_categories.add(cleaned_cat)
                
    return sorted(list(all_categories))


# --- 路由設定 ---

@app.route('/')
def home():
    """首頁：提供導航連結"""
    return render_template('home.html')

@app.route('/categories_overview')
def categories_overview():
    """分類總覽頁面：顯示所有唯一的分類"""
    categories = get_all_categories()
    return render_template('categories_overview.html', categories=categories)


@app.route('/list_page/<data_type>')
def list_page(data_type):
    """單字/文法清單顯示頁面，支持分頁和分類篩選"""
    page = request.args.get('page', 1, type=int)
    category = request.args.get('category', None) 
    
    conn = get_db_connection()
    
    if data_type == 'vocab':
        table_name = 'vocab_table'
    elif data_type == 'grammar':
        table_name = 'grammar_table'
    else:
        flash('無效的資料類型', 'danger')
        return redirect(url_for('home'))

    # Category Filtering Logic
    params = []
    where_clause = ''
    if category:
        where_clause = ' WHERE categories LIKE ?'
        params.append(f'%{category}%')
    
    # 重建總數查詢和資料查詢
    total_query = f'SELECT COUNT(*) FROM {table_name}{where_clause}'
    data_query = f'SELECT * FROM {table_name}{where_clause} ORDER BY id DESC LIMIT ? OFFSET ?'
    
    # 計算總頁數
    try:
        total_items = conn.execute(total_query, params).fetchone()[0]
    except Exception as e:
        flash(f'資料庫查詢錯誤，請檢查表格結構是否已更新: {e}', 'danger')
        total_items = 0
        
    total_pages = (total_items + PER_PAGE - 1) // PER_PAGE
    page = max(1, min(page, total_pages if total_pages > 0 else 1))
        
    offset = (page - 1) * PER_PAGE
    
    # 執行資料查詢
    data_params = params + [PER_PAGE, offset] 
    items = conn.execute(data_query, data_params).fetchall()
    conn.close()
    
    page_range = list(range(1, total_pages + 1)) if total_pages > 0 else []
    
    if category:
        flash(f'篩選結果: 僅顯示包含「{category}」分類的記錄。', 'info')

    return render_template('list_template.html', 
                           items=items, 
                           data_type=data_type, 
                           current_page=page, 
                           total_pages=total_pages, 
                           page_range=page_range,
                           current_category=category) 


@app.route('/add_vocab', methods=['GET', 'POST'])
def add_vocab():
    if request.method == 'POST':
        categories = request.form.get('categories', '') 
        
        conn = get_db_connection()
        conn.execute('INSERT INTO vocab_table (term, part_of_speech, explanation, example_sentence, categories) VALUES (?, ?, ?, ?, ?)',
                     (request.form['term'], request.form['part_of_speech'], request.form['explanation'], request.form['example_sentence'], categories))
        conn.commit()
        conn.close()
        flash('單字新增成功！', 'success')
        return redirect(url_for('list_page', data_type='vocab'))
    
    return render_template('add_vocab.html', categories=get_all_categories())


@app.route('/add_grammar', methods=['GET', 'POST'])
def add_grammar():
    if request.method == 'POST':
        categories = request.form.get('categories', '')
        
        conn = get_db_connection()
        conn.execute('INSERT INTO grammar_table (term, explanation, example_sentence, categories) VALUES (?, ?, ?, ?)',
                     (request.form['term'], request.form['explanation'], request.form['example_sentence'], categories))
        conn.commit()
        conn.close()
        flash('文法新增成功！', 'success')
        return redirect(url_for('list_page', data_type='grammar'))
    
    return render_template('add_grammar.html', categories=get_all_categories())


@app.route('/edit/<data_type>/<int:item_id>', methods=['GET', 'POST'])
def edit_item(data_type, item_id):
    table_name = 'vocab_table' if data_type == 'vocab' else 'grammar_table'
    conn = get_db_connection()

    if request.method == 'POST':
        term = request.form['term']
        explanation = request.form['explanation']
        example_sentence = request.form['example_sentence']
        categories = request.form.get('categories', '') 
        
        if data_type == 'vocab':
            part_of_speech = request.form['part_of_speech']
            conn.execute(f'UPDATE {table_name} SET term=?, part_of_speech=?, explanation=?, example_sentence=?, categories=? WHERE id=?',
                         (term, part_of_speech, explanation, example_sentence, categories, item_id))
        elif data_type == 'grammar':
            conn.execute(f'UPDATE {table_name} SET term=?, explanation=?, example_sentence=?, categories=? WHERE id=?',
                         (term, explanation, example_sentence, categories, item_id))
        
        conn.commit()
        conn.close()
        flash(f'{data_type} 記錄更新成功！', 'success')
        return redirect(url_for('list_page', data_type=data_type))

    # GET 請求
    item = conn.execute(f'SELECT * FROM {table_name} WHERE id=?', (item_id,)).fetchone()
    conn.close()

    if item is None:
        flash('找不到該筆記錄。', 'danger')
        return redirect(url_for('list_page', data_type=data_type))
    
    all_categories = get_all_categories()
    return render_template('edit_item.html', item=item, data_type=data_type, categories=all_categories)


@app.route('/delete/<data_type>/<int:item_id>', methods=['POST'])
def delete_item(data_type, item_id):
    table_name = 'vocab_table' if data_type == 'vocab' else 'grammar_table'
    conn = get_db_connection()
    conn.execute(f'DELETE FROM {table_name} WHERE id = ?', (item_id,))
    conn.commit()
    conn.close()
    flash('刪除成功！', 'success')
    return redirect(request.referrer or url_for('list_page', data_type=data_type))


# --- 新增：分類管理路由 (刪除功能) ---

@app.route('/api/delete_category/<category_name>', methods=['POST'])
def delete_category(category_name):
    """
    接收要刪除的分類名稱，並從所有相關記錄中移除該分類。
    """
    conn = get_db_connection()
    
    # 遍歷 vocab_table 和 grammar_table
    tables = ['vocab_table', 'grammar_table']
    
    for table_name in tables:
        # 查詢所有包含該分類的記錄
        # 這裡使用 f-string 因為 table_name 是受控於內部程式碼的變數，是安全的。
        updates = conn.execute(
            f"SELECT id, categories FROM {table_name} WHERE categories LIKE ?", 
            (f'%{category_name}%',)
        ).fetchall()
        
        for item in updates:
            old_categories = item['categories']
            
            # 移除要刪除的分類，並用逗號重新連接
            new_categories_list = [
                cat.strip() for cat in old_categories.split(',') 
                if cat.strip() != category_name and cat.strip() != ''
            ]
            new_categories = ','.join(new_categories_list)
            
            conn.execute(
                f'UPDATE {table_name} SET categories = ? WHERE id = ?', 
                (new_categories, item['id'])
            )

    conn.commit()
    conn.close()
    
    flash(f'分類「{category_name}」已成功從所有記錄中移除。', 'success')
    return jsonify({'success': True})


@app.route('/flashcard_select')
def flashcard_select():
    """單字卡篩選設定頁面"""
    all_categories = get_all_categories()
    conn = get_db_connection()
    parts_of_speech_data = conn.execute("SELECT DISTINCT part_of_speech FROM vocab_table WHERE part_of_speech IS NOT NULL AND part_of_speech != ''").fetchall()
    conn.close()
    
    return render_template('flashcard_select.html', categories=all_categories, parts_of_speech=parts_of_speech_data)


@app.route('/api/flashcard_data', methods=['POST'])
def flashcard_data():
    """獲取單字卡數據並存入 Session，並儲存篩選條件"""
    data = request.get_json()
    data_type = data.get('data_type')
    pos_filter = data.get('pos_filter') 
    category_filter = data.get('category_filter') 

    conn = get_db_connection()
    flashcards_data = []

    # 處理單字 (vocab)
    if data_type == 'vocab' or data_type == 'all':
        query = 'SELECT term, explanation, example_sentence, part_of_speech, categories FROM vocab_table'
        params = []
        where_clauses = []
        
        if pos_filter and pos_filter != 'all':
            where_clauses.append('part_of_speech = ?')
            params.append(pos_filter)
        
        if category_filter and category_filter != 'all':
            where_clauses.append('categories LIKE ?')
            params.append(f'%{category_filter}%')
            
        if where_clauses:
            query += ' WHERE ' + ' AND '.join(where_clauses)
        
        query += ' ORDER BY id DESC' 

        raw_data = conn.execute(query, params).fetchall()
        for row in raw_data:
            flashcards_data.append({
                'term': row['term'],
                'explanation': row['explanation'],
                'example_sentence': row['example_sentence'],
                'part_of_speech': row['part_of_speech'],
                'categories': row['categories']
            })
        
        # 如果只選擇 vocab，立即返回
        if data_type == 'vocab': 
            conn.close()
            session['flashcards_data'] = flashcards_data
            session['flashcard_filters'] = {'data_type': data_type, 'pos_filter': pos_filter, 'category_filter': category_filter}
            last_index = session.get('last_flashcard_index', 0)
            return jsonify({'success': True, 'count': len(flashcards_data), 'last_index': last_index})


    # 處理文法 (grammar) - 只有當 data_type 是 'grammar' 或 'all' 時才執行
    if data_type == 'grammar' or data_type == 'all':
        query = 'SELECT term, explanation, example_sentence, categories FROM grammar_table'
        params = []
        where_clauses = []
        
        if category_filter and category_filter != 'all':
            where_clauses.append('categories LIKE ?')
            params.append(f'%{category_filter}%')
        
        if where_clauses:
            query += ' WHERE ' + ' AND '.join(where_clauses)
            
        query += ' ORDER BY id DESC' 

        raw_data = conn.execute(query, params).fetchall()
        for row in raw_data:
            flashcards_data.append({
                'term': row['term'],
                'explanation': row['explanation'],
                'example_sentence': row['example_sentence'],
                'part_of_speech': '文法', 
                'categories': row['categories']
            })
            
    conn.close()

    # 將數據和篩選條件儲存到 Session
    session['flashcards_data'] = flashcards_data
    session['flashcard_filters'] = {'data_type': data_type, 'pos_filter': pos_filter, 'category_filter': category_filter}
    
    last_index = session.get('last_flashcard_index', 0)
    
    return jsonify({
        'success': True, 
        'count': len(flashcards_data),
        'last_index': last_index
    })


@app.route('/api/update_index', methods=['POST'])
def update_flashcard_index():
    """接收新的單字卡索引並更新 Session 中的記憶點 (此 API 負責保存進度)"""
    data = request.get_json()
    new_index = data.get('index')
    
    if new_index is not None and isinstance(new_index, int) and new_index >= 0:
        session['last_flashcard_index'] = new_index
        return jsonify({'success': True, 'message': f'Index updated to {new_index}'})
    else:
        return jsonify({'success': False, 'message': 'Invalid index provided'}), 400


@app.route('/flashcard_deck/<action>')
def flashcard_deck(action):
    """單字卡顯示頁面"""
    flashcards_data = session.get('flashcards_data', [])
    filters = session.get('flashcard_filters', {}) 
    
    if not flashcards_data:
        # 如果沒有數據，強制回到篩選頁面
        flash('請先在設定頁面選擇內容。', 'warning')
        return redirect(url_for('flashcard_select'))

    total_count = len(flashcards_data)
    
    # 1. 載入上次進度
    current_index = session.get('last_flashcard_index', 0) 

    if action == 'start':
        current_index = 0

    # 2. 確保索引不越界
    if total_count > 0:
        if current_index >= total_count: 
             current_index = 0
        current_index = max(0, current_index)
        
    else:
        current_index = 0
        flash('載入的單字卡為空，請調整篩選條件。', 'warning')
        return redirect(url_for('flashcard_select'))
        
    # 獲取該筆數據並生成篩選摘要
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
        
    filter_summary = " | ".join(parts)

    return render_template('flashcard_deck.html', 
                           card=current_card,
                           current_index=current_index,
                           total_count=total_count,
                           filter_summary=filter_summary) 

if __name__ == '__main__':
    init_db()
    app.run(debug=True)