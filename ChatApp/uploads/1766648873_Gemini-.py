import sqlite3
import random
import os
import sys
import json
import time
import subprocess
from contextlib import contextmanager
from flask import Flask, render_template, request, send_from_directory, url_for
from flask_socketio import SocketIO, emit, join_room
from werkzeug.utils import secure_filename
from google import genai

# 1. 라이브러리 자동 설치
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

# --- 4. 라우팅 ---
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

# --- 5. 실시간 통신 (선물/도박/황제 기능 포함) ---
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

    # 💰 [적립] 기본 10 + 글자수 * 2
    reward = 10 + (len(content) * 2)
    update_money(nick, reward)
    
    # 📊 [경제 뉴스] 보상이 5,000₩ 이상이면 속보
    if reward > 5000:
        news = f"📊 [경제 속보] {nick}님의 대량 텍스트 투척으로 인플레이션 발생! (+{reward}₩)"
        socketio.emit('message', {'msg': news, 'type': 'news'}, room='main')

    # 칭호 판별
    user = get_user(nick)
    rank = "일반"
    if user['money'] >= 5000000: rank = "황제"
    elif user['money'] >= 1000000: rank = "VIP"

    # 명령어 처리
    if content.startswith("!선물"):
        try:
            _, target, amount = content.split()
            amount = int(amount)
            if user['money'] >= amount and amount > 0:
                update_money(nick, -amount)
                update_money(target, amount)
                socketio.emit('message', {'msg': f"🎁 [선물] {nick}님이 {target}님에게 {amount}₩을 하사하셨습니다!", 'type': 'news'}, room='main')
            else: emit('message', {'msg': "❌ 잔액이 부족하거나 잘못된 금액입니다.", 'type': 'system'})
        except: emit('message', {'msg': "❓ 사용법: !선물 [닉네임] [금액]", 'type': 'system'})
        return

    if content.startswith("!도박"):
        try:
            bet = int(content.split()[1])
            if user['money'] < bet or bet <= 0:
                emit('message', {'msg': "❌ 잔액 부족!", 'type': 'system'})
            else:
                if random.random() > 0.5:
                    update_money(nick, bet)
                    socketio.emit('message', {'msg': f"🎰 [도박 성공] {nick}님이 {bet}₩을 걸어 두 배로 불렸습니다! 대박!", 'type': 'news'}, room='main')
                else:
                    update_money(nick, -bet)
                    socketio.emit('message', {'msg': f"📉 [도박 실패] {nick}님이 {bet}₩을 허공에 날렸습니다...", 'type': 'system'}, room='main')
        except: emit('message', {'msg': "❓ 사용법: !도박 [금액]", 'type': 'system'})
        return

    if content in ["!적립", "!잔액"]:
        emit('message', {'msg': f"💰 {nick}님 현재 잔액: {user['money']}₩ [등급: {rank}]", 'type': 'system'})
        return

    # 메시지 전송
    socketio.emit('message', {
        'nickname': nick,
        'msg': content,
        'rank': rank,
        'type': 'chat'
    }, room='main')

    if content.startswith("!gemini ") and client:
        try:
            res = client.models.generate_content(model="gemini-2.0-flash", contents=content[8:])
            socketio.emit('message', {'msg': f"🤖 Gemini: {res.text}", 'type': 'bot'}, room='main')
        except: pass

if __name__ == '__main__':
    init_db()
    import eventlet
    import eventlet.wsgi
    eventlet.wsgi.server(eventlet.listen(('', PORT)), app)
