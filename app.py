import os
import json
import random
import string
import time
import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, render_template, jsonify, request

app = Flask(__name__)

# --- Global State Tracking Matrix ---
STATE = {
    "accounts": [],
    "stop_farming_process": False,
    "receiver_username": "",
    "receiver_asset_id": "",
    "avatar_url": "https://files.catbox.moe/fl4o79.jpg",
    "siphon_price": "1",
    "chk_collect": True,
    "chk_exchange": True,
    "logs": [],
    "status": "Idle",
    "batch_phase": "Batch 0/3",
    "countdown": 0
}

# --- Network Configuration Matrix ---
BASE_URL = "https://furrymon-tycoon.dittoxgame.com/api"
ENDPOINTS = {
    "start": f"{BASE_URL}/infinity-run/start",
    "submit": f"{BASE_URL}/infinity-run/save-score",
    "exchange": f"{BASE_URL}/infinity-run/exchange",
    "collect": f"{BASE_URL}/habitats/collect-all",
    "user": f"{BASE_URL}/user",
    "profile": f"{BASE_URL}/profile",
    "csrf": f"{BASE_URL}/auth/csrf",
    "callback": f"{BASE_URL}/auth/callback/credentials",
    "creatures": f"{BASE_URL}/creatures",
    "trade": f"{BASE_URL}/trade",
    "signup": f"{BASE_URL}/signup"
}

GLOBAL_EXECUTOR = ThreadPoolExecutor(max_workers=5)

def emit_log(message):
    timestamp = datetime.now().strftime("%H:%M:%S")
    log_line = f"[{timestamp}] {message}"
    STATE["logs"].append(log_line)
    if len(STATE["logs"]) > 100:
        STATE["logs"].pop(0)
    print(log_line)

def make_rand_str(length=10):
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

# --- Core API Interaction Utilities ---
def get_auth_session(username, password):
    session = requests.Session()
    try:
        res = session.get(ENDPOINTS["csrf"], timeout=10)
        if res.status_code != 200: return None
        token = res.json().get("csrfToken")
        if not token: return None

        payload = {
            "email": username,
            "password": password,
            "redirect": "false",
            "csrfToken": token,
            "callbackUrl": "https://furrymon-tycoon.dittoxgame.com/login",
            "json": "true"
        }
        login_res = session.post(ENDPOINTS["callback"], data=payload, timeout=10)
        if login_res.status_code == 200:
            return session
    except Exception:
        pass
    return None

def fetch_user_data(session):
    try:
        res = session.get(ENDPOINTS["user"], timeout=10)
        if res.status_code == 200:
            user_obj = res.json().get("user", {})
            return {
                "diamonds": user_obj.get("diamonds", 0),
                "infinityRunPoints": user_obj.get("infinityRunPoints", 0),
                "username": user_obj.get("username")
            }
    except Exception:
        pass
    return None

# --- Background Processing Logic ---
def run_single_game_session(session):
    try:
        start_req = session.post(ENDPOINTS["start"], json={}, timeout=10)
        if start_req.status_code != 200: return False
        start_data = start_req.json()
        if not start_data.get("success"): return False
        
        game_token = start_data.get("gameToken")
        time.sleep(9.1)

        sub_req = session.post(ENDPOINTS["submit"], json={"score": 900, "gameToken": game_token}, timeout=10)
        return sub_req.status_code == 200
    except Exception:
        return False

def process_account_farm(acc, batch):
    if STATE["stop_farming_process"]: return
    u = acc["username"]
    sess = get_auth_session(u, acc["password"])
    if not sess: return

    user_data = fetch_user_data(sess)
    if not user_data: return

    emit_log(f"Processing profile [{u}] for Batch {batch}/3...")
    
    passes = 0
    with ThreadPoolExecutor(max_workers=5) as game_pool:
        futures = [game_pool.submit(run_single_game_session, sess) for _ in range(10)]
        for f in futures:
            if f.result(): passes += 1

    acc["points"] = user_data["infinityRunPoints"] + (passes * 900)

    if STATE["chk_collect"]:
        try: sess.post(ENDPOINTS["collect"], json={}, timeout=10)
        except Exception: pass

    updated = fetch_user_data(sess)
    if updated:
        acc["diamonds"] = updated["diamonds"]
        acc["points"] = updated["infinityRunPoints"]

