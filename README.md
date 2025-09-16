# MineBoard

Dashboard web per la gestione di server Minecraft. Include console live, log viewer, file manager, gestione multi‑server, backup e webhook.

## Caratteristiche
- Gestione multipli server Minecraft (avvio/stop/riavvio)
- Console in tempo reale e visualizzazione log
- File manager (upload, download, modifica, rinomina, elimina)
- Backup e ripristino
- Gestione utenti, ruoli e permessi
- Integrazione webhook (es. Discord) per eventi del server
- Download/aggiornamento JAR (Paper/Spigot/Vanilla, ecc.) con fallback

## Requisiti
- Python 3.10+ (consigliato 3.11)
- pip
- (Opzionale) Git

Le dipendenze Python sono elencate in `requirements.txt` (Flask, Werkzeug, psutil, requests).

## Avvio rapido

### Linux/macOS
```bash
./start.sh
```
Lo script:
- crea un virtualenv `mineboard/`
- installa le dipendenze
- crea le cartelle `servers/`, `logs/`, `uploads/`
- avvia l'applicazione

### Windows
Esegui con doppio click oppure da terminale:
```bat
start.bat
```
Lo script:
- crea un virtualenv `mineboard\`
- installa le dipendenze
- crea le cartelle `servers/`, `logs/`, `uploads/`
- avvia l'applicazione

Dopo l'avvio, apri il browser su:
- http://localhost:8999

## Avvio manuale (alternativa)
```bash
# 1) Creazione e attivazione virtualenv
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 2) Installazione dipendenze
pip install -r requirements.txt

# 3) Esecuzione
python app.py
```

## Struttura del progetto
- `app.py` — Applicazione Flask e logica di backend
- `templates/` — Template HTML (Jinja2)
- `static/` — File statici (`css/`, `js/`)
- `versions/` — Liste versioni JAR e mapping URL
- `start.sh` / `start.bat` — Script di avvio rapidi
- `requirements.txt` — Dipendenze Python

Alla prima esecuzione vengono create cartelle utili in automatico: `servers/`, `logs/`, `uploads/`, `backups/`.

## Note su autenticazione e permessi
- Alla prima esecuzione viene creato un utente `admin`.
- Ti verrà richiesto di configurare la password al primo accesso o dalle impostazioni utenti.
- I permessi sono granulari (es. controllo server, accesso file, statistiche, impostazioni, backup, ecc.).

## Porte e configurazione
- Per impostazione predefinita l'app è accessibile su `http://localhost:8999` (come indicato negli script di avvio).
- Le directory principali sono gestite in `app.py` (es. `servers/`, `logs/`, `uploads/`, `backups/`, `versions/`).

## Troubleshooting
- Verifica la versione di Python con `python3 --version` (o `python --version` su Windows).
- Se le dipendenze non si installano, assicurati che `pip` punti al virtualenv attivo.
- Controlla i log del terminale in cui avvii l'app per eventuali tracce di errore.

## Licenza
Questo progetto è distribuito con licenza MIT. Vedi il file `LICENSE` per i dettagli.
