# ccm – Claude Code Manager

Alle Claude-Code-Sessions in tmux, live in einem Dashboard. Mit Enter springst du hinein, mit **Ctrl-Q** wieder heraus. Claude arbeitet währenddessen im Hintergrund weiter.

```
 ◆ ccm  Claude Code Sessions                         ⠹ 1 aktiv   ▲ 1 wartet   ● 1 fertig
    NAME      STATUS                ORDNER              AKTIVITÄT
▌ ⠹ api       arbeitet · 2m         ~/dev/api main      Bash · Run tests  [3/7]
  ▲ shop      Freigabe nötig · 10s  ~/dev/shop          → Bash · rm -rf dist
  ● docs      fertig · 1m           ~/dev/docs          „Die Doku ist aktualisiert …“
── api ⠹ arbeitet ─────────────────────────────────────────────────── ⇥  Live  Verlauf ──
  (Live-Bildschirm der gewählten Session)
```

## Voraussetzungen

| | Version | Wozu |
|---|---|---|
| [Claude Code](https://github.com/anthropics/claude-code) | aktuell | die Sessions selbst |
| tmux | 3.3 oder neuer empfohlen | jede Session läuft in tmux |
| Python 3 | 3.7 oder neuer | ccm selbst – nur Standardbibliothek, kein `pip` |
| git | beliebig | zum Herunterladen und Aktualisieren |

ccm läuft auf **Linux** und **macOS**. Unter **Windows** läuft es in **WSL** (tmux gibt es nicht nativ für Windows).

## Installation

### Linux

```sh
# 1. Abhängigkeiten
sudo apt install tmux python3 git          # Debian / Ubuntu / Raspberry Pi OS
# sudo dnf install tmux python3 git        # Fedora
# sudo pacman -S tmux python git           # Arch

# 2. Claude Code (falls noch nicht installiert)
curl -fsSL https://claude.ai/install.sh | bash

# 3. ccm
git clone https://github.com/onem0/ccm.git ~/.ccm
~/.ccm/install.sh
```

### macOS

```sh
# 1. Abhängigkeiten (Homebrew: https://brew.sh)
brew install tmux git
xcode-select --install       # liefert python3, falls noch nicht vorhanden (alternativ: brew install python)

# 2. Claude Code (falls noch nicht installiert)
curl -fsSL https://claude.ai/install.sh | bash

# 3. ccm
git clone https://github.com/onem0/ccm.git ~/.ccm
~/.ccm/install.sh
```

Falls das Skript meldet, dass `~/.local/bin` nicht im `PATH` ist (bei macOS üblich):

```sh
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
```

Danach das Terminal neu öffnen.

### Windows (über WSL)

1. **WSL installieren.** PowerShell *als Administrator* öffnen:
   ```powershell
   wsl --install
   ```
   Den PC neu starten. Danach öffnet sich Ubuntu und fragt nach Benutzername und Passwort.
2. **Terminal:** am besten das [Windows Terminal](https://aka.ms/terminal) mit dem Profil „Ubuntu“ benutzen. Dort funktionieren Farben, Unicode und Tastenkürzel richtig.
3. **In Ubuntu (WSL)** genau wie unter Linux weitermachen:
   ```sh
   sudo apt update && sudo apt install tmux python3 git
   curl -fsSL https://claude.ai/install.sh | bash      # Claude Code *in* WSL installieren
   git clone https://github.com/onem0/ccm.git ~/.ccm
   ~/.ccm/install.sh
   ```

Wichtig unter Windows:

- Claude Code muss **in WSL** installiert sein. Eine Windows-Installation von Claude Code kann ccm nicht benutzen.
- Projekte am besten im Linux-Dateisystem ablegen (z.B. `~/dev/...`). Windows-Laufwerke liegen unter `/mnt/c/...`, dort ist alles deutlich langsamer.
- Später startest du ccm, indem du „Ubuntu“ im Windows Terminal öffnest und `ccm` eingibst.

### Was `install.sh` macht

- prüft Python, tmux und Claude Code und sagt dir, was fehlt
- legt `ccm` und `ccn` als Links in `~/.local/bin` an (anderer Ordner: `CCM_BIN=/usr/local/bin ./install.sh`)
- weist dich darauf hin, falls `~/.local/bin` nicht im `PATH` ist

Der geklonte Ordner (`~/.ccm`) muss bestehen bleiben, denn die Befehle verweisen dorthin. Ohne Skript geht es auch von Hand:

```sh
ln -s ~/.ccm/ccm ~/.local/bin/ccm
ln -s ~/.ccm/ccm ~/.local/bin/ccn
```

### Aktualisieren

```sh
git -C ~/.ccm pull
```

### Deinstallieren

```sh
~/.ccm/install.sh --uninstall           # entfernt die Befehle ccm und ccn
rm -rf ~/.ccm ~/.local/share/ccm        # optional: Code und Daten löschen
```

## Schnellstart

```sh
cd ~/dev/mein-projekt
ccn                    # neue Claude-Session hier starten und direkt öffnen
                       # … Ctrl-Q bringt dich zurück ins Terminal
ccm                    # Dashboard mit allen Sessions
```

## Befehle

| Befehl | Was passiert |
|---|---|
| `ccm` | Dashboard öffnen |
| `ccn` | neue Session im **aktuellen Ordner** starten und direkt öffnen |
| `ccn "Fix die Tests"` | dasselbe, Claude legt sofort mit der Aufgabe los |
| `ccn --model sonnet` | unbekannte Optionen gehen direkt an `claude` |
| `ccn -d "Aufgabe"` | im Hintergrund starten, nicht öffnen |
| `ccm a [name]` | Session öffnen (ohne Name: die im aktuellen Ordner) |
| `ccm ls` | alle Sessions mit Status auflisten (`--json` für Skripte) |
| `ccm peek <name>` | Bildschirm einer Session ansehen, ohne sie zu öffnen |
| `ccm send <name> <text>` | Nachricht an eine Session schicken |
| `ccm kill <name>` | Claude stoppen (bleibt in der Liste, fortsetzbar) |
| `ccm resume <name>` | gestoppte Session fortsetzen (`--fresh`: ohne Verlauf) |
| `ccm rename <alt> <neu>` / `ccm rm <name>` | umbenennen / entfernen |
| `ccm help` | alle Optionen |

## Dashboard-Tasten

`↑↓`/`jk` wählen · `↵` öffnen (gestoppte werden fortgesetzt) · `n` neue Session (Ordnersuche mit Tab-Vervollständigung) · `s` Nachricht senden · `1`–`9` Freigabe/Rückfrage direkt beantworten · `r` umbenennen · `x` stoppen/entfernen · `F` frisch starten · `Tab` Live ↔ Verlauf · `/` filtern · `o` sortieren · `v` Vorschau · `?` Hilfe · `q` schließen

## Wie es funktioniert

- Jede Session ist eine tmux-Session auf einem eigenen Server (`tmux -L ccm ls`). Deine eigenen tmux-Sessions werden nicht berührt.
- Der tmux-Server hat **kein Prefix**, damit es keinen Konflikt mit Claudes `Ctrl-B` gibt. Einzige Taste: `Ctrl-Q` = zurück. Unten zeigt eine Statuszeile, welche anderen Sessions gerade warten oder fertig sind.
- Claude startet mit `--settings ~/.local/share/ccm/claude-hooks.json`. Die Hooks melden jedes Event (Prompt, Tool, Freigabe, fertig …) an `ccm`. Deine `~/.claude/settings.json` bleibt unverändert.
- Zusätzlich wird der Bildschirm jeder Session ausgewertet. So stimmt der Status auch nach einem Esc-Abbruch oder bei Dialogen.
- Gestoppte Sessions (auch nach einem Neustart des Rechners) werden mit `claude --resume <id>` genau dort fortgesetzt.

## Dateien

- Code: `ccm.py` = Logik und CLI, `ccm_ui.py` = Dashboard, `ccm` = Startskript. Nur Python-Standardbibliothek.
- Befehle: `~/.local/bin/ccm` und `~/.local/bin/ccn` (Links auf das Startskript `ccm` im Repo)
- Daten: `~/.local/share/ccm/`
- Optional `~/.config/ccm/config.json`, z.B. für Standard-Argumente jeder neuen Session:
  ```json
  { "claude_args": ["--model", "sonnet"] }
  ```
  Liegt `claude` nicht im `PATH`, kannst du den Pfad hier mit `"claude": "/pfad/zu/claude"` angeben.
- Optional `~/.config/ccm/tmux.conf` für eigene tmux-Einstellungen (wird zuletzt geladen).
