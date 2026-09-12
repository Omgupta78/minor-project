"""Generate a self-contained stylesheet for the classes this app actually uses.

The app was built against the Tailwind CDN, which means it renders unstyled the
moment the machine has no internet -- exactly what happens in a college lab or
while presenting. This script scans the templates, collects every utility class
that appears (including ones built inside JavaScript strings), and emits plain
CSS for just those. No network, no build toolchain, no node_modules.

Run:  python3 build_css.py
Out:  static/app.css
"""
from pathlib import Path
import re

ROOT = Path(__file__).parent
TEMPLATES = ROOT / "templates"
OUT = ROOT / "static" / "app.css"

# ---------------------------------------------------------------- palette
THEME = {
    "primary": "#1565C0",
    "primary-light": "#E3F0FF",
    "surface": "#FFFFFF",
    "surface-el": "#F0F4F8",
    "bg": "#F8FAFB",
    "bdr": "#E0E7EF",
    "success": "#16A34A",
    "success-light": "#E8F5EC",
    "warn": "#D97706",
    "warn-light": "#FEF3C7",
    "danger": "#DC2626",
    "danger-light": "#FEE2E2",
    "txt": "#0F172A",
    "txt-m": "#475569",
    "txt-f": "#94A3B8",
    # stock Tailwind shades referenced by the templates
    "white": "#FFFFFF",
    "black": "#000000",
    "transparent": "transparent",
    "current": "currentColor",
    "slate-50": "#F8FAFC",
    "slate-100": "#F1F5F9",
    "slate-200": "#E2E8F0",
    "slate-400": "#94A3B8",
    "slate-500": "#64748B",
    "slate-600": "#475569",
    "slate-700": "#334155",
    "slate-800": "#1E293B",
    "slate-900": "#0F172A",
    "gray-50": "#F9FAFB",
    "gray-100": "#F3F4F6",
    "gray-200": "#E5E7EB",
    "gray-400": "#9CA3AF",
    "gray-500": "#6B7280",
    "gray-600": "#4B5563",
    "green-50": "#F0FDF4",
    "green-100": "#DCFCE7",
    "green-600": "#16A34A",
    "green-700": "#15803D",
    "green-800": "#166534",
    "blue-50": "#EFF6FF",
    "blue-600": "#2563EB",
    "blue-700": "#1D4ED8",
    "blue-800": "#1E40AF",
    "red-50": "#FEF2F2",
    "red-100": "#FEE2E2",
    "red-500": "#EF4444",
    "red-600": "#DC2626",
    "red-700": "#B91C1C",
    "red-800": "#991B1B",
    "amber-50": "#FFFBEB",
    "amber-500": "#F59E0B",
    "amber-600": "#D97706",
    "amber-700": "#B45309",
    "amber-800": "#92400E",
    "yellow-50": "#FEFCE8",
    "orange-500": "#F97316",
    "purple-500": "#A855F7",
    "indigo-500": "#6366F1",
}

FONT_SIZE = {
    "xs": ("0.75rem", "1rem"),
    "sm": ("0.875rem", "1.25rem"),
    "base": ("1rem", "1.5rem"),
    "lg": ("1.125rem", "1.75rem"),
    "xl": ("1.25rem", "1.75rem"),
    "2xl": ("1.5rem", "2rem"),
    "3xl": ("1.875rem", "2.25rem"),
    "4xl": ("2.25rem", "2.5rem"),
}

FONT_WEIGHT = {
    "thin": 100, "light": 300, "normal": 400, "medium": 500,
    "semibold": 600, "bold": 700, "extrabold": 800, "black": 900,
}

RADIUS = {
    "none": "0", "sm": "0.125rem", "": "0.25rem", "md": "0.375rem",
    "lg": "0.5rem", "xl": "0.75rem", "2xl": "1rem", "3xl": "1.5rem",
    "full": "9999px",
}

