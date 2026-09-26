"""
Huawei N5368X Router Tool
Combines: veryraregaming band tool + pearlxcore router tool + gazzasat signal features
Auth: veryraregaming pattern (base64+sha256) with huawei-lte-api fallback
Your specific feature: Cell Scanner — scan visible cells by EARFCN/PCI, click to lock
"""

import sys, os, json, threading, time, hashlib, base64, socket, subprocess, platform, re
from datetime import datetime
import xml.etree.ElementTree as ET
import requests
from urllib.parse import urljoin
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

# ── Optional deps (graceful fallback) ──────────────────────────
try:
    from huawei_lte_api.Client import Client
    from huawei_lte_api.AuthorizedConnection import AuthorizedConnection
    HUAWEI_API = True
except ImportError:
    HUAWEI_API = False

try:
    import speedtest as speedtest_lib
    SPEEDTEST = True
except ImportError:
    SPEEDTEST = False

# ── Speed-test providers (fast.com primary, OpenSpeedTest fallback) ─────────
FAST_TOKEN   = 'YXNkZmFzZGxmbnNkYWZoYXNkZmhrYWxm'   # public token embedded in fast.com's client
OST_SERVERS  = (('https://openspeedtest.com', '/downloading', '/upload'),)
# antenna-sweep speed test: tune these (seconds per combo) —
#   ANT_DL_SEC/ANT_UL_SEC = 0 disables that phase
ANT_DL_SEC   = 6
ANT_UL_SEC   = 3
# antenna-sweep phasing: right after an apply the modem re-tunes and readings
# swing before it locks — so we IGNORE samples before ANT_SOAK_S and only
# accept a value after ANT_STABLE_N consecutive in-band reads. The stability
# gate uses CQI + DL MCS (see below), NOT device/signal 'sinr' which this
# firmware reports bogus-low (2-7 dB while negotiated MCS reaches 256QAM).
ANT_SOAK_S       = 4        # seconds of re-tune transient to skip
ANT_STABLE_N     = 3        # consecutive in-band samples required
ANT_CQI_TOL      = 1        # CQI must sit within this (index) to count stable
ANT_MCS_TOL      = 3        # DL MCS must sit within this (index) to count stable
ANT_SETTLE_MAX_S = 20
ANT_SAMPLE_S     = 1.0
# Trusted per-combo metrics on this firmware — live-verified after a clean
# reboot: RSRP is frozen at -80/-81 dBm, device/signal 'sinr' is bogus,
# net/cell_info is always 100003. The truthful quality axis is CQI + the
# negotiated DL MCS (+ measured throughput). 'SINR≈' below is an estimate
# mapped from CQI so the sweep stays comparable to a phone's SNR reading.
CQI2SINR = {0:-4.0, 1:-3.0, 2:0.0, 3:1.5, 4:3.3, 5:5.5, 6:7.5, 7:10.0, 8:12.0,
            9:14.0, 10:16.0, 11:18.0, 12:19.5, 13:21.5, 14:22.8, 15:24.0}

try:
    import matplotlib
    matplotlib.use('TkAgg')
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure
    MATPLOTLIB = True
except ImportError:
    MATPLOTLIB = False

# ── Constants ──────────────────────────────────────────────────
CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'huawei_config.json')
APP_VERSION = "1.0.0"

BAND_HEX = {
    1:0x1, 3:0x4, 7:0x40, 8:0x80, 20:0x80000,
    28:0x8000000, 32:0x80000000, 38:0x40000000000,
    40:0x100000000000, 41:0x200000000000, 42:0x400000000000,
}
NR_BAND_HEX = {
    1:0x1, 3:0x4, 28:0x8000000, 41:0x10000000000,
    78:0x200000000000000000, 79:0x400000000000000000,
}
EARFCN_BAND = [
    (1,0,599),(2,600,1199),(3,1200,1949),(4,1950,2399),(5,2400,2649),
    (7,2750,3449),(8,3450,3799),(9,3800,4149),(20,6150,6449),
    (28,9210,9659),(32,9920,10359),(38,37750,38249),
    (40,38250,39649),(41,39650,41589),(42,41590,43589),(43,43590,45589),
    (66,66436,67335),
]
# Automatic per-band neighbour discovery. The modem only reports neighbours
# (nei_cellid) for the band it is currently camped on, so the always-on logger
# hops through every band, triggers a tower sweep, catches neighbours, restores.
NEI_SWEEP_BANDS    = sorted(BAND_HEX)      # B1,B3,B7,B8,B20,B28,B32,B38,B40,B41,B42
NEI_SWEEP_RECAMP   = 12.0                  # max seconds waiting for the modem to camp
NEI_SWEEP_WINDOW   = 7.0                   # poll seconds after the sweep starts
NEI_SWEEP_POLL     = 0.5                   # poll interval during the sweep window
MODE_LABELS = {
    '0':'No service','1':'GSM/2G','2':'GPRS','3':'EDGE','4':'UMTS/3G',
    '5':'HSDPA','6':'HSUPA','7':'HSPA+','8':'DC-HSPA+',
    '17':'4G/LTE','101':'4G+/LTE-CA','256':'5G NSA','257':'5G SA',
}

COLORS = {
    'bg':       '#0f1117',
    'surface':  '#1a1d27',
    'surface2': '#22263a',
    'border':   '#2d3148',
    'accent':   '#4f8ef7',
    'accent2':  '#6c63ff',
    'green':    '#3dd68c',
    'yellow':   '#f0b429',
    'red':      '#ef5350',
    'text':     '#e8eaf6',
    'muted':    '#7b82a8',
    'tab_sel':  '#4f8ef7',
}

# ── Helpers ─────────────────────────────────────────────────────
def safe_rsrp(v):
    try: return float(re.sub(r'[^\d\.\-]', '', str(v)))
    except: return -150

NR_EARFCN_BAND = [
    (1,422000,434000),(3,361000,376000),(5,167300,177900),(7,524000,534000),
    (8,185000,192000),(20,156000,160999),(28,151600,160599),(41,499200,537999),
    (38,514000,524000),(40,460000,480000),(78,620000,653333),
    (79,693334,733333),(77,620000,680000),
]

def nrearfcn_to_band(e):
    try: e = int(str(e).strip())
    except: return None
    for b,lo,hi in NR_EARFCN_BAND:
        if lo <= e <= hi: return b
    return None

def earfcn_to_band(e):
    try: e = int(str(e).strip())
    except: return None
    for b,lo,hi in EARFCN_BAND:
        if lo <= e <= hi: return b
    return None

def rsrp_class(v):
    try: v=float(re.sub(r'[^\d\.\-]','',str(v)))
    except: return 'muted'
    if v >= -80: return 'green'
    if v >= -100: return 'yellow'
    return 'red'

def rsrq_class(v):
    try: v=float(re.sub(r'[^\d\.\-]','',str(v)))
    except: return 'muted'
    if v >= -10: return 'green'
    if v >= -15: return 'yellow'
    return 'red'

def sinr_class(v):
    try: v=float(re.sub(r'[^\d\.\-]','',str(v)))
    except: return 'muted'
    if v >= 15: return 'green'
    if v >= 5:  return 'yellow'
    return 'red'

def xml_val(xml_str, tag):
    try:
        root = ET.fromstring(xml_str)
        el = root.find('.//' + tag)
        return el.text.strip() if el is not None and el.text else ''
    except: return ''

def load_config():
    try:
        with open(CONFIG_FILE) as f: return json.load(f)
    except: return {'ip':'192.168.8.1','password':'','remember':True}

def save_config(cfg):
    try:
        with open(CONFIG_FILE,'w') as f: json.dump(cfg, f, indent=2)
    except: pass

# ── Auth ────────────────────────────────────────────────────────
def encrypt_password(username, password, csrf_token):
    """veryraregaming pattern — confirmed working on N5368X newer firmware"""
    eu = base64.b64encode(username.encode()).decode()
    ep = base64.b64encode(password.encode()).decode()
    et = base64.b64encode(csrf_token.encode()).decode()
    combined = f"{eu}#{ep}#{et}"
    hashed = hashlib.sha256(combined.encode()).digest()
    return base64.b64encode(hashed).decode()

def encrypt_password_legacy(password):
    """Older firmware fallback"""
    h = hashlib.sha256(password.encode()).hexdigest()
    return base64.b64encode(h.encode()).decode()

