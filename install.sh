#!/bin/sh
# ccm – installer for Linux, macOS and Windows (WSL).
#
# One-liner (no clone needed, ccm then updates itself from GitHub on every start):
#   curl -fsSL https://raw.githubusercontent.com/onem0/ccm/refs/heads/main/install.sh | sh
#   curl -fsSL https://raw.githubusercontent.com/onem0/ccm/refs/heads/main/install.sh | sh -s -- --uninstall
#
# From a git clone (for development – links the commands to that clone, no auto-update):
#   ./install.sh
#   ./install.sh --uninstall
#
# Environment:  CCM_BIN   where to put the ccm/ccn commands  (default ~/.local/bin)
#               CCM_HOME  where the one-liner puts the code   (default ~/.local/share/ccm/app)
#               CCM_REPO  git URL to install from             (default: this GitHub repo)

set -eu

REPO=${CCM_REPO:-"https://github.com/onem0/ccm.git"}
BRANCH="main"
DATA_DIR=${CCM_DATA:-"${XDG_DATA_HOME:-$HOME/.local/share}/ccm"}
APP=${CCM_HOME:-"$DATA_DIR/app"}
BIN=${CCM_BIN:-"$HOME/.local/bin"}
export GIT_TERMINAL_PROMPT=0

if [ -t 1 ]; then
    R=$(printf '\033[31m'); G=$(printf '\033[32m'); Y=$(printf '\033[33m'); B=$(printf '\033[1m'); N=$(printf '\033[0m')
else
    R=; G=; Y=; B=; N=
fi
ok()   { printf '  %s✓%s %s\n' "$G" "$N" "$1"; }
warn() { printf '  %s!%s %s\n' "$Y" "$N" "$1"; }
die()  { printf '  %s✗%s %s\n' "$R" "$N" "$1" >&2; exit 1; }

# Run as a file from inside a ccm checkout → local mode, otherwise (curl | sh) → download from GitHub.
MODE=remote
DIR=$APP
case $0 in
    *install.sh)
        here=$(cd "$(dirname "$0")" && pwd -P)
        if [ -f "$here/ccm.py" ] && [ -f "$here/ccm" ]; then MODE=local; DIR=$here; fi ;;
esac

case $(uname -s) in
    Darwin) OS=macos ;;
    Linux)  if grep -qi microsoft /proc/version 2>/dev/null; then OS=wsl; else OS=linux; fi ;;
    *)      die "Unsupported system: $(uname -s). On Windows, please install inside WSL." ;;
esac

if [ "$OS" = macos ]; then
    HINT_TMUX="brew install tmux"
    HINT_PY="xcode-select --install   (or: brew install python)"
    HINT_GIT="xcode-select --install   (or: brew install git)"
else
    HINT_TMUX="sudo apt install tmux   (Fedora: sudo dnf install tmux · Arch: sudo pacman -S tmux)"
    HINT_PY="sudo apt install python3"
    HINT_GIT="sudo apt install git"
fi

# ── Uninstall ───────────────────────────────────────────────────────────────
if [ "${1:-}" = "--uninstall" ] || [ "${1:-}" = "uninstall" ]; then
    printf '%sUninstalling ccm%s\n' "$B" "$N"
    found=
    for c in ccm ccn; do
        if [ -L "$BIN/$c" ] && [ "$(readlink "$BIN/$c")" = "$DIR/ccm" ]; then
            rm "$BIN/$c" && ok "removed $BIN/$c" && found=1
        fi
    done
    if [ -f "$DIR/.ccm-managed" ]; then
        rm -rf "$DIR" && ok "removed $DIR" && found=1
    fi
    [ -n "$found" ] || warn "nothing to remove for $DIR"
    printf '\nYour sessions and settings are kept in %s\n' "$DATA_DIR"
    printf 'To delete them too: rm -rf "%s"\n' "$DATA_DIR"
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

if [ "$MODE" = remote ]; then
    command -v git >/dev/null 2>&1 || die "git is missing → $HINT_GIT"
    ok "$(git --version)"
fi

if command -v claude >/dev/null 2>&1; then
    ok "found Claude Code ($(command -v claude))"
else
    warn "claude is not in PATH – install Claude Code:  curl -fsSL https://claude.ai/install.sh | bash"
fi

# ── Download / update from GitHub (one-liner only) ──────────────────────────
if [ "$MODE" = remote ]; then
    mkdir -p "$DATA_DIR" && chmod 700 "$DATA_DIR"
    if [ -d "$APP/.git" ]; then
        git -C "$APP" fetch -q --depth 1 origin "$BRANCH" || die "could not reach GitHub ($REPO)"
        git -C "$APP" reset -q --hard FETCH_HEAD
        rm -rf "$APP/__pycache__"
        ok "updated $APP ($(git -C "$APP" rev-parse --short HEAD))"
    elif [ -e "$APP" ]; then
        die "$APP already exists and is not a ccm download – please check it and remove it yourself"
    else
        mkdir -p "$(dirname "$APP")"
        git clone -q --depth 1 --branch "$BRANCH" "$REPO" "$APP" || die "could not download ccm from $REPO"
        ok "downloaded ccm to $APP ($(git -C "$APP" rev-parse --short HEAD))"
    fi
    : > "$APP/.ccm-managed"     # marks this copy for auto-updates
fi

# ── Link the commands ───────────────────────────────────────────────────────
chmod +x "$DIR/ccm"
mkdir -p "$BIN"
for c in ccm ccn; do
    if [ -e "$BIN/$c" ] && [ ! -L "$BIN/$c" ]; then
        die "$BIN/$c already exists and is not a symlink – please check it and remove it yourself"
    fi
    if [ -L "$BIN/$c" ] && [ "$(readlink "$BIN/$c")" != "$DIR/ccm" ]; then
        warn "$BIN/$c pointed to $(readlink "$BIN/$c") – replacing it"
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
if [ "$MODE" = remote ]; then
    printf 'ccm updates itself from GitHub every time you start it.\n'
else
    printf 'Linked to the git clone %s – update it yourself with git pull (no auto-update).\n' "$DIR"
fi