SHADOW = {
    "sm": "0 1px 2px 0 rgba(15,23,42,.05)",
    "": "0 1px 3px 0 rgba(15,23,42,.1), 0 1px 2px -1px rgba(15,23,42,.1)",
    "md": "0 4px 6px -1px rgba(15,23,42,.1), 0 2px 4px -2px rgba(15,23,42,.1)",
    "lg": "0 10px 15px -3px rgba(15,23,42,.1), 0 4px 6px -4px rgba(15,23,42,.1)",
    "xl": "0 20px 25px -5px rgba(15,23,42,.1), 0 8px 10px -6px rgba(15,23,42,.1)",
    "2xl": "0 25px 50px -12px rgba(15,23,42,.25)",
    "inner": "inset 0 2px 4px 0 rgba(15,23,42,.05)",
    "none": "none",
}

MAX_W = {
    "xs": "20rem", "sm": "24rem", "md": "28rem", "lg": "32rem", "xl": "36rem",
    "2xl": "42rem", "3xl": "48rem", "4xl": "56rem", "5xl": "64rem",
    "6xl": "72rem", "7xl": "80rem", "full": "100%", "none": "none",
}

BREAKPOINTS = {"sm": "640px", "md": "768px", "lg": "1024px", "xl": "1280px"}
STATES = {
    "hover": ":hover", "focus": ":focus", "active": ":active",
    "disabled": ":disabled", "last": ":last-child", "first": ":first-child",
    "odd": ":nth-child(odd)", "even": ":nth-child(even)",
    "focus-within": ":focus-within", "checked": ":checked",
}


def spacing(token):
    """Tailwind's 0.25rem scale, plus the handful of special keywords."""
    fixed = {"px": "1px", "auto": "auto", "full": "100%", "screen": "100vh"}
    if token in fixed:
        return fixed[token]
    if re.fullmatch(r"\d+(\.5)?", token):
        return f"{float(token) * 0.25:g}rem"
    if "/" in token:
        a, b = token.split("/", 1)
        if a.isdigit() and b.isdigit():
            return f"{float(a) / float(b) * 100:g}%"
    return None


def arbitrary(token):
    """text-[10px] / w-[84px] / top-[2px] -> the bracketed value."""
    m = re.fullmatch(r"\[(.+)\]", token)
    return m.group(1).replace("_", " ") if m else None


