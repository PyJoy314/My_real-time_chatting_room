import sqlite3
import os
import time
import threading
import random
from flask import Flask, render_template, request, send_from_directory, url_for
from flask_socketio import SocketIO, emit, join_room
from werkzeug.utils import secure_filename

# --- [환경 설정] ---
PORT = 5001
UPLOAD_FOLDER = 'uploads'
DB_FILE = "multiverse_empire_ultimate.sqlite"

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

noejul_loops = {}
crypto_prices = {"비트코인": 50000000} 

# Gemini AI 로드
client = None
try:
    from google import genai
    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key: client = genai.Client(api_key=api_key)
except: pass

# --- [DB 시스템: 영구 보존] ---
def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                nickname TEXT PRIMARY KEY, 
                money INTEGER DEFAULT 1000, 
                bank_money INTEGER DEFAULT 0,
                btc_amount REAL DEFAULT 0
            )
        """)
        # 채팅 기록 보존 테이블
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nickname TEXT,
                msg TEXT,
                type TEXT,
                rank TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

def get_user(nick):
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("INSERT OR IGNORE INTO users (nickname) VALUES (?)", (nick,))
        return conn.execute("SELECT * FROM users WHERE nickname=?", (nick,)).fetchone()

def update_db(nick, col, amount):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute(f"UPDATE users SET {col} = {col} + ? WHERE nickname = ?", (amount, nick))
        conn.commit()

# [실시간 경제 시스템: 뉴스 및 시세 변동]
def background_scheduler():
    global crypto_prices
    while True:
        time.sleep(60) 
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute("UPDATE users SET bank_money = CAST(bank_money * 1.01 AS INTEGER) WHERE bank_money > 0")
            conn.commit()
        
        crypto_prices["비트코인"] = int(crypto_prices["비트코인"] * random.uniform(0.90, 1.15))
        news = f"📰 [제국 경제 뉴스] 비트코인 현재가: {crypto_prices['비트코인']:,}₩ | 은행 이자 1% 지급 완료!"
        socketio.emit('message', {'msg': news, 'type': 'system'}, room='main')

# --- [로직 처리] ---
@app.route('/')
def index(): return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    file = request.files.get('file'); nick = request.form.get('nickname', 'Unknown')
    if file:
        uname = f"{int(time.time())}_{secure_filename(file.filename)}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], uname))
        url = url_for('download_file', filename=uname, _external=True)
        msg = f"📂 {nick}님이 파일을 공유했습니다: {url}"
        socketio.emit('message', {'msg': msg, 'type': 'system'}, room='main')
        return 'OK'
    return 'Fail', 400

@app.route('/uploads/<filename>')
def download_file(filename): return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@socketio.on('join')
def on_join(data):
    join_room('main')
    # 이전 채팅 기록 불러오기
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        logs = conn.execute("SELECT * FROM (SELECT * FROM chats ORDER BY id DESC LIMIT 20) ORDER BY id ASC").fetchall()
        for log in logs:
            emit('message', {'nickname': log['nickname'], 'msg': log['msg'], 'type': log['type'], 'rank': log['rank']})
    emit('message', {'msg': f"🚀 {data['nickname']}님이 제국에 접속했습니다!", 'type': 'system'}, room='main')

@socketio.on('send_msg')
def handle_msg(data):
    nick = data['nickname']; msg = data['msg'].strip()
    if not msg: return
    user = get_user(nick); msg_len = len(msg)
    
    # [수익 로직] 메시지 길이에 따른 자동 ₩ 적립
    reward = 100 + (msg_len * 5) 
    update_db(nick, "money", reward)

    display_msg = msg
    if msg_len > 1000: # 대용량 메시지 처리
        filename = f"LARGE_{int(time.time())}_{nick}.txt"
        with open(os.path.join(UPLOAD_FOLDER, filename), "w", encoding="utf-8") as f: f.write(msg)
        link = url_for('download_file', filename=filename, _external=True)
        display_msg = f"📄 [대용량 데이터] 길이: {msg_len}자 | 적립: {reward:,}₩\n🔗 링크: {link}"

    parts = msg.split()
    cmd = parts[0].lower() if msg.startswith("!") else ""

    # [명령어 시스템 통합]
    if cmd == "!잔액":
        btc_val = int(user['btc_amount'] * crypto_prices['비트코인'])
        total = user['money'] + user['bank_money'] + btc_val
        res = (f"💰 {nick}님의 자산 보고서\n"
               f"💵 현금: {user['money']:,}₩\n"
               f"🏦 은행: {user['bank_money']:,}₩\n"
               f"🪙 비트코인 가치: {btc_val:,}₩\n"
               f"💳 총합 자산: {total:,}₩")
        emit('message', {'msg': res, 'type': 'system'})

    elif cmd == "!저금":
        try:
            amt = int(parts[1])
            if user['money'] >= amt:
                update_db(nick, "money", -amt); update_db(nick, "bank_money", amt)
                emit('message', {'msg': f"🏦 {amt:,}₩ 저금 완료!", 'type': 'system'})
        except: pass

    elif cmd == "!출금":
        try:
            amt = int(parts[1])
            if user['bank_money'] >= amt:
                update_db(nick, "money", amt); update_db(nick, "bank_money", -amt)
                emit('message', {'msg': f"🏧 {amt:,}₩ 출금 완료!", 'type': 'system'})
        except: pass

    elif cmd == "!가위바위보":
        try:
            choice = parts[1]; bet = int(parts[2])
            if user['money'] >= bet:
                com = random.choice(["가위", "바위", "보"])
                if choice == com: result = "무승부"; update_db(nick, "money", 0)
                elif (choice=="가위" and com=="보") or (choice=="바위" and com=="가위") or (choice=="보" and com=="바위"):
                    result = "승리"; update_db(nick, "money", bet)
                else: result = "패배"; update_db(nick, "money", -bet)
                emit('message', {'msg': f"🎮 결과: 나({choice}) vs 컴({com}) -> {result}!", 'type': 'system'})
        except: pass

    elif cmd == "!매수":
        try:
            amt = int(parts[2])
            if user['money'] >= amt:
                qty = amt / crypto_prices['비트코인']
                update_db(nick, "money", -amt); update_db(nick, "btc_amount", qty)
                emit('message', {'msg': f"📉 비트코인 {qty:.6f}개 매수 성공!", 'type': 'system'})
        except: pass

    elif cmd == "!랭킹":
        with sqlite3.connect(DB_FILE) as conn:
            rows = conn.execute("SELECT nickname, (money + bank_money) as total FROM users ORDER BY total DESC LIMIT 10").fetchall()
            res = "🏆 [제국 부자 순위]\n" + "\n".join([f"{i+1}위: {r[0]} ({r[1]:,}₩)" for i, r in enumerate(rows)])
            emit('message', {'msg': res, 'type': 'system'})

    elif cmd in ["!뇌절", "!무한뇌절"]:
        noejul_loops[nick] = True
        def noejul_task(n):
            while noejul_loops.get(n):
                update_db(n, "bank_money", 5000)
                socketio.emit('message', {'nickname': n, 'msg': "🌀 뇌절 채굴 중... (+5,000₩)", 'type': 'noejul'}, room='main')
                time.sleep(2)
        threading.Thread(target=noejul_task, args=(nick,), daemon=True).start()

    elif cmd in ["!뇌절정지", "!뇌절중단"]:
        noejul_loops[nick] = False

    elif cmd == "!gemini" and client:
        try:
            res = client.models.generate_content(model="gemini-2.0-flash", contents=" ".join(parts[1:]))
            socketio.emit('message', {'msg': f"🤖 Gemini: {res.text}", 'type': 'bot'}, room='main')
        except: pass

    elif cmd == "!명령어":
        emit('message', {'msg': "!잔액, !저금 [금액], !출금 [금액], !랭킹, !가위바위보 [패] [금액], !매수 비트코인 [금액], !무한뇌절, !뇌절중단, !gemini [질문]", 'type': 'system'})

    else:
        # 비트코인 현재 가치를 계산합니다 (개수 * 시세)
        btc_val = int(user['btc_amount'] * crypto_prices['비트코인'])
        
        # 현금 + 은행잔고 + 비트코인 가치를 모두 합산합니다
        total = user['money'] + user['bank_money'] + btc_val
        
        # 합산된 금액을 기준으로 등급을 판정합니다
        rank = "초월자" if total >= 10000000 else "VIP" if total >= 1000000 else "평민"
        # DB에 채팅 기록 저장
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute("INSERT INTO chats (nickname, msg, type, rank) VALUES (?, ?, ?, ?)", (nick, display_msg, 'chat', rank))
        socketio.emit('message', {'nickname': nick, 'msg': display_msg, 'type': 'chat', 'rank': rank, 'reward': f"+{reward:,}₩"}, room='main')

if __name__ == '__main__':
    init_db()
    threading.Thread(target=background_scheduler, daemon=True).start()
    socketio.run(app, host='0.0.0.0', port=PORT, debug=False)

