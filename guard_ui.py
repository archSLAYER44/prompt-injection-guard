"""HTML pieces shared by dashboard.py and chat_app.py: palette, badges, chips, tiles, the chat transcript.

Pure string builders (no Streamlit calls), so both pages draw the same chips, badges and chat bubbles. The look
follows design/stitch/ (dense telemetry panels, 4 px radii, monospace numbers, status badges that pair an icon
with a label); the colours are the project's own palette.
"""
import html

import guard_core

BG, PANEL, PANEL2, BORDER, BORDER2, TEXT, MUTED = "#111217", "#181b1f", "#20242a", "#2c3235", "#3b4247", "#d8d9da", "#9fa3aa"
GREEN, RED, YELLOW, BLUE = "#73BF69", "#F2495C", "#FADE2A", "#5794F2"
MONO = "ui-monospace, 'JetBrains Mono', 'SFMono-Regular', Menlo, Consolas, monospace"
ICONS = {"green": "✓", "red": "⊘", "yellow": "⚠", "blue": "●", "gray": "·"}

BASE_CSS = f"""
[data-testid="stDecoration"], .stAppDeployButton {{display: none;}}
header[data-testid="stHeader"] {{background: transparent; height: 0;}}
[data-testid="stVerticalBlockBorderWrapper"] {{background: {PANEL}; border-color: {BORDER} !important; border-radius: 4px;}}
.topbar {{display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 10px; min-height: 48px; background: {PANEL}; border: 1px solid {BORDER}; border-radius: 4px; padding: 4px 14px; margin-bottom: 6px;}}
.topbar .brand {{display: flex; align-items: center; gap: 10px; font-weight: 700; font-size: 1.05rem; color: {TEXT};}}
.profile {{display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 10px; background: {BG}; border: 1px solid {BORDER}; border-radius: 4px; padding: 5px 14px; margin-bottom: 12px; font-family: {MONO}; font-size: .76rem; color: {MUTED};}}
.profile b {{color: {TEXT}; font-weight: 500;}}
.chips {{display: flex; flex-wrap: wrap; gap: 6px;}}
.chip {{display: inline-flex; align-items: center; gap: 6px; padding: 3px 8px; border-radius: 4px; border: 1px solid {BORDER}; background: {BG}; font-family: {MONO}; font-size: .72rem; font-weight: 500; color: {TEXT}; white-space: nowrap;}}
.chip .dot {{width: 7px; height: 7px; border-radius: 50%;}}
.ptitle {{display: flex; align-items: baseline; justify-content: space-between; gap: 10px; margin: 0 0 6px;}}
.ptitle .t {{font-size: .82rem; font-weight: 500; color: {MUTED};}}
.ptitle .r {{font-family: {MONO}; font-size: .72rem; color: {MUTED};}}
.psub {{font-size: .78rem; color: {MUTED}; margin: -4px 0 8px;}}
.tiles {{display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; margin: 2px 0 12px;}}
.tile {{position: relative; background: {PANEL}; border: 1px solid {BORDER}; border-left: 3px solid {BLUE}; border-radius: 4px; padding: 12px 14px; min-width: 0;}}
.tile .label {{font-size: .72rem; color: {MUTED}; font-weight: 500;}}
.tile .value {{font-family: {MONO}; font-size: 1.45rem; font-weight: 600; color: {TEXT}; margin-top: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; letter-spacing: -.02em;}}
.tile .sub {{font-size: .76rem; color: {MUTED}; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;}}
.tile .ico {{position: absolute; top: 10px; right: 12px; font-size: 1rem; opacity: .8;}}
.badge {{display: inline-flex; align-items: center; gap: 4px; padding: 2px 7px; border-radius: 4px; font-family: {MONO}; font-size: .7rem; font-weight: 600; letter-spacing: .03em; text-transform: uppercase; white-space: nowrap; border: 1px solid transparent;}}
.badge.green {{background: rgba(115,191,105,.12); color: {GREEN}; border-color: rgba(115,191,105,.35);}}
.badge.red {{background: rgba(242,73,92,.12); color: {RED}; border-color: rgba(242,73,92,.35);}}
.badge.yellow {{background: rgba(250,222,42,.12); color: {YELLOW}; border-color: rgba(250,222,42,.35);}}
.badge.blue {{background: rgba(87,148,242,.12); color: {BLUE}; border-color: rgba(87,148,242,.35);}}
.badge.gray {{background: {PANEL2}; color: {MUTED}; border-color: {BORDER};}}
.mono {{font-family: {MONO};}}
.muted {{color: {MUTED}; font-size: .8rem;}}
.kv {{font-family: {MONO}; font-size: .78rem; display: grid; grid-template-columns: 170px 1fr; gap: 4px 10px;}}
.kv .k {{color: {MUTED};}} .kv .v {{color: {TEXT}; word-break: break-all;}}
.legend {{display: flex; flex-direction: column; gap: 6px; font-family: {MONO}; font-size: .78rem; color: {TEXT};}}
.legend div {{display: flex; justify-content: space-between; align-items: center; gap: 8px; white-space: nowrap;}}
.tile.small .value {{font-size: .95rem; letter-spacing: 0;}}
.chat {{display: flex; flex-direction: column; gap: 10px;}}
.msg {{max-width: 86%; border-radius: 6px; padding: 10px 12px; border: 1px solid {BORDER};}}
.msg .meta {{font-family: {MONO}; font-size: .7rem; color: {MUTED}; margin-bottom: 4px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap;}}
.msg .body {{font-size: .93rem; color: {TEXT}; white-space: pre-wrap; word-break: break-word;}}
.msg .doc {{font-family: {MONO}; font-size: .72rem; color: {MUTED}; margin-top: 6px; border-top: 1px dashed {BORDER}; padding-top: 4px;}}
.msg.user {{align-self: flex-end; background: rgba(87,148,242,.10); border-color: rgba(87,148,242,.35);}}
.msg.bot {{align-self: flex-start; background: {PANEL};}}
.msg.blocked {{align-self: flex-start; background: rgba(242,73,92,.08); border-color: rgba(242,73,92,.5); max-width: 100%;}}
.msg.blocked .head {{display: flex; gap: 10px; align-items: center; flex-wrap: wrap; font-family: {MONO}; font-size: .74rem; color: {TEXT};}}
.msg.blocked .foot {{font-family: {MONO}; font-size: .7rem; color: {MUTED}; margin-top: 6px;}}
.msg.err {{align-self: flex-start; background: rgba(250,222,42,.07); border-color: rgba(250,222,42,.4);}}
"""


