import sqlite3
import random
import os
import sys
import time
import subprocess
import threading
from contextlib import contextmanager
from flask import Flask, render_template, request, send_from_directory, url_for
from flask_socketio import SocketIO, emit, join_room
from werkzeug.utils import secure_filename
from google import genai

# 1. 서버 및 파일 설정
PORT = 5001
UPLOAD_FOLDER = 'uploads'
DB_FILE = "chat_db.sqlite"
if not os.path.exists(UPLOAD_FOLDER): os.makedirs(UPLOAD_FOLDER)

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Gemini API 설정
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

# 🏦 [이자 시스템] 매 1분마다 은행 잔고의 1% 지급
def interest_system():
    while True:
        time.sleep(60)
        with get_db() as conn:
            conn.execute("UPDATE users SET bank_money = CAST(bank_money * 1.01 AS INTEGER) WHERE bank_money > 0")

# --- 3. 뇌절 엔진 (Joyce님의 소스 코드 기반) ---
def generate_noejul_text(nick):
    # 업로드하신 《@파이썬@찐@뇌절@프로그램》 001.py의 핵심 로직 반영
    S = "[:-Minecraft&https://solwitter.top/ &https://colab.research.google.com &Python_IDLE-3.14.exe&Midda&ect-:]"
    M = len(nick) + len(S)
    pattern = f'[:[^].[{nick}]:]~[:[{S}].[{M}₩/$]:]' * 10
    return pattern

# --- 4. 라우팅 및 소켓 통신 ---
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

@socketio.on('join')
def on_join(data):
    join_room('main')
    nick = data['nickname']
    if not get_user(nick): update_money(nick, 0)
    emit('message', {'msg': f"📢 {nick}님이 자본과 뇌절의 정점에 합류했습니다.", 'type': 'system'}, room='main')

@socketio.on('send_msg')
def handle_msg(data):
    nick = data['nickname']
    content = data['msg'].strip()
    if not content: return

    user = get_user(nick)
    total_wealth = user['money'] + user['bank_money']
    
    # 💎 [핵심] 통합 자산 기반 등급 판정
    rank = "초월자" if total_wealth >= 10000000 else ("황제" if total_wealth >= 5000000 else "VIP")

    # 🔥 [명령어 1] 뇌절 시스템 (텍스트 출력 + 잔액 저장)
    if content == "!뇌절":
        noejul_txt = generate_noejul_text(nick)
        reward = len(noejul_txt) * 50 # 뇌절 보너스 대폭 상향!
        update_money(nick, reward)
        socketio.emit('message', {
            'nickname': nick, 'msg': f"🌀 뇌절 가동!! 🌀\n{noejul_txt}\n💰 뇌절 적립금 +{reward}₩!",
            'rank': rank, 'type': 'noejul'
        }, room='main')
        return

    # 🏦 [명령어 2] 금융 시스템 (저금, 출금, 잔액)
    if content.startswith("!저금") or content.startswith("!출금"):
        try:
            amt = int(content.split()[1])
            if content.startswith("!저금") and user['money'] >= amt:
                update_money(nick, -amt); update_money(nick, amt, bank=True)
                emit('message', {'msg': f"🏦 저금 완료: {amt}₩", 'type': 'system'})
            elif content.startswith("!출금") and user['bank_money'] >= amt:
                update_money(nick, amt); update_money(nick, -amt, bank=True)
                emit('message', {'msg': f"🏦 출금 완료: {amt}₩", 'type': 'system'})
            else: emit('message', {'msg': "❌ 잔액 부족!", 'type': 'system'})
        except: pass
        return

    if content in ["!잔액", "!적립", "!순위"]:
        user = get_user(nick)
        msg = f"💰 {nick}님 | 총자산: {user['money']+user['bank_money']}₩ (현금:{user['money']}/은행:{user['bank_money']}) | 등급: {rank}"
        emit('message', {'msg': msg, 'type': 'system'})
        return

    # 🤖 [명령어 3] Gemini AI
    if content.startswith("!gemini ") and client:
        try:
            res = client.models.generate_content(model="gemini-2.0-flash", contents=content[8:])
            socketio.emit('message', {'msg': f"🤖 Gemini: {res.text}", 'type': 'bot'}, room='main')
        except: pass
        return

    # 일반 채팅 적립 및 전송
    update_money(nick, 10 + (len(content) * 2))
    socketio.emit('message', {'nickname': nick, 'msg': content, 'rank': rank, 'type': 'chat'}, room='main')

if __name__ == '__main__':
    init_db()
    threading.Thread(target=interest_system, daemon=True).start()
    import eventlet.wsgi
    eventlet.wsgi.server(eventlet.listen(('', PORT)), app)
