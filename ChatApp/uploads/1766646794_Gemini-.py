import sqlite3
import random
import os
import sys
import json
import time
import subprocess
from datetime import datetime
from flask import Flask, render_template, request, send_from_directory, url_for
from flask_socketio import SocketIO, emit, join_room
from werkzeug.utils import secure_filename
from google import genai

# 1. 필수 라이브러리 자동 설치
try:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "Flask", "Flask-SocketIO", "eventlet", "google-genai", "-q"])
except: pass

# 2. 설정 및 폴더 준비
PORT = 5001
UPLOAD_FOLDER = 'uploads'
DB_FILE = "chat_db.sqlite"
if not os.path.exists(UPLOAD_FOLDER): os.makedirs(UPLOAD_FOLDER)

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB 제한
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Gemini 초기화
client = None
try:
    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key: client = genai.Client(api_key=api_key)
except: pass

# --- 3. 데이터베이스 로직 ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users 
                 (nickname TEXT PRIMARY KEY, money INTEGER DEFAULT 1000, items TEXT DEFAULT '{}')""")
    conn.commit()
    conn.close()

def get_user(nick):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE nickname=?", (nick,))
    row = c.fetchone()
    conn.close()
    if row: return {"nickname": row[0], "money": row[1]}
    return None

def update_money(nick, amount):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (nickname, money) VALUES (?, 1000)", (nick,))
    c.execute("UPDATE users SET money = money + ? WHERE nickname = ?", (amount, nick))
    conn.commit()
    conn.close()

# --- 4. 파일 업로드 및 서버 경로 ---
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
        socketio.emit('message', {'msg': f"<span style='color:#818cf8; font-weight:bold;'>{nick}</span>: {msg}"}, room='main')
        return "OK"
    return "Error", 400

@app.route('/uploads/<filename>')
def download_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# --- 5. 실시간 통신 및 명령어 (적립 로직 포함) ---
@socketio.on('join')
def on_join(data):
    join_room('main')
    nick = data['nickname']
    if not get_user(nick): update_money(nick, 0)
    emit('message', {'msg': f"📢 {nick}님이 입장했습니다! (기본 1000₩ 지급)"}, room='main')

@socketio.on('send_msg')
def handle_msg(data):
    nick = data['nickname']
    content = data['msg'].strip()
    if not content: return

    # 💰 [핵심] 메시지 길이에 따른 차등 적립 (기본 10원 + 글자수*2원)
    reward = 10 + (len(content) * 2)
    update_money(nick, reward)
    
    # 메시지 전송
    socketio.emit('message', {'msg': f"<span style='color:#818cf8; font-weight:bold;'>{nick}</span>: {content}"}, room='main')

    # 명령어 처리
    if content in ["!적립", "!잔액"]:
        user = get_user(nick)
        emit('message', {'msg': f"💰 <b>{nick}</b>님, 방금 <b>{reward}₩</b> 적립! 현재 잔액: <b>{user['money']}₩</b>"})

    elif content.startswith("!도박 "):
        try:
            bet = int(content.split()[1])
            user = get_user(nick)
            if user['money'] < bet: emit('message', {'msg': "❌ 잔액 부족!"})
            else:
                if random.random() > 0.5:
                    update_money(nick, bet)
                    socketio.emit('message', {'msg': f"🎲 {nick}님 도박 성공! {bet*2}₩ 획득!"}, room='main')
                else:
                    update_money(nick, -bet)
                    socketio.emit('message', {'msg': f"📉 {nick}님 도박 실패... {bet}₩ 손실"}, room='main')
        except: emit('message', {'msg': "❓ 사용법: !도박 [금액]"})

    elif content.startswith("!gemini ") and client:
        prompt = content[8:]
        try:
            res = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
            socketio.emit('message', {'msg': f"<div style='background:#1e293b; padding:10px; border-left:4px solid #38bdf8; margin:5px 0;'>🤖 <b>Gemini</b>: {res.text}</div>"}, room='main')
        except: emit('message', {'msg': "❌ Gemini 응답 오류"})

if __name__ == '__main__':
    init_db()
    import eventlet
    import eventlet.wsgi
    print(f"🚀 서버 가동: http://127.0.0.1:{PORT}")
    eventlet.wsgi.server(eventlet.listen(('', PORT)), app)
