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
    "countdown": 0,
    "is_siphoning_interactively": False  # Interlocking flag to prevent thread collision
}

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
    if len(STATE["logs"]) > 100: STATE["logs"].pop(0)
    print(log_line)

def make_rand_str(length=10):
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

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
        if login_res.status_code == 200: return session
    except Exception: pass
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
    except Exception: pass
    return None

def run_single_game_session(session):
    try:
        start_req = session.post(ENDPOINTS["start"], json={}, timeout=10)
        if start_req.status_code != 200: return False
        start_data = start_req.json()
        if not start_data.get("success"): return False
        
        game_token = start_data.get("gameToken")
        time.sleep(3.1)

        sub_req = session.post(ENDPOINTS["submit"], json={"score": 30, "gameToken": game_token}, timeout=10)
        return sub_req.status_code == 200
    except Exception: return False

# --- Auto-Interleaved Siphon Injector Routine ---
def check_and_trigger_inline_siphon(trigger_acc, current_diamonds):
    # Gate 1: Only initiate the global harvest sweep if the triggering account hits 50+ diamonds
    if current_diamonds < 50: return
    
    if not STATE["receiver_username"] or not STATE["receiver_asset_id"]:
        emit_log(f"⚠️ [{trigger_acc['username']}] reached {current_diamonds} 💎 but sweep was skipped because no receiver target is locked!")
        return

    if STATE["is_siphoning_interactively"]:
        return

    # Activate atomic synchronization locks for a full global sweep
    STATE["is_siphoning_interactively"] = True
    old_status = STATE["status"]
    STATE["status"] = "GLOBAL AUTOPILOT SWEEP"
    
    locked_user = STATE["receiver_username"]
    locked_asset = STATE["receiver_asset_id"]

    emit_log(f"🚨 GLOBAL SWEEP TRIGGERED: [{trigger_acc['username']}] hit {current_diamonds} 💎!")
    emit_log("⏸️ Pausing farming pipeline threads. Scanning all alternative wallets...")

    try:
        # Get receiver account profile information
        receiver_acc = next((a for a in STATE["accounts"] if a["username"] == locked_user), None)
        
        # Loop through EVERY account inside local server memory registry
        for acc in STATE["accounts"]:
            if acc["username"] == locked_user: continue
            
            u, p = acc["username"], acc["password"]
            
            # Authenticate alternative account session 
            sess = get_auth_session(u, p)
            if not sess: continue
            
            ud = fetch_user_data(sess)
            if not ud: continue
            
            balance = ud["diamonds"]
            acc["diamonds"] = balance
            
            # Condition: Siphon any account that has strictly more than the 5 diamond floor minimum
            if balance > 5:
                dynamic_price = balance - 5  # Leaves exactly 5 diamonds behind in the wallet
                emit_log(f"🔮 [Sweep] Found {balance} 💎 on Alt [{u}]. Harvesting {dynamic_price} 💎...")
                
                # Authenticate receiver session to list the transfer vehicle asset
                if receiver_acc and receiver_acc.get("password"):
                    recv_sess = get_auth_session(receiver_acc["username"], receiver_acc["password"])
                else:
                    recv_sess = get_auth_session(locked_user, p)

                if not recv_sess:
                    recv_sess = get_auth_session(u, p) # Ultimate handshake proxy vehicle fallback
                    
                if not recv_sess:
                    emit_log(f"❌ Skipped [{u}]: Failed to verify receiver network tokens.")
                    continue

                # Place market listing order
                list_payload = {"action": "list", "creatureId": locked_asset, "price": dynamic_price, "priceType": "diamonds"}
                list_req = recv_sess.post(ENDPOINTS["trade"], json=list_payload, timeout=10)
                
                if list_req.status_code == 200:
                    emit_log(f"Asset listed for {dynamic_price} 💎. Executing transaction from Alt...")
                    time.sleep(1.2)  # Cooldown propagation wait step buffer
                    
                    # FIX: We use the existing 'sess' structure directly instead of re-logging in and breaking tokens!
                    buy_payload = {"action": "buy", "creatureId": locked_asset}
                    buy_req = sess.post(ENDPOINTS["trade"], json=buy_payload, timeout=10)
                    
                    if buy_req.status_code == 200:
                        time.sleep(3.2)  # Secure action cooldown timing bypass
                        
                        emit_log(f"Gifting asset back to [{locked_user}]...")
                        gift_payload = {"action": "gift", "creatureId": locked_asset, "toUsername": locked_user}
                        sess.post(ENDPOINTS["trade"], json=gift_payload, timeout=10)
                        
                        acc["diamonds"] = 5  # Update local screen layout tracker context state
                        emit_log(f"🎉 Sweep Success! Extracted diamonds from [{u}]. Wallet preserved at 5 💎.")
                    else:
                        emit_log(f"❌ Buy transaction rejected for Alt [{u}]. Server response status: {buy_req.status_code}")
                else:
                    emit_log(f"❌ Failed to list trade vehicle from receiver main profile. Status code: {list_req.status_code}")
                    
    except Exception as e:
        emit_log(f"❌ Internal exception occurred inside global automation sweep layer: {str(e)}")

    emit_log("▶️ Global autopilot sweep complete. Resuming farming loop pipelines smoothly...")
    STATE["status"] = old_status
    STATE["is_siphoning_interactively"] = False

