#!/usr/bin/env python3
"""
MineBoard - Dashboard per Server Minecraft
Webserver Python con console, log, file manager e gestione multipli server
"""

import os
import json
import subprocess
import threading
import time
import requests
import zipfile
import tarfile
import psutil
import shutil
import urllib.parse
import base64
import tempfile
from datetime import datetime, timedelta, timezone
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, abort, session
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import logging

app = Flask(__name__)
app.secret_key = 'mineboard_secret_key_2024'

# Riduci i log del server di sviluppo/werkzeug (niente access log in console)
logging.getLogger('werkzeug').setLevel(logging.ERROR)
logging.getLogger('werkzeug.serving').setLevel(logging.ERROR)
logging.getLogger('waitress').setLevel(logging.WARNING)
try:
    # Evita che Flask propaghi troppi log
    app.logger.setLevel(logging.WARNING)
except Exception:
    pass

# Configurazione
SERVER_DIR = os.path.join(os.getcwd(), 'servers')
LOG_DIR = os.path.join(os.getcwd(), 'logs')
UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads')
BACKUP_DIR = os.path.join(os.getcwd(), 'backups')
VERSIONS_DIR = os.path.join(os.getcwd(), 'versions')
ALLOWED_EXTENSIONS = {'jar', 'zip', 'txt', 'properties', 'yml', 'yaml', 'json'}
USERS_FILE = os.path.join(os.getcwd(), 'users.json')

# Versioning SE MODIFICHI QUESTA SEZIONE NIENTE PIÙ BISCOTTI :<
APP_VERSION = os.environ.get('MINEBOARD_VERSION', '1.0.4')
UPDATE_CHECK_URL = os.environ.get('MINEBOARD_UPDATE_URL', 'https://pastebin.com/raw/whfbJD7K')
UPDATE_PAGE_URL = os.environ.get('MINEBOARD_UPDATE_PAGE', 'https://github.com/Scalamobile/mineboard')

# Crea directory necessarie
for directory in [SERVER_DIR, LOG_DIR, UPLOAD_FOLDER, BACKUP_DIR, VERSIONS_DIR]:
    os.makedirs(directory, exist_ok=True)

DEFAULT_PERMISSIONS = {
    'servers_control': True,   # avviare/fermare/riavviare
    'files_access': True,      # file manager
    'players_access': True,    # scheda players
    'stats_view': True,        # dashboard stats (HOME)
    'settings_access': True,   # accesso a impostazioni/gestione utenti
    'config_access': True,     # accesso configurazione server (properties/eula)
    'backup_access': True,     # gestione backup del server
    'server_stats_access': True  # statistiche del server singolo
}

# Inizializza file utenti se non esiste
if not os.path.exists(USERS_FILE):
    with open(USERS_FILE, 'w') as f:
        json.dump({
            'admin': {
                'password_hash': None,
                'role': 'admin',
                'permissions': DEFAULT_PERMISSIONS
            }
        }, f)

# Gestione utenti e OTP
otp_info = {
    'password': None,
    'expires_at': None,
    'used': False
}

def load_users():
    try:
        with open(USERS_FILE, 'r') as f:
            users = json.load(f)
    except Exception:
        users = {
            'admin': {
                'password_hash': None,
                'role': 'admin',
                'permissions': DEFAULT_PERMISSIONS
            }
        }
    # Normalize: ensure role and permissions exist
    changed = False
    for uname, info in list(users.items()):
        if not isinstance(info, dict):
            users[uname] = {'password_hash': None, 'role': 'user', 'permissions': {'servers_control': False, 'files_access': False, 'players_access': False, 'stats_view': False}}
            changed = True
            continue
        if 'role' not in info:
            info['role'] = 'admin' if uname == 'admin' else 'user'
            changed = True
        if 'permissions' not in info:
            if info['role'] == 'admin':
                info['permissions'] = DEFAULT_PERMISSIONS
            else:
                info['permissions'] = {
                    'servers_control': False,
                    'files_access': False,
                    'players_access': False,
                    'stats_view': False,
                    'settings_access': False,
                    'config_access': False,
                    'backup_access': False,
                    'server_stats_access': False
                }
            changed = True
    if changed:
        save_users(users)
    return users

def save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=2)

def set_admin_password(raw_password):
    users = load_users()
    users.setdefault('admin', {'role': 'admin', 'permissions': DEFAULT_PERMISSIONS})
    users['admin']['password_hash'] = generate_password_hash(raw_password)
    save_users(users)

def is_authenticated():
    return bool(session.get('user'))

def get_current_user():
    username = session.get('user')
    if not username:
        return None, None
    users = load_users()
    return username, users.get(username)

def has_permission(perm_key):
    username, user = get_current_user()
    if not user:
        return False
    if user.get('role') == 'admin':
        return True
    perms = user.get('permissions', {})
    return perms.get(perm_key, False)

def login_required_path(path):
    # Percorsi pubblici
    public_paths = [
        '/login', '/forgot-password', '/static/', '/favicon.ico'
    ]
    # Consenti static
    if path.startswith('/static/'):
        return False
    return path not in public_paths

@app.before_request
def enforce_authentication():
    path = request.path
    if login_required_path(path) and not is_authenticated():
        return redirect(url_for('login', next=path))

def generate_console_password():
    import secrets
    pwd = secrets.token_hex(32)  # 64 caratteri
    return pwd

# Dizionario per tenere traccia dei processi server
running_servers = {}

# CentroJars API Configuration (legacy – kept for backward compatibility)
CENTROJARS_BASE_URL = "https://centrojars.com"
CENTROJARS_TYPES = {
    'servers': ['paper', 'spigot', 'bukkit', 'vanilla', 'fabric', 'forge', 'quilt'],
    'proxies': ['velocity', 'bungeecord', 'waterfall'],
    'modded': ['fabric', 'forge', 'quilt', 'neoforge']
}

# MCUtils API Configuration (new)
MCUTILS_BASE_URL = "https://mcutils.com"
MCUTILS_TYPES = {
    'servers': ['purpur', 'pufferfish', 'paper', 'vanilla', 'folia'],
    'proxies': ['velocity'],
    'modded': ['fabric', 'neoforge', 'quilt', 'forge']
}

# Fallback URLs per download JAR
FALLBACK_JAR_URLS = {
    'paper': 'https://api.papermc.io/v2/projects/paper/versions/{version}/builds/{build}/downloads/paper-{version}-{build}.jar',
    'spigot': 'https://download.getbukkit.org/spigot/spigot-{version}.jar',
    'vanilla': 'https://launcher.mojang.com/v1/objects/{hash}/server.jar'
}

def fetch_jar_types():
    """Ottieni tutti i tipi di JAR disponibili da CentroJars"""
    try:
        response = requests.get(f"{CENTROJARS_BASE_URL}/api/fetchJar/fetchAllTypes.php", timeout=10)
        if response.status_code == 200:
            return response.json()
        return CENTROJARS_TYPES
    except Exception as e:
        print(f"Errore nel fetch dei tipi JAR: {e}")
        return CENTROJARS_TYPES

def fetch_latest_jar(type_name, category):
    """Ottieni informazioni sull'ultimo JAR disponibile"""
    try:
        # Prova prima con CentroJars
        response = requests.get(f"{CENTROJARS_BASE_URL}/api/fetchLatest/{type_name}/{category}", timeout=10, allow_redirects=True)
        if response.status_code == 200:
            data = response.json()
            # CentroJars restituisce la struttura: {"status": "success", "response": {...}}
            if data.get('status') == 'success' and 'response' in data:
                return data['response']
            return data
        
        # Se CentroJars non funziona, usa fallback per versioni comuni
        print(f"CentroJars non disponibile per {category}, uso fallback")
        fallback_versions = {
            'paper': '1.20.1',
            'spigot': '1.20.1', 
            'bukkit': '1.20.1',
            'vanilla': '1.20.1',
            'fabric': '1.20.1',
            'forge': '1.20.1',
            'quilt': '1.20.1',
            'velocity': '3.2.0',
            'bungeecord': '1.20',
            'waterfall': '1.20'
        }
        
        if category in fallback_versions:
            return {
                'version': fallback_versions[category],
                'category': category,
                'type': type_name,
                'source': 'fallback'
            }
        
        return None
    except Exception as e:
        print(f"Errore nel fetch dell'ultimo JAR: {e}")
        return None

def fetch_jar_download_link(type_name, category, version="latest"):
    """Ottieni il link di download diretto per un JAR specifico"""
    try:
        # Se la versione è "latest", ottieni prima l'ultima versione disponibile
        if version == "latest":
            latest_info = fetch_latest_jar(type_name, category)
            if latest_info and 'version' in latest_info:
                version = latest_info['version']
                print(f"Versione latest trovata: {version}")
            else:
                # Fallback per versioni comuni
                version = "1.20.1"
                print(f"Usando versione fallback: {version}")
        
        # Prova prima con l'URL diretto
        url = f"{CENTROJARS_BASE_URL}/api/fetchJar/{type_name}/{category}/{version}"
        print(f"Tentativo di accesso a: {url}")
        
        response = requests.get(url, timeout=10, allow_redirects=True)
        print(f"Status code: {response.status_code}")
        
        if response.status_code == 200:
            try:
                data = response.json()
                # CentroJars restituisce la struttura: {"status": "success", "response": {...}}
                if data.get('status') == 'success' and 'response' in data:
                    return data['response']
                return data
            except:
                # Se non è JSON, potrebbe essere il file JAR diretto
                if response.headers.get('content-type', '').startswith('application/java-archive'):
                    return {'url': url, 'download_url': url, 'direct_download': True}
                return None
        elif response.status_code in [301, 302]:
            # Segui il redirect
            redirect_url = response.headers.get('Location')
            if redirect_url:
                redirect_response = requests.get(redirect_url, timeout=10)
                if redirect_response.status_code == 200:
                    try:
                        return redirect_response.json()
                    except:
                        return {'url': redirect_url, 'download_url': redirect_url}
        
        return None
    except Exception as e:
        print(f"Errore nel fetch del link download: {e}")
        return None

# ===================== SERVER INTERNAL CONFIG + WEBHOOK HELPERS =====================
def load_server_internal_config(server_name):
    """Carica server_config.json come dict, se manca ritorna default."""
    server_path = os.path.join(SERVER_DIR, server_name)
    cfg_path = os.path.join(server_path, 'server_config.json')
    cfg = {
        'name': server_name,
        'port': 25565,
        'jar_file': 'server.jar',
        'max_memory': '1G',
        'status': 'stopped',
        'use_custom_start': False,
        'custom_start_cmd': '',
        'webhook': {
            'url': '',
            'triggers': {
                'server_started': False,
                'server_stopped': False,
                'server_crashed': False,
                'backup_completed': False,
                'jar_updated': False,
                'command_received': False,
                'server_terminated': False,
                'player_join_match': False
            },
            'player_match_username': ''
        }
    }
    try:
        if os.path.exists(cfg_path):
            with open(cfg_path, 'r') as f:
                file_cfg = json.load(f)
                # merge shallow
                for k, v in file_cfg.items():
                    cfg[k] = v
                # Default webhook keys
                wb = cfg.get('webhook') or {}
                wb.setdefault('url', '')
                wb.setdefault('triggers', {})
                for t in ['server_started','server_stopped','server_crashed','backup_completed','jar_updated','command_received','server_terminated','player_join_match']:
                    wb['triggers'].setdefault(t, False)
                wb.setdefault('player_match_username', '')
                cfg['webhook'] = wb
                # Ensure custom start keys exist after merge
                cfg.setdefault('use_custom_start', False)
                cfg.setdefault('custom_start_cmd', '')
    except Exception as e:
        print(f"Errore nel caricare config server {server_name}: {e}")
    return cfg

def save_server_internal_config(server_name, cfg):
    server_path = os.path.join(SERVER_DIR, server_name)
    os.makedirs(server_path, exist_ok=True)
    cfg_path = os.path.join(server_path, 'server_config.json')
    try:
        with open(cfg_path, 'w') as f:
            json.dump(cfg, f, indent=2)
        return True
    except Exception as e:
        print(f"Errore nel salvataggio config server {server_name}: {e}")
        return False

