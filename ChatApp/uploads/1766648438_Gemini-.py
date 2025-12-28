import sqlite3
import random
import os
import sys
import json
import time
import subprocess
from contextlib import contextmanager
from datetime import datetime
from flask import Flask, render_template, request, send_from_directory, url_for
from flask_socketio import SocketIO, emit, join_room
from werkzeug.utils import secure_filename
from google import genai

# 1. 필수 라이브러리 설치
try:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "Flask", "Flask-SocketIO", "eventlet", "google-genai", "-q"])
except: pass

# 2. 서버 설정
PORT = 5001
UPLOAD_FOLDER = 'uploads'
DB_FILE = "chat_db.sqlite"
if not os.path.exists(UPLOAD_FOLDER): os.makedirs(UPLOAD_FOLDER)

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Gemini 초기화
client = None
try:
    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key: client = genai.Client(api_key=api_key)
except: pass

# --- 3. 데이터베이스 시스템 ---
@contextmanager
def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    try: yield conn
    finally:
        conn.commit()
        conn.close()

def init_db():
    with get_db() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS users (nickname TEXT PRIMARY KEY, money INTEGER DEFAULT 1000)")

def get_user(nick):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE nickname=?", (nick,)).fetchone()
        return {"nickname": row['nickname'], "money": row['money']} if row else None

def update_money(nick, amount):
    with get_db() as conn:
        conn.execute("INSERT OR IGNORE INTO users (nickname, money) VALUES (?, 1000)", (nick,))
        conn.execute("UPDATE users SET money = money + ? WHERE nickname = ?", (amount, nick))

# --- 4. 라우팅 및 파일 업로드 ---
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

# --- 5. 실시간 통신 (VIP & 뉴스 로직 포함) ---
@socketio.on('join')
def on_join(data):
    join_room('main')
    nick = data['nickname']
    if not get_user(nick): update_money(nick, 0)
    emit('message', {'msg': f"📢 {nick}님이 멀티버스에 입장했습니다!", 'type': 'system'}, room='main')

@socketio.on('send_msg')
def handle_msg(data):
    nick = data['nickname']
    content = data['msg'].strip()
    if not content: return

    # 💰 [적립 로직] 기본 10 + 글자수 * 2
    reward = 10 + (len(content) * 2)
    update_money(nick, reward)
    
    # 📊 [경제 뉴스] 보상이 5,000₩ 이상이면 속보 발송
    if reward > 5000:
        news = f"📊 [경제 속보] {nick}님이 대용량 텍스트를 투척! 멀티버스 인플레이션 발생! (+{reward}₩)"
        socketio.emit('message', {'msg': news, 'type': 'news'}, room='main')

    # 💎 [VIP 판별] 100만 원 이상 재벌
    user = get_user(nick)
    is_vip = user['money'] >= 1000000
    
    # 메시지 전송
    socketio.emit('message', {
        'nickname': nick,
        'msg': content,
        'is_vip': is_vip,
        'type': 'chat'
    }, room='main')

    # 명령어 처리
    if content in ["!적립", "!잔액"]:
        emit('message', {'msg': f"💰 {nick}님 현재 잔액: {user['money']}₩ {'(💎 VIP)' if is_vip else ''}", 'type': 'system'})
    
    elif content.startswith("!gemini ") and client:
        try:
            res = client.models.generate_content(model="gemini-2.0-flash", contents=content[8:])
            socketio.emit('message', {'msg': f"🤖 Gemini: {res.text}", 'type': 'bot'}, room='main')
        except: pass

if __name__ == '__main__':
    init_db()
    import eventlet
    import eventlet.wsgi
    print(f"🚀 재벌 전용 서버 가동: http://127.0.0.1:{PORT}")
    eventlet.wsgi.server(eventlet.listen(('', PORT)), app)
