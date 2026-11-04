"""
ccm – Claude Code Manager

Startet Claude-Code-Sessions in tmux, zeigt live, was jede Session gerade tut,
und lässt dich mit Enter hinein- und mit Ctrl-Q wieder herausspringen.

Aufbau
  * jede Session = eine tmux-Session auf einem eigenen tmux-Server (-L ccm)
  * Claude wird mit --settings <hooks.json> gestartet; die Hooks rufen
    `ccm _hook` auf und schreiben den Status nach ~/.local/share/ccm/state/
  * zusätzlich wird der Bildschirm jeder Session (tmux capture-pane)
    ausgewertet – damit stimmt der Status auch nach Esc-Abbrüchen etc.

Nur Python-Standardbibliothek, kein pip nötig.
"""

import os
import sys
import json
import time

VERSION = "1.0.0"
HOME = os.path.expanduser("~")
SOCKET = os.environ.get("CCM_SOCKET") or "ccm"
TPREFIX = "ccm-"


def _xdg(var, rel):
    return os.environ.get(var) or os.path.join(HOME, rel)


DATA = os.environ.get("CCM_DATA") or os.path.join(_xdg("XDG_DATA_HOME", ".local/share"), "ccm")
SESS_DIR = os.path.join(DATA, "sessions")
STATE_DIR = os.path.join(DATA, "state")
EVENT_DIR = os.path.join(DATA, "events")
HOOKS_PATH = os.path.join(DATA, "claude-hooks.json")
TMUX_CONF = os.path.join(DATA, "tmux.conf")
STATUS_SH = os.path.join(DATA, "tmux-status.sh")
CONFIG_PATH = os.path.join(_xdg("XDG_CONFIG_HOME", ".config"), "ccm", "config.json")

# wird vom Launcher-Skript überschrieben (realpath von ~/dev/ccm/ccm)
LAUNCHER = os.path.realpath(sys.argv[0]) if sys.argv and sys.argv[0] else "ccm"

DEFAULT_CONFIG = {
    # Pfad oder Name der claude-Binary
    "claude": "claude",
    # Argumente, die jede neue Session bekommt, z.B. ["--model", "sonnet"]
    "claude_args": [],
}

# Umgebungsvariablen, die eine *laufende* Claude-Session setzt. Startet man ccm
# aus Claude heraus, dürfen die nicht in die neue Session durchsickern.
NESTED_ENV = (
    "CLAUDECODE", "CLAUDE_PID", "CLAUDE_EFFORT", "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_SSE_PORT",
    "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN",
    "CLAUDE_CODE_BRIDGE_SESSION_ID", "CLAUDE_CODE_SESSION_ATTENDED",
    "CLAUDE_CODE_EXECPATH",
)

ATTN = ("permission", "question", "plan", "input")
BUSY = ("working", "compacting", "starting")

LABELS = {
    "starting": "startet",
    "working": "arbeitet",
    "compacting": "komprimiert",
    "permission": "Freigabe nötig",
    "question": "Rückfrage",
    "plan": "Plan prüfen",
    "input": "Eingabe nötig",
    "done": "fertig",
    "idle": "bereit",
    "error": "Fehler",
    "exited": "beendet",
}


class CCMError(Exception):
    pass


NO_TMUX = "tmux ist nicht installiert (%s)." % (
    "brew install tmux" if sys.platform == "darwin" else "z.B. sudo apt install tmux")


# ───────────────────────────── kleine Helfer ─────────────────────────────

def now():
    return time.time()


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def secure_data_dir():
    """DATA enthält Prompts und Antworten → nur für den eigenen Benutzer (0700)."""
    try:
        os.makedirs(DATA, mode=0o700, exist_ok=True)
        if os.stat(DATA).st_mode & 0o077:
            os.chmod(DATA, 0o700)
    except OSError:
        pass


def write_json(path, data, pretty=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1 if pretty else None)
    os.replace(tmp, path)


def write_if_changed(path, text, mode=None):
    try:
        with open(path, encoding="utf-8") as f:
            if f.read() == text:
                return
    except OSError:
        pass
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    if mode:
        os.chmod(tmp, mode)
    os.replace(tmp, path)


def tilde(p):
    if not p:
        return ""
    if p == HOME:
        return "~"
    if p.startswith(HOME + os.sep):
        return "~" + p[len(HOME):]
    return p


# C0- und C1-Steuerzeichen (ESC, CSI, BEL …). Texte aus Hooks stammen von Claude
# bzw. aus Dateien/Tool-Ausgaben und dürfen das Terminal nicht steuern.
_CTRL = dict.fromkeys(c for c in range(0xa0) if c < 0x20 or c >= 0x7f)
_CTRL_ML = {c: v for c, v in _CTRL.items() if c not in (9, 10)}


def strip_ctrl(s, multiline=False):
    return str(s or "").translate(_CTRL_ML if multiline else _CTRL)


def oneline(s, n=200):
    s = strip_ctrl(" ".join(str(s or "").split()))
    return s if len(s) <= n else s[: max(0, n - 1)] + "…"