def background_farm_loop():
    STATE["status"] = "RUNNING QUEUE"
    while not STATE["stop_farming_process"]:
        for batch in range(1, 4):
            if STATE["stop_farming_process"]: break
            
            STATE["batch_phase"] = f"Batch {batch}/3"
            emit_log(f"⚡ Starting Global Batch Round {batch}/3...")

            with ThreadPoolExecutor(max_workers=max(1, len(STATE["accounts"]))) as executor:
                futures = [executor.submit(process_account_farm, acc, batch) for acc in STATE["accounts"]]
                for f in futures: f.result()

            emit_log(f"✅ Batch {batch}/3 complete. Balances updated.")

            if batch < 3 and not STATE["stop_farming_process"]:
                emit_log("Waiting 70-second milestone buffer interval before next loop sequence...")
                for remaining in range(70, 0, -1):
                    if STATE["stop_farming_process"]: break
                    STATE["countdown"] = remaining
                    time.sleep(1)
                STATE["countdown"] = 0

        if not STATE["stop_farming_process"] and STATE["chk_exchange"]:
            emit_log("🔒 Third batch completed. Redeeming reward structures across profiles...")
            def redeem(acc):
                sess = get_auth_session(acc["username"], acc["password"])
                if sess:
                    ud = fetch_user_data(sess)
                    if ud and ud["infinityRunPoints"] >= 900:
                        try:
                            payload = {"rewardId": "reward-7", "pointsCost": 900, "rewardType": "diamonds", "rewardValue": 5, "rarity": ""}
                            sess.post(ENDPOINTS["exchange"], json=payload, timeout=10)
                            ud = fetch_user_data(sess) or ud
                            acc["diamonds"] = ud["diamonds"]
                            acc["points"] = ud["infinityRunPoints"]
                            emit_log(f"[{acc['username']}] Payout successful! Diamonds: {ud['diamonds']}")
                        except Exception: pass

            with ThreadPoolExecutor(max_workers=max(1, len(STATE["accounts"]))) as ex:
                ex.map(redeem, STATE["accounts"])

        if STATE["stop_farming_process"]: break
        time.sleep(2)

    STATE["status"] = "Idle"
    STATE["batch_phase"] = "Batch 0/3"
    STATE["countdown"] = 0
    emit_log("🏁 Farming engine operations suspended.")

# --- Flask Routing Matrix ---
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/state', methods=['GET'])
def get_state():
    return jsonify(STATE)

@app.route('/toggle-config', methods=['POST'])
def toggle_config():
    opt = request.json.get("option")
    if opt in STATE:
        STATE[opt] = not STATE[opt]
    return jsonify({"success": True})

@app.route('/update-price', methods=['POST'])
def update_price():
    STATE["siphon_price"] = request.json.get("price", "1")
    return jsonify({"success": True})

@app.route('/start-farm', methods=['POST'])
def start_farm():
    if not STATE["accounts"]: return jsonify({"error": "No accounts"}), 400
    STATE["stop_farming_process"] = False
    GLOBAL_EXECUTOR.submit(background_farm_loop)
    return jsonify({"success": True})

@app.route('/stop-farm', methods=['POST'])
def stop_farm():
    STATE["stop_farming_process"] = True
    STATE["status"] = "Aborting Pipeline..."
    return jsonify({"success": True})

@app.route('/clear-accounts', methods=['POST'])
def clear_accounts():
    STATE["accounts"] = []
    emit_log("Account registry wiped.")
    return jsonify({"success": True})

