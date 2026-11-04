#!/bin/sh
# ccm – Installation für Linux, macOS und Windows (WSL).
#
#   ./install.sh               Befehle ccm und ccn nach ~/.local/bin verlinken
#   ./install.sh --uninstall   Links wieder entfernen (Daten bleiben erhalten)
#
# Anderer Zielordner:  CCM_BIN=/usr/local/bin ./install.sh

set -eu

DIR=$(cd "$(dirname "$0")" && pwd -P)
BIN=${CCM_BIN:-"$HOME/.local/bin"}

if [ -t 1 ]; then
    R=$(printf '\033[31m'); G=$(printf '\033[32m'); Y=$(printf '\033[33m'); B=$(printf '\033[1m'); N=$(printf '\033[0m')
else
    R=; G=; Y=; B=; N=
fi
ok()   { printf '  %s✓%s %s\n' "$G" "$N" "$1"; }
warn() { printf '  %s!%s %s\n' "$Y" "$N" "$1"; }
die()  { printf '  %s✗%s %s\n' "$R" "$N" "$1" >&2; exit 1; }

case $(uname -s) in
    Darwin) OS=macos ;;
    Linux)  if grep -qi microsoft /proc/version 2>/dev/null; then OS=wsl; else OS=linux; fi ;;
    *)      die "Nicht unterstütztes System: $(uname -s). Unter Windows bitte in WSL installieren." ;;
esac

if [ "$OS" = macos ]; then
    HINT_TMUX="brew install tmux"
    HINT_PY="xcode-select --install   (oder: brew install python)"
else
    HINT_TMUX="sudo apt install tmux   (Fedora: sudo dnf install tmux · Arch: sudo pacman -S tmux)"
    HINT_PY="sudo apt install python3"
fi

# ── Deinstallation ──────────────────────────────────────────────────────────
if [ "${1:-}" = "--uninstall" ] || [ "${1:-}" = "uninstall" ]; then
    printf '%sccm deinstallieren%s\n' "$B" "$N"
    for c in ccm ccn; do
        if [ -L "$BIN/$c" ] && [ "$(readlink "$BIN/$c")" = "$DIR/ccm" ]; then
            rm "$BIN/$c" && ok "$BIN/$c entfernt"
        fi
    done
    printf '\nDaten (Sessions, Hooks) liegen weiterhin in %s\n' "${XDG_DATA_HOME:-$HOME/.local/share}/ccm"
    printf 'Komplett löschen: rm -rf "%s" "%s"\n' "${XDG_DATA_HOME:-$HOME/.local/share}/ccm" "$DIR"
    exit 0
fi

printf '%sccm installieren%s (%s)\n' "$B" "$N" "$OS"

# ── Voraussetzungen ─────────────────────────────────────────────────────────
command -v python3 >/dev/null 2>&1 || die "python3 fehlt → $HINT_PY"
python3 -c 'import sys; sys.exit(sys.version_info < (3, 7))' \
    || die "Python 3.7 oder neuer nötig (gefunden: $(python3 -V 2>&1)) → $HINT_PY"
python3 -c 'import curses' 2>/dev/null || die "Python-Modul curses fehlt → $HINT_PY"
ok "$(python3 -V 2>&1)"

if command -v tmux >/dev/null 2>&1; then
    TV=$(tmux -V | sed 's/[^0-9.]*\([0-9][0-9]*\.[0-9][0-9]*\).*/\1/')
    if echo "$TV" | awk -F. '{ exit !($1 > 3 || ($1 == 3 && $2 >= 3)) }'; then
        ok "tmux $TV"
    else
        warn "tmux $TV gefunden – empfohlen ist 3.3 oder neuer (ältere Versionen gehen meist, einzelne Optionen fehlen)"
    fi
else
    die "tmux fehlt → $HINT_TMUX"
fi

if command -v claude >/dev/null 2>&1; then
    ok "Claude Code gefunden ($(command -v claude))"
else
    warn "claude nicht im PATH – Claude Code installieren:  curl -fsSL https://claude.ai/install.sh | bash"
fi

# ── Befehle verlinken ───────────────────────────────────────────────────────
chmod +x "$DIR/ccm"
mkdir -p "$BIN"
for c in ccm ccn; do
    if [ -e "$BIN/$c" ] && [ ! -L "$BIN/$c" ]; then
        die "$BIN/$c existiert bereits und ist kein Link – bitte selbst prüfen und entfernen"
    fi
    ln -sfn "$DIR/ccm" "$BIN/$c"
    ok "$BIN/$c → $DIR/ccm"
done

# ── PATH prüfen ─────────────────────────────────────────────────────────────
case ":$PATH:" in
    *":$BIN:"*) ;;
    *)
        case ${SHELL:-} in
            */zsh)  RC="~/.zshrc" ;;
            */bash) if [ "$OS" = macos ]; then RC="~/.bash_profile"; else RC="~/.bashrc"; fi ;;
            */fish) RC= ;;
            *)      RC="~/.profile" ;;
        esac
        printf '\n'
        warn "$BIN ist nicht im PATH. Einmalig ausführen und Terminal neu öffnen:"
        if [ -n "$RC" ]; then
            printf "      echo 'export PATH=\"%s:\$PATH\"' >> %s\n" "$BIN" "$RC"
        else
            printf '      fish_add_path %s\n' "$BIN"
        fi
        ;;
esac

printf '\n%sFertig.%s Im Projektordner %sccn%s starten, Übersicht mit %sccm%s, Hilfe: ccm help\n' \
    "$G" "$N" "$B" "$N" "$B" "$N"
printf 'Der Ordner %s muss bestehen bleiben (die Befehle sind Links dorthin).\n' "$DIR"
