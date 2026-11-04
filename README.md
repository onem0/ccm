# ccm – Claude Code Manager

All your Claude Code sessions in tmux, live in one dashboard. Press Enter to jump into a session and **Ctrl-Q** to jump back out. Claude keeps working in the background.

```
 ◆ ccm  Claude Code Sessions                         ⠹ 1 aktiv   ▲ 1 wartet   ● 1 fertig
    NAME      STATUS                ORDNER              AKTIVITÄT
▌ ⠹ api       arbeitet · 2m         ~/dev/api main      Bash · Run tests  [3/7]
  ▲ shop      Freigabe nötig · 10s  ~/dev/shop          → Bash · rm -rf dist
  ● docs      fertig · 1m           ~/dev/docs          „Die Doku ist aktualisiert …“
── api ⠹ arbeitet ─────────────────────────────────────────────────── ⇥  Live  Verlauf ──
  (live screen of the selected session)
```

> **Note:** the interface itself (dashboard, status labels, `ccm help`) is currently in German. For example, *arbeitet* = working, *Freigabe nötig* = needs permission, *fertig* = done, *wartet* = waiting.

## Requirements

| | Version | Used for |
|---|---|---|
| [Claude Code](https://github.com/anthropics/claude-code) | current | the sessions themselves |
| tmux | 3.3 or newer recommended | every session runs in tmux |
| Python 3 | 3.7 or newer | ccm itself (standard library only, no `pip`) |
| git | any | downloading and updating |

ccm runs on **Linux** and **macOS**. On **Windows** it runs inside **WSL**, because tmux doesn't run natively on Windows.

## Installation

### Linux

```sh
# 1. Dependencies
sudo apt install tmux python3 git          # Debian / Ubuntu / Raspberry Pi OS
# sudo dnf install tmux python3 git        # Fedora
# sudo pacman -S tmux python git           # Arch

# 2. Claude Code (if not installed yet)
curl -fsSL https://claude.ai/install.sh | bash

# 3. ccm
git clone https://github.com/onem0/ccm.git ~/.ccm
~/.ccm/install.sh
```

### macOS

```sh
# 1. Dependencies (Homebrew: https://brew.sh)
brew install tmux git
xcode-select --install       # provides python3 if you don't have it yet (or: brew install python)

# 2. Claude Code (if not installed yet)
curl -fsSL https://claude.ai/install.sh | bash

# 3. ccm
git clone https://github.com/onem0/ccm.git ~/.ccm
~/.ccm/install.sh
```

If the script says that `~/.local/bin` is not in your `PATH` (common on macOS):

```sh
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
```

Then open a new terminal window.

### Windows (via WSL)

1. **Install WSL.** Open PowerShell *as Administrator* and run:
   ```powershell
   wsl --install
   ```
   Restart your PC. Ubuntu then opens and asks you for a username and password.
2. **Terminal:** use [Windows Terminal](https://aka.ms/terminal) with the "Ubuntu" profile. Colors, Unicode and keyboard shortcuts work correctly there.
3. **Inside Ubuntu (WSL)**, continue exactly as on Linux:
   ```sh
   sudo apt update && sudo apt install tmux python3 git
   curl -fsSL https://claude.ai/install.sh | bash      # install Claude Code *inside* WSL
   git clone https://github.com/onem0/ccm.git ~/.ccm
   ~/.ccm/install.sh
   ```

Things to know on Windows:

- Claude Code must be installed **inside WSL**. ccm can't use a Windows installation of Claude Code.
- Keep your projects in the Linux file system (e.g. `~/dev/...`). Windows drives are mounted under `/mnt/c/...`, and everything is much slower there.
- To use ccm later, open "Ubuntu" in Windows Terminal and type `ccm`.

### What `install.sh` does

- checks for Python, tmux and Claude Code and tells you what's missing
- creates `ccm` and `ccn` as symlinks in `~/.local/bin` (for a different folder: `CCM_BIN=/usr/local/bin ./install.sh`)
- warns you if `~/.local/bin` is not in your `PATH`

Keep the cloned folder (`~/.ccm`): the commands are links into it. You can also install by hand without the script:

```sh
ln -s ~/.ccm/ccm ~/.local/bin/ccm
ln -s ~/.ccm/ccm ~/.local/bin/ccn
```

### Updating

```sh
git -C ~/.ccm pull
```

### Uninstalling

```sh
~/.ccm/install.sh --uninstall           # removes the ccm and ccn commands
rm -rf ~/.ccm ~/.local/share/ccm        # optional: delete the code and data
```

## Quick start

```sh
cd ~/dev/my-project
ccn                    # start a new Claude session here and open it
                       # … Ctrl-Q takes you back to your shell
ccm                    # dashboard with all sessions
```

## Commands

| Command | What it does |
|---|---|
| `ccm` | open the dashboard |
| `ccn` | start a new session in the **current folder** and open it |
| `ccn "Fix the tests"` | same, and Claude starts on the task right away |
| `ccn --model sonnet` | unknown options are passed straight to `claude` |
| `ccn -d "task"` | start in the background without opening it |
| `ccm a [name]` | open a session (without a name: the one in the current folder) |
| `ccm ls` | list all sessions with their status (`--json` for scripts) |
| `ccm peek <name>` | look at a session's screen without opening it |
| `ccm send <name> <text>` | send a message to a session |
| `ccm kill <name>` | stop Claude (the session stays in the list and can be resumed) |
| `ccm resume <name>` | resume a stopped session (`--fresh`: without the history) |
| `ccm rename <old> <new>` / `ccm rm <name>` | rename / remove |
| `ccm help` | all options |

## Dashboard keys

`↑↓`/`jk` select · `↵` open (stopped sessions are resumed) · `n` new session (folder picker with Tab completion) · `s` send a message · `1`–`9` answer a permission prompt or question directly · `r` rename · `x` stop/remove · `F` start fresh · `Tab` Live ↔ History · `/` filter · `o` sort · `v` preview · `?` help · `q` quit

## How it works

- Every session is a tmux session on a separate tmux server (`tmux -L ccm ls`). Your own tmux sessions are left alone.
- This tmux server has **no prefix key**, so it doesn't clash with Claude's `Ctrl-B`. The only key is `Ctrl-Q` = back.
- The status bar at the bottom shows which other sessions are waiting or done, plus the current session's **context usage** and your account's **5-hour and weekly limits** with their reset times, e.g. `Kontext 34%  5h 23% ↻14:30  Woche 41% ↻Fr 09:00`. Values turn yellow at 60 % and red at 85 %. The limits also appear in the dashboard header. They are only available with a Claude subscription (Pro/Max) and update after each reply from Claude.
- Claude is started with `--settings ~/.local/share/ccm/claude-hooks.json`. The hooks report every event (prompt, tool call, permission request, done …) to `ccm`. Your `~/.claude/settings.json` is not changed.
- The same file sets a `statusLine` command, which is how ccm gets context usage and limits from Claude Code. If you have your own `statusLine` in `~/.claude/settings.json`, ccm runs it afterwards with the same input, so it still shows up inside Claude. (A `statusLine` from a project's `.claude/settings.json` is deliberately not run.)
- ccm also reads each session's screen, so the status stays correct after an Esc interrupt or while a dialog is open.
- Stopped sessions (even after a reboot) are resumed exactly where they left off with `claude --resume <id>`.

## Files

- Code: `ccm.py` = logic and CLI, `ccm_ui.py` = dashboard, `ccm` = launcher script. Python standard library only.
- Commands: `~/.local/bin/ccm` and `~/.local/bin/ccn` (symlinks to the `ccm` launcher in the repo)
- Data: `~/.local/share/ccm/` (readable only by you, since it contains your prompts and Claude's replies)
- Optional `~/.config/ccm/config.json`, e.g. for default arguments for every new session:
  ```json
  { "claude_args": ["--model", "sonnet"] }
  ```
  If `claude` is not in your `PATH`, you can set its location here with `"claude": "/path/to/claude"`.
- Optional `~/.config/ccm/tmux.conf` for your own tmux settings (loaded last).
