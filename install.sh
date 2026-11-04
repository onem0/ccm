#!/bin/sh
# ccm – installer for Linux, macOS and Windows (WSL).
#
#   ./install.sh               link the ccm and ccn commands into ~/.local/bin
#   ./install.sh --uninstall   remove the links again (data is kept)
#
# Different target folder:  CCM_BIN=/usr/local/bin ./install.sh

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
    *)      die "Unsupported system: $(uname -s). On Windows, please install inside WSL." ;;
esac

if [ "$OS" = macos ]; then
    HINT_TMUX="brew install tmux"
    HINT_PY="xcode-select --install   (or: brew install python)"
else
    HINT_TMUX="sudo apt install tmux   (Fedora: sudo dnf install tmux · Arch: sudo pacman -S tmux)"
    HINT_PY="sudo apt install python3"
fi

# ── Uninstall ───────────────────────────────────────────────────────────────
if [ "${1:-}" = "--uninstall" ] || [ "${1:-}" = "uninstall" ]; then
    printf '%sUninstalling ccm%s\n' "$B" "$N"
    for c in ccm ccn; do
        if [ -L "$BIN/$c" ] && [ "$(readlink "$BIN/$c")" = "$DIR/ccm" ]; then
            rm "$BIN/$c" && ok "removed $BIN/$c"
        fi
    done
    printf '\nData (sessions, hooks) is still in %s\n' "${XDG_DATA_HOME:-$HOME/.local/share}/ccm"
    printf 'To delete everything: rm -rf "%s" "%s"\n' "${XDG_DATA_HOME:-$HOME/.local/share}/ccm" "$DIR"
    exit 0
fi

printf '%sInstalling ccm%s (%s)\n' "$B" "$N" "$OS"

# ── Requirements ────────────────────────────────────────────────────────────
command -v python3 >/dev/null 2>&1 || die "python3 is missing → $HINT_PY"
python3 -c 'import sys; sys.exit(sys.version_info < (3, 7))' \
    || die "Python 3.7 or newer is required (found: $(python3 -V 2>&1)) → $HINT_PY"
python3 -c 'import curses' 2>/dev/null || die "Python module curses is missing → $HINT_PY"
ok "$(python3 -V 2>&1)"

if command -v tmux >/dev/null 2>&1; then
    TV=$(tmux -V | sed 's/[^0-9.]*\([0-9][0-9]*\.[0-9][0-9]*\).*/\1/')
    if echo "$TV" | awk -F. '{ exit !($1 > 3 || ($1 == 3 && $2 >= 3)) }'; then
        ok "tmux $TV"
    else
        warn "found tmux $TV – 3.3 or newer is recommended (older versions mostly work, a few options are missing)"
    fi
else
    die "tmux is missing → $HINT_TMUX"
fi

if command -v claude >/dev/null 2>&1; then
    ok "found Claude Code ($(command -v claude))"
else
    warn "claude is not in PATH – install Claude Code:  curl -fsSL https://claude.ai/install.sh | bash"
fi

# ── Link the commands ───────────────────────────────────────────────────────
chmod +x "$DIR/ccm"
mkdir -p "$BIN"
for c in ccm ccn; do
    if [ -e "$BIN/$c" ] && [ ! -L "$BIN/$c" ]; then
        die "$BIN/$c already exists and is not a symlink – please check it and remove it yourself"
    fi
    ln -sfn "$DIR/ccm" "$BIN/$c"
    ok "$BIN/$c → $DIR/ccm"
done

# ── Check PATH ──────────────────────────────────────────────────────────────
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
        warn "$BIN is not in your PATH. Run this once, then open a new terminal:"
        if [ -n "$RC" ]; then
            printf "      echo 'export PATH=\"%s:\$PATH\"' >> %s\n" "$BIN" "$RC"
        else
            printf '      fish_add_path %s\n' "$BIN"
        fi
        ;;
esac

printf '\n%sDone.%s Run %sccn%s in a project folder, %sccm%s for the dashboard, help: ccm help\n' \
    "$G" "$N" "$B" "$N" "$B" "$N"
printf 'Keep the folder %s – the commands are links into it.\n' "$DIR"
