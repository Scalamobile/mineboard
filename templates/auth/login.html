// MineBoard - JavaScript Comune

// Funzioni di utilità
function showNotification(message, type = 'success') {
    const notification = document.getElementById('notification');
    if (!notification) return;
    
    notification.textContent = message;
    notification.className = `notification ${type}`;
    notification.classList.add('show');
    
    setTimeout(() => {
        notification.classList.remove('show');
    }, 3000);
}

// Inietta un pannello per impostare il comando di avvio personalizzato nel dettaglio del server
async function initCustomStartPanel(serverName) {
    const container = document.querySelector('.container') || document.body;

    const card = document.createElement('div');
    card.className = 'card';
    card.style.marginTop = '20px';
    card.style.maxWidth = '900px';
    card.innerHTML = `
        <div class="card-header">
            <i class="fas fa-terminal"></i>
            <h2>Avvio Personalizzato</h2>
        </div>
        <div style="padding: 15px; text-align: left;">
            <div class="form-group" style="display:flex; align-items:center; gap:6px;">
                <input type="checkbox" id="use_custom_start_cb" style="margin:0; width:auto;">
                <label for="use_custom_start_cb" style="margin:0;">Usa comando personalizzato per avviare il server</label>
            </div>
            <div class="form-group">
                <label for="custom_start_cmd_ta">Comando di Avvio</label>
                <textarea id="custom_start_cmd_ta" rows="3" placeholder="Esempio: java -Xmx2G -Xms2G -jar server.jar nogui"></textarea>
                <div style="color:#666; margin-top:6px;">
                    - Il comando viene eseguito nella cartella del server <code>servers/${serverName}/</code>.
                    <br>
                    - Se abilitato, il comando viene lanciato come shell script (shell=true).
                    <br>
                    - I log vanno in <code>logs/${serverName}.log</code>.
                </div>
            </div>
            <div style="display:flex; gap:8px; justify-content:flex-start; align-items:center;">
                <button id="save_custom_start_btn" class="btn btn-success" style="margin:0;"><i class="fas fa-save"></i> Salva</button>
            </div>
        </div>
    `;

    container.appendChild(card);

    // Carica configurazione attuale
    try {
        const data = await apiCall(`/api/servers/${encodeURIComponent(serverName)}/config`);
        const cfg = (data && data.config) || {};
        document.getElementById('use_custom_start_cb').checked = !!cfg.use_custom_start;
        document.getElementById('custom_start_cmd_ta').value = cfg.custom_start_cmd || '';
    } catch (e) {
        // già notificato
    }

    // Salvataggio
    const saveBtn = document.getElementById('save_custom_start_btn');
    saveBtn.addEventListener('click', async () => {
        const useCustom = document.getElementById('use_custom_start_cb').checked;
        const cmd = document.getElementById('custom_start_cmd_ta').value;
        try {
            const res = await apiCall(`/api/servers/${encodeURIComponent(serverName)}/config`, {
                method: 'POST',
                body: JSON.stringify({ use_custom_start: useCustom, custom_start_cmd: cmd })
            });
            showNotification(res.message || 'Impostazioni salvate', 'success');
        } catch (e) {}
    });
}

function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

function formatDate(timestamp) {
    return new Date(timestamp).toLocaleString();
}

// Funzioni API
async function apiCall(url, options = {}) {
    try {
        const response = await fetch(url, {
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            },
            ...options
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.message || 'Errore nella richiesta');
        }
        
        return data;
    } catch (error) {
        console.error('API Error:', error);
        showNotification(error.message, 'error');
        throw error;
    }
}

// Gestione tab
function initTabs() {
    const tabs = document.querySelectorAll('.nav-tab');
    const contents = document.querySelectorAll('.tab-content');
    
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const targetId = tab.getAttribute('data-tab');
            
            // Rimuovi active da tutti
            tabs.forEach(t => t.classList.remove('active'));
            contents.forEach(c => c.classList.remove('active'));
            
            // Aggiungi active al tab e contenuto selezionati
            tab.classList.add('active');
            const targetContent = document.getElementById(targetId);
            if (targetContent) {
                targetContent.classList.add('active');
            }
        });
    });
}

// Inizializzazione comune
document.addEventListener('DOMContentLoaded', function() {
    initTabs();
    initThemeSwitcher();
    
    // Aggiungi notifiche se non esistono
    if (!document.getElementById('notification')) {
        const notification = document.createElement('div');
        notification.id = 'notification';
        document.body.appendChild(notification);
    }

    // Inietta pannello solo nella pagina dettaglio server
    try {
        const m = window.location.pathname.match(/^\/servers\/([^\/]+)\/?$/);
        if (m && m[1]) {
            const serverName = decodeURIComponent(m[1]);
            initCustomStartPanel(serverName);
        }
    } catch (e) {
        console.warn('Init custom start panel error:', e);
    }
});

// Gestione tema
function initThemeSwitcher() {
    const themeToggle = document.getElementById('theme-toggle');
    if (!themeToggle) return;

    const currentTheme = localStorage.getItem('theme') || 'light';
    document.body.classList.toggle('dark-mode', currentTheme === 'dark');
    themeToggle.checked = currentTheme === 'dark';

    themeToggle.addEventListener('change', function() {
        const isDarkMode = this.checked;
        document.body.classList.toggle('dark-mode', isDarkMode);
        localStorage.setItem('theme', isDarkMode ? 'dark' : 'light');
    });
}
