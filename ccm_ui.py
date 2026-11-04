"""ccm – interaktives Dashboard (curses, nur Standardbibliothek)."""

import curses
import locale
import os
import shlex
import time
import unicodedata

import ccm

# ───────────────────────────── Farben (xterm-256) ─────────────────────────────
ACCENT = 173      # Claude-Orange
WORK = 75         # blau  – arbeitet
ATTN = 221        # gelb  – wartet auf dich
DONE = 114        # grün  – fertig
ERR = 203         # rot
PURPLE = 141      # komprimiert
BRANCH = 109      # git-Branch
MUTED = 245
DIM = 241
BORDER = 238
SEL_BG = 236
SEL_FG = 255
MODAL_BG = 235
MODAL_FG = 252
INPUT_BG = 238
WHITE = 255

SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
ENTER = ("\n", "\r", curses.KEY_ENTER)
A_ITALIC = getattr(curses, "A_ITALIC", 0)

STATUS_COLOR = {
    "starting": MUTED, "working": WORK, "compacting": PURPLE,
    "permission": ATTN, "question": ATTN, "plan": ATTN, "input": ATTN,
    "done": DONE, "idle": MUTED, "error": ERR, "exited": DIM,
}

LOG_KIND = {
    "prompt": ("❯", ACCENT, "Prompt"),
    "tool": ("·", MUTED, "Tool"),
    "perm": ("▲", ATTN, "Freigabe"),
    "ask": ("?", ATTN, "Rückfrage"),
    "plan": ("▲", ATTN, "Plan"),
    "done": ("✓", DONE, "fertig"),
    "error": ("✕", ERR, "Fehler"),
    "fail": ("✕", ERR, "Fehler"),
    "exit": ("✕", ERR, "Exit"),
    "interrupt": ("■", MUTED, "abgebrochen"),
    "start": ("▶", MUTED, "Start"),
    "end": ("■", MUTED, "Ende"),
    "compact": ("◇", PURPLE, "komprimiert"),
    "agent": ("◆", WORK, "Subagent"),
}


# ───────────────────────────── Zeichenbreiten ─────────────────────────────
_CW = {}


def cw(ch):
    o = ord(ch)
    if 0x20 <= o < 0x7F:
        return 1
    w = _CW.get(ch)
    if w is None:
        if o < 0x20 or 0x7F <= o < 0xA0:
            w = 0
        elif unicodedata.combining(ch) or unicodedata.category(ch) in ("Mn", "Me", "Cf"):
            w = 0
        elif unicodedata.east_asian_width(ch) in ("W", "F"):
            w = 2
        else:
            w = 1
        _CW[ch] = w
    return w


def dw(s):
    if s.isascii():
        return len(s)
    return sum(cw(c) for c in s)


def clip(s, maxw, ell=True):
    """(text, breite) so kürzen, dass breite <= maxw."""
    if maxw <= 0 or not s:
        return "", 0
    if s.isascii():
        if len(s) <= maxw:
            return s, len(s)
        if ell:
            return s[: maxw - 1] + "…", maxw
        return s[:maxw], maxw
    w = 0
    for i, ch in enumerate(s):
        c = cw(ch)
        if w + c > maxw:
            if not ell:
                return s[:i], w
            t, tw = s[:i], w
            while t and tw + 1 > maxw:
                tw -= cw(t[-1])
                t = t[:-1]
            return t + "…", tw + 1
        w += c
    return s, w


def shorten_path(p, maxw):
    if dw(p) <= maxw:
        return p
    parts = p.split("/")
    out = parts[-1]
    for part in reversed(parts[:-1]):
        cand = part + "/" + out
        if dw(cand) + 2 > maxw:
            break
        out = cand
    return clip("…/" + out, maxw)[0]


# ───────────────────────────── ANSI → curses ─────────────────────────────