def esc(value):
    return html.escape(str(value))


def badge(text, colour="gray", icon=None):
    icon = ICONS.get(colour, "") if icon is None else icon
    return f'<span class="badge {colour}">{esc(icon)} {esc(text)}</span>' if icon else f'<span class="badge {colour}">{esc(text)}</span>'


def chip(text, colour):
    return f'<span class="chip"><span class="dot" style="background:{colour}"></span>{esc(text)}</span>'


def tiles_html(items):
    """items: (label, value, sub, colour[, icon])."""
    cells = []
    for item in items:
        label, value, sub, colour = item[:4]
        icon = item[4] if len(item) > 4 else ""
        small = " small" if len(str(value)) > 12 else ""
        cells.append(f'<div class="tile{small}" style="border-left-color:{colour}"><div class="label">{esc(label)}</div>'
                     f'<div class="value">{esc(value)}</div><div class="sub">{esc(sub)}</div>'
                     + (f'<div class="ico" style="color:{colour}">{esc(icon)}</div>' if icon else "") + "</div>")
    return f'<div class="tiles">{"".join(cells)}</div>'


def transcript_html(rows, limit=None, show_scores=True):
    """The conversation as right/left bubbles, blocked turns as the red card. Rows are history_row() dicts."""
    parts = []
    for h in (rows[-limit:] if limit else rows):
        verdict = badge("blocked", "red") if h["blocked"] == "yes" else (badge("flagged", "yellow") if h["verdict"] == "injection" else badge("allowed", "green"))
        meta = f'You · {esc(h["time"])} · {verdict}' + (f' · <span class="mono">score {h["score"]:+.2f}</span>' if show_scores else "")
        parts.append(f'<div class="msg user"><div class="meta">{meta}</div><div class="body">{esc(h["_message"])}</div>'
                     + (f'<div class="doc">📎 retrieved document · {esc(h["_document"][:140])}{"…" if len(h["_document"]) > 140 else ""}</div>' if h.get("_document") else "")
                     + "</div>")
        if h["blocked"] == "yes":
            rule = f' · rule: {esc(h["top_rule"])}' if h.get("top_rule") else " · no rule fired: the embedding alone"
            parts.append(f'<div class="msg blocked"><div class="head">{badge("blocked by guard", "red")} '
                         f'<span>score <b>{h["score"]:+.2f}</b> (threshold {h.get("threshold", 0):.3f}){rule} · {", ".join(h.get("flagged") or []).lower()} flagged</span></div>'
                         f'<div class="body">{esc(guard_core.BLOCKED_REPLY)}</div>'
                         f'<div class="foot">the model was not called · nothing left the guard · detector {h.get("scan_ms", 0):.0f} ms</div></div>')
        elif h.get("_error"):
            parts.append(f'<div class="msg err"><div class="meta">Assistant · {badge("model error", "yellow")}</div><div class="body">{esc(h["_error"])}</div></div>')
        else:
            leak = badge("secret leaked", "red") if h["reply contains secret"] == "yes" else badge("no secret in the reply", "green")
            meta = f'Assistant · {esc(h["provider"])} · <span class="mono">{h.get("elapsed", 0):.1f} s</span>' + (f" · {leak}" if show_scores else "")
            parts.append(f'<div class="msg bot"><div class="meta">{meta}</div><div class="body">{esc(h["_reply"] or "")}</div></div>')
    return '<div class="chat">' + "".join(parts) + "</div>"
