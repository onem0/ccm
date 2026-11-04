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
| git | any | downloading and auto-updating from GitHub |

ccm runs on **Linux** and **macOS**. On **Windows** it runs inside **WSL**, because tmux doesn't run natively on Windows.

## Installation

Install the [requirements](#requirements) for your system (see below), then run this one line. You don't need to clone anything:

```sh
curl -fsSL https://raw.githubusercontent.com/onem0/ccm/refs/heads/main/install.sh | sh
```

The script checks Python, tmux, git and Claude Code, downloads ccm from GitHub to `~/.local/share/ccm/app` and puts the `ccm` and `ccn` commands into `~/.local/bin`. Running the line again updates or repairs the installation.

### Linux

```sh
sudo apt install tmux python3 git curl     # Debian / Ubuntu / Raspberry Pi OS
# sudo dnf install tmux python3 git        # Fedora
# sudo pacman -S tmux python git           # Arch

curl -fsSL https://claude.ai/install.sh | bash                                         # Claude Code, if not installed yet
curl -fsSL https://raw.githubusercontent.com/onem0/ccm/refs/heads/main/install.sh | sh  # ccm
```

### macOS

```sh
brew install tmux             # Homebrew: https://brew.sh
xcode-select --install        # provides git and python3 if you don't have them yet

curl -fsSL https://claude.ai/install.sh | bash                                         # Claude Code, if not installed yet
curl -fsSL https://raw.githubusercontent.com/onem0/ccm/refs/heads/main/install.sh | sh  # ccm
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
   sudo apt update && sudo apt install tmux python3 git curl
   curl -fsSL https://claude.ai/install.sh | bash                                         # Claude Code *inside* WSL
   curl -fsSL https://raw.githubusercontent.com/onem0/ccm/refs/heads/main/install.sh | sh  # ccm
   ```

Things to know on Windows:

- Claude Code must be installed **inside WSL**. ccm can't use a Windows installation of Claude Code.
- Keep your projects in the Linux file system (e.g. `~/dev/...`). Windows drives are mounted under `/mnt/c/...`, and everything is much slower there.
- To use ccm later, open "Ubuntu" in Windows Terminal and type `ccm`.

### Updates

ccm **updates itself from GitHub every time you start it** (`ccm`, `ccn` or any other command). The update runs in the background, so starting is not slowed down, and the new version is used from the next start on. ccm tells you when it has been updated.

- An update is only applied if the new code compiles, so a broken commit can't break your installation.
- Update right now: `ccm update` · show the installed version: `ccm version`
- Turn auto-updates off with `"auto_update": false` in `~/.config/ccm/config.json` (or `CCM_NO_UPDATE=1`).
- Auto-updates only apply to installations made with the one-liner. A git clone you work on is never changed automatically (see [Development](#development)).

### Uninstalling

```sh
curl -fsSL https://raw.githubusercontent.com/onem0/ccm/refs/heads/main/install.sh | sh -s -- --uninstall
rm -rf ~/.local/share/ccm        # optional: also delete your sessions and settings
```

### Development

To work on ccm itself, clone the repo and link the commands to your clone:

```sh
git clone https://github.com/onem0/ccm.git && cd ccm
./install.sh                     # links ccm/ccn to this clone, no auto-update
./install.sh --uninstall         # removes the links again
```

Options for `install.sh`: `CCM_BIN` (where the commands go, default `~/.local/bin`), `CCM_HOME` (where the one-liner puts the code), `CCM_REPO` (git URL to install from, e.g. your fork).

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
| `ccn -w "task"` | start in the background, wait until Claude is done and print its reply |
| `ccm a [name]` | open a session (without a name: the one in the current folder) |
| `ccm ls` | list all sessions with their status (`--json` for scripts) |
| `ccm peek <name>` | look at a session's screen without opening it |
| `ccm send <name> <text>` | send a message to a session (`--wait`: wait for the reply and print it) |
| `ccm wait <name>…` | wait until the sessions stop working (`--any`, `--timeout SEC`, `--result`, `--json`) |
| `ccm result <name>` | print a session's last reply in full |
| `ccm kill <name>` | stop Claude (the session stays in the list and can be resumed) |
| `ccm resume <name>` | resume a stopped session (`--fresh`: without the history) |
| `ccm rename <old> <new>` / `ccm rm <name>` | rename / remove |
| `ccm update` / `ccm version` | update from GitHub now / show the installed version |
| `ccm help` | all options |

## Sessions that start sessions

Claude itself can use `ccm` inside a ccm session. So instead of subagents, you can ask a normal session to split the work into real, separate Claude Code sessions:

```
ccn
> Split this into 5 ccm sessions: one per service, each fixes its failing tests. Wait for all of them and summarize.
```

Claude then runs something like this (every ccm session knows these commands):

```sh
ccm new -d -n api   -C ../wt-api   "Fix the failing tests in services/api …"
ccm new -d -n shop  -C ../wt-shop  "…"
ccm wait api shop … --timeout 540 --result     # blocks until they are done, prints their replies
ccm send api --wait "Also update the changelog"  # follow-up, waits for the answer
```

That makes 6 sessions in total. The sub-sessions show up in the dashboard **indented under the session that started them**, and you can open any of them with `↵` to watch or step in. Each one has its own context and its own permission prompts.

- A sub-session's **result** is its final reply (`ccm result <name>`, stored in full).
- `ccm wait` returns as soon as no session is working any more, including when one **needs you** (permission prompt, question, plan). Claude then tells you which session to open.
- Sub-sessions are told who started them, to work on their own, and to finish with a self-contained summary.
- Read-only commands (`ccm ls`, `peek`, `wait`, `result`) run without a permission prompt. Starting or controlling sessions (`ccm new`, `send`, `kill` …) asks you like any other command, unless you allow it.

Limits, so a session can't do more than you allowed it:

- Sub-sessions **inherit the permission mode** of the session that starts them and can never get a more permissive one. Apart from `--model`, `--effort`, `--fallback-model` and `--permission-mode`, no claude options can be passed to them.
- A session **cannot answer permission prompts or dialogs** of other sessions (`ccm send` refuses while one is open). Only you can.
- From inside a session, `kill`, `rm`, `rename` and `resume` only work on its **own** sub-sessions, and it can't `send` to or `wait` for itself.
- By default sub-sessions can't start further sub-sessions (`max_depth`), and a session can run at most 10 at once (`max_children`). Both can be changed in the config, and `"agents": false` turns the feature off completely.

## Dashboard keys

`↑↓`/`jk` select · `↵` open (stopped sessions are resumed) · `n` new session (folder picker with Tab completion) · `s` send a message · `1`–`9` answer a permission prompt or question directly · `r` rename · `x` stop/remove · `F` start fresh · `Tab` Live ↔ History · `/` filter · `o` sort · `v` preview · `?` help · `q` quit

## How it works

- Every session is a tmux session on a separate tmux server (`tmux -L ccm ls`). Your own tmux sessions are left alone.
- This tmux server has **no prefix key**, so it doesn't clash with Claude's `Ctrl-B`. The only key is `Ctrl-Q` = back.
- The status bar at the bottom shows which other sessions are waiting or done, plus the current session's **context usage** and your account's **5-hour and weekly limits** with their reset times, e.g. `Kontext 34%  5h 23% ↻14:30  Woche 41% ↻Fr 09:00`. Values turn yellow at 60 % and red at 85 %. The limits also appear in the dashboard header. They are only available with a Claude subscription (Pro/Max) and update after each reply from Claude.
- Claude is started with `--settings ~/.local/share/ccm/claude-hooks.json`. The hooks report every event (prompt, tool call, permission request, done …) to `ccm`. Your `~/.claude/settings.json` is not changed.
- The same file sets a `statusLine` command, which is how ccm gets context usage and limits from Claude Code. If you have your own `statusLine` in `~/.claude/settings.json`, ccm runs it afterwards with the same input, so it still shows up inside Claude. (A `statusLine` from a project's `.claude/settings.json` is deliberately not run.)
- Every session also gets a short `--append-system-prompt` that explains the `ccm` commands for [sub-sessions](#sessions-that-start-sessions), and `CCM_ID` in its environment, so a `ccm` call from Claude knows which session it comes from.
- ccm also reads each session's screen, so the status stays correct after an Esc interrupt or while a dialog is open.
- Stopped sessions (even after a reboot) are resumed exactly where they left off with `claude --resume <id>`.

## Files

- Code: `ccm.py` = logic and CLI, `ccm_ui.py` = dashboard, `ccm` = launcher script. Python standard library only.
- Installed code (one-liner): `~/.local/share/ccm/app/`, a git checkout that ccm keeps up to date
- Commands: `~/.local/bin/ccm` and `~/.local/bin/ccn` (symlinks to the `ccm` launcher)
- Data: `~/.local/share/ccm/` (readable only by you, since it contains your prompts and Claude's replies)
- Optional `~/.config/ccm/config.json`, e.g. for default arguments for every new session:
  ```json
  { "claude_args": ["--model", "sonnet"] }
  ```
  If `claude` is not in your `PATH`, you can set its location here with `"claude": "/path/to/claude"`.
  Sub-sessions: `"agents"` (default `true`), `"max_depth"` (default `1`), `"max_children"` (default `10`).
- Optional `~/.config/ccm/tmux.conf` for your own tmux settings (loaded last).