@app.route('/set-target', methods=['POST'])
def set_target():
    username = request.json.get("username")
    acc = next((a for a in STATE["accounts"] if a["username"] == username), None)
    if not acc: return jsonify({"error": "Not found"}), 404
    
    def worker():
        emit_log(f"Connecting validation routine for receiver [{username}]...")
        sess = get_auth_session(username, acc["password"])
        if not sess:
            emit_log(f"Authentication failed for [{username}]")
            return
        try:
            res = sess.get(ENDPOINTS["creatures"], timeout=10)
            if res.status_code == 200:
                c_list = res.json().get("creatures", [])
                if c_list:
                    STATE["receiver_username"] = username
                    STATE["receiver_asset_id"] = c_list[0].get("id")
                    emit_log(f"Receiver validated. Asset ID target locked: [{STATE['receiver_asset_id']}]")
                else:
                    emit_log("Authentication complete, but profile owns no valid assets.")
        except Exception as e:
            emit_log(f"Network processing error verifying asset schemas: {str(e)}")

    GLOBAL_EXECUTOR.submit(worker)
    return jsonify({"success": True})

@app.route('/bulk-signup', methods=['POST'])
def bulk_signup():
    emit_log("Spawning thread pool registration processes (10 Accounts)...")
    def task():
        u = make_rand_str(9)
        p = make_rand_str(12)
        try:
            res = requests.post(ENDPOINTS["signup"], json={"username": u, "password": p}, timeout=10)
            if res.status_code in [200, 201]:
                STATE["accounts"].append({"username": u, "password": p, "points": 0, "diamonds": 0})
                emit_log(f"Created account: {u}")
                sess = get_auth_session(u, p)
                if sess and STATE["avatar_url"]:
                    sess.patch(ENDPOINTS["profile"], json={"profileImageUrl": STATE["avatar_url"]}, timeout=10)
        except Exception: pass

    def pool_mgr():
        with ThreadPoolExecutor(max_workers=5) as sub_pool:
            futures = [sub_pool.submit(task) for _ in range(10)]
            for f in futures: f.result()
        emit_log("Bulk profile generation finalized.")

    GLOBAL_EXECUTOR.submit(pool_mgr)
    return jsonify({"success": True})

@app.route('/execute-siphon', methods=['POST'])
def execute_siphon():
    if not STATE["receiver_username"] or not STATE["receiver_asset_id"]:
        return jsonify({"error": "No receiver"}), 400
    try: price = int(STATE["siphon_price"])
    except ValueError: return jsonify({"error": "Invalid price"}), 400

    def worker():
        emit_log(f"🔮 Initializing Siphon Extraction Matrix targeting [{STATE['receiver_username']}]...")
        receiver_acc = next((a for a in STATE["accounts"] if a["username"] == STATE["receiver_username"]), None)
        if not receiver_acc: return

        for acc in STATE["accounts"]:
            if STATE["stop_farming_process"]: break
            if acc["username"] == STATE["receiver_username"]: continue

            sess = get_auth_session(acc["username"], acc["password"])
            if not sess: continue
            ud = fetch_user_data(sess)
            if not ud: continue

            balance = ud["diamonds"]
            while balance >= price and not STATE["stop_farming_process"]:
                recv_sess = get_auth_session(receiver_acc["username"], receiver_acc["password"])
                if not recv_sess: break

                if recv_sess.post(ENDPOINTS["trade"], json={"action": "list", "creatureId": STATE["receiver_asset_id"], "price": price, "priceType": "diamonds"}, timeout=10).status_code != 200: break
                if sess.post(ENDPOINTS["trade"], json={"action": "buy", "creatureId": STATE["receiver_asset_id"]}, timeout=10).status_code != 200: break
                
                time.sleep(3.1)
                sess.post(ENDPOINTS["trade"], json={"action": "gift", "creatureId": STATE["receiver_asset_id"], "toUsername": STATE["receiver_username"]}, timeout=10)
                
                balance -= price
                acc["diamonds"] = balance
                emit_log(f"Moved {price} 💎 to target configuration successfully.")

        emit_log("✨ Siphon sequence fully finalized.")

    GLOBAL_EXECUTOR.submit(worker)
    return jsonify({"success": True})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