def send_discord_webhook(server_name, trigger_key, content):
    """Invia un webhook Discord se abilitato per il trigger indicato."""
    try:
        cfg = load_server_internal_config(server_name)
        wb = (cfg or {}).get('webhook', {})
        url = wb.get('url', '').strip()
        if not url:
            return False
        triggers = wb.get('triggers', {})
        if not triggers.get(trigger_key, False):
            return False
        payload = {
            'content': content
        }
        r = requests.post(url, json=payload, timeout=10)
        return r.status_code in (200, 204)
    except Exception as e:
        print(f"Errore invio webhook ({trigger_key}): {e}")
        return False

def get_fallback_jar_url(category, version="latest"):
    """Ottieni URL di fallback per download JAR quando CentroJars non è disponibile"""
    try:
        # Se la versione è "latest", usa versioni predefinite
        if version == "latest":
            fallback_versions = {
                'paper': '1.20.1',
                'spigot': '1.20.1', 
                'bukkit': '1.20.1',
                'vanilla': '1.20.1',
                'fabric': '1.20.1',
                'forge': '1.20.1',
                'quilt': '1.20.1',
                'velocity': '3.2.0',
                'bungeecord': '1.20',
                'waterfall': '1.20'
            }
            version = fallback_versions.get(category, '1.20.1')
        
        if category == 'paper':
            # Per Paper, usa l'API ufficiale
            try:
                # Ottieni l'ultimo build per quella versione
                builds_response = requests.get(f'https://api.papermc.io/v2/projects/paper/versions/{version}/builds', timeout=10)
                if builds_response.status_code == 200:
                    builds = builds_response.json()['builds']
                    latest_build = builds[-1]['build']
                    return f'https://api.papermc.io/v2/projects/paper/versions/{version}/builds/{latest_build}/downloads/paper-{version}-{latest_build}.jar'
            except:
                pass
        
        elif category == 'spigot':
            # Per Spigot, usa GetBukkit
            return f'https://download.getbukkit.org/spigot/spigot-{version}.jar'
        elif category == 'bukkit':
            # Per Bukkit, usa GetBukkit
            return f'https://download.getbukkit.org/bukkit/bukkit-{version}.jar'
        
        elif category == 'vanilla':
            # Per Vanilla, usa l'API Mojang
            return f'https://launcher.mojang.com/v1/objects/a1d5b5d4c5b5d4c5b5d4c5b5d4c5b5d4c5b5d4c5/server.jar'
        
        return None
    except Exception as e:
        print(f"Errore nel fallback JAR: {e}")
        return None

def get_url_from_versions(jar_type, version):
    """Leggi i file JSON in versions/ per ottenere l'URL di download per jar_type/version.
    Ritorna None se non trovato."""
    try:
        os.makedirs(VERSIONS_DIR, exist_ok=True)
        # Normalizza nomi file: bukkit -> craftbukkit
        file_key = jar_type.lower()
        if file_key == 'bukkit':
            file_key = 'craftbukkit'
        filename = f"{file_key}_version_list.json"
        path = os.path.join(VERSIONS_DIR, filename)
        if not os.path.exists(path):
            return None
        with open(path, 'r') as f:
            data = json.load(f)
        # Le chiavi sono versioni, i valori URL
        url = data.get(str(version))
        return url
    except Exception as e:
        print(f"Errore lettura versions/{jar_type}: {e}")
        return None

# ===================== VERSION CHECK =====================
def parse_version(v):
    try:
        # Keep only digits and dots, split to ints for comparison
        parts = [int(p) for p in str(v).strip().split('.') if p.isdigit() or p.isnumeric()]
        return parts
    except Exception:
        return []

def compare_versions(a, b):
    """Return -1 if a<b, 0 if a==b, 1 if a>b for dotted versions."""
    pa, pb = parse_version(a), parse_version(b)
    # pad shorter
    n = max(len(pa), len(pb))
    pa += [0] * (n - len(pa))
    pb += [0] * (n - len(pb))
    for x, y in zip(pa, pb):
        if x < y:
            return -1
        if x > y:
            return 1
    return 0

def fetch_latest_version():
    try:
        r = requests.get(UPDATE_CHECK_URL, timeout=10)
        if r.status_code == 200:
            latest = r.text.strip().splitlines()[0].strip()
            return latest
    except Exception as e:
        print(f"Errore fetch versione da Pastebin: {e}")
    return None

# Background version checker cache and thread
version_cache = {
    'latest': None,
    'update_available': False,
    'last_checked': None,
}

def background_version_checker():
    while True:
        try:
            latest = fetch_latest_version()
            if latest:
                version_cache['latest'] = latest
                version_cache['last_checked'] = datetime.now(timezone.utc).isoformat()
                # Treat any mismatch as update available
                ua = compare_versions(APP_VERSION, latest) != 0
                # Log only on change from previous state or when update available
                if ua and not version_cache.get('update_available', False):
                    print(f"[UPDATE] Nuova versione disponibile: {latest} (installata: {APP_VERSION}). Scarica: {UPDATE_PAGE_URL}")
                version_cache['update_available'] = ua
        except Exception as e:
            try:
                version_cache['last_checked'] = datetime.now(timezone.utc).isoformat()
            except Exception:
                pass
        # Sleep 2 minutes
        time.sleep(120)

@app.route('/api/version')
def get_version():
    try:
        latest = version_cache.get('latest') or fetch_latest_version()
        cmp = compare_versions(APP_VERSION, latest or APP_VERSION)
        update_available = (latest is not None and cmp != 0)
        try:
            if update_available:
                print(f"[UPDATE] Nuova versione disponibile: {latest} (installata: {APP_VERSION}). Scarica: {UPDATE_PAGE_URL}")
        except Exception:
            pass
        return jsonify({
            'success': True,
            'version': APP_VERSION,
            'latest': latest,
            'update_available': update_available,
            'update_url': UPDATE_PAGE_URL
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e), 'version': APP_VERSION}), 500

@app.route('/api/version/check')
def check_version():
    try:
        latest = fetch_latest_version()
        if not latest:
            return jsonify({'success': False, 'message': 'Impossibile ottenere la versione remota', 'version': APP_VERSION}), 502
        cmp = compare_versions(APP_VERSION, latest)
        update_available = cmp != 0
        try:
            if update_available:
                print(f"[UPDATE] Nuova versione disponibile: {latest} (installata: {APP_VERSION}). Scarica: {UPDATE_PAGE_URL}")
        except Exception:
            pass
        return jsonify({
            'success': True,
            'version': APP_VERSION,
            'latest': latest,
            'update_available': update_available,
            'update_url': UPDATE_PAGE_URL
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e), 'version': APP_VERSION}), 500