def process_account_farm(acc, batch):
    if STATE["stop_farming_process"]: return
    
    # Spin-wait loop interface if a separate account is actively holding an open siphon lock
    while STATE["is_siphoning_interactively"]:
        if STATE["stop_farming_process"]: return
        time.sleep(0.5)

    u = acc["username"]
    p = acc["password"]
    sess = get_auth_session(u, p)
    if not sess: return

    user_data = fetch_user_data(sess)
    if not user_data: return

    emit_log(f"Processing profile [{u}] for Batch {batch}/3...")
    
    passes = 0
    with ThreadPoolExecutor(max_workers=5) as game_pool:
        futures = [game_pool.submit(run_single_game_session, sess) for _ in range(10)]
        for f in futures:
            if f.result(): passes += 1

    acc["points"] = user_data["infinityRunPoints"] + (passes * 30)

    if STATE["chk_collect"]:
        try: sess.post(ENDPOINTS["collect"], json={}, timeout=10)
        except Exception: pass

    updated = fetch_user_data(sess)
    if updated:
        acc["username"] = u
        acc["password"] = p
        acc["diamonds"] = updated["diamonds"]
        acc["points"] = updated["infinityRunPoints"]
        
        # INTERCEPT AUTOMATION POINT: Evaluate wallet parameters instantly
        check_and_trigger_inline_siphon(acc, updated["diamonds"])

def background_farm_loop():
    STATE["status"] = "RUNNING QUEUE"
    while not STATE["stop_farming_process"]:
        for batch in range(1, 4):
            if STATE["stop_farming_process"]: break
            
            while STATE["is_siphoning_interactively"]: time.sleep(0.5)
            
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
                    while STATE["is_siphoning_interactively"]: time.sleep(0.1)
                    STATE["countdown"] = remaining
                    time.sleep(1)
                STATE["countdown"] = 0

        if not STATE["stop_farming_process"] and STATE["chk_exchange"]:
            while STATE["is_siphoning_interactively"]: time.sleep(0.5)
            emit_log("🔒 Third batch completed. Running multi-redemption loop across profiles...")
            
            def redeem(acc):
                sess = get_auth_session(acc["username"], acc["password"])
                if sess:
                    ud = fetch_user_data(sess)
                    if ud:
                        current_pts = ud["infinityRunPoints"]
                        # FIX: Loop to burn ALL available point surpluses down below 900
                        while current_pts >= 900 and not STATE["stop_farming_process"]:
                            try:
                                emit_log(f"[{acc['username']}] Burning points balance surplus ({current_pts} Pts remaining)...")
                                payload = {"rewardId": "reward-7", "pointsCost": 900, "rewardType": "diamonds", "rewardValue": 5, "rarity": ""}
                                res = sess.post(ENDPOINTS["exchange"], json=payload, timeout=10)
                                if res.status_code != 200: break
                                
                                next_ud = fetch_user_data(sess)
                                if not next_ud or next_ud["infinityRunPoints"] == current_pts: break
                                ud = next_ud
                                current_pts = ud["infinityRunPoints"]
                                acc["diamonds"] = ud["diamonds"]
                                acc["points"] = ud["infinityRunPoints"]
                                emit_log(f"[{acc['username']}] Redeem successful! Wallet: {ud['diamonds']} 💎 | {current_pts} Pts")
                            except Exception:
                                break
                        
                        # Check if point conversion pushed them into global sweep conditions
                        check_and_trigger_inline_siphon(acc, ud["diamonds"])

            with ThreadPoolExecutor(max_workers=max(1, len(STATE["accounts"]))) as ex:
                ex.map(redeem, STATE["accounts"])

        if STATE["stop_farming_process"]: break
        emit_log("Round finished. Waiting 70-second buffer interval before resetting to Batch 1...")
        for remaining in range(70, 0, -1):
            if STATE["stop_farming_process"]: break
            while STATE["is_siphoning_interactively"]: time.sleep(0.1)
            STATE["countdown"] = remaining
            time.sleep(1)
        STATE["countdown"] = 0

    STATE["status"] = "Idle"
    STATE["batch_phase"] = "Batch 0/3"
    STATE["countdown"] = 0
    emit_log("🏁 Farming engine operations suspended.")



