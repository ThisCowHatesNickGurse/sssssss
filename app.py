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
    "is_siphoning_interactively": False
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
    "signup": f"{BASE_URL}/signup",
    "market": f"{BASE_URL}/trade?type=market"
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

def check_and_trigger_inline_siphon(trigger_acc, current_diamonds):
    if current_diamonds < 50: return
    if not STATE["receiver_username"] or not STATE["receiver_asset_id"]:
        emit_log(f"⚠️ [{trigger_acc['username']}] reached {current_diamonds} 💎 but sweep was skipped because no receiver target is locked!")
        return
    if STATE["is_siphoning_interactively"]: return

    STATE["is_siphoning_interactively"] = True
    old_status = STATE["status"]
    STATE["status"] = "GLOBAL AUTOPILOT SWEEP"
    
    locked_user = STATE["receiver_username"]
    locked_asset = STATE["receiver_asset_id"]

    emit_log(f"🚨 GLOBAL SWEEP TRIGGERED: [{trigger_acc['username']}] hit {current_diamonds} 💎!")
    emit_log("⏸️ Pausing farming pipeline threads. Scanning all alternative wallets...")

    try:
        receiver_acc = next((a for a in STATE["accounts"] if a["username"] == locked_user), None)
        
        for acc in STATE["accounts"]:
            if acc["username"] == locked_user: continue
            u, p = acc["username"], acc["password"]
            
            sess = get_auth_session(u, p)
            if not sess: continue
            ud = fetch_user_data(sess)
            if not ud: continue
            
            balance = ud["diamonds"]
            acc["diamonds"] = balance
            
            if balance >= 5:
                dynamic_price = balance  
                emit_log(f"🔮 [Sweep] Found {balance} 💎 on Alt [{u}]. Executing 100% drain payload...")
                
                if receiver_acc and receiver_acc.get("password"):
                    recv_sess = get_auth_session(receiver_acc["username"], receiver_acc["password"])
                else:
                    recv_sess = get_auth_session(locked_user, p)

                if not recv_sess: recv_sess = get_auth_session(u, p)
                if not recv_sess:
                    emit_log(f"❌ Skipped [{u}]: Failed to verify receiver network tokens.")
                    continue

                list_payload = {"action": "list", "creatureId": locked_asset, "price": dynamic_price, "priceType": "diamonds"}
                list_req = recv_sess.post(ENDPOINTS["trade"], json=list_payload, timeout=10)
                
                if list_req.status_code == 200:
                    emit_log(f"Asset listed for full balance of {dynamic_price} 💎. Executing transaction from Alt...")
                    time.sleep(1.2)
                    
                    buy_payload = {"action": "buy", "creatureId": locked_asset}
                    buy_req = sess.post(ENDPOINTS["trade"], json=buy_payload, timeout=10)
                    
                    if buy_req.status_code == 200:
                        time.sleep(3.2)
                        emit_log(f"Gifting tracking asset back to [{locked_user}]...")
                        gift_payload = {"action": "gift", "creatureId": locked_asset, "toUsername": locked_user}
                        sess.post(ENDPOINTS["trade"], json=gift_payload, timeout=10)
                        
                        acc["diamonds"] = 0
                        emit_log(f"🎉 Sweep Success! Extracted all {dynamic_price} 💎 from [{u}]. Wallet cleared out.")
                    else: emit_log(f"❌ Buy transaction rejected for Alt [{u}]. Response code: {buy_req.status_code}")
                else: emit_log(f"❌ Failed to list trade vehicle from receiver main profile. Response code: {list_req.status_code}")
            else:
                emit_log(f"ℹ️ Skipped [{u}]: Balance ({balance} 💎) is under the 5 💎 minimum floor threshold.")
                    
    except Exception as e:
        emit_log(f"❌ Internal exception occurred inside global automation sweep layer: {str(e)}")

    emit_log("▶️ Global autopilot sweep complete. Resuming farming loop pipelines smoothly...")
    STATE["status"] = old_status
    STATE["is_siphoning_interactively"] = False

def process_account_farm(acc, batch):
    if STATE["stop_farming_process"]: return
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
                                emit_log(f"[{acc['username']}] Redeem successful! Wallet: {ud['diamonds']} 💎")
                            except Exception: break
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
                        except Exception: break
                    
                    acc["diamonds"] = ud["diamonds"]
                    acc["points"] = ud["infinityRunPoints"]
                    emit_log(f"Sync complete for [{u}]: {ud['diamonds']} 💎 | {ud['infinityRunPoints']} Pts")
            else: emit_log(f"Unable to authenticate [{u}] during stat refresh layout sync.")
            updated_list.append(acc)
        
        STATE["accounts"] = updated_list
        emit_log("✅ All local storage balances checked and synced successfully.")

    GLOBAL_EXECUTOR.submit(refresh_worker)
    return jsonify({"success": True})