def color(token):
    """Resolve a colour name, honouring the /opacity suffix."""
    val = arbitrary(token)
    if val:
        return val
    alpha = None
    if "/" in token:
        token, _, pct = token.rpartition("/")
        if not pct.isdigit():
            return None
        alpha = int(pct) / 100
    hexval = THEME.get(token)
    if hexval is None:
        return None
    if alpha is None:
        return hexval
    if not hexval.startswith("#"):
        return hexval
    r, g, b = (int(hexval[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r},{g},{b},{alpha:g})"


# ---------------------------------------------------------------- rules
STATIC = {
    "block": "display:block", "inline-block": "display:inline-block",
    "inline": "display:inline", "flex": "display:flex",
    "inline-flex": "display:inline-flex", "grid": "display:grid",
    "hidden": "display:none", "table": "display:table",
    "flex-row": "flex-direction:row", "flex-col": "flex-direction:column",
    "flex-wrap": "flex-wrap:wrap", "flex-nowrap": "flex-wrap:nowrap",
    "flex-1": "flex:1 1 0%", "flex-auto": "flex:1 1 auto",
    "flex-none": "flex:none", "flex-shrink-0": "flex-shrink:0",
    "shrink-0": "flex-shrink:0", "flex-grow": "flex-grow:1",
    "items-start": "align-items:flex-start", "items-center": "align-items:center",
    "items-end": "align-items:flex-end", "items-stretch": "align-items:stretch",
    "items-baseline": "align-items:baseline",
    "justify-start": "justify-content:flex-start",
    "justify-center": "justify-content:center",
    "justify-end": "justify-content:flex-end",
    "justify-between": "justify-content:space-between",
    "justify-around": "justify-content:space-around",
    "self-start": "align-self:flex-start", "self-center": "align-self:center",
    "static": "position:static", "relative": "position:relative",
    "absolute": "position:absolute", "fixed": "position:fixed",
    "sticky": "position:sticky",
    "inset-0": "top:0;right:0;bottom:0;left:0",
    "inset-x-0": "left:0;right:0", "inset-y-0": "top:0;bottom:0",
    "overflow-hidden": "overflow:hidden", "overflow-auto": "overflow:auto",
    "overflow-x-auto": "overflow-x:auto", "overflow-y-auto": "overflow-y:auto",
    "overflow-visible": "overflow:visible",
    "text-left": "text-align:left", "text-center": "text-align:center",
    "text-right": "text-align:right",
    "uppercase": "text-transform:uppercase",
    "lowercase": "text-transform:lowercase",
    "capitalize": "text-transform:capitalize",
    "italic": "font-style:italic",
    "underline": "text-decoration-line:underline",
    "no-underline": "text-decoration-line:none",
    "line-through": "text-decoration-line:line-through",
    "truncate": "overflow:hidden;text-overflow:ellipsis;white-space:nowrap",
    "whitespace-nowrap": "white-space:nowrap",
    "whitespace-pre-line": "white-space:pre-line",
    "break-words": "overflow-wrap:break-word",
    "font-sans": "font-family:'IBM Plex Sans',ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif",
    "font-mono": "font-family:'IBM Plex Mono',ui-monospace,'SFMono-Regular',Menlo,Consolas,'Liberation Mono',monospace",
    "antialiased": "-webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale",
    "cursor-pointer": "cursor:pointer", "cursor-default": "cursor:default",
    "cursor-not-allowed": "cursor:not-allowed",
    "pointer-events-none": "pointer-events:none",
    "pointer-events-auto": "pointer-events:auto",
    "select-none": "user-select:none",
    "resize-none": "resize:none",
    "appearance-none": "appearance:none;-webkit-appearance:none",
    "object-cover": "object-fit:cover", "object-contain": "object-fit:contain",
    "aspect-video": "aspect-ratio:16/9", "aspect-square": "aspect-ratio:1/1",
    "mx-auto": "margin-left:auto;margin-right:auto",
    "ml-auto": "margin-left:auto", "mr-auto": "margin-right:auto",
    "min-w-0": "min-width:0", "min-h-screen": "min-height:100vh",
    "min-h-0": "min-height:0",
    "w-full": "width:100%", "h-full": "height:100%",
    "w-screen": "width:100vw", "h-screen": "height:100vh",
    "w-auto": "width:auto", "h-auto": "height:auto",
    "w-fit": "width:fit-content",
    "transition-colors": "transition-property:color,background-color,border-color,fill,stroke;transition-duration:150ms;transition-timing-function:cubic-bezier(.4,0,.2,1)",
    "transition-all": "transition-property:all;transition-duration:150ms;transition-timing-function:cubic-bezier(.4,0,.2,1)",
    "transition-opacity": "transition-property:opacity;transition-duration:150ms;transition-timing-function:cubic-bezier(.4,0,.2,1)",
    "transition-transform": "transition-property:transform;transition-duration:150ms;transition-timing-function:cubic-bezier(.4,0,.2,1)",
    "transition": "transition-property:color,background-color,border-color,opacity,box-shadow,transform;transition-duration:150ms;transition-timing-function:cubic-bezier(.4,0,.2,1)",
    "backdrop-blur-sm": "backdrop-filter:blur(4px);-webkit-backdrop-filter:blur(4px)",
    "animate-pulse": "animation:tw-pulse 2s cubic-bezier(.4,0,.6,1) infinite",
    "animate-spin": "animation:tw-spin 1s linear infinite",
    "sr-only": "position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border-width:0",
    "border": "border-width:1px;border-style:solid",
    "border-0": "border-width:0",
    "border-2": "border-width:2px;border-style:solid",
    "border-4": "border-width:4px;border-style:solid",
    "border-t": "border-top-width:1px;border-top-style:solid",
    "border-b": "border-bottom-width:1px;border-bottom-style:solid",
    "border-l": "border-left-width:1px;border-left-style:solid",
    "border-r": "border-right-width:1px;border-right-style:solid",
    "border-b-0": "border-bottom-width:0",
    "border-t-0": "border-top-width:0",
    "border-b-2": "border-bottom-width:2px;border-bottom-style:solid",
    "border-t-2": "border-top-width:2px;border-top-style:solid",
    "border-l-4": "border-left-width:4px;border-left-style:solid",
    "border-dashed": "border-style:dashed",
    "border-solid": "border-style:solid",
    "border-collapse": "border-collapse:collapse",
    "align-middle": "vertical-align:middle",
    "align-top": "vertical-align:top",
    "leading-none": "line-height:1",
    "leading-tight": "line-height:1.25",
    "leading-snug": "line-height:1.375",
    "leading-normal": "line-height:1.5",
    "leading-relaxed": "line-height:1.625",
    "tracking-tight": "letter-spacing:-0.025em",
    "tracking-normal": "letter-spacing:0",
    "tracking-wide": "letter-spacing:0.025em",
    "tracking-wider": "letter-spacing:0.05em",
    "tracking-widest": "letter-spacing:0.1em",
    "table-fixed": "table-layout:fixed",
}

SIDES = {
    "p": ["padding"], "pt": ["padding-top"], "pb": ["padding-bottom"],
    "pl": ["padding-left"], "pr": ["padding-right"],
    "px": ["padding-left", "padding-right"],
    "py": ["padding-top", "padding-bottom"],
    "m": ["margin"], "mt": ["margin-top"], "mb": ["margin-bottom"],
    "ml": ["margin-left"], "mr": ["margin-right"],
    "mx": ["margin-left", "margin-right"],
    "my": ["margin-top", "margin-bottom"],
}

POS_SIDES = {"top": "top", "bottom": "bottom", "left": "left", "right": "right"}
Z_INDEX = {"0", "10", "20", "30", "40", "50", "auto"}


def declarations(cls):
    """Return the CSS body for one utility class, or None if unrecognised."""
    if cls in STATIC:
        return STATIC[cls]

    # gap / grid
    for prefix, prop in (("gap-x-", "column-gap"), ("gap-y-", "row-gap"), ("gap-", "gap")):
        if cls.startswith(prefix):
            v = arbitrary(cls[len(prefix):]) or spacing(cls[len(prefix):])
            if v:
                return f"{prop}:{v}"
    if cls.startswith("grid-cols-"):
        n = cls[len("grid-cols-"):]
        if n.isdigit():
            return f"grid-template-columns:repeat({n},minmax(0,1fr))"
        if n == "none":
            return "grid-template-columns:none"
    if cls.startswith("col-span-"):
        n = cls[len("col-span-"):]
        if n.isdigit():
            return f"grid-column:span {n}/span {n}"
        if n == "full":
            return "grid-column:1/-1"

    # padding / margin
    m = re.fullmatch(r"(-?)(p|py|px|pt|pb|pl|pr|m|my|mx|mt|mb|ml|mr)-(.+)", cls)
    if m:
        neg, key, rest = m.groups()
        v = arbitrary(rest) or spacing(rest)
        if v:
            if neg and not v.startswith("-"):
                v = "-" + v
            return ";".join(f"{p}:{v}" for p in SIDES[key])

    # sizing
    for prefix, prop in (("min-w-", "min-width"), ("min-h-", "min-height"),
                         ("max-h-", "max-height"), ("w-", "width"), ("h-", "height")):
        if cls.startswith(prefix):
            rest = cls[len(prefix):]
            v = arbitrary(rest) or spacing(rest)
            if v:
                return f"{prop}:{v}"
    if cls.startswith("max-w-"):
        rest = cls[len("max-w-"):]
        v = MAX_W.get(rest) or arbitrary(rest) or spacing(rest)
        if v:
            return f"max-width:{v}"

    # position offsets
    m = re.fullmatch(r"(top|bottom|left|right)-(.+)", cls)
    if m:
        side, rest = m.groups()
        v = arbitrary(rest) or spacing(rest)
        if v:
            return f"{POS_SIDES[side]}:{v}"

    if cls.startswith("z-"):
        rest = cls[2:]
        v = arbitrary(rest)
        if v or rest in Z_INDEX:
            return f"z-index:{v or rest}"

    # typography
    if cls.startswith("text-"):
        rest = cls[len("text-"):]
        if rest in FONT_SIZE:
            size, lh = FONT_SIZE[rest]
            return f"font-size:{size};line-height:{lh}"
        v = arbitrary(rest)
        if v and re.fullmatch(r"[\d.]+(px|rem|em|pt)", v):
            return f"font-size:{v};line-height:1.35"
        c = color(rest)
        if c:
            return f"color:{c}"
    if cls.startswith("font-"):
        rest = cls[len("font-"):]
        if rest in FONT_WEIGHT:
            return f"font-weight:{FONT_WEIGHT[rest]}"
    if cls.startswith("leading-"):
        v = arbitrary(cls[len("leading-"):])
        if v:
            return f"line-height:{v}"

    # colours
    if cls.startswith("bg-"):
        c = color(cls[len("bg-"):])
        if c:
            return f"background-color:{c}"
    if cls.startswith("border-"):
        c = color(cls[len("border-"):])
        if c:
            return f"border-color:{c}"
    if cls.startswith("ring-"):
        c = color(cls[len("ring-"):])
        if c:
            return f"box-shadow:0 0 0 2px {c};outline:none"
    if cls.startswith("fill-"):
        c = color(cls[len("fill-"):])
        if c:
            return f"fill:{c}"

    # radius
    if cls == "rounded":
        return f"border-radius:{RADIUS['']}"
    if cls.startswith("rounded-"):
        rest = cls[len("rounded-"):]
        if rest in RADIUS:
            return f"border-radius:{RADIUS[rest]}"
        v = arbitrary(rest)
        if v:
            return f"border-radius:{v}"
        m = re.fullmatch(r"(t|b|l|r|tl|tr|bl|br)-(.+)", rest)
        if m and m.group(2) in RADIUS:
            corner, size = m.group(1), RADIUS[m.group(2)]
            corners = {
                "t": ["top-left", "top-right"], "b": ["bottom-left", "bottom-right"],
                "l": ["top-left", "bottom-left"], "r": ["top-right", "bottom-right"],
                "tl": ["top-left"], "tr": ["top-right"],
                "bl": ["bottom-left"], "br": ["bottom-right"],
            }[corner]
            return ";".join(f"border-{c}-radius:{size}" for c in corners)

    # shadow / opacity
    if cls == "shadow":
        return f"box-shadow:{SHADOW['']}"
    if cls.startswith("shadow-"):
        rest = cls[len("shadow-"):]
        if rest in SHADOW:
            return f"box-shadow:{SHADOW[rest]}"
    if cls.startswith("opacity-"):
        rest = cls[len("opacity-"):]
        if rest.isdigit():
            return f"opacity:{int(rest) / 100:g}"

    return None


def escape(selector):
    """Escape the characters Tailwind-style class names put in CSS selectors."""
    return re.sub(r"([:./\[\]#%()+,'\"!])", r"\\\1", selector)


def main():
    files = sorted(TEMPLATES.glob("*.html"))
    if not files:
        raise SystemExit("no templates found")

    text = "\n".join(f.read_text(encoding="utf-8") for f in files)
    # Grab every candidate token anywhere in the file. Classes are built inside
    # JS strings and Jinja ternaries too, so scanning the whole text and then
    # ignoring anything we don't recognise is safer than parsing class="...".
    tokens = set(re.findall(r"[A-Za-z][A-Za-z0-9:_./\[\]#%-]*", text))

    base, responsive, unknown = {}, {bp: {} for bp in BREAKPOINTS}, set()

    for token in sorted(tokens):
        variants, _, name = token.rpartition(":")
        parts = [p for p in variants.split(":") if p] if variants else []
        if any(p not in BREAKPOINTS and p not in STATES for p in parts):
            continue
        body = declarations(name)
        if not body:
            if parts:
                unknown.add(token)
            continue

        pseudo = "".join(STATES[p] for p in parts if p in STATES)
        screens = [p for p in parts if p in BREAKPOINTS]
        selector = f".{escape(token)}{pseudo}"
        rule = f"{selector} {{ {body}; }}"
        if screens:
            responsive[screens[-1]][token] = rule
        else:
            base[token] = rule

    out = [HEADER]
    out.append("/* ---- utilities ---- */")
    out.extend(base[k] for k in sorted(base))
    for bp, px in BREAKPOINTS.items():
        rules = responsive[bp]
        if rules:
            out.append(f"\n@media (min-width: {px}) {{")
            out.extend("  " + rules[k] for k in sorted(rules))
            out.append("}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(out) + "\n", encoding="utf-8")

    print(f"scanned   {len(files)} templates, {len(tokens)} candidate tokens")
    print(f"generated {len(base)} base rules + "
          f"{sum(len(v) for v in responsive.values())} responsive rules")
    print(f"wrote     {OUT.relative_to(ROOT)}  ({OUT.stat().st_size} bytes)")
    if unknown:
        # Only variant-prefixed misses are reported: a bare miss is almost
        # always an ordinary English word, not a utility class.
        print("\nUNRECOGNISED variant classes (would render unstyled):")
        for u in sorted(unknown):
            print("   ", u)


HEADER = """/* FaceID Attendance -- offline stylesheet
 * Generated by build_css.py from the classes used in templates/.
 * Do not edit by hand: run `python3 build_css.py` after changing templates.
 * This file exists so the app renders correctly with no internet connection.
 */

*,*::before,*::after { box-sizing:border-box; border-width:0; border-style:solid; border-color:#E0E7EF; }
* { margin:0; }
html { -webkit-text-size-adjust:100%; line-height:1.5; }
body {
  font-family:'IBM Plex Sans',ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;
  background:#F8FAFB; color:#0F172A; line-height:1.5;
}
h1,h2,h3,h4,h5,h6 { font-size:inherit; font-weight:inherit; }
a { color:inherit; text-decoration:none; }
img,svg,video,canvas { display:block; max-width:100%; }
button,input,select,textarea { font:inherit; color:inherit; margin:0; }
button { background:none; cursor:pointer; }
button:disabled { cursor:not-allowed; }
table { border-collapse:collapse; }
hr { border-top-width:1px; }

/* form controls -- stands in for the Tailwind forms plugin */
input[type=text],input[type=date],input[type=number],input[type=search],
input[type=email],input[type=password],input[type=file],select,textarea {
  appearance:none; -webkit-appearance:none;
  background-color:#fff; border-width:1px; border-color:#E0E7EF;
  border-radius:0; padding:.5rem .75rem; font-size:1rem; line-height:1.5rem;
}
input:focus,select:focus,textarea:focus { outline:2px solid transparent; outline-offset:2px; border-color:#1565C0; box-shadow:0 0 0 1px #1565C0; }
input[type=file] { border:none; padding:0; }
input[type=checkbox] { appearance:auto; -webkit-appearance:auto; width:1rem; height:1rem; accent-color:#1565C0; }
select {
  background-image:url("data:image/svg+xml,%3csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 20 20'%3e%3cpath stroke='%236B7280' stroke-linecap='round' stroke-linejoin='round' stroke-width='1.5' d='M6 8l4 4 4-4'/%3e%3c/svg%3e");
  background-position:right .5rem center; background-repeat:no-repeat;
  background-size:1.5em 1.5em; padding-right:2.5rem;
}
::placeholder { color:#94A3B8; opacity:1; }

@keyframes tw-pulse { 50% { opacity:.5; } }
@keyframes tw-spin { to { transform:rotate(360deg); } }
"""


if __name__ == "__main__":
    main()