# --- Flask Routing Matrix ---
@app.route('/')
def home(): return render_template('index.html')

@app.route('/state', methods=['GET'])
def get_state(): return jsonify(STATE)

@app.route('/sync-accounts', methods=['POST'])
def sync_accounts():
    if not STATE["is_siphoning_interactively"]:
        STATE["accounts"] = request.json.get("accounts", [])
    return jsonify({"success": True})

@app.route('/toggle-config', methods=['POST'])
def toggle_config():
    opt = request.json.get("option")
    if opt in STATE: STATE[opt] = not STATE[opt]
    return jsonify({"success": True})

@app.route('/update-price', methods=['POST'])
def update_price():
    STATE["siphon_price"] = request.json.get("price", "1")
    return jsonify({"success": True})

@app.route('/start-farm', methods=['POST'])
def start_farm():
    STATE["accounts"] = request.json.get("accounts", [])
    if not STATE["accounts"]: return jsonify({"error": "No accounts provided"}), 400
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
    return jsonify({"success": True})

@app.route('/set-target', methods=['POST'])
def set_target():
    username = request.json.get("username")
    password = request.json.get("password", "")
    def worker():
        emit_log(f"Connecting validation routine for receiver [{username}]...")
        sess = get_auth_session(username, password)
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
                else: emit_log("Authentication complete, but profile owns no valid assets.")
        except Exception as e: emit_log(f"Network error verifying asset metadata: {str(e)}")
    GLOBAL_EXECUTOR.submit(worker)
    return jsonify({"success": True})

@app.route('/bulk-signup', methods=['POST'])
def bulk_signup():
    emit_log("Spawning thread pool registration processes (10 Accounts)...")
    new_accounts = []
    def task():
        u = make_rand_str(9)
        p = make_rand_str(12)
        try:
            res = requests.post(ENDPOINTS["signup"], json={"username": u, "password": p}, timeout=10)
            if res.status_code in [200, 201]:
                new_accounts.append({"username": u, "password": p, "points": 0, "diamonds": 0})
                emit_log(f"Created account: {u}")
                sess = get_auth_session(u, p)
                if sess and STATE["avatar_url"]:
                    sess.patch(ENDPOINTS["profile"], json={"profileImageUrl": STATE["avatar_url"]}, timeout=10)
        except Exception: pass

    with ThreadPoolExecutor(max_workers=5) as sub_pool:
        futures = [sub_pool.submit(task) for _ in range(10)]
        for f in futures: f.result()
    emit_log("Bulk profile generation finalized.")
    return jsonify({"success": True, "created": new_accounts})