def _xterm_rgb(n):
    if n < 16:
        return [(0, 0, 0), (205, 0, 0), (0, 205, 0), (205, 205, 0), (0, 0, 238), (205, 0, 205),
                (0, 205, 205), (229, 229, 229), (127, 127, 127), (255, 0, 0), (0, 255, 0),
                (255, 255, 0), (92, 92, 255), (255, 0, 255), (0, 255, 255), (255, 255, 255)][n]
    if n < 232:
        n -= 16
        lv = (0, 95, 135, 175, 215, 255)
        return lv[n // 36], lv[(n // 6) % 6], lv[n % 6]
    g = 8 + (n - 232) * 10
    return g, g, g


def rgb_to_256(r, g, b):
    def q(v):
        return 0 if v < 48 else 1 if v < 115 else min(5, (v - 35) // 40)
    lv = (0, 95, 135, 175, 215, 255)
    cr, cg, cb = q(r), q(g), q(b)
    cube = 16 + 36 * cr + 6 * cg + cb
    dc = (lv[cr] - r) ** 2 + (lv[cg] - g) ** 2 + (lv[cb] - b) ** 2
    avg = (r + g + b) // 3
    gi = 0 if avg < 8 else min(23, (avg - 8) // 10)
    gv = 8 + gi * 10
    dg = (gv - r) ** 2 + (gv - g) ** 2 + (gv - b) ** 2
    return cube if dc <= dg else 232 + gi


def _int(s):
    try:
        return max(0, min(255, int(s or 0)))
    except ValueError:
        return 0


def apply_sgr(params, fg, bg, fl):
    if not params:
        return -1, -1, 0
    if params[0] in "<=>?":
        return fg, bg, fl
    if ":" in params:
        params = params.replace("::", ":").replace(":", ";")
    p = params.split(";")
    i, n = 0, len(p)
    while i < n:
        try:
            c = int(p[i] or 0)
        except ValueError:
            i += 1
            continue
        if c == 0:
            fg, bg, fl = -1, -1, 0
        elif c == 1:
            fl |= 1
        elif c == 2:
            fl |= 2
        elif c == 3:
            fl |= 4
        elif c == 4:
            fl |= 8
        elif c == 7:
            fl |= 16
        elif c == 22:
            fl &= ~3
        elif c == 23:
            fl &= ~4
        elif c == 24:
            fl &= ~8
        elif c == 27:
            fl &= ~16
        elif 30 <= c <= 37:
            fg = c - 30
        elif c == 39:
            fg = -1
        elif 40 <= c <= 47:
            bg = c - 40
        elif c == 49:
            bg = -1
        elif 90 <= c <= 97:
            fg = c - 82
        elif 100 <= c <= 107:
            bg = c - 92
        elif c in (38, 48, 58):
            col = None
            if i + 2 < n and p[i + 1] == "5":
                col = _int(p[i + 2])
                i += 2
            elif i + 4 < n and p[i + 1] == "2":
                col = rgb_to_256(_int(p[i + 2]), _int(p[i + 3]), _int(p[i + 4]))
                i += 4
            if col is not None:
                if c == 38:
                    fg = col
                elif c == 48:
                    bg = col
        i += 1
    return fg, bg, fl


def parse_ansi_screen(raw):
    esc = ccm._rx().esc
    fg, bg, fl = -1, -1, 0
    out = []
    for line in raw.split("\n"):
        segs = []
        pos = 0
        for m in esc.finditer(line):
            if m.start() > pos:
                segs.append((line[pos:m.start()], (fg, bg, fl)))
            if m.group(2) == "m":
                fg, bg, fl = apply_sgr(m.group(1) or "", fg, bg, fl)
            pos = m.end()
        if pos < len(line):
            segs.append((line[pos:], (fg, bg, fl)))
        out.append(segs)
    return out


def clip_segs(segs, width):
    out, w = [], 0
    for text, key in segs:
        if w >= width:
            break
        if "\t" in text:
            text = text.replace("\t", "    ")
        if not text.isprintable():
            text = "".join(ch for ch in text if ch.isprintable() or ord(ch) > 0x9F)
        s, sw = clip(text, width - w, ell=False)
        if s:
            out.append((s, key))
            w += sw
    return out


class Pairs:
    """Verwaltet curses-Farbpaare (max. 255 in Attributen nutzbar)."""

    def __init__(self):
        self.ok = curses.has_colors()
        self.default_ok = False
        self.ncolors = 8
        if self.ok:
            try:
                curses.start_color()
                curses.use_default_colors()
                self.default_ok = True
            except curses.error:
                pass
            self.ncolors = curses.COLORS
        self.max = min(255, (curses.COLOR_PAIRS - 1) if self.ok else 0)
        self.cache = {}
        self.next = 1
        self.full = False

    def _map(self, c, is_bg):
        if c is None or c < 0:
            return -1 if self.default_ok else (0 if is_bg else 7)
        if c < self.ncolors:
            return c
        r, g, b = _xterm_rgb(c)
        best, bd = 7, 1 << 30
        for i in range(min(self.ncolors, 16)):
            rr, gg, bb = _xterm_rgb(i)
            d = (r - rr) ** 2 + (g - gg) ** 2 + (b - bb) ** 2
            if d < bd:
                best, bd = i, d
        return best

    def get(self, fg, bg):
        key = (fg, bg)
        p = self.cache.get(key)
        if p is None:
            if not self.ok:
                return 0
            if self.next > self.max:
                self.full = True
                return 0
            p = self.next
            self.next += 1
            try:
                curses.init_pair(p, self._map(fg, False), self._map(bg, True))
            except curses.error:
                p = 0
            self.cache[key] = p
        return curses.color_pair(p) if p else 0

    def maybe_reset(self):
        if not self.full:
            return False
        self.cache.clear()
        self.next = 1
        self.full = False
        return True


# ───────────────────────────── Eingabefeld ─────────────────────────────

class TextInput:
    def __init__(self, text="", placeholder=""):
        self.buf = list(text)
        self.pos = len(self.buf)
        self.scroll = 0
        self.placeholder = placeholder

    @property
    def text(self):
        return "".join(self.buf)

    def set(self, t):
        self.buf = list(t)
        self.pos = len(self.buf)
        self.scroll = 0

    def key(self, k):
        b = self.buf
        if k in (curses.KEY_BACKSPACE, "\x7f", "\x08"):
            if self.pos > 0:
                del b[self.pos - 1]
                self.pos -= 1
        elif k in (curses.KEY_DC, "\x04"):
            if self.pos < len(b):
                del b[self.pos]
        elif k in (curses.KEY_LEFT, "\x02"):
            self.pos = max(0, self.pos - 1)
        elif k in (curses.KEY_RIGHT, "\x06"):
            self.pos = min(len(b), self.pos + 1)
        elif k in (curses.KEY_HOME, "\x01"):
            self.pos = 0
        elif k in (curses.KEY_END, "\x05"):
            self.pos = len(b)
        elif k == "\x15":
            del b[: self.pos]
            self.pos = 0
        elif k == "\x0b":
            del b[self.pos:]
        elif k == "\x17":
            i = self.pos
            while i > 0 and b[i - 1] == " ":
                i -= 1
            while i > 0 and b[i - 1] not in " /":
                i -= 1
            if i == self.pos and i > 0:
                i -= 1
            del b[i: self.pos]
            self.pos = i
        elif isinstance(k, str) and k.isprintable():
            for ch in k:
                b.insert(self.pos, ch)
                self.pos += 1
        else:
            return False
        return True

    def draw(self, ui, y, x, w, focused=True, bg=INPUT_BG):
        base = ui.c(MODAL_FG, bg)
        ui.put(y, x, " " * w, base, ell=False)
        text = self.text
        cur = ui.c(MODAL_FG, bg, rev=True)
        if not text:
            if self.placeholder:
                ui.put(y, x + 1, self.placeholder, ui.c(243, bg, italic=True), w=w - 2)
            if focused:
                ui.put(y, x, " ", cur, ell=False)
            return
        avail = w - 1
        if self.pos < self.scroll:
            self.scroll = self.pos
        while self.scroll < self.pos and dw(text[self.scroll:self.pos]) > avail - 1:
            self.scroll += 1
        s, _ = clip(text[self.scroll:], avail, ell=False)
        ui.put(y, x, s, base, ell=False)
        if focused:
            cx = x + dw(text[self.scroll:self.pos])
            ch = text[self.pos] if self.pos < len(text) else " "
            ui.put(y, cx, ch, cur, ell=False)


# ───────────────────────────── Modale Dialoge ─────────────────────────────

class Confirm:
    def __init__(self, title, lines, on_yes, enter_ok=True, yes_label="ja"):
        self.title, self.lines, self.on_yes = title, lines, on_yes
        self.enter_ok, self.yes_label = enter_ok, yes_label

    def draw(self, ui):
        w = min(ui.W - 4, max(48, max(dw(l) for l in self.lines) + 8))
        h = len(self.lines) + 5
        y, x = max(0, (ui.H - h) // 2), max(0, (ui.W - w) // 2)
        ui.box(y, x, h, w, self.title)
        for i, l in enumerate(self.lines):
            ui.put(y + 2 + i, x + 3, l, ui.c(MODAL_FG if i == 0 else 246, MODAL_BG, bold=(i == 0)), w=w - 6)
        hint = [("j", self.yes_label), ("n", "abbrechen")]
        if self.enter_ok:
            hint[0] = ("↵/j", self.yes_label)
        ui.hints(y + h - 2, x + 3, hint, bg=MODAL_BG, maxx=x + w - 2)

    def key(self, ui, k):
        if k in ("j", "J", "y", "Y") or (self.enter_ok and k in ENTER):
            ui.modal = None
            self.on_yes()
        elif k in ("n", "N", "\x1b", "q", "\x03"):
            ui.modal = None


class Prompt:
    def __init__(self, title, initial="", placeholder="", on_submit=None, hint=None, bottom=False):
        self.title = title
        self.inp = TextInput(initial, placeholder)
        self.on_submit = on_submit
        self.hint = hint or [("↵", "ok"), ("esc", "abbrechen")]
        self.bottom = bottom
        self.err = None

    def draw(self, ui):
        w = min(ui.W - 4, 96)
        h = 6 if self.err else 5
        y = (ui.H - h - 1) if self.bottom else (ui.H - h) // 2
        x = max(0, (ui.W - w) // 2)
        ui.box(max(0, y), x, h, w, self.title)
        ui.put(y + 2, x + 3, "❯", ui.c(ACCENT, MODAL_BG, bold=True))
        self.inp.draw(ui, y + 2, x + 5, w - 8)
        if self.err:
            ui.put(y + 3, x + 5, self.err, ui.c(ERR, MODAL_BG), w=w - 8)
        ui.hints(y + h - 2, x + 3, self.hint, bg=MODAL_BG, maxx=x + w - 2)

    def key(self, ui, k):
        if k in ("\x1b", "\x03"):
            ui.modal = None
        elif k in ENTER:
            ui.modal = None
            err = self.on_submit(self.inp.text) if self.on_submit else None
            if err:
                self.err = err
                ui.modal = self
        else:
            if self.inp.key(k):
                self.err = None


HELP_LINES = [
    ("", "Navigation"),
    ("↑ ↓  j k", "Session wählen (auch per Mausklick / Mausrad)"),
    ("↵", "Session öffnen – beendete werden fortgesetzt"),
    ("Ctrl-Q", "in einer Session: zurück hierher, Claude läuft weiter"),
    ("", "Aktionen"),
    ("n", "neue Session (Ordner wählen, optional mit Aufgabe)"),
    ("s", "Nachricht an die Session schicken, ohne sie zu öffnen"),
    ("1 – 9", "Freigabe / Rückfrage direkt beantworten (z.B. 1 = Yes)"),
    ("r", "umbenennen"),
    ("x", "Claude stoppen (bleibt fortsetzbar) · bei beendeten: entfernen"),
    ("X", "sofort beenden und aus der Liste entfernen"),
    ("F", "beendete Session frisch starten (ohne Verlauf)"),
    ("", "Ansicht"),
    ("Tab", "Live-Bildschirm ↔ Verlauf (was die Session getan hat)"),
    ("v", "Vorschau ein/aus"),
    ("o", "Sortierung: erstellt ↔ letzte Aktivität"),
    ("/", "filtern nach Name oder Ordner"),
    ("q", "Dashboard schließen – alle Sessions laufen weiter"),
    ("", "Im Terminal"),
    ("ccn [aufgabe]", "neue Session im aktuellen Ordner starten & öffnen"),
    ("ccm a [name]", "Session öffnen (ohne Name: die im aktuellen Ordner)"),
    ("ccm ls", "alle Sessions auflisten  ·  ccm help für alles"),
]


class Help:
    def draw(self, ui):
        w = min(ui.W - 2, 78)
        h = min(ui.H - 1, len(HELP_LINES) + 4)
        y, x = max(0, (ui.H - h) // 2), max(0, (ui.W - w) // 2)
        ui.box(y, x, h, w, "Tastenkürzel")
        for i, (k, d) in enumerate(HELP_LINES[: h - 4]):
            yy = y + 2 + i
            if not k:
                ui.put(yy, x + 3, d, ui.c(ACCENT, MODAL_BG, bold=True))
            else:
                ui.put(yy, x + 5, k, ui.c(WHITE, MODAL_BG, bold=True), w=15)
                ui.put(yy, x + 21, d, ui.c(248, MODAL_BG), w=w - 23)
        ui.put(y + h - 1, x + w - 22, " beliebige Taste ", ui.c(MUTED, MODAL_BG))

    def key(self, ui, k):
        ui.modal = None


def expand_path(q, base):
    p = os.path.expanduser(q.strip())
    if not os.path.isabs(p):
        p = os.path.join(base, p)
    return os.path.normpath(p)


def fuzzy_score(q, path):
    ql = q.lower()
    base = os.path.basename(path).lower()
    tp = ccm.tilde(path).lower()
    if base.startswith(ql):
        return 0
    if ql in base:
        return 1
    if ql in tp:
        return 2
    it = iter(tp)
    if all(ch in it for ch in ql):
        return 3
    return None


class NewSession:
    FIELDS = ("Name", "Aufgabe", "Args", "Öffnen")

    def __init__(self, ui):
        self.base = ui.base
        self.step = "dir"
        self.q = TextInput("", "Ordner suchen oder Pfad tippen (~/…  /…)")
        self.recent = ccm.recent_dirs()
        self.running = {v.cwd for v in ui.views if v.alive}
        self.cands, self.ci, self.cscroll = [], 0, 0
        self.err, self.create_confirm = None, None
        self.dir = None
        self.f = [TextInput("", ""),
                  TextInput("", "optional – erste Aufgabe, Claude legt sofort los"),
                  TextInput("", "optional – z.B. --model sonnet  --permission-mode plan")]
        self.field = 1
        self.open_now, self.open_touched = True, False
        self.update()

    # ---- Ordner-Auswahl
    def update(self):
        qs = self.q.text.strip()
        path_mode = qs.startswith(("/", "~", ".")) or "/" in qs
        cands = []
        seen = set()

        def add(p, tag=""):
            p = os.path.normpath(p)
            if p not in seen:
                seen.add(p)
                cands.append((p, tag))
        if path_mode:
            p = expand_path(qs, self.base)
            if qs.endswith("/"):
                parent, pref = p, ""
            else:
                parent, pref = os.path.dirname(p), os.path.basename(p)
            if os.path.isdir(p):
                add(p, "↵ dieser Ordner")
            for d in ccm.list_subdirs(parent, pref, hidden=pref.startswith(".")):
                add(d)
        else:
            pool = [(self.base, "hier")] + [(d, "zuletzt") for d in self.recent] + \
                   [(d, "") for d in ccm.list_subdirs(self.base)]
            if qs:
                scored = []
                for i, (p, tag) in enumerate(pool):
                    sc = fuzzy_score(qs, p)
                    if sc is not None:
                        scored.append((sc, i, p, tag))
                scored.sort()
                pool = [(p, tag) for _, _, p, tag in scored]
            for p, tag in pool:
                add(p, tag)
        self.cands = cands[:300]
        self.ci = 0
        self.cscroll = 0

    def choose(self, path):
        self.dir = path
        base = ccm.clean_name(os.path.basename(path)) or "home"
        self.f[0].placeholder = ccm.unique_name(base, ccm.load_metas())
        self.step = "form"
        self.field = 1
        self.err = None

    # ---- Zeichnen
    def draw(self, ui):
        if self.step == "dir":
            self.draw_dir(ui)
        else:
            self.draw_form(ui)

    def draw_dir(self, ui):
        w = min(ui.W - 4, 86)
        h = min(ui.H - 2, 24)
        y, x = max(0, (ui.H - h) // 2), max(0, (ui.W - w) // 2)
        ui.box(y, x, h, w, "Neue Session · Ordner wählen")
        ui.put(y + 2, x + 3, "❯", ui.c(ACCENT, MODAL_BG, bold=True))
        self.q.draw(ui, y + 2, x + 5, w - 8)
        ui.put(y + 3, x + 3, "─" * (w - 6), ui.c(BORDER, MODAL_BG), ell=False)
        rows = h - 7
        if self.ci < self.cscroll:
            self.cscroll = self.ci
        if self.ci >= self.cscroll + rows:
            self.cscroll = self.ci - rows + 1
        if not self.cands:
            msg = "Keine passenden Ordner." if self.q.text.strip() else "Keine Ordner gefunden."
            ui.put(y + 4, x + 5, msg, ui.c(MUTED, MODAL_BG, italic=True))
        for r in range(rows):
            i = self.cscroll + r
            if i >= len(self.cands):
                break
            p, tag = self.cands[i]
            yy = y + 4 + r
            sel = i == self.ci
            bg = INPUT_BG if sel else MODAL_BG
            if sel:
                ui.put(yy, x + 2, " " * (w - 4), ui.c(MODAL_FG, bg), ell=False)
                ui.put(yy, x + 2, "▌", ui.c(ACCENT, bg))
            if p in self.running:
                tag = (tag + " · " if tag else "") + "● läuft"
            tw = dw(tag)
            disp = shorten_path(ccm.tilde(p), w - 10 - tw)
            ui.put(yy, x + 4, disp, ui.c(WHITE if sel else MODAL_FG, bg, bold=sel))
            if tag:
                ui.put(yy, x + w - 4 - tw, tag, ui.c(DONE if "läuft" in tag else MUTED, bg))
        if len(self.cands) > rows:
            ui.put(y + h - 3, x + w - 14, "%d/%d" % (self.ci + 1, len(self.cands)), ui.c(DIM, MODAL_BG))
        if self.err:
            ui.put(y + h - 2, x + 3, self.err, ui.c(ATTN, MODAL_BG), w=w - 6)
        else:
            ui.hints(y + h - 2, x + 3, [("↑↓", "wählen"), ("⇥", "hinein"), ("↵", "übernehmen"),
                                        ("esc", "abbrechen")], bg=MODAL_BG, maxx=x + w - 2)

    def draw_form(self, ui):
        w = min(ui.W - 4, 86)
        h = 13 if self.err else 12
        y, x = max(0, (ui.H - h) // 2), max(0, (ui.W - w) // 2)
        ui.box(y, x, h, w, "Neue Session")
        lx, fx = x + 3, x + 14
        fw = w - 17
        ui.put(y + 2, lx, "Ordner", ui.c(246, MODAL_BG))
        xx = ui.put(y + 2, fx, shorten_path(ccm.tilde(self.dir), fw - 12), ui.c(WHITE, MODAL_BG, bold=True))
        br = ccm.git_branch(self.dir)
        if br:
            ui.put(y + 2, xx + 1, br, ui.c(BRANCH, MODAL_BG), w=x + w - 3 - xx)
        for i in range(3):
            yy = y + 4 + i
            foc = self.field == i
            ui.put(yy, lx, self.FIELDS[i], ui.c(ACCENT if foc else 246, MODAL_BG, bold=foc))
            self.f[i].draw(ui, yy, fx, fw, focused=foc)
        yy = y + 7
        foc = self.field == 3
        ui.put(yy, lx, "Öffnen", ui.c(ACCENT if foc else 246, MODAL_BG, bold=foc))
        a_on = ui.c(WHITE, MODAL_BG, bold=True)
        a_off = ui.c(MUTED, MODAL_BG)
        xx = ui.put(yy, fx, ("◉ " if self.open_now else "○ ") + "direkt öffnen", a_on if self.open_now else a_off)
        ui.put(yy, xx + 3, ("◉ " if not self.open_now else "○ ") + "im Hintergrund arbeiten lassen",
               a_on if not self.open_now else a_off)
        if foc:
            ui.put(yy, fx - 2, "›", ui.c(ACCENT, MODAL_BG, bold=True))
        if self.err:
            ui.put(y + 9, lx, self.err, ui.c(ERR, MODAL_BG), w=w - 6)
        ui.hints(y + h - 2, lx, [("↵", "starten"), ("↑↓ ⇥", "Feld"), ("␣", "Öffnen umschalten"),
                                 ("esc", "zurück")], bg=MODAL_BG, maxx=x + w - 2)

    # ---- Tasten
    def key(self, ui, k):
        if self.step == "dir":
            return self.key_dir(ui, k)
        return self.key_form(ui, k)

    def key_dir(self, ui, k):
        if k in ("\x1b", "\x03"):
            ui.modal = None
        elif k in (curses.KEY_UP, "\x10"):
            self.ci = max(0, self.ci - 1)
        elif k in (curses.KEY_DOWN, "\x0e"):
            self.ci = min(max(0, len(self.cands) - 1), self.ci + 1)
        elif k == curses.KEY_PPAGE:
            self.ci = max(0, self.ci - 10)
        elif k == curses.KEY_NPAGE:
            self.ci = min(max(0, len(self.cands) - 1), self.ci + 10)
        elif k == "\t":
            if self.cands:
                self.q.set(ccm.tilde(self.cands[self.ci][0]).rstrip("/") + "/")
                self.update()
        elif k in ENTER:
            if self.cands:
                self.choose(self.cands[self.ci][0])
                return
            qs = self.q.text.strip()
            if not qs:
                return
            p = expand_path(qs, self.base)
            if os.path.isdir(p):
                self.choose(p)
            elif self.create_confirm == p:
                try:
                    os.makedirs(p)
                    self.choose(p)
                except OSError as e:
                    self.err = "Konnte Ordner nicht anlegen: %s" % e.strerror
            else:
                self.create_confirm = p
                self.err = "»%s« gibt es nicht – nochmal ↵ legt den Ordner an" % ccm.tilde(p)
        elif self.q.key(k):
            self.err, self.create_confirm = None, None
            self.update()

    def key_form(self, ui, k):
        if k in ("\x1b",):
            self.step = "dir"
            self.err = None
        elif k == "\x03":
            ui.modal = None
        elif k in (curses.KEY_UP, curses.KEY_BTAB):
            self.field = (self.field - 1) % 4
        elif k in (curses.KEY_DOWN, "\t"):
            self.field = (self.field + 1) % 4
        elif k in ENTER:
            self.submit(ui)
        elif self.field == 3:
            if k in (" ", curses.KEY_LEFT, curses.KEY_RIGHT, "h", "l"):
                self.open_now = not self.open_now
                self.open_touched = True
        else:
            if self.f[self.field].key(k):
                self.err = None
                if self.field == 1 and not self.open_touched:
                    self.open_now = not self.f[1].text.strip()

    def submit(self, ui):
        try:
            args = shlex.split(self.f[2].text)
        except ValueError as e:
            self.err = "Args: %s" % e
            return
        name = self.f[0].text.strip() or None
        prompt = self.f[1].text.strip() or None
        ui.modal = None
        ui.create(self.dir, name, prompt, args, self.open_now)


# ───────────────────────────── Dashboard ─────────────────────────────

class Cols:
    pass


class UI:
    def __init__(self, scr):
        self.scr = scr
        try:
            cwd = os.getcwd()
        except OSError:
            cwd = ccm.HOME
        self.base = cwd if os.path.isdir(cwd) else ccm.HOME
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        curses.raw()
        scr.keypad(True)
        self.pairs = Pairs()
        self._ac = {}
        self._ansi = {}
        self.setup_mouse()
        self.views = []
        self.sel_id = None
        self.last_idx = 0
        self.offset = 0
        self.mode = "live"
        self.show_preview = True
        self.filter = TextInput("", "")
        self.filtering = False
        self.sort_activity = False
        self.modal = None
        self.toast_msg, self.toast_kind, self.toast_until = None, "ok", 0
        self.last_refresh = 0
        self.row_ids = {}
        self.tab_y = -1
        self.prev_cache = {}
        self.quit = False
        self.H, self.W = scr.getmaxyx()

    # ---------- Grundlagen
    def setup_mouse(self):
        try:
            mask = (curses.BUTTON1_PRESSED | curses.BUTTON1_CLICKED |
                    getattr(curses, "BUTTON4_PRESSED", 0) | getattr(curses, "BUTTON5_PRESSED", 0))
            curses.mousemask(mask)
            curses.mouseinterval(0)
        except curses.error:
            pass

    def c(self, fg=-1, bg=-1, bold=False, dim=False, italic=False, rev=False, ul=False):
        key = (fg, bg, bold, dim, italic, rev, ul)
        a = self._ac.get(key)
        if a is None:
            a = self.pairs.get(fg, bg)
            if bold:
                a |= curses.A_BOLD
            if dim:
                a |= curses.A_DIM
            if italic:
                a |= A_ITALIC
            if rev:
                a |= curses.A_REVERSE
            if ul:
                a |= curses.A_UNDERLINE
            self._ac[key] = a
        return a

    def ansi_attr(self, key):
        a = self._ansi.get(key)
        if a is None:
            fg, bg, fl = key
            a = self.pairs.get(fg, bg)
            if fl & 1:
                a |= curses.A_BOLD
            if fl & 2:
                a |= curses.A_DIM
            if fl & 4:
                a |= A_ITALIC
            if fl & 8:
                a |= curses.A_UNDERLINE
            if fl & 16:
                a |= curses.A_REVERSE
            self._ansi[key] = a
        return a

    def put(self, y, x, s, attr=0, w=None, ell=True):
        """Text an (y,x) schreiben, auf Breite w / Bildschirmrand kürzen. Gibt neues x zurück."""
        if y < 0 or y >= self.H or x >= self.W or x < 0:
            return x
        lim = self.W - x if w is None else min(w, self.W - x)
        if lim <= 0:
            return x
        s, sw = clip(s, lim, ell)
        if not s:
            return x
        try:
            self.scr.addstr(y, x, s, attr)
        except curses.error:
            pass
        return x + sw

    def box(self, y, x, h, w, title=""):
        fill = self.c(MODAL_FG, MODAL_BG)
        b = self.c(ACCENT, MODAL_BG)
        for r in range(h):
            self.put(y + r, x, " " * w, fill, ell=False)
        self.put(y, x, "╭" + "─" * (w - 2) + "╮", b, ell=False)
        for r in range(1, h - 1):
            self.put(y + r, x, "│", b)
            self.put(y + r, x + w - 1, "│", b)
        self.put(y + h - 1, x, "╰" + "─" * (w - 2) + "╯", b, ell=False)
        if title:
            self.put(y, x + 2, " %s " % title, self.c(WHITE, MODAL_BG, bold=True), w=w - 4)

    def hints(self, y, x, items, bg=-1, maxx=None):
        maxx = self.W - 1 if maxx is None else maxx
        for i, (k, label) in enumerate(items):
            need = dw(k) + 1 + dw(label) + (2 if i else 0)
            if x + need > maxx:
                break
            if i:
                x += 2
            x = self.put(y, x, k, self.c(ACCENT, bg, bold=True))
            x = self.put(y, x + 1, label, self.c(MUTED if bg == -1 else 246, bg))
        return x

    def toast(self, msg, kind="ok", dur=3.0):
        self.toast_msg, self.toast_kind, self.toast_until = msg, kind, time.time() + dur

    # ---------- Daten
    def refresh(self):
        try:
            self.views = ccm.snapshot(capture=True, escapes=True)
        except ccm.CCMError as e:
            self.toast(str(e), "err")
            self.views = []
        self.last_refresh = time.time()
        vis = self.visible()
        if vis and not any(v.id == self.sel_id for v in vis):
            self.sel_id = vis[min(self.last_idx, len(vis) - 1)].id
        live = {v.id for v in self.views}
        for k in list(self.prev_cache):
            if k[0] not in live:
                del self.prev_cache[k]

    def visible(self):
        vs = self.views
        q = self.filter.text.strip().lower()
        if q:
            vs = [v for v in vs if q in v.name.lower() or q in ccm.tilde(v.cwd).lower()]
        if self.sort_activity:
            vs = sorted(vs, key=lambda v: -float(v.st.get("t") or v.meta.get("created") or 0))
        return vs

    def selected(self):
        vis = self.visible()
        for v in vis:
            if v.id == self.sel_id:
                return v
        return vis[0] if vis else None

    def sel_index(self, vis):
        for i, v in enumerate(vis):
            if v.id == self.sel_id:
                return i
        return 0

    def move(self, d):
        vis = self.visible()
        if not vis:
            return
        i = max(0, min(len(vis) - 1, self.sel_index(vis) + d))
        self.sel_id = vis[i].id
        self.last_idx = i

    def preview(self, v, width):
        key = (v.id, width)
        hit = self.prev_cache.get(key)
        if hit and hit[0] == v.raw:
            return hit[1]
        lines = parse_ansi_screen(v.raw or "")

        def blank(segs):
            return all((not t.strip()) and k[1] == -1 and not (k[2] & 16) for t, k in segs)
        while lines and blank(lines[-1]):
            lines.pop()
        out, prev_blank = [], True
        for segs in lines:
            b = blank(segs)
            if b and prev_blank:
                continue
            prev_blank = b
            out.append(clip_segs(segs, width))
        self.prev_cache[key] = (v.raw, out)
        return out

    # ---------- Zeichnen
    def draw(self):
        if self.pairs.maybe_reset():
            self._ac.clear()
            self._ansi.clear()
            self.scr.clearok(True)
        self.H, self.W = self.scr.getmaxyx()
        self.scr.erase()
        self.row_ids = {}
        self.tab_y = -1
        if self.H < 10 or self.W < 50:
            self.put(0, 0, "Fenster zu klein (min. 50×10)", self.c(ATTN, bold=True))
            self.put(1, 0, "q beendet", self.c(MUTED))
        else:
            self.draw_header()
            vis = self.visible()
            if not self.views:
                self.draw_empty()
            else:
                avail = self.H - 3
                n = max(1, len(vis))
                if self.show_preview and avail >= 14:
                    list_h = min(n, max(3, int(avail * 0.4)))
                else:
                    list_h = avail
                self.draw_list(vis, 1, list_h)
                py = 2 + list_h
                if py < self.H - 5 and self.show_preview:
                    v = self.selected()
                    if v:
                        self.draw_panel(v, py, self.H - 1)
            self.draw_footer()
            if self.modal:
                self.modal.draw(self)
        self.scr.noutrefresh()
        curses.doupdate()

    def draw_header(self):
        x = self.put(0, 0, " ◆ ccm ", self.c(ACCENT, bold=True))
        self.put(0, x, " Claude Code Sessions", self.c(MUTED))
        allv = self.views
        nw = sum(1 for v in allv if v.status in ccm.BUSY)
        na = sum(1 for v in allv if v.status in ccm.ATTN)
        nd = sum(1 for v in allv if v.unseen)
        frame = SPIN[int(time.time() * 10) % len(SPIN)]
        parts = []
        if nw:
            parts.append(("%s %d aktiv" % (frame, nw), WORK, False))
        if na:
            parts.append(("▲ %d %s" % (na, "wartet" if na == 1 else "warten"), ATTN, True))
        if nd:
            parts.append(("● %d fertig" % nd, DONE, True))
        if allv:
            parts.append(("%d Sessions" % len(allv), DIM, False))
        lvl_col = (MUTED, ATTN, ERR)
        for label, val, extra, lvl in ccm.usage_parts(None):
            parts.append(("%s %s%s" % (label, val, (" " + extra) if extra else ""), lvl_col[lvl], lvl == 2))
        parts.append((time.strftime("%H:%M"), MUTED, False))
        total = sum(dw(p[0]) for p in parts) + 3 * (len(parts) - 1) + 1
        xr = self.W - total
        for i, (txt, col, bold) in enumerate(parts):
            if i:
                xr = self.put(0, xr, "   ", 0)
            xr = self.put(0, xr, txt, self.c(col, bold=bold))

    def draw_empty(self):
        H, W = self.H, self.W
        y = max(2, H // 2 - 4)
        lines = [
            [("◆", ACCENT, True)],
            [("Noch keine Claude-Sessions", -1, True)],
            [],
            [("n", ACCENT, True), ("  neue Session starten", MUTED, False)],
            [("?", ACCENT, True), ("  alle Tastenkürzel", MUTED, False)],
            [],
            [("oder im Terminal:  ", DIM, False), ("cd mein-projekt && ccn", MUTED, True)],
        ]
        for i, segs in enumerate(lines):
            tw = sum(dw(t) for t, _, _ in segs)
            x = max(0, (W - tw) // 2)
            for t, col, bold in segs:
                x = self.put(y + i, x, t, self.c(col, bold=bold))

    def columns(self, vis):
        W = self.W
        c = Cols()
        c.x_name = 4
        c.name_w = min(24, max([8] + [dw(v.name) for v in vis]))
        c.x_status = c.x_name + c.name_w + 2
        c.status_w = 21
        c.dir_w = 0
        x = c.x_status + c.status_w + 1
        if W >= 100:
            c.dir_w = min(32, max([8] + [dw(self.dir_label(v)) for v in vis]))
            c.x_dir = x
            x += c.dir_w + 2
        c.x_act = x
        c.act_w = W - x - 1
        if c.act_w < 10:
            c.act_w = 0
        return c

    def dir_label(self, v):
        b = ccm.git_branch(v.cwd)
        return ccm.tilde(v.cwd) + ((" " + b) if b else "")

    def glyph(self, v):
        s, t = v.status, time.time()
        if s in ("working", "compacting", "starting"):
            return SPIN[int(t * 10) % len(SPIN)], STATUS_COLOR[s], s != "starting"
        if s in ccm.ATTN:
            return ("▲" if int(t * 2) % 2 == 0 else "△"), ATTN, True
        if s == "done":
            return ("●", DONE, True) if v.unseen else ("✓", DONE, False)
        if s == "error":
            return "✕", ERR, True
        if s == "exited":
            return "■", DIM, False
        return "○", MUTED, False

    def draw_list(self, vis, y0, list_h):
        W = self.W
        cols = self.columns(vis)
        hd = self.c(DIM)
        self.put(y0, cols.x_name, "NAME", hd)
        self.put(y0, cols.x_status, "STATUS", hd)
        if cols.dir_w:
            self.put(y0, cols.x_dir, "ORDNER", hd)
        if cols.act_w:
            self.put(y0, cols.x_act, "AKTIVITÄT", hd)
        tags = []
        if self.sort_activity:
            tags.append("sortiert: Aktivität")
        if self.filter.text and not self.filtering:
            tags.append("Filter: %s" % self.filter.text)
        if tags:
            t = "  ·  ".join(tags)
            self.put(y0, W - dw(t) - 2, t, self.c(ACCENT))
        if not vis:
            self.put(y0 + 1, 4, "Keine Treffer für »%s«  (esc löscht den Filter)" % self.filter.text,
                     self.c(MUTED, italic=True))
            return
        idx = self.sel_index(vis)
        if idx < self.offset:
            self.offset = idx
        if idx >= self.offset + list_h:
            self.offset = idx - list_h + 1
        self.offset = max(0, min(self.offset, max(0, len(vis) - list_h)))
        for r in range(list_h):
            i = self.offset + r
            if i >= len(vis):
                break
            y = y0 + 1 + r
            self.row_ids[y] = vis[i].id
            self.draw_row(y, vis[i], vis[i].id == self.sel_id, cols)
        if self.offset > 0:
            self.put(y0 + 1, W - 2, "↑", self.c(MUTED))
        if self.offset + list_h < len(vis):
            self.put(y0 + list_h, W - 2, "↓", self.c(MUTED))

    def draw_row(self, y, v, sel, cols):
        W = self.W
        bg = SEL_BG if sel else -1

        def fg(col):
            if not sel:
                return col
            return {-1: SEL_FG, MUTED: 250, DIM: 246}.get(col, col)
        if sel:
            self.put(y, 0, " " * W, self.c(-1, bg), ell=False)
            self.put(y, 0, "▌", self.c(ACCENT, bg))
        g, gcol, gbold = self.glyph(v)
        self.put(y, 2, g, self.c(gcol, bg, bold=gbold))
        strong = sel or v.unseen or v.status in ccm.ATTN
        ncol = -1 if v.status != "exited" else MUTED
        self.put(y, cols.x_name, v.name, self.c(fg(ncol), bg, bold=strong), w=cols.name_w)
        scol = STATUS_COLOR.get(v.status, MUTED)
        label = v.note or ccm.LABELS.get(v.status, v.status)
        x = self.put(y, cols.x_status, label, self.c(scol, bg, bold=v.status in ccm.ATTN), w=cols.status_w)
        age = ccm.fmt_age(time.time() - v.since)
        if x + 3 + len(age) <= cols.x_status + cols.status_w:
            self.put(y, x, " · " + age, self.c(fg(DIM), bg))
        if cols.dir_w:
            b = ccm.git_branch(v.cwd)
            bw = (dw(b) + 1) if b else 0
            d = shorten_path(ccm.tilde(v.cwd), max(6, cols.dir_w - bw))
            x = self.put(y, cols.x_dir, d, self.c(fg(MUTED), bg), w=cols.dir_w)
            if b and x + 2 < cols.x_dir + cols.dir_w:
                self.put(y, x + 1, b, self.c(BRANCH, bg), w=cols.x_dir + cols.dir_w - x - 1)
        if cols.act_w:
            s = v.status
            acol = {"working": -1, "permission": ATTN, "question": ATTN, "plan": ATTN, "input": ATTN,
                    "error": ERR, "compacting": PURPLE, "done": MUTED}.get(s, DIM)
            self.put(y, cols.x_act, ccm.activity_text(v), self.c(fg(acol), bg, italic=(s == "done")),
                     w=cols.act_w)

    def draw_panel(self, v, y0, y1):
        W = self.W
        self.put(y0, 0, "─" * W, self.c(BORDER), ell=False)
        x = self.put(y0, 2, " %s " % v.name, self.c(-1, bold=True))
        g, gcol, _ = self.glyph(v)
        x = self.put(y0, x, g + " " + (v.note or ccm.LABELS.get(v.status, "")) + " ", self.c(gcol))
        self.tab_y = y0
        tabs = [("Live", "live"), ("Verlauf", "log")]
        tx = W - (sum(len(n) + 2 for n, _ in tabs) + 6)
        tx = self.put(y0, tx, " ⇥ ", self.c(DIM))
        for n, m in tabs:
            on = self.mode == m
            tx = self.put(y0, tx, " %s " % n, self.c(ACCENT if on else MUTED, bold=on, ul=on))
        # Info-Zeile
        t = time.time()
        parts = [(ccm.tilde(v.cwd), MUTED)]
        b = ccm.git_branch(v.cwd)
        ti = ccm.transcript_info(v.st.get("transcript"))
        model = ccm.pretty_model(v.st.get("model") or (ti or {}).get("model"))
        if model:
            parts.append((model, MUTED))
        pct = v.st.get("ctx_pct")
        if isinstance(pct, (int, float)):
            txt = "ctx %d%%" % round(pct)
            if ti and ti.get("ctx"):
                txt += " (%s)" % ccm.fmt_tokens(ti["ctx"])
            parts.append((txt, (MUTED, ATTN, ERR)[ccm.usage_level(pct)]))
        elif ti and ti.get("ctx"):
            parts.append(("ctx " + ccm.fmt_tokens(ti["ctx"]), MUTED))
        if v.alive:
            lt = v.st.get("launch_t") or v.meta.get("launch_t")
            if lt:
                parts.append(("läuft seit " + ccm.fmt_dur(t - float(lt)), MUTED))
        else:
            parts.append(("beendet vor " + ccm.fmt_dur(t - v.since), MUTED))
        if v.attached:
            parts.append(("● gerade geöffnet", WORK))
        parts.append(("#" + v.id, DIM))
        x = 2
        for i, (txt, col) in enumerate(parts):
            if i:
                x = self.put(y0 + 1, x, "  ·  ", self.c(BORDER))
            x = self.put(y0 + 1, x, txt, self.c(col))
            if i == 0 and b:
                x = self.put(y0 + 1, x + 1, b, self.c(BRANCH))
        p = v.st.get("prompt")
        x = self.put(y0 + 2, 2, "❯ ", self.c(ACCENT, bold=True))
        if p:
            self.put(y0 + 2, x, ccm.oneline(p, 2000), self.c(-1), w=W - x - 1)
        else:
            self.put(y0 + 2, x, "noch keine Aufgabe", self.c(DIM, italic=True))
        cy = y0 + 4
        self.put(y0 + 3, 0, "╌" * W, self.c(BORDER), ell=False)
        if not v.alive:
            hint = "Session ist beendet  –  "
            x = self.put(cy, 2, hint, self.c(MUTED))
            self.hints(cy, x, [("↵", "fortsetzen" if v.st.get("has_conv") else "neu starten"),
                               ("F", "frisch starten"), ("x", "entfernen")])
            self.draw_log(v, cy + 2, y1)
        elif self.mode == "log":
            self.draw_log(v, cy, y1)
        else:
            self.draw_live(v, cy, y1)

    def draw_live(self, v, y0, y1):
        h = y1 - y0
        if h <= 0:
            return
        if v.raw is None:
            self.put(y0, 2, "Kein Bildschirminhalt verfügbar.", self.c(DIM, italic=True))
            return
        lines = self.preview(v, self.W - 2)
        show = lines[-h:]
        for i, segs in enumerate(show):
            x = 1
            for text, key in segs:
                x = self.put(y0 + i, x, text, self.ansi_attr(key), ell=False)

    def draw_log(self, v, y0, y1):
        h = y1 - y0
        if h <= 0:
            return
        evs = ccm.read_events(v.id)
        W = self.W
        if not evs:
            self.put(y0, 2, "Noch keine Aktivität aufgezeichnet.", self.c(DIM, italic=True))
            return
        today = time.strftime("%Y%m%d")
        for i, e in enumerate(evs[-h:]):
            y = y0 + i
            lt = time.localtime(float(e.get("t") or 0))
            ts = time.strftime("%H:%M:%S" if time.strftime("%Y%m%d", lt) == today else "%d.%m. %H:%M", lt)
            self.put(y, 2, ts, self.c(DIM))
            k = e.get("k")
            g, col, label = LOG_KIND.get(k, ("·", MUTED, str(k)))
            text = e.get("x") or ""
            if k in ("tool", "fail"):
                label = e.get("tool") or label
            if k == "perm":
                text = "%s · %s" % (e.get("tool") or "Tool", text) if text else (e.get("tool") or "")
            self.put(y, 14, g, self.c(col, bold=True))
            self.put(y, 16, label, self.c(col if k not in ("tool",) else 250, bold=k in ("prompt", "done", "perm")), w=12)
            tcol = -1 if k in ("prompt", "done", "ask", "perm") else MUTED
            x = self.put(y, 29, text, self.c(tcol), w=W - 30)
            extra = e.get("y")
            if extra and k == "tool" and x < W - 6:
                self.put(y, x + 2, "— " + extra, self.c(DIM), w=W - x - 3)

    def draw_footer(self):
        y, W = self.H - 1, self.W
        if self.toast_msg and time.time() < self.toast_until:
            col = {"ok": DONE, "err": ERR, "info": ACCENT}.get(self.toast_kind, ACCENT)
            self.put(y, 0, " " * (W - 1), self.c(-1, SEL_BG), ell=False)
            self.put(y, 1, self.toast_msg, self.c(col, SEL_BG, bold=True), w=W - 3)
            return
        if self.filtering:
            x = self.put(y, 1, "Filter ", self.c(ACCENT, bold=True))
            self.filter.draw(self, y, x, min(40, W - x - 30), focused=True, bg=SEL_BG)
            self.hints(y, x + min(40, W - x - 30) + 2, [("↵", "fertig"), ("esc", "löschen")])
            return
        v = self.selected()
        items = []
        if v and v.alive and v.status in ("permission", "question", "plan"):
            items.append(("1-9", "antworten"))
        if v:
            items.append(("↵", "öffnen" if v.alive else ("fortsetzen" if v.st.get("has_conv") else "starten")))
        items.append(("n", "neu"))
        if v and v.alive:
            items.append(("s", "senden"))
        if v:
            items.append(("x", "stoppen" if v.alive else "entfernen"))
            items.append(("r", "umbenennen"))
        items += [("⇥", "Verlauf" if self.mode == "live" else "Live"), ("/", "Filter"),
                  ("?", "Hilfe"), ("q", "schließen")]
        self.hints(y, 1, items)

    # ---------- Aktionen
    def attach(self, meta):
        ccm.mark_seen(meta["id"])
        curses.def_prog_mode()
        curses.endwin()
        try:
            ccm.attach_tmux(ccm.TPREFIX + meta["id"])
        finally:
            ccm.mark_seen(meta["id"])
            curses.reset_prog_mode()
            try:
                curses.curs_set(0)
            except curses.error:
                pass
            curses.raw()
            self.scr.keypad(True)
            self.setup_mouse()
            self.scr.clear()
            self.refresh()

    def create(self, cwd, name, prompt, args, open_now):
        try:
            meta = ccm.create_session(cwd, name, prompt, args, cols=self.W, rows=self.H - 1)
        except ccm.CCMError as e:
            self.toast(str(e), "err", 5)
            return
        self.sel_id = meta["id"]
        self.refresh()
        if open_now:
            self.attach(meta)
        else:
            self.toast("▶ »%s« gestartet – arbeitet im Hintergrund" % meta["name"])

    def open_selected(self):
        v = self.selected()
        if not v:
            return
        if not v.alive:
            try:
                ccm.resume_session(v.meta, cols=self.W, rows=self.H - 1)
            except ccm.CCMError as e:
                self.toast(str(e), "err", 5)
                return
        self.attach(v.meta)

    def answer(self, k):
        v = self.selected()
        if not v or not v.alive:
            return
        if v.status in ("permission", "question", "plan"):
            try:
                ccm.tmux_send(v.tname, keys=[k])
                self.toast("→ Auswahl %s an »%s« gesendet" % (k, v.name))
            except ccm.CCMError as e:
                self.toast(str(e), "err")
            self.last_refresh = time.time() - 0.7
        elif v.status == "input":
            self.toast("Dialog offen – mit ↵ öffnen und dort antworten", "info")
        else:
            self.toast("»%s« wartet gerade auf keine Antwort" % v.name, "info")

    def send_dialog(self):
        v = self.selected()
        if not v:
            return
        if not v.alive:
            self.toast("»%s« läuft nicht – erst mit ↵ fortsetzen" % v.name, "info")
            return

        def submit(text):
            if not text.strip():
                return None
            try:
                ccm.tmux_send(v.tname, text=text, enter=True)
            except ccm.CCMError as e:
                return str(e)
            self.toast("→ an »%s« gesendet" % v.name)
            self.last_refresh = time.time() - 0.6
            return None
        self.modal = Prompt("Nachricht an »%s«" % v.name, "", "Text für Claude …", submit,
                            hint=[("↵", "senden"), ("esc", "abbrechen")], bottom=True)

    def rename_dialog(self):
        v = self.selected()
        if not v:
            return

        def submit(text):
            if not text.strip() or text.strip() == v.name:
                return None
            try:
                m = ccm.rename_session(v.meta, text)
            except ccm.CCMError as e:
                return str(e)
            self.toast("✓ umbenannt in »%s«" % m["name"])
            self.refresh()
            return None
        self.modal = Prompt("»%s« umbenennen" % v.name, v.name, "", submit,
                            hint=[("↵", "speichern"), ("esc", "abbrechen")])

    def kill_dialog(self):
        v = self.selected()
        if not v:
            return
        if not v.alive:
            return self.remove_dialog()

        def yes():
            ccm.kill_session(v.meta)
            self.toast("■ »%s« gestoppt – ↵ setzt sie später fort" % v.name)
            self.refresh()
        self.modal = Confirm("Session stoppen?", [
            "»%s« beenden?" % v.name,
            "Claude wird geschlossen. Mit ↵ machst du später",
            "genau dort weiter – der Verlauf bleibt erhalten.",
        ], yes, yes_label="stoppen")

    def remove_dialog(self):
        v = self.selected()
        if not v:
            return

        def yes():
            ccm.remove_session(v.meta)
            self.toast("✕ »%s« entfernt" % v.name)
            self.refresh()
        lines = ["»%s« aus ccm entfernen?" % v.name]
        if v.alive:
            lines.append("Die Session läuft noch und wird beendet.")
        lines.append("Die Unterhaltung selbst bleibt in Claude Code (claude --resume).")
        self.modal = Confirm("Session entfernen?", lines, yes, enter_ok=False, yes_label="entfernen")

    def fresh_dialog(self):
        v = self.selected()
        if not v:
            return
        if v.alive:
            self.toast("»%s« läuft noch – erst mit x stoppen" % v.name, "info")
            return

        def yes():
            try:
                ccm.resume_session(v.meta, fresh=True, cols=self.W, rows=self.H - 1)
            except ccm.CCMError as e:
                self.toast(str(e), "err", 5)
                return
            self.attach(v.meta)
        self.modal = Confirm("Frisch starten?", [
            "»%s« ohne bisherigen Verlauf neu starten?" % v.name,
            "Gleicher Ordner, neue leere Unterhaltung.",
        ], yes, yes_label="starten")

    def on_mouse(self):
        try:
            _, mx, my, _, b = curses.getmouse()
        except curses.error:
            return
        if b & getattr(curses, "BUTTON4_PRESSED", 0):
            self.move(-1)
        elif b & getattr(curses, "BUTTON5_PRESSED", 0):
            self.move(1)
        elif b & (curses.BUTTON1_PRESSED | curses.BUTTON1_CLICKED):
            vid = self.row_ids.get(my)
            if vid:
                if vid == self.sel_id:
                    self.open_selected()
                else:
                    self.sel_id = vid
                    self.last_idx = self.sel_index(self.visible())
            elif my == self.tab_y and mx > self.W - 20:
                self.mode = "log" if self.mode == "live" else "live"

    def on_key(self, k):
        if k == curses.KEY_RESIZE:
            self.scr.clear()
            return
        if self.modal:
            self.modal.key(self, k)
            return
        if k == curses.KEY_MOUSE:
            self.on_mouse()
            return
        if self.filtering:
            if k == "\x1b":
                self.filter.set("")
                self.filtering = False
            elif k in ENTER:
                self.filtering = False
            elif k == curses.KEY_UP:
                self.move(-1)
            elif k == curses.KEY_DOWN:
                self.move(1)
            else:
                self.filter.key(k)
                vis = self.visible()
                if vis and not any(v.id == self.sel_id for v in vis):
                    self.sel_id = vis[0].id
            return
        if k in ("q", "\x03"):
            self.quit = True
        elif k == "\x1b":
            if self.filter.text:
                self.filter.set("")
        elif k in (curses.KEY_UP, "k"):
            self.move(-1)
        elif k in (curses.KEY_DOWN, "j"):
            self.move(1)
        elif k == curses.KEY_PPAGE:
            self.move(-5)
        elif k == curses.KEY_NPAGE:
            self.move(5)
        elif k in (curses.KEY_HOME, "g"):
            self.move(-10 ** 6)
        elif k in (curses.KEY_END, "G"):
            self.move(10 ** 6)
        elif k in ENTER:
            self.open_selected()
        elif k == "n":
            self.modal = NewSession(self)
        elif k in ("s", "i"):
            self.send_dialog()
        elif k == "r":
            self.rename_dialog()
        elif k in ("x", curses.KEY_DC):
            self.kill_dialog()
        elif k == "X":
            self.remove_dialog()
        elif k == "F":
            self.fresh_dialog()
        elif k in ("\t", curses.KEY_BTAB):
            self.mode = "log" if self.mode == "live" else "live"
        elif k == "v":
            self.show_preview = not self.show_preview
        elif k == "o":
            self.sort_activity = not self.sort_activity
            self.toast("Sortierung: " + ("letzte Aktivität" if self.sort_activity else "erstellt"), "info", 1.5)
        elif k == "/":
            self.filtering = True
        elif k == "?":
            self.modal = Help()
        elif k == "\x0c":
            self.scr.clear()
        elif isinstance(k, str) and k in "123456789":
            self.answer(k)

    def loop(self):
        self.refresh()
        note = ccm.pop_update_notice()
        if note:
            self.toast("✓ " + note, "ok", 5)
        while not self.quit:
            if time.time() - self.last_refresh >= 1.0:
                self.refresh()
            self.draw()
            anim = (any(v.status in ccm.BUSY or v.status in ccm.ATTN for v in self.views)
                    or time.time() < self.toast_until)
            self.scr.timeout(100 if anim else 400)
            try:
                k = self.scr.get_wch()
            except curses.error:
                continue
            except KeyboardInterrupt:
                break
            self.on_key(k)
        return 0


def run():
    os.environ.setdefault("ESCDELAY", "25")
    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        pass
    return curses.wrapper(lambda scr: UI(scr).loop())
