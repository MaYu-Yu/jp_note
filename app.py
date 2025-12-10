# app.py

from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import sqlite3
app = Flask(__name__)
# 設置 Secret Key 來啟用 session (用於儲存記憶點)
app.secret_key = 'your_super_secret_key' # 請自行修改為一個複雜的字串
DB_NAME = 'jp_db.db'
PER_PAGE = 20 # 每頁顯示 20 筆資料

# --- 資料庫操作 (維持不變) ---
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS vocab_table (
            id INTEGER PRIMARY KEY,
            term TEXT NOT NULL,
            part_of_speech TEXT,
            explanation TEXT,
            example_sentence TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS grammar_table (
            id INTEGER PRIMARY KEY,
            term TEXT NOT NULL,
            explanation TEXT,
            example_sentence TEXT
        )
    ''')
    conn.commit()
    conn.close()

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

# --- 路由設定 ---

@app.route('/')
def home():
    """首頁：只提供導航連結"""
    return render_template('home.html')

# === 列表顯示與分頁刪除 ===

def get_list_data(table_name, page, total_count_query):
    """通用列表數據獲取和分頁邏輯"""
    conn = get_db_connection()
    offset = (page - 1) * PER_PAGE
    
    # 獲取總數
    total_items = conn.execute(total_count_query).fetchone()[0]
    total_pages = (total_items + PER_PAGE - 1) // PER_PAGE
    
    # 獲取當前頁數據
    items_query = f"SELECT * FROM {table_name} ORDER BY id DESC LIMIT ? OFFSET ?"
    items = conn.execute(items_query, (PER_PAGE, offset)).fetchall()
    conn.close()
    
    return items, total_items, total_pages, page

@app.route('/list/<data_type>')
def list_page(data_type):
    page = request.args.get('page', 1, type=int)
    
    if data_type == 'vocab':
        table = 'vocab_table'
        total_query = "SELECT COUNT(*) FROM vocab_table"
        items, total_items, total_pages, current_page = get_list_data(table, page, total_query)
        return render_template('list_vocab.html', items=items, total_pages=total_pages, current_page=current_page, data_type=data_type)
        
    elif data_type == 'grammar':
        table = 'grammar_table'
        total_query = "SELECT COUNT(*) FROM grammar_table"
        items, total_items, total_pages, current_page = get_list_data(table, page, total_query)
        return render_template('list_grammar.html', items=items, total_pages=total_pages, current_page=current_page, data_type=data_type)
        
    return redirect(url_for('home'))

@app.route('/delete/<data_type>/<int:item_id>', methods=['POST'])
def delete_item(data_type, item_id):
    if data_type == 'vocab':
        table = 'vocab_table'
    elif data_type == 'grammar':
        table = 'grammar_table'
    else:
        return redirect(url_for('home'))

    conn = get_db_connection()
    conn.execute(f"DELETE FROM {table} WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    
    # 刪除後返回列表頁面，保持當前的 data_type
    return redirect(url_for('list_page', data_type=data_type))
    
@app.route('/edit/<data_type>/<int:item_id>', methods=['GET', 'POST'])
def edit_item(data_type, item_id):
    conn = get_db_connection()
    
    if data_type == 'vocab':
        table = 'vocab_table'
        redirect_url = url_for('list_page', data_type='vocab')
    elif data_type == 'grammar':
        table = 'grammar_table'
        redirect_url = url_for('list_page', data_type='grammar')
    else:
        conn.close()
        return redirect(url_for('home'))

    if request.method == 'POST':
        # 處理更新資料
        term = request.form['term']
        explanation = request.form['explanation']
        example_sentence = request.form['example_sentence']
        
        if data_type == 'vocab':
            part_of_speech = request.form['part_of_speech']
            conn.execute(
                f"UPDATE {table} SET term=?, part_of_speech=?, explanation=?, example_sentence=? WHERE id=?",
                (term, part_of_speech, explanation, example_sentence, item_id)
            )
        else: # grammar
            conn.execute(
                f"UPDATE {table} SET term=?, explanation=?, example_sentence=? WHERE id=?",
                (term, explanation, example_sentence, item_id)
            )
        
        conn.commit()
        conn.close()
        return redirect(redirect_url)
    
    # GET 請求：顯示編輯表單
    item = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (item_id,)).fetchone()
    conn.close()
    
    if item is None:
        return "找不到該項目", 404
        
    return render_template('edit_item.html', item=item, data_type=data_type)

# === 新增功能 (維持不變) ===
@app.route('/add_vocab', methods=['GET', 'POST'])
# ... (add_vocab 邏輯維持不變，僅返回 home) ...
def add_vocab():
    if request.method == 'POST':
        term = request.form['term']
        part_of_speech = request.form['part_of_speech']
        explanation = request.form['explanation']
        example_sentence = request.form['example_sentence']
        
        if term:
            conn = get_db_connection()
            conn.execute(
                'INSERT INTO vocab_table (term, part_of_speech, explanation, example_sentence) VALUES (?, ?, ?, ?)',
                (term, part_of_speech, explanation, example_sentence)
            )
            conn.commit()
            conn.close()
            return redirect(url_for('list_page', data_type='vocab')) # 新增後導向列表
        
    # 獲取所有詞性供 flashcard 頁面篩選用
    conn = get_db_connection()
    parts_of_speech = conn.execute("SELECT DISTINCT part_of_speech FROM vocab_table WHERE part_of_speech IS NOT NULL AND part_of_speech != '' ORDER BY part_of_speech").fetchall()
    conn.close()
    
    return render_template('add_vocab.html', parts_of_speech=parts_of_speech)

@app.route('/add_grammar', methods=['GET', 'POST'])
# ... (add_grammar 邏輯維持不變，僅返回 home) ...
def add_grammar():
    if request.method == 'POST':
        term = request.form['term']
        explanation = request.form['explanation']
        example_sentence = request.form['example_sentence']
        
        if term:
            conn = get_db_connection()
            conn.execute(
                'INSERT INTO grammar_table (term, explanation, example_sentence) VALUES (?, ?, ?)',
                (term, explanation, example_sentence)
            )
            conn.commit()
            conn.close()
            return redirect(url_for('list_page', data_type='grammar')) # 新增後導向列表
        
    return render_template('add_grammar.html')


# === 單字卡功能 ===

@app.route('/flashcard')
def flashcard_select():
    """單字卡篩選頁面"""
    conn = get_db_connection()
    # 獲取所有詞性供篩選用
    parts_of_speech = conn.execute("SELECT DISTINCT part_of_speech FROM vocab_table WHERE part_of_speech IS NOT NULL AND part_of_speech != '' ORDER BY part_of_speech").fetchall()
    conn.close()
    return render_template('flashcard_select.html', parts_of_speech=parts_of_speech)

@app.route('/get_flashcards', methods=['POST'])
def get_flashcards():
    """根據使用者選擇的類型和詞性獲取單字卡數據"""
    
    # 獲取 JSON 數據
    data = request.json
    data_type = data.get('data_type')
    pos_filter = data.get('pos_filter')
    
    conn = get_db_connection()
    query = ""
    params = []
    # 統一欄位名稱，讓單字和文法資料結構一致
    VOCAB_SELECT = "SELECT id, term, part_of_speech, explanation, example_sentence, 'vocab' as type FROM vocab_table"
    GRAMMAR_SELECT = "SELECT id, term, '文法' as part_of_speech, explanation, example_sentence, 'grammar' as type FROM grammar_table" 
    
    if data_type == 'vocab':
        query = VOCAB_SELECT
        if pos_filter and pos_filter != 'all':
            query += " WHERE part_of_speech = ?"
            params.append(pos_filter)
            
    elif data_type == 'grammar':
        query = GRAMMAR_SELECT
        
    else: # data_type == 'all'
        # 修正後的 UNION ALL 語法：直接連接兩個 SELECT 語句
        query = f"{VOCAB_SELECT} UNION ALL {GRAMMAR_SELECT}" 

    try:
        items = conn.execute(query, params).fetchall()
        
    except sqlite3.OperationalError as e:
        # 如果修正後仍有問題，打印錯誤並返回空集
        print(f"SQL 執行錯誤: {e}")
        print(f"使用的查詢: {query}")
        items = []
        
    finally:
        conn.close()
    
    # 將數據轉換為字典列表，並儲存到 session 中
    flashcards_data = [dict(item) for item in items]
    session['flashcards_data'] = flashcards_data
    
    # 處理記憶點
    last_index = session.get('last_flashcard_index', 0)
    
    return jsonify({
        'success': True, 
        'count': len(flashcards_data),
        'last_index': last_index
    })

@app.route('/flashcard_deck/<action>')
def flashcard_deck(action):
    """單字卡顯示頁面"""
    flashcards_data = session.get('flashcards_data', [])
    if not flashcards_data:
        return redirect(url_for('flashcard_select'))

    total_count = len(flashcards_data)
    
    # 處理記憶點
    current_index = session.get('last_flashcard_index', 0)
    
    if action == 'resume':
        current_index = session.get('last_flashcard_index', 0)
    elif action == 'start':
        current_index = 0

    # 確保索引不越界
    if current_index >= total_count:
        current_index = 0
    
    # 儲存當前索引，供下次使用
    session['last_flashcard_index'] = current_index

    # 獲取該筆數據
    current_card = flashcards_data[current_index]

    return render_template('flashcard_deck.html', 
                           card=current_card, 
                           current_index=current_index, 
                           total_count=total_count)

@app.route('/update_flashcard_index', methods=['POST'])
def update_flashcard_index():
    """接收前端請求，更新 session 中的記憶點"""
    index = request.json.get('index')
    session['last_flashcard_index'] = index
    return jsonify({'success': True})

if __name__ == '__main__':
    init_db()
    app.run(debug=True)