def fmt_age(sec):
    sec = max(0, int(sec))
    if sec < 60:
        return "%ds" % sec
    if sec < 3600:
        return "%dm" % (sec // 60)
    if sec < 86400:
        return "%dh" % (sec // 3600)
    return "%dd" % (sec // 86400)


def fmt_dur(sec):
    sec = max(0, int(sec))
    if sec < 60:
        return "%ds" % sec
    m = sec // 60
    if m < 60:
        return "%dm" % m
    h, m = divmod(m, 60)
    if h < 24:
        return "%dh %02dm" % (h, m)
    d, h = divmod(h, 24)
    return "%dd %dh" % (d, h)


def fmt_tokens(n):
    if not n:
        return "0"
    if n < 1000:
        return str(n)
    if n < 10000:
        return "%.1fk" % (n / 1000)
    if n < 1000000:
        return "%dk" % (n // 1000)
    return "%.1fM" % (n / 1000000)


def pretty_model(m):
    if not m:
        return ""
    import re
    mm = re.match(r"claude-([a-z]+)-(\d+)(?:-(\d+))?", m)
    if not mm:
        return m
    s = mm.group(1).capitalize() + " " + mm.group(2) + ("." + mm.group(3) if mm.group(3) else "")
    if "[1m]" in m:
        s += " 1M"
    return s


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    user = read_json(CONFIG_PATH, {})
    if isinstance(user, dict):
        cfg.update(user)
    return cfg


def self_cmd():
    import shlex
    return "%s %s" % (shlex.quote(sys.executable), shlex.quote(LAUNCHER))


# ───────────────────────────── Sessions (Metadaten) ─────────────────────────────

def meta_path(i):
    return os.path.join(SESS_DIR, i + ".json")


def state_path(i):
    return os.path.join(STATE_DIR, i + ".json")


def load_meta(i):
    m = read_json(meta_path(i))
    return m if isinstance(m, dict) else None


def save_meta(m):
    write_json(meta_path(m["id"]), m, pretty=True)


def load_metas():
    out = []
    try:
        names = os.listdir(SESS_DIR)
    except OSError:
        return out
    for n in names:
        if n.endswith(".json"):
            m = read_json(os.path.join(SESS_DIR, n))
            if isinstance(m, dict) and m.get("id") and m.get("name"):
                out.append(m)
    out.sort(key=lambda m: m.get("created") or 0)
    return out


def read_state(i):
    st = read_json(state_path(i), {})
    return st if isinstance(st, dict) else {}


def update_meta(i, **kw):
    m = load_meta(i)
    if m:
        m.update(kw)
        save_meta(m)
    return m


def mark_seen(i):
    update_meta(i, last_seen=now())


def new_id():
    import secrets
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    while True:
        i = "".join(secrets.choice(alphabet) for _ in range(6))
        if not os.path.exists(meta_path(i)):
            return i


def clean_name(s):
    import re
    s = "".join(ch if (ch.isalnum() or ch in "-_.") else "-" for ch in (s or "").strip())
    s = re.sub(r"-{2,}", "-", s).strip("-.")
    return s[:40]


def unique_name(base, metas, skip_id=None):
    names = {m["name"] for m in metas if m.get("id") != skip_id}
    if base not in names:
        return base
    n = 2
    while "%s-%d" % (base, n) in names:
        n += 1
    return "%s-%d" % (base, n)


def find_session(query, metas=None):
    metas = load_metas() if metas is None else metas
    q = (query or "").strip()
    if not q:
        raise CCMError("Kein Session-Name angegeben.")
    for m in metas:
        if m["name"] == q or m["id"] == q:
            return m
    low = q.lower()
    pref = [m for m in metas if m["name"].lower().startswith(low)]
    if len(pref) == 1:
        return pref[0]
    sub = [m for m in metas if low in m["name"].lower()]
    if len(sub) == 1:
        return sub[0]
    cand = pref or sub
    if cand:
        raise CCMError("»%s« ist mehrdeutig: %s" % (q, ", ".join(m["name"] for m in cand)))
    raise CCMError("Keine Session »%s« gefunden. (ccm ls zeigt alle)" % q)


# ───────────────────────────── Hook-Verarbeitung ─────────────────────────────
# Wird von Claude Code bei jedem Hook-Event aufgerufen. Muss schnell sein, darf
# nichts auf stdout schreiben (das würde bei manchen Events in den Kontext
# wandern) und endet immer mit Exit-Code 0.

def update_state(i, fn):
    import fcntl
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(os.path.join(STATE_DIR, "." + i + ".lock"), "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        st = read_state(i)
        entry = fn(st)
        write_json(state_path(i), st)
        if entry:
            entry["t"] = round(now(), 2)
            log_event(i, entry)
        return st


def log_event(i, entry):
    os.makedirs(EVENT_DIR, exist_ok=True)
    path = os.path.join(EVENT_DIR, i + ".jsonl")
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    try:
        if os.path.getsize(path) > 600_000:
            with open(path, "rb") as f:
                f.seek(-300_000, 2)
                data = f.read()
            data = data[data.find(b"\n") + 1:]
            with open(path + ".tmp", "wb") as f:
                f.write(data)
            os.replace(path + ".tmp", path)
    except OSError:
        pass


def _set(st, status, t):
    if st.get("status") != status:
        st["status"] = status
        st["since"] = t


def _first_str(d):
    for v in d.values():
        if isinstance(v, str) and v.strip():
            return v
    return ""


def summarize_tool(name, inp, cwd=None):
    """Kurzbeschreibung eines Tool-Aufrufs: (label, detail, extra)."""
    if not isinstance(inp, dict):
        inp = {}

    def s(k):
        v = inp.get(k)
        return v.strip() if isinstance(v, str) else ""

    def rel(p):
        if not p:
            return ""
        c = (cwd or "").rstrip("/")
        if c and p.startswith(c + "/"):
            return p[len(c) + 1:]
        return tilde(p)

    label, detail, extra = name, "", ""
    if name == "Bash":
        detail, extra = s("command"), s("description")
    elif name in ("Read", "Write", "Edit", "MultiEdit", "NotebookEdit", "NotebookRead"):
        detail = rel(s("file_path") or s("notebook_path") or s("path"))
    elif name == "Grep":
        detail = s("pattern")
        extra = rel(s("path")) or s("glob")
    elif name == "Glob":
        detail = s("pattern")
    elif name == "WebFetch":
        detail = s("url")
    elif name == "WebSearch":
        detail = s("query")
    elif name in ("Task", "Agent"):
        detail = s("description") or s("prompt")
        extra = s("subagent_type")
    elif name == "TodoWrite":
        todos = inp.get("todos") if isinstance(inp.get("todos"), list) else []
        cur = ""
        for td in todos:
            if isinstance(td, dict) and td.get("status") == "in_progress":
                cur = str(td.get("activeForm") or td.get("content") or "")
                break
        done = sum(1 for td in todos if isinstance(td, dict) and td.get("status") == "completed")
        label = "Todos"
        detail = cur or "%d/%d erledigt" % (done, len(todos))
    elif name == "AskUserQuestion":
        qs = inp.get("questions")
        if isinstance(qs, list) and qs and isinstance(qs[0], dict):
            detail = str(qs[0].get("question") or "")
        label = "Frage"
    elif name == "ExitPlanMode":
        label, detail = "Plan", "wartet auf Freigabe"
    elif name == "Skill":
        detail = s("skill") or s("command") or _first_str(inp)
    elif name.startswith("mcp__"):
        parts = name.split("__")
        label = parts[1] if len(parts) > 1 else name
        if len(parts) > 2:
            label += ":" + "__".join(parts[2:])
        detail = _first_str(inp)
    else:
        detail = _first_str(inp)
    return oneline(label, 40), oneline(detail, 300), oneline(extra, 200)


def handle_hook(sid, d):
    ev = str(d.get("hook_event_name") or "")
    t = now()

    def fn(st):
        prev = st.get("event")
        st["event"] = ev
        st["t"] = t
        sess = d.get("session_id")
        if sess and ev in ("SessionStart", "UserPromptSubmit"):
            st["claude_sid"] = sess
        if d.get("transcript_path") and ev in ("SessionStart", "UserPromptSubmit"):
            st["transcript"] = d["transcript_path"]

        if ev == "SessionStart":
            src = str(d.get("source") or "")
            if d.get("model"):
                st["model"] = d["model"]
            if src in ("resume", "fork"):
                st["has_conv"] = True
            if src == "clear":
                st["has_conv"] = False
                for k in ("prompt", "last_msg", "todos", "tool", "detail", "extra", "error", "perm", "question"):
                    st.pop(k, None)
            if src != "compact":
                _set(st, "idle", t)
            return {"k": "start", "x": src}

        if ev == "UserPromptSubmit":
            st["has_conv"] = True
            src = d.get("source")
            p = str(d.get("prompt") or "")
            entry = None
            if src in (None, "user", "sdk") and p.strip():
                st["prompt"] = p[:3000]
                st["prompt_t"] = t
                entry = {"k": "prompt", "x": oneline(p, 400)}
            st["turn_t"] = t
            st["tools_n"] = 0
            for k in ("tool", "detail", "extra", "perm", "error", "question"):
                st.pop(k, None)
            _set(st, "working", t)
            return entry

        if ev == "PreToolUse":
            name = str(d.get("tool_name") or "?")
            inp = d.get("tool_input") if isinstance(d.get("tool_input"), dict) else {}
            label, detail, extra = summarize_tool(name, inp, d.get("cwd"))
            st.update(tool=label, detail=detail, extra=extra, tool_t=t)
            st["tools_n"] = int(st.get("tools_n") or 0) + 1
            if name == "TodoWrite":
                todos = inp.get("todos") if isinstance(inp.get("todos"), list) else []
                done = sum(1 for x in todos if isinstance(x, dict) and x.get("status") == "completed")
                st["todos"] = [done, len(todos)]
            if name == "AskUserQuestion":
                st["question"] = detail
                _set(st, "question", t)
                return {"k": "ask", "x": detail}
            if name == "ExitPlanMode":
                _set(st, "plan", t)
                return {"k": "plan", "x": "Plan wartet auf Freigabe"}
            _set(st, "working", t)
            return {"k": "tool", "tool": label, "x": detail, "y": extra}

        if ev == "PermissionRequest":
            name = str(d.get("tool_name") or "?")
            if name in ("AskUserQuestion", "ExitPlanMode"):
                return None
            label, detail, extra = summarize_tool(name, d.get("tool_input"), d.get("cwd"))
            st["perm"] = ("%s · %s" % (label, extra or detail)) if (extra or detail) else label
            _set(st, "permission", t)
            return {"k": "perm", "tool": label, "x": detail, "y": extra}

        if ev == "PostToolUse":
            st.pop("perm", None)
            st.pop("question", None)
            _set(st, "working", t)
            return None

        if ev == "PostToolUseFailure":
            st.pop("perm", None)
            if d.get("is_interrupt"):
                _set(st, "idle", t)
                return {"k": "interrupt", "x": "unterbrochen"}
            _set(st, "working", t)
            label, _, _ = summarize_tool(str(d.get("tool_name") or "?"), d.get("tool_input"), d.get("cwd"))
            return {"k": "fail", "tool": label, "x": oneline(d.get("error"), 240)}

        if ev == "Notification":
            nt = str(d.get("notification_type") or "")
            st["notice"] = oneline(d.get("message"), 200)
            if nt == "permission_prompt" and prev in ("PreToolUse", "PermissionRequest", "Notification"):
                if st.get("status") not in ("question", "plan"):
                    _set(st, "permission", t)
            elif nt == "elicitation_dialog":
                st["question"] = oneline(d.get("message"), 200)
                _set(st, "question", t)
                return {"k": "ask", "x": st["question"]}
            return None

        if ev == "Stop":
            msg = str(d.get("last_assistant_message") or "")
            if msg:
                st["last_msg"] = msg[:4000]
            st["done_t"] = t
            st["subagents"] = 0
            for k in ("perm", "question"):
                st.pop(k, None)
            _set(st, "done", t)
            return {"k": "done", "x": oneline(msg, 300)}

        if ev == "StopFailure":
            err = d.get("error")
            det = d.get("error_details")
            st["error"] = oneline("%s%s" % (err or "Fehler", (": %s" % det) if det else ""), 300)
            msg = d.get("last_assistant_message")
            if msg:
                st["last_msg"] = str(msg)[:4000]
            st["done_t"] = t
            _set(st, "error", t)
            return {"k": "error", "x": st["error"]}

        if ev == "SubagentStart":
            st["subagents"] = int(st.get("subagents") or 0) + 1
            return {"k": "agent", "x": str(d.get("agent_type") or "Subagent")}

        if ev == "SubagentStop":
            st["subagents"] = max(0, int(st.get("subagents") or 0) - 1)
            return None

        if ev == "PreCompact":
            _set(st, "compacting", t)
            return {"k": "compact", "x": str(d.get("trigger") or "")}

        if ev == "PostCompact":
            _set(st, "working" if d.get("trigger") == "auto" else "idle", t)
            return None

        if ev == "SessionEnd":
            _set(st, "ended", t)
            st["end_reason"] = str(d.get("reason") or "")
            return {"k": "end", "x": st["end_reason"]}
        return None

    update_state(sid, fn)


def cmd_hook():
    try:
        raw = sys.stdin.read()
    except Exception:
        return 0
    sid = os.environ.get("CCM_ID") or ""
    if not sid.isalnum() or not raw.strip() or not os.path.exists(meta_path(sid)):
        return 0
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            handle_hook(sid, data)
    except Exception as e:  # niemals Claude stören
        try:
            with open(os.path.join(DATA, "hook-errors.log"), "a") as f:
                f.write("%s %s: %r\n" % (time.strftime("%F %T"), sid, e))
        except OSError:
            pass
    return 0


# ───────────────────────────── generierte Dateien ─────────────────────────────

def ensure_hooks_file():
    import shlex
    cmd = "CCM_DATA=%s %s _hook" % (shlex.quote(DATA), self_cmd())
    h = {"type": "command", "command": cmd, "timeout": 10}
    hooks = {}
    for e in ("PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest"):
        hooks[e] = [{"matcher": "*", "hooks": [h]}]
    for e in ("SessionStart", "UserPromptSubmit", "Notification", "Stop", "StopFailure",
              "SubagentStart", "SubagentStop", "PreCompact", "PostCompact", "SessionEnd"):
        hooks[e] = [{"hooks": [h]}]
    write_if_changed(HOOKS_PATH, json.dumps({"hooks": hooks}, indent=1) + "\n")
    return HOOKS_PATH


def truecolor():
    return os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit")


def ensure_tmux_conf():
    import shlex
    write_if_changed(STATUS_SH, "#!/bin/sh\n# ccm – erzeugt automatisch\nCCM_DATA=%s CCM_SOCKET=%s exec %s _status \"$1\"\n"
                     % (shlex.quote(DATA), shlex.quote(SOCKET), self_cmd()), mode=0o755)
    rgb = "set -s 'terminal-features[92]' '*:RGB'\n" if truecolor() else ""
    conf = f"""# ccm – wird automatisch erzeugt und bei jedem Start überschrieben.
# Eigene Anpassungen bitte in ~/.config/ccm/tmux.conf (wird am Ende geladen).

set -g default-terminal "tmux-256color"
set -s escape-time 10
set -g focus-events on
set -g mouse on
set -g history-limit 50000
set -s extended-keys on
set -s 'terminal-features[90]' 'xterm*:extkeys'
set -s 'terminal-features[91]' 'xterm*:hyperlinks'
{rgb}set -s set-clipboard on
set -g allow-passthrough on
set -g detach-on-destroy on
set -g remain-on-exit off
set -g window-size latest
set -g aggressive-resize on
set -g allow-rename off
set -g automatic-rename off
set -g set-titles on
set -g set-titles-string '#{{@ccm_name}} · ccm'

# Kein Prefix: Claude Code braucht Ctrl-B selbst. Ctrl-Q bringt dich zurück.
set -g prefix None
set -g prefix2 None
bind-key -n C-q detach-client

set -g status on
set -g status-position bottom
set -g status-interval 2
set -g status-justify left
set -g status-style 'bg=colour235,fg=colour250'
set -g status-left-length 90
set -g status-right-length 140
set -g status-left '#[bg=colour173,fg=colour232,bold] ◆ ccm #[bg=colour237,fg=colour255,bold] #{{@ccm_name}} #[bg=colour235,fg=colour245,nobold] #{{@ccm_dir}} '
set -g status-right '#({STATUS_SH} #{{session_name}}) #[bg=colour237,fg=colour173,bold] ^Q #[fg=colour250,nobold]zurück '
set -g window-status-format ''
set -g window-status-current-format ''
set -g message-style 'bg=colour173,fg=colour232'
set -g mode-style 'bg=colour173,fg=colour232'

if-shell -b 'test -f "$HOME/.config/ccm/tmux.conf"' 'source-file "$HOME/.config/ccm/tmux.conf"'
"""
    write_if_changed(TMUX_CONF, conf)
    return TMUX_CONF


# ───────────────────────────── tmux ─────────────────────────────

def tmux_run(args, check=False):
    import subprocess
    try:
        r = subprocess.run(["tmux", "-L", SOCKET] + list(args), capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, errors="replace")
    except FileNotFoundError:
        raise CCMError(NO_TMUX)
    if check and r.returncode != 0:
        raise CCMError("tmux: " + (r.stderr.strip() or "Fehler %d" % r.returncode))
    return r


def tmux_list():
    r = tmux_run(["list-sessions", "-F",
                  "#{session_name}\t#{session_attached}\t#{session_activity}\t#{window_width}\t#{window_height}"])
    out = {}
    if r.returncode != 0:
        return out
    for line in r.stdout.splitlines():
        p = line.split("\t")
        if len(p) >= 5 and p[0].startswith(TPREFIX):
            out[p[0]] = {"attached": int(p[1] or 0), "activity": int(p[2] or 0),
                         "w": int(p[3] or 0), "h": int(p[4] or 0)}
    return out


def tmux_capture(names, escapes=True):
    """Bildschirminhalt mehrerer Sessions mit EINEM tmux-Aufruf holen."""
    out = {}
    if not names:
        return out
    # Zufälliger Trenner pro Aufruf: ein Pane-Inhalt kann ihn nicht vorhersagen
    # und sich damit nicht als Ausgabe einer anderen Session ausgeben.
    mark = "@@ccm-%s@@" % os.urandom(12).hex()

    def run(ns):
        args = []
        for n in ns:
            if args:
                args.append(";")
            args += ["display-message", "-p", mark + n, ";", "capture-pane", "-p"]
            if escapes:
                args.append("-e")
            args += ["-t", "=%s:" % n]
        r = tmux_run(args)
        cur, buf = None, []
        for line in r.stdout.split("\n"):
            if line.startswith(mark):
                if cur:
                    out[cur] = "\n".join(buf)
                cur, buf = line[len(mark):], []
            elif cur is not None:
                buf.append(line)
        if cur:
            out[cur] = "\n".join(buf)
        return r.returncode

    rc = run(names)
    if rc != 0 and len(names) > 1:
        for n in names:
            if n not in out:
                run([n])
    return out


def tmux_alive(tname):
    return tmux_run(["has-session", "-t", "=" + tname]).returncode == 0


def tmux_send(tname, text=None, keys=None, enter=False):
    tgt = "=%s:" % tname
    if text:
        tmux_run(["send-keys", "-t", tgt, "-l", "--", text], check=True)
    if keys:
        tmux_run(["send-keys", "-t", tgt] + list(keys), check=True)
    if enter:
        time.sleep(0.2)
        tmux_run(["send-keys", "-t", tgt, "Enter"], check=True)


def inside_ccm_tmux():
    t = os.environ.get("TMUX", "")
    return bool(t) and os.path.basename(t.split(",")[0]) == SOCKET


def attach_tmux(tname):
    """Blockiert, bis du mit Ctrl-Q zurückkommst."""
    import subprocess
    if inside_ccm_tmux():
        subprocess.run(["tmux", "-L", SOCKET, "switch-client", "-t", "=" + tname])
        return
    env = dict(os.environ)
    env.pop("TMUX", None)
    env.pop("TMUX_PANE", None)
    subprocess.run(["tmux", "-u", "-L", SOCKET, "attach-session", "-t", "=" + tname], env=env)


def resolve_claude(cfg):
    import shutil
    c = os.path.expanduser(str(cfg.get("claude") or "claude"))
    p = shutil.which(c)
    if not p:
        raise CCMError("claude wurde nicht gefunden (%s). Pfad in %s eintragen." % (c, CONFIG_PATH))
    return os.path.abspath(p)


def tmux_start(meta, cols=None, rows=None):
    """tmux-Session für meta starten; darin läuft `ccm _run <id>` → claude."""
    import shutil
    if not shutil.which("tmux"):
        raise CCMError(NO_TMUX)
    if not os.path.isdir(meta["cwd"]):
        raise CCMError("Ordner existiert nicht mehr: %s" % tilde(meta["cwd"]))
    ensure_hooks_file()
    conf = ensure_tmux_conf()
    if not cols or not rows:
        sz = shutil.get_terminal_size((160, 45))
        cols, rows = sz.columns, sz.lines
    tname = TPREFIX + meta["id"]
    envs = ["CCM_ID=" + meta["id"], "CCM_DATA=" + DATA, "CCM_SOCKET=" + SOCKET,
            "PATH=" + os.environ.get("PATH", "/usr/bin:/bin")]
    if truecolor():
        envs.append("COLORTERM=truecolor")
    args = ["-f", conf, "new-session", "-d", "-s", tname, "-x", str(max(40, cols)),
            "-y", str(max(10, rows)), "-c", meta["cwd"]]
    for e in envs:
        args += ["-e", e]
    args += [sys.executable, LAUNCHER, "_run", meta["id"]]
    tmux_run(args, check=True)
    tmux_run(["source-file", conf, ";",
              "set-option", "-t", "=%s:" % tname, "@ccm_name", meta["name"], ";",
              "set-option", "-t", "=%s:" % tname, "@ccm_dir", tilde(meta["cwd"])])


# ───────────────────────────── Lebenszyklus ─────────────────────────────

def create_session(cwd, name=None, prompt=None, args=None, cols=None, rows=None):
    cwd = os.path.realpath(os.path.expanduser(cwd))
    if not os.path.isdir(cwd):
        raise CCMError("Ordner existiert nicht: %s" % tilde(cwd))
    cfg = load_config()
    claude = resolve_claude(cfg)
    metas = load_metas()
    base = clean_name(name) or clean_name(os.path.basename(cwd)) or "home"
    name = unique_name(base, metas)
    t = now()
    meta = {
        "id": new_id(),
        "name": name,
        "cwd": cwd,
        "created": t,
        "claude": claude,
        "args": [str(a) for a in (cfg.get("claude_args") or [])] + [str(a) for a in (args or [])],
        "prompt": prompt or None,
        "launched": 0,
        "last_seen": t,
    }
    save_meta(meta)
    write_json(state_path(meta["id"]), {"status": "starting", "since": t, "t": t})
    try:
        tmux_start(meta, cols, rows)
    except CCMError:
        remove_files(meta["id"])
        raise
    return meta


def kill_session(meta):
    tmux_run(["kill-session", "-t", "=" + TPREFIX + meta["id"]])


def remove_files(i):
    for p in (meta_path(i), state_path(i), os.path.join(STATE_DIR, "." + i + ".lock"),
              os.path.join(EVENT_DIR, i + ".jsonl")):
        try:
            os.remove(p)
        except OSError:
            pass


def remove_session(meta):
    kill_session(meta)
    remove_files(meta["id"])


def resume_session(meta, fresh=False, cols=None, rows=None):
    if tmux_alive(TPREFIX + meta["id"]):
        return
    if fresh:
        def fn(st):
            st["has_conv"] = False
            st.pop("claude_sid", None)
            for k in ("prompt", "last_msg", "todos", "tool", "detail", "extra", "error"):
                st.pop(k, None)
            return {"k": "start", "x": "frisch"}
        update_state(meta["id"], fn)
        meta = update_meta(meta["id"], prompt=None) or meta
    tmux_start(meta, cols, rows)


def rename_session(meta, new):
    new = clean_name(new)
    if not new:
        raise CCMError("Ungültiger Name.")
    metas = load_metas()
    if any(m["name"] == new and m["id"] != meta["id"] for m in metas):
        raise CCMError("Name »%s« ist schon vergeben." % new)
    meta = update_meta(meta["id"], name=new) or meta
    tmux_run(["set-option", "-t", "=%s%s:" % (TPREFIX, meta["id"]), "@ccm_name", new])
    return meta


SESSION_FLAGS_WITH_VALUE = ("-r", "--resume", "--session-id")
SESSION_FLAGS = ("-c", "--continue", "--fork-session")


def strip_session_flags(args):
    out, i = [], 0
    while i < len(args):
        a = args[i]
        if a in SESSION_FLAGS:
            i += 1
            continue
        if a in SESSION_FLAGS_WITH_VALUE:
            i += 1
            if a != "--session-id" and i < len(args) and args[i].startswith("-"):
                continue
            i += 1
            continue
        if a.startswith(("--resume=", "--session-id=")):
            i += 1
            continue
        out.append(a)
        i += 1
    return out


def cmd_run(sid):
    """Läuft *in* der tmux-Session: startet claude und wacht darüber."""
    import signal
    import subprocess
    import uuid
    meta = load_meta(sid)
    if not meta:
        print("ccm: unbekannte Session %s" % sid)
        time.sleep(3)
        return 1
    st = read_state(sid)
    cfg = load_config()
    claude = meta.get("claude") or cfg.get("claude") or "claude"
    if not os.path.exists(claude):
        try:
            claude = resolve_claude(cfg)
        except CCMError:
            pass
    user_args = list(meta.get("args") or [])
    launched = int(meta.get("launched") or 0)
    argv = [claude, "--settings", ensure_hooks_file(), "-n", meta["name"]]
    if launched and st.get("has_conv") and st.get("claude_sid"):
        # Fortsetzen: genau diese Unterhaltung wieder öffnen
        argv += ["--resume", st["claude_sid"]]
        argv += strip_session_flags(user_args)
    elif not launched:
        if not any(a in user_args or any(x.startswith(a + "=") for x in user_args)
                   for a in SESSION_FLAGS + SESSION_FLAGS_WITH_VALUE):
            argv += ["--session-id", str(uuid.uuid4())]
        argv += user_args
    else:
        argv += ["--session-id", str(uuid.uuid4())]
        argv += strip_session_flags(user_args)
    # Erste Aufgabe mitgeben, solange sie noch nie angekommen ist (z.B. erster Start abgestürzt)
    if meta.get("prompt") and not st.get("has_conv"):
        argv.append(meta["prompt"])
    meta["launched"] = int(meta.get("launched") or 0) + 1
    meta["launch_t"] = now()
    save_meta(meta)

    def mark_start(s):
        t = now()
        s.update(status="starting", since=t, t=t, launch_t=t, exit_code=None)
        s.pop("error", None)
        return None
    update_state(sid, mark_start)

    env = dict(os.environ)
    for k in NESTED_ENV:
        env.pop(k, None)
    env["CCM_ID"] = sid
    env["CCM_DATA"] = DATA
    for sg in (signal.SIGINT, signal.SIGQUIT, signal.SIGTSTP):
        signal.signal(sg, lambda *a: None)   # Handler (nicht SIG_IGN) → Kind bekommt Default

    start = time.time()
    try:
        p = subprocess.Popen(argv, env=env, cwd=meta["cwd"])
    except OSError as e:
        code, p = 127, None
        print("\n\x1b[1;31m✕ claude konnte nicht gestartet werden:\x1b[0m %s" % e)
    if p is not None:
        while True:
            try:
                _, status = os.waitpid(p.pid, os.WUNTRACED)
            except ChildProcessError:
                code = 0
                break
            if os.WIFSTOPPED(status):           # Ctrl-Z hätte die Session eingefroren
                os.kill(p.pid, signal.SIGCONT)
                continue
            code = os.waitstatus_to_exitcode(status)
            break
        p.returncode = code

    def mark_exit(s):
        t = now()
        s["exit_code"] = code
        s["exit_t"] = t
        _set(s, "crashed" if code > 0 else "ended", t)
        return {"k": "exit", "x": "Exit-Code %d" % code} if code else None
    update_state(sid, mark_exit)

    if code > 0:
        print("\n\x1b[1;31m✕ Claude wurde mit Code %d beendet\x1b[0m (nach %s)." % (code, fmt_dur(time.time() - start)))
        print("  \x1b[2mDie Session bleibt in ccm. Im Dashboard: ↵ fortsetzen · F frisch starten.\x1b[0m")
        print("  Enter drücken zum Schließen …")
        try:
            sys.stdin.readline()
        except Exception:
            pass
    return 0


# ───────────────────────────── Status-Auswertung ─────────────────────────────

_RX = None


def _rx():
    global _RX
    if _RX is None:
        import re

        class R:
            pass
        R.esc = re.compile(r"\x1b\[([0-9;:?<>=]*)([@-~])|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?|\x1b[PX^_][^\x1b]*(?:\x1b\\)?|\x1b.?")
        R.spin = re.compile(r"^\s*[·✢✳✶✻✽*∗⁕]\s+[^\s…]{2,40}…")
        R.yes = re.compile(r"^\s*(?:❯\s*)?1\.\s+Yes\b", re.M)
        R.rule = re.compile(r"^\s*[─━]{8,}")
        _RX = R
    return _RX


def strip_ansi(s):
    return _rx().esc.sub("", s)


def analyze_screen(plain):
    R = _rx()
    lines = [ln.rstrip() for ln in plain.split("\n")]
    tail = [ln for ln in lines if ln.strip()][-18:]
    text = "\n".join(tail)
    info = {"busy": False, "perm": False, "trust": False, "dialog": False, "promptbox": False}
    for ln in tail:
        if R.spin.match(ln) or "esc to interrupt" in ln.lower():
            info["busy"] = True
            break
    if "trust this folder" in text or "Do you trust the files" in text:
        info["trust"] = True
    if R.yes.search(text) and ("Do you want" in text or "Esc to cancel" in text):
        info["perm"] = True
    if "Esc to cancel" in text or "Enter to confirm" in text or "Enter to select" in text:
        info["dialog"] = True
    for i in range(len(tail) - 1, max(0, len(tail) - 9), -1):
        if tail[i].lstrip().startswith("❯") and R.rule.match(tail[i - 1]):
            info["promptbox"] = True
            break
    return info


GRACE = 6.0


def derive_status(st, alive, scr, t):
    s = st.get("status") or "starting"
    age = t - float(st.get("t") or 0)
    if not alive:
        return "exited"
    if s == "crashed":
        return "error"
    if scr is None:
        return {"ended": "exited", "interrupted": "idle"}.get(s, s)
    if scr["trust"]:
        return "input"
    if scr["perm"]:
        return "permission"
    if scr["busy"]:
        return "compacting" if s == "compacting" else "working"
    if s in ("question", "plan", "permission"):
        if scr["dialog"] or not scr["promptbox"] or age < GRACE:
            return s
        return "idle"
    if scr["dialog"] and not scr["promptbox"]:
        return "input"
    if s in ("working", "compacting"):
        return s if age < GRACE else "idle"
    if s == "starting":
        return "starting" if age < 40 else "idle"
    if s in ("done", "error"):
        return s
    return "idle"


class View:
    __slots__ = ("id", "name", "cwd", "meta", "st", "status", "note", "alive", "attached",
                 "unseen", "raw", "tname", "since")


def snapshot(capture=True, escapes=False):
    metas = load_metas()
    live = tmux_list()
    names = [TPREFIX + m["id"] for m in metas if TPREFIX + m["id"] in live]
    raws = tmux_capture(names, escapes) if (capture and names) else {}
    t = now()
    views = []
    for m in metas:
        v = View()
        v.id, v.name, v.cwd, v.meta = m["id"], m["name"], m["cwd"], m
        v.tname = TPREFIX + m["id"]
        v.st = read_state(m["id"])
        info = live.get(v.tname)
        v.alive = info is not None
        v.attached = bool(info and info["attached"])
        v.raw = raws.get(v.tname)
        an = None
        if v.raw is not None:
            an = analyze_screen(strip_ansi(v.raw) if escapes else v.raw)
        v.status = derive_status(v.st, v.alive, an, t)
        v.note = "Ordner vertrauen?" if (an and an["trust"]) else None
        if v.status == "exited":
            v.since = float(v.st.get("exit_t") or v.st.get("t") or m.get("created") or t)
        else:
            v.since = float(v.st.get("since") or v.st.get("t") or m.get("created") or t)
        if v.status in ("idle",) and v.st.get("status") in ("working", "compacting", "permission", "question", "plan"):
            v.since = float(v.st.get("t") or v.since)
        done_t = float(v.st.get("done_t") or 0)
        v.unseen = (v.status in ("done", "error") and done_t > float(m.get("last_seen") or 0)
                    and not v.attached)
        views.append(v)
    return views


def activity_text(v):
    st, s = v.st, v.status
    if s == "working":
        tool = st.get("tool")
        if tool and float(st.get("tool_t") or 0) >= float(st.get("turn_t") or 0):
            d = st.get("extra") or st.get("detail") or ""
            txt = "%s · %s" % (tool, d) if d else tool
        else:
            txt = "denkt nach …"
        n = int(st.get("subagents") or 0)
        if n:
            txt = "%d Agent%s · %s" % (n, "s" if n > 1 else "", txt)
        td = st.get("todos")
        if isinstance(td, list) and len(td) == 2 and td[1]:
            txt += "  [%d/%d]" % (td[0], td[1])
        return txt
    if s == "compacting":
        return "Kontext wird komprimiert …"
    if s == "starting":
        return "Claude startet …"
    if s == "permission":
        return "→ " + (st.get("perm") or ("%s · %s" % (st.get("tool") or "Tool", st.get("detail") or "")))
    if s == "question":
        return "? " + (st.get("question") or st.get("detail") or "Claude hat eine Frage")
    if s == "plan":
        return "Plan wartet auf deine Freigabe"
    if s == "input":
        if v.note:
            return "↵ öffnen → „Yes, I trust this folder“ wählen"
        return "Dialog offen – ↵ zum Antworten"
    if s == "done":
        msg = (st.get("last_msg") or "").strip()
        return ("„%s“" % oneline(msg.split("\n")[0], 300)) if msg else "Antwort fertig"
    if s == "error":
        if st.get("status") == "crashed":
            return "Claude beendet mit Exit-Code %s" % st.get("exit_code")
        return st.get("error") or "Fehler"
    if s == "exited":
        return "↵ fortsetzen" if st.get("has_conv") else "↵ neu starten"
    p = st.get("prompt")
    return ("zuletzt: „%s“" % oneline(p, 200)) if p else "wartet auf deine Eingabe"


def git_branch(path, _cache={}):
    t = now()
    hit = _cache.get(path)
    if hit and t - hit[0] < 8:
        return hit[1]
    branch = None
    d = path
    for _ in range(40):
        g = os.path.join(d, ".git")
        head = None
        if os.path.isdir(g):
            head = os.path.join(g, "HEAD")
        elif os.path.isfile(g):
            try:
                with open(g) as f:
                    line = f.read().strip()
                if line.startswith("gitdir:"):
                    gd = line[7:].strip()
                    if not os.path.isabs(gd):
                        gd = os.path.join(d, gd)
                    head = os.path.join(gd, "HEAD")
            except OSError:
                pass
        if head:
            try:
                with open(head) as f:
                    h = f.read().strip()
                branch = h[16:] if h.startswith("ref: refs/heads/") else h[:7]
            except OSError:
                pass
            break
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    _cache[path] = (t, branch)
    return branch


def transcript_info(path, _cache={}):
    if not path:
        return None
    try:
        s = os.stat(path)
    except OSError:
        return None
    key = (s.st_mtime, s.st_size)
    hit = _cache.get(path)
    if hit and hit[0] == key:
        return hit[1]
    res = None
    try:
        with open(path, "rb") as f:
            f.seek(max(0, s.st_size - 64_000))
            data = f.read()
            if b'"usage"' not in data and s.st_size > 64_000:
                f.seek(max(0, s.st_size - 600_000))
                data = f.read()
        for line in reversed(data.split(b"\n")):
            if b'"usage"' not in line or b'"assistant"' not in line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if obj.get("type") != "assistant" or obj.get("isSidechain"):
                continue
            msg = obj.get("message") or {}
            u = msg.get("usage") or {}
            ctx = sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_read_input_tokens",
                                                   "cache_creation_input_tokens"))
            res = {"ctx": ctx, "model": msg.get("model")}
            break
    except OSError:
        pass
    _cache[path] = (key, res)
    return res


def read_events(i, _cache={}):
    path = os.path.join(EVENT_DIR, i + ".jsonl")
    try:
        s = os.stat(path)
    except OSError:
        return []
    key = (s.st_mtime, s.st_size)
    hit = _cache.get(path)
    if hit and hit[0] == key:
        return hit[1]
    out = []
    try:
        with open(path, "rb") as f:
            f.seek(max(0, s.st_size - 120_000))
            data = f.read()
        lines = data.split(b"\n")
        if s.st_size > 120_000:
            lines = lines[1:]
        for ln in lines:
            if ln.strip():
                try:
                    out.append(json.loads(ln))
                except ValueError:
                    pass
    except OSError:
        pass
    _cache[path] = (key, out)
    return out


def recent_dirs():
    import re
    seen, out = set(), []

    def add(p):
        if p and p not in seen and not p.startswith("/tmp/") and os.path.isdir(p):
            seen.add(p)
            out.append(p)
    for m in sorted(load_metas(), key=lambda m: -(m.get("created") or 0)):
        add(m.get("cwd"))
    cj = read_json(os.path.join(HOME, ".claude.json"), {}) or {}
    projs = list((cj.get("projects") or {}).keys()) if isinstance(cj, dict) else []
    pdir = os.path.join(HOME, ".claude", "projects")

    def mt(p):
        try:
            return os.path.getmtime(os.path.join(pdir, re.sub(r"[^A-Za-z0-9]", "-", p)))
        except OSError:
            return 0
    for p in sorted(projs, key=mt, reverse=True):
        add(p)
    return out[:80]


def list_subdirs(path, prefix="", hidden=False, limit=300):
    out = []
    try:
        with os.scandir(path) as it:
            for e in it:
                n = e.name
                if n.startswith(".") and not hidden:
                    continue
                if prefix and not n.lower().startswith(prefix.lower()):
                    continue
                try:
                    if e.is_dir():
                        out.append(os.path.join(path, n))
                except OSError:
                    pass
    except OSError:
        return []
    out.sort(key=lambda p: os.path.basename(p).lower())
    return out[:limit]


# ───────────────────────────── CLI ─────────────────────────────

HELP = """\
ccm %s – Claude-Code-Sessions in tmux

  ccm                       Dashboard öffnen (alle Sessions, live)
  ccn [aufgabe]             Neue Session im aktuellen Ordner starten & öffnen
  ccm new [ordner] [opts]   Neue Session starten
      -n, --name NAME         Name (Standard: Ordnername)
      -p, --prompt TEXT       erste Aufgabe für Claude
      -C, --dir ORDNER        Ordner (Standard: aktueller Ordner)
      -d, --detach            im Hintergrund starten, nicht öffnen
      -- ARGS…                weitere claude-Argumente, z.B. -- --model sonnet
                              (unbekannte Optionen wie --model gehen auch direkt)
  ccm a [name]              Session öffnen (ohne Name: die im aktuellen Ordner)
  ccm ls [--json]           Sessions auflisten
  ccm peek <name>           Bildschirm einer Session zeigen, ohne sie zu öffnen
  ccm send <name> <text>    Nachricht an eine Session schicken
  ccm rename <name> <neu>   Session umbenennen
  ccm kill <name>           Claude beenden (bleibt in der Liste, fortsetzbar)
  ccm resume <name>         beendete Session fortsetzen (--fresh: ohne Verlauf)
  ccm rm <name>             Session beenden und aus der Liste entfernen
  ccm config                Konfiguration anzeigen

In einer Session:   Ctrl-Q  → zurück (Claude arbeitet im Hintergrund weiter)
""" % VERSION


def eprint(*a):
    print(*a, file=sys.stderr)


def tty():
    return sys.stdin.isatty() and sys.stdout.isatty()


def parse_new(argv):
    o = {"dir": None, "name": None, "prompt": None, "detach": False, "args": []}
    pos = []
    i = 0

    def val(i):
        if i + 1 >= len(argv):
            raise CCMError("Option %s braucht einen Wert." % argv[i])
        return argv[i + 1]
    while i < len(argv):
        a = argv[i]
        if a == "--":
            o["args"] += argv[i + 1:]
            break
        elif a in ("-n", "--name"):
            o["name"] = val(i)
            i += 1
        elif a in ("-p", "--prompt"):
            o["prompt"] = val(i)
            i += 1
        elif a in ("-C", "--dir"):
            o["dir"] = val(i)
            i += 1
        elif a in ("-d", "--detach", "--bg"):
            o["detach"] = True
        elif a in ("-h", "--help"):
            print(HELP)
            sys.exit(0)
        elif a.startswith("-") and len(a) > 1:
            o["args"] += argv[i:]          # ab hier alles an claude
            break
        else:
            pos.append(a)
        i += 1
    if pos and o["dir"] is None and os.path.isdir(os.path.expanduser(pos[0])):
        o["dir"] = pos.pop(0)
    if pos:
        text = " ".join(pos)
        o["prompt"] = (o["prompt"] + " " + text) if o["prompt"] else text
    return o


def attach_and_report(meta):
    mark_seen(meta["id"])
    attach_tmux(TPREFIX + meta["id"])
    mark_seen(meta["id"])
    m = load_meta(meta["id"]) or meta
    if tmux_alive(TPREFIX + meta["id"]):
        print("\x1b[38;5;173m◆\x1b[0m »%s« läuft im Hintergrund weiter  \x1b[2m·  ccm → Übersicht  ·  ccm a %s → zurück\x1b[0m"
              % (m["name"], m["name"]))
    else:
        print("\x1b[2m■ »%s« ist beendet  ·  ccm a %s → fortsetzen\x1b[0m" % (m["name"], m["name"]))


def cmd_new(argv):
    o = parse_new(argv)
    meta = create_session(o["dir"] or os.getcwd(), o["name"], o["prompt"], o["args"])
    if o["detach"] or not tty():
        print("✓ Session »%s« gestartet in %s  ·  öffnen: ccm a %s" % (meta["name"], tilde(meta["cwd"]), meta["name"]))
        return 0
    attach_and_report(meta)
    return 0


def cmd_attach(argv):
    metas = load_metas()
    if argv:
        m = find_session(argv[0], metas)
    else:
        cwd = os.path.realpath(os.getcwd())
        here = [x for x in metas if x["cwd"] == cwd]
        if not here:
            if len(metas) == 1:
                here = metas
            else:
                raise CCMError("Keine Session in diesem Ordner. Neue starten: ccn  ·  Übersicht: ccm")
        live = tmux_list()
        alive = [x for x in here if TPREFIX + x["id"] in live]
        m = (alive or here)[-1]
    if not tmux_alive(TPREFIX + m["id"]):
        resume_session(m)
        print("▶ Setze »%s« fort …" % m["name"])
    if not tty():
        print("Session »%s« läuft (kein Terminal zum Öffnen)." % m["name"])
        return 0
    attach_and_report(m)
    return 0


def short_path(p, maxw):
    if len(p) <= maxw:
        return p
    parts = p.split("/")
    out = parts[-1]
    for part in reversed(parts[:-1]):
        if len(part) + len(out) + 3 > maxw:
            break
        out = part + "/" + out
    out = "…/" + out
    return out if len(out) <= maxw else "…" + p[-(maxw - 1):]


def _c(code, s, on=True):
    return "\x1b[%sm%s\x1b[0m" % (code, s) if on else s


STATIC_GLYPH = {"working": ("●", 75), "compacting": ("●", 141), "starting": ("●", 245),
                "permission": ("▲", 221), "question": ("▲", 221), "plan": ("▲", 221), "input": ("▲", 221),
                "done": ("✓", 114), "idle": ("○", 245), "error": ("✕", 203), "exited": ("■", 240)}


def cmd_ls(argv):
    views = snapshot(capture=True)
    t = now()
    if "--json" in argv:
        print(json.dumps([{
            "id": v.id, "name": v.name, "cwd": v.cwd, "status": v.status, "since": v.since,
            "attached": v.attached, "unseen": v.unseen, "activity": activity_text(v),
            "prompt": v.st.get("prompt"), "claude_session_id": v.st.get("claude_sid"),
        } for v in views], ensure_ascii=False, indent=1))
        return 0
    if not views:
        on = sys.stdout.isatty()
        print("Keine Sessions.  Neue starten: %s (im Projektordner) oder %s → n" % (_c("1", "ccn", on), _c("1", "ccm", on)))
        return 0
    import shutil
    on = sys.stdout.isatty()
    W = shutil.get_terminal_size((120, 24)).columns
    nw = min(24, max(4, max(len(v.name) for v in views)))
    dirs = []
    for v in views:
        b = git_branch(v.cwd)
        dirs.append(tilde(v.cwd) + ((" (%s)" % b) if b else ""))
    dw_ = min(34, max(6, max(len(d) for d in dirs)))
    labs = [(v.note or LABELS.get(v.status, v.status)) + " · " + fmt_age(t - v.since) for v in views]
    lw = max(len(x) for x in labs)
    for v, d, lab in zip(views, dirs, labs):
        g, col = STATIC_GLYPH.get(v.status, ("?", 245))
        if v.status == "done" and v.unseen:
            g = "●"
        d = short_path(d, dw_)
        act_w = max(0, W - (3 + nw + 2 + lw + 2 + dw_ + 2))
        act = oneline(activity_text(v), act_w) if act_w > 8 else ""
        name = v.name if len(v.name) <= nw else v.name[: nw - 1] + "…"
        print(" %s %s  %s  %s  %s" % (
            _c("38;5;%d" % col, g, on),
            _c("1", name.ljust(nw), on and (v.unseen or v.status in ATTN)),
            _c("38;5;%d" % col, lab.ljust(lw), on),
            _c("38;5;245", d.ljust(dw_), on),
            _c("2", act, on) if v.status in ("idle", "exited") else act))
    return 0


def cmd_peek(argv):
    if not argv:
        raise CCMError("Welche Session? ccm peek <name>")
    m = find_session(argv[0])
    tname = TPREFIX + m["id"]
    if not tmux_alive(tname):
        st = read_state(m["id"])
        print("»%s« ist beendet." % m["name"])
        if st.get("last_msg"):
            print("\nLetzte Antwort:\n" + strip_ctrl(st["last_msg"], multiline=True))
        return 0
    args = ["capture-pane", "-p", "-t", "=%s:" % tname]
    if sys.stdout.isatty():
        args.insert(2, "-e")
    out = tmux_run(args, check=True).stdout.rstrip("\n").split("\n")
    while out and not strip_ansi(out[-1]).strip():
        out.pop()
    print("\n".join(out) + ("\x1b[0m" if sys.stdout.isatty() else ""))
    return 0


def cmd_send(argv):
    if len(argv) < 2:
        raise CCMError("ccm send <name> <text>   (Text \"-\" liest von stdin)")
    m = find_session(argv[0])
    text = sys.stdin.read().strip() if argv[1:] == ["-"] else " ".join(argv[1:])
    tname = TPREFIX + m["id"]
    if not tmux_alive(tname):
        raise CCMError("»%s« läuft nicht. Erst fortsetzen: ccm resume %s" % (m["name"], m["name"]))
    tmux_send(tname, text=text, enter=True)
    print("→ an »%s« gesendet" % m["name"])
    return 0


def cmd_rename(argv):
    if len(argv) != 2:
        raise CCMError("ccm rename <name> <neuer-name>")
    m = rename_session(find_session(argv[0]), argv[1])
    print("✓ umbenannt in »%s«" % m["name"])
    return 0


def cmd_kill(argv):
    if not argv:
        raise CCMError("ccm kill <name>")
    for q in argv:
        m = find_session(q)
        kill_session(m)
        print("■ »%s« beendet (fortsetzen: ccm resume %s)" % (m["name"], m["name"]))
    return 0


def cmd_rm(argv):
    names = [a for a in argv if not a.startswith("-")]
    if not names:
        raise CCMError("ccm rm <name> …")
    for q in names:
        m = find_session(q)
        remove_session(m)
        print("✕ »%s« entfernt" % m["name"])
    return 0


def cmd_resume(argv):
    fresh = "--fresh" in argv
    detach = "-d" in argv or "--detach" in argv
    names = [a for a in argv if not a.startswith("-")]
    if not names:
        raise CCMError("ccm resume <name> [--fresh] [-d]")
    m = find_session(names[0])
    if tmux_alive(TPREFIX + m["id"]):
        print("»%s« läuft bereits." % m["name"])
    else:
        resume_session(m, fresh=fresh)
        print("▶ »%s« %s" % (m["name"], "frisch gestartet" if fresh else "fortgesetzt"))
    if not detach and tty():
        attach_and_report(m)
    return 0


def cmd_config(argv):
    if not os.path.exists(CONFIG_PATH):
        write_json(CONFIG_PATH, DEFAULT_CONFIG, pretty=True)
        print("Neue Konfiguration angelegt.")
    print("Konfiguration:  %s" % CONFIG_PATH)
    print(json.dumps(load_config(), indent=1, ensure_ascii=False))
    print("\nDaten:          %s" % DATA)
    print("tmux-Socket:    tmux -L %s ls" % SOCKET)
    print("eigene tmux-Einstellungen: %s" % os.path.join(os.path.dirname(CONFIG_PATH), "tmux.conf"))
    return 0


def cmd_tmux_status(cur):
    try:
        views = snapshot(capture=True)
    except Exception:
        return 0
    others = [v for v in views if v.tname != cur]
    attn = [v.name.replace("#", "##") for v in others if v.status in ATTN]
    work = [v for v in others if v.status in BUSY]
    done = [v for v in others if v.unseen]
    parts = []
    if attn:
        parts.append("#[fg=colour221,bold]▲ %s%s#[nobold]" % (", ".join(attn[:3]), " …" if len(attn) > 3 else ""))
    if work:
        parts.append("#[fg=colour75]● %d aktiv" % len(work))
    if done:
        parts.append("#[fg=colour114]✓ %d fertig" % len(done))
    print(("  ".join(parts) + "#[default]") if parts else "")
    return 0


def cmd_dashboard():
    if not tty():
        return cmd_ls([])
    import shutil
    if not shutil.which("tmux"):
        raise CCMError(NO_TMUX)
    import ccm_ui
    return ccm_ui.run()


COMMANDS = {
    "new": cmd_new, "n": cmd_new,
    "a": cmd_attach, "attach": cmd_attach, "open": cmd_attach, "o": cmd_attach,
    "ls": cmd_ls, "list": cmd_ls,
    "peek": cmd_peek, "show": cmd_peek,
    "send": cmd_send,
    "rename": cmd_rename, "mv": cmd_rename,
    "kill": cmd_kill, "stop": cmd_kill,
    "resume": cmd_resume, "start": cmd_resume,
    "rm": cmd_rm, "remove": cmd_rm, "delete": cmd_rm,
    "config": cmd_config,
}


def main(argv=None):
    argv = sys.argv if argv is None else argv
    prog = os.path.basename(argv[0]) if argv else "ccm"
    args = argv[1:]
    secure_data_dir()
    try:
        if prog == "ccn":
            return cmd_new(args)
        if not args:
            return cmd_dashboard()
        c, rest = args[0], args[1:]
        if c == "_hook":
            return cmd_hook()
        if c == "_run":
            return cmd_run(rest[0])
        if c == "_status":
            return cmd_tmux_status(rest[0] if rest else "")
        if c in ("help", "-h", "--help"):
            print(HELP)
            return 0
        if c in ("version", "--version", "-V"):
            print("ccm " + VERSION)
            return 0
        fn = COMMANDS.get(c)
        if not fn:
            eprint("ccm: unbekannter Befehl »%s«\n" % c)
            eprint(HELP)
            return 2
        return fn(rest) or 0
    except CCMError as e:
        eprint("\x1b[31mccm:\x1b[0m %s" % e if sys.stderr.isatty() else "ccm: %s" % e)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