# --- Feature Modification: External Main Account Siphon Pipeline ---
@app.route('/execute-external-siphon', methods=['POST'])
def execute_external_siphon():
    req_data = request.get_json(force=True) or {}
    ext_user = req_data.get("external_username", "").strip()
    ext_pass = req_data.get("external_password", "").strip()
    target_alt_user = req_data.get("target_alt_username", "").strip()
    passed_accounts = req_data.get("accounts", [])

    if not ext_user or not ext_pass or not target_alt_user:
        return jsonify({"error": "Missing validation tracking contexts"}), 400

    alt_acc = next((a for a in passed_accounts if a["username"] == target_alt_user), None)
    if not alt_acc:
        return jsonify({"error": "Selected alt profile missing from cache"}), 400

    def external_worker():
        emit_log(f"🔮 Spawning External Main Handshake Session for [{ext_user}]...")
        ext_sess = get_auth_session(ext_user, ext_pass)
        if not ext_sess:
            emit_log("❌ Failed to validate external account credentials.")
            return

        alt_sess = get_auth_session(alt_acc["username"], alt_acc["password"])
        if not alt_sess:
            emit_log(f"❌ Failed to authenticate chosen alt profile [{alt_acc['username']}]")
            return

        alt_ud = fetch_user_data(alt_sess)
        if not alt_ud or alt_ud["diamonds"] <= 0:
            emit_log(f"❌ Target Alt [{alt_acc['username']}] has no diamonds available to buy listings.")
            return

        siphon_total_price = alt_ud["diamonds"]
        emit_log(f"ℹ️ Locked target balance: {siphon_total_price} 💎 inside wallet of [{alt_acc['username']}]")

        try:
            # Step 1: Request active market index metrics to pull a generic $1 item vehicle
            emit_log("Querying open public market endpoints for trade vehicle asset allocation...")
            market_res = ext_sess.get(ENDPOINTS["market"], timeout=10)
            if market_res.status_code != 200:
                emit_log("❌ Public market registry indexing query failure.")
                return

            market_creatures = market_res.json().get("creatures", [])
            # Filter entries matching strict structural rule: tradePrice == 1 and type == diamonds
            eligible = [c for c in market_creatures if c.get("tradePrice") == 1 and c.get("tradePriceType") == "diamonds"]

            if not eligible:
                emit_log("❌ No active public market items found listed at 1 Diamond baseline constraint.")
                return

            selected_vehicle = random.choice(eligible)
            vehicle_id = selected_vehicle["id"]
            emit_log(f"🎯 Vehicle acquired. Selected creature asset ID: [{vehicle_id}] from market index.")

            # Step 2: External main purchases the 1 diamond listing vehicle item
            emit_log(f"Buying item [{vehicle_id}] from market into External main wallet...")
            buy_req = ext_sess.post(ENDPOINTS["trade"], json={"action": "buy", "creatureId": vehicle_id}, timeout=10)
            if buy_req.status_code != 200:
                emit_log("❌ External buy configuration handshake failed. Check external diamond balances.")
                return

            time.sleep(2.0)

            # Step 3: External main puts it back on the market for the alt's entire balance size
            emit_log(f"Relisting asset [{vehicle_id}] from External main for total wallet payload value: {siphon_total_price} 💎...")
            list_req = ext_sess.post(ENDPOINTS["trade"], json={
                "action": "list",
                "creatureId": vehicle_id,
                "price": siphon_total_price,
                "priceType": "diamonds"
            }, timeout=10)
            if list_req.status_code != 200:
                emit_log("❌ Failed to list intermediate asset vehicle on public exchange ledger.")
                return

            time.sleep(2.0)

            # Step 4: Alternative account completes the buy payload to clear funds
            emit_log(f"Executing transfer buy handshake from Alt account [{alt_acc['username']}]...")
            alt_buy_req = alt_sess.post(ENDPOINTS["trade"], json={"action": "buy", "creatureId": vehicle_id}, timeout=10)
            if alt_buy_req.status_code != 200:
                emit_log("❌ Alt buyout routine rejected or transaction intercepted.")
                return

            time.sleep(3.2)

            # Step 5: Alt gifts the creature vehicle item right back to the external account cleanly
            emit_log(f"Returning asset item [{vehicle_id}] back to External Main account layout...")
            gift_req = alt_sess.post(ENDPOINTS["trade"], json={
                "action": "gift",
                "creatureId": vehicle_id,
                "toUsername": ext_user
            }, timeout=10)

            alt_acc["diamonds"] = 0
            emit_log(f"🎉 External Siphon Success! Moved {siphon_total_price} 💎 to [{ext_user}] and returned vehicle asset cleanly.")

        except Exception as e:
            emit_log(f"❌ Internal anomaly running external target siphon matrix sequence: {str(e)}")

    GLOBAL_EXECUTOR.submit(external_worker)
    return jsonify({"success": True})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
