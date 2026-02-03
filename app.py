import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import sqlite3
import datetime
import math

# --- Configuration ---
st.set_page_config(layout="wide", page_title="BCP Market Pro")

# --- Database Setup (v4) ---
def init_db():
    conn = sqlite3.connect('bcp_market_v4.db') 
    c = conn.cursor()
    
    # Users: Added 'last_claim' for Daily Bonus
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (username TEXT PRIMARY KEY, password TEXT, cash REAL, last_claim TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS markets 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT, status TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS outcomes 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, market_id INTEGER, 
                 label TEXT, price REAL)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS portfolio 
                 (username TEXT, outcome_id INTEGER, quantity INTEGER, avg_cost REAL, 
                 PRIMARY KEY (username, outcome_id))''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS price_history 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, outcome_id INTEGER, price REAL, timestamp TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS transactions 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, 
                 description TEXT, timestamp TEXT)''')
                 
    # NEW: Comments Table
    c.execute('''CREATE TABLE IF NOT EXISTS comments 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, market_id INTEGER, 
                 username TEXT, text TEXT, timestamp TEXT)''')

    # Admin Account
    c.execute("INSERT OR IGNORE INTO users (username, password, cash) VALUES (?, ?, ?)", ('admin', 'admin123', 1000000.0))
    conn.commit()
    conn.close()

init_db()

# --- Backend Logic ---

def create_user(username, password):
    conn = sqlite3.connect('bcp_market_v4.db')
    c = conn.cursor()
    try:
        # Start with $500
        c.execute("INSERT INTO users (username, password, cash) VALUES (?, ?, ?)", (username, password, 500.0))
        conn.commit()
        conn.close()
        return True
    except:
        conn.close()
        return False

def login_user(username, password):
    conn = sqlite3.connect('bcp_market_v4.db')
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username=? AND password=?", (username, password))
    user = c.fetchone()
    conn.close()
    return user

def claim_daily(username):
    conn = sqlite3.connect('bcp_market_v4.db')
    c = conn.cursor()
    
    # Check last claim
    c.execute("SELECT last_claim, cash FROM users WHERE username=?", (username,))
    res = c.fetchone()
    last_date = res[0]
    
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    
    if last_date == today:
        conn.close()
        return False, "Already claimed today!"
    
    # Give $50
    c.execute("UPDATE users SET cash = cash + 50, last_claim = ? WHERE username=?", (today, username))
    conn.commit()
    conn.close()
    return True, "claimed"

def post_comment(market_id, username, text):
    conn = sqlite3.connect('bcp_market_v4.db')
    c = conn.cursor()
    ts = datetime.datetime.now().strftime("%m-%d %H:%M")
    c.execute("INSERT INTO comments (market_id, username, text, timestamp) VALUES (?, ?, ?, ?)", 
              (market_id, username, text, ts))
    conn.commit()
    conn.close()

def get_leaderboard():
    conn = sqlite3.connect('bcp_market_v4.db')
    users = pd.read_sql("SELECT username, cash FROM users", conn)
    portfolio = pd.read_sql("SELECT username, outcome_id, quantity FROM portfolio", conn)
    outcomes = pd.read_sql("SELECT id, price FROM outcomes", conn)
    conn.close()
    
    net_worths = []
    for index, user in users.iterrows():
        if user['username'] == 'admin': continue
        total = user['cash']
        user_holdings = portfolio[portfolio['username'] == user['username']]
        for i, holding in user_holdings.iterrows():
            o_price = outcomes.loc[outcomes['id'] == holding['outcome_id'], 'price'].values
            if len(o_price) > 0:
                total += holding['quantity'] * o_price[0]
        net_worths.append({'Player': user['username'], 'Net Worth': total})
    
    df = pd.DataFrame(net_worths)
    if not df.empty:
        df = df.sort_values(by='Net Worth', ascending=False).reset_index(drop=True)
        df.index += 1
    return df

def create_market(question, options_list, prices_list=None):
    conn = sqlite3.connect('bcp_market_v4.db')
    c = conn.cursor()
    c.execute("INSERT INTO markets (question, status) VALUES (?, ?)", (question, 'OPEN'))
    m_id = c.lastrowid
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if not prices_list:
        default_prob = round(1.0 / len(options_list), 2)
        prices_list = [default_prob] * len(options_list)
    
    for opt, price in zip(options_list, prices_list):
        c.execute("INSERT INTO outcomes (market_id, label, price) VALUES (?, ?, ?)", (m_id, opt.strip(), price))
        o_id = c.lastrowid
        c.execute("INSERT INTO price_history (outcome_id, price, timestamp) VALUES (?, ?, ?)", (o_id, price, timestamp))
    conn.commit()
    conn.close()

def log_price(outcome_id, new_price):
    conn = sqlite3.connect('bcp_market_v4.db')
    c = conn.cursor()
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO price_history (outcome_id, price, timestamp) VALUES (?, ?, ?)", (outcome_id, new_price, timestamp))
    conn.commit()
    conn.close()

def trade(username, outcome_id, action, quantity, current_price):
    conn = sqlite3.connect('bcp_market_v4.db')
    c = conn.cursor()
    LIQUIDITY_K = 150.0 
    
    c.execute("SELECT cash FROM users WHERE username=?", (username,))
    res = c.fetchone()
    if not res: return False, "User error"
    cash = res[0]
    
    c.execute("SELECT quantity, avg_cost FROM portfolio WHERE username=? AND outcome_id=?", (username, outcome_id))
    holding = c.fetchone()
    current_qty = holding[0] if holding else 0

    safe_price = max(0.01, min(0.99, current_price))
    current_score = math.log(safe_price / (1 - safe_price))
    impact = quantity / LIQUIDITY_K
    
    if action == "BUY": new_score = current_score + impact
    else: new_score = current_score - impact
        
    new_price = 1 / (1 + math.exp(-new_score))
    new_price = round(new_price, 3)
    
    if action == "BUY":
        avg_price = (current_price + new_price) / 2
        total_cost = quantity * avg_price
        if cash < total_cost: return False, f"Need ${total_cost:.2f}"
        c.execute("UPDATE users SET cash = cash - ? WHERE username=?", (total_cost, username))
        if holding:
            new_qty = current_qty + quantity
            new_avg = ((holding[0] * holding[1]) + total_cost) / new_qty
            c.execute("UPDATE portfolio SET quantity=?, avg_cost=? WHERE username=? AND outcome_id=?", (new_qty, new_avg, username, outcome_id))
        else:
            c.execute("INSERT INTO portfolio VALUES (?, ?, ?, ?)", (username, outcome_id, quantity, avg_price))
    elif action == "SELL":
        if current_qty < quantity: return False, "Not enough shares!"
        avg_price = (current_price + new_price) / 2
        revenue = quantity * avg_price
        c.execute("UPDATE users SET cash = cash + ? WHERE username=?", (revenue, username))
        new_qty = current_qty - quantity
        if new_qty == 0:
            c.execute("DELETE FROM portfolio WHERE username=? AND outcome_id=?", (username, outcome_id))
        else:
            c.execute("UPDATE portfolio SET quantity=? WHERE username=? AND outcome_id=?", (new_qty, username, outcome_id))

    c.execute("UPDATE outcomes SET price=? WHERE id=?", (new_price, outcome_id))
    
    # Log
    o_data = c.execute("SELECT label, market_id FROM outcomes WHERE id=?", (outcome_id,)).fetchone()
    desc = f"{action} {quantity} shares of '{o_data[0]}'"
    c.execute("INSERT INTO transactions (username, description, timestamp) VALUES (?, ?, ?)", 
              (username, desc, datetime.datetime.now().strftime("%H:%M:%S")))

    conn.commit()
    conn.close()
    log_price(outcome_id, new_price)
    return True, "Success"

def resolve_market(market_id, winning_outcome_id):
    conn = sqlite3.connect('bcp_market_v4.db')
    c = conn.cursor()
    c.execute("UPDATE markets SET status='RESOLVED' WHERE id=?", (market_id,))
    outcomes = pd.read_sql("SELECT id FROM outcomes WHERE market_id=?", conn, params=(market_id,))
    for index, row in outcomes.iterrows():
        o_id = row['id']
        payout = 1.0 if (str(o_id) == str(winning_outcome_id)) else 0.0
        c.execute("UPDATE outcomes SET price=? WHERE id=?", (payout, o_id))
        holders = c.execute("SELECT username, quantity FROM portfolio WHERE outcome_id=?", (o_id,)).fetchall()
        for user, qty in holders:
            cash_val = qty * payout
            if cash_val > 0:
                c.execute("UPDATE users SET cash = cash + ? WHERE username=?", (cash_val, user))
        c.execute("DELETE FROM portfolio WHERE outcome_id=?", (o_id,))
    conn.commit()
    conn.close()

# --- UI LAYER ---

st.sidebar.title("🏆 Richest List")
lb = get_leaderboard()
if not lb.empty:
    st.sidebar.dataframe(lb.style.format({"Net Worth": "${:,.2f}"}), use_container_width=True, hide_index=False)

st.sidebar.divider()
st.sidebar.title("🔐 Account")

if 'logged_in_user' not in st.session_state:
    st.session_state.logged_in_user = None

if st.session_state.logged_in_user is None:
    t1, t2 = st.sidebar.tabs(["Login", "Register"])
    with t1:
        lu = st.text_input("Username", key="lu")
        lp = st.text_input("Password", type="password", key="lp")
        if st.button("Login"):
            user = login_user(lu, lp)
            if user:
                st.session_state.logged_in_user = user
                st.rerun()
            else: st.error("Invalid.")
    with t2:
        ru = st.text_input("New Username", key="ru")
        rp = st.text_input("New Password", type="password", key="rp")
        if st.button("Register"):
            if create_user(ru, rp): st.success("Made! Login now.")
            else: st.error("Taken.")
else:
    user = st.session_state.logged_in_user[0]
    st.sidebar.write(f"Logged in: **{user}**")
    
    # --- DAILY CLAIM BUTTON ---
    if st.sidebar.button("💰 Claim Daily $50"):
        ok, msg = claim_daily(user)
        if ok: st.success("Cash added!")
        else: st.error(msg)
    
    if st.sidebar.button("Logout"):
        st.session_state.logged_in_user = None
        st.rerun()

if not st.session_state.logged_in_user:
    st.title("BCP Prediction Market")
    st.info("Login to play.")
    st.stop()

user = st.session_state.logged_in_user[0]
user_info = login_user(user, st.session_state.logged_in_user[1])
is_admin = (user == "admin")

# --- ADMIN VIEW ---
if is_admin:
    st.title("🛠️ Admin Panel")
    with st.expander("Create Market", expanded=True):
        q = st.text_input("Question")
        c1, c2 = st.columns(2)
        opts_str = c1.text_area("Options (comma sep)", placeholder="Yes, No")
        prices_str = c2.text_area("Prices (comma sep)", placeholder="0.5, 0.5")
        if st.button("Launch"):
            if q and opts_str:
                opt_list = opts_str.split(',')
                price_list = [float(p) for p in prices_str.split(',')] if prices_str else None
                create_market(q, opt_list, price_list)
                st.success("Launched!")
                st.rerun()

    st.divider()
    conn = sqlite3.connect('bcp_market_v4.db')
    mkts = pd.read_sql("SELECT * FROM markets WHERE status='OPEN'", conn)
    for i, m in mkts.iterrows():
        st.markdown(f"#### {m['question']}")
        outcomes = pd.read_sql("SELECT * FROM outcomes WHERE market_id=?", conn, params=(m['id'],))
        cols = st.columns(len(outcomes))
        for idx, o in outcomes.iterrows():
            if cols[idx % len(cols)].button(f"Win: {o['label']}", key=f"win_{o['id']}"):
                resolve_market(m['id'], o['id'])
                st.success("Resolved!")
                st.rerun()
        st.divider()
    conn.close()

# --- PLAYER VIEW ---
else:
    # TICKER
    st.subheader("📢 Live Activity")
    conn = sqlite3.connect('bcp_market_v4.db')
    trades = pd.read_sql("SELECT * FROM transactions ORDER BY id DESC LIMIT 5", conn)
    if not trades.empty:
        for i, t in trades.iterrows():
            st.caption(f"🕒 {t['timestamp']} | **{t['username']}** {t['description']}")
    
    st.divider()
    st.title(f"Balance: ${user_info[2]:,.2f}")
    
    mkts = pd.read_sql("SELECT * FROM markets WHERE status='OPEN'", conn)
    
    for i, m in mkts.iterrows():
        st.markdown(f"## ❓ {m['question']}")
        outcomes = pd.read_sql("SELECT * FROM outcomes WHERE market_id=?", conn, params=(m['id'],))
        
        # GRAPH
        fig = go.Figure()
        for idx, o in outcomes.iterrows():
            hist = pd.read_sql("SELECT * FROM price_history WHERE outcome_id=?", conn, params=(o['id'],))
            if not hist.empty:
                fig.add_trace(go.Scatter(x=pd.to_datetime(hist['timestamp']), y=hist['price'], mode='lines', name=o['label']))
        fig.update_layout(height=300, margin=dict(l=0,r=0,t=0,b=0), yaxis=dict(range=[0,1], title="Prob"), template="plotly_dark")
        st.plotly_chart(fig, use_container_width=True)
        
        # TRADING CARDS
        o_cols = st.columns(len(outcomes))
        for idx, o in outcomes.iterrows():
            with o_cols[idx % len(o_cols)]:
                with st.container(border=True):
                    st.markdown(f"### {o['label']}")
                    st.metric("Price", f"${o['price']:.2f}")
                    hold = conn.execute("SELECT quantity FROM portfolio WHERE username=? AND outcome_id=?", (user, o['id'])).fetchone()
                    my_qty = hold[0] if hold else 0
                    st.write(f"Owned: **{my_qty}**")
                    b, s = st.tabs(["Buy", "Sell"])
                    with b:
                        qb = st.number_input("Qty", 1, key=f"qb_{o['id']}")
                        if st.button("Buy", key=f"bb_{o['id']}"):
                            ok, msg = trade(user, o['id'], 'BUY', qb, o['price'])
                            if ok: st.rerun()
                            else: st.error(msg)
                    with s:
                        qs = st.number_input("Qty", 1, key=f"qs_{o['id']}")
                        if st.button("Sell", key=f"ss_{o['id']}"):
                            ok, msg = trade(user, o['id'], 'SELL', qs, o['price'])
                            if ok: st.rerun()
                            else: st.error(msg)
        
        # COMMENTS SECTION
        st.write("💬 **Chirp Box**")
        comments = pd.read_sql("SELECT * FROM comments WHERE market_id=? ORDER BY id DESC LIMIT 5", conn, params=(m['id'],))
        for x, comm in comments.iterrows():
            st.caption(f"**{comm['username']}**: {comm['text']}")
            
        c_txt = st.text_input("Say something...", key=f"comm_{m['id']}")
        if st.button("Post", key=f"p_{m['id']}"):
            post_comment(m['id'], user, c_txt)
            st.rerun()
            
        st.divider()
    conn.close()