@app.route('/refresh-stats', methods=['POST'])
def refresh_stats():
    passed_accounts = request.json.get("accounts", [])
    if not passed_accounts: return jsonify({"error": "No accounts provided"}), 400
    
    emit_log("Starting balance synchronization and multi-point check engine...")
    updated_list = []

    def refresh_worker():
        for acc in passed_accounts:
            u, p = acc["username"], acc["password"]
            sess = get_auth_session(u, p)
            if sess:
                ud = fetch_user_data(sess)
                if ud:
                    current_pts = ud["infinityRunPoints"]
                    # FIX: Apply the consecutive looping fix to manual stat refreshing too!
                    while current_pts >= 900:
                        emit_log(f"[{u}] Clearing point balance surplus ({current_pts} Pts remaining)...")
                        try:
                            payload = {"rewardId": "reward-7", "pointsCost": 900, "rewardType": "diamonds", "rewardValue": 5, "rarity": ""}
                            res = sess.post(ENDPOINTS["exchange"], json=payload, timeout=10)
                            if res.status_code != 200: break
                            
                            next_ud = fetch_user_data(sess)
                            if not next_ud or next_ud["infinityRunPoints"] == current_pts: break
                            ud = next_ud
                            current_pts = ud["infinityRunPoints"]
                        except Exception:
                            break
                    
                    acc["diamonds"] = ud["diamonds"]
                    acc["points"] = ud["infinityRunPoints"]
                    emit_log(f"Sync complete for [{u}]: {ud['diamonds']} 💎 | {ud['infinityRunPoints']} Pts")
            else:
                emit_log(f"Unable to authenticate [{u}] during stat refresh layout sync.")
            updated_list.append(acc)
        
        STATE["accounts"] = updated_list
        emit_log("✅ All local storage balances checked and synced successfully.")

    GLOBAL_EXECUTOR.submit(refresh_worker)
    return jsonify({"success": True})
    
@app.route('/execute-siphon', methods=['POST'])
def execute_siphon():
    req_data = request.get_json(force=True) or {}
    passed_accounts = req_data.get("accounts", [])
    if not passed_accounts: passed_accounts = STATE["accounts"]

    if not passed_accounts: return jsonify({"error": "No accounts available"}), 400
    if not STATE["receiver_username"] or not STATE["receiver_asset_id"]: return jsonify({"error": "No targets verified"}), 400
    
    target_user = STATE["receiver_username"]
    target_asset = STATE["receiver_asset_id"]

    def worker(accounts_to_process, locked_user, locked_asset):
        emit_log(f"🔮 Initializing Pre-Owned Asset Extraction Matrix targeting [{locked_user}]...")
        receiver_acc = next((a for a in accounts_to_process if a["username"] == locked_user), None)
        if not receiver_acc: receiver_acc = {"username": locked_user, "password": ""}

        processed_count = 0
        for acc in accounts_to_process:
            if STATE["stop_farming_process"]: break
            if acc["username"] == locked_user: continue

            processed_count += 1
            emit_log(f"Logging into Alt [{acc['username']}] to verify balances...")
            sess = get_auth_session(acc["username"], acc["password"])
            if not sess: continue
            ud = fetch_user_data(sess)
            if not ud: continue

            balance = ud["diamonds"]
            acc["diamonds"] = balance
            if balance <= 0: continue

            dynamic_price = balance
            while balance >= dynamic_price and not STATE["stop_farming_process"]:
                emit_log(f"Listing asset from Receiver account dynamically for exact balance: {dynamic_price} 💎...")
                recv_sess = get_auth_session(receiver_acc["username"], receiver_acc.get("password", ""))
                if not recv_sess: break

                list_payload = {"action": "list", "creatureId": locked_asset, "price": dynamic_price, "priceType": "diamonds"}
                if recv_sess.post(ENDPOINTS["trade"], json=list_payload, timeout=10).status_code != 200: break
                
                sess = get_auth_session(acc["username"], acc["password"])
                if not sess: break
                if sess.post(ENDPOINTS["trade"], json={"action": "buy", "creatureId": locked_asset}, timeout=10).status_code != 200: break
                time.sleep(3.0)
                sess.post(ENDPOINTS["trade"], json={"action": "gift", "creatureId": locked_asset, "toUsername": locked_user}, timeout=10)
                
                balance -= dynamic_price
                acc["diamonds"] = balance
                emit_log(f"Successfully moved all {dynamic_price} 💎 to target and returned pet asset!")

        emit_log(f"✨ Dynamic siphon matrix sequence complete. Processed {processed_count} alternative accounts.")

    GLOBAL_EXECUTOR.submit(worker, list(passed_accounts), target_user, target_asset)
    return jsonify({"success": True})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