def download_jar_to_server(server_name, jar_url, jar_filename="server.jar"):
    """Scarica un JAR da CentroJars e lo salva nella directory del server"""
    try:
        server_path = os.path.join(SERVER_DIR, server_name)
        os.makedirs(server_path, exist_ok=True)
        
        jar_path = os.path.join(server_path, jar_filename)
        
        print(f"Scaricamento JAR da: {jar_url}")
        response = requests.get(jar_url, timeout=60, stream=True)
        
        if response.status_code == 200:
            with open(jar_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            print(f"JAR scaricato con successo: {jar_path}")
            return True, f"JAR scaricato con successo: {jar_filename}"
        else:
            return False, f"Errore nel download: HTTP {response.status_code}"
            
    except Exception as e:
        return False, f"Errore nel download del JAR: {str(e)}"

# ===================== AUTO-UPDATE (APP) – MIRROR MODE =====================
def github_main_zip_url():
    return 'https://github.com/Scalamobile/mineboard/archive/refs/heads/main.zip'

def build_repo_file_set(root_dir):
    files = set()
    for r, dnames, fnames in os.walk(root_dir):
        rel_root = os.path.relpath(r, root_dir)
        if rel_root == '.':
            rel_root = ''
        for f in fnames:
            rel_path = os.path.join(rel_root, f) if rel_root else f
            files.add(rel_path.replace('\\', '/'))
    return files

def mirror_copy_repo_to_project(repo_root, project_root, preserve_dirs=None, preserve_files=None):
    preserve_dirs = set(preserve_dirs or [])
    preserve_files = set(preserve_files or [])

    repo_files = build_repo_file_set(repo_root)

    # 1) Delete local files not present in repo (excluding preserved)
    for r, dnames, fnames in os.walk(project_root, topdown=True):
        rel_root = os.path.relpath(r, project_root)
        if rel_root == '.':
            rel_root = ''
        top_component = rel_root.split(os.sep)[0] if rel_root else ''
        if top_component in preserve_dirs:
            dnames[:] = []
            continue
        dnames[:] = [dn for dn in dnames if (top_component or dn) not in preserve_dirs]
        for f in fnames:
            rel_path = os.path.join(rel_root, f) if rel_root else f
            rel_norm = rel_path.replace('\\', '/')
            if rel_norm in preserve_files:
                continue
            if rel_norm.startswith('mineboard/') or rel_norm.startswith('venv/'):
                continue
            if rel_norm not in repo_files:
                try:
                    os.remove(os.path.join(project_root, rel_path))
                except Exception:
                    pass

    # 2) Copy/overwrite files from repo into project
    for r, dnames, fnames in os.walk(repo_root):
        rel_root = os.path.relpath(r, repo_root)
        if rel_root == '.':
            rel_root = ''
        top_component = rel_root.split(os.sep)[0] if rel_root else ''
        if top_component in preserve_dirs:
            continue
        target_root = os.path.join(project_root, rel_root) if rel_root else project_root
        os.makedirs(target_root, exist_ok=True)
        for f in fnames:
            rel_path = os.path.join(rel_root, f) if rel_root else f
            if rel_path.replace('\\', '/') in preserve_files:
                continue
            src_path = os.path.join(r, f)
            dst_path = os.path.join(target_root, f)
            os.makedirs(os.path.dirname(dst_path), exist_ok=True)
            shutil.copy2(src_path, dst_path)

@app.route('/api/system/update', methods=['POST'])
def system_auto_update():
    """Aggiorna i file locali a specchio dal branch main della repo, preservando cartelle/file dati."""
    if not has_permission('settings_access'):
        return jsonify({'success': False, 'message': 'Permesso negato'}), 403
    try:
        zip_url = github_main_zip_url()
        print(f"[UPDATE] Scarico pacchetto da: {zip_url}")
        with requests.get(zip_url, stream=True, timeout=120) as r:
            if r.status_code != 200:
                return jsonify({'success': False, 'message': f'Download fallito: HTTP {r.status_code}'}), 502
            with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as tmpf:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        tmpf.write(chunk)
                tmp_zip = tmpf.name
        with tempfile.TemporaryDirectory() as tmpdir:
            with zipfile.ZipFile(tmp_zip, 'r') as z:
                z.extractall(tmpdir)
            entries = os.listdir(tmpdir)
            if not entries:
                os.remove(tmp_zip)
                return jsonify({'success': False, 'message': 'Pacchetto vuoto'}), 500
            repo_root = os.path.join(tmpdir, entries[0])
            if not os.path.isdir(repo_root):
                repo_root = tmpdir
            project_root = os.getcwd()
            preserve_dirs = {'backups', 'logs', 'versions', 'servers', 'uploads', '.git'}
            preserve_files = {'users.json'}
            mirror_copy_repo_to_project(repo_root, project_root, preserve_dirs, preserve_files)
        try:
            os.remove(tmp_zip)
        except Exception:
            pass
        print("[UPDATE] Aggiornamento mirror completato. Riavviare l'app per applicare le modifiche.")
        return jsonify({'success': True, 'message': "Aggiornamento completato. Riavvia l'app per applicare le modifiche."})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Errore aggiornamento: {str(e)}'}), 500

# ===================== MCUTILS API ROUTES =====================
@app.route('/api/mcutils/types')
def mcutils_types():
    try:
        return jsonify({'success': True, 'types': MCUTILS_TYPES})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Errore: {str(e)}'}), 500


@app.route('/api/mcutils/download/<jar_type>/<version>', methods=['GET', 'OPTIONS'])
def mcutils_download(jar_type, version):
    """Proxy per scaricare JAR da MCUtils evitando problemi CORS"""
    if request.method == 'OPTIONS':
        return '', 200, {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type'
        }

    try:
        jar_type = jar_type.strip()
        version = version.strip()
        source = (request.args.get('source') or '').strip().lower()
        
        def send_jar(r):
            # Stream chunks to client and log progress to console
            total = None
            try:
                total = int(r.headers.get('Content-Length', '0')) or None
            except Exception:
                total = None

            def generate():
                downloaded = 0
                for chunk in r.iter_content(chunk_size=8192):
                    if not chunk:
                        continue
                    downloaded += len(chunk)
                    # Console progress logging
                    try:
                        if total:
                            pct = downloaded * 100.0 / total
                            print(f"[MCUtils] Download {jar_type}-{version}: {downloaded}/{total} bytes ({pct:.1f}%)")
                        else:
                            print(f"[MCUtils] Download {jar_type}-{version}: {downloaded} bytes")
                    except Exception:
                        pass
                    yield chunk

            headers = {
                'Content-Type': 'application/java-archive',
                'Content-Disposition': f'attachment; filename="{jar_type}-{version}.jar"',
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
                'Access-Control-Allow-Headers': 'Content-Type'
            }
            if total:
                headers['Content-Length'] = str(total)
            return app.response_class(generate(), status=200, headers=headers)

        # 0) Sorgente locale in versions/ (salta se ?source=mcutils)
        if source != 'mcutils':
            local_url = get_url_from_versions(jar_type, version)
            if local_url:
                print(f"Using local versions URL for {jar_type} {version}: {local_url}")
                lr = requests.get(local_url, timeout=120, stream=True, allow_redirects=True)
                if lr.status_code == 200:
                    return send_jar(lr)
                # Se l'URL locale non funziona, prosegui con MCUtils/fallback

        # 1) Prova endpoint diretto MCUtils
        primary_url = f"{MCUTILS_BASE_URL}/api/server-jars/{jar_type}/{version}/download"
        print(f"MCUtils direct attempt: {primary_url}")
        resp = requests.get(primary_url, timeout=120, stream=True, allow_redirects=True)

        

        if resp.status_code == 200:
            ctype = resp.headers.get('content-type', '')
            if 'java-archive' in ctype or 'octet-stream' in ctype:
                return send_jar(resp)
            # Alcune risposte possono ancora essere JSON: prova a leggerlo e seguire downloadUrl
            try:
                meta = resp.json()
                download_url = meta.get('downloadUrl') or meta.get('download')
                if download_url:
                    print(f"MCUtils meta provided downloadUrl: {download_url}")
                    dr = requests.get(download_url, timeout=120, stream=True, allow_redirects=True)
                    if dr.status_code == 200:
                        return send_jar(dr)
            except Exception:
                pass

        # 2) Fallback: colpisci endpoint senza /download, leggi JSON e segui downloadUrl
        meta_url = f"{MCUTILS_BASE_URL}/api/server-jars/{jar_type}/{version}"
        print(f"MCUtils fallback meta attempt: {meta_url}")
        mr = requests.get(meta_url, timeout=60, allow_redirects=True)
        if mr.status_code == 404:
            # 3) Try our own fallback URLs when MCUtils has no entry
            fb = get_fallback_jar_url(jar_type, version)
            if fb:
                print(f"Using fallback URL for {jar_type} {version}: {fb}")
                fr = requests.get(fb, timeout=120, stream=True, allow_redirects=True)
                if fr.status_code == 200:
                    return send_jar(fr)
                else:
                    return jsonify({'success': False, 'message': f'Fallback download failed: HTTP {fr.status_code}'}), 502
            return jsonify({'success': False, 'message': 'Versione non trovata'}), 404
        if mr.status_code != 200:
            # Try fallback URL as well
            fb = get_fallback_jar_url(jar_type, version)
            if fb:
                print(f"Using fallback URL for {jar_type} {version}: {fb}")
                fr = requests.get(fb, timeout=120, stream=True, allow_redirects=True)
                if fr.status_code == 200:
                    return send_jar(fr)
                else:
                    return jsonify({'success': False, 'message': f'Fallback download failed: HTTP {fr.status_code}'}), 502
            return jsonify({'success': False, 'message': f'Errore nel download: HTTP {mr.status_code}'}), 500
        try:
            meta = mr.json()
            download_url = meta.get('downloadUrl') or meta.get('download')
            if not download_url:
                return jsonify({'success': False, 'message': 'downloadUrl non presente nella risposta MCUtils'}), 500
            print(f"MCUtils resolved downloadUrl: {download_url}")
            dr = requests.get(download_url, timeout=120, stream=True, allow_redirects=True)
            if dr.status_code == 200:
                return send_jar(dr)
            elif dr.status_code == 404:
                # Try fallback URL
                fb = get_fallback_jar_url(jar_type, version)
                if fb:
                    print(f"Using fallback URL for {jar_type} {version}: {fb}")
                    fr = requests.get(fb, timeout=120, stream=True, allow_redirects=True)
                    if fr.status_code == 200:
                        return send_jar(fr)
                    else:
                        return jsonify({'success': False, 'message': f'Fallback download failed: HTTP {fr.status_code}'}), 502
                return jsonify({'success': False, 'message': 'Versione non trovata'}), 404
            else:
                # Try fallback URL for any other failure
                fb = get_fallback_jar_url(jar_type, version)
                if fb:
                    print(f"Using fallback URL for {jar_type} {version}: {fb}")
                    fr = requests.get(fb, timeout=120, stream=True, allow_redirects=True)
                    if fr.status_code == 200:
                        return send_jar(fr)
                    else:
                        return jsonify({'success': False, 'message': f'Fallback download failed: HTTP {fr.status_code}'}), 502
                return jsonify({'success': False, 'message': f'Errore download JAR: HTTP {dr.status_code}'}), 500
        except ValueError:
            return jsonify({'success': False, 'message': 'Risposta MCUtils non valida'}), 500
    except Exception as e:
        return jsonify({'success': False, 'message': f'Errore: {str(e)}'}), 500

class MinecraftServer:
    def __init__(self, name, port, jar_file, max_memory='1G', platform='minecraft', use_custom_start=False, custom_start_cmd=''):
        self.name = name
        self.port = port
        self.jar_file = jar_file
        self.max_memory = max_memory
        self.platform = platform or 'minecraft'
        self.use_custom_start = bool(use_custom_start)
        self.custom_start_cmd = (custom_start_cmd or '').strip()
        self.process = None
        self.status = 'stopped'
        self.stopping = False  # per distinguere arresto intenzionale da crash
        self.log_file = os.path.join(LOG_DIR, f'{name}.log')
        self.online_players = set()  # Traccia giocatori online
        
    def start(self):
        if self.status == 'running':
            return False, "Server già in esecuzione"
        
        try:
            jar_path = os.path.join(SERVER_DIR, self.name, self.jar_file)
            if not os.path.exists(jar_path):
                return False, f"File JAR non trovato: {jar_path}"
            
            # Per server Minecraft normali richiedi EULA; per Velocity non serve
            if self.platform != 'velocity':
                eula_file = os.path.join(SERVER_DIR, self.name, 'eula.txt')
                if not os.path.exists(eula_file):
                    return False, "EULA_NOT_ACCEPTED"
            
            # Comando per avviare il server
            if self.use_custom_start and self.custom_start_cmd:
                cmd = self.custom_start_cmd
                use_shell = True
            else:
                cmd = [
                    'java', 
                    f'-Xmx{self.max_memory}',
                    f'-Xms{self.max_memory}',
                    '-jar', 
                    jar_path,
                    'nogui'
                ]
                use_shell = False
            
            # Avvia il processo
            with open(self.log_file, 'a') as log:
                self.process = subprocess.Popen(
                    cmd,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.PIPE,
                    text=True,
                    cwd=os.path.join(SERVER_DIR, self.name),
                    shell=use_shell
                )
            
            self.status = 'running'
            running_servers[self.name] = self
            
            # Avvia il monitoraggio del processo
            self.start_process_monitoring()
            
            return True, "Server avviato con successo"
            
        except Exception as e:
            return False, f"Errore nell'avvio: {str(e)}"
    
    def start_process_monitoring(self):
        """Avvia il monitoraggio del processo per rilevare quando si spegne"""
        def monitor_process():
            if self.process:
                self.process.wait()  # Aspetta che il processo termini
                # Il processo è terminato
                self.status = 'stopped'
                self.process = None
                if self.name in running_servers:
                    del running_servers[self.name]
                print(f"Server {self.name} si è spento automaticamente")
                # Invio webhook per arresto anomalo se non è stato uno stop richiesto
                try:
                    if not self.stopping:
                        send_discord_webhook(self.name, 'server_crashed', f"Il server '{self.name}' si è arrestato in modo anomalo")
                    else:
                        # Arresto normale
                        send_discord_webhook(self.name, 'server_stopped', f"Server '{self.name}' arrestato")
                        send_discord_webhook(self.name, 'server_terminated', f"Server '{self.name}' terminato")
                except Exception as e:
                    print(f"Errore invio webhook (monitor): {e}")
                finally:
                    self.stopping = False
        
        # Avvia il monitoraggio in un thread separato
        monitor_thread = threading.Thread(target=monitor_process, daemon=True)
        monitor_thread.start()
    
    def stop(self):
        if self.status != 'running' or not self.process:
            return False, "Server non in esecuzione"
        
        try:
            self.stopping = True
            # Invia comando stop al server
            self.process.stdin.write('stop\n')
            self.process.stdin.flush()
            
            # Aspetta che il processo termini
            self.process.wait(timeout=30)
            
            self.status = 'stopped'
            self.process = None
            if self.name in running_servers:
                del running_servers[self.name]
            
            return True, "Server fermato con successo"
            
        except subprocess.TimeoutExpired:
            # Forza la terminazione se non risponde
            self.process.kill()
            self.status = 'stopped'
            self.process = None
            if self.name in running_servers:
                del running_servers[self.name]
            return True, "Server fermato forzatamente"
        except Exception as e:
            return False, f"Errore nella fermata: {str(e)}"
    
    def send_command(self, command):
        if self.status != 'running' or not self.process:
            return False, "Server non in esecuzione"
        
        try:
            self.process.stdin.write(f'{command}\n')
            self.process.stdin.flush()
            # Webhook: comando ricevuto
            send_discord_webhook(self.name, 'command_received', f"Comando ricevuto: `{command}`")
            return True, "Comando inviato"
        except Exception as e:
            return False, f"Errore nell'invio comando: {str(e)}"
    
    def get_logs(self, lines=100):
        try:
            if os.path.exists(self.log_file):
                with open(self.log_file, 'r', encoding='utf-8', errors='ignore') as f:
                    all_lines = f.readlines()
                    logs = all_lines[-lines:] if len(all_lines) > lines else all_lines
                    # Aggiorna giocatori online quando leggiamo i log
                    self.update_online_players(logs)
                    return logs
            return []
        except Exception as e:
            return [f"Errore nella lettura log: {str(e)}"]
    
    def update_online_players(self, logs):
        """Aggiorna la lista dei giocatori online analizzando i log"""
        try:
            import re
            for log in logs:
                log_lower = log.lower()
                
                # Pattern per connessioni
                if 'joined the game' in log_lower or 'logged in' in log_lower:
                    # Estrai nome giocatore
                    match = re.search(r'(\w+)\s+(?:joined the game|logged in)', log_lower)
                    if match:
                        player_name = match.group(1)
                        self.online_players.add(player_name)
                        # Webhook su match username configurato
                        try:
                            cfg = load_server_internal_config(self.name)
                            wb = (cfg or {}).get('webhook', {})
                            match_user = (wb.get('player_match_username') or '').strip().lower()
                            if match_user and player_name.lower() == match_user and wb.get('triggers', {}).get('player_join_match'):
                                send_discord_webhook(self.name, 'player_join_match', f"L'utente '{player_name}' è entrato nel server")
                        except Exception as e:
                            print(f"Errore invio webhook (player join): {e}")
                
                # Pattern per disconnessioni
                elif 'left the game' in log_lower or 'disconnected' in log_lower:
                    # Estrai nome giocatore
                    match = re.search(r'(\w+)\s+(?:left the game|disconnected)', log_lower)
                    if match:
                        player_name = match.group(1)
                        self.online_players.discard(player_name)
                        
        except Exception as e:
            print(f"Errore nell'aggiornamento giocatori online: {e}")
    
    def get_online_players_count(self):
        """Restituisce il numero di giocatori attualmente online"""
        return len(self.online_players)

# Route principali
@app.route('/')
def dashboard():
    username, user = get_current_user()
    perms = (user or {}).get('permissions', DEFAULT_PERMISSIONS)
    return render_template('dashboard.html', current_user=username, permissions=perms)

@app.route('/login', methods=['GET', 'POST'])
def login():
    users = load_users()
    admin_hash = users.get('admin', {}).get('password_hash')
    info_message = "If this is your first login, click 'Forgot password' and use the password printed in the console."

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if username not in users:
            return render_template('auth/login.html', error='Invalid credentials', info_message=info_message)

        # Verifica password persistente
        if users[username].get('password_hash') and check_password_hash(users[username]['password_hash'], password):
            session['user'] = username
            # Invalida OTP se presente
            otp_info['used'] = True
            otp_info['password'] = None
            next_url = request.args.get('next') or url_for('dashboard')
            return redirect(next_url)

        # Verifica OTP console
        if otp_info['password'] and not otp_info['used']:
            try:
                now = datetime.now(timezone.utc)
                if username == 'admin' and now < otp_info['expires_at'] and password == otp_info['password']:
                    session['user'] = 'admin'
                    otp_info['used'] = True
                    otp_info['password'] = None
                    next_url = request.args.get('next') or url_for('dashboard')
                    return redirect(next_url)
            except Exception:
                pass

        return render_template('auth/login.html', error='Invalid credentials', info_message=info_message)

    # GET
    return render_template('auth/login.html', info_message=info_message)

@app.route('/forgot-password', methods=['POST'])
def forgot_password():
    # Genera password console valida 1 ora
    pwd = generate_console_password()
    expires = datetime.now(timezone.utc) + timedelta(hours=1)
    otp_info['password'] = pwd
    otp_info['expires_at'] = expires
    otp_info['used'] = False
    print('\n================== TEMP ADMIN PASSWORD ==================')
    print(f"Username: admin\nPassword: {pwd}\nValid until (UTC): {expires.isoformat()} (1 hour)")
    print('========================================================\n')
    return render_template('auth/login.html', info_message='Temporary password generated. Check the server console.',
                           success='Temporary password generated. Use the value printed in the console.')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/settings/users', methods=['GET'])
def settings_users():
    if not has_permission('settings_access'):
        abort(403)
    users = load_users()
    return render_template('settings/users.html', users=users, current_user=session.get('user'))

@app.route('/settings/users/password', methods=['POST'])
def update_admin_password():
    if not is_authenticated():
        return redirect(url_for('login'))
    if not has_permission('settings_access'):
        abort(403)
    # Solo admin può cambiare senza password precedente, oppure chiunque cambi la propria chiedendo quella vecchia (non implementato qui)
    if session.get('user') != 'admin':
        return render_template('settings/users.html', error='Solo l\'utente admin può usare questa funzione', users=load_users(), current_user=session.get('user'))
    new_password = request.form.get('new_password', '')
    confirm_password = request.form.get('confirm_password', '')
    if not new_password or len(new_password) < 8:
        return render_template('settings/users.html', error='La nuova password deve avere almeno 8 caratteri', users=load_users(), current_user=session.get('user'))
    if new_password != confirm_password:
        return render_template('settings/users.html', error='Le password non coincidono', users=load_users(), current_user=session.get('user'))
    set_admin_password(new_password)
    # Invalida eventuale OTP ancora attivo
    otp_info['used'] = True
    otp_info['password'] = None
    return render_template('settings/users.html', success='Password admin aggiornata con successo')

# API/Settings per gestione utenti
@app.route('/settings/users/add', methods=['POST'])
def add_user():
    if session.get('user') != 'admin':
        abort(403)
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    perms = {
        'servers_control': request.form.get('servers_control') == 'on',
        'files_access': request.form.get('files_access') == 'on',
        'players_access': request.form.get('players_access') == 'on',
        'stats_view': request.form.get('stats_view') == 'on',
        'settings_access': request.form.get('settings_access') == 'on',
        'config_access': request.form.get('config_access') == 'on',
        'backup_access': request.form.get('backup_access') == 'on',
        'server_stats_access': request.form.get('server_stats_access') == 'on'
    }
    if not username or not password or len(password) < 8:
        return render_template('settings/users.html', error='Dati non validi (password min 8)', users=load_users(), current_user=session.get('user'))
    users = load_users()
    if username in users:
        return render_template('settings/users.html', error='Utente già esistente', users=users, current_user=session.get('user'))
    users[username] = {
        'password_hash': generate_password_hash(password),
        'role': 'user',
        'permissions': perms
    }
    save_users(users)
    return render_template('settings/users.html', success='Utente creato', users=users, current_user=session.get('user'))

@app.route('/settings/users/update', methods=['POST'])
def update_user_permissions():
    if session.get('user') != 'admin':
        abort(403)
    username = request.form.get('username')
    if not username:
        return render_template('settings/users.html', error='Utente non specificato', users=load_users(), current_user=session.get('user'))
    users = load_users()
    if username not in users:
        return render_template('settings/users.html', error='Utente inesistente', users=users, current_user=session.get('user'))
    users[username]['permissions'] = {
        'servers_control': request.form.get('servers_control') == 'on',
        'files_access': request.form.get('files_access') == 'on',
        'players_access': request.form.get('players_access') == 'on',
        'stats_view': request.form.get('stats_view') == 'on',
        'settings_access': request.form.get('settings_access') == 'on',
        'config_access': request.form.get('config_access') == 'on',
        'backup_access': request.form.get('backup_access') == 'on',
        'server_stats_access': request.form.get('server_stats_access') == 'on'
    }
    save_users(users)
    return render_template('settings/users.html', success='Permessi aggiornati', users=users, current_user=session.get('user'))

@app.route('/settings/users/delete', methods=['POST'])
def delete_user():
    if session.get('user') != 'admin':
        abort(403)
    username = request.form.get('username')
    users = load_users()
    if username == 'admin':
        return render_template('settings/users.html', error='Non è possibile eliminare admin', users=users, current_user=session.get('user'))
    if username in users:
        del users[username]
        save_users(users)
        return render_template('settings/users.html', success='Utente eliminato', users=users, current_user=session.get('user'))
    return render_template('settings/users.html', error='Utente inesistente', users=users, current_user=session.get('user'))

@app.route('/servers')
def servers_list():
    username, user = get_current_user()
    perms = (user or {}).get('permissions', DEFAULT_PERMISSIONS)
    return render_template('servers/list.html', current_user=username, permissions=perms)

@app.route('/servers/new')
def servers_new():
    username, user = get_current_user()
    perms = (user or {}).get('permissions', DEFAULT_PERMISSIONS)
    return render_template('servers/new.html', current_user=username, permissions=perms)

@app.route('/servers/<server_name>')
def server_detail(server_name):
    # Verifica che il server esista
    server_path = os.path.join(SERVER_DIR, server_name)
    if not os.path.exists(server_path):
        abort(404)
    
    username, user = get_current_user()
    perms = (user or {}).get('permissions', DEFAULT_PERMISSIONS)
    return render_template('servers/detail.html', server_name=server_name, current_user=username, permissions=perms)

# ===================== SPIGET PROXY ENDPOINTS =====================
SPIGET_BASE = "https://api.spiget.org/v2"

def spiget_get(path, params=None, stream=False):
    url = f"{SPIGET_BASE}{path}"
    r = requests.get(url, params=params or {}, timeout=30, stream=stream)
    r.raise_for_status()
    return r

@app.route('/api/spiget/resources')
def spiget_resources():
    """Lista risorse (proxy) ordinata per downloads desc lato server."""
    try:
        size = int(request.args.get('size', 20))
        page = int(request.args.get('page', 1))
        res = spiget_get('/resources', params={'size': size, 'page': page})
        data = res.json()
        # Ordina per downloads desc se presente
        data.sort(key=lambda x: x.get('downloads', 0), reverse=True)
        return jsonify({'success': True, 'resources': data})
    except requests.HTTPError as he:
        code = he.response.status_code if getattr(he, 'response', None) is not None else 502
        return jsonify({'success': False, 'message': f'Errore Spiget: HTTP {code}'}), code
    except Exception as e:
        return jsonify({'success': False, 'message': f'Errore Spiget: {str(e)}'}), 500

@app.route('/api/spiget/search')
def spiget_search():
    """Ricerca risorse per query, ordinate per downloads desc lato server."""
    try:
        q = request.args.get('q', '').strip()
        size = int(request.args.get('size', 20))
        page = int(request.args.get('page', 1))
        if not q:
            return jsonify({'success': True, 'resources': []})
        # Spiget search endpoint
        res = spiget_get(f"/search/resources/{urllib.parse.quote(q)}", params={'size': size, 'page': page})
        data = res.json()
        data.sort(key=lambda x: x.get('downloads', 0), reverse=True)
        return jsonify({'success': True, 'resources': data})
    except requests.HTTPError as he:
        code = he.response.status_code if getattr(he, 'response', None) is not None else 502
        return jsonify({'success': False, 'message': f'Errore Spiget: HTTP {code}'}), code
    except Exception as e:
        return jsonify({'success': False, 'message': f'Errore Spiget: {str(e)}'}), 500

@app.route('/api/servers/<server_name>/plugins/download', methods=['POST'])
def download_plugin(server_name):
    """Scarica un plugin Spiget nella cartella plugins del server."""
    try:
        if not has_permission('files_access'):
            return jsonify({'success': False, 'message': 'Permesso negato'}), 403
        server_path = os.path.join(SERVER_DIR, server_name)
        if not os.path.isdir(server_path):
            return jsonify({'success': False, 'message': 'Server non trovato'}), 404
        data = request.get_json(silent=True) or {}
        resource_id = data.get('resource_id')
        if not resource_id:
            return jsonify({'success': False, 'message': 'resource_id mancante'}), 400

        # Scarica il file (proxy) – usa endpoint download che redirige al jar
        r = spiget_get(f"/resources/{resource_id}/download", stream=True)

        # Determina filename da Content-Disposition
        filename = f"plugin-{resource_id}.jar"
        cd = r.headers.get('Content-Disposition') or r.headers.get('content-disposition')
        if cd and 'filename=' in cd:
            filename = cd.split('filename=')[-1].strip('"')
        # Assicura estensione jar
        if not filename.lower().endswith('.jar'):
            filename += '.jar'

        plugins_dir = os.path.join(server_path, 'plugins')
        os.makedirs(plugins_dir, exist_ok=True)
        out_path = os.path.join(plugins_dir, secure_filename(filename))

        with open(out_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        return jsonify({'success': True, 'message': f'Plugin salvato in plugins/{os.path.basename(out_path)}'})
    except requests.HTTPError as he:
        return jsonify({'success': False, 'message': f'Errore download: HTTP {he.response.status_code}'}), 502
    except Exception as e:
        return jsonify({'success': False, 'message': f'Errore: {str(e)}'}), 500

@app.route('/api/servers', methods=['GET'])
def get_servers():
    try:
        os.makedirs(SERVER_DIR, exist_ok=True)
        servers = []
        for name in os.listdir(SERVER_DIR):
            server_path = os.path.join(SERVER_DIR, name)
            if os.path.isdir(server_path):
                # Carica configurazione server se esiste
                config_file = os.path.join(server_path, 'server_config.json')
                config = {
                    'name': name,
                    'port': 25565,
                    'jar_file': 'server.jar',
                    'max_memory': '1G',
                    'status': 'stopped'
                }
                
                if os.path.exists(config_file):
                    with open(config_file, 'r') as f:
                        config.update(json.load(f))
                
                # Controlla se il server è in esecuzione
                if name in running_servers:
                    config['status'] = running_servers[name].status
            
                servers.append(config)
        return jsonify(servers)
    except Exception as e:
        return jsonify([])

@app.route('/api/servers/import', methods=['POST'])
def import_server():
    """Importa una cartella server esistente dentro ./servers/<target_name>"""
    try:
        if not has_permission('settings_access'):
            return jsonify({'success': False, 'message': 'Permesso negato'}), 403

        data = request.get_json(silent=True) or {}
        source_path = (data.get('source_path') or '').strip()
        target_name = (data.get('target_name') or '').strip()

        if not source_path or not os.path.isabs(source_path):
            return jsonify({'success': False, 'message': 'Percorso sorgente non valido (usa percorso assoluto)'}), 400
        if not os.path.isdir(source_path):
            return jsonify({'success': False, 'message': 'La cartella sorgente non esiste'}), 400

        # Se non indicato, usa il nome cartella di origine
        if not target_name:
            target_name = os.path.basename(os.path.normpath(source_path))

        # Normalizza nome
        import re
        target_name = re.sub(r'[^a-zA-Z0-9_-]', '-', target_name)
        if not target_name:
            return jsonify({'success': False, 'message': 'Nome di destinazione non valido'}), 400

        dest_path = os.path.join(SERVER_DIR, target_name)
        if os.path.exists(dest_path):
            return jsonify({'success': False, 'message': f"Esiste già un server chiamato '{target_name}'"}), 400

        # Controllo veloce: deve contenere un .jar o server.properties
        contains_jar = any(fn.lower().endswith('.jar') for fn in os.listdir(source_path))
        contains_props = os.path.exists(os.path.join(source_path, 'server.properties'))
        if not (contains_jar or contains_props):
            return jsonify({'success': False, 'message': 'La cartella non sembra contenere un server Minecraft (manca JAR o server.properties)'}), 400

        # Copia ricorsiva
        shutil.copytree(source_path, dest_path)

        # Crea un file di configurazione minimale se non presente
        config_file = os.path.join(dest_path, 'server_config.json')
        if not os.path.exists(config_file):
            cfg = {
                'name': target_name,
                'port': 25565,
                'jar_file': 'server.jar',
                'max_memory': '1G',
                'status': 'stopped'
            }
            try:
                # Prova ad indovinare jar
                jars = [f for f in os.listdir(dest_path) if f.lower().endswith('.jar')]
                if jars:
                    cfg['jar_file'] = jars[0]
            except Exception:
                pass
            with open(config_file, 'w') as f:
                json.dump(cfg, f, indent=2)

        return jsonify({'success': True, 'message': f"Server importato come '{target_name}'"})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Errore import: {str(e)}'}), 500

def create_server_properties(server_path, config):
    """Crea il file server.properties con le configurazioni"""
    properties_file = os.path.join(server_path, 'server.properties')
    
    # Configurazioni di base
    properties = {
        'server-port': str(config.get('port', 25565)),
        'gamemode': config.get('gamemode', 'survival'),
        'difficulty': config.get('difficulty', 'easy'),
        'max-players': str(config.get('max_players', 20)),
        'motd': config.get('motd', 'A Minecraft Server'),
        'level-name': 'world',
        'level-seed': '',
        'level-type': 'minecraft:normal',
        'allow-nether': 'true',
        'announce-player-achievements': 'true',
        'enable-command-block': 'false',
        'spawn-animals': 'true',
        'spawn-monsters': 'true',
        'spawn-npcs': 'true',
        'generate-structures': 'true',
        'online-mode': 'true',
        'pvp': 'true',
        'hardcore': 'false',
        'enable-query': 'false',
        'enable-rcon': 'false',
        'enable-status': 'true',
        'allow-flight': 'false',
        'broadcast-console-to-ops': 'true',
        'broadcast-rcon-to-ops': 'true',
        'enable-jmx-monitoring': 'false',
        'sync-chunk-writes': 'true',
        'enable-whitelist': 'false',
        'enforce-whitelist': 'false',
        'resource-pack': '',
        'resource-pack-sha1': '',
        'resource-pack-id': '',
        'resource-pack-prompt': '',
        'require-resource-pack': 'false',
        'entity-broadcast-range-percentage': '100',
        'function-permission-level': '2',
        'network-compression-threshold': '256',
        'max-tick-time': '60000',
        'max-chained-neighbor-updates': '1000000',
        'rate-limit': '0',
        'simulation-distance': '10',
        'view-distance': '10',
        'spawn-protection': '16',
        'max-world-size': '29999984',
        'server-ip': '',
        'query.port': str(config.get('port', 25565)),
        'rcon.port': '25575',
        'rcon.password': '',
        'log-ips': 'true',
        'prevent-proxy-connections': 'false',
        'use-native-transport': 'true',
        'enable-status': 'true',
        'hide-online-players': 'false',
        'enforce-secure-profile': 'true',
        'log-stats': 'false',
        'force-gamemode': 'false',
        'rate-limit': '0',
        'player-idle-timeout': '0',
        'debug': 'false',
        'hardcore': 'false',
        'enable-command-block': 'false',
        'broadcast-console-to-ops': 'true',
        'broadcast-rcon-to-ops': 'true',
        'enable-jmx-monitoring': 'false',
        'enable-query': 'false',
        'enable-rcon': 'false',
        'enable-status': 'true',
        'enforce-secure-profile': 'true',
        'enforce-whitelist': 'false',
        'entity-broadcast-range-percentage': '100',
        'force-gamemode': 'false',
        'function-permission-level': '2',
        'gamemode': config.get('gamemode', 'survival'),
        'generate-structures': 'true',
        'generator-settings': '{}',
        'hardcore': 'false',
        'hide-online-players': 'false',
        'initial-disabled-packs': '',
        'initial-enabled-packs': 'vanilla',
        'level-name': 'world',
        'level-seed': '',
        'level-type': 'minecraft:normal',
        'log-ips': 'true',
        'max-chained-neighbor-updates': '1000000',
        'max-players': str(config.get('max_players', 20)),
        'max-tick-time': '60000',
        'max-world-size': '29999984',
        'motd': config.get('motd', 'A Minecraft Server'),
        'network-compression-threshold': '256',
        'online-mode': 'true',
        'op-permission-level': '4',
        'pause-when-empty-seconds': '-1',
        'player-idle-timeout': '0',
        'prevent-proxy-connections': 'false',
        'pvp': 'true',
        'query.port': str(config.get('port', 25565)),
        'rate-limit': '0',
        'rcon.password': '',
        'rcon.port': '25575',
        'region-file-compression': 'deflate',
        'require-resource-pack': 'false',
        'resource-pack': '',
        'resource-pack-id': '',
        'resource-pack-prompt': '',
        'resource-pack-sha1': '',
        'server-ip': '',
        'server-port': str(config.get('port', 25565)),
        'simulation-distance': '10',
        'spawn-animals': 'true',
        'spawn-monsters': 'true',
        'spawn-npcs': 'true',
        'spawn-protection': '16',
        'sync-chunk-writes': 'true',
        'text-filtering-config': '',
        'text-filtering-version': '0',
        'use-native-transport': 'true',
        'view-distance': '10',
        'white-list': 'false'
    }
    
    # Scrivi il file server.properties
    with open(properties_file, 'w') as f:
        f.write("#Minecraft server properties\n")
        f.write(f"#{datetime.now().strftime('%a %b %d %H:%M:%S %Z %Y')}\n")
        for key, value in properties.items():
            f.write(f"{key}={value}\n")

def create_velocity_toml(server_path, config):
    cfg = []
    cfg.append('# Config version. Do not change this')
    cfg.append('config-version = "2.7"')
    cfg.append('')
    bind = f"0.0.0.0:{config.get('port', 25565)}"
    cfg.append('# What port should the proxy be bound to? By default, we\'ll bind to all addresses on port 25565.')
    cfg.append(f'bind = "{bind}"')
    cfg.append('')
    motd = config.get('motd', '<#09add3>A Velocity Server')
    cfg.append('# What should be the MOTD? This gets displayed when the player adds your server to')
    cfg.append('# their server list. Only MiniMessage format is accepted.')
    cfg.append(f'motd = "{motd}"')
    cfg.append('')
    cfg.append('# What should we display for the maximum number of players? (Velocity does not support a cap')
    cfg.append('# on the number of players online.)')
    cfg.append(f'show-max-players = {int(config.get("max_players", 500))}')
    cfg.append('')
    cfg.append('# Should we authenticate players with Mojang? By default, this is on.')
    cfg.append(f'online-mode = {str(config.get("online_mode", True)).lower()}')
    cfg.append('')
    cfg.append('# Should the proxy enforce the new public key security standard? By default, this is on.')
    cfg.append('force-key-authentication = true')
    cfg.append('')
    cfg.append('# If client\'s ISP/AS sent from this proxy is different from the one from Mojang\'s')
    cfg.append('# authentication server, the player is kicked. This disallows some VPN and proxy')
    cfg.append('# connections but is a weak form of protection.')
    cfg.append('prevent-client-proxy-connections = false')
    cfg.append('')
    cfg.append('# Should we forward IP addresses and other data to backend servers?')
    cfg.append('player-info-forwarding-mode = "NONE"')
    cfg.append('')
    cfg.append('# Announce whether or not your server supports Forge. If you run a modded server, we')
    cfg.append('announce-forge = false')
    cfg.append('')
    cfg.append('# If enabled (default is false) and the proxy is in online mode, Velocity will kick')
    cfg.append('kick-existing-players = false')
    cfg.append('')
    cfg.append('# Should Velocity pass server list ping requests to a backend server?')
    cfg.append('ping-passthrough = "DISABLED"')
    cfg.append('')
    cfg.append('sample-players-in-ping = false')
    cfg.append('enable-player-address-logging = true')
    cfg.append('')
    cfg.append('[servers]')
    cfg.append('lobby = "127.0.0.1:30066"')
    cfg.append('factions = "127.0.0.1:30067"')
    cfg.append('minigames = "127.0.0.1:30068"')
    cfg.append('try = [')
    cfg.append('    "lobby"')
    cfg.append(']')
    cfg.append('')
    cfg.append('[forced-hosts]')
    cfg.append('"lobby.example.com" = [')
    cfg.append('    "lobby"')
    cfg.append(']')
    cfg.append('"factions.example.com" = [')
    cfg.append('    "factions"')
    cfg.append(']')
    cfg.append('"minigames.example.com" = [')
    cfg.append('    "minigames"')
    cfg.append(']')
    cfg.append('')
    cfg.append('[advanced]')
    cfg.append('compression-threshold = 256')
    cfg.append('compression-level = -1')
    cfg.append('login-ratelimit = 3000')
    cfg.append('connection-timeout = 5000')
    cfg.append('read-timeout = 30000')
    cfg.append('haproxy-protocol = false')
    cfg.append('tcp-fast-open = false')
    cfg.append('bungee-plugin-message-channel = true')
    cfg.append('show-ping-requests = false')
    cfg.append('failover-on-unexpected-server-disconnect = true')
    cfg.append('announce-proxy-commands = true')
    cfg.append('log-command-executions = false')
    cfg.append('log-player-connections = true')
    cfg.append('accepts-transfers = false')
    cfg.append('enable-reuse-port = false')
    cfg.append('command-rate-limit = 50')
    cfg.append('forward-commands-if-rate-limited = true')
    cfg.append('kick-after-rate-limited-commands = 0')
    cfg.append('tab-complete-rate-limit = 10')
    cfg.append('kick-after-rate-limited-tab-completes = 0')
    cfg.append('')
    cfg.append('[query]')
    cfg.append('enabled = false')
    cfg.append('port = 25565')
    cfg.append('map = "Velocity"')
    cfg.append('show-plugins = false')

    cfg_path = get_velocity_toml_path(server_path)
    with open(cfg_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(cfg) + '\n')

@app.route('/api/servers', methods=['POST'])
def create_server():
    data = request.json
    name = data.get('name')
    port = data.get('port', 25565)
    jar_file = data.get('jar_file', 'server.jar')
    platform = data.get('platform', 'minecraft').lower()
    max_memory = data.get('max_memory', '1G')
    
    if not name:
        return jsonify({'success': False, 'message': 'Nome server richiesto'}), 400
    
    server_path = os.path.join(SERVER_DIR, name)
    if os.path.exists(server_path):
        return jsonify({'success': False, 'message': 'Server già esistente'}), 400
    
    try:
        os.makedirs(server_path, exist_ok=True)
        
        # Non generare più automaticamente velocity.toml per Velocity.
        # Per i server Minecraft normali, inizializza server.properties.
        if platform != 'velocity':
            create_server_properties(server_path, data)
        
        # Crea anche un file di configurazione interno per MineBoard
        config = {
            'name': name,
            'port': port,
            'jar_file': jar_file,
            'max_memory': max_memory,
            'platform': platform,
            'status': 'stopped'
        }
        
        config_file = os.path.join(server_path, 'server_config.json')
        with open(config_file, 'w') as f:
            json.dump(config, f, indent=2)
        
        return jsonify({'success': True, 'message': 'Server creato con successo'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Errore nella creazione: {str(e)}'}), 500

@app.route('/api/servers/temp', methods=['POST'])
def create_temp_server():
    """Crea una cartella temporanea per il server"""
    try:
        # Genera un nome temporaneo unico
        import uuid
        temp_name = f"temp_{uuid.uuid4().hex[:8]}"
        temp_path = os.path.join(SERVER_DIR, temp_name)
        
        os.makedirs(temp_path, exist_ok=True)
        
        return jsonify({'success': True, 'temp_name': temp_name, 'message': 'Cartella temporanea creata'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Errore nella creazione cartella temporanea: {str(e)}'}), 500

@app.route('/api/servers/rename', methods=['POST'])
def rename_temp_server():
    """Rinomina una cartella temporanea con il nome finale del server"""
    try:
        data = request.json
        temp_name = data.get('temp_name')
        final_name = data.get('final_name')
        
        if not temp_name or not final_name:
            return jsonify({'success': False, 'message': 'Nome temporaneo e nome finale richiesti'}), 400
        
        temp_path = os.path.join(SERVER_DIR, temp_name)
        final_path = os.path.join(SERVER_DIR, final_name)
        
        if not os.path.exists(temp_path):
            return jsonify({'success': False, 'message': 'Cartella temporanea non trovata'}), 404
        
        if os.path.exists(final_path):
            return jsonify({'success': False, 'message': 'Server con questo nome già esistente'}), 400
        
        # Rinomina la cartella
        os.rename(temp_path, final_path)
        
        # Aggiorna il file di configurazione se esiste
        config_file = os.path.join(final_path, 'server_config.json')
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                config = json.load(f)
            config['name'] = final_name
            with open(config_file, 'w') as f:
                json.dump(config, f, indent=2)
        
        return jsonify({'success': True, 'message': 'Server rinominato con successo'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Errore nel rinominare: {str(e)}'}), 500

@app.route('/api/servers/move-jar', methods=['POST'])
def move_jar_from_temp():
    """Sposta un JAR dalla cartella temporanea al server finale"""
    try:
        data = request.json
        temp_name = data.get('temp_name')
        final_name = data.get('final_name')
        jar_filename = data.get('jar_filename', 'server.jar')
        
        if not temp_name or not final_name:
            return jsonify({'success': False, 'message': 'Nome temporaneo e nome finale richiesti'}), 400
        
        temp_path = os.path.join(SERVER_DIR, temp_name)
        final_path = os.path.join(SERVER_DIR, final_name)
        
        if not os.path.exists(temp_path):
            return jsonify({'success': False, 'message': 'Cartella temporanea non trovata'}), 404
        
        if not os.path.exists(final_path):
            return jsonify({'success': False, 'message': 'Server finale non trovato'}), 404
        
        # Sposta il JAR dalla cartella temporanea a quella finale
        temp_jar_path = os.path.join(temp_path, jar_filename)
        final_jar_path = os.path.join(final_path, jar_filename)
        
        if os.path.exists(temp_jar_path):
            shutil.move(temp_jar_path, final_jar_path)
            # Webhook: JAR aggiornato
            try:
                send_discord_webhook(final_name, 'jar_updated', f"Eseguibile del server aggiornato: {jar_filename}")
            except Exception as e:
                print(f"Errore webhook jar_updated: {e}")
            # Pulisci la cartella temporanea
            shutil.rmtree(temp_path)
            
            return jsonify({'success': True, 'message': 'JAR spostato con successo'})
        else:
            # Se non c'è JAR da spostare, pulisci comunque la cartella temporanea
            shutil.rmtree(temp_path)
            return jsonify({'success': True, 'message': 'Cartella temporanea pulita'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Errore nello spostamento JAR: {str(e)}'}), 500

def read_server_properties(server_path):
    """Legge il file server.properties e restituisce un dizionario"""
    properties_file = os.path.join(server_path, 'server.properties')
    properties = {}
    
    if os.path.exists(properties_file):
        with open(properties_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    if '=' in line:
                        key, value = line.split('=', 1)
                        properties[key] = value
    
    return properties

def write_server_properties(server_path, properties):
    """Scrive le proprietà nel file server.properties"""
    properties_file = os.path.join(server_path, 'server.properties')
    
    with open(properties_file, 'w') as f:
        f.write("#Minecraft server properties\n")
        f.write(f"#{datetime.now().strftime('%a %b %d %H:%M:%S %Z %Y')}\n")
        for key, value in properties.items():
            f.write(f"{key}={value}\n")

def get_velocity_toml_path(server_path):
    return os.path.join(server_path, 'velocity.toml')

@app.route('/api/servers/<server_name>/velocity-config', methods=['GET'])
def get_velocity_config(server_name):
    """Ritorna il contenuto di velocity.toml se presente"""
    if not has_permission('config_access'):
        return jsonify({'success': False, 'message': 'Permesso negato'}), 403
    server_path = os.path.join(SERVER_DIR, server_name)
    if not os.path.exists(server_path):
        return jsonify({'success': False, 'message': 'Server non trovato'}), 404
    try:
        cfg_path = get_velocity_toml_path(server_path)
        if not os.path.exists(cfg_path):
            return jsonify({'success': True, 'exists': False, 'content': ''})
        with open(cfg_path, 'r', encoding='utf-8', errors='ignore') as f:
            return jsonify({'success': True, 'exists': True, 'content': f.read()})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Errore: {str(e)}'}), 500

@app.route('/api/servers/<server_name>/velocity-config', methods=['POST'])
def save_velocity_config(server_name):
    """Salva il contenuto di velocity.toml"""
    if not has_permission('config_access'):
        return jsonify({'success': False, 'message': 'Permesso negato'}), 403
    server_path = os.path.join(SERVER_DIR, server_name)
    if not os.path.exists(server_path):
        return jsonify({'success': False, 'message': 'Server non trovato'}), 404
    try:
        data = request.get_json() or {}
        content = data.get('content', '')
        if content is None:
            return jsonify({'success': False, 'message': 'Contenuto mancante'}), 400
        cfg_path = get_velocity_toml_path(server_path)
        with open(cfg_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return jsonify({'success': True, 'message': 'velocity.toml salvato'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Errore: {str(e)}'}), 500

@app.route('/api/servers/<server_name>/properties', methods=['GET'])
def get_server_properties(server_name):
    """Ottieni le proprietà del server"""
    if not has_permission('config_access'):
        return jsonify({'success': False, 'message': 'Permesso negato'}), 403
    server_path = os.path.join(SERVER_DIR, server_name)
    if not os.path.exists(server_path):
        return jsonify({'success': False, 'message': 'Server non trovato'}), 404
    
    try:
        properties = read_server_properties(server_path)
        return jsonify({'success': True, 'properties': properties})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Errore: {str(e)}'}), 500

@app.route('/api/servers/<server_name>/properties', methods=['POST'])
def update_server_properties(server_name):
    """Aggiorna le proprietà del server"""
    if not has_permission('config_access'):
        return jsonify({'success': False, 'message': 'Permesso negato'}), 403
    server_path = os.path.join(SERVER_DIR, server_name)
    if not os.path.exists(server_path):
        return jsonify({'success': False, 'message': 'Server non trovato'}), 404
    
    try:
        data = request.json
        properties = data.get('properties', {})
        
        # Leggi le proprietà esistenti
        existing_properties = read_server_properties(server_path)
        
        # Aggiorna solo le proprietà fornite
        existing_properties.update(properties)
        
        # Scrivi le proprietà aggiornate
        write_server_properties(server_path, existing_properties)
        
        return jsonify({'success': True, 'message': 'Proprietà aggiornate con successo'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Errore: {str(e)}'}), 500

@app.route('/api/servers/<server_name>/config', methods=['GET'])
def get_server_config(server_name):
    """Ottiene la configurazione interna del server (server_config.json)"""
    server_path = os.path.join(SERVER_DIR, server_name)
    config_file = os.path.join(server_path, 'server_config.json')
    if not os.path.exists(server_path) or not os.path.exists(config_file):
        return jsonify({'success': False, 'message': 'Server non trovato'}), 404
    try:
        with open(config_file, 'r') as f:
            cfg = json.load(f)
        return jsonify({'success': True, 'config': cfg})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Errore: {str(e)}'}), 500

@app.route('/api/servers/<server_name>/config', methods=['POST'])
def update_server_config(server_name):
    """Aggiorna parti della configurazione interna del server (es. max_memory)"""
    server_path = os.path.join(SERVER_DIR, server_name)
    config_file = os.path.join(server_path, 'server_config.json')
    if not os.path.exists(server_path) or not os.path.exists(config_file):
        return jsonify({'success': False, 'message': 'Server non trovato'}), 404
    try:
        data = request.get_json() or {}
        with open(config_file, 'r') as f:
            cfg = json.load(f)

        # Consenti aggiornare solo alcuni campi in modo sicuro
        if 'max_memory' in data:
            cfg['max_memory'] = str(data['max_memory']).strip()
        if 'port' in data:
            try:
                cfg['port'] = int(data['port'])
            except Exception:
                pass
        if 'jar_file' in data:
            cfg['jar_file'] = str(data['jar_file']).strip()
        if 'use_custom_start' in data:
            cfg['use_custom_start'] = bool(data['use_custom_start'])
        if 'custom_start_cmd' in data:
            cfg['custom_start_cmd'] = str(data['custom_start_cmd']).strip()

        with open(config_file, 'w') as f:
            json.dump(cfg, f, indent=2)
        return jsonify({'success': True, 'message': 'Configurazione aggiornata', 'config': cfg})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Errore: {str(e)}'}), 500

@app.route('/api/servers/<server_name>/eula', methods=['POST'])
def accept_eula(server_name):
    """Accetta l'EULA per il server"""
    if not has_permission('config_access'):
        return jsonify({'success': False, 'message': 'Permesso negato'}), 403
    server_path = os.path.join(SERVER_DIR, server_name)
    if not os.path.exists(server_path):
        return jsonify({'success': False, 'message': 'Server non trovato'}), 404
    
    try:
        eula_file = os.path.join(server_path, 'eula.txt')
        with open(eula_file, 'w') as f:
            f.write("#By changing the setting below to TRUE you are indicating your agreement to our EULA (https://aka.ms/MinecraftEULA).\n")
            f.write(f"#{datetime.now().strftime('%a %b %d %H:%M:%S %Z %Y')}\n")
            f.write("eula=true\n")
        
        return jsonify({'success': True, 'message': 'EULA accettata con successo'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Errore: {str(e)}'}), 500

@app.route('/api/servers/<server_name>/eula', methods=['GET'])
def check_eula(server_name):
    """Controlla se l'EULA è stata accettata"""
    if not has_permission('config_access'):
        return jsonify({'success': False, 'message': 'Permesso negato'}), 403
    server_path = os.path.join(SERVER_DIR, server_name)
    if not os.path.exists(server_path):
        return jsonify({'success': False, 'message': 'Server non trovato'}), 404
    
    eula_file = os.path.join(server_path, 'eula.txt')
    eula_accepted = os.path.exists(eula_file)
    
    return jsonify({'success': True, 'eula_accepted': eula_accepted})

@app.route('/api/servers/<server_name>/start', methods=['POST'])
def start_server(server_name):
    if not has_permission('servers_control'):
        return jsonify({'success': False, 'message': 'Permesso negato'}), 403
    config_file = os.path.join(SERVER_DIR, server_name, 'server_config.json')
    if not os.path.exists(config_file):
        return jsonify({'success': False, 'message': 'Server non trovato'}), 404
    
    with open(config_file, 'r') as f:
        config = json.load(f)
    
    server = MinecraftServer(
        config['name'],
        config['port'],
        config['jar_file'],
        config['max_memory'],
        config.get('platform', 'minecraft'),
        config.get('use_custom_start', False),
        config.get('custom_start_cmd', '')
    )
    
    success, message = server.start()
    
    if not success and message == "EULA_NOT_ACCEPTED":
        return jsonify({'success': False, 'message': 'EULA_NOT_ACCEPTED', 'eula_required': True})
    # Webhook: server avviato
    if success:
        try:
            send_discord_webhook(server_name, 'server_started', f"Server '{server_name}' avviato")
        except Exception as e:
            print(f"Errore webhook start: {e}")
    return jsonify({'success': success, 'message': message})

@app.route('/api/servers/<server_name>/stop', methods=['POST'])
def stop_server(server_name):
    if not has_permission('servers_control'):
        return jsonify({'success': False, 'message': 'Permesso negato'}), 403
    if server_name not in running_servers:
        return jsonify({'success': False, 'message': 'Server non in esecuzione'}), 400
    server = running_servers[server_name]
    success, message = server.stop()
    return jsonify({'success': success, 'message': message})

@app.route('/api/servers/<server_name>/command', methods=['POST'])
def send_command(server_name):
    if not has_permission('servers_control'):
        return jsonify({'success': False, 'message': 'Permesso negato'}), 403
    if server_name not in running_servers:
        return jsonify({'success': False, 'message': 'Server non in esecuzione'}), 400
    try:
        data = request.get_json() or {}
        command = (data.get('command') or '').strip()
        if not command:
            return jsonify({'success': False, 'message': 'Comando vuoto'}), 400
        server = running_servers[server_name]
        success, message = server.send_command(command)
        return jsonify({'success': success, 'message': message})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Errore: {str(e)}'}), 500

@app.route('/api/servers/<server_name>/webhook', methods=['GET'])
def get_webhook_config(server_name):
    if not has_permission('config_access'):
        return jsonify({'success': False, 'message': 'Permesso negato'}), 403
    try:
        cfg = load_server_internal_config(server_name)
        return jsonify({'success': True, 'webhook': cfg.get('webhook', {})})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Errore: {str(e)}'}), 500

@app.route('/api/servers/<server_name>/webhook', methods=['POST'])
def save_webhook_config(server_name):
    if not has_permission('config_access'):
        return jsonify({'success': False, 'message': 'Permesso negato'}), 403
    try:
        data = request.get_json() or {}
        cfg = load_server_internal_config(server_name)
        wb = cfg.get('webhook', {})
        url = (data.get('url') or '').strip()
        triggers = data.get('triggers') or {}
        player_match_username = (data.get('player_match_username') or '').strip()
        if url is not None:
            wb['url'] = url
        wb.setdefault('triggers', {})
        for key in ['server_started','server_stopped','server_crashed','backup_completed','jar_updated','command_received','server_terminated','player_join_match']:
            if key in triggers:
                wb['triggers'][key] = bool(triggers[key])
        wb['player_match_username'] = player_match_username
        cfg['webhook'] = wb
        ok = save_server_internal_config(server_name, cfg)
        return jsonify({'success': ok, 'message': 'Configurazione webhook salvata' if ok else 'Salvataggio fallito'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Errore: {str(e)}'}), 500

@app.route('/api/servers/<server_name>/webhook/test', methods=['POST'])
def test_webhook(server_name):
    if not has_permission('config_access'):
        return jsonify({'success': False, 'message': 'Permesso negato'}), 403
    try:
        sent = send_discord_webhook(server_name, 'server_started', f"Test webhook su server '{server_name}'")
        return jsonify({'success': bool(sent), 'message': 'Webhook inviato' if sent else 'Webhook non configurato o trigger disabilitato'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Errore: {str(e)}'}), 500

# Gestione errori
# File Manager API Routes
@app.route('/api/files/<server_name>/<path:filepath>')
def get_file_content(server_name, filepath):
    if not has_permission('files_access'):
        return jsonify({'success': False, 'message': 'Permesso negato'}), 403
    """Leggi il contenuto di un file"""
    server_path = os.path.join(SERVER_DIR, server_name)
    full_path = os.path.join(server_path, filepath)
    
    if not os.path.exists(server_path):
        return jsonify({'success': False, 'message': 'Server non trovato'}), 404
    
    if not os.path.exists(full_path):
        return jsonify({'success': False, 'message': 'File non trovato'}), 404
    
    if os.path.isdir(full_path):
        return jsonify({'success': False, 'message': 'È una cartella, non un file'}), 400
    
    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return jsonify({'success': True, 'content': content})
    except UnicodeDecodeError:
        return jsonify({'success': False, 'message': 'File binario non supportato'}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': f'Errore: {str(e)}'}), 500

@app.route('/api/files/<server_name>', methods=['GET'])
def list_files(server_name):
    """Lista i contenuti della cartella del server. Facoltativamente ?path=subdir"""
    if not has_permission('files_access'):
        return jsonify({'success': False, 'message': 'Permesso negato'}), 403
    server_path = os.path.join(SERVER_DIR, server_name)
    if not os.path.exists(server_path):
        return jsonify({'success': False, 'message': 'Server non trovato'}), 404
    rel = (request.args.get('path') or '').strip()
    target = os.path.normpath(os.path.join(server_path, rel))
    # Evita traversal
    if not target.startswith(server_path):
        return jsonify({'success': False, 'message': 'Percorso non valido'}), 400
    if not os.path.exists(target):
        return jsonify({'success': False, 'message': 'Percorso non trovato'}), 404
    try:
        entries = []
        for name in os.listdir(target):
            fp = os.path.join(target, name)
            try:
                st = os.stat(fp)
                is_dir = os.path.isdir(fp)
                # Costruisci path relativo da server root
                rel_path = name if not rel else f"{rel}/{name}"
                entries.append({
                    'name': name,
                    'type': 'directory' if is_dir else 'file',
                    'size': st.st_size,
                    'modified': datetime.fromtimestamp(st.st_mtime).isoformat(),
                    'path': rel_path
                })
            except Exception:
                continue
        # Ordina: cartelle prima, poi file, entrambi alfabetici
        entries.sort(key=lambda e: (e['type'] != 'directory', e['name'].lower()))
        # Calcola parent_path per breadcrumb/back
        parent_path = ''
        if rel:
            parts = rel.strip('/').split('/')
            parent_path = '/'.join(parts[:-1])
        return jsonify({'success': True, 'current_path': rel, 'parent_path': parent_path, 'files': entries})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Errore: {str(e)}'}), 500

@app.route('/api/files/<server_name>/<path:filepath>', methods=['PUT'])
def save_file_content(server_name, filepath):
    if not has_permission('files_access'):
        return jsonify({'success': False, 'message': 'Permesso negato'}), 403
    """Salva il contenuto di un file"""
    server_path = os.path.join(SERVER_DIR, server_name)
    full_path = os.path.join(server_path, filepath)
    
    if not os.path.exists(server_path):
        return jsonify({'success': False, 'message': 'Server non trovato'}), 404
    
    try:
        data = request.get_json()
        content = data.get('content', '')
        
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return jsonify({'success': True, 'message': 'File salvato con successo'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Errore: {str(e)}'}), 500

@app.route('/api/files/<server_name>/<path:filepath>', methods=['DELETE'])
def delete_file(server_name, filepath):
    if not has_permission('files_access'):
        return jsonify({'success': False, 'message': 'Permesso negato'}), 403
    """Elimina un file o cartella"""
    server_path = os.path.join(SERVER_DIR, server_name)
    full_path = os.path.join(server_path, filepath)
    
    if not os.path.exists(server_path):
        return jsonify({'success': False, 'message': 'Server non trovato'}), 404
    
    if not os.path.exists(full_path):
        return jsonify({'success': False, 'message': 'File non trovato'}), 404
    
    try:
        if os.path.isdir(full_path):
            shutil.rmtree(full_path)
            return jsonify({'success': True, 'message': 'Cartella eliminata con successo'})
        else:
            os.remove(full_path)
            return jsonify({'success': True, 'message': 'File eliminato con successo'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Errore: {str(e)}'}), 500

@app.route('/api/files/<server_name>/<path:filepath>', methods=['POST'])
def rename_file(server_name, filepath):
    if not has_permission('files_access'):
        return jsonify({'success': False, 'message': 'Permesso negato'}), 403
    """Rinomina un file o cartella"""
    server_path = os.path.join(SERVER_DIR, server_name)
    full_path = os.path.join(server_path, filepath)
    
    if not os.path.exists(server_path):
        return jsonify({'success': False, 'message': 'Server non trovato'}), 404
    
    if not os.path.exists(full_path):
        return jsonify({'success': False, 'message': 'File non trovato'}), 404
    
    try:
        data = request.get_json()
        new_name = data.get('new_name', '').strip()
        
        if not new_name:
            return jsonify({'success': False, 'message': 'Nome non valido'}), 400
        
        new_path = os.path.join(os.path.dirname(full_path), new_name)
        
        if os.path.exists(new_path):
            return jsonify({'success': False, 'message': 'Un file con questo nome esiste già'}), 400
        
        os.rename(full_path, new_path)
        return jsonify({'success': True, 'message': 'File rinominato con successo'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Errore: {str(e)}'}), 500

@app.route('/api/files/<server_name>/upload-blob', methods=['POST'])
def upload_blob(server_name):
    """Carica un file (base64) nella cartella del server specificato."""
    if not has_permission('files_access'):
        return jsonify({'success': False, 'message': 'Permesso negato'}), 403
    try:
        data = request.get_json() or {}
        filename = (data.get('filename') or '').strip()
        file_data = data.get('file_data')
        if not filename or not file_data:
            return jsonify({'success': False, 'message': 'Parametri mancanti'}), 400
        safe_name = secure_filename(filename)
        if not safe_name:
            return jsonify({'success': False, 'message': 'Nome file non valido'}), 400
        server_path = os.path.join(SERVER_DIR, server_name)
        if not os.path.exists(server_path):
            return jsonify({'success': False, 'message': 'Server non trovato'}), 404
        os.makedirs(server_path, exist_ok=True)
        out_path = os.path.join(server_path, safe_name)
        # Decodifica base64 e salva
        try:
            raw = base64.b64decode(file_data)
        except Exception:
            return jsonify({'success': False, 'message': 'Base64 non valido'}), 400
        with open(out_path, 'wb') as f:
            f.write(raw)
        return jsonify({'success': True, 'message': f'File caricato: {safe_name}'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Errore: {str(e)}'}), 500

@app.route('/api/files/<server_name>/upload', methods=['POST'])
def upload_file(server_name):
    """Carica un file via multipart/form-data nella cartella del server (con percorso opzionale)."""
    if not has_permission('files_access'):
        return jsonify({'success': False, 'message': 'Permesso negato'}), 403
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'message': 'Nessun file nella richiesta'}), 400
        file = request.files['file']
        if not file or file.filename.strip() == '':
            return jsonify({'success': False, 'message': 'Nome file mancante'}), 400
        # Percorso relativo opzionale all'interno del server
        rel_path = (request.form.get('path') or '').strip()
        server_path = os.path.join(SERVER_DIR, server_name)
        if not os.path.isdir(server_path):
            return jsonify({'success': False, 'message': 'Server non trovato'}), 404
        # Costruisci destinazione sicura
        safe_filename = secure_filename(file.filename)
        dest_dir = os.path.join(server_path, rel_path) if rel_path else server_path
        os.makedirs(dest_dir, exist_ok=True)
        dest_path = os.path.join(dest_dir, safe_filename)
        file.save(dest_path)
        return jsonify({'success': True, 'message': f"File caricato: {os.path.relpath(dest_path, server_path)}"})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Errore: {str(e)}'}), 500

@app.route('/api/files/<server_name>/create-folder', methods=['POST'])
def create_folder(server_name):
    if not has_permission('files_access'):
        return jsonify({'success': False, 'message': 'Permesso negato'}), 403
    """Crea una nuova cartella"""
    server_path = os.path.join(SERVER_DIR, server_name)
    
    if not os.path.exists(server_path):
        return jsonify({'success': False, 'message': 'Server non trovato'}), 404
    
    try:
        data = request.get_json()
        folder_name = data.get('folder_name', '').strip()
        current_path = data.get('current_path', '')
        
        if not folder_name:
            return jsonify({'success': False, 'message': 'Nome cartella non valido'}), 400
        
        full_path = os.path.join(server_path, current_path, folder_name)
        
        if os.path.exists(full_path):
            return jsonify({'success': False, 'message': 'Una cartella con questo nome esiste già'}), 400
        
        os.makedirs(full_path, exist_ok=True)
        return jsonify({'success': True, 'message': 'Cartella creata con successo'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Errore: {str(e)}'}), 500

@app.route('/api/files/<server_name>/download/<path:filepath>')
def download_file(server_name, filepath):
    if not has_permission('files_access'):
        return jsonify({'success': False, 'message': 'Permesso negato'}), 403
    """Scarica un file"""
    server_path = os.path.join(SERVER_DIR, server_name)
    full_path = os.path.join(server_path, filepath)
    
    if not os.path.exists(server_path):
        return jsonify({'success': False, 'message': 'Server non trovato'}), 404
    
    if not os.path.exists(full_path):
        return jsonify({'success': False, 'message': 'File non trovato'}), 404
    
    if os.path.isdir(full_path):
        return jsonify({'success': False, 'message': 'È una cartella, non un file'}), 400
    
    try:
        return send_file(full_path, as_attachment=True)
    except Exception as e:
        return jsonify({'success': False, 'message': f'Errore: {str(e)}'}), 500

@app.route('/api/servers/<server_name>/logs')
def get_logs(server_name):
    """Ritorna gli ultimi log del server se disponibile."""
    if server_name in running_servers:
        server = running_servers[server_name]
        logs = server.get_logs()
        return jsonify({'success': True, 'logs': logs})
    # Se non in esecuzione, prova a leggere file di log su disco
    log_file = os.path.join(LOG_DIR, f'{server_name}.log')
    if os.path.exists(log_file):
        try:
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            return jsonify({'success': True, 'logs': lines[-200:]})
        except Exception:
            pass
    return jsonify({'success': False, 'message': 'Server non in esecuzione'}), 404

@app.route('/api/servers/<server_name>/players')
def get_players(server_name):
    """Ritorna lista giocatori online se disponibile (per Velocity ritorna vuoto)."""
    if not has_permission('players_access'):
        return jsonify({'success': False, 'message': 'Permesso negato'}), 403
    if server_name in running_servers:
        server = running_servers[server_name]
        try:
            # Converte set in lista
            players = sorted(list(getattr(server, 'online_players', set())))
            return jsonify({'success': True, 'players': players})
        except Exception:
            return jsonify({'success': True, 'players': []})
    return jsonify({'success': True, 'players': []})

@app.route('/api/servers/<server_name>/stats')
def get_server_stats(server_name):
    """Statistiche di base del server e di sistema."""
    if not has_permission('server_stats_access'):
        return jsonify({'success': False, 'message': 'Permesso negato'}), 403
    status = 'stopped'
    pid = None
    players = 0
    tps = None
    if server_name in running_servers:
        srv = running_servers[server_name]
        status = srv.status
        proc = srv.process
        pid = proc.pid if proc else None
        try:
            players = len(getattr(srv, 'online_players', []) or [])
        except Exception:
            players = 0
        # Se il server espone TPS, leggilo; altrimenti lascia None
        tps = getattr(srv, 'tps', None)
    try:
        cpu_percent = psutil.cpu_percent(interval=0.1)
        mem_info = psutil.virtual_memory()
        memory_percent = float(mem_info.percent)
        stats = {
            'tps': tps,
            'cpu_percent': float(cpu_percent) if cpu_percent is not None else None,
            'memory_percent': memory_percent,
            'players': players,
            'status': status,
            'pid': pid,
        }
        return jsonify({'success': True, 'stats': stats})
    except Exception as e:
        return jsonify({'success': True, 'stats': {'tps': tps, 'players': players, 'status': status, 'pid': pid}})

@app.route('/api/servers/<server_name>', methods=['DELETE'])
def delete_server(server_name):
    """Elimina definitivamente il server specificato (cartella, log e backup opzionale)."""
    if not has_permission('settings_access'):
        return jsonify({'success': False, 'message': 'Permesso negato'}), 403
    server_path = os.path.join(SERVER_DIR, server_name)
    if not os.path.exists(server_path):
        return jsonify({'success': False, 'message': 'Server non trovato'}), 404
    try:
        # Ferma se in esecuzione
        if server_name in running_servers:
            try:
                running_servers[server_name].stop()
            except Exception:
                pass
        # Rimuovi cartella server
        shutil.rmtree(server_path)
        # Rimuovi file log se presente
        log_file = os.path.join(LOG_DIR, f'{server_name}.log')
        if os.path.exists(log_file):
            try:
                os.remove(log_file)
            except Exception:
                pass
        return jsonify({'success': True, 'message': f"Server '{server_name}' eliminato"})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Errore nell\'eliminazione: {str(e)}'}), 500

# Backup API Routes
@app.route('/api/servers/<server_name>/backups')
def get_backups(server_name):
    """Ottieni lista backup del server"""
    if not has_permission('backup_access'):
        return jsonify({'success': False, 'message': 'Permesso negato'}), 403
    try:
        server_backup_dir = os.path.join(BACKUP_DIR, server_name)
        if not os.path.exists(server_backup_dir):
            return jsonify({'success': True, 'backups': []})
        
        backups = []
        for filename in os.listdir(server_backup_dir):
            if filename.endswith('.zip'):
                filepath = os.path.join(server_backup_dir, filename)
                stat = os.stat(filepath)
                backups.append({
                    'name': filename.replace('.zip', ''),
                    'created': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    'size': stat.st_size
                })
        
        # Ordina per data di creazione (più recenti prima)
        backups.sort(key=lambda x: x['created'], reverse=True)
        
        return jsonify({'success': True, 'backups': backups})
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Errore: {str(e)}'}), 500

@app.route('/api/servers/<server_name>/backups', methods=['POST'])
def create_backup(server_name):
    """Crea un nuovo backup del server"""
    if not has_permission('backup_access'):
        return jsonify({'success': False, 'message': 'Permesso negato'}), 403
    try:
        server_path = os.path.join(SERVER_DIR, server_name)
        if not os.path.exists(server_path):
            return jsonify({'success': False, 'message': 'Server non trovato'}), 404
        
        # Ottieni nome backup
        data = request.get_json() or {}
        backup_name = data.get('name', '').strip()
        
        if not backup_name:
            backup_name = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Crea directory backup per il server
        server_backup_dir = os.path.join(BACKUP_DIR, server_name)
        os.makedirs(server_backup_dir, exist_ok=True)
        
        # Crea file zip
        backup_file = os.path.join(server_backup_dir, f"{backup_name}.zip")
        
        with zipfile.ZipFile(backup_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(server_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, server_path)
                    
                    # Escludi file problematici
                    if (file.endswith('.log') and 'latest.log' in file) or \
                       file.endswith('.tmp') or \
                       file.startswith('.') or \
                       file in ['session.lock', 'usercache.json']:
                        continue  # Salta file che possono causare problemi
                    
                    try:
                        zipf.write(file_path, arcname)
                    except Exception as e:
                        print(f"Errore nel backup di {file_path}: {e}")
                        continue  # Continua con gli altri file
        
        # Webhook su backup completato
        try:
            send_discord_webhook(server_name, 'backup_completed', f"Backup '{backup_name}' completato")
        except Exception as e:
            print(f"Errore webhook backup: {e}")
        return jsonify({'success': True, 'message': f'Backup "{backup_name}" creato con successo'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Errore: {str(e)}'}), 500

@app.route('/api/servers/<server_name>/backups/<backup_name>/restore', methods=['POST'])
def restore_backup(server_name, backup_name):
    """Ripristina un backup del server"""
    if not has_permission('backup_access'):
        return jsonify({'success': False, 'message': 'Permesso negato'}), 403
    try:
        server_path = os.path.join(SERVER_DIR, server_name)
        backup_file = os.path.join(BACKUP_DIR, server_name, f"{backup_name}.zip")
        
        if not os.path.exists(backup_file):
            return jsonify({'success': False, 'message': 'Backup non trovato'}), 404
        
        # Ferma il server se è in esecuzione
        if server_name in running_servers:
            server = running_servers[server_name]
            if server.status == 'running':
                server.stop()
        
        # Rimuovi directory server esistente
        if os.path.exists(server_path):
            shutil.rmtree(server_path)
        
        # Ricrea directory server
        os.makedirs(server_path, exist_ok=True)
        
        # Estrai backup con gestione errori
        with zipfile.ZipFile(backup_file, 'r') as zipf:
            # Verifica l'integrità del file ZIP
            try:
                zipf.testzip()
            except Exception as e:
                return jsonify({'success': False, 'message': f'File ZIP corrotto: {str(e)}'}), 500
            
            # Estrai file per file per gestire errori individuali
            for member in zipf.infolist():
                try:
                    zipf.extract(member, server_path)
                except Exception as e:
                    print(f"Errore nell'estrazione di {member.filename}: {e}")
                    # Continua con gli altri file invece di fermarsi
                    continue
        
        return jsonify({'success': True, 'message': f'Backup "{backup_name}" ripristinato con successo'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Errore: {str(e)}'}), 500

@app.route('/api/servers/<server_name>/backups/<backup_name>', methods=['DELETE'])
def delete_backup(server_name, backup_name):
    """Elimina un backup del server"""
    if not has_permission('backup_access'):
        return jsonify({'success': False, 'message': 'Permesso negato'}), 403
    try:
        backup_file = os.path.join(BACKUP_DIR, server_name, f"{backup_name}.zip")
        
        if not os.path.exists(backup_file):
            return jsonify({'success': False, 'message': 'Backup non trovato'}), 404
        
        os.remove(backup_file)
        
        return jsonify({'success': True, 'message': f'Backup "{backup_name}" eliminato con successo'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Errore: {str(e)}'}), 500

@app.route('/api/system/stats')
def system_stats():
    """Statistiche di sistema per la dashboard (CPU, memoria, disco)."""
    try:
        cpu_percent = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        memory_percent = float(mem.percent)
        disk = psutil.disk_usage('/')
        disk_percent = float(disk.percent)
        return jsonify({
            'success': True,
            'stats': {
                'cpu_percent': float(cpu_percent),
                'memory_percent': memory_percent,
                'disk_percent': disk_percent
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'Errore: {str(e)}'}), 500

@app.errorhandler(404)
def not_found(error):
    # Rispondi in JSON per le API, HTML per il resto
    if request.path.startswith('/api/'):
        return jsonify({'success': False, 'message': 'Risorsa non trovata'}), 404
    return render_template('error.html', error_code=404, error_message='Pagina non trovata'), 404

@app.errorhandler(500)
def internal_error(error):
    if request.path.startswith('/api/'):
        return jsonify({'success': False, 'message': 'Errore interno del server'}), 500
    return render_template('error.html', error_code=500, error_message='Errore interno del server'), 500

if __name__ == '__main__':
    print("🚀 Avvio MineBoard Dashboard...")
    print(f"📁 Directory server: {SERVER_DIR}")
    print(f"📝 Directory log: {LOG_DIR}")
    print("🌐 Server disponibile su: http://localhost:8999")
    # Avvia il checker versione in background (ogni 2 minuti)
    try:
        t = threading.Thread(target=background_version_checker, daemon=True)
        t.start()
    except Exception:
        pass
    # Quick version check at startup (non-bloccante)
    try:
        latest = fetch_latest_version()
        if latest and compare_versions(APP_VERSION, latest) != 0:
            print(f"[UPDATE] Nuova versione disponibile: {latest} (installata: {APP_VERSION}). Scarica: {UPDATE_PAGE_URL}")
    except Exception:
        pass
    # Usa un server WSGI di produzione per evitare l'avviso del dev server
    try:
        from waitress import serve
        serve(app, host='0.0.0.0', port=8999)
    except ImportError:
        # Fallback se waitress non è installato
        app.run(host='0.0.0.0', port=8999, debug=False)