# ── Router API ──────────────────────────────────────────────────
class RouterAPI:
    def __init__(self, ip, status_cb=None):
        self.ip = ip
        self.session = requests.Session()
        self.token = ''
        self.session_id = ''
        self.client = None
        self.use_lib = False
        self.status_cb = status_cb
        self._username = 'admin'
        self._password = ''
        self._relogin_lock = threading.Lock()
        self._token_pool = []  # Pool of CSRF tokens from auth response

    def base(self): return f'http://{self.ip}'

    def _headers(self):
        return {
            '__RequestVerificationToken': self.token,
            'X-Requested-With': 'XMLHttpRequest',
            '_ResponseSource': 'Broswer',
        }

    def _update_token(self, response):
        """Parse token or token pool from response headers.
        Auth response sends 32 tokens as a #-separated string.
        Each POST must use a fresh token from the pool.
        """
        combined = (response.headers.get('__RequestVerificationToken') or
                    response.headers.get('__requestverificationtoken') or '')
        if '#' in combined:
            # Full token pool — split and store
            pool = [t for t in combined.split('#') if t]
            self.token = pool[0]
            self._token_pool = pool[1:]
            return
        # Accumulate one/two tokens
        for h in ['__RequestVerificationTokenone','__requestverificationtokenone']:
            t = response.headers.get(h)
            if t and t not in self._token_pool:
                self._token_pool.append(t)
        for h in ['__RequestVerificationTokentwo','__requestverificationtokentwo']:
            t = response.headers.get(h)
            if t and t not in self._token_pool:
                self._token_pool.append(t)
        if combined and '#' not in combined:
            self.token = combined

    def _get_fresh_token(self):
        """Consume next token from pool, or fetch from /api/webserver/token."""
        if self._token_pool:
            try:
                self.token = self._token_pool.pop(0)
                return
            except IndexError:
                pass  # pool drained by another thread — fall through
        try:
            raw = self.session.get(
                self.base()+'/api/webserver/token',
                headers=self._headers(), timeout=5).text
            t = xml_val(raw, 'token') or xml_val(raw, 'Token')
            if t: self.token = t
        except: pass

    def _raw_post(self, path, body, timeout=10):
        """POST bypassing auto-relogin — used by SCRAM auth to avoid recursion."""
        h = self._headers()
        h['Content-Type'] = 'application/x-www-form-urlencoded; charset=UTF-8'
        r = self.session.post(self.base()+path, data=body, headers=h, timeout=timeout)
        self._update_token(r)
        return r.text

    def _silent_relogin(self):
        """Re-authenticate silently when session expires."""
        if not self._password: return False
        with self._relogin_lock:
            try:
                if callable(self.status_cb): self.status_cb('Session expired — reconnecting…')
                self._token_pool = []  # Clear stale pool
                r0 = self.session.get(self.base()+'/api/webserver/SesTokInfo', timeout=10)
                self.session_id = xml_val(r0.text, 'SesInfo')
                self.token      = xml_val(r0.text, 'TokInfo')
                self.session.cookies.set('SessionID', self.session_id, domain=self.ip, path='/')
                ok, msg = self._scram_login(self._username, self._password)
                if ok:
                    if callable(self.status_cb): self.status_cb('Reconnected')
                    return True
            except Exception as e:
                if callable(self.status_cb): self.status_cb(f'Reconnect failed: {e}')
            return False

    def get(self, path, timeout=10):
        r = self.session.get(self.base()+path, headers=self._headers(), timeout=timeout)
        self._update_token(r)
        if '125002' in r.text or '125003' in r.text:
            if self._silent_relogin():
                r = self.session.get(self.base()+path, headers=self._headers(), timeout=timeout)
                self._update_token(r)
        return r.text

    def post(self, path, body, timeout=10):
        # Always get a fresh token before POSTing
        self._get_fresh_token()
        h = self._headers()
        h['Content-Type'] = 'application/x-www-form-urlencoded; charset=UTF-8'
        r = self.session.post(self.base()+path, data=body, headers=h, timeout=timeout)
        self._update_token(r)
        if '125002' in r.text or '125003' in r.text:
            if self._silent_relogin():
                self._get_fresh_token()
                h2 = self._headers()
                h2['Content-Type'] = 'application/x-www-form-urlencoded; charset=UTF-8'
                r = self.session.post(self.base()+path, data=body, headers=h2, timeout=timeout)
                self._update_token(r)
        return r.text

    def keepalive(self):
        """Send heartbeat to keep session alive — router JS sends every 1s, we send every 3s."""
        try:
            self.get('/api/user/heartbeat', timeout=5)
        except: pass

    def _scram_login(self, username, password, loginflag=None):
        """SCRAM authentication — exact port of CryptoJS.SCRAM() flow in index.js:
        1. POST challenge_login with username + firstnonce
        2. Router returns salt, iterations, servernonce
        3. Compute clientProof via SCRAM-SHA-256
        4. POST authentication_login with clientproof + finalnonce

        loginflag='2' reproduces the developer-mode login (WebUI developer page's
        Login(..., flag=true)) — the server responds to it by re-enabling
        user/second_login (see dev_login())."""
        import hmac, hashlib, os, struct

        def H(data):
            return hashlib.sha256(data).digest()

        def HMAC(key, msg):
            return hmac.new(key, msg, hashlib.sha256).digest()

        def Hi(password, salt, iterations):
            """PBKDF2 with SHA-256"""
            import hashlib
            return hashlib.pbkdf2_hmac('sha256', password, salt, iterations)

        def XOR(a, b):
            return bytes(x ^ y for x, y in zip(a, b))

        # Step 1: generate client nonce (hex string like the JS does)
        first_nonce = os.urandom(32).hex()  # 32 bytes = 64 hex chars, matching CryptoJS keySize:8

        body1 = (f'<?xml version="1.0" encoding="UTF-8"?>'
                 f'<request>'
                 f'<username>{username}</username>'
                 f'<firstnonce>{first_nonce}</firstnonce>'
                 f'<mode>1</mode>'
                 f'</request>')
        resp1 = self._raw_post('/api/user/challenge_login', body1)

        if '<error>' in resp1:
            code = xml_val(resp1, 'code')
            return False, f'Challenge failed: error {code}'

        salt_hex   = xml_val(resp1, 'salt')
        iterations = int(xml_val(resp1, 'iterations') or '1000')
        servernonce= xml_val(resp1, 'servernonce')

        if not salt_hex or not servernonce:
            return False, f'Invalid challenge response: {resp1[:200]}'

        # Step 2: compute SCRAM proof
        salt       = bytes.fromhex(salt_hex)
        auth_msg   = f'{first_nonce},{servernonce},{servernonce}'

        # SaltedPassword = Hi(password, salt, iterations)
        salted_pw  = Hi(password.encode(), salt, iterations)

        # CryptoJS HmacSHA256(message, key) is REVERSED vs standard HMAC
        # ClientKey = HMAC(key="Client Key", msg=SaltedPassword)
        client_key = HMAC(b'Client Key', salted_pw)

        # StoredKey = H(ClientKey)
        stored_key = H(client_key)

        # ClientSignature = HMAC(key=StoredKey, msg=AuthMessage)
        client_sig = HMAC(auth_msg.encode(), stored_key)  # CryptoJS HmacSHA256(storedKey, authMsg) = HMAC(key=authMsg, msg=storedKey)

        # ClientProof = ClientKey XOR ClientSignature
        client_proof = XOR(client_key, client_sig).hex()

        body2 = (f'<?xml version="1.0" encoding="UTF-8"?>'
                 f'<request>'
                 f'<clientproof>{client_proof}</clientproof>'
                 f'<finalnonce>{servernonce}</finalnonce>')
        if loginflag:
            body2 += f'<loginflag>{loginflag}</loginflag>'
        body2 += '</request>'
        resp2 = self._raw_post('/api/user/authentication_login', body2)

        if '<error>' in resp2:
            code = xml_val(resp2, 'code')
            if code in ('108001','108002','108003','108006','108007'):
                return False, f'Wrong password (SCRAM error {code})'
            return False, f'Auth failed: error {code}'

        return True, 'Connected (SCRAM)'

    def _rsa_encrypt(self, password, rsa_type='1'):
        """Exact Python port of EMUI.LoginStateController.doRSAEncrypt:
        1. base64encode(password)
        2. split into 214-char chunks (OAEP) or 245-char chunks (PKCS1v1.5)
        3. encrypt each chunk, retry if output hex length != n hex length
        4. concatenate hex results
        """
        try:
            from Crypto.PublicKey.RSA import construct
            from Crypto.Cipher import PKCS1_OAEP, PKCS1_v1_5
            import binascii

            key_xml = self.get('/api/webserver/publickey')
            rsan = xml_val(key_xml, 'encpubkeyn')
            rsae = xml_val(key_xml, 'encpubkeye')

            if not rsan or not rsae:
                return None, f'RSA public key XML tags not found. Raw: {key_xml[:120]}'

            n      = int(rsan, 16)
            e      = int(rsae, 16)
            pubkey = construct((n, e))
            n_len  = len(rsan)  # expected hex output length per block

            # Step 1: base64 encode the password (as the JS does)
            enc_str = base64.b64encode(password.encode()).decode()

            # Step 2: chunk size matches JS exactly
            chunk_size = 214 if rsa_type == '1' else 245

            # Step 3+4: encrypt each chunk, retry if hex output length != n_len
            if rsa_type == '1':
                cipher = PKCS1_OAEP.new(pubkey)
            else:
                cipher = PKCS1_v1_5.new(pubkey)

            result = ''
            i = 0
            num_chunks = len(enc_str) / chunk_size
            import math
            total_chunks = math.ceil(num_chunks) if num_chunks > 0 else 1

            while i < total_chunks:
                chunk = enc_str[i * chunk_size:(i + 1) * chunk_size]
                if not chunk:
                    break
                encrypted = cipher.encrypt(chunk.encode())
                hex_out   = binascii.hexlify(encrypted).decode()
                # Retry if output length doesn't match (OAEP is non-deterministic)
                if len(hex_out) != n_len:
                    tries = getattr(self, '_rsa_tries', 0) + 1
                    self._rsa_tries = tries
                    if tries > 10:
                        self._rsa_tries = 0
                        return None, 'RSA encryption length mismatch after retries'
                    continue
                self._rsa_tries = 0
                result += hex_out
                i += 1

            return result, None

        except ImportError:
            return None, 'pycryptodome not installed — run: pip install pycryptodome'
        except Exception as ex:
            return None, f'RSA error: {ex}'

    def _encode_password(self, username, password, pw_type, rsa_type):
        """Encode password matching EMUI.LoginStateController.doRSAEncrypt exactly.
        The router always uses RSA when rsapadingtype is set ('0' or '1').
        rsa_type '1' = OAEP (214 char chunks), '0' = PKCS1v1.5 (245 char chunks)
        Falls back to plain sha256hex only if RSA key fetch fails.
        """
        if rsa_type in ('0', '1'):
            enc, err = self._rsa_encrypt(password, rsa_type)
            if enc:
                return enc, None
            return None, f'RSA failed: {err}'
        # Fallback — no RSA declared
        if pw_type == '4':
            enc = hashlib.sha256(password.encode()).hexdigest()
        else:
            enc = base64.b64encode(password.encode()).decode()
        return enc, None

    def _wait_lockout(self):
        """Poll state-login until lockstatus clears. Updates UI via status_cb."""
        import time as _t
        wait_secs = 180
        while wait_secs > 0:
            _t.sleep(3)
            wait_secs -= 3
            try:
                sx  = self.get('/api/user/state-login')
                ls  = xml_val(sx, 'lockstatus')
                rw  = xml_val(sx, 'remainwaittime')
                if ls == '0': return
                try:
                    v = int(rw)
                    if v > 0: wait_secs = v
                except: pass
            except: pass
            if callable(self.status_cb):
                self.status_cb(f'Locked — retrying in ~{max(wait_secs,0)}s…')
        if callable(self.status_cb):
            self.status_cb('Lock cleared — connecting…')

    def login(self, username, password):
        import time as _t

        # Step 1: session + CSRF token
        try:
            tok_xml = self.session.get(self.base()+'/api/webserver/SesTokInfo', timeout=10).text
        except requests.exceptions.ConnectionError:
            return False, f'Cannot reach {self.ip} — check IP and WiFi'
        except Exception as e:
            return False, str(e)

        self.session_id = xml_val(tok_xml, 'SesInfo')
        self.token      = xml_val(tok_xml, 'TokInfo')
        if not self.token:
            return False, f'Cannot reach router at {self.ip}'

        # Step 2: check lockstatus
        pw_type = '4'; rsa_type = '1'
        try:
            state_xml   = self.get('/api/user/state-login')
            lock_status = xml_val(state_xml, 'lockstatus') or '0'
            remain_wait = xml_val(state_xml, 'remainwaittime') or '0'
            login_state = xml_val(state_xml, 'State')
            pw_type     = xml_val(state_xml, 'password_type') or '4'
            rsa_type    = xml_val(state_xml, 'rsapadingtype') or '1'
            if lock_status != '0':
                try: wait_secs = int(remain_wait)
                except: wait_secs = 180
                if callable(self.status_cb): self.status_cb(f'Router locked — waiting {wait_secs}s…')
                self._wait_lockout()
                tok_xml = self.session.get(self.base()+'/api/webserver/SesTokInfo', timeout=10).text
                self.session_id = xml_val(tok_xml, 'SesInfo')
                self.token      = xml_val(tok_xml, 'TokInfo')
            if login_state == '0':
                return True, 'Connected (reused existing session)'
        except Exception: pass

        # Step 3: SCRAM login (what the WebUI actually uses)
        if callable(self.status_cb): self.status_cb('Authenticating (SCRAM)…')
        ok, msg = self._scram_login(username, password)
        if ok:
            self._username = username
            self._password = password
            return True, msg
        if 'Wrong password' in msg or '108001' in msg or '108002' in msg or '108003' in msg:
            return False, msg

        # Step 4: fallback RSA (older firmware)
        if callable(self.status_cb): self.status_cb('Trying RSA fallback…')
        enc, enc_err = self._encode_password(username, password, pw_type, rsa_type)
        if enc_err: return False, f'SCRAM: {msg} | RSA: {enc_err}'
        try:
            body = (f'<?xml version="1.0" encoding="UTF-8"?>'
                    f'<request><Username>{username}</Username>'
                    f'<Password>{enc}</Password>'
                    f'<password_type>{pw_type}</password_type></request>')
            resp = self.post('/api/user/login', body)
            err  = xml_val(resp, 'code') or xml_val(resp, 'Code')
            if not err or 'OK' in resp: return True, f'Connected (RSA)'
            if err in ('108001','108002','108003','108006','108007'):
                return False, 'Wrong password — check the password field'
            return False, f'Login error {err}'
        except Exception as e:
            return False, str(e)

    def signal(self):
        if self.use_lib:
            try: return self.client.device.signal()
            except: self.use_lib = False
        try:
            xml = self.get('/api/device/signal')
            raw = {t: xml_val(xml, t) for t in ['rsrp','rsrq','sinr','rssi','band','pci','earfcn','cell_id','mode',
                                                 'nei_cellid','enodeb_id','tac','lac','plmn',
                                                 'nrearfcn','nrrsrp','nrsinr','nrrsrq','nrdlfreq','nrdlbandwidth',
                                                 'cqi0','cqi1','dl_mcs','ul_mcs']}
            # Strip unit suffixes and parse DL:/UL: prefixes
            for k in ('rsrp','rsrq','sinr','rssi','nrrsrp','nrsinr','nrrsrq'):
                if raw[k]: raw[k] = re.sub(r'[^\d\.\-]', '', raw[k])
            # Negotiated DL/UL MCS and CQI are the truthful quality axis on this
            # firmware (device/signal SINR reports bogus-low). Keep the raw codes.
            m = re.search(r'mcsDownCarrier1Code0:(\d+)', raw.get('dl_mcs',''))
            raw['mcs'] = m.group(1) if m else ''
            m = re.search(r'mcsUpCarrier1:(\d+)', raw.get('ul_mcs',''))
            raw['mcs_ul'] = m.group(1) if m else ''
            # EARFCN comes as "DL:400 UL:18400" — extract DL value
            if raw.get('earfcn'):
                m = re.search(r'DL:(\d+)', raw['earfcn'])
                if m: raw['earfcn'] = m.group(1)
                else: raw['earfcn'] = re.sub(r'[^\d]', '', raw['earfcn'].split()[0])
            if raw.get('nrearfcn'):
                m = re.search(r'DL:(\d+)', raw['nrearfcn'])
                if m: raw['nrearfcn'] = m.group(1)
                else: raw['nrearfcn'] = re.sub(r'[^\d]', '', raw['nrearfcn'].split()[0])
            return raw
        except: return {}

    def status(self):
        if self.use_lib:
            try: return self.client.monitoring.status()
            except: pass
        try:
            xml = self.get('/api/monitoring/status')
            keys = ['CurrentNetworkType','CurrentNetworkTypeEx','PrimaryDnsSuffix',
                    'SignalIcon','WifiConnectionStatus','SimStatus','WanIPAddress',
                    'SecondaryEarfcn','SecondaryPci','SecondaryRsrp']
            return {k: xml_val(xml, k) for k in keys}
        except: return {}

    def device_info(self):
        if self.use_lib:
            try: return self.client.device.information()
            except: pass
        try:
            xml = self.get('/api/device/information')
            return {t: xml_val(xml, t) for t in ['devicename','HardwareVersion','SoftwareVersion','firmwareversion','MacAddress1','uptime','Iccid']}
        except: return {}

    def current_plmn(self):
        if self.use_lib:
            try: return self.client.net.current_plmn()
            except: pass
        try:
            xml = self.get('/api/net/current-plmn')
            return {t: xml_val(xml, t) for t in ['State','FullName','ShortName','Numeric','Rat']}
        except: return {}

    def net_mode(self):
        if self.use_lib:
            try: return self.client.net.net_mode()
            except: pass
        try:
            xml = self.get('/api/net/net-mode')
            return {t: xml_val(xml, t) for t in ['NetworkMode','NetworkBand','LTEBand','NRBand']}
        except: return {}

    def check_session(self):
        """Proactively verify session is valid and relogin if needed. Call before critical POSTs."""
        try:
            raw = self.get('/api/user/state-login')
            state = xml_val(raw, 'State')
            if state == '0':  # Already logged in
                return True
            # Not logged in — relogin
            return self._silent_relogin()
        except Exception:
            return self._silent_relogin()

    def set_net_mode(self, mode, lte_band_hex='7FFFFFFFFFFFFFFF', nr_band_hex='7FFFFFFFFFFFFFFF', timeout=10):
        """POST to /api/net/net-mode.
        NetworkMode: 00=auto, 01=2G, 02=3G, 03=4G, 0302=4G pref 3G, 0301=4G pref 2G
        NetworkBand: hex bitmask for 2G/3G bands (3FFFFFFF = all)
        LTEBand:     hex bitmask for 4G bands
        NRBand:      hex bitmask for 5G NR bands
        timeout:     per-endpoint request timeout (raise when the modem is busy).
        """
        body = (f'<?xml version="1.0" encoding="UTF-8"?>'
                f'<request>'
                f'<NetworkMode>{mode}</NetworkMode>'
                f'<NetworkBand>3FFFFFFF</NetworkBand>'
                f'<LTEBand>{lte_band_hex}</LTEBand>'
                f'<NRBand>{nr_band_hex}</NRBand>'
                f'</request>')
        # Try multiple endpoints — some firmware uses /api/ntwk/net-mode
        for ep in ['/api/net/net-mode', '/api/ntwk/net-mode', '/api/net/network-mode']:
            resp = self.post(ep, body, timeout=timeout)
            code = xml_val(resp, 'code')
            if not code or code not in ('100003','100004'):
                return resp  # Got a real response (OK or real error)
        return resp

    def cell_info(self):
        if self.use_lib:
            try: return self.client.net.cell_info()
            except: pass
        try:
            return self.get('/api/net/cell-info')
        except: return ''

    def scan_cells(self):
        """Try all known neighbor/cell endpoints and return list of cells"""
        cells = []
        seen = set()

        def add(c):
            k = f"{c.get('pci','?')}_{c.get('earfcn','?')}"
            if k not in seen:
                seen.add(k)
                cells.append(c)

        # 1. Serving cell
        sig = self.signal()
        if sig.get('earfcn') or sig.get('pci'):
            earfcn = sig.get('earfcn','')
            pci    = sig.get('pci','')
            add({
                'type':'Serving', 'pci':pci, 'earfcn':earfcn,
                'band': earfcn_to_band(earfcn),
                'rsrp':sig.get('rsrp',''), 'rsrq':sig.get('rsrq',''),
                'sinr':sig.get('sinr',''), 'cell_id':sig.get('cell_id',''),
            })

        # 2. CA secondary from monitoring/status
        st = self.status()
        se, sp, sr = st.get('SecondaryEarfcn',''), st.get('SecondaryPci',''), st.get('SecondaryRsrp','')
        if se and sp:
            add({'type':'CA-SCC','pci':sp,'earfcn':se,'band':earfcn_to_band(se),'rsrp':sr,'rsrq':'','sinr':'','cell_id':''})

        # 3. Neighbor cells — try several endpoints
        for ep in ['/api/net/cell-info', '/api/net/neighborcell-info',
                   '/api/net/neighborcell', '/api/net/signal-advance',
                   '/api/device/signal-advance']:
            try:
                raw = self.get(ep, timeout=8)
                if not raw or '<error>' in raw: continue
                # Parse any <Cell> blocks or flat PCI/EARFCN lists
                blocks = re.findall(r'<[Cc]ell[^>]*>([\s\S]*?)<\/[Cc]ell>', raw)
                if blocks:
                    for b in blocks:
                        def gv(t): return re.search(rf'<{t}[^>]*>([^<]*)<\/{t}>', b, re.I)
                        pci    = (gv('pci') or gv('PhysCellId') or gv('physcellid') or gv('PCI'))
                        earfcn = (gv('earfcn') or gv('Earfcn') or gv('DlEarfcn'))
                        rsrp   = (gv('rsrp') or gv('Rsrp'))
                        rsrq   = (gv('rsrq') or gv('Rsrq'))
                        pci_v  = pci.group(1).strip()    if pci    else ''
                        ear_v  = earfcn.group(1).strip() if earfcn else ''
                        rp_v   = rsrp.group(1).strip()   if rsrp   else ''
                        rq_v   = rsrq.group(1).strip()   if rsrq   else ''
                        if pci_v or ear_v:
                            add({'type':'Neighbor','pci':pci_v,'earfcn':ear_v,
                                 'band':earfcn_to_band(ear_v),'rsrp':rp_v,'rsrq':rq_v,'sinr':'','cell_id':''})
                    break
                # Flat list
                pcis    = re.findall(r'<[Pp][Cc][Ii][^>]*>(\d+)<\/[Pp][Cc][Ii]>', raw)
                earfcns = re.findall(r'<[Ee]arfcn[^>]*>(\d+)<\/[Ee]arfcn>', raw)
                rsrps   = re.findall(r'<[Rr]srp[^>]*>([\-\d.]+)<\/[Rr]srp>', raw)
                if pcis:
                    for i,p in enumerate(pcis):
                        e = earfcns[i] if i < len(earfcns) else ''
                        r = rsrps[i]   if i < len(rsrps)   else ''
                        add({'type':'Neighbor','pci':p,'earfcn':e,'band':earfcn_to_band(e),'rsrp':r,'rsrq':'','sinr':'','cell_id':''})
                    break
            except: continue

        return cells

    def scan_cells_logged(self):
        """Scan serving cell + CA + standard endpoints + AT commands."""
        logs  = []
        cells = []
        seen  = set()

        def add(c):
            k = f"{c.get('pci','?')}_{c.get('earfcn','?')}"
            if k not in seen:
                seen.add(k); cells.append(c)

        # 1. Serving cell
        try:
            sig    = self.signal()
            earfcn = sig.get('earfcn','')
            pci    = sig.get('pci','')
            if earfcn or pci:
                b = earfcn_to_band(earfcn)
                add({'type':'Serving','pci':pci,'earfcn':earfcn,'band':b,
                     'rsrp':sig.get('rsrp',''),'rsrq':sig.get('rsrq',''),
                     'sinr':sig.get('sinr',''),'cell_id':sig.get('cell_id',''),
                     'enodeb':sig.get('enodeb_id',''),'tac':sig.get('tac','')})
                logs.append(('ok', f'Serving: PCI={pci} EARFCN={earfcn} B{b} RSRP={sig.get("rsrp","")} '
                                   f'CI={sig.get("cell_id","") or "-"} eNB={sig.get("enodeb_id","") or "-"} '
                                   f'TAC={sig.get("tac","") or "-"}'))
            else:
                logs.append(('warn', 'Serving cell: no data'))

            # 1b. Neighbour cells from nei_cellid field (same EARFCN as serving cell).
            #     This field is modem MEASUREMENT TELEMETRY: it populates during the
            #     modem's tower sweep (🔍 Network Search window), then clears. Burst-sample
            #     to catch it when a search is running alongside a scan.
            nei = sig.get('nei_cellid','')
            for _ in range(8):
                nei = sig.get('nei_cellid','')
                if nei: break
                time.sleep(0.6)
                try: sig = self.signal()
                except: break
            if not nei:
                logs.append(('api', 'nei_cellid empty — run 🔍 Network Search; neighbours populate during that sweep window'))
            if nei:
                nei_pcis = [m for m in re.findall(r'No\d+\s*:?\s*(\d+)', nei) if m and m != '0']
                if nei_pcis:
                    for np in nei_pcis:
                        if np and np != pci:
                            add({'type':'Neighbor','pci':np,'earfcn':earfcn,
                                 'band':earfcn_to_band(earfcn),'rsrp':'','rsrq':'','sinr':'','cell_id':''})
                    logs.append(('ok', f'Neighbour cells from nei_cellid: PCI {" ".join(nei_pcis)} on EARFCN={earfcn or "?"}'))
                else:
                    logs.append(('warn', f'nei_cellid present but no PCIs parsed: {nei[:60]}'))
        except Exception as e:
            logs.append(('error', f'signal() failed: {e}'))

        # 2. CA secondary
        try:
            st = self.status()
            se = st.get('SecondaryEarfcn','')
            sp = st.get('SecondaryPci','')
            sr = st.get('SecondaryRsrp','')
            if se and sp:
                add({'type':'CA-SCC','pci':sp,'earfcn':se,'band':earfcn_to_band(se),
                     'rsrp':sr,'rsrq':'','sinr':'','cell_id':''})
                logs.append(('ok', f'CA-SCC: PCI={sp} EARFCN={se}'))
            else:
                logs.append(('info','CA-SCC: none active'))
        except Exception as e:
            logs.append(('error', f'status() failed: {e}'))

        # 3. Read active band mask — decode which bands are configured
        try:
            nm      = self.net_mode()
            lte_hex = nm.get('LTEBand','')
            if lte_hex:
                lte_int      = int(lte_hex, 16)
                active_bands = [b for b,mask in BAND_HEX.items() if lte_int & mask]
                logs.append(('info', f'Active bands from mask {lte_hex}: B{active_bands}'))
        except Exception as e:
            logs.append(('warn', f'Could not read band mask: {e}'))

        # 4. Standard neighbour endpoints
        found_neighbors = False
        for ep in ['/api/net/cell-info','/api/net/neighborcell-info',
                   '/api/net/neighborcell','/api/net/signal-advance',
                   '/api/device/signal-advance']:
            try:
                raw  = self.get(ep, timeout=6)
                if not raw or '<error>' in raw:
                    logs.append(('warn', f'{ep}: error {xml_val(raw,"code") if raw else "empty"}')); continue
                if ep == '/api/net/cell-info':
                    ci = xml_val(raw,'cellinfo'); lac = xml_val(raw,'lac')
                    try: ci_d  = int(ci, 16)
                    except: ci_d  = '?'
                    try: lac_d = int(lac, 16)
                    except: lac_d = '?'
                    logs.append(('ok', f'cell-info: CellId={ci}({ci_d}) LAC/TAC={lac}({lac_d})'))
                    continue
                pcis    = re.findall(r'<[Pp][Cc][Ii][^>]*>(\d+)<\/[Pp][Cc][Ii]>', raw)
                earfcns = re.findall(r'<[Ee]arfcn[^>]*>(\d+)<\/[Ee]arfcn>', raw)
                rsrps   = re.findall(r'<[Rr]srp[^>]*>([\-\d.]+)<\/[Rr]srp>', raw)
                if pcis:
                    for i,p in enumerate(pcis):
                        e = earfcns[i] if i<len(earfcns) else ''
                        r = rsrps[i]   if i<len(rsrps)   else ''
                        add({'type':'Neighbor','pci':p,'earfcn':e,
                             'band':earfcn_to_band(e),'rsrp':r,'rsrq':'','sinr':'','cell_id':''})
                    logs.append(('ok', f'{ep}: {len(pcis)} neighbors found'))
                    found_neighbors = True; break
                else:
                    logs.append(('warn', f'{ep}: no cell data in response'))
            except Exception as e:
                logs.append(('warn', f'{ep}: {e}'))

        # 5. AT commands
        if not found_neighbors:
            for cmd, ep in [
                ('AT+QENG="neighbourcell"', '/api/net/at-command'),
                ('AT^MONSC',               '/api/net/at-command'),
                ('AT+QENG="servingcell"',  '/api/net/at-command'),
            ]:
                try:
                    body = f'<?xml version="1.0" encoding="UTF-8"?><request><atc>{cmd}</atc></request>'
                    raw  = self.post(ep, body, timeout=8)
                    if '<error>' not in raw and len(raw) > 60:
                        logs.append(('ok', f'AT {cmd}: {raw[:200]}'))
                        for m in re.finditer(r'LTE[",]+(\d+)[",]+(\d+)[",]+([\-\d]+)', raw):
                            e2,p2,rp = m.groups()
                            add({'type':'Neighbor','pci':p2,'earfcn':e2,
                                 'band':earfcn_to_band(e2),'rsrp':rp,'rsrq':'','sinr':'','cell_id':''})
                        found_neighbors = True; break
                    else:
                        logs.append(('warn', f'AT {cmd}: error {xml_val(raw,"code")}'))
                except Exception as e:
                    logs.append(('warn', f'AT {cmd}: {e}'))

        if not found_neighbors:
            logs.append(('info', 'No neighbours this sweep. Use 🔍 Network Search — the modem reports neighbours (nei_cellid) during its tower-scan window.'))

        return cells, logs

    def get_lock_state(self):
        """Read the firmware lock state — /api/net/lock-freq (the developer-mode
        Lock Band API). Returns {Mode, Enable, Band, Freq, CellId}."""
        try:
            raw = self.get('/api/net/lock-freq')
            return {t: xml_val(raw, t) for t in ['Mode','Enable','Band','Freq','CellId']}
        except Exception:
            return {}

    def _lock_freq(self, mode, enable, freq, band, cellid, timeout=40):
        body = (f'<?xml version="1.0" encoding="UTF-8"?><request>'
                f'<Mode>{mode}</Mode><Enable>{enable}</Enable><Freq>{freq}</Freq>'
                f'<Band>{band}</Band><CellId>{cellid}</CellId></request>')
        return self.post('/api/net/lock-freq', body, timeout=timeout)

    def reset_lte_bands(self, mask='7FFFFFFFFFFFFFFF', timeout=20):
        """Clear a band mask via /api/net/lte-band-info (kept current_lte_band)."""
        body = (f'<?xml version="1.0" encoding="UTF-8"?>'
                f'<request><current_lte_band>{mask}</current_lte_band></request>')
        return self.post('/api/net/lte-band-info', body, timeout=timeout)

    def lock_cell(self, pci, earfcn):
        """PCI+frequency lock via /api/net/lock-freq Enable=2 (the API the WebUI's
        developer-mode Lock Band page uses). The POST is slow — the modem re-searches
        so it can time out; we then verify the applied state."""
        band = earfcn_to_band(earfcn)
        if not band:
            return False, f'Cannot resolve the band for EARFCN {earfcn}'
        try:
            # A leftover lock-freq lock (Enable=1/2) makes the modem REJECT a new
            # band/cell change (100003) and keeps it pinned to the old band — clear
            # it first so the new lock can actually engage.
            try:
                self._lock_freq(0, 0, 0, 0, 0)
                time.sleep(0.5)
            except Exception:
                pass
            r = self._lock_freq(0, 2, earfcn, band, pci)
            code = xml_val(r, 'code')
            if code: return False, f'error {code}'
            try: self.reset_lte_bands('7FFFFFFFFFFFFFFF')
            except Exception: pass
            try:
                st = self.get_lock_state()
                if st.get('Enable') == '2' and st.get('CellId') == str(pci) \
                   and st.get('Freq') == str(earfcn):
                    return True, f'Locked → PCI {pci} / EARFCN {earfcn} (B{band})'
            except Exception:
                pass
            return True, f'Lock sent → PCI {pci} / EARFCN {earfcn} (B{band})'
        except Exception as e:
            try:
                st = self.get_lock_state()
                if st.get('Enable') == '2' and st.get('CellId') == str(pci) \
                   and st.get('Freq') == str(earfcn):
                    return True, f'Lock accepted → PCI {pci} / EARFCN {earfcn} (B{band})'
            except Exception:
                pass
            return False, f'Lock failed: {e}'

    def lock_frequency(self, earfcn):
        """Whole-frequency lock (any sector) via /api/net/lock-freq Enable=1."""
        band = earfcn_to_band(earfcn)
        if not band:
            return False, f'Cannot resolve the band for EARFCN {earfcn}'
        try:
            try:
                self._lock_freq(0, 0, 0, 0, 0)
                time.sleep(0.5)
            except Exception:
                pass
            r = self._lock_freq(0, 1, earfcn, band, 0)
            code = xml_val(r, 'code')
            if code: return False, f'error {code}'
            try: self.reset_lte_bands('7FFFFFFFFFFFFFFF')
            except Exception: pass
            return True, f'Locked → EARFCN {earfcn} (B{band}, any sector)'
        except Exception as e:
            try:
                st = self.get_lock_state()
                if st.get('Enable') == '1' and st.get('Freq') == str(earfcn):
                    return True, f'Lock accepted → EARFCN {earfcn} (B{band})'
            except Exception:
                pass
            return False, f'Lock failed: {e}'

    def unlock_cell(self):
        """Clear the freq/PCI lock and restore the LTE band mask."""
        try:
            try: self._lock_freq(0, 0, 0, 0, 0)
            except Exception: pass
            try: self.reset_lte_bands('7FFFFFFFFFFFFFFF')
            except Exception: pass
            return True, 'Cell/frequency lock removed'
        except Exception as e:
            return False, f'Unlock error: {e}'

    def antenna_config(self):
        """Read the antenna-tuning state (live-verified schema):
        SelectMode 1=fixed combo / 0=auto-scan, SelectCycle 1-720 min,
        CombIndex 1-10, SelectIndex = comma list of radiating elements."""
        try:
            x = self.get('/api/net/antenna-configuration', timeout=12)
            return {t: xml_val(x, t) for t in
                    ['SelectMode','SelectCycle','CombIndex','SelectIndex']}
        except Exception:
            return {}

    def antenna_select_result(self):
        """Result of an antenna auto-scan: Result 0=done (CombIndex/SelectIndex
        applied), 9=still scanning, 255=stopped, others=errors."""
        try:
            x = self.get('/api/net/antenna-select-result', timeout=12)
            return {t: xml_val(x, t) for t in ['Result','CombIndex','SelectIndex']}
        except Exception:
            return {}

    def antenna_apply(self, mode=None, cycle=None, index=None, action=0, timeout=15):
        """POST /api/net/antenna-configuration. action: 0=apply, 1=start auto
        scan, 2=stop scan. Missing fields inherit the current state."""
        cur = self.antenna_config() or {}
        SelMode  = str(mode  if mode  is not None else cur.get('SelectMode')  or '1')
        SelCycle = str(cycle if cycle is not None else cur.get('SelectCycle') or '72')
        CombInd  = str(index if index is not None else cur.get('CombIndex')   or '1')
        body = (f'<?xml version="1.0" encoding="UTF-8"?><request>'
                f'<SelectMode>{SelMode}</SelectMode><SelectCycle>{SelCycle}</SelectCycle>'
                f'<CombIndex>{CombInd}</CombIndex><ActionMode>{action}</ActionMode></request>')
        try:
            r = self.post('/api/net/antenna-configuration', body, timeout=timeout)
            return (not xml_val(r, 'code')), r
        except Exception as e:
            return False, str(e)

    def register_cell(self, plmn, rat):
        """Manual network registration — /api/net/register Mode 1. Re-searches and registers to the given PLMN/RAT."""
        body = (f'<?xml version="1.0" encoding="UTF-8"?><request><Mode>1</Mode>'
                f'<Plmn>{plmn}</Plmn><Rat>{rat}</Rat></request>')
        try: return self.post('/api/net/register', body)
        except Exception as e: return f'<error><code>exc</code>{e}</error>'

    def register_auto(self):
        """Revert to automatic network registration — /api/net/register Mode 0."""
        body = '<?xml version="1.0" encoding="UTF-8"?><request><Mode>0</Mode><Plmn></Plmn><Rat></Rat></request>'
        try: return self.post('/api/net/register', body)
        except Exception as e: return f'<error><code>exc</code>{e}</error>'

    def set_band_lock(self, lte_bands=None, nr_bands=None):
        """Lock to specific LTE bands using hex bitmask"""
        if lte_bands:
            mask = 0
            for b in lte_bands: mask |= BAND_HEX.get(b, 0)
            lte_hex = hex(mask).upper()[2:] if mask else '7FFFFFFFFFFFFFFF'
        else:
            lte_hex = '7FFFFFFFFFFFFFFF'

        if nr_bands:
            mask = 0
            for b in nr_bands: mask |= NR_BAND_HEX.get(b, 0)
            nr_hex = hex(mask).upper()[2:] if mask else '7FFFFFFFFFFFFFFF'
        else:
            nr_hex = '7FFFFFFFFFFFFFFF'

        return self.set_net_mode('03', lte_hex, nr_hex)

    def connected_devices(self):
        if self.use_lib:
            try: return self.client.host.hosts()
            except: pass
        try:
            xml = self.get('/api/host/info')
            hosts = []
            for h in ET.fromstring(xml).findall('.//Host'):
                hosts.append({c.tag: c.text or '' for c in h})
            return hosts
        except: return []

    def traffic_stats(self):
        if self.use_lib:
            try: return self.client.monitoring.traffic_statistics()
            except: pass
        try:
            xml = self.get('/api/monitoring/traffic-statistics')
            keys = ['CurrentDownloadRate','CurrentUploadRate','TotalDownload','TotalUpload','CurrentConnectTime']
            return {k: xml_val(xml, k) for k in keys}
        except: return {}

    def reboot(self):
        body = '<?xml version="1.0" encoding="UTF-8"?><request><Control>1</Control></request>'
        return self.post('/api/device/control', body)

    # ── WebUI-mapped reads (all live-verified against this firmware) ──
    @staticmethod
    def _xml_map(xml):
        """Map the child tags of the first response/error container to text."""
        out = {}
        try:
            root = ET.fromstring(xml)
            for el in root.iter():
                if len(el) == 0 and el.text and el.tag != 'response':
                    out[el.tag] = el.text
        except Exception:
            pass
        return out

    def _get_map(self, path, keys=(), timeout=10):
        try:
            xml = self.get('/' + path, timeout=timeout)
            m = self._xml_map(xml)
            if not keys and 'error' in xml and 'code' not in m:
                c = xml_val(xml, 'code')
                if c:
                    return {'code': c}
            return {k: (m.get(k) or '') for k in keys} if keys else m
        except Exception:
            return {}

    def module_switch(self):
        """All WebUI feature flags from /api/global/module-switch."""
        return self._get_map('api/global/module-switch')

    def cradle_status(self):
        """4G-dongle cradle info: status-info, basic-info, mac-info, factory-mac."""
        return {
            'status': self._get_map('api/cradle/status-info'),
            'basic':  self._get_map('api/cradle/basic-info'),
            'mac':    self._get_map('api/cradle/mac-info'),
            'factory':self._get_map('api/cradle/factory-mac'),
        }

    def dhcp_info(self):
        return self._get_map('api/dhcp/settings')

    def security_info(self):
        return {
            'bridge':    self._get_map('api/security/bridgemode'),
            'firewall':  self._get_map('api/security/firewall-switch'),
        }

    def wlan_statics(self):
        """Read-only WLAN configuration snapshot."""
        return {
            'basic':   self._get_map('api/wlan/multi-basic-settings'),
            'security':self._get_map('api/wlan/multi-security-settings'),
            'status':  self._get_map('api/wlan/status-switch-settings'),
            'feature': self._get_map('api/wlan/wifi-feature-switch'),
            'guide':   self._get_map('api/wlan/wlan-guide-settings'),
        }

    def pin_status(self):
        return {
            'pin':  self._get_map('api/pin/status'),
            'simlock': self._get_map('api/pin/simlock'),
        }

    def system_json(self, path='api/system/deviceinfo'):
        """/api/system/deviceinfo + devcapacity return JSON, not XML."""
        import json as _json
        try:
            raw = self.get('/' + path)
            return _json.loads(raw)
        except Exception:
            return {}

    def developer_mode(self):
        return self._get_map('api/developer/developermode-featureswitch')

    def current_language(self):
        return self._get_map('api/language/current-language')

    def history_login(self):
        return self._get_map('api/user/history-login')

    def log_info(self):
        """Latest system log (log/loginfo is a GET on this firmware)."""
        return self.get('/api/log/loginfo', timeout=12)

    def update_config(self):
        return {
            'config':        self._get_map('api/online-update/configuration'),
            'autoupdate':    self._get_map('api/online-update/autoupdate-config'),
        }

    def check_updates(self):
        """Trigger a manual firmware check — works with an empty POST."""
        try:
            r = self.post('/api/online-update/check-new-version',
                          '<?xml version="1.0" encoding="UTF-8"?><request/>', timeout=20)
            return False if xml_val(r, 'code') else True
        except Exception:
            return False

    def sms_list(self, page_index=1, read_count=20, box_type=1,
                 sort_type=0, ascending=0, unread_pref=0):
        """Read the SMS box. Requires the POST body (plain GET returns 100002)."""
        body = (f'<?xml version="1.0" encoding="UTF-8"?>'
                f'<request><PageIndex>{page_index}</PageIndex><ReadCount>{read_count}</ReadCount>'
                f'<BoxType>{box_type}</BoxType><SortType>{sort_type}</SortType>'
                f'<Ascending>{ascending}</Ascending><UnreadPreferred>{unread_pref}</UnreadPreferred></request>')
        msgs, err = [], ''
        try:
            xml = self.post('/api/sms/sms-list', body)
            code = xml_val(xml, 'code')
            if code:
                # This firmware simply has no SMS module provisioned — every
                # list/send variant returns 100002 (confirmed by live probing).
                err = ('SMS module not provisioned on this firmware '
                       '(endpoint returns 100002)')
                return msgs, err
            root = ET.fromstring(xml)
            for m in root.findall('.//Message'):
                msgs.append({c.tag: (c.text or '') for c in m})
            if not msgs:
                for m in root.findall('.//message'):
                    msgs.append({c.tag: (c.text or '') for c in m})
        except Exception as e:
            err = str(e)[:100]
        return msgs, err

    def wan_path(self):
        return self._get_map('api/staticroute/wanpath')

    def dialup_info(self):
        return self._get_map('api/dialup/connection')

    def lan_wan_config(self):
        return self._get_map('api/ntwk/lan-wan-config')

    def csps_state(self):
        return self._get_map('api/net/csps_state')

    def converged_status(self):
        return self._get_map('api/monitoring/converged-status')

    def check_notifications(self):
        return self._get_map('api/monitoring/check-notifications')

    def month_statistics(self):
        return self._get_map('api/monitoring/month_statistics')

    def start_date(self):
        return self._get_map('api/monitoring/start_date')

    def band_info(self):
        """Reported band information from /api/net/lte-band-info."""
        return self._get_map('api/net/lte-band-info')

    def net_reconnect(self):
        try:
            r = self.post('/api/net/reconnect',
                          '<?xml version="1.0" encoding="UTF-8"?><request><ReconnectAction>1</ReconnectAction></request>')
            return False if xml_val(r, 'code') else True
        except Exception:
            return False

    # ── System-settings page endpoints (js_systemsettings.js) ──
    def led_schedule(self):
        """Pilot lamp LED schedule (getAjaxData api/led/appctrlled)."""
        return self._get_map('api/led/appctrlled')

    def set_led_schedule(self, ledctrlswitch, starttime='00:00', endtime='00:00'):
        """Set pilot lamp schedule — exact body from postPilotlampInfo()."""
        return not bool(xml_val(self.post('/api/led/appctrlled',
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<request><ledctrlswitch>{ledctrlswitch}</ledctrlswitch>'
            f'<starttime>{starttime}</starttime><endtime>{endtime}</endtime></request>'), 'code'))

    def circle_led(self):
        """Master LED switch (changeLedSwitch writes {ledSwitch})."""
        return self._get_map('api/led/circle-switch')

    def set_circle_led(self, ledswitch):
        return not bool(xml_val(self.post('/api/led/circle-switch',
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<request><ledSwitch>{ledswitch}</ledSwitch></request>'), 'code'))

    def time_reboot(self):
        """Scheduled reboot config (diagnosis/time_reboot)."""
        return self._get_map('api/diagnosis/time_reboot')

    def set_time_reboot(self, enable, begintime, endtime, dayinterval):
        return not bool(xml_val(self.post('/api/diagnosis/time_reboot',
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<request><enable>{enable}</enable>'
            f'<begintime>{begintime}</begintime><endtime>{endtime}</endtime>'
            f'<dayinterval>{dayinterval}</dayinterval></request>'), 'code'))

    def usb_tethering(self):
        """USB tethering: master switch + current state."""
        return {
            'switch': self._get_map('api/device/usb-tethering-switch'),
            'state':  self._get_map('api/device/usb-tethering'),
        }

    def set_usb_tethering(self, tethering):
        return not bool(xml_val(self.post('/api/device/usb-tethering',
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<request><tethering>{tethering}</tethering></request>'), 'code'))

    def antenna_mode(self):
        """Antenna mode (auto/0 internal/1 external/2 mixed) set type + type."""
        return {
            'set_type': self._get_map('api/device/antenna_set_type'),
            'type':     self._get_map('api/device/antenna_type'),
        }

    def set_antenna_mode(self, antennasettype):
        return not bool(xml_val(self.post('/api/device/antenna_set_type',
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<request><antennasettype>{antennasettype}</antennasettype></request>'), 'code'))

    def online_update_config(self):
        return self._get_map('api/online-update/configuration')

    def set_online_update_config(self, not_need_login):
        return not bool(xml_val(self.post('/api/online-update/configuration',
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<request><not_need_login>{not_need_login}</not_need_login></request>'), 'code'))

    # ── Feature-switch flag endpoints (GLOBAL.modules sources) ──
    def dev_features(self):
        """device/device-feature-switch — onekeydiag etc."""
        return self._get_map('api/device/device-feature-switch')

    def wifi_features(self):
        """wlan/wifi-feature-switch — guestwifi, dual-band, wps flags."""
        return self._get_map('api/wlan/wifi-feature-switch')

    def dialup_features(self):
        """dialup/dialup-feature-switch — wanmanagement/wanprofile visibility."""
        return self._get_map('api/dialup/dialup-feature-switch')

    def statistic_features(self):
        return self._get_map('api/monitoring/statistic-feature-switch')

    def net_features(self):
        return self._get_map('api/net/net-feature-switch')

    def dhcp_features(self):
        return self._get_map('api/dhcp/feature-switch')

    # ── Wi-Fi extra toggles (doubleFrequency / intelligence / wifisync) ──
    # These are JSON-only endpoints on the router. Plain GET/POST (XML) get
    # 100002 SYSTEM_NO_SUPPORT from the server, so the WebUI renders them OFF.
    # The WebUI toggles them via JSON POST (content-type json + _ResponseFormat
    # JSON); the server then answers HTTP 200 with an empty JSON array.
    def _json_post(self, path, obj):
        self._get_fresh_token()
        h = self._headers()
        h['_ResponseFormat'] = 'JSON'
        h['Content-Type'] = 'application/json;charset=UTF-8'
        r = self.session.post(self.base() + path, data=json.dumps(obj), headers=h, timeout=12)
        self._update_token(r)
        if '125002' in r.text or '125003' in r.text:
            if self._silent_relogin():
                self._get_fresh_token()
                h = self._headers(); h['_ResponseFormat'] = 'JSON'
                h['Content-Type'] = 'application/json;charset=UTF-8'
                r = self.session.post(self.base() + path, data=json.dumps(obj), headers=h, timeout=12)
                self._update_token(r)
        return self._json_request(path, obj) is not None

    def _json_request(self, path, obj):
        """JSON POST exactly as ObjController.postData does when contentType has
        'json': headers _ResponseSource/_ResponseFormat JSON, json body, fresh
        token. Returns response text (None on failure)."""
        self._get_fresh_token()
        h = self._headers()
        h['_ResponseFormat'] = 'JSON'
        h['Content-Type'] = 'application/json;charset=UTF-8'
        r = self.session.post(self.base() + path, data=json.dumps(obj), headers=h, timeout=12)
        self._update_token(r)
        if '125002' in r.text or '125003' in r.text:
            if self._silent_relogin():
                self._get_fresh_token()
                h = self._headers(); h['_ResponseFormat'] = 'JSON'
                h['Content-Type'] = 'application/json;charset=UTF-8'
                r = self.session.post(self.base() + path, data=json.dumps(obj), headers=h, timeout=12)
                self._update_token(r)
        return r.text if r.status_code == 200 else None

    def _xml_post(self, path, inner):
        """POST an XML body built as <request><inner.../request> — the WebUI's
        object2xml('request', data). Reports {'code':..,'ok':bool}."""
        try:
            xml = self.post('/' + path,
                            '<?xml version="1.0" encoding="UTF-8"?><request>' + inner + '</request>')
            c = xml_val(xml, 'code')
            return {'code': (c or 'OK'), 'ok': not bool(c)}
        except Exception as e:
            return {'code': 'exc', 'ok': False, 'err': str(e)[:80]}

    def wlan_intelligent(self, enable=None):
        """Wi-Fi intelligent (smart switch). GET -> 100002 (off); JSON POST {'data':{'enable':bool}}."""
        if enable is None:
            return self._get_map('api/wlan/wlanintelligent')
        return self._json_post('/api/wlan/wlanintelligent', {'data': {'enable': bool(enable)}})

    def wlan_dbho(self, enable=None):
        """Dual-band hand-over. JSON POST {'data':{'DbhoEnable':0|1,'WifiRestart':0}}."""
        if enable is None:
            return self._get_map('api/wlan/wlandbho')
        return self._json_post('/api/wlan/wlandbho',
                               {'data': {'DbhoEnable': 1 if enable else 0, 'WifiRestart': 0}})

    def wlan_wifisync(self, enable=None):
        """Wi-Fi sync — read-only status endpoint (load() only, no UI write)."""
        return self._get_map('api/wlan/wlanwifisync')

    # ── Every remaining WebUI write action (bodies pulled from the dump) ──
    def set_user_behavior(self, enable):
        """diagnosis/user_behavior — user-experience/CHR log upload switch
        ({chrlog_upload_enable:'0'|'1'})."""
        return self._xml_post('api/diagnosis/user_behavior',
                              '<chrlog_upload_enable>%d</chrlog_upload_enable>' % (1 if enable else 0))

    def agree_privacy(self, approve='2', liscence='0'):
        """app/privacypolicy — agree the licence (WebUI agreePrivacyNotice body)."""
        return self._xml_post('api/app/privacypolicy',
                              '<data><Approve>%s</Approve><Liscence>%s</Liscence></data>' % (approve, liscence))

    def set_mac_clone(self, currentmac):
        """cradle/current-mac — MAC clone on the 4G-dongle ethernet port
        (GuideCurMacController body: {currentmac})."""
        return self._xml_post('api/cradle/current-mac', '<currentmac>%s</currentmac>' % currentmac)

    def set_cradle_wan(self, **fields):
        """cradle/basic-info — WAN/PPPoE/static settings (GuideSetCradleController,
        connectionmode/pppoeuser/pppoepwd/ipaddress/netmask/gateway/dns/mtu/auth…).
        Pass only the fields you want changed."""
        return self._xml_post('api/cradle/basic-info', ''.join(
            '<%s>%s</%s>' % (k, v, k) for k, v in fields.items()))

    def set_log_view(self, display_type, display_level):
        """log/loginfo — which log type/level is listed
        (DisplayType/DisplayLevel, from submitSystemLogDataProcess)."""
        return self._xml_post('api/log/loginfo',
                              '<DisplayType>%s</DisplayType><DisplayLevel>%s</DisplayLevel>' % (display_type, display_level))

    def set_lte_band_mask(self, mask='7FFFFFFFFFFFFFFF'):
        """net/lte-band-info — NSA LTE band mask (developermode nsarequest
        {current_lte_band}). '7FFFFFFFFFFFFFFF' clears the band lock."""
        return self._xml_post('api/net/lte-band-info', '<current_lte_band>%s</current_lte_band>' % mask)

    def check_online_upgrade(self):
        """system/onlineupg — JSON {'action':'check','data':{'UpdateAction':1}}
        (globalDetectSmartUpgVersionController.checkNewversion)."""
        return self._json_request('/api/system/onlineupg',
                                  {'action': 'check', 'data': {'UpdateAction': 1}})

    def set_auto_upgrade(self, auto_update, ui_download=0):
        """online-update/autoupdate-config (AutoUpgradeController.sendUpgData
        body: {auto_update, ui_download})."""
        return self._xml_post('api/online-update/autoupdate-config',
                              '<auto_update>%s</auto_update><ui_download>%s</ui_download>' % (auto_update, ui_download))

    def set_agency_upgrade(self, auto_update_interval, server_force_enable):
        """online-update/configuration agency-switch (sendAgencyUpg body:
        {autoUpdateInterval, server_force_enable})."""
        return self._xml_post('api/online-update/configuration',
                              '<autoUpdateInterval>%s</autoUpdateInterval>'
                              '<server_force_enable>%s</server_force_enable>' % (auto_update_interval, server_force_enable))

    def set_developer_mode(self, enable):
        """user/second_login — developer/second-login switch (developermode
        developerSwitchObjCtrl). Verified live + browser-console: only DISABLE
        (enable=0) is writable by POST (OK). ENABLE via POST is rejected with
        100006 — it is NOT a write: the WebUI turns it on by logging in from the
        developer page (SCRAM auth with loginflag=2), which the server actionizes
        as a side effect (see dev_login())."""
        return self._xml_post('api/user/second_login', '<enable>%s</enable>' % (1 if enable else 0))

    def dev_login(self, username, password):
        """Developer-context login — byte-for-byte the WebUI developer page's
        login button (#cradleDisconnected_login_box #developer_btn →
        LoginObjController.Login(0, cb, box, true)): a SCRAM login whose
        authentication_login carries loginflag='2'. The server responds by
        setting user/second_login enable back to 1 — the ONLY way the firmware
        re-enables developer second-login. Session stays usable after it."""
        return self._scram_login(username, password, loginflag='2')

    def second_login(self):
        """user/second_login — second-login (dev-page) gate: enable=1 dev page
        opens without a password prompt, 0 = gate shown on entry."""
        return self._get_map('api/user/second_login')

    def set_wifi_settings(self, ssid_entries):
        """wlan/multi-basic-settings — save full SSID table. ssid_entries is a
        list of dicts (each an Ssid node from wlan-guide-settings/multi-basic-
        settings: ID, Index, WifiSsid, WifiWpapsk, WifiAuthmode, …). Matches the
        WebUI's GuideWlanObjController/wifi-save flow."""
        inner = '<Ssids><Ssid>' + '</Ssid><Ssid>'.join(
            ''.join('<%s>%s</%s>' % (k, v, k) for k, v in e.items()) for e in ssid_entries
        ) + '</Ssid></Ssids>'
        return self._xml_post('api/wlan/multi-basic-settings', inner)

    def set_login_password(self, currentpassword, newpassword, username='admin'):
        """user/password_scram — change the WebUI login password. WARNING: the
        WebUI sends this body RSA-encrypted (contentType ';enc'); plaintext may
        be rejected on builds that enforce encryption. Not intended for blind
        live runs — verify carefully."""
        return self._xml_post(
            'api/user/password_scram',
            '<username>%s</username><currentpassword>%s</currentpassword>'
            '<newpassword>%s</newpassword>' % (username, currentpassword, newpassword))

    # ── Remaining dump endpoints ──
    def cbs_news(self):
        """Cell Broadcast SMS list (CBSNewListController)."""
        return self.post('/api/sms/get-cbsnewslist',
                         '<?xml version="1.0" encoding="UTF-8"?><request/>')

    def operator_info(self):
        """app/operatorinfo returns JSON, not XML."""
        return self.system_json('api/app/operatorinfo')

    def privacy_policy(self):
        """app/privacypolicy returns JSON, not XML."""
        return self.system_json('api/app/privacypolicy')

    def device_capacity(self):
        """system/devcapacity (JSON) + ioc_device_capacity.json."""
        out = {'devcapacity': self.system_json('api/system/devcapacity')}
        try:
            raw = self.get('/system/ioc_device_capacity.json')
            import json as _json
            out['ioc'] = _json.loads(raw)
        except Exception:
            out['ioc'] = {}
        return out

    def encryp_imsi(self):
        return self._get_map('api/device/encryp_imsi_imei')

    def log_export(self):
        """System log export — exact WebUI flow: POST log_operate_type=1."""
        try:
            xml = self.post('/api/log/logexport',
                            '<?xml version="1.0" encoding="UTF-8"?>'
                            '<request><log_operate_type>1</log_operate_type></request>')
            return {'code': (xml_val(xml, 'code') or 'OK')}
        except Exception:
            return {}

    def onekey_diag(self):
        return self._get_map('api/monitoring/onekey_diag')

    def voice_status(self):
        """voice/voiperstatus — SIP/VoIP state (hangs when no VoIP subsystem)."""
        m = self._get_map('api/voice/voiperstatus', timeout=8)
        if m:
            return m
        return {'state': 'no response — VoIP subsystem not active on this unit'}

    def voice_busy(self):
        m = self._get_map('api/voice/voicebusy', timeout=8)
        if m:
            return m
        return {'state': 'no response — voice subsystem not active'}

    def volte(self):
        return self._get_map('api/voice/volte')

    def set_ims_display(self, enabled):
        return not bool(xml_val(self.post('/api/voice/volte',
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<request><ui_display_ims>{1 if enabled else 0}</ui_display_ims></request>'), 'code'))

    def smart_upgrade(self):
        """Header auto-upgrade checks (system/onlineupg + onlinestate?devid=all)."""
        return {
            'upg':   self._get_map('api/system/onlineupg'),
            'state': self._get_map('api/system/onlinestate?devid=all'),
        }

    def homepage_redirect(self):
        return self._get_map('api/redirection/homepage')

# ══════════════════════════════════════════════════════════════
#  Main App
# ══════════════════════════════════════════════════════════════
class HuaweiTool(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f'Huawei Router Tool v{APP_VERSION}')
        self.geometry('1000x720')
        self.minsize(900, 640)
        self.configure(bg=COLORS['bg'])

        self.api = None
        self.connected = False
        self.cfg = load_config()
        self.locked_cell = None
        self.refresh_job = None
        self.signal_history = []
        self._cells = []
        self._nei_logging = False
        self._nei_logger_stop = threading.Event()
        self._nei_seen = set()  # (band, nei) captured this session
        self._sweeping = False
        self._ant_sweeping = False
        self._initial_sweep_ok = None  # None=pending popup answer, else True/False

        self._apply_theme()
        self._build_ui()
        self._start_refresh()
        self.protocol('WM_DELETE_WINDOW', self._on_close)

    # ── Theme ──────────────────────────────────────────────────
    def _apply_theme(self):
        s = ttk.Style(self)
        s.theme_use('clam')
        bg,sb,sf = COLORS['bg'], COLORS['surface'], COLORS['surface2']
        fg,mu,ac = COLORS['text'], COLORS['muted'], COLORS['accent']
        bd = COLORS['border']

        s.configure('.', background=bg, foreground=fg, fieldbackground=sf,
                    troughcolor=sb, bordercolor=bd, darkcolor=sb, lightcolor=sb,
                    selectbackground=ac, selectforeground=bg, font=('Segoe UI',10))
        s.configure('TFrame',   background=bg)
        s.configure('TLabel',   background=bg, foreground=fg)
        s.configure('TButton',  background=sf, foreground=fg, borderwidth=1,
                    relief='flat', padding=(12,6))
        s.map('TButton',
              background=[('active',ac),('pressed',COLORS['accent2'])],
              foreground=[('active',bg)])
        s.configure('Accent.TButton', background=ac, foreground=bg, font=('Segoe UI',10,'bold'))
        s.map('Accent.TButton', background=[('active',COLORS['accent2'])])
        s.configure('Danger.TButton', background=COLORS['red'], foreground='white')
        s.map('Danger.TButton', background=[('active','#c62828')])
        s.configure('Running.TButton', background=COLORS['accent2'], foreground=bg, font=('Segoe UI',10,'bold'))
        s.map('Running.TButton', background=[('active',COLORS['accent2'])])
        s.configure('TEntry',   fieldbackground=sf, foreground=fg, insertcolor=fg,
                    bordercolor=bd, relief='flat', padding=6)
        s.configure('TNotebook', background=bg, borderwidth=0, tabmargins=[0,0,0,0])
        s.configure('TNotebook.Tab', background=sb, foreground=mu, padding=(16,8),
                    borderwidth=0, font=('Segoe UI',10))
        s.map('TNotebook.Tab',
              background=[('selected',bg)],
              foreground=[('selected',ac)],
              expand=[('selected',[0,0,0,2])])
        s.configure('Treeview', background=sf, foreground=fg, fieldbackground=sf,
                    borderwidth=0, rowheight=28)
        s.configure('Treeview.Heading', background=sb, foreground=mu,
                    font=('Segoe UI',9,'bold'), relief='flat', borderwidth=0)
        s.map('Treeview', background=[('selected',ac)], foreground=[('selected',bg)])
        s.configure('TSeparator', background=bd)
        s.configure('TCheckbutton', background=bg, foreground=fg)
        s.configure('TCombobox', fieldbackground=sf, foreground=fg, background=sf)

    # ── UI Build ───────────────────────────────────────────────
    def _build_ui(self):
        # ── Header bar ──
        hdr = tk.Frame(self, bg=COLORS['surface'], height=56)
        hdr.pack(fill='x', side='top')
        hdr.pack_propagate(False)
        tk.Label(hdr, text='⬡  Huawei Router Tool', bg=COLORS['surface'],
                 fg=COLORS['accent'], font=('Segoe UI',14,'bold')).pack(side='left', padx=20, pady=10)
        self.conn_label = tk.Label(hdr, text='● Disconnected', bg=COLORS['surface'],
                                   fg=COLORS['red'], font=('Segoe UI',10))
        self.conn_label.pack(side='right', padx=20)
        self.conn_pb = ttk.Progressbar(hdr, mode='indeterminate', length=90)
        self.conn_pb.pack(side='right', padx=(0,8))
        ttk.Separator(self, orient='horizontal').pack(fill='x')

        # ── Connection strip ──
        cs = tk.Frame(self, bg=COLORS['surface2'], pady=10)
        cs.pack(fill='x', padx=0)
        inner = tk.Frame(cs, bg=COLORS['surface2'])
        inner.pack(padx=20, fill='x')

        tk.Label(inner, text='Router IP', bg=COLORS['surface2'], fg=COLORS['muted'],
                 font=('Segoe UI',9)).grid(row=0,column=0,sticky='w')
        self.e_ip = ttk.Entry(inner, width=16)
        self.e_ip.insert(0, self.cfg.get('ip','192.168.8.1'))
        self.e_ip.grid(row=0,column=1,padx=(4,24),sticky='w')

        tk.Label(inner, text='Password', bg=COLORS['surface2'], fg=COLORS['muted'],
                 font=('Segoe UI',9)).grid(row=0,column=2,sticky='w')
        self.e_pass = ttk.Entry(inner, width=20, show='●')
        self.e_pass.insert(0, self.cfg.get('password',''))
        self.e_pass.grid(row=0,column=3,padx=(4,16))
        self.e_pass.bind('<Return>', lambda e: self._connect())

        self.btn_connect = ttk.Button(inner, text='Connect', style='Accent.TButton',
                                      command=self._connect)
        self.btn_connect.grid(row=0,column=4,padx=(0,8))
        self.btn_disconnect = ttk.Button(inner, text='Disconnect', command=self._disconnect)
        self.btn_disconnect.grid(row=0,column=5)
        self.btn_disconnect.state(['disabled'])

        self.status_var = tk.StringVar(value='Enter password and click Connect')
        tk.Label(inner, textvariable=self.status_var, bg=COLORS['surface2'],
                 fg=COLORS['muted'], font=('Segoe UI',9)).grid(row=0,column=6,padx=(20,0))

        ttk.Separator(self, orient='horizontal').pack(fill='x')

        # ── Signal strip (always visible) ──
        self._build_signal_strip()

        # ── Notebook ──
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill='both', expand=True, padx=0, pady=0)

        self._tab_cells  = self._make_tab('📡  Cell Scanner')
        self._tab_bands  = self._make_tab('📶  Band Lock')
        self._tab_opt    = self._make_tab('⚡  Optimiser')
        self._tab_antenna = self._make_tab('📡  Antenna')
        self._tab_info   = self._make_tab('ℹ   Device Info')
        self._tab_sys    = self._make_tab('⚙   System')
        self._tab_hosts  = self._make_tab('🖥  Devices')
        self._tab_sms    = self._make_tab('💬  SMS')
        self._tab_chart  = self._make_tab('📊  Chart')
        self._tab_log    = self._make_tab('🪵  Log')

        self._build_tab_cells()
        self._build_tab_bands()
        self._build_tab_optimiser()
        self._build_tab_antenna()
        self._build_tab_info()
        self._build_tab_sys()
        self._build_tab_hosts()
        self._build_tab_sms()
        self._build_tab_chart()
        self._build_tab_log()

        # Refresh antenna status whenever that tab is opened
        self.nb.bind('<<NotebookTabChanged>>', self._on_tab_changed)

        # ── Status bar ──
        sb_frame = tk.Frame(self, bg=COLORS['surface'], height=26)
        sb_frame.pack(fill='x', side='bottom')
        sb_frame.pack_propagate(False)
        self.sb_var = tk.StringVar(value='Ready')
        tk.Label(sb_frame, textvariable=self.sb_var, bg=COLORS['surface'],
                 fg=COLORS['muted'], font=('Segoe UI',8), anchor='w').pack(
                     side='left', padx=12, fill='x')
        self.sb_time = tk.Label(sb_frame, text='', bg=COLORS['surface'],
                                fg=COLORS['muted'], font=('Segoe UI',8))
        self.sb_time.pack(side='right', padx=12)

    def _make_tab(self, label):
        f = ttk.Frame(self.nb)
        self.nb.add(f, text=label)
        return f

    # ── Signal strip ──────────────────────────────────────────
    def _build_signal_strip(self):
        strip = tk.Frame(self, bg=COLORS['surface'], height=64)
        strip.pack(fill='x')
        strip.pack_propagate(False)

        self._sig_widgets = {}
        fields = [
            ('Band','band'),('EARFCN','earfcn'),('PCI','pci'),
            ('RSRP','rsrp'),('RSRQ','rsrq'),('SINR','sinr'),
            ('Mode','mode'),('Cell ID','cell_id'),
            ('PLMN','plmn'),('Neighb PCI','nei'),
        ]
        for i,(label,key) in enumerate(fields):
            cell = tk.Frame(strip, bg=COLORS['surface'])
            cell.pack(side='left', expand=True, fill='both',
                      padx=(1 if i else 0, 0))
            tk.Label(cell, text=label, bg=COLORS['surface'],
                     fg=COLORS['muted'], font=('Segoe UI',8)).pack(pady=(8,0))
            val = tk.Label(cell, text='—', bg=COLORS['surface'],
                           fg=COLORS['accent'], font=('Segoe UI',12,'bold'))
            val.pack()
            self._sig_widgets[key] = val
        ttk.Separator(self, orient='horizontal').pack(fill='x')

    def _update_signal_strip(self, sig):
        earfcn = sig.get('earfcn','')
        band   = sig.get('band','')
        if not band and earfcn:
            b = earfcn_to_band(earfcn)
            if b: band = f'B{b}'

        mode_raw = sig.get('mode','')
        mode_str = MODE_LABELS.get(str(mode_raw), mode_raw or '—')

        def sv(key, val, color=None):
            w = self._sig_widgets.get(key)
            if w:
                w.config(text=val or '—', fg=color or COLORS['accent'])

        sv('band',    band or '—')
        sv('earfcn',  earfcn or '—')
        sv('pci',     sig.get('pci','') or '—')
        sv('cell_id', sig.get('cell_id','') or '—')
        sv('mode',    mode_str)
        sv('plmn',    sig.get('plmn','') or '—')

        # Neighbour PCIs from nei_cellid (same EARFCN as serving cell)
        nei = sig.get('nei_cellid','')
        nei_s = ''
        if nei:
            npcis = re.findall(r'No\d+\s*:\s*(\d+)', nei)
            nei_s = ', '.join(npcis) if npcis else nei
        sv('nei', nei_s, COLORS['accent2'] if nei_s else None)

        # NR (5G) summary — surface the 5G band and RSRP when active
        nrearfcn = sig.get('nrearfcn','')
        if nrearfcn:
            nrb = nrearfcn_to_band(nrearfcn)
            nrb_s = f'n{nrb}' if nrb else '5G'
            band = f"{band}+{nrb_s}" if band else nrb_s
            sv('band', band or '—')
            nrrsrp = sig.get('nrrsrp','')
            if nrrsrp:
                if getattr(self, '_last_nrearfcn', '') != nrearfcn:
                    self.log(f'5G active: {nrb_s} DL-NR EARFCN={nrearfcn} RSRP={nrrsrp} dBm', 'ok')
                self._last_nrearfcn = nrearfcn
            else:
                self._last_nrearfcn = None

        rsrp = sig.get('rsrp',''); rsrq = sig.get('rsrq',''); sinr = sig.get('sinr','')
        rsrp_d = f'{rsrp} dBm' if rsrp else '—'
        rsrq_d = f'{rsrq} dB'  if rsrq else '—'
        sinr_d = f'{sinr} dB'  if sinr else '—'
        sv('rsrp', rsrp_d, COLORS[rsrp_class(rsrp)])
        sv('rsrq', rsrq_d, COLORS[rsrq_class(rsrq)])
        sv('sinr', sinr_d, COLORS[sinr_class(sinr)])

        # Track history for chart
        try:
            self.signal_history.append({
                'time': datetime.now(), 'rsrp': safe_rsrp(rsrp),
                'rsrq': safe_rsrp(rsrq), 'sinr': safe_rsrp(sinr),
            })
            if len(self.signal_history) > 120:
                self.signal_history = self.signal_history[-120:]
        except: pass

    # ── Tab: Cell Scanner ────────────────────────────────────
    def _build_tab_cells(self):
        f = self._tab_cells
        top = tk.Frame(f, bg=COLORS['bg'])
        top.pack(fill='x', padx=16, pady=(14,6))
        tk.Label(top, text='Cell Scanner', bg=COLORS['bg'],
                 fg=COLORS['text'], font=('Segoe UI',12,'bold')).pack(side='left')

        # Toolbar — split over two rows so every button stays fully visible in
        # windowed mode (a single packed row overflows at min window width).
        tb = tk.Frame(f, bg=COLORS['bg'])
        tb.pack(fill='x', padx=16, pady=(0,8))
        row1 = tk.Frame(tb, bg=COLORS['bg'])
        row1.pack(fill='x', pady=(0,4))
        self.btn_scan = ttk.Button(row1, text='⟳  Scan', style='Accent.TButton',
                                   command=self._do_scan)
        self.btn_scan.pack(side='left', padx=(0,6))
        self.btn_net_search = ttk.Button(row1, text='🔍  Network Search',
                                         command=self._do_network_search)
        self.btn_net_search.pack(side='left', padx=(0,6))
        self.btn_band_sweep = ttk.Button(row1, text='🔭  Sweep All Bands',
                                         command=self._manual_sweep)
        self.btn_band_sweep.pack(side='left', padx=(0,6))
        self.btn_speed = ttk.Button(row1, text='🔄  Speed Test', style='Accent.TButton',
                                    command=self._do_speedtest)
        self.btn_speed.pack(side='left', padx=(0,6))
        row2 = tk.Frame(tb, bg=COLORS['bg'])
        row2.pack(fill='x')
        ttk.Button(row2, text='📋  Copy Browser Neigh-Cell Snippet',
                   command=self._copy_browser_snippet).pack(side='left', padx=(0,6))
        self.btn_register_auto = ttk.Button(row2, text='📶  Re-register Auto',
                                            command=self._do_register_auto)
        self.btn_register_auto.pack(side='left', padx=(0,6))
        self.btn_unlock = ttk.Button(row2, text='✕  Remove Lock', style='Danger.TButton',
                                     command=self._do_unlock, state='disabled')
        self.btn_unlock.pack(side='left', padx=(0,6))
        self.lock_badge = tk.Label(row2, text='', bg=COLORS['bg'],
                                   fg=COLORS['green'], font=('Segoe UI',10,'bold'))
        self.lock_badge.pack(side='left', padx=(0,10))

        # Band-sweep progress (initial + manual sweep) — always visible below
        # the toolbar so you can see a sweep running even from another point.
        prog = tk.Frame(f, bg=COLORS['bg'])
        self.sweep_lbl = tk.Label(prog, text='Band sweep:', bg=COLORS['bg'],
                                  fg=COLORS['muted'], font=('Segoe UI',8))
        self.sweep_lbl.pack(side='left', padx=(16,6))
        self.sweep_pb = ttk.Progressbar(prog, mode='determinate',
                                        maximum=len(NEI_SWEEP_BANDS), length=220)
        self.sweep_pb.pack(side='left', padx=(0,6))
        self.sweep_lbl_val = tk.Label(prog, text='idle', bg=COLORS['bg'],
                                      fg=COLORS['muted'], font=('Segoe UI',8))
        self.sweep_lbl_val.pack(side='left')
        self.ns_lbl = tk.Label(prog, text='Network search:', bg=COLORS['bg'],
                               fg=COLORS['muted'], font=('Segoe UI',8))
        self.ns_lbl.pack(side='left', padx=(16,6))
        self.ns_pb = ttk.Progressbar(prog, mode='indeterminate', length=120)
        self.ns_pb.pack(side='left', padx=(0,6))
        self.speed_lbl = tk.Label(prog, text='Speed test:', bg=COLORS['bg'],
                                  fg=COLORS['muted'], font=('Segoe UI',8))
        self.speed_lbl.pack(side='left', padx=(16,6))
        self.speed_pb = ttk.Progressbar(prog, mode='indeterminate', length=120)
        self.speed_pb.pack(side='left', padx=(0,6))
        prog.pack(fill='x', padx=16, pady=(0,8))
        self._sweep_prog_frame = prog

        # Discovered-cell lock frame — dropdowns fed by serving/CA/neighbour cells
        ml = tk.LabelFrame(f, text=' Lock to Discovered Cell ', bg=COLORS['bg'],
                           fg=COLORS['muted'], font=('Segoe UI',9), bd=1, relief='groove')
        ml.pack(fill='x', padx=16, pady=(0,8))
        mlr = tk.Frame(ml, bg=COLORS['bg'])
        mlr.pack(padx=10, pady=6, fill='x')

        tk.Label(mlr, text='Frequency (band)', bg=COLORS['bg'], fg=COLORS['muted'], font=('Segoe UI',9)).pack(side='left')
        self.cb_earfcn = ttk.Combobox(mlr, width=16, state='readonly')
        self.cb_earfcn.pack(side='left', padx=(4,14))
        tk.Label(mlr, text='Cell (PCI)', bg=COLORS['bg'], fg=COLORS['muted'], font=('Segoe UI',9)).pack(side='left')
        self.cb_pci = ttk.Combobox(mlr, width=12)
        self.cb_pci.pack(side='left', padx=(4,14))
        ttk.Button(mlr, text='🔒  Lock to Cell', command=self._do_manual_lock).pack(side='left', padx=(0,16))
        tk.Label(mlr, text='Frequencies/bands shown are the ones found by Scan, Network Search and the neighbour logger — pick one, then the PCI sector (leave PCI empty to lock the whole frequency). Band-wide locks belong to the Band Lock tab.',
                 bg=COLORS['bg'], fg=COLORS['muted'], font=('Segoe UI',8)).pack(side='left')

        self.cb_earfcn.bind('<<ComboboxSelected>>', self._on_earfcn_pick)
        self._preset_earfcns = ['400', '1250', '1500', '1675', '1815', '2150', '2450', '2650', '2750', '3300', '3450', '37900']

        # Cell table
        cols   = ('type','band','earfcn','pci','rsrp','rsrq','sinr','cell_id')
        hdrs   = ('Type','Band','EARFCN','PCI','RSRP','RSRQ','SINR','Cell ID')
        widths = (70,55,70,55,100,90,80,90)

        frame = tk.Frame(f, bg=COLORS['bg'])
        frame.pack(fill='both', expand=True, padx=16, pady=(0,8))
        self.tree_cells = ttk.Treeview(frame, columns=cols, show='headings', height=10)
        for c,h,w in zip(cols,hdrs,widths):
            self.tree_cells.heading(c, text=h)
            self.tree_cells.column(c, width=w, anchor='center')
        sb = ttk.Scrollbar(frame, orient='vertical', command=self.tree_cells.yview)
        self.tree_cells.configure(yscrollcommand=sb.set)
        self.tree_cells.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')
        self.tree_cells.bind('<Double-1>', self._on_cell_double_click)
        self.tree_cells.bind('<ButtonRelease-1>', self._on_cell_select)
        self.tree_cells.tag_configure('serving', foreground=COLORS['green'])
        self.tree_cells.tag_configure('locked',  foreground=COLORS['green'], background=COLORS['surface2'])
        self.tree_cells.tag_configure('ca',      foreground=COLORS['accent'])
        self.tree_cells.tag_configure('plmn',    foreground=COLORS['yellow'])

        tk.Label(f, text='Click a row to load it into the lock dropdowns  •  Double-click to lock  •  Scan reads serving+CA cells  •  🔍 Network Search forces the modem to scan all towers (~30s)  •  Band sweeps add each band\u2019s camped-cell SINR',
                 bg=COLORS['bg'], fg=COLORS['muted'], font=('Segoe UI',8)).pack(pady=(0,6))

    def _render_cells(self):
        for row in self.tree_cells.get_children():
            self.tree_cells.delete(row)

        sorted_cells = sorted(self._cells, key=lambda c: (
            0 if c['type']=='Serving' else 1 if c['type']=='CA-SCC' else 2,
            -(safe_rsrp(c['rsrp']) if c.get('rsrp') else -150)
        ))

        for c in sorted_cells:
            earfcn = c.get('earfcn','')
            pci    = c.get('pci','')
            band   = c.get('band')
            band_s = f"B{band}" if band else '—'
            rsrp   = c.get('rsrp',''); rsrq = c.get('rsrq',''); sinr = c.get('sinr','')
            is_locked = (self.locked_cell and
                         self.locked_cell.get('pci') == pci and
                         self.locked_cell.get('earfcn') == earfcn)
            typ = '🔒 ' + c['type'] if is_locked else c['type']
            tag = 'locked' if is_locked else ('serving' if c['type']=='Serving' else
                  'ca' if c['type']=='CA-SCC' else '')
            self.tree_cells.insert('', 'end', values=(
                typ, band_s, earfcn or '—', pci or '—',
                f'{rsrp} dBm' if rsrp else '—',
                f'{rsrq} dB'  if rsrq else '—',
                f'{sinr} dB'  if sinr else '—',
                c.get('cell_id','') or '—',
            ), tags=(tag,), iid=f"{pci}_{earfcn}")
        self._refresh_lock_combos()

    def _do_scan(self):
        if not self.connected:
            self.log('Scan clicked but not connected', 'warn')
            self.sb_var.set('Not connected'); return
        self.btn_scan.state(['disabled'])
        self.sb_var.set('Scanning cells…')
        self.log('Cell scan started', 'info')
        def worker():
            cells, logs = self.api.scan_cells_logged()
            for lvl, msg in logs:
                self.log(msg, lvl)
            # Keep neighbour & manual rows across scans so the lock dropdowns
            # don't lose captured frequencies (that's what made PCI show -1).
            keep   = [c for c in self._cells if c['type'] in ('Neighbor','Manual')]
            merged = list(cells)
            seen_k = {f"{c.get('pci','?')}_{c.get('earfcn','?')}" for c in merged}
            for c in keep:
                k = f"{c.get('pci','?')}_{c.get('earfcn','?')}"
                if k not in seen_k:
                    seen_k.add(k)
                    merged.append(c)
            self._cells = merged
            self.after(0, self._render_cells)
            self.after(0, lambda: self.sb_var.set(f'Found {len(merged)} cell(s)'))
            self.after(0, lambda: self.btn_scan.state(['!disabled']))
            self.log(f'Scan complete — {len(merged)} cell(s) found', 'ok' if cells else 'warn')
        threading.Thread(target=worker, daemon=True).start()

    def _on_cell_double_click(self, evt):
        sel = self.tree_cells.selection()
        if not sel: return
        iid = sel[0]
        entry = next((c for c in self._cells
                      if f"{c.get('pci','?_')}_{c.get('earfcn','?')}" == iid), None)
        if entry is None:
            parts = iid.split('_', 1)
            if len(parts) == 2: self._lock(parts[0], parts[1])
            return
        if entry.get('type') == 'PLMN':
            plmn = entry.get('pci','')
            ratn = entry.get('rat_num','')
            if not plmn: return
            if not messagebox.askyesno(
                    'Manual Register',
                    f'Re-register to {entry.get("cell_id","(name)")}?\nPLMN {plmn}  RAT {ratn}\n\nThis may briefly drop the connection.'):
                return
            self._register_to(plmn, ratn)
        else:
            self._lock(entry.get('pci',''), entry.get('earfcn',''))

    def _register_to(self, plmn, rat):
        if not self.connected: return
        self.log(f'Manual register: PLMN {plmn} RAT {rat}…', 'info')
        def worker():
            try:
                self.api.check_session()
                resp = self.api.register_cell(plmn, rat)
                err  = xml_val(resp, 'code')
                if err:
                    self.log(f'Register failed: error {err}', 'error')
                    self.after(0, lambda: self.sb_var.set(f'Register failed: {err}'))
                else:
                    self.log('Register sent OK — waiting for attach…', 'ok')
                    self.after(0, lambda: self.sb_var.set('Register sent OK'))
            except Exception as e:
                self.log(f'Register error: {e}', 'error')
        threading.Thread(target=worker, daemon=True).start()

    def _do_register_auto(self):
        if not self.connected:
            self.log('Not connected', 'warn'); return
        self.log('Re-register auto…', 'info')
        def worker():
            try:
                self.api.check_session()
                resp = self.api.register_auto()
                err  = xml_val(resp, 'code')
                if err:
                    # Router still settling after a reconnect — wait and retry once
                    time.sleep(8)
                    self.api.check_session()
                    resp = self.api.register_auto()
                    err  = xml_val(resp, 'code')
                if err:
                    self.log(f'Re-register failed: error {err}', 'error')
                    self.after(0, lambda: self.sb_var.set(f'Register failed: {err}'))
                else:
                    self.log('Automatic registration reapplied', 'ok')
                    self.after(0, lambda: self.sb_var.set('Auto registration reapplied'))
            except Exception as e:
                self.log(f'Re-register error: {e}', 'error')
        threading.Thread(target=worker, daemon=True).start()

    def _lock(self, pci, earfcn):
        if not self.connected: return
        # Rapid re-locks to the SAME cell each kick a modem re-search and queue
        # up on the router (field log: one cell re-locked 20+ times in minutes,
        # wedging the modem so the next band sweep got 100003 the whole way).
        band = earfcn_to_band(earfcn)
        now = time.time()
        last = getattr(self, '_last_lock', None)
        if last and last[0] == str(pci) and last[1] == str(earfcn) and now - last[2] < 10:
            return
        self._last_lock = (str(pci), str(earfcn), now)
        def worker():
            ok, msg = self.api.lock_cell(pci, earfcn)
            if not ok:
                # Stale session (a net-mode change rotates it) — re-auth and retry once
                try:
                    self.api.check_session()
                    ok, msg = self.api.lock_cell(pci, earfcn)
                except Exception:
                    pass
            if ok:
                self.locked_cell = {'pci':pci,'earfcn':earfcn,'band':band}
                badge = f'🔒  Locked → PCI {pci} / EARFCN {earfcn}' + (f' (B{band})' if band else '')
                self.after(0, lambda: self.lock_badge.config(text=badge, fg=COLORS['green']))
                self.after(0, lambda: self.btn_unlock.state(['!disabled']))
                self.log(f'Cell locked → PCI {pci} / EARFCN {earfcn}', 'ok')
            else:
                self.log(f'Cell lock not confirmed: {msg}', 'warn')
                self.after(0, lambda: self.lock_badge.config(
                    text='Cell lock failed', fg=COLORS['red']))
            self.after(0, self._render_cells)
            self.after(0, lambda: self.sb_var.set(msg))
        threading.Thread(target=worker, daemon=True).start()

    def _do_manual_lock(self):
        earfcn = self._earfcn_of(self.cb_earfcn.get())
        pci    = self.cb_pci.get().strip()
        if not earfcn:
            messagebox.showwarning('Missing', 'Choose a frequency first'); return
        # Whole-frequency lock ('-1' or empty) → frequency lock via lock-freq API
        if pci in ('', '-1'):
            self._lock_frequency(earfcn)
            return
        # Add to table if not already there
        if not any(c.get('earfcn')==earfcn and c.get('pci')==pci for c in self._cells):
            self._cells.append({'type':'Manual','pci':pci,'earfcn':earfcn,
                                 'band':earfcn_to_band(earfcn),'rsrp':'','rsrq':'','sinr':'','cell_id':''})
        self._lock(pci, earfcn)

    def _lock_frequency(self, earfcn):
        """Lock a whole frequency (any sector) via the firmware's lock-freq API."""
        def worker():
            # Same dedupe as _lock — identical freq re-applied within 10s is a no-op
            now = time.time()
            last = getattr(self, '_last_lock', None)
            if last and last[0] == '-1' and last[1] == str(earfcn) and now - last[2] < 10:
                return
            self._last_lock = ('-1', str(earfcn), now)
            try:
                self.api.check_session()
                ok, msg = self.api.lock_frequency(earfcn)
                if not ok:
                    # Stale session or the modem still settling from a net-mode
                    # change (the sweep-restore 'error -1' from the field log) —
                    # wait briefly, then re-auth and retry once
                    time.sleep(3)
                    self.api.check_session()
                    ok, msg = self.api.lock_frequency(earfcn)
                band = earfcn_to_band(earfcn)
                if ok:
                    self.locked_cell = {'pci':'-1','earfcn':earfcn,'band':band}
                    badge = f'🔒  Locked → EARFCN {earfcn}' + (f' (B{band}, any sector)' if band else '')
                    self.after(0, lambda: self.lock_badge.config(text=badge, fg=COLORS['green']))
                    self.after(0, lambda: self.btn_unlock.state(['!disabled']))
                    self.after(0, self._render_cells)
                    self.after(0, lambda: self.sb_var.set(msg))
                    self.log(msg, 'ok')
                else:
                    self.log(msg, 'error')
                    self.after(0, lambda: self.lock_badge.config(text='Frequency lock failed', fg=COLORS['red']))
            except Exception as e:
                self.log(f'Frequency lock error: {e}', 'error')
        threading.Thread(target=worker, daemon=True).start()

    # ── Lock dropdowns ─────────────────────────────────────────
    @staticmethod
    def _earfcn_of(s):
        m = re.match(r'(\d+)', str(s or ''))
        return m.group(1) if m else ''

    def _refresh_lock_combos(self):
        if not hasattr(self, 'cb_earfcn'): return
        freqs, by_freq = [], {}
        for c in self._cells:
            e = str(c.get('earfcn') or '').strip()
            if e and e.isdigit():
                if e not in by_freq: by_freq[e] = []
                if c.get('pci'): by_freq[e].append(str(c.get('pci')).strip())
                if e not in freqs: freqs.append(e)
        items = []
        for e in freqs:
            band = earfcn_to_band(e)
            items.append(f'{e}  (B{band})' if band else e)
        for e in self._preset_earfcns:
            if e not in freqs:
                band = earfcn_to_band(e)
                items.append(f'{e}  (B{band})' if band else e)
        cur = self.cb_earfcn.get()
        cur_e = self._earfcn_of(cur)
        self.cb_earfcn['values'] = items
        if not cur:
            # Default-select the serving cell's frequency
            sv = next((c for c in self._cells if c['type'] == 'Serving'), None)
            se = str(sv.get('earfcn') or '') if sv else ''
            if se:
                m = [i for i in items if self._earfcn_of(i) == se]
                if m: self.cb_earfcn.set(m[0])
        elif cur_e:
            m = [i for i in items if self._earfcn_of(i) == cur_e]
            if m: self.cb_earfcn.set(m[0])
        self._sync_pci_combo()

    def _sync_pci_combo(self):
        earfcn = self._earfcn_of(self.cb_earfcn.get())
        pcips = []
        if earfcn:
            seen = set()
            for c in self._cells:
                if str(c.get('earfcn') or '').strip() == earfcn and c.get('pci'):
                    p = str(c.get('pci')).strip()
                    if p not in seen:
                        seen.add(p); pcips.append(p)
            if not pcips:
                pcips = ['-1']          # no known sector — whole-frequency lock
            elif '-1' not in pcips:
                pcips = pcips + ['-1']  # whole-frequency option always available
        self.cb_pci['values'] = pcips
        cur = self.cb_pci.get()
        if cur not in pcips:
            self.cb_pci.set(pcips[0] if pcips else '')

    def _on_earfcn_pick(self, evt=None):
        self._sync_pci_combo()

    def _set_earfcn_combo(self, earfcn):
        """Set the frequency dropdown to the given EARFCN, adding it if the
        cell table row came from somewhere the combo hasn't seen yet."""
        vals = list(self.cb_earfcn['values']) or []
        m = [i for i in vals if self._earfcn_of(i) == str(earfcn)]
        if m:
            self.cb_earfcn.set(m[0])
            return
        band = earfcn_to_band(earfcn)
        lbl = f'{earfcn}  (B{band})' if band else str(earfcn)
        self.cb_earfcn['values'] = vals + [lbl]
        self.cb_earfcn.set(lbl)

    def _on_cell_select(self, evt=None):
        """Single-click a cell/neighbour row → load its frequency into the
        band/frequency dropdown and its PCI into the PCI dropdown, instead of
        the dropdown defaulting to -1."""
        sel = self.tree_cells.selection()
        if not sel:
            return
        iid = sel[0]
        entry = next((c for c in self._cells
                      if f"{c.get('pci','?_')}_{c.get('earfcn','?')}" == iid), None)
        if entry is None:
            parts = iid.split('_', 1)
            if len(parts) != 2:
                return
            pci, earfcn = parts[0], parts[1]
        else:
            if entry.get('type') == 'PLMN':
                return
            pci, earfcn = str(entry.get('pci','')), str(entry.get('earfcn',''))
        if not earfcn or not earfcn.isdigit():
            return
        self._set_earfcn_combo(earfcn)
        self._sync_pci_combo()
        pci = pci.strip()
        if pci.isdigit() and pci != '-1' and pci in list(self.cb_pci['values']):
            self.cb_pci.set(pci)

    def _copy_browser_snippet(self):
        """Copies the working browser-console dump to the clipboard.
        The modem populates nei_cellid (neighbour cells) DURING its tower sweep —
        i.e. while 🔍 Network Search is running (or right at the start of it),
        then clears it. Best capture: click 🔍 Network Search in the tool (or
        Network Search in the WebUI), then press F12 → Console, paste, Enter."""
        hop = (self.api.ip if getattr(self.api, 'ip', None) else '192.168.8.1')
        script = (
            "/** N5368X neighbour-cell one-shot — paste into DevTools Console while\n"
            " ** a 🔍 Network Search sweep is running (that modem tower scan is what\n"
            " ** fills nei_cellid); run Network Search, then hit Enter on this. */\n"
            "$.ajax({ type:'GET', url:'/api/device/signal',\n"
            "  headers:{ '__RequestVerificationToken':\n"
            "    (typeof g_requestVerificationToken!=='undefined')? g_requestVerificationToken:'',\n"
            "    'X-Requested-With':'XMLHttpRequest' },\n"
            "  dataType:'xml',\n"
            "  success:function(xml){ var o='=== NEIGHBOUR + SERVING CELLS ===\\n';\n"
            "    $(xml).find('*').each(function(){ var v=$(this).text();\n"
            "      if(v && $(this).children().length===0) o+=$(this).prop('tagName')+': '+v+'\\n'; });\n"
            "    console.log(o); },\n"
            "  error:function(xhr){ console.log('Status '+xhr.status+' code '+"
            "$(xhr.responseText).find('code').text()); } });"
        )
        try:
            import subprocess
            subprocess.run(['clip'], input=script, text=True, check=True)
            self.log('Browser snippet copied — check the log / paste anywhere to read it.', 'ok')
            self.after(0, lambda: self.sb_var.set('Neighbour-cell snippet copied to clipboard'))
        except Exception:
            self.log('Could not reach clipboard using clip.exe — snippet logged below.', 'warn')
            self.log(script, 'api')

    def _start_nei_logger(self):
        """Always-on background neighbour-cell watcher. Passively catches
        nei_cellid whenever it appears AND automatically sweeps every band
        (lock band → tower sweep → catch neighbours → restore) so you get
        neighbours for the whole spectrum without touching the UI."""
        if not self.connected or self._nei_logging:
            return
        self._nei_logging = True
        self._nei_logger_stop = threading.Event()
        self._initial_sweep_ok = None
        self.log('🔭 Neighbour logger active — paused for your go/no-go on the initial band sweep (re-run anytime with the 🔭 Sweep All Bands button).', 'ok')
        # Yes/No popup for the automatic initial band/tower sweep (main thread)
        self.after(0, self._ask_initial_sweep)
        threading.Thread(target=self._nei_logger_worker, daemon=True).start()

    def _ask_initial_sweep(self):
        """Popup asked once at each connect: run the automatic band/tower
        sweep or not. Passive neighbour logging keeps running either way."""
        if self._initial_sweep_ok is not None:
            return
        self._initial_sweep_ok = messagebox.askyesno(
            'Initial band sweep',
            'Run the automatic band/tower sweep now?\n\n'
            'It locks every band in turn and runs a tower search to capture '
            'neighbour cells and their SINR across the whole spectrum.\n'
            'It takes ~2-3 minutes and briefly drops the data link while each '
            'band is searched.\n\n'
            "Click No to skip — you can run it anytime with the "
            '🔭 Sweep All Bands button.')
        if not self._initial_sweep_ok:
            self.log('Initial band sweep skipped — use 🔭 Sweep All Bands to run it later.', 'info')

    def _stop_nei_logger(self):
        if not self._nei_logging:
            return
        self._nei_logging = False
        self._nei_logger_stop.set()
        self._initial_sweep_ok = None  # ask again on the next connect

    def _nei_logger_worker(self):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'neighbour_log.txt')
        seen = self._nei_seen  # (band, nei_string) captured this session
        with open(path, 'a', encoding='utf-8') as f:
            f.write(f'\n===== Neighbour logger started {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} =====\n')
            first = True
            while not self._nei_logger_stop.is_set():
                try:
                    self.api.check_session()
                    s = self.api.signal()
                except Exception:
                    time.sleep(2); continue
                self._nei_capture(s, seen, f, '')
                # Sweep every band exactly once, right after connect. After that
                # the modem is left alone — use the 🔭 Sweep All Bands button to
                # re-run it manually instead of auto-re-sweeping (which drops the
                # data link every few minutes).
                if first:
                    first = False
                    # Wait for the connect-time Yes/No answer, then honour it
                    t0 = time.time()
                    while self._initial_sweep_ok is None and time.time() - t0 < 20:
                        time.sleep(0.1)
                    if self._initial_sweep_ok:
                        self._sweep_all_bands(seen, f)
                time.sleep(1.0)
            f.write(f'===== Logger stopped {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} =====\n')
        self.log(f'Neighbour logger log saved to {path}', 'info')

    def _nei_capture(self, s, seen, f, marker):
        """Record whatever neighbours nei_cellid is showing right now, deduped
        per band. marker prefixes the log line (e.g. '[SWEEP B3]')."""
        nei = (s.get('nei_cellid') or '').strip()
        if not nei:
            return False
        band = str(s.get('band') or '').strip()
        key  = (band, nei)
        if key in seen:
            return False
        seen.add(key)
        line = (f'[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] {marker} '
                f'PCI={s.get("pci")} band={s.get("band")} EARFCN={s.get("earfcn")} '
                f'mode={s.get("mode")} RSRP={s.get("rsrp")}dBm SINR={s.get("sinr")}dB '
                f'cell_id={s.get("cell_id")} eNB={s.get("enodeb_id")} TAC={s.get("tac")} '
                f'PLMN={s.get("plmn")} NR={s.get("nrearfcn")} | NEIGHBOURS={nei}')
        f.write(line + '\n')
        f.flush()
        self.log(f'🔭 NEIGHBOURS {marker} {nei} — logged (band {band or "?"})', 'ok')
        # Feed into the cell table so lock dropdowns see them (PCI 0 = empty slot)
        searfcn = str(s.get('earfcn') or '')
        for np in re.findall(r'No\d+\s*:\s*(\d+)', nei):
            if np == '0': continue
            if not any(c.get('type')=='Neighbor' and c.get('pci')==np
                       and c.get('earfcn')==searfcn for c in self._cells):
                self._cells.append({'type':'Neighbor','pci':np,
                                    'earfcn':searfcn,'band':earfcn_to_band(searfcn),
                                    'rsrp':'','rsrq':'','sinr':'','cell_id':''})
        self.after(0, self._render_cells)
        return True

    def _band_of(self, s):
        """Best band attribution for a signal sample: the modem 'band' field,
        else derived from the EARFCN (catches e.g. B28 showing SINR without a
        band tag)."""
        b = str(s.get('band') or '').strip()
        if b.isdigit():
            return b
        e = str(s.get('earfcn') or '').strip()
        if e.isdigit():
            eb = earfcn_to_band(e)
            if eb:
                return str(eb)
        return ''

    def _camped_on(self, band):
        """True if the modem camps on the given band within NEI_SWEEP_RECAMP."""
        t0 = time.time()
        while time.time() - t0 < NEI_SWEEP_RECAMP:
            if self._nei_logger_stop.is_set():
                break
            try:
                if self._band_of(self.api.signal()) == str(band):
                    return True
            except Exception:
                pass
            time.sleep(0.8)
        return False

    def _wait_modem_responsive(self, max_secs):
        """Sleep until a cheap keptalive probe succeeds or the budget elapses
        (used after timeouts, when the modem is still finishing a search)."""
        t0 = time.time()
        while time.time() - t0 < max_secs and not self._nei_logger_stop.is_set():
            try:
                self.api.keepalive()
                return True
            except Exception:
                time.sleep(1)
        return False

    def _note_cell_signal(self, s, band=None):
        """Record the REAL signal telemetry (RSRP/RSRQ/SINR) of the cell the
        modem is currently camped on into its table row. The neighbour
        endpoints (cell-info, signal-advance, …) are 100003-gated on this
        firmware, so nei_cellid neighbours only ever carry a PCI — the one cell
        whose SINR we can actually measure is the camped sector of each band we
        lock during a sweep (or the serving cell during a search). Optional
        band: only record when the sample's band matches, so a failed lock
        doesn't echo the stale serving cell into the new band's row."""
        raw_pci = str(s.get('pci') or '').strip()
        pci = '' if raw_pci in ('', '0') else raw_pci
        if not pci and not (s.get('rsrp') or s.get('sinr')):
            return False
        if band and self._band_of(s) != str(band):
            return False
        band_attr = self._band_of(s) or earfcn_to_band(str(s.get('earfcn') or '').strip())
        if not band_attr:
            return False
        earfcn = str(s.get('earfcn') or '').strip()
        if pci:
            key = f"{pci}_{earfcn}"
            row = next((c for c in self._cells
                        if f"{c.get('pci','?_')}_{c.get('earfcn','?')}" == key), None)
            if row is None:
                row = next((c for c in self._cells
                            if c.get('type') in ('Neighbor','Manual')
                            and str(c.get('pci','')).strip() == pci
                            and str(c.get('band') or '') == band_attr), None)
        else:
            # Some bands (e.g. B28) report real RSRP/SINR but a blank PCI —
            # keep a band-level row so the measured SINR isn't lost. Skip when
            # the living serving cell already owns this band (mid-recamp echo).
            if any(c.get('type') == 'Serving' and str(c.get('band') or '') == band_attr
                   and c.get('pci') for c in self._cells):
                return False
            row = next((c for c in self._cells
                        if c.get('type') in ('Neighbor','Manual')
                        and str(c.get('pci','')).strip() == ''
                        and str(c.get('band') or '') == band_attr), None)
        if row is None:
            row = {'type':'Neighbor','pci':pci,'earfcn':earfcn,
                   'band':band_attr,
                   'rsrp':'','rsrq':'','sinr':'','cell_id':''}
            self._cells.append(row)
        for k in ('rsrp','rsrq','sinr','cell_id'):
            if s.get(k): row[k] = s.get(k)
        return True

    def _sweep_progress_on(self):
        self.sweep_pb.config(value=0, maximum=len(NEI_SWEEP_BANDS))
        self.sweep_lbl_val.config(text='0/{}'.format(len(NEI_SWEEP_BANDS)))

    def _sweep_progress_update(self, done):
        self.sweep_pb.config(value=done)
        self.sweep_lbl_val.config(text='{}/{}'.format(done, len(NEI_SWEEP_BANDS)))

    def _sweep_progress_off(self):
        self.sweep_pb.config(value=0)
        self.sweep_lbl_val.config(text='idle')

    def _best_sinr_cell(self):
        """Cell with the highest real SINR captured so far (sweep/search
        telemetry), or None if nothing was measured."""
        def s(v):
            try: return float(re.sub(r'[^\d\.\-]', '', str(v)))
            except: return -999.0
        cands = [c for c in self._cells if c.get('sinr')]
        return max(cands, key=lambda c: s(c.get('sinr'))) if cands else None

    def _sweep_all_bands(self, seen, f):
        """Search every band for neighbours automatically. The modem reports
        neighbours only for the band it is currently camped on, so: let the
        previous search finish (the modem is busy while it runs — locking too
        early just times out), lock this band with retries, run a tower sweep
        (GET /api/net/plmn-list) that fills nei_cellid, catch whatever appears.
        EVERY band is swept — none skipped — then the original selection is
        restored."""
        if self._sweeping or getattr(self, '_searching', False) or getattr(self, '_ant_sweeping', False):
            return
        if getattr(self, '_optimising', False):
            self.log('Optimiser is busy — skipping band sweep', 'warn'); return
        self._sweeping = True
        self.after(0, lambda: self.sb_var.set('Band sweep: searching every band for neighbours…'))
        self.log('🔭 Band sweep: locking and searching EVERY band (~2-3 min)…', 'ok')
        self.after(0, self._sweep_progress_on)
        try:
            self.api.check_session()
            orig = self.api.net_mode() or {}
            orig_mode = orig.get('NetworkMode') or '03'
            orig_lte  = orig.get('LTEBand')  or '3FFFFFFF'
            orig_nr   = orig.get('NRBand')   or '7FFFFFFFFFFFFFFF'
        except Exception as e:
            self.log(f'Band sweep aborted — could not read current bands: {e}', 'error')
            self._sweeping = False
            return
        # A leftover cell/freq lock (Enable=1/2) pins the modem to its current
        # band — every following band change then returns 100003 (the B1-first,
        # then B3+ 100003 storm seen in the field log). The sweep hops bands via
        # set_net_mode directly, so clear any residual lock BEFORE the first hop.
        try:
            self.api.unlock_cell()
            time.sleep(1)
        except Exception:
            pass
        prev_fire = None
        pinned = []
        try:
            pinned = self._pick_targets(self._fast_targets() or self._ost_targets())
        except Exception:
            pass
        if pinned:
            self.log(f'🔭 Band-sweep DL probe: {len(pinned)} pinned targets', 'info')
        self._band_dl = {}
        try:
            done = 0
            for band in NEI_SWEEP_BANDS:
                if self._nei_logger_stop.is_set():
                    break
                if getattr(self, '_optimising', False):
                    self.log('Optimiser started — stopping band sweep', 'warn'); break
                # Prevent lock timeouts: wait for the previous search to finish
                if prev_fire is not None:
                    prev_fire.join(timeout=180)
                mask = hex(BAND_HEX[band])[2:].upper()
                locked = False
                for attempt in (1, 2, 3):
                    try:
                        # A session that dies mid-sweep (field log) makes every
                        # remaining hop fail — re-auth before each band change so
                        # a stuck session can't veto the rest of the sweep.
                        self.api.check_session()
                        resp = self.api.set_net_mode('03', mask, orig_nr, timeout=45)
                        code = xml_val(resp, 'code')
                        if not code:
                            locked = True
                            break
                        self.log(f'🔭   B{band}: lock code {code} (attempt {attempt})…', 'warn')
                        if code == '100003':
                            # Router busy (previous tower sweep still running) —
                            # give it real settling time instead of instant retries.
                            time.sleep(12)
                        else:
                            self._wait_modem_responsive(15)
                    except Exception as e:
                        self.log(f'🔭   B{band}: lock attempt {attempt} ({str(e).split(chr(10))[0][:60]}) — retrying…', 'warn')
                        self._wait_modem_responsive(15)
                # Re-camp watch — also notices bands that show signal but aren't attached
                camped = self._camped_on(band)
                # ALWAYS run the tower sweep, locked or not
                if not self._nei_logger_stop.is_set():
                    def fire():
                        try: self.api.get('/api/net/plmn-list', timeout=120)
                        except Exception: pass
                    th = threading.Thread(target=fire, daemon=True)
                    th.start()
                    prev_fire = th
                    gained = 0
                    sig_note = ''
                    dl_note = ''
                    t0 = time.time()
                    while time.time() - t0 < NEI_SWEEP_WINDOW:
                        if self._nei_logger_stop.is_set(): break
                        try:
                            s = self.api.signal()
                            # Camped cell on THIS band → real RSRP/RSRQ/SINR
                            self._note_cell_signal(s, band)
                            if not sig_note and self._band_of(s) == str(band):
                                sig_note = (f"PCI={s.get('pci')} RSRP={s.get('rsrp','')}"
                                            f"dBm SINR={s.get('sinr','')}dB")
                            if self._nei_capture(s, seen, f, f'[SWEEP B{band}]'):
                                gained += 1
                        except Exception:
                            pass
                        time.sleep(NEI_SWEEP_POLL)
                    # DL is the only decision metric — measure it AFTER the capture
                    # window: the concurrent plmn-list tower sweep depletes the
                    # modem and made in-window probes read 0 on perfectly healthy
                    # bands. Let that search finish, give the link a moment, probe.
                    if sig_note and pinned:
                        self.log(f'🔭   B{band}: measuring download speed (8s)…', 'info')
                        try:
                            if prev_fire is not None:
                                prev_fire.join(timeout=60)
                            time.sleep(2)
                            _p, d, _u, _i = self._net_speed(8, 0, threads_dl=4, targets=pinned)
                            d = float(d or 0.0)
                            if d > 0:
                                self._band_dl[band] = max(self._band_dl.get(band, 0), d)
                                dl_note = f' DL={d:.1f} Mbps'
                            else:
                                dl_note = ' DL=0 Mbps (no data)'
                        except Exception:
                            dl_note = ' DL=err'
                    state = 'locked' if locked else ('camped' if camped else 'no camp')
                    self.log(f'🔭   ✓ B{band}: {state} — {gained} new capture(s)'
                             + (f' | camped {sig_note}' if sig_note else '')
                             + (dl_note if dl_note else ''), 'ok' if gained else 'warn')
                    self.after(0, lambda b=band: self.sb_var.set(f'Band sweep: B{b} done — see log'))
                done += 1
                self.after(0, lambda v=done: self._sweep_progress_update(v))
        except Exception as e:
            self.log(f'Band sweep error: {e}', 'error')
        finally:
            # Let the last search finish so the restore lock isn't queued behind it
            if prev_fire is not None:
                prev_fire.join(timeout=180)
            for attempt in range(3):
                try:
                    self.api.check_session()
                    self.api.set_net_mode(orig_mode, orig_lte, orig_nr, timeout=45)
                    self.log(f'✅ Band sweep done — restored mode={orig_mode} LTEBand={orig_lte} NRBand={orig_nr or "(auto)"}', 'ok')
                    break
                except Exception as e:
                    if attempt == 2:
                        self.log(f'⚠ Band restore failed after sweep: {e} — check the Band Lock tab', 'error')
                    else:
                        self._wait_modem_responsive(15)
            # A stale lock-freq lock survives a net-mode restore and pins the
            # modem to a single band (making every later band/cell change return
            # 100003). Clear it so the modem is truly free between runs — the
            # auto-lock below then (re)applies a clean lock.
            try:
                self.api.unlock_cell()
            except Exception:
                pass
            self._sweeping = False
            self.after(0, lambda: self.sb_var.set('Band sweep complete — bands restored'))
            self.after(0, self._sweep_progress_off)
            # Let the restore settle — net-mode changes rotate the session and the
            # modem takes a moment to re-attach, so the lock isn't sent stale.
            time.sleep(4)
            # Finish — everything auto, nothing locked. Rank what was measured by
            # real download speed only; the router decides where it sits.
            if self._band_dl:
                order = sorted(self._band_dl.items(), key=lambda kv: -kv[1])
                desc = '   '.join(f'B{b} = {d:.1f} Mbps' for b, d in order)
                self.log(f'🔭 Sweep done — auto kept, nothing locked. Download speed: {desc}', 'ok')
            else:
                self.log('🔭 Sweep done — no band had measurable download; auto kept, nothing locked', 'info')

    def _do_network_search(self):
        if not self.connected:
            self.log('Not connected', 'warn'); return
        # Prevent multiple simultaneous searches
        if getattr(self, '_searching', False):
            self.log('Search already in progress', 'warn'); return
        if getattr(self, '_sweeping', False):
            self.log('Band sweep in progress — the logger is scanning each band', 'warn'); return
        if getattr(self, '_ant_sweeping', False):
            self.log('Antenna sweep in progress', 'warn'); return
        self._searching = True
        self.log('Network search started — scanning all visible towers (~30s)…', 'info')
        self.sb_var.set('Network search in progress (~30s)…')
        self.after(0, lambda: self.btn_net_search.state(['disabled']))
        self.after(0, lambda: self.btn_net_search.config(style='Running.TButton', text='🔍  Searching…'))
        self.after(0, lambda: self.ns_pb.start(12))
        def worker():
            import queue as _q
            result = {}
            def fetch():
                try:
                    self.api.check_session()
                    result['raw'] = self.api.get('/api/net/plmn-list', timeout=120)
                except Exception as e:
                    result['err'] = str(e)
            th = threading.Thread(target=fetch, daemon=True)
            th.start()
            # The modem fills nei_cellid DURING the sweep window (the known
            # trigger) then clears it — poll hard while the search runs.
            seen = set()
            while th.is_alive():
                try:
                    sg = self.api.signal()
                    self._note_cell_signal(sg)
                    nei = (sg.get('nei_cellid','') or '').strip()
                    if nei and nei not in seen:
                        seen.add(nei)
                        self.log(f'🔭 Neighbours captured during search: {nei} '
                                 f'(PCI={sg.get("pci")} {sg.get("band")} EARFCN={sg.get("earfcn")} '
                                 f'RSRP={sg.get("rsrp")}dBm SINR={sg.get("sinr")}dB)', 'ok')
                        for np in re.findall(r'No\d+\s*:\s*(\d+)', nei):
                            if np == '0': continue
                            searfcn = sg.get('earfcn','')
                            if not any(c.get('type')=='Neighbor' and c.get('pci')==np for c in self._cells):
                                self._cells.append({'type':'Neighbor','pci':np,
                                                    'earfcn':searfcn,'band':earfcn_to_band(searfcn),
                                                    'rsrp':'','rsrq':'','sinr':'','cell_id':''})
                        self.after(0, self._render_cells)
                except Exception:
                    pass
                time.sleep(0.5)
            th.join(timeout=125)
            try:
                raw = result.get('raw')
                if not raw:
                    raise Exception(result.get('err') or 'empty response')
                self.log(f'PLMN raw: {raw[:200]}', 'api')
                import xml.etree.ElementTree as ET2
                root   = ET2.fromstring(raw)
                networks = []
                for net in root.findall('.//Network') + root.findall('.//network'):
                    name  = (net.findtext('FullName') or net.findtext('ShortName') or '').strip()
                    plmn  = (net.findtext('Numeric') or '').strip()
                    rat   = (net.findtext('Rat') or '').strip()
                    state = (net.findtext('State') or '').strip()
                    rat_s = {'0':'GSM','2':'WCDMA','7':'LTE','11':'NR'}.get(rat, rat)
                    state_s = {'1':'Available','2':'Current','3':'Forbidden'}.get(state, state)
                    if plmn:
                        networks.append({
                            'type': 'PLMN', 'pci': plmn, 'earfcn': rat_s,
                            'band': '', 'rsrp': state_s, 'rsrq': '', 'sinr': '',
                            'cell_id': name, 'rat_num': rat,
                        })
                        self.log(f'  {name:20s} PLMN={plmn} RAT={rat_s} {state_s}',
                                 'ok' if state_s=='Available' else 'warn')
                if networks:
                    self._cells = [c for c in self._cells if c['type'] != 'PLMN'] + networks
                    self.after(0, self._render_cells)
                    self.after(0, lambda: self.sb_var.set(
                        f'Found {len(networks)} network(s) — ZONG shown if available'))
                else:
                    self.log('No networks found in PLMN list', 'warn')
                    self.after(0, lambda: self.sb_var.set('Network search: no results'))
            except Exception as e:
                self.log(f'Network search failed: {e}', 'error')
                self.after(0, lambda: self.sb_var.set('Network search failed — see log'))
            finally:
                self._searching = False
                self.after(0, lambda: self.btn_net_search.state(['!disabled']))
                self.after(0, lambda: self.btn_net_search.config(style='TButton', text='🔍  Network Search'))
                self.after(0, lambda: self.ns_pb.stop())

            # Neighbour glance — the modem just ran a full sweep, PCIs may be cached
            for _ in range(3):
                try:
                    self.api.keepalive()
                    sg   = self.api.signal()
                    self._note_cell_signal(sg)
                    nei  = sg.get('nei_cellid','') or ''
                    pcis = re.findall(r'No\d+\s*:\s*(\d+)', nei) if nei else []
                    if pcis:
                        searfcn = sg.get('earfcn','')
                        self.log(f'Neighbours after search: PCI {" ".join(pcis)} on EARFCN={searfcn or "?"}', 'ok')
                        for np in pcis:
                            if not any(c.get('type')=='Neighbor' and c.get('pci')==np for c in self._cells):
                                self._cells.append({'type':'Neighbor','pci':np,
                                                    'earfcn':searfcn,'band':earfcn_to_band(searfcn),
                                                    'rsrp':'','rsrq':'','sinr':'','cell_id':''})
                        self.after(0, self._render_cells)
                        break
                except: pass
                time.sleep(3)
        threading.Thread(target=worker, daemon=True).start()

    def _manual_sweep(self):
        """🔭 Sweep All Bands — search every band for neighbours right now."""
        if not self.connected:
            self.log('Not connected', 'warn'); return
        if self._sweeping or getattr(self, '_searching', False):
            self.log('A sweep / network search is already running', 'warn'); return
        self.after(0, lambda: self.btn_band_sweep.state(['disabled']))
        self.after(0, lambda: self.btn_band_sweep.config(style='Running.TButton', text='🔭  Sweeping…'))
        def worker():
            try:
                path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'neighbour_log.txt')
                with open(path, 'a', encoding='utf-8') as f:
                    f.write(f'\n===== Manual band sweep {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} =====\n')
                    self._sweep_all_bands(self._nei_seen, f)
            except Exception as e:
                self.log(f'Manual sweep error: {e}', 'error')
            finally:
                self.after(0, lambda: self.btn_band_sweep.state(['!disabled']))
                self.after(0, lambda: self.btn_band_sweep.config(style='TButton', text='🔭  Sweep All Bands'))
        threading.Thread(target=worker, daemon=True).start()

    def _do_unlock(self):
        def worker():
            try:
                self.api.check_session()
                ok, msg = self.api.unlock_cell()
                self.log(msg, 'ok' if ok else 'error')
            except Exception as e:
                self.log(f'Unlock error: {e}', 'error')
            self.locked_cell = None
            self.after(0, lambda: self.lock_badge.config(text=''))
            self.after(0, lambda: self.btn_unlock.state(['disabled']))
            self.after(0, self._render_cells)
            self.after(0, lambda: self.sb_var.set('Lock removed'))
        threading.Thread(target=worker, daemon=True).start()

    # ── Tab: Band Lock ────────────────────────────────────────
    def _build_tab_bands(self):
        f = self._tab_bands
        tk.Label(f, text='Band Lock', bg=COLORS['bg'],
                 fg=COLORS['text'], font=('Segoe UI',12,'bold')).pack(anchor='w', padx=16, pady=(14,4))
        tk.Label(f, text='Select which LTE bands the router is allowed to use. Uncheck all = use all.',
                 bg=COLORS['bg'], fg=COLORS['muted'], font=('Segoe UI',9)).pack(anchor='w', padx=16)

        lte_frame = tk.LabelFrame(f, text=' LTE Bands ', bg=COLORS['bg'], fg=COLORS['muted'],
                                   font=('Segoe UI',9), bd=1, relief='groove')
        lte_frame.pack(fill='x', padx=16, pady=(12,8))
        self._band_vars = {}
        lte_bands = [1,3,7,8,20,28,32,38,40,41,42]
        for i,b in enumerate(lte_bands):
            var = tk.BooleanVar(value=False)
            self._band_vars[b] = var
            cb = ttk.Checkbutton(lte_frame, text=f'B{b}', variable=var)
            cb.grid(row=i//6, column=i%6, padx=14, pady=6, sticky='w')

        nr_frame = tk.LabelFrame(f, text=' 5G NR Bands ', bg=COLORS['bg'], fg=COLORS['muted'],
                                  font=('Segoe UI',9), bd=1, relief='groove')
        nr_frame.pack(fill='x', padx=16, pady=(0,12))
        self._nr_band_vars = {}
        nr_bands = [1,3,28,41,78,79]
        for i,b in enumerate(nr_bands):
            var = tk.BooleanVar(value=False)
            self._nr_band_vars[b] = var
            cb = ttk.Checkbutton(nr_frame, text=f'n{b}', variable=var)
            cb.grid(row=0, column=i, padx=14, pady=6, sticky='w')

        # Mode selector
        mf = tk.Frame(f, bg=COLORS['bg'])
        mf.pack(fill='x', padx=16, pady=(0,12))
        tk.Label(mf, text='Network Mode', bg=COLORS['bg'], fg=COLORS['muted'],
                 font=('Segoe UI',9)).pack(side='left')
        self.mode_var = tk.StringVar(value='Auto (4G/5G)')
        mode_combo = ttk.Combobox(mf, textvariable=self.mode_var, width=22, state='readonly',
                                   values=['Auto (4G/5G)','4G Only','5G Only','3G Only','Auto (All)'])
        mode_combo.pack(side='left', padx=12)

        btn_row = tk.Frame(f, bg=COLORS['bg'])
        btn_row.pack(fill='x', padx=16, pady=(0,12))
        ttk.Button(btn_row, text='Apply Band Lock', style='Accent.TButton',
                   command=self._apply_bands).pack(side='left', padx=(0,8))
        ttk.Button(btn_row, text='Reset to All Bands', command=self._reset_bands).pack(side='left', padx=(0,8))
        ttk.Button(btn_row, text='Read Current Bands', command=self._read_bands).pack(side='left', padx=(0,8))
        ttk.Button(btn_row, text='🔍 5G Probe', command=self._probe_5g).pack(side='left')
        ttk.Button(btn_row, text='📡 5G Anchor Scan', command=self._scan_5g_anchors).pack(side='left', padx=(8,0))

        # Current mode display
        self.band_status = tk.Label(f, text='', bg=COLORS['bg'],
                                    fg=COLORS['green'], font=('Segoe UI',9))
        self.band_status.pack(anchor='w', padx=16)

    def _apply_bands(self):
        if not self.connected:
            self.log('Not connected', 'warn'); return
        sel_lte = [b for b,v in self._band_vars.items() if v.get()]
        sel_nr  = [b for b,v in self._nr_band_vars.items() if v.get()]
        # Correct NetworkMode codes confirmed from huawei-dongle-api source:
        mode_map = {
            'Auto (4G/5G)': '03',
            '4G Only':       '03',
            '5G Only':       '08',
            '3G Only':       '02',
            '2G Only':       '01',
            'Auto (All)':    '00',
        }
        mode_code = mode_map.get(self.mode_var.get(), '03')

        # Build hex masks
        lte_hex = '7FFFFFFFFFFFFFFF'
        nr_hex  = '7FFFFFFFFFFFFFFF'
        if sel_lte:
            mask = 0
            for b in sel_lte: mask |= BAND_HEX.get(b, 0)
            if mask: lte_hex = hex(mask).upper()[2:]
        if sel_nr:
            mask = 0
            for b in sel_nr: mask |= NR_BAND_HEX.get(b, 0)
            if mask: nr_hex = hex(mask).upper()[2:]

        self.log(f'Applying band lock: mode={mode_code} LTE={lte_hex} NR={nr_hex}', 'info')

        def worker():
            self.api.check_session()
            resp = self.api.set_net_mode(mode_code, lte_hex, nr_hex)
            self.log(f'Band lock response: {resp[:150]}', 'api')
            err  = xml_val(resp, 'code')
            if err:
                self.log(f'Band lock failed: error {err}', 'error')
                self.after(0, lambda: self.sb_var.set(f'Band lock failed: error {err}'))
            else:
                self.log(f'Band lock applied — LTE:{sel_lte or "all"} NR:{sel_nr or "all"}', 'ok')
                self.after(0, lambda: self.sb_var.set('Band lock applied'))
                self.after(0, lambda: self.band_status.config(
                    text=f'✓ LTE {sel_lte or "all"}  NR {sel_nr or "all"}  mode={mode_code}',
                    fg=COLORS['green']))
        threading.Thread(target=worker, daemon=True).start()

    def _reset_bands(self):
        for v in self._band_vars.values(): v.set(False)
        for v in self._nr_band_vars.values(): v.set(False)
        if not self.connected: return
        self.log('Resetting to all bands…', 'info')
        def worker():
            resp = self.api.set_net_mode('00', '7FFFFFFFFFFFFFFF', '7FFFFFFFFFFFFFFF')
            self.log(f'Reset response: {resp[:150]}', 'api')
            err = xml_val(resp, 'code')
            if err:
                self.log(f'Reset failed: error {err}', 'error')
            else:
                self.log('All bands enabled', 'ok')
                self.after(0, lambda: self.sb_var.set('All bands enabled'))
                self.after(0, lambda: self.band_status.config(text='', fg=COLORS['muted']))
        threading.Thread(target=worker, daemon=True).start()

    def _read_bands(self):
        if not self.connected: return
        self.log('Reading current band config from router…', 'info')
        def worker():
            nm      = self.api.net_mode()
            lte_hex = nm.get('LTEBand','')
            nr_hex  = nm.get('NRBand','')
            mode    = nm.get('NetworkMode','')
            self.log(f'Current: NetworkMode={mode} LTEBand={lte_hex} NRBand={nr_hex}', 'api')
            try:
                lte_int = int(lte_hex, 16)
                for b,mask in BAND_HEX.items():
                    self._band_vars[b].set(bool(lte_int & mask))
            except: pass
            try:
                nr_int = int(nr_hex, 16)
                for b,mask in NR_BAND_HEX.items():
                    self._nr_band_vars[b].set(bool(nr_int & mask))
            except: pass
            self.after(0, lambda: self.sb_var.set(f'Bands read: LTE={lte_hex} NR={nr_hex}'))
            self.after(0, lambda: self.band_status.config(
                text=f'Mode={mode}  LTE={lte_hex}  NR={nr_hex}', fg=COLORS['accent']))
        threading.Thread(target=worker, daemon=True).start()

    def _probe_5g(self):
        """Diagnostic probe — reports whether the modem exposes / attaches to a 5G NR channel."""
        if not self.connected:
            self.log('Not connected', 'warn'); return
        self.log('5G probe started…', 'info')
        def worker():
            try:
                self.api.check_session()
                info  = self.api.device_info()
                nm    = self.api.net_mode()
                sig   = self.api.signal()
                fw    = info.get('firmwareversion', info.get('SoftwareVersion',''))
                mode  = nm.get('NetworkMode','')
                nrhex = nm.get('NRBand','')
                nre   = sig.get('nrearfcn','')
                nrs   = sig.get('nrrsrp','')
                self.log(f'── 5G Probe ── firmware {fw}', 'info')
                self.log(f'NetworkMode={mode}  NRBand={nrhex or "(empty)"}', 'api')
                if nre or nrs:
                    nb = nrearfcn_to_band(nre)
                    self.log(f'5G ACTIVE: n{nb or "?"} DL-NR EARFCN={nre or "?"} RSRP={nrs or "?"} dBm', 'ok')
                else:
                    self.log('No 5G/NR channel currently attached (signal has no NR fields)', 'warn')
                if not nrhex:
                    self.log('NRBand mask is EMPTY — this firmware exposes no NR configuration.', 'warn')
                    self.log('To attempt 5G: tick 5G NR bands (e.g. n78) + pick 5G Only on Band Lock, then Apply.', 'info')
                else:
                    try:
                        active = [b for b,m in NR_BAND_HEX.items() if int(nrhex,16) & m]
                    except: active = []
                    self.log(f'NRBand={nrhex} → NR bands: {active or "none of the known masks"}', 'ok')
                self.log('5G probe done.', 'ok')
                self.after(0, lambda: self.sb_var.set('5G probe done — see log'))
            except Exception as e:
                self.log(f'5G probe failed: {e}', 'error')
        threading.Thread(target=worker, daemon=True).start()

    def _scan_5g_anchors(self):
        """Test each supported LTE band as a 4G anchor and report which ones
        reach a 5G NSA carrier (this firmware locks out neighbour-cell APIs,
        so band-by-band probing is the only way to find the 5G mast)."""
        if not self.connected:
            self.log('Not connected', 'warn'); return
        self.log('5G Anchor Scan started — testing each LTE band for an NR anchor…', 'info')
        self.log('(mode=auto incl 5G, one LTE band at a time; ~8 s per band; then restores)', 'info')
        def worker():
            original = None
            try:
                self.api.check_session()
                nm = self.api.net_mode()
                original = (nm.get('NetworkMode','00'), nm.get('NetworkBand','3FFFFFFF'),
                            nm.get('LTEBand',''), nm.get('NRBand',''))
                lte_hex = nm.get('LTEBand','') or '7FFFFFFFFFFFFFFF'
                try: cur = int(lte_hex, 16)
                except: cur = 0x7FFFFFFFFFFFFFFF
                supported = [b for b,m in BAND_HEX.items() if cur & m] or [b for b in BAND_HEX]
                self.log(f'Supported LTE bands on this mask: {supported}', 'api')

                anchors = []
                for b in supported:
                    if not self.connected:
                        self.log('Disconnected — aborting anchor scan', 'warn'); break
                    self.api.check_session()
                    mask = hex(BAND_HEX[b]).upper()[2:]
                    resp = self.api.set_net_mode('00', '3FFFFFFF', mask)
                    if xml_val(resp, 'code'):
                        self.log(f'  B{b}: lock rejected', 'warn'); continue
                    time.sleep(8)
                    sig = self.api.signal()
                    nre = (sig.get('nrearfcn','') or '').strip()
                    nrs = (sig.get('nrrsrp','') or '').strip()
                    lrs = (sig.get('rsrp','') or '').strip()
                    if nre:
                        nb = nrearfcn_to_band(nre) or '?'
                        anchors.append((b, nre, nrs, lrs, nb))
                        self.log(f'  B{b}: 5G HAS ANCHOR  n{nb} NR-EARFCN={nre} NR-RSRP={nrs or "-"}', 'ok')
                    else:
                        self.log(f'  B{b}: no NR attach (LTE RSRP {lrs or "-"})', 'info')

                self.log('── 5G Anchor Scan results ──', 'info')
                if anchors:
                    for b, nre, nrs, lrs, nb in anchors:
                        self.log(f'  5G anchor on LTE B{b}: NR n{nb} EARFCN {nre} RSRP {nrs}', 'ok')
                    def _dbm(v):
                        try: return int((v or '-130').replace('dBm','').strip())
                        except: return -130
                    best = max(anchors, key=lambda a: _dbm(a[2]))
                    self.log(f'Best 5G anchor: LTE B{best[0]} → NR n{best[4]} EARFCN {best[1]} '
                             f'RSRP {best[2]} dBm. Band-lock to B{best[0]} to stay on the 5G mast.', 'ok')
                    self.after(0, lambda: self.sb_var.set(
                        f'5G anchor: LTE B{best[0]} → NR n{best[4]} (RSRP {_dbm(best[2])} dBm)'))
                else:
                    self.log('No LTE band in this area reaches a 5G carrier '
                             '(check 5G coverage / SIM provisioning).', 'warn')
                    self.after(0, lambda: self.sb_var.set('No 5G anchor found on any band'))
            except Exception as e:
                self.log(f'Anchor scan failed: {e}', 'error')
            finally:
                if original:
                    try:
                        self.api.check_session()
                        resp = self.api.set_net_mode(original[0], original[1], original[2] or '7FFFFFFFFFFFFFFF')
                        self.log(f'Restored band config (NetworkMode={original[0]}): '
                                 f"{xml_val(resp,'code') or 'OK'}", 'api')
                    except Exception as e:
                        self.log(f'Restore failed: {e}', 'error')
        threading.Thread(target=worker, daemon=True).start()

    # ── Tab: Device Info ─────────────────────────────────────
    def _build_tab_info(self):
        f = self._tab_info
        top = tk.Frame(f, bg=COLORS['bg'])
        top.pack(fill='x', padx=16, pady=(14,8))
        tk.Label(top, text='Device Information', bg=COLORS['bg'],
                 fg=COLORS['text'], font=('Segoe UI',12,'bold')).pack(side='left')
        ttk.Button(top, text='Refresh', command=self._refresh_info).pack(side='right')
        ttk.Button(top, text='Reboot Router', style='Danger.TButton',
                   command=self._do_reboot).pack(side='right', padx=8)

        self.info_text = scrolledtext.ScrolledText(f, bg=COLORS['surface'],
                                                    fg=COLORS['text'], font=('Consolas',10),
                                                    relief='flat', wrap='word',
                                                    insertbackground=COLORS['text'])
        self.info_text.pack(fill='both', expand=True, padx=16, pady=(0,14))
        self.info_text.config(state='disabled')

    def _refresh_info(self):
        if not self.connected: return
        def worker():
            info   = self.api.device_info()
            plmn   = self.api.current_plmn()
            status = self.api.status()
            traffic= self.api.traffic_stats()
            nm     = self.api.net_mode()

            def fmt_bytes(b):
                try:
                    b = int(b)
                    for u in ['B','KB','MB','GB','TB']:
                        if b < 1024: return f'{b:.1f} {u}'
                        b /= 1024
                except: return b
                return str(b)

            lines = [
                '── Device ─────────────────────────────────',
                f"  Name:         {info.get('devicename','')}",
                f"  Hardware:     {info.get('HardwareVersion','')}",
                f"  Firmware:     {info.get('firmwareversion',info.get('SoftwareVersion',''))}",
                f"  MAC:          {info.get('MacAddress1','')}",
                f"  ICCID:        {info.get('Iccid','')}",
                f"  Uptime:       {info.get('uptime','')}",
                '',
                '── Network ─────────────────────────────────',
                f"  Operator:     {plmn.get('FullName','')} ({plmn.get('ShortName','')})",
                f"  PLMN:         {plmn.get('Numeric','')}",
                f"  RAT:          {plmn.get('Rat','')}",
                f"  WAN IP:       {status.get('WanIPAddress','')}",
                f"  Network Type: {MODE_LABELS.get(status.get('CurrentNetworkType',''), status.get('CurrentNetworkType',''))}",
                '',
                '── Bands ───────────────────────────────────',
                f"  LTE Band Hex: {nm.get('LTEBand','')}",
                f"  NR Band Hex:  {nm.get('NRBand','')}",
                f"  Network Mode: {nm.get('NetworkMode','')}",
                '',
                '── Traffic ─────────────────────────────────',
                f"  Download Rate: {fmt_bytes(traffic.get('CurrentDownloadRate','0'))}/s",
                f"  Upload Rate:   {fmt_bytes(traffic.get('CurrentUploadRate','0'))}/s",
                f"  Total Down:    {fmt_bytes(traffic.get('TotalDownload','0'))}",
                f"  Total Up:      {fmt_bytes(traffic.get('TotalUpload','0'))}",
                f"  Session Time:  {traffic.get('CurrentConnectTime','')} s",
            ]
            text = '\n'.join(lines)
            def update():
                self.info_text.config(state='normal')
                self.info_text.delete('1.0','end')
                self.info_text.insert('end', text)
                self.info_text.config(state='disabled')
            self.after(0, update)
        threading.Thread(target=worker, daemon=True).start()

    def _do_reboot(self):
        if not self.connected: return
        if not messagebox.askyesno('Reboot', 'Reboot the router now?'): return
        def worker():
            self.api.reboot()
            self.after(0, lambda: self.sb_var.set('Reboot command sent'))
        threading.Thread(target=worker, daemon=True).start()

    # ── Tab: System & Diagnostics ─────────────────────────────
    def _build_tab_sys(self):
        f = self._tab_sys
        top = tk.Frame(f, bg=COLORS['bg'])
        top.pack(fill='x', padx=16, pady=(14,8))
        tk.Label(top, text='System & Diagnostics', bg=COLORS['bg'],
                 fg=COLORS['text'], font=('Segoe UI',12,'bold')).pack(side='left')
        ttk.Button(top, text='Refresh', command=self._refresh_sys).pack(side='right')
        ttk.Button(top, text='Check Updates', command=self._sys_check_updates).pack(side='right', padx=8)
        ttk.Button(top, text='Reconnect Net', command=self._sys_reconnect).pack(side='right', padx=8)
        ttk.Button(top, text='Read SMS', command=self._sys_read_sms).pack(side='right', padx=8)

        self.sys_text = scrolledtext.ScrolledText(f, bg=COLORS['surface'],
                                                    fg=COLORS['text'], font=('Consolas',10),
                                                    relief='flat', wrap='word',
                                                    insertbackground=COLORS['text'])
        self.sys_text.pack(fill='both', expand=True, padx=16, pady=(0,14))
        self.sys_text.config(state='disabled')

    def _sys_set_text(self, text):
        self.sys_text.config(state='normal')
        self.sys_text.delete('1.0','end')
        self.sys_text.insert('end', text)
        self.sys_text.config(state='disabled')

    def _sys_check_updates(self):
        if not self.connected: return
        def worker():
            ok = self.api.check_updates()
            msg = 'Firmware check sent — see Settings/Updates page for the result' if ok else 'Check failed'
            self.after(0, lambda: (self.log(msg, 'ok' if ok else 'error'),
                                   self.sb_var.set(msg)))
            self.after(0, self._refresh_sys)
        threading.Thread(target=worker, daemon=True).start()

    def _sys_reconnect(self):
        if not self.connected: return
        def worker():
            ok = self.api.net_reconnect()
            msg = 'WAN reconnected' if ok else 'Reconnect failed'
            self.after(0, lambda: (self.log(msg, 'ok' if ok else 'error'),
                                   self.sb_var.set(msg)))
        threading.Thread(target=worker, daemon=True).start()

    def _sys_read_sms(self):
        if not self.connected: return
        def worker():
            msgs, err = self.api.sms_list()
            if err:
                self.after(0, lambda: (self.log(f'SMS read: {err}', 'warn'),
                                       self.sb_var.set(f'SMS: {err}')))
                return
            joined = '\n'.join(
                f"[{m.get('Date','')}] {m.get('Phone','')}: {m.get('Content','')[:90]}"
                for m in msgs[:20]) or '(box empty)'
            def upd():
                self._sys_set_text(f'── SMS Inbox ({len(msgs)} total) ──\n\n{joined}')
                self.log(f'{len(msgs)} SMS message(s) loaded', 'ok')
            self.after(0, upd)
        threading.Thread(target=worker, daemon=True).start()

    def _refresh_sys(self):
        if not self.connected: return
        def worker():
            api = self.api
            sections = []
            def blk(title, body):
                sections.append(f'── {title} ──────────────────────────────\n{body}')

            dev = api.device_info()
            blk('Device',
                '\n'.join(f"  {k}: {v}" for k, v in dev.items() if v))

            sw = api.module_switch()
            if sw:
                feats = sorted(sw.items())
                blk('Module Feature Switches',
                    '\n'.join(f"  {k:<32s} {'ON' if v == '1' else v}" for k, v in feats))

            dm = api.developer_mode(); dl = api.current_language()
            blk('Developer / Language',
                f"  Developer mode: {dm.get('Enabled','') or dm}\n  Language: {dl.get('Language','') or dl}")

            hl = api.history_login()
            if hl:
                blk('Login History',
                    '\n'.join(f"  {k}: {v}" for k, v in hl.items() if v))

            pins = api.pin_status()
            st = pins.get('pin', {})
            si = pins.get('simlock', {})
            blk('SIM / PIN',
                (f"  PIN: {st.get('PinStatus','')} | SIM state: {st.get('SimState','')}\n"
                 f"  SIM lock: {si.get('LockInfo','') or si}"))

            cr = api.cradle_status()
            if any(v for v in cr.values()):
                blk('Cradle (4G dongle)',
                    '\n'.join(f"  {k}: {v}" for k, v in cr['status'].items() if v)
                    + (f"\n  MAC: {cr.get('mac',{}).get('UsbMacAddress','') or cr.get('mac')}"
                       if cr.get('mac') else ''))

            dh = api.dhcp_info(); sec = api.security_info()
            blk('Network Config (DHCP / Security)',
                f"  DHCP: {dh.get('LanDHCPMode','') or dh}\n"
                f"  Bridge mode: {sec['bridge'].get('Bridgemode','') or sec['bridge']}\n"
                f"  Firewall: {sec['firewall'].get('FirewallSwitch','') or sec['firewall']}")

            wl = api.wlan_statics()
            bs = wl.get('basic', {})
            blk('WLAN (read-only)',
                f"  SSID: {bs.get('Ssid','')} | 2.4G: {bs.get('WifiSsid0','')} "
                f"| 5G: {bs.get('WifiSsid1','')}\n  {bs}")

            lw = api.lan_wan_config(); dp = api.dialup_info(); wp = api.wan_path()
            blk('WAN Path / Dialup / LAN-WAN',
                f"  wan path: {wp}\n  dialup: {dp}\n  lan/wan: {lw}")

            cs = api.csps_state(); sg = api.converged_status(); cn = api.check_notifications()
            blk('CSPS / Converged / Notifications',
                f"  csps: {cs}\n  converged: {sg}\n  notifications: {cn}")

            ms = api.month_statistics(); sd = api.start_date()
            blk('Traffic statistics',
                f"  month: {ms}\n  start date: {sd}")

            sobj = api.system_json('api/system/deviceinfo')
            cap = api.system_json('api/system/devcapacity')
            if sobj:
                import json as _json
                blk('System info (JSON)',
                    _json.dumps(sobj, indent=2)[:2000])
            if cap:
                import json as _json
                blk('Device capability (JSON)', _json.dumps(cap, indent=2)[:1200])

            uc = api.update_config()
            blk('Software update config',
                f"  config: {uc.get('config')}\n  autoupdate: {uc.get('autoupdate')}")

            led = api.led_schedule(); cir = api.circle_led(); trb = api.time_reboot()
            blk('LED / reboot scheduling',
                f"  LED schedule: switch={led.get('ledctrlswitch','')} "
                f"{led.get('starttime','')}-{led.get('endtime','')} "
                f"| circle LED: {cir.get('ledSwitch', cir)}\n"
                f"  Reboot timer: enable={trb.get('enable','')} "
                f"{trb.get('begintime','')}->{trb.get('endtime','')} every "
                f"{trb.get('dayinterval','')}d")

            ut = api.usb_tethering(); am = api.antenna_mode()
            st = am.get('set_type', {}); at = am.get('type', {})
            blk('USB tethering / antenna',
                f"  usb: switch={ut.get('switch') or '-'} state={ut.get('state') or '-'}\n"
                f"  antenna: mode={st.get('antennasettype', st)} "
                f"| type={at.get('antennatype', at)}")

            fl = api.wifi_features(); df = api.dialup_features(); nf = api.net_features()
            blk('Wi-Fi / dialup / net features',
                f"  Dual Wi-Fi: guestwifi={fl.get('guestwifi_enable','')} "
                f"WiFi5G={fl.get('wifi5g_enabled','')} dualchip={fl.get('isdoublechip','')}\n"
                f"  dialup: multi-wan={df.get('multi_wan_enabled','')} "
                f"auto-dial={df.get('auto_dial_enabled','')}\n"
                f"  net: pre-mode={nf.get('net_premode_switch','')} "
                f"lock-freq={nf.get('lock_freq_switch','')}")

            okd = api.onekey_diag()
            blk('One-key diagnostics',
                f"  connection {okd.get('connection_status','')} | SIM {okd.get('sim_status','')} "
                f"| dialup err {okd.get('modemdialup_err','')} | data-limit off {okd.get('datalimit_off','')}")

            vl = api.volte(); vd = api.voice_status()
            blk('Voice state (module-gated)',
                f"  volte={vl}  voip={vd}")

            rawlog = ''
            try:
                rawlog = api.log_info()
                import xml.etree.ElementTree as ET2
                root = ET2.fromstring(rawlog)
                el = root.find('.//LogContent')
                if el is not None:
                    rawlog = el.text or ''
            except Exception:
                pass
            if rawlog and '<' not in rawlog[:200]:
                lines = rawlog.splitlines()
                blk('System log (last lines)', '\n'.join(lines[-40:] if lines else [rawlog]))

            text = '\n\n'.join(sections) or 'No data returned.'
            self.after(0, lambda t=text: (self._sys_set_text(t),
                                          self.log('System info refreshed', 'ok'),
                                          self.sb_var.set('System refresh complete')))
        threading.Thread(target=worker, daemon=True).start()
    # ── Tab: Connected Devices ────────────────────────────────
    def _build_tab_hosts(self):
        f = self._tab_hosts
        top = tk.Frame(f, bg=COLORS['bg'])
        top.pack(fill='x', padx=16, pady=(14,8))
        tk.Label(top, text='Connected Devices', bg=COLORS['bg'],
                 fg=COLORS['text'], font=('Segoe UI',12,'bold')).pack(side='left')
        ttk.Button(top, text='Refresh', command=self._refresh_hosts).pack(side='right')

        cols = ('name','ip','mac','type','active')
        hdrs = ('Hostname','IP Address','MAC Address','Type','Active')
        widths = (180,130,160,80,60)
        frame = tk.Frame(f, bg=COLORS['bg'])
        frame.pack(fill='both', expand=True, padx=16, pady=(0,14))
        self.tree_hosts = ttk.Treeview(frame, columns=cols, show='headings')
        for c,h,w in zip(cols,hdrs,widths):
            self.tree_hosts.heading(c, text=h)
            self.tree_hosts.column(c, width=w)
        sb = ttk.Scrollbar(frame, orient='vertical', command=self.tree_hosts.yview)
        self.tree_hosts.configure(yscrollcommand=sb.set)
        self.tree_hosts.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')

    def _refresh_hosts(self):
        if not self.connected: return
        def worker():
            hosts = self.api.connected_devices()
            def update():
                for r in self.tree_hosts.get_children(): self.tree_hosts.delete(r)
                for h in hosts:
                    self.tree_hosts.insert('', 'end', values=(
                        h.get('HostName', h.get('hostname','')),
                        h.get('IpAddress', h.get('ip','')),
                        h.get('MacAddress', h.get('mac','')),
                        h.get('InterfaceType', h.get('type','')),
                        h.get('Active', h.get('active','')),
                    ))
            self.after(0, update)
        threading.Thread(target=worker, daemon=True).start()

    # ── Tab: Band Optimiser ───────────────────────────────────
    def _build_tab_optimiser(self):
        f = self._tab_opt
        tk.Label(f, text='Band Optimiser', bg=COLORS['bg'],
                 fg=COLORS['text'], font=('Segoe UI',12,'bold')).pack(anchor='w', padx=16, pady=(14,2))
        tk.Label(f, text='Tests each LTE band individually, measures signal quality, and recommends the best combination.',
                 bg=COLORS['bg'], fg=COLORS['muted'], font=('Segoe UI',9)).pack(anchor='w', padx=16)

        btn_row = tk.Frame(f, bg=COLORS['bg'])
        btn_row.pack(fill='x', padx=16, pady=10)
        self.btn_optimise = ttk.Button(btn_row, text='⚡ Auto Optimise Bands',
                                        style='Accent.TButton', command=self._do_optimise)
        self.btn_optimise.pack(side='left', padx=(0,8))
        self.opt_progress = tk.Label(btn_row, text='', bg=COLORS['bg'],
                                      fg=COLORS['muted'], font=('Segoe UI',9))
        self.opt_progress.pack(side='left', padx=8)
        self.opt_pb = ttk.Progressbar(btn_row, mode='determinate',
                                      maximum=len(BAND_HEX), length=150)
        self.opt_pb.pack(side='left', padx=(0,8))

        # Results table
        cols   = ('band','rsrp','rsrq','sinr','score','dl','ul')
        hdrs   = ('Band','RSRP','RSRQ','SINR','DL Mbps','Est DL','Est UL')
        widths = (60,90,80,80,70,90,90)
        frame  = tk.Frame(f, bg=COLORS['bg'])
        frame.pack(fill='both', expand=True, padx=16, pady=(0,8))
        self.tree_opt = ttk.Treeview(frame, columns=cols, show='headings', height=10)
        for c,h,w in zip(cols,hdrs,widths):
            self.tree_opt.heading(c, text=h)
            self.tree_opt.column(c, width=w, anchor='center')
        sb = ttk.Scrollbar(frame, orient='vertical', command=self.tree_opt.yview)
        self.tree_opt.configure(yscrollcommand=sb.set)
        self.tree_opt.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')
        self.tree_opt.tag_configure('best',  background=COLORS['surface2'], foreground=COLORS['green'])
        self.tree_opt.tag_configure('good',  foreground=COLORS['green'])
        self.tree_opt.tag_configure('ok',    foreground=COLORS['yellow'])
        self.tree_opt.tag_configure('bad',   foreground=COLORS['red'])

        self.opt_result = tk.Label(f, text='', bg=COLORS['bg'],
                                    fg=COLORS['green'], font=('Segoe UI',10,'bold'))
        self.opt_result.pack(anchor='w', padx=16, pady=(0,8))

    def _do_optimise(self):
        if not self.connected:
            self.log('Not connected', 'warn'); return
        if getattr(self,'_optimising', False):
            self.log('Optimisation already running', 'warn'); return
        self._optimising = True
        self.btn_optimise.state(['disabled'])
        self.after(0, lambda: self.btn_optimise.config(style='Running.TButton', text='⚡ Optimising…'))
        self.after(0, lambda: self.opt_pb.config(value=0, maximum=len(lte_bands)))
        lte_bands = [b for b in BAND_HEX.keys()]
        self.log(f'Starting band optimisation — testing {len(lte_bands)} bands…', 'info')

        def worker():
            results = []
            targets = []
            try:
                targets = self._pick_targets(self._fast_targets() or self._ost_targets())
            except Exception:
                pass
            if targets:
                self.log(f'Band optimisation — speed probe: {len(targets)} pinned targets', 'info')
            for i, band in enumerate(lte_bands):
                self.after(0, lambda b=band, i=i, n=len(lte_bands): [
                    self.opt_progress.config(text=f'Testing B{b} ({i+1}/{n})…'),
                    self.opt_pb.config(value=i + 1),
                ])
                self.log(f'Testing Band {band}…', 'info')

                # Keep session alive before each band lock
                self.api.keepalive()
                time.sleep(0.5)

                # Verify session before attempting band lock
                self.api.check_session()

                # Lock to this band only
                mask    = BAND_HEX.get(band, 0)
                lte_hex = hex(mask).upper()[2:] if mask else '7FFFFFFFFFFFFFFF'
                resp    = self.api.set_net_mode('03', lte_hex, '7FFFFFFFFFFFFFFF')
                self.log(f'B{band} lock response: {resp[:120]}', 'api')
                if '<error>' in resp:
                    self.log(f'B{band}: could not lock — {xml_val(resp,"code")}', 'warn')
                    continue

                time.sleep(4)  # Wait for band to stabilise
                sig = self.api.signal()
                rsrp = safe_rsrp(sig.get('rsrp',''))
                rsrq = safe_rsrp(sig.get('rsrq',''))
                sinr = safe_rsrp(sig.get('sinr',''))

                if rsrp == -150:  # No signal on this band
                    self.log(f'B{band}: no signal', 'warn')
                    continue

                # Decision metric: measured download speed — and only that.
                dl = 0.0
                if targets:
                    try:
                        _p, d, _u, _i = self._net_speed(8, 0, threads_dl=4, targets=targets)
                        dl = float(d or 0.0)
                    except Exception:
                        dl = 0.0
                score = dl
                results.append({'band': band, 'rsrp': rsrp, 'rsrq': rsrq, 'sinr': sinr, 'score': score})
                self.log(f'B{band}: RSRP={rsrp} RSRQ={rsrq} SINR={sinr} DL={score:.1f} Mbps'
                         + ('' if score > 0 else ' (no data)'), 'ok' if score > 0 else 'warn')

                # Update table live
                self.after(0, lambda r=results: self._render_opt_results(r))

            # Restore all bands
            self.api.set_net_mode('03', '7FFFFFFFFFFFFFFF', '7FFFFFFFFFFFFFFF')

            if any(r['score'] > 0 for r in results):
                best = max(results, key=lambda r: r['score'])
                # Apply best band by download speed
                mask    = BAND_HEX.get(best['band'], 0)
                lte_hex = hex(mask).upper()[2:] if mask else '7FFFFFFFFFFFFFFF'
                self.api.set_net_mode('03', lte_hex, '7FFFFFFFFFFFFFFF')
                msg = f"✓ Best band: B{best['band']} ({best['score']:.1f} Mbps measured) — applied"
                self.log(msg, 'ok')
                self.after(0, lambda: self.opt_result.config(text=msg))
                # Tick the checkbox
                if best['band'] in self._band_vars:
                    for v in self._band_vars.values(): v.set(False)
                    self._band_vars[best['band']].set(True)
            else:
                self.log('No band delivered measurable download speed — bands left auto', 'warn')

            self._optimising = False
            self.after(0, lambda: self.btn_optimise.state(['!disabled']))
            self.after(0, lambda: self.btn_optimise.config(style='TButton', text='⚡ Auto Optimise Bands'))
            self.after(0, lambda: self.opt_progress.config(text='Done'))
            self.after(0, lambda: self.opt_pb.config(value=len(lte_bands)))

        threading.Thread(target=worker, daemon=True).start()

    def _render_opt_results(self, results):
        for r in self.tree_opt.get_children(): self.tree_opt.delete(r)
        sorted_r = sorted(results, key=lambda x: x['score'], reverse=True)
        for i,r in enumerate(sorted_r):
            tag = 'best' if i==0 else ('good' if r['rsrp']>=-90 else 'ok' if r['rsrp']>=-105 else 'bad')
            self.tree_opt.insert('','end', values=(
                f"B{r['band']}", f"{r['rsrp']} dBm", f"{r['rsrq']} dB",
                f"{r['sinr']} dB", f"{r['score']:.1f}", '—', '—'
            ), tags=(tag,))

    def _on_tab_changed(self, evt=None):
        try:
            if self.nb.index('current') == self.nb.index(self._tab_antenna):
                self._refresh_antenna_status()
        except Exception:
            pass

    # ── Tab: Antenna ─────────────────────────────────────────────
    ANT_RESULT_CODES = {
        '0':'OK — combo applied', '9':'scanning…',
        '255':'stopped / no result', '1':'error 1','2':'error 2',
        '3':'error 3','4':'error 4','5':'error 5','6':'error 6',
        '7':'error 7','8':'error 8','10':'error 10','11':'error 11',
        '12':'error 12',
    }

    def _build_tab_antenna(self):
        f = self._tab_antenna
        tk.Label(f, text='Antenna Optimiser', bg=COLORS['bg'],
                 fg=COLORS['text'], font=('Segoe UI',12,'bold')).pack(anchor='w', padx=16, pady=(14,2))
        tk.Label(f, text='Control the 10 antenna combinations and find the strongest one empirically — the WebUI only applies them blind.',
                 bg=COLORS['bg'], fg=COLORS['muted'], font=('Segoe UI',9)).pack(anchor='w', padx=16)

        # ── Status strip ──
        st = tk.LabelFrame(f, bg=COLORS['bg'], fg=COLORS['muted'], text='  Antenna state (live)  ',
                           font=('Segoe UI',9,'bold'))
        st.pack(fill='x', padx=16, pady=(12,4))
        self.ant_status = {}
        row = tk.Frame(st, bg=COLORS['bg']); row.pack(fill='x', padx=10, pady=8)
        for key, title in [('mode','Mode'),('combo','Combination'),('elem','Radiating elements'),
                           ('cycle','Cycle (min)'),('res','Result')]:
            c = tk.Frame(row, bg=COLORS['bg']); c.pack(side='left', padx=(0,22))
            tk.Label(c, text=title, bg=COLORS['bg'], fg=COLORS['muted'],
                     font=('Segoe UI',8)).pack(anchor='w')
            self.ant_status[key] = tk.Label(c, text='—', bg=COLORS['bg'], fg=COLORS['text'],
                                            font=('Segoe UI',10,'bold'))
            self.ant_status[key].pack(anchor='w')
        ttk.Button(row, text='🔄 Refresh', command=self._refresh_antenna_status).pack(side='right')

        # ── Tuning controls ──
        ctl = tk.LabelFrame(f, bg=COLORS['bg'], fg=COLORS['muted'], text='  Tuning (as in the WebUI)  ',
                            font=('Segoe UI',9,'bold'))
        ctl.pack(fill='x', padx=16, pady=4)
        self.ant_mode_var = tk.StringVar(value='1')
        inner = tk.Frame(ctl, bg=COLORS['bg']); inner.pack(anchor='w', padx=10, pady=8)
        tk.Radiobutton(inner, text='Fixed combo (1–10) — recommended', value='1',
                       variable=self.ant_mode_var, bg=COLORS['bg'], fg=COLORS['text'],
                       selectcolor=COLORS['surface'], activebackground=COLORS['bg'],
                       activeforeground=COLORS['accent']).pack(anchor='w')
        tk.Radiobutton(inner, text='Auto-scan mode (SelectMode 0)', value='0',
                       variable=self.ant_mode_var, bg=COLORS['bg'], fg=COLORS['text'],
                       selectcolor=COLORS['surface'], activebackground=COLORS['bg'],
                       activeforeground=COLORS['accent']).pack(anchor='w')
        c2 = tk.Frame(ctl, bg=COLORS['bg']); c2.pack(anchor='w', padx=10, pady=(0,8))
        tk.Label(c2, text='Cycle (1–720 min):', bg=COLORS['bg'], fg=COLORS['text'],
                 font=('Segoe UI',9)).pack(side='left')
        self.ant_cycle_var = tk.StringVar(value='72')
        ttk.Spinbox(c2, from_=1, to=720, width=6, textvariable=self.ant_cycle_var).pack(side='left', padx=6)
        tk.Label(c2, text='Combo (1–10):', bg=COLORS['bg'], fg=COLORS['text'],
                 font=('Segoe UI',9)).pack(side='left', padx=(16,4))
        self.ant_index_var = tk.StringVar(value='1')
        ttk.Spinbox(c2, from_=1, to=10, width=6, textvariable=self.ant_index_var).pack(side='left', padx=6)
        ttk.Button(c2, text='▶ Start Antenna Scan', command=self._do_antenna_scan).pack(side='left', padx=(18,6))
        ttk.Button(c2, text='✓ Apply Combo', command=self._do_antenna_apply).pack(side='left', padx=6)
        ttk.Button(c2, text='◼ Stop', command=self._do_antenna_stop).pack(side='left', padx=6)
        self.ant_action_lbl = tk.Label(ctl, text='', bg=COLORS['bg'], fg=COLORS['yellow'],
                                       font=('Segoe UI',9,'bold'))
        self.ant_action_lbl.pack(anchor='w', padx=10, pady=(0,8))

        # ── Hidden improvement: exhaustive combo sweep ──
        sw = tk.LabelFrame(f, bg=COLORS['bg'], fg=COLORS['muted'],
                           text='  Combo sweep — measure every combination (hidden capability)  ',
                           font=('Segoe UI',9,'bold'))
        sw.pack(fill='both', expand=True, padx=16, pady=4)
        btn_row = tk.Frame(sw, bg=COLORS['bg']); btn_row.pack(anchor='w', padx=10, pady=6)
        self.btn_ant_sweep = ttk.Button(btn_row, text='📶 Sweep Antenna Combos 1–10',
                                        style='Accent.TButton', command=self._sweep_antenna_combos)
        self.btn_ant_sweep.pack(side='left', padx=(0,8))
        self.ant_apply_best = tk.BooleanVar(value=True)
        tk.Checkbutton(btn_row, text='Apply best combo at end', variable=self.ant_apply_best,
                       bg=COLORS['bg'], fg=COLORS['text'], selectcolor=COLORS['surface'],
                       activebackground=COLORS['bg'], activeforeground=COLORS['accent'],
                       font=('Segoe UI',9)).pack(side='left', padx=(6,16))
        self.ant_progress = tk.Label(btn_row, text='', bg=COLORS['bg'], fg=COLORS['muted'],
                                     font=('Segoe UI',9))
        self.ant_progress.pack(side='left', padx=8)
        self.ant_pb = ttk.Progressbar(btn_row, mode='determinate', maximum=10, length=150)
        self.ant_pb.pack(side='left', padx=(0,8))

        cols   = ('combo','elem','rsrp','rsrq','cqi','ismr','mcs','dl','ul')
        hdrs   = ('Combo','Elements','RSRP','RSRQ','CQI','SINR≈','MCS','DL Mbps','UL Mbps')
        widths = (60,90,80,70,55,80,55,95,95)
        frame  = tk.Frame(sw, bg=COLORS['bg'])
        frame.pack(fill='both', expand=True, padx=10, pady=(0,4))
        self.tree_ant = ttk.Treeview(frame, columns=cols, show='headings', height=6)
        for c,h,w in zip(cols,hdrs,widths):
            self.tree_ant.heading(c, text=h)
            self.tree_ant.column(c, width=w, anchor='center')
        sb = ttk.Scrollbar(frame, orient='vertical', command=self.tree_ant.yview)
        self.tree_ant.configure(yscrollcommand=sb.set)
        self.tree_ant.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')
        self.tree_ant.tag_configure('best', background=COLORS['surface2'], foreground=COLORS['green'])
        self.tree_ant.tag_configure('good', foreground=COLORS['green'])
        self.tree_ant.tag_configure('ok',   foreground=COLORS['yellow'])
        self.tree_ant.tag_configure('bad',  foreground=COLORS['red'])
        self.ant_result_lbl = tk.Label(sw, text='', bg=COLORS['bg'], fg=COLORS['green'],
                                       font=('Segoe UI',10,'bold'))
        self.ant_result_lbl.pack(anchor='w', padx=10, pady=(0,8))

        # ── Rotation tracker (hidden capability) ──
        rot = tk.LabelFrame(f, bg=COLORS['bg'], fg=COLORS['muted'],
                            text='  Rotation tracker — live ≈SINR (from CQI) while you turn the antenna  ',
                            font=('Segoe UI',9,'bold'))
        rot.pack(fill='x', padx=16, pady=(4,10))
        rrow = tk.Frame(rot, bg=COLORS['bg']); rrow.pack(anchor='w', padx=10, pady=6)
        ttk.Button(rrow, text='🧭 Start tracking (60s)', command=self._toggle_rotate_track).pack(side='left')
        self.ant_rot_lbl = tk.Label(rrow, text='peak ≈SINR —', bg=COLORS['bg'], fg=COLORS['muted'],
                                    font=('Segoe UI',10,'bold'))
        self.ant_rot_lbl.pack(side='left', padx=12)

    def _refresh_antenna_status(self):
        if not getattr(self, 'connected', False) or self.api is None:
            return
        def worker():
            try:
                c = self.api.antenna_config() or {}
                r = self.api.antenna_select_result() or {}
            except Exception:
                return
            self.after(0, lambda: self._ant_render(c, r))
        threading.Thread(target=worker, daemon=True).start()

    def _ant_render(self, c, r):
        mode = c.get('SelectMode','')
        self.ant_status['mode'].config(
            text=('Auto scan' if mode == '0' else 'Fixed combo' if mode == '1' else f'Mode {mode}'))
        self.ant_status['combo'].config(text=c.get('CombIndex','—') or '—')
        self.ant_status['elem'].config(text=c.get('SelectIndex','—') or '—')
        self.ant_status['cycle'].config(text=c.get('SelectCycle','—') or '—')
        res = r.get('Result','')
        self.ant_status['res'].config(
            text=self.ANT_RESULT_CODES.get(res, f'Result {res}'),
            fg=COLORS['green'] if res == '0' else COLORS['yellow'] if res == '9'
               else COLORS['red'] if res not in ('','0') else COLORS['muted'])
        try:
            self.ant_mode_var.set('0' if mode == '0' else '1')
        except Exception:
            pass

    def _do_antenna_apply(self):
        if not self.connected:
            self.log('Not connected', 'warn'); return
        try:
            idx = int(self.ant_index_var.get())
        except Exception:
            self.log('Combo index must be 1–10', 'warn'); return
        if not 1 <= idx <= 10:
            self.log('Combo index must be 1–10', 'warn'); return
        mode = self.ant_mode_var.get()
        self.log(f'📡 Applying antenna combo {idx} (mode {"auto" if mode=="0" else "fixed"})…', 'info')
        def worker():
            try:
                self.api.check_session()
                ok, body = self.api.antenna_apply(mode=mode, index=idx, action=0, timeout=20)
                self.log(f'📡 Combo {idx} apply → {"OK" if ok else body[:80]}',
                         'ok' if ok else 'error')
                if ok:
                    time.sleep(2)
                    self._refresh_antenna_status()
            except Exception as e:
                self.log(f'📡 Antenna apply error: {e}', 'error')
        threading.Thread(target=worker, daemon=True).start()

    def _do_antenna_scan(self):
        if not self.connected:
            self.log('Not connected', 'warn'); return
        try:
            cyc = int(self.ant_cycle_var.get())
        except Exception:
            self.log('Cycle must be 1–720', 'warn'); return
        if not 1 <= cyc <= 720:
            self.log('Cycle must be 1–720', 'warn'); return
        self.log(f'📡 Starting one-shot antenna tuning round (scans combos, keeps best)…', 'info')
        self.ant_action_lbl.config(text='Scanning…', fg=COLORS['yellow'])
        def worker():
            try:
                self.api.check_session()
                # Verified live: SelectMode=0 + ActionMode=1 (WebUI auto-scan) is
                # rejected with error code 1 on this firmware. A real tuning round
                # starts with SelectMode=1 + ActionMode=1 from the current combo.
                cfg = self.api.antenna_config() or {}
                cur = int(cfg.get('CombIndex') or 1)
                ok, body = self.api.antenna_apply(mode='1', cycle=cyc, index=cur,
                                                  action=1, timeout=25)
                if not ok:
                    self.log(f'📡 Scan start failed: {body[:100]}', 'error')
                    self.after(0, lambda: self.ant_action_lbl.config(text='Start failed', fg=COLORS['red']))
                    return
                self.log('📡 Scan round running — polling for the router\u2019s best combo…', 'info')
                # Poll the result like the WebUI (every 2s, up to 5 min)
                started = time.time()
                while time.time() - started < 300:
                    if getattr(self, '_ant_scan_stop', False):
                        self._ant_scan_stop = False
                        self.api.antenna_apply(mode='1', action=2, timeout=15)
                        self.log('📡 Scan round stopped by user', 'warn')
                        break
                    time.sleep(2)
                    r = self.api.antenna_select_result() or {}
                    res = r.get('Result','')
                    if res in ('', '9'):
                        continue
                    if res == '0':
                        self.log(f"📡 Scan round done → best combo {r.get('CombIndex')} "
                                 f"elements {r.get('SelectIndex')}", 'ok')
                        self.after(0, lambda: self.ant_action_lbl.config(
                            text='Scan done — combo applied', fg=COLORS['green']))
                        self._refresh_antenna_status()
                        return
                    self.log(f"📡 Scan round result {res}: {self.ANT_RESULT_CODES.get(res,res)}", 'warn')
                    break
                else:
                    self.log('📡 Scan round timed out', 'warn')
            except Exception as e:
                self.log(f'📡 Auto-scan error: {e}', 'error')
        self._ant_scan_stop = False
        threading.Thread(target=worker, daemon=True).start()

    def _do_antenna_stop(self):
        self._ant_scan_stop = True
        def worker():
            try:
                self.api.check_session()
                self.api.antenna_apply(mode='1', action=2, timeout=15)
                self.log('📡 Antenna scan stop command sent', 'info')
            except Exception as e:
                self.log(f'📡 Stop error: {e}', 'error')
        threading.Thread(target=worker, daemon=True).start()

    def _clear_tree(self, tree):
        for i in tree.get_children(): tree.delete(i)

    def _ant_measure(self, idx, targets=None):
        """Apply combo idx (fixed), verify the modem APPLIED it, then phase out
        the re-tune transient and report the settled (locked) quality. The
        quality axis is CQI + negotiated DL MCS (+ RSRQ + DL/UL throughput):
        we skip the first ANT_SOAK_S seconds, wait for ANT_STABLE_N consecutive
        samples with CQI within ANT_CQI_TOL and MCS within ANT_MCS_TOL, and
        median the settled tail. 'SINR≈' is a CQI-derived estimate — the
        firmware's raw device/signal SINR is bogus-low (see ANT constants).
        `targets` pins the speed-test server set so combos compare fairly."""
        ok = False
        for _ in range(2):
            ok, _b = self.api.antenna_apply(mode='1', index=idx, action=0, timeout=15)
            if ok:
                break
            time.sleep(1)
        if not ok:
            return {'combo': idx, 'elem': '', 'rsrp': -150, 'rsrq': -150, 'cqi': 0,
                    'mcs': 0, 'sinr': -150, 'dl': '—', 'ul': '—', 'settle_s': 0}
        # Phase 1 — confirm the modem actually switched to combo idx.
        applied = False
        for _ in range(20):
            if str(self.api.antenna_config().get('CombIndex')) == str(idx):
                applied = True
                break
            time.sleep(0.5)
        if not applied:
            cfg = self.api.antenna_config() or {}
            return {'combo': idx, 'elem': cfg.get('SelectIndex', ''), 'rsrp': -150,
                    'rsrq': -150, 'cqi': 0, 'mcs': 0, 'sinr': -150,
                    'dl': '—', 'ul': '—', 'settle_s': -1}

        # Phase 2 — soak past the transient, then wait for CQI/MCS stability.
        rsrp_a, rsrq_a, cqi_a, mcs_a = [], [], [], []
        t0 = time.time()
        stable_tail = False
        while time.time() - t0 < ANT_SETTLE_MAX_S:
            time.sleep(ANT_SAMPLE_S)
            try:
                s = self.api.signal()
                r  = safe_rsrp(s.get('rsrp', ''))
                q  = safe_rsrp(s.get('rsrq', ''))
                c  = int(s.get('cqi0') or 0)
                m  = int(s.get('mcs') or 0)
                if r <= -150:
                    continue
                rsrp_a.append(r); rsrq_a.append(q)
                cqi_a.append(c);  mcs_a.append(m)
            except Exception:
                pass
            el = time.time() - t0
            n = ANT_STABLE_N
            if el < ANT_SOAK_S or len(cqi_a) < n:
                continue
            last_c = cqi_a[-n:]
            last_m = mcs_a[-n:]
            if max(abs(x - last_c[0]) for x in last_c[1:]) <= ANT_CQI_TOL and \
               max(abs(x - last_m[0]) for x in last_m[1:]) <= ANT_MCS_TOL:
                stable_tail = True
                break
        # Median of the settled tail (post-stability samples, or last 3 if we
        # never confirmed stability — at least the worst-case window is bounded).
        medf = lambda xs: round(sorted(xs)[len(xs) // 2], 1) if xs else -150
        medi = lambda xs: sorted(xs)[len(xs) // 2] if xs else 0
        tail = lambda xs: xs[-ANT_STABLE_N:] if stable_tail else xs[-3:]
        rsrp = medf(rsrp_a) if rsrp_a else -150
        rsrq = medf(rsrq_a) if rsrq_a else -150
        cqi  = medi(tail(cqi_a))
        mcs  = medi(tail(mcs_a))
        sinr = CQI2SINR.get(cqi, 0) if cqi else -150
        settle_s = round(time.time() - t0, 1)

        dl = ul = '—'
        if ANT_DL_SEC or ANT_UL_SEC:
            try:
                _, dl_m, ul_m, _ = self._net_speed(ANT_DL_SEC, ANT_UL_SEC,
                                                   threads_dl=3, threads_ul=2,
                                                   targets=targets)
                dl = f'{dl_m:.1f}' if dl_m is not None else '—'
                ul = f'{ul_m:.1f}' if ul_m is not None else '—'
            except Exception:
                pass
        cfg = self.api.antenna_config() or {}
        return {'combo': idx, 'elem': cfg.get('SelectIndex', ''), 'rsrp': rsrp,
                'rsrq': rsrq, 'cqi': cqi, 'mcs': mcs, 'sinr': sinr,
                'dl': dl, 'ul': ul, 'settle_s': settle_s}

    def _render_ant_results(self, results):
        for r in self.tree_ant.get_children(): self.tree_ant.delete(r)
        def mps(r, k):
            try: return float(r.get(k, '—'))
            except Exception: return -1
        ordered = sorted(enumerate(results),
                         key=lambda t: (mps(t[1], 'dl'), t[1]['cqi'], mps(t[1], 'ul')),
                         reverse=True)
        best_idx = ordered[0][0] if ordered else None
        for i, r in enumerate(results):
            tag = 'best' if i == best_idx else ('good' if r['cqi'] >= 8 else 'ok' if r['cqi'] >= 4 else 'bad')
            self.tree_ant.insert('','end', values=(
                f"Combo {r['combo']}", r['elem'],
                f"{round(r['rsrp'])} dBm" if r['rsrp'] > -150 else '—',
                f"{round(r['rsrq'])} dB"  if r['rsrq'] > -150 else '—',
                r['cqi'] if r['cqi'] else '—',
                f"{round(r['sinr'])} dB"  if r['sinr'] > -150 else '—',
                r['mcs'] if r['mcs'] else '—',
                r['dl'], r['ul'],
            ), tags=(tag,))

    def _sweep_antenna_combos(self):
        if not self.connected:
            self.log('Not connected', 'warn'); return
        if getattr(self, '_ant_sweeping', False):
            self.log('Antenna sweep already running', 'warn'); return
        if getattr(self, '_sweeping', False):
            self.log('Band sweep in progress — finish it first', 'warn'); return
        if getattr(self, '_optimising', False):
            self.log('Band optimiser busy — finish it first', 'warn'); return
        self._ant_sweeping = True
        self._ant_sweep_stop = threading.Event()
        self.btn_ant_sweep.state(['disabled'])
        self.after(0, lambda: self.btn_ant_sweep.config(style='Running.TButton', text='📶 Sweeping…'))
        self.after(0, lambda: self.ant_pb.config(value=0))
        self._clear_tree(self.tree_ant)
        self.ant_result_lbl.config(text='')
        self.log('📶 Antenna combo sweep: measuring combos 1–10 (each briefly re-tunes the antenna)…', 'ok')

        def worker():
            orig = {}
            try:
                orig = self.api.antenna_config() or {}
            except Exception:
                pass
            # Pin ONE speed-test server set for the whole sweep so every combo
            # is measured against the same targets — per-combo re-discovery was
            # hitting different fast.com OCAs and producing bimodal, unfair DL
            # numbers (combo 3 won on CQI yet showed ~7 Mbps vs ~30 on others).
            targets = []
            try:
                raw = self._fast_targets() or self._ost_targets()
                targets = self._pick_targets(raw) if raw else []
                if targets:
                    self.log(f'📶 Sweep speed test: {len(targets)} pinned targets', 'info')
                else:
                    self.log('📶 Sweep speed test: no targets', 'warn')
            except Exception:
                pass
            results = []
            try:
                for n in range(1, 11):
                    if self._ant_sweep_stop.is_set():
                        self.log('📶 Combo sweep stopped', 'warn')
                        break
                    self.after(0, lambda n=n: [
                        self.ant_progress.config(text=f'Testing combo {n}/10…'),
                        self.ant_pb.config(value=n),
                    ])
                    try:
                        res = self._ant_measure(n, targets=targets or None)
                        results.append(res)
                        self.log(f'📶 Combo {n}: elements {res["elem"] or "?"} '
                                 f'CQI={res["cqi"]} MCS={res["mcs"]} RSRP={res["rsrp"]}dBm '
                                 f'RSRQ={res["rsrq"]}dB SINR≈{res["sinr"]}dB '
                                 f'(locked in {res["settle_s"]}s)'
                                 + (f' DL={res["dl"]}' if res['dl'] != '—' else ''), 'ok')
                    except Exception as e:
                        self.log(f'📶 Combo {n} failed: {e}', 'warn')
                    self.after(0, lambda rs=results: self._render_ant_results(rs))
            finally:
                self._ant_sweeping = False
                self.after(0, lambda: self.btn_ant_sweep.state(['!disabled']))
                self.after(0, lambda: self.btn_ant_sweep.config(style='TButton', text='📶 Sweep Antenna Combos 1–10'))
                self.after(0, lambda: self.ant_progress.config(text=''))
                self.after(0, lambda: self.ant_pb.config(value=0))
            if not results:
                self.after(0, lambda: self.ant_result_lbl.config(
                    text='No measurements — check connection', fg=COLORS['red']))
                return
            def _mps(r, k):
                """DL/UL Mbps string → number for ranking; '—' sorts last."""
                try:
                    return float(r.get(k, '—'))
                except Exception:
                    return -1
            best = max(results, key=lambda r: _mps(r, 'dl'))
            self.log(f"📶 Best combo → #{best['combo']} (elements {best['elem'] or '?'}) "
                     f"DL {best['dl']} Mbps CQI {best['cqi']} SINR≈{best['sinr']}dB", 'ok')
            if self.ant_apply_best.get() and not self._ant_sweep_stop.is_set():
                ok, body = self.api.antenna_apply(mode='1', index=best['combo'], action=0, timeout=20)
                msg = f"✓ Best combo {best['combo']} applied (DL {best['dl']} Mbps CQI {best['cqi']})"
                self.log(f'📶 {msg}', 'ok' if ok else 'warn')
                if ok:
                    msg += ' — keep it? use ◼/Restore to revert'
                self.after(0, lambda m=msg: self.ant_result_lbl.config(text=m, fg=COLORS['green']))
                self._refresh_antenna_status()
            else:
                self.after(0, lambda: self.ant_result_lbl.config(
                    text=f"Best combo #{best['combo']} — not applied (apply manually)", fg=COLORS['green']))

        threading.Thread(target=worker, daemon=True).start()

    def _toggle_rotate_track(self):
        if getattr(self, '_rotating', False):
            self._rotating = False
            self.log('🧭 Rotation tracker stopped', 'info')
            return
        if not self.connected:
            self.log('Not connected', 'warn'); return
        self._rotating = True
        self._rot_peak = -150
        self.log('🧭 Rotation tracker: 60s of live signal quality (~SINR from CQI) '
                 'while you turn the antenna. Rotate slowly — the big swings show '
                 'the best angle.', 'info')
        def worker():
            end = time.time() + 60
            while self._rotating and time.time() < end:
                try:
                    s = self.api.signal()
                    cqi = int(s.get('cqi0') or 0)
                    sinr = CQI2SINR.get(cqi, 0) or -150
                    self._rot_peak = max(self._rot_peak, sinr)
                    self.after(0, lambda s=sinr: self.ant_rot_lbl.config(
                        text=f'now {s}dB   peak {self._rot_peak}dB', fg=COLORS['green']))
                except Exception:
                    pass
                time.sleep(2)
            self._rotating = False
            self.log(f"🧭 Tracker done — peak SINR {self._rot_peak}dB at this position", 'ok')
        threading.Thread(target=worker, daemon=True).start()

    def _fast_targets(self):
        """Discovery — fast.com v2 JSON API. Returns a list of Netflix OCA
        download/upload target URLs. If the embedded token is rejected, scrape a
        fresh one from fast.com's JS bundle."""
        toks = [FAST_TOKEN]
        fresh = self._scrape_fast_token()
        if fresh and fresh != FAST_TOKEN:
            toks.append(fresh)
        for tok in toks:
            try:
                r = requests.get(
                    'https://api.fast.com/netflix/speedtest/v2?https=true&token=%s&urlCount=5' % tok,
                    timeout=12)
                if r.status_code == 200:
                    urls = [x['url'] for x in r.json().get('targets', []) if x.get('url')]
                    if urls:
                        return urls
            except Exception:
                continue
        return []

    def _scrape_fast_token(self):
        try:
            html = requests.get('https://fast.com/', timeout=12).text
            m = re.search(r'src="([^"]*app-[^"]+\.js[^"]*)"', html)
            if not m:
                return None
            js = requests.get(urljoin('https://fast.com/', m.group(1)), timeout=12).text
            m = re.search(r'"token"\s*:\s*"([A-Za-z0-9=_\-]+)"', js) or \
                re.search(r'token\s*=\s*"([A-Za-z0-9=_\-]+)"', js)
            return m.group(1) if m else None
        except Exception:
            return None

    def _ost_targets(self):
        """OpenSpeedTest fallback — static HTTP GET endpoints."""
        for base, dlp, _ulp in OST_SERVERS:
            try:
                r = requests.get(base + dlp, stream=True, timeout=8)
                if r.status_code == 200:
                    return [base + dlp]
            except Exception:
                continue
        return []

    def _pick_targets(self, urls, probe_seconds=3, probe_threads=2, keep=3,
                      floor=4.0, keep_ratio=0.30):
        """Rank download targets by throughput and keep only the good ones.
        fast.com's OCA pool is negotiated fresh per session and can include dud
        nodes (e.g. Warsaw ~0.6 Mbps vs Singapore ~40-55 Mbps); pooling all of
        them would drag any average down and misrank antenna combos. The single
        best target is always kept regardless of the threshold."""
        if not urls or len(urls) == 1:
            return urls
        scored = []
        for u in urls:
            try:
                m = self._speed_dl([u], probe_seconds, probe_threads)
            except Exception:
                m = 0.0
            scored.append((m, u))
        scored.sort(reverse=True)
        best = scored[0][0]
        picked = [u for m, u in scored if m >= floor and m >= keep_ratio * best]
        if not picked:
            picked = [scored[0][1]]
        return picked[:keep]

    @staticmethod
    def _range_url(url, n):
        p, sep, q = url.partition('?')
        return '%s/range/0-%d%s%s' % (p, n, sep, q)

    def _speed_ping(self, url):
        try:
            t0 = time.time()
            requests.get(self._range_url(url, 0), timeout=8)
            return int((time.time() - t0) * 1000)
        except Exception:
            return None

    def _speed_dl(self, urls, seconds=8, threads=4):
        counters = []
        lock = threading.Lock()
        def worker(url):
            s = requests.Session()
            n = 0
            end = time.time() + seconds
            while time.time() < end:
                try:
                    with s.get(url, stream=True, timeout=10) as r:
                        if r.status_code == 200:
                            for chunk in r.iter_content(262144):
                                n += len(chunk)
                                if time.time() >= end:
                                    break
                except Exception:
                    time.sleep(0.4)
            with lock:
                counters.append(n)
        ts = [threading.Thread(target=worker, args=(urls[i % len(urls)],))
              for i in range(threads)]
        t0 = time.time()
        for t in ts: t.start()
        for t in ts: t.join()
        el = max(time.time() - t0, 0.1)
        return sum(counters) * 8 / 1e6 / el

    def _speed_ul(self, urls, seconds=5, threads=3):
        counters = []
        lock = threading.Lock()
        blob = os.urandom(1 << 20)
        def worker(url):
            s = requests.Session()
            n = 0
            end = time.time() + seconds
            while time.time() < end:
                try:
                    r = s.post(url, data=blob, timeout=12)
                    if r.status_code == 200:
                        n += len(blob)
                except Exception:
                    time.sleep(0.4)
            with lock:
                counters.append(n)
        ts = [threading.Thread(target=worker, args=(urls[i % len(urls)],))
              for i in range(threads)]
        t0 = time.time()
        for t in ts: t.start()
        for t in ts: t.join()
        el = max(time.time() - t0, 0.1)
        return sum(counters) * 8 / 1e6 / el

    def _net_speed(self, dl_seconds=8, ul_seconds=5, threads_dl=4, threads_ul=3, targets=None, prune=False):
        """Full speed test. Provider auto-detect: fast.com → OpenSpeedTest.
        Pass `targets` (a pre-discovered target URL list) to reuse the SAME
        servers across repeated tests — the antenna sweep pins one set per run
        so combos are compared apples-to-apples instead of hitting different
        fast.com OCAs each time. `prune=True` (standalone button) ranks the
        freshly discovered targets first so dud OCAs don't drag the reading.
        Returns (provider, dl, ul|None, ping|None)."""
        if targets:
            urls, provider = list(targets), 'fast.com(static)'
        else:
            urls = self._fast_targets()
            provider = 'fast.com'
            if prune and len(urls) > 1:
                urls = self._pick_targets(urls)
        if not urls:
            urls = self._ost_targets()
            provider = 'OpenSpeedTest'
            if not urls:
                raise RuntimeError('no speed-test server reachable (fast.com and OpenSpeedTest both failed)')
        ping = self._speed_ping(urls[0])
        dl   = self._speed_dl(urls, dl_seconds, threads_dl)
        ul   = None
        if ul_seconds and ul_seconds > 0:
            try:
                ul = self._speed_ul(urls, ul_seconds, threads_ul)
            except Exception:
                ul = None
        return provider, dl, ul, ping

    def _do_speedtest(self):
        if not self.connected: return
        if getattr(self, '_speedtesting', False):
            self.log('Speed test already running', 'warn'); return
        self._speedtesting = True
        self.log('Speed test starting… (fast.com)', 'info')
        self.after(0, lambda: self.btn_speed.state(['disabled']))
        self.after(0, lambda: self.btn_speed.config(text='🔄 Testing…'))
        self.after(0, lambda: self.speed_pb.start(12))
        def worker():
            try:
                prov, dl, ul, ping = self._net_speed(8, 5, prune=True)
                ul_s = '—' if ul is None else f'{ul:.1f}'
                p_s  = '—' if ping is None else f'{ping:.0f}ms'
                msg  = f'Speed ({prov}): ↓{dl:.1f} Mbps  ↑{ul_s} Mbps  ping {p_s}'
                self.log(msg, 'ok')
                self.after(0, lambda: self.sb_var.set(msg))
            except Exception as e:
                self.log(f'Speed test failed: {e}', 'error')
            finally:
                self._speedtesting = False
                self.after(0, lambda: [
                    self.btn_speed.state(['!disabled']),
                    self.btn_speed.config(text='🔄 Speed Test'),
                    self.speed_pb.stop(),
                ])
        threading.Thread(target=worker, daemon=True).start()

    # ── Tab: SMS ─────────────────────────────────────────────
    def _build_tab_sms(self):
        f = self._tab_sms
        top = tk.Frame(f, bg=COLORS['bg'])
        top.pack(fill='x', padx=16, pady=(14,8))
        tk.Label(top, text='SMS', bg=COLORS['bg'],
                 fg=COLORS['text'], font=('Segoe UI',12,'bold')).pack(side='left')
        ttk.Button(top, text='Refresh', command=self._refresh_sms).pack(side='right')

        # SMS list
        cols   = ('idx','from','date','preview')
        hdrs   = ('#','From','Date','Message')
        widths = (40,120,140,340)
        frame  = tk.Frame(f, bg=COLORS['bg'])
        frame.pack(fill='both', expand=True, padx=16, pady=(0,8))
        self.tree_sms = ttk.Treeview(frame, columns=cols, show='headings', height=10)
        for c,h,w in zip(cols,hdrs,widths):
            self.tree_sms.heading(c, text=h)
            self.tree_sms.column(c, width=w)
        sb = ttk.Scrollbar(frame, orient='vertical', command=self.tree_sms.yview)
        self.tree_sms.configure(yscrollcommand=sb.set)
        self.tree_sms.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')
        self.tree_sms.bind('<Double-1>', self._read_sms)

        # Send SMS
        send_frame = tk.LabelFrame(f, text=' Send SMS ', bg=COLORS['bg'],
                                    fg=COLORS['muted'], font=('Segoe UI',9), bd=1, relief='groove')
        send_frame.pack(fill='x', padx=16, pady=(0,14))
        sr = tk.Frame(send_frame, bg=COLORS['bg'])
        sr.pack(padx=10, pady=8, fill='x')
        tk.Label(sr, text='To', bg=COLORS['bg'], fg=COLORS['muted'], font=('Segoe UI',9)).pack(side='left')
        self.sms_to = ttk.Entry(sr, width=18)
        self.sms_to.pack(side='left', padx=(4,14))
        tk.Label(sr, text='Message', bg=COLORS['bg'], fg=COLORS['muted'], font=('Segoe UI',9)).pack(side='left')
        self.sms_msg = ttk.Entry(sr, width=40)
        self.sms_msg.pack(side='left', padx=(4,10), fill='x', expand=True)
        ttk.Button(sr, text='Send', command=self._send_sms).pack(side='left')

    def _refresh_sms(self):
        if not self.connected: return
        def worker():
            try:
                msgs, err = self.api.sms_list()
                if err:
                    self.log(f'SMS read failed: {err}', 'warn')
                    return
                def update():
                    for r in self.tree_sms.get_children(): self.tree_sms.delete(r)
                    for m in msgs:
                        idx     = m.get('Index', '')
                        phone   = m.get('Phone', '')
                        date    = m.get('Date', '')
                        content = m.get('Content', '')
                        self.tree_sms.insert('','end', values=(idx, phone, date, content[:60]), iid=str(idx))
                    self.log(f'{len(msgs)} SMS message(s) loaded', 'ok')
                self.after(0, update)
            except Exception as e:
                self.log(f'SMS refresh failed: {e}', 'error')
        threading.Thread(target=worker, daemon=True).start()

    def _read_sms(self, evt):
        sel = self.tree_sms.selection()
        if not sel: return
        vals = self.tree_sms.item(sel[0], 'values')
        if vals:
            messagebox.showinfo('SMS', f"From: {vals[1]}\nDate: {vals[2]}\n\n{vals[3]}")

    def _send_sms(self):
        if not self.connected: return
        to  = self.sms_to.get().strip()
        msg = self.sms_msg.get().strip()
        if not to or not msg: messagebox.showwarning('Missing', 'Enter number and message'); return
        def worker():
            body = (f'<?xml version="1.0" encoding="UTF-8"?>'
                    f'<request><Index>-1</Index><Phones><Phone>{to}</Phone></Phones>'
                    f'<Sca></Sca><Content>{msg}</Content><Length>{len(msg)}</Length>'
                    f'<Reserved>1</Reserved><Date>-1</Date></request>')
            resp = self.api.post('/api/sms/send-sms', body)
            err  = xml_val(resp, 'code')
            if err:
                self.log(f'SMS send failed: error {err}', 'error')
                self.after(0, lambda: messagebox.showerror('Failed', f'SMS error {err}'))
            else:
                self.log(f'SMS sent to {to}', 'ok')
                self.after(0, lambda: [self.sms_msg.delete(0,'end'),
                                        messagebox.showinfo('Sent', 'SMS sent successfully')])
        threading.Thread(target=worker, daemon=True).start()

    # ── Tab: Signal Chart ─────────────────────────────────────
    def _build_tab_chart(self):
        f = self._tab_chart
        if not MATPLOTLIB:
            tk.Label(f, text='Install matplotlib to enable charts\npip install matplotlib',
                     bg=COLORS['bg'], fg=COLORS['muted'],
                     font=('Segoe UI',11)).pack(expand=True)
            return

        top = tk.Frame(f, bg=COLORS['bg'])
        top.pack(fill='x', padx=16, pady=(14,4))
        tk.Label(top, text='Live Signal Chart', bg=COLORS['bg'],
                 fg=COLORS['text'], font=('Segoe UI',12,'bold')).pack(side='left')
        ttk.Button(top, text='Clear', command=lambda: self.signal_history.clear()).pack(side='right')

        self.fig = Figure(figsize=(9, 4), facecolor=COLORS['bg'])
        self.ax  = self.fig.add_subplot(111)
        self.ax.set_facecolor(COLORS['surface'])
        self.ax.tick_params(colors=COLORS['muted'])
        for sp in self.ax.spines.values(): sp.set_edgecolor(COLORS['border'])
        self.ax.set_title('Signal Metrics (last 120 samples)', color=COLORS['muted'], fontsize=9)
        self.ax.set_ylabel('dBm / dB', color=COLORS['muted'], fontsize=9)
        self.canvas = FigureCanvasTkAgg(self.fig, master=f)
        self.canvas.get_tk_widget().pack(fill='both', expand=True, padx=16, pady=(0,14))

    def _update_chart(self):
        if not MATPLOTLIB or not hasattr(self, 'ax'): return
        if len(self.signal_history) < 2: return
        hist = self.signal_history[-120:]
        times = list(range(len(hist)))
        rsrp  = [h['rsrp'] for h in hist]
        rsrq  = [h['rsrq'] for h in hist]
        sinr  = [h['sinr'] for h in hist]
        try:
            self.ax.clear()
            self.ax.set_facecolor(COLORS['surface'])
            self.ax.plot(times, rsrp, color=COLORS['accent'],  label='RSRP (dBm)', linewidth=1.5)
            self.ax.plot(times, rsrq, color=COLORS['yellow'],  label='RSRQ (dB)',  linewidth=1.5)
            self.ax.plot(times, sinr, color=COLORS['green'],   label='SINR (dB)',  linewidth=1.5)
            self.ax.legend(facecolor=COLORS['surface'], edgecolor=COLORS['border'],
                           labelcolor=COLORS['text'], fontsize=8)
            self.ax.set_title('Signal Metrics (last 120 samples)', color=COLORS['muted'], fontsize=9)
            self.ax.set_ylabel('dBm / dB', color=COLORS['muted'], fontsize=9)
            self.ax.tick_params(colors=COLORS['muted'], labelsize=8)
            for sp in self.ax.spines.values(): sp.set_edgecolor(COLORS['border'])
            self.fig.tight_layout()
            self.canvas.draw_idle()  # draw_idle is thread-safe unlike draw()
        except Exception as e:
            self.log(f'Chart error: {e}', 'error')

    # ── Tab: Log ──────────────────────────────────────────────
    def _build_tab_log(self):
        f = self._tab_log
        top = tk.Frame(f, bg=COLORS['bg'])
        top.pack(fill='x', padx=16, pady=(14,8))
        tk.Label(top, text='Activity Log', bg=COLORS['bg'],
                 fg=COLORS['text'], font=('Segoe UI',12,'bold')).pack(side='left')
        ttk.Button(top, text='Clear', command=self._clear_log).pack(side='right')
        ttk.Button(top, text='Copy All', command=self._copy_log).pack(side='right', padx=8)

        self.log_text = scrolledtext.ScrolledText(
            f, bg=COLORS['surface'], fg=COLORS['text'],
            font=('Consolas', 9), relief='flat', wrap='word',
            insertbackground=COLORS['text'], state='disabled')
        self.log_text.pack(fill='both', expand=True, padx=16, pady=(0,14))

        # Tags for colouring
        self.log_text.tag_config('ts',    foreground=COLORS['muted'])
        self.log_text.tag_config('info',  foreground=COLORS['text'])
        self.log_text.tag_config('ok',    foreground=COLORS['green'])
        self.log_text.tag_config('error', foreground=COLORS['red'])
        self.log_text.tag_config('warn',  foreground=COLORS['yellow'])
        self.log_text.tag_config('api',   foreground=COLORS['accent'])

    def log(self, msg, level='info'):
        """Thread-safe log — can be called from any thread."""
        def _write():
            ts = datetime.now().strftime('%H:%M:%S')
            self.log_text.config(state='normal')
            self.log_text.insert('end', f'[{ts}] ', 'ts')
            self.log_text.insert('end', msg + '\n', level)
            self.log_text.see('end')
            self.log_text.config(state='disabled')
        self.after(0, _write)

    def _clear_log(self):
        self.log_text.config(state='normal')
        self.log_text.delete('1.0', 'end')
        self.log_text.config(state='disabled')

    def _copy_log(self):
        content = self.log_text.get('1.0', 'end')
        self.clipboard_clear()
        self.clipboard_append(content)
        self.sb_var.set('Log copied to clipboard')

    # ── Connection ────────────────────────────────────────────
    def _connect(self):
        ip  = self.e_ip.get().strip()
        pwd = self.e_pass.get()
        if not ip:
            messagebox.showwarning('Missing', 'Enter router IP'); return

        self.btn_connect.state(['disabled'])
        self.status_var.set('Connecting…')
        self.conn_label.config(text='● Connecting…', fg=COLORS['yellow'])
        self.after(0, lambda: self.conn_pb.start(12))

        def worker():
            def status_cb(msg):
                self.after(0, lambda m=msg: self.status_var.set(m))
                self.log(msg, 'info')
            self.api = RouterAPI(ip, status_cb=status_cb)
            self.log(f'Connecting to {ip}…', 'info')
            ok, msg = self.api.login('admin', pwd)
            if ok:
                self.connected = True
                self.cfg.update({'ip':ip,'password':pwd})
                save_config(self.cfg)
                self.log(f'✓ {msg}', 'ok')
                self._start_nei_logger()
                self.after(0, lambda: [
                    self.conn_label.config(text='● Connected', fg=COLORS['green']),
                    self.status_var.set(msg),
                    self.sb_var.set(f'Connected to {ip}'),
                    self.btn_disconnect.state(['!disabled']),
                    self.btn_connect.state(['!disabled']),
                    self.conn_pb.stop(),
                    self._refresh_info(),
                    self._refresh_hosts(),
                ])
            else:
                self.connected = False
                self.api = None
                self.log(f'✗ {msg}', 'error')
                self.after(0, lambda: [
                    self.conn_label.config(text='● Disconnected', fg=COLORS['red']),
                    self.status_var.set(msg),
                    self.sb_var.set('Connection failed'),
                    self.btn_connect.state(['!disabled']),
                    self.conn_pb.stop(),
                ])
        threading.Thread(target=worker, daemon=True).start()

    def _on_close(self):
        """Closing the window while a sweep/search is running must NOT leave the
        modem mid-search and band-locked — the daemon threads die with the
        process before the sweep's restore runs, so the router stays busy and
        won't answer the API. Stop the logger (the sweep aborts and restores
        itself in its finally), then force a bounded best-effort restore to
        full-auto bands as a belt-and-braces."""
        if self._nei_logging or self._sweeping or getattr(self, '_searching', False):
            self._stop_nei_logger()
            if self.api:
                try:
                    time.sleep(1.0)  # let the sweep's finally begin its restore
                    self.api.check_session()
                    self.api.set_net_mode('00', '7FFFFFFFFFFFFFFF',
                                          '7FFFFFFFFFFFFFFF', timeout=15)
                    # A lock-freq PCI lock survives the net-mode restore and keeps
                    # the modem hard-pinned — never leave the router like that.
                    try: self.api.unlock_cell()
                    except Exception: pass
                    self.log('Pre-close: bands restored to auto', 'info')
                except Exception as e:
                    self.log(f'Pre-close restore failed: {e}', 'warn')
        self.destroy()

    def _disconnect(self):
        self._stop_nei_logger()
        self.connected = False
        self.api = None
        self.conn_label.config(text='● Disconnected', fg=COLORS['red'])
        self.status_var.set('Disconnected')
        self.btn_disconnect.state(['disabled'])
        for w in self._sig_widgets.values(): w.config(text='—', fg=COLORS['accent'])
        self.sb_var.set('Disconnected')
        self.log('Disconnected', 'warn')

    # ── Background refresh ────────────────────────────────────
    def _start_refresh(self):
        self._refresh_tick()

    def _refresh_tick(self):
        if self.connected and self.api:
            def worker():
                try:
                    sig = self.api.signal()
                    self.after(0, lambda: self._update_signal_strip(sig))
                    self.after(0, self._update_chart)
                except: pass
                # Keepalive every tick (every 3s) — router times out sessions quickly
                try: self.api.keepalive()
                except: pass
                self.after(0, lambda: self.sb_time.config(
                    text=datetime.now().strftime('%H:%M:%S')))
            threading.Thread(target=worker, daemon=True).start()
        self.after(3000, self._refresh_tick)  # 3s tick to keep session alive

    def _set_sb(self, msg):
        self.sb_var.set(msg)

if __name__ == '__main__':
    app = HuaweiTool()
    app.mainloop()
