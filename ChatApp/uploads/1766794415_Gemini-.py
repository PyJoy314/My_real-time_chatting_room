import sqlite3
import random
import os
import sys
import time
import threading
from contextlib import contextmanager
from flask import Flask, render_template, request, send_from_directory, url_for
from flask_socketio import SocketIO, emit, join_room
from werkzeug.utils import secure_filename
from google import genai

# --- 1. 초기 설정 ---
PORT = 5001
UPLOAD_FOLDER = 'uploads'
DB_FILE = "chat_db.sqlite"
if not os.path.exists(UPLOAD_FOLDER): os.makedirs(UPLOAD_FOLDER)

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

noejul_loops = {}  # 유저별 무한뇌절 상태 관리용

# Gemini 설정
client = None
try:
    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key: client = genai.Client(api_key=api_key)
except: pass

# --- 2. 데이터베이스 로직 ---
@contextmanager
def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    try: yield conn
    finally:
        conn.commit(); conn.close()

def init_db():
    with get_db() as conn:
        try: conn.execute("ALTER TABLE users ADD COLUMN bank_money INTEGER DEFAULT 0")
        except: pass
        conn.execute("CREATE TABLE IF NOT EXISTS users (nickname TEXT PRIMARY KEY, money INTEGER DEFAULT 1000, bank_money INTEGER DEFAULT 0)")

def get_user(nick):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE nickname=?", (nick,)).fetchone()
        return dict(row) if row else None

def update_money(nick, amount, bank=False):
    col = "bank_money" if bank else "money"
    with get_db() as conn:
        conn.execute("INSERT OR IGNORE INTO users (nickname, money, bank_money) VALUES (?, 1000, 0)", (nick,))
        conn.execute(f"UPDATE users SET {col} = {col} + ? WHERE nickname = ?", (amount, nick))

# 🏦 [백그라운드] 이자 시스템: 1분마다 1%
def interest_system():
    while True:
        time.sleep(60)
        with get_db() as conn:
            conn.execute("UPDATE users SET bank_money = CAST(bank_money * 1.01 AS INTEGER) WHERE bank_money > 0")

# 🌀 [백그라운드] 무한 뇌절 태스크
def infinite_noejul_task(nick):
    while noejul_loops.get(nick):
        user = get_user(nick)
        # 뇌절 텍스트 생성 로직 (uploaded 파일 기반)
        S = "[:-Minecraft&https://solwitter.top/ &https://colab.research.google.com &Python_IDLE-3.14.exe&Midda&ect-:]"
        M = len(nick) + len(S)
        pattern = f'[:[^].[{nick}]:]~[:[{S}].[{random.randint(100, 999)}₩/$]:]' * 10
        
        reward = len(pattern) * 100 # 무한뇌절은 보상도 100배!
        update_money(nick, reward, bank=True) # 은행으로 자동 입금
        
        socketio.emit('message', {
            'nickname': nick, 
            'msg': f"🌀 [무한뇌절 가동중] 🌀\n{pattern}\n💰 무한 적립: +{reward}₩ (은행 입금 완료)",
            'type': 'noejul'
        }, room='main')
        time.sleep(5) # 5초 대기

# --- 3. 웹 라우팅 ---
@app.route('/')
def index(): return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    file = request.files.get('file')
    nick = request.form.get('nickname', '익명')
    if file:
        filename = secure_filename(f"{int(time.time())}_{file.filename}")
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        url = url_for('download_file', filename=filename)
        msg = f"📁 <b>{file.filename}</b> 공유됨! <a href='{url}' target='_blank' style='color:#38bdf8;'>[다운로드]</a>"
        socketio.emit('message', {'msg': msg, 'nickname': nick, 'type': 'file'}, room='main')
        return "OK"
    return "Err", 400

@app.route('/uploads/<filename>')
def download_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# --- 4. 소켓 통신 ---
@socketio.on('join')
def on_join(data):
    join_room('main')
    nick = data['nickname']
    if not get_user(nick): update_money(nick, 0)
    emit('message', {'msg': f"📢 {nick}님이 초월적 뇌절 제국에 입장했습니다.", 'type': 'system'}, room='main')

@socketio.on('send_msg')
def handle_msg(data):
    nick = data['nickname']
    content = data['msg'].strip()
    if not content: return

    user = get_user(nick)
    total_wealth = user['money'] + user['bank_money']
    rank = "초월자" if total_wealth >= 10000000 else ("황제" if total_wealth >= 5000000 else "VIP")

    # [명령어] 무한 뇌절 시작
    if content == "!무한뇌절":
        if not noejul_loops.get(nick):
            noejul_loops[nick] = True
            threading.Thread(target=infinite_noejul_task, args=(nick,), daemon=True).start()
            emit('message', {'msg': "🚀 [SYSTEM] 무한 뇌절 루프가 시작되었습니다!", 'type': 'system'})
        return

    # [명령어] 뇌절 중단
    if content == "!뇌절중단":
        noejul_loops[nick] = False
        emit('message', {'msg': "🛑 [SYSTEM] 무한 뇌절 루프가 중단되었습니다.", 'type': 'system'})
        return

    # [명령어] 단발성 뇌절
    if content == "!뇌절":
        S = "[:-Minecraft&https://solwitter.top/ &https://colab.research.google.com &Python_IDLE-3.14.exe&Midda&ect-:]"
        M = len(nick) + len(S)
        noejul_txt = f'[:[^].[{nick}]:]~[:[{S}].[{M}₩/$]:]' * 10
        reward = len(noejul_txt) * 50
        update_money(nick, reward)
        socketio.emit('message', {'nickname': nick, 'msg': f"🌀 뇌절 가동!!\n{noejul_txt}\n💰 보너스 +{reward}₩", 'rank': rank, 'type': 'noejul'}, room='main')
        return

    # [명령어] 금융
    if content.startswith("!저금") or content.startswith("!출금"):
        try:
            amt = int(content.split()[1])
            if content.startswith("!저금") and user['money'] >= amt:
                update_money(nick, -amt); update_money(nick, amt, bank=True)
                emit('message', {'msg': f"🏦 저금 완료: {amt}₩", 'type': 'system'})
            elif content.startswith("!출금") and user['bank_money'] >= amt:
                update_money(nick, amt); update_money(nick, -amt, bank=True)
                emit('message', {'msg': f"🏦 출금 완료: {amt}₩", 'type': 'system'})
        except: pass
        return

    if content in ["!잔액", "!적립", "!순위"]:
        user = get_user(nick)
        msg = f"💰 {nick}님 | 총자산: {user['money']+user['bank_money']}₩ | 등급: {rank}"
        emit('message', {'msg': msg, 'type': 'system'})
        return

    # [명령어] Gemini
    if content.startswith("!gemini ") and client:
        try:
            res = client.models.generate_content(model="gemini-2.0-flash", contents=content[8:])
            socketio.emit('message', {'msg': f"🤖 Gemini: {res.text}", 'type': 'bot'}, room='main')
        except: pass
        return

    # 일반 채팅
    update_money(nick, 10 + (len(content) * 2))
    socketio.emit('message', {'nickname': nick, 'msg': content, 'rank': rank, 'type': 'chat'}, room='main')

if __name__ == '__main__':
    init_db()
    threading.Thread(target=interest_system, daemon=True).start()
    import eventlet.wsgi
    eventlet.wsgi.server(eventlet.listen(('', PORT)), app)
