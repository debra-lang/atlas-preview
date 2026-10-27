"""Patient-guide illustrations and icons ("a quiet horizon"), used by tools/build_seo.py.
Small layered SVG scenes and a 24px line-icon set. Everything is coloured by CSS variables in css/guides.css, so it follows the
site's dark/light theme; all of it is decorative (aria-hidden) and the text beside it carries the meaning. Deterministic output:
random elements (stars) use fixed seeds, so rebuilds are byte-identical."""
import math, random

ICONS = {
  # homepage choices / guides
  "sprout":   '<path d="M12 20v-7"/><path d="M12 13c-4.2 0-6.5-2.6-6.5-6.5 3.9 0 6.5 2.3 6.5 6.5z"/><path d="M12 11c0-3.9 2.5-6.5 6.5-6.5 0 3.9-2.6 6.5-6.5 6.5z"/><path d="M7.5 20h9"/>',
  "moon":     '<path d="M19.5 14.6A7.8 7.8 0 1 1 9.4 4.5a6.3 6.3 0 0 0 10.1 10.1z"/><path d="M17 3.5v2.6M15.7 4.8h2.6"/>',
  "heart":    '<path d="M12 20s-7.5-4.5-7.5-10.2A4.1 4.1 0 0 1 12 7.4a4.1 4.1 0 0 1 7.5 2.4C19.5 15.5 12 20 12 20z"/><path d="M8 12.2h2l1.1-1.8 1.7 3.2 1.1-1.4H16"/>',
  "focus":    '<circle cx="12" cy="12" r="5.2"/><circle cx="12" cy="12" r="1.3" fill="currentColor" stroke="none"/><path d="M12 3.5v2.3M12 18.2v2.3M3.5 12h2.3M18.2 12h2.3"/>',
  "clipboard":'<rect x="5.5" y="5" width="13" height="15.5" rx="2.2"/><path d="M9.2 5V3.8h5.6V5"/><path d="M9 10.2h6M9 13.6h6M9 17h3.6"/>',
  "research": '<path d="M5 19.5v-5.5M9 19.5v-9M13 19.5v-3.5"/><circle cx="16.2" cy="8.2" r="3.4"/><path d="M18.6 10.6l2.4 2.4"/><path d="M3.5 19.5h11"/>',
  "spike":    '<path d="M2.5 13h3.2l1.8-2.6 2.4 7 2.6-12 2.4 9.2 1.8-3.6h4.8"/>',
  "talk":     '<path d="M4.5 5.5h9.5a2 2 0 0 1 2 2v4.3a2 2 0 0 1-2 2H9l-3.2 2.6v-2.6H4.5a2 2 0 0 1-2-2V7.5a2 2 0 0 1 2-2z"/><path d="M18.3 9.5h1.2a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2h-.7v2.3l-2.9-2.3h-3.4a2 2 0 0 1-1.7-1"/>',
  "ear":      '<path d="M7.5 9.2a4.8 4.8 0 1 1 9.6 0c0 2.8-2.3 3.6-3 5.5-.7 1.8-1.6 3.8-4 3.8A2.7 2.7 0 0 1 7.4 16"/><path d="M10.2 9.6a2.1 2.1 0 1 1 4.2 0c0 1.2-1.1 1.5-1.5 2.4"/><path d="M19.6 5.6a6.8 6.8 0 0 1 0 7.2"/>',
  "plane":    '<path d="M3 12.6 20.8 5l-6 15.4-3-6.4z"/><path d="M11.8 14 20.8 5"/>',
  "waves":    '<path d="M3 9.5c1.5-1.3 3-1.3 4.5 0s3 1.3 4.5 0 3-1.3 4.5 0 3 1.3 4.5 0"/><path d="M3 14.5c1.5-1.3 3-1.3 4.5 0s3 1.3 4.5 0 3-1.3 4.5 0 3 1.3 4.5 0" opacity=".55"/>',
  # steps and tips
  "speaker":  '<path d="M4 9.8v4.4h3.2l4.3 3.6V6.2L7.2 9.8z"/><path d="M15 9.4a3.7 3.7 0 0 1 0 5.2"/><path d="M17.6 6.8a7.4 7.4 0 0 1 0 10.4" opacity=".6"/>',
  "speaker-low": '<path d="M5 9.8v4.4h3.2l4.3 3.6V6.2L8.2 9.8z"/><path d="M16 10.2a2.6 2.6 0 0 1 0 3.6"/>',
  "bed":      '<path d="M3 18.5V7"/><path d="M3 14h18v4.5"/><path d="M21 14v-2.3A2.7 2.7 0 0 0 18.3 9H11v5"/><circle cx="6.8" cy="11.2" r="1.7"/>',
  "lamp":     '<path d="M8.2 4h7.6l2.4 6.2H5.8z"/><path d="M12 10.2v8"/><path d="M8.6 20h6.8"/><path d="M9.5 13.2l-1 1.2M14.5 13.2l1 1.2" opacity=".55"/>',
  "phone-down":'<rect x="7" y="3" width="10" height="18" rx="2.6"/><path d="M14.3 9.8a2.6 2.6 0 1 1-2.6-3 2 2 0 0 0 2.6 3z"/><path d="M10.6 17.6h2.8"/>',
  "support":  '<path d="M5 5h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-7l-4.2 3.2V17H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z"/><path d="M12 13.6s-3-1.8-3-4a1.6 1.6 0 0 1 3-.9 1.6 1.6 0 0 1 3 .9c0 2.2-3 4-3 4z"/>',
  "shield":   '<path d="M12 3.2 19 6v5.2c0 4.4-3 7.8-7 9.6-4-1.8-7-5.2-7-9.6V6z"/><path d="M12 8.2v4.6"/><path d="M12 15.8v.2"/>',
  "headphones":'<path d="M4.5 15.5v-3.3a7.5 7.5 0 0 1 15 0v3.3"/><path d="M4.5 14.5h2.8v5.8H5.6a1.1 1.1 0 0 1-1.1-1.1z"/><path d="M19.5 14.5h-2.8v5.8h1.7a1.1 1.1 0 0 0 1.1-1.1z"/>',
  "moon-waves":'<path d="M16.6 3.8a6 6 0 1 0 3.9 7.7 4.8 4.8 0 0 1-3.9-7.7z"/><path d="M3 18.5c1.5-1.2 3-1.2 4.5 0s3 1.2 4.5 0 3-1.2 4.5 0 3 1.2 4.5 0"/>',
  "leaf":     '<path d="M5 19C5 10.2 10.2 5 19 5c0 8.8-5.2 14-14 14z"/><path d="M5 19l8.5-8.5"/>',
  "tag-off":  '<path d="M3.5 11.2V4.5h6.7l9.6 9.6-6.7 6.7z"/><circle cx="7.6" cy="8.6" r="1.2"/><path d="M3.5 20.5 20.5 3.5" opacity=".7"/>',
  "cloud-rain":'<path d="M7.2 15a4 4 0 0 1 .4-8 5.2 5.2 0 0 1 9.8 1.6A3.3 3.3 0 0 1 17 15z"/><path d="M9 18.2l-.8 1.8M12.6 18.2l-.8 1.8M16.2 18.2l-.8 1.8" opacity=".6"/>',
  "timer":    '<circle cx="12" cy="13.2" r="7.2"/><path d="M12 13.2V9.6"/><path d="M12 13.2l2.6 1.6"/><path d="M9.8 3.5h4.4"/>',
  "pillow":   '<path d="M4 9c0-2.3 1.2-3.5 3.5-3.5h9C18.8 5.5 20 6.7 20 9v6c0 2.3-1.2 3.5-3.5 3.5h-9C5.2 18.5 4 17.3 4 15z"/><path d="M9.5 12h.01M12 12h.01M14.5 12h.01" stroke-width="2.2"/>',
  "notebook": '<rect x="5" y="3.5" width="13.5" height="17" rx="2"/><path d="M8.5 3.5v17" opacity=".55"/><path d="M11 8.5h4.5M11 12h4.5M11 15.5h2.5"/>',
  "screen-off":'<rect x="3.5" y="5" width="17" height="11" rx="1.8"/><path d="M9 20h6M12 16v4"/><path d="M15 8.2a2.4 2.4 0 1 1-2.4-2.4" opacity=".0"/><path d="M14.4 8.6a2.4 2.4 0 1 1-2.6-2.1 1.9 1.9 0 0 0 2.6 2.1z"/>',
  "bed-only": '<path d="M3 18.5V8"/><path d="M3 14h18v4.5"/><path d="M21 14v-2.3A2.7 2.7 0 0 0 18.3 9H11v5"/><path d="M5.5 11.5h3"/>',
  "breath":   '<path d="M3.5 9.5h9.5a2.5 2.5 0 1 0-2.5-2.5"/><path d="M3.5 13h13.5a2.5 2.5 0 1 1-2.5 2.5"/><path d="M3.5 16.5h6"/>',
  "sunrise":  '<path d="M3 18.5h18"/><path d="M6.6 18.5a5.4 5.4 0 0 1 10.8 0"/><path d="M12 5.5v3M5.2 9.6l1.7 1.6M18.8 9.6l-1.7 1.6"/>',
  "nap":      '<circle cx="12" cy="12" r="8"/><path d="M12 7.8V12l2.8 1.8"/>',
  "walk":     '<path d="M3 16.5h12.8l4.7 1.6v1.6H3z"/><path d="M3 16.5V10l3.8 1.1 2.6-2.1 4.4 4.7 2.9.6"/>',
  "cup":      '<path d="M5 9h11v4.8a4.2 4.2 0 0 1-4.2 4.2H9.2A4.2 4.2 0 0 1 5 13.8z"/><path d="M16 10.4h1.4a2.1 2.1 0 0 1 0 4.2H16"/><path d="M8.2 3.8c0 1 1 1.1 1 2.2M12 3.8c0 1 1 1.1 1 2.2" opacity=".6"/>',
  "car":      '<path d="M4 16.5v-3.3l2.1-5h11.8l2.1 5v3.3z"/><path d="M6.5 16.5v2M17.5 16.5v2"/><path d="M7.4 13.2h.01M16.6 13.2h.01" stroke-width="2.4"/>',
  "pill":     '<path d="M10.4 3.9a5.1 5.1 0 0 1 7.2 7.2l-6.9 6.9a5.1 5.1 0 0 1-7.2-7.2z"/><path d="M7 10.3l6.9 6.9" opacity=".6"/>',
  "calendar": '<rect x="4" y="5" width="16" height="15.5" rx="2.2"/><path d="M4 9.6h16M8.5 3.5v3M15.5 3.5v3"/><path d="M8 13.4h2.6M13.4 13.4H16M8 16.8h2.6" opacity=".6"/>',
  "check-list":'<path d="M4 6.8l1.6 1.6 2.8-3"/><path d="M4 12.8l1.6 1.6 2.8-3"/><path d="M4 18.8l1.6 1.6 2.8-3" opacity=".45"/><path d="M11.5 7h8.5M11.5 13h8.5M11.5 19h6"/>',
  "earplug":  '<path d="M9.2 5.6a3.4 3.4 0 0 1 5.6 2.6v2.4c0 1.2.5 2.2 1.4 2.9l.8.6a2.8 2.8 0 0 1-1.7 5h-.9a3 3 0 0 1-3-3v-4.2c0-1-.4-1.9-1.1-2.5A3.4 3.4 0 0 1 9.2 5.6z"/><path d="M4.5 12h2.2M3.8 8.6l1.9.9M3.8 15.4l1.9-.9" opacity=".6"/>',
  "spark":    '<path d="M12 3.8l1.7 5 5 1.7-5 1.7-1.7 5-1.7-5-5-1.7 5-1.7z"/><path d="M18.6 16.2l.7 1.9 1.9.7-1.9.7-.7 1.9-.7-1.9-1.9-.7 1.9-.7z" opacity=".6"/>',
  "chev":     '<path d="M9.5 6l6 6-6 6"/>',
  "arrow":    '<path d="M5 12h13.5M13.5 7l5 5-5 5"/>',
  "clock-now":'<circle cx="12" cy="12" r="8.2"/><path d="M12 7.6V12h3.6"/>',
  "siren":    '<path d="M6.5 17.5v-5a5.5 5.5 0 0 1 11 0v5"/><path d="M4.5 20h15M12 3.5v1.8M4.4 6.4l1.3 1.3M19.6 6.4l-1.3 1.3"/>',
}

def sprite(names):
    syms = "".join(f'<symbol id="vi-{n}" viewBox="0 0 24 24">{ICONS[n]}</symbol>' for n in sorted(set(names)))
    return f'<svg width="0" height="0" style="position:absolute" aria-hidden="true" focusable="false"><defs>{syms}</defs></svg>'

def icon(n, cls="vi"):
    return f'<svg class="{cls}" aria-hidden="true" focusable="false"><use href="#vi-{n}"/></svg>'

def _r(seed): return random.Random(seed)

def defs(p, grain=True):
    g = (f'<filter id="{p}-grain" x="0" y="0" width="100%" height="100%"><feTurbulence type="fractalNoise" baseFrequency=".85" numOctaves="2" stitchTiles="stitch"/>'
         f'<feColorMatrix values="0 0 0 0 .5  0 0 0 0 .5  0 0 0 0 .5  0 0 0 .55 0"/></filter>') if grain else ""
    return (f'<defs><linearGradient id="{p}-sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" class="s-sky1"/><stop offset=".62" class="s-sky2"/><stop offset="1" class="s-sky3"/></linearGradient>'
            f'<linearGradient id="{p}-h1" x1="0" y1="0" x2="0" y2="1"><stop offset="0" class="s-hill1a"/><stop offset="1" class="s-hill1b"/></linearGradient>'
            f'<linearGradient id="{p}-h2" x1="0" y1="0" x2="0" y2="1"><stop offset="0" class="s-hill2a"/><stop offset="1" class="s-hill2b"/></linearGradient>'
            f'<linearGradient id="{p}-h3" x1="0" y1="0" x2="0" y2="1"><stop offset="0" class="s-hill3a"/><stop offset="1" class="s-hill3b"/></linearGradient>'
            f'<radialGradient id="{p}-glow"><stop offset="0" class="s-warm" stop-opacity=".55"/><stop offset=".45" class="s-warm" stop-opacity=".16"/><stop offset="1" class="s-warm" stop-opacity="0"/></radialGradient>'
            f'<radialGradient id="{p}-cool"><stop offset="0" class="s-a" stop-opacity=".40"/><stop offset="1" class="s-a" stop-opacity="0"/></radialGradient>'
            f'<radialGradient id="{p}-lamp" cx=".5" cy="0" r="1"><stop offset="0" class="s-warm" stop-opacity=".55"/><stop offset="1" class="s-warm" stop-opacity="0"/></radialGradient>'
            f'{g}</defs>')

def sky(p, w, h): return f'<rect width="{w}" height="{h}" fill="url(#{p}-sky)"/>'
def grain(p, w, h, op=.10): return f'<rect width="{w}" height="{h}" filter="url(#{p}-grain)" opacity="{op}" class="s-grain"/>'

def stars(seed, x0, y0, x1, y1, n):
    r = _r(seed); out = []
    for _ in range(n):
        x, y = r.uniform(x0, x1), r.uniform(y0, y1); rad = r.choice((.8, 1, 1.2, 1.5)); op = r.uniform(.25, .75)
        out.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{rad}" class="s-star" opacity="{op:.2f}"/>')
    return "".join(out)

def moon(p, cx, cy, r, glow=True):
    m = f'<mask id="{p}-mm"><rect x="{cx-2*r}" y="{cy-2*r}" width="{4*r}" height="{4*r}" fill="#fff"/><circle cx="{cx+r*.55}" cy="{cy-r*.35}" r="{r*.92}" fill="#000"/></mask>'
    g = f'<circle cx="{cx}" cy="{cy}" r="{r*3.2}" fill="url(#{p}-glow)" opacity=".7"/>' if glow else ""
    return f'{m}{g}<circle cx="{cx}" cy="{cy}" r="{r}" class="s-moon" mask="url(#{p}-mm)"/>'

def sun(p, cx, cy, r, rings=4, clip_y=None):
    rr = "".join(f'<circle cx="{cx}" cy="{cy}" r="{r*(1.6+i*.75):.0f}" fill="none" class="s-st-warm" stroke-width="1.3" opacity="{.42-i*.09:.2f}"/>' for i in range(rings))
    return (f'<circle cx="{cx}" cy="{cy}" r="{r*4}" fill="url(#{p}-glow)"/>{rr}<circle cx="{cx}" cy="{cy}" r="{r}" class="s-sun"/>')

def ridge(seed, w, y, amp, n=4):
    r = _r(seed); xs = [w * i / n for i in range(n + 1)]; ys = [y + r.uniform(-amp, amp) for _ in xs]
    d = f"M0 {ys[0]:.0f}"
    for i in range(1, len(xs)):
        cx = (xs[i - 1] + xs[i]) / 2
        d += f" C {cx:.0f} {ys[i-1]:.0f}, {cx:.0f} {ys[i]:.0f}, {xs[i]:.0f} {ys[i]:.0f}"
    return d

def hills(p, seed, w, h, y, gap=26, amp=(14, 18, 22)):
    out = []
    for k, (cls, a) in enumerate(((f"url(#{p}-h1)", amp[0]), (f"url(#{p}-h2)", amp[1]), (f"url(#{p}-h3)", amp[2]))):
        out.append(f'<path d="{ridge(seed + k, w, y + k * gap, a)} V{h} H0z" fill="{cls}"/>')
    return "".join(out)

def rings(cx, cy, radii, cls="s-st-a", op0=.5, sw=1.4):
    return "".join(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" class="{cls}" stroke-width="{sw}" opacity="{max(op0 - i*op0/len(radii), .05):.2f}"/>' for i, r in enumerate(radii))

def wave(x0, x1, y, a0, a1, cycles, cls="s-st-a", sw=1.6, op=.8, steps=140):
    pts = []
    for i in range(steps + 1):
        t = i / steps; x = x0 + (x1 - x0) * t; a = a0 + (a1 - a0) * t
        pts.append(f"{x:.1f},{y - a * math.sin(t * cycles * 2 * math.pi):.1f}")
    return f'<path d="M{" L".join(pts)}" fill="none" class="{cls}" stroke-width="{sw}" stroke-linecap="round" opacity="{op}"/>'

def path_road(x0, y0, x1, y1, w0, w1, bend=60):
    """A tapering path from (x0,y0) (near, width w0) to (x1,y1) (far, width w1)."""
    mx, my = (x0 + x1) / 2 + bend, (y0 + y1) / 2
    return (f'<path d="M{x0-w0/2:.0f} {y0} Q {mx-w0/4:.0f} {my:.0f} {x1-w1/2:.0f} {y1} L {x1+w1/2:.0f} {y1} Q {mx+w0/4:.0f} {my:.0f} {x0+w0/2:.0f} {y0} Z" class="s-path"/>')

def stones(pts, cls="s-a"):
    return "".join(f'<ellipse cx="{x}" cy="{y}" rx="{rx}" ry="{rx*.36:.1f}" class="{cls}" opacity="{o}"/>' for x, y, rx, o in pts)

def svg(vb, body, cls="s-art", par="xMidYMid slice", label=None):
    return f'<svg viewBox="{vb}" class="{cls}" preserveAspectRatio="{par}" aria-hidden="true" focusable="false">{body}</svg>'

# ---------------- motifs ----------------
def window(x, y, w, h, p, inner=""):
    r = w / 2
    d = f"M{x} {y+h}V{y+r}a{r} {r} 0 0 1 {w} 0V{y+h}z"
    return (f'<clipPath id="{p}-win"><path d="{d}"/></clipPath><path d="{d}" class="s-night"/>'
            f'<g clip-path="url(#{p}-win)">{inner}</g><path d="{d}" fill="none" class="s-st-frame" stroke-width="3"/>'
            f'<path d="M{x+r} {y+4}V{y+h}" class="s-st-frame" stroke-width="2" opacity=".6"/>')

def speaker(x, y, s=1):
    return (f'<g transform="translate({x} {y}) scale({s})"><rect x="0" y="0" width="34" height="48" rx="8" class="s-obj"/>'
            f'<circle cx="17" cy="28" r="9" fill="none" class="s-st-a" stroke-width="2"/><circle cx="17" cy="11" r="3" class="s-a" opacity=".7"/></g>'
            + "".join(f'<path d="M{x+44*s+i*13*s:.0f} {y+28*s-(12+i*9)*s:.0f} a{(12+i*9)*s:.0f} {(12+i*9)*s:.0f} 0 0 1 0 {(24+i*18)*s:.0f}" fill="none" class="s-st-a" stroke-width="{2*s:.1f}" stroke-linecap="round" opacity="{.75-i*.22:.2f}"/>' for i in range(3)))

def lamp(x, y, s=1, p="l"):
    # floor lamp: shade, stem, warm cone
    return (f'<path d="M{x-90*s} {y+250*s} L{x-28*s} {y+52*s} L{x+28*s} {y+52*s} L{x+90*s} {y+250*s} Z" fill="url(#{p}-lamp)" opacity=".9"/>'
            f'<path d="M{x-30*s} {y+52*s} L{x-20*s} {y} H{x+20*s} L{x+30*s} {y+52*s} Z" class="s-warm" opacity=".85"/>'
            f'<path d="M{x} {y+52*s} V{y+240*s}" class="s-st-ink" stroke-width="{4*s:.1f}"/><path d="M{x-26*s} {y+242*s} H{x+26*s}" class="s-st-ink" stroke-width="{5*s:.1f}" stroke-linecap="round"/>')

def chair(x, y, s=1):
    return (f'<path d="M{x} {y+40*s} q0 -40 40 -40 h70 q40 0 40 40 v58 h-150z" class="s-obj"/>'
            f'<rect x="{x-14*s}" y="{y+50*s}" width="{178*s}" height="{44*s}" rx="{18*s}" class="s-obj2"/>'
            f'<path d="M{x+6*s} {y+94*s} v22 M{x+144*s} {y+94*s} v22" class="s-st-ink" stroke-width="{5*s:.1f}" stroke-linecap="round"/>')

def book(x, y, s=1):
    return (f'<path d="M{x} {y} q{30*s} -10 {60*s} 0 v{40*s} q-{30*s} -10 -{60*s} 0z" class="s-paper"/><path d="M{x+60*s} {y} q{30*s} -10 {60*s} 0 v{40*s} q-{30*s} -10 -{60*s} 0z" class="s-paper2"/>'
            f'<path d="M{x+60*s} {y} v{40*s}" class="s-st-ink" stroke-width="1.5" opacity=".5"/>')

def cup(x, y, s=1):
    st = "".join(f'<path d="M{x+(14+i*14)*s} {y-8*s} c-6 -8 6 -14 0 -24" fill="none" class="s-st-warm" stroke-width="{2*s:.1f}" stroke-linecap="round" opacity=".55"/>' for i in range(3))
    return (f'{st}<path d="M{x} {y} h{56*s} v{28*s} a{22*s} {22*s} 0 0 1 -{22*s} {22*s} h-{12*s} a{22*s} {22*s} 0 0 1 -{22*s} -{22*s}z" class="s-paper"/>'
            f'<path d="M{x+56*s} {y+8*s} h{8*s} a{9*s} {9*s} 0 0 1 0 {18*s} h-{8*s}" fill="none" class="s-st-paper" stroke-width="{4*s:.1f}"/>')

def lighthouse(x, y, s=1, p="lh"):
    return (f'<path d="M{x+18*s} {y+20*s} L{x+380*s} {y-70*s} L{x+380*s} {y+70*s} Z" fill="url(#{p}-glow)" opacity=".8"/>'
            f'<path d="M{x-16*s} {y+150*s} L{x-10*s} {y+30*s} H{x+10*s} L{x+16*s} {y+150*s} Z" class="s-paper"/>'
            f'<path d="M{x-13*s} {y+70*s} H{x+13*s} M{x-14*s} {y+110*s} H{x+14*s}" class="s-st-b" stroke-width="{7*s:.1f}" opacity=".6"/>'
            f'<rect x="{x-12*s}" y="{y+8*s}" width="{24*s}" height="{24*s}" rx="{4*s}" class="s-warm"/><path d="M{x-16*s} {y+8*s} L{x} {y-10*s} L{x+16*s} {y+8*s} Z" class="s-obj"/>')

def headphones(x, y, s=1):
    return (f'<path d="M{x} {y+60*s} v-14 a{50*s} {50*s} 0 0 1 {100*s} 0 v14" fill="none" class="s-st-paper" stroke-width="{8*s:.1f}" stroke-linecap="round"/>'
            f'<rect x="{x-10*s}" y="{y+44*s}" width="{26*s}" height="{44*s}" rx="{10*s}" class="s-a"/><rect x="{x+84*s}" y="{y+44*s}" width="{26*s}" height="{44*s}" rx="{10*s}" class="s-a"/>')

def leaf(x, y, s=1):
    return (f'<path d="M{x} {y} c{30*s} -40 {90*s} -40 {110*s} -10 c-{30*s} {34*s} -{80*s} {40*s} -{110*s} {10*s}z" class="s-a" opacity=".9"/>'
            f'<path d="M{x+4*s} {y} c{30*s} -10 {60*s} -14 {100*s} -10" fill="none" class="s-st-night" stroke-width="{2*s:.1f}" opacity=".6"/>')

def tag(x, y, s=1):
    return (f'<path d="M{x} {y} h{70*s} l{30*s} {30*s} l-{30*s} {30*s} h-{70*s}z" class="s-paper" transform="rotate(-12 {x} {y})"/>'
            f'<circle cx="{x+72*s}" cy="{y+16*s}" r="{6*s}" class="s-night" transform="rotate(-12 {x} {y})"/>'
            f'<path d="M{x+80*s} {y+12*s} c{40*s} -30 {70*s} -10 {90*s} -40" fill="none" class="s-st-paper" stroke-width="2" stroke-dasharray="3 6" opacity=".7"/>')

def notebook(x, y, s=1):
    lines = "".join(f'<path d="M{x+30*s} {y+(34+i*22)*s} h{(80 if i%2 else 100)*s}" class="s-st-ink" stroke-width="3" stroke-linecap="round" opacity=".35"/>' for i in range(5))
    checks = "".join(f'<path d="M{x+12*s} {y+(30+i*22)*s} l4 4 7 -8" fill="none" class="s-st-a" stroke-width="2.4" stroke-linecap="round"/>' for i in range(3))
    return (f'<rect x="{x}" y="{y}" width="{150*s}" height="{150*s}" rx="{12*s}" class="s-paper" transform="rotate(-4 {x} {y})"/>'
            f'<g transform="rotate(-4 {x} {y})">{lines}{checks}</g>'
            f'<path d="M{x+130*s} {y+150*s} l{60*s} -{110*s}" class="s-st-b" stroke-width="{8*s:.1f}" stroke-linecap="round"/>')

def bubble(x, y, w, h, s=1, cls="s-obj"):
    return f'<path d="M{x+14} {y} h{w-28} a14 14 0 0 1 14 14 v{h-28} a14 14 0 0 1 -14 14 h-{w*.55:.0f} l-18 16 v-16 h-{w*.45-46:.0f} a14 14 0 0 1 -14 -14 v-{h-28} a14 14 0 0 1 14 -14z" class="{cls}"/>'

def magnifier(x, y, s=1):
    return (f'<circle cx="{x}" cy="{y}" r="{46*s}" class="s-glass"/><circle cx="{x}" cy="{y}" r="{46*s}" fill="none" class="s-st-paper" stroke-width="{7*s:.1f}"/>'
            f'<path d="M{x+33*s} {y+33*s} l{40*s} {40*s}" class="s-st-paper" stroke-width="{12*s:.1f}" stroke-linecap="round"/>')

def shelter(x, y, w, s=1):
    rain = "".join(f'<path d="M{x-60+i*28} {y-90+(i%3)*14} l-8 18" class="s-st-b" stroke-width="2" stroke-linecap="round" opacity=".45"/>' for i in range(int((w+120)/28)))
    return (f'{rain}<path d="M{x} {y} a{w/2} {w/2*0.78} 0 0 1 {w} 0z" class="s-paper2"/>'
            f'<path d="M{x+w*.12} {y} a{w*.38} {w*.38*0.78} 0 0 1 {w*.76} 0z" class="s-warm" opacity=".22"/>'
            f'<circle cx="{x+w/2}" cy="{y-w*.16}" r="{w*.07}" class="s-warm"/>')

def sprout(x, y, s=1):
    return (f'<path d="M{x} {y} v-{38*s}" class="s-st-a" stroke-width="{4*s:.1f}" stroke-linecap="round"/>'
            f'<path d="M{x} {y-34*s} c-{26*s} 0 -{40*s} -{14*s} -{40*s} -{36*s} c{24*s} 0 {40*s} {12*s} {40*s} {36*s}z" class="s-a"/>'
            f'<path d="M{x} {y-24*s} c0 -{24*s} {16*s} -{40*s} {40*s} -{40*s} c0 {24*s} -{16*s} {40*s} -{40*s} {40*s}z" class="s-a2"/>')

# ---------------- scenes ----------------
def _vign(p, seed, inner, night=True, sunpos=None, moonpos=None, horizon=150, W=400, H=240, star_n=14):
    b = defs(p) + sky(p, W, H)
    if night: b += stars(seed, 10, 10, W - 10, horizon - 30, star_n)
    if moonpos: b += moon(p, *moonpos)
    if sunpos: b += sun(p, *sunpos)
    b += hills(p, seed, W, H, horizon, gap=22, amp=(8, 10, 12)) + inner + grain(p, W, H, .08)
    return svg(f"0 0 {W} {H}", b, "s-art s-vign")

def step_art(i):
    W, H = 320, 200
    if i == 0: return _vign("j0", 21, '<path d="M0 200 q 80 -40 150 -30 t 170 10 V200z" class="s-obj2"/>' + lighthouse(96, 40, .82, "j0"), night=True, W=W, H=H, horizon=130)
    if i == 1: return _vign("j1", 22, headphones(110, 40, 1) + wave(40, 290, 172, 12, 4, 4, "s-st-b", 2, .7), night=False, sunpos=(270, 130, 12), W=W, H=H, horizon=130)
    if i == 2: return _vign("j2", 23, moon("j2m", 230, 60, 20) + wave(20, 300, 150, 6, 6, 5, "s-st-a", 2, .8) + wave(20, 300, 166, 5, 5, 5, "s-st-a", 1.6, .55) + wave(20, 300, 182, 4, 4, 5, "s-st-a", 1.3, .35), night=True, W=W, H=H, horizon=130)
    if i == 3: return _vign("j3", 24, rings(170, 160, (24, 44, 66, 90), "s-st-a", .55, 1.6) + leaf(120, 160, .95), night=False, sunpos=(60, 130, 12), W=W, H=H, horizon=130)
    if i == 4: return _vign("j4", 25, tag(96, 92, 1.05), night=False, sunpos=(262, 130, 13), W=W, H=H, horizon=130)

def card_art(kind):
    """Small square scenes for the Sleep routine cards (night, still awake, tomorrow)."""
    W = H = 240
    if kind == "now":
        return _vign("kn", 81, window(88, 34, 96, 150, "kn", stars(82, 88, 34, 184, 140, 7) + moon("knm", 150, 82, 13)) + speaker(30, 150, .72),
                     night=True, W=W, H=H, horizon=184, star_n=10)
    if kind == "awake":
        return _vign("ka", 83, lamp(150, 40, .62, "ka") + chair(70, 150, .82) + book(96, 140, .5), night=True, W=W, H=H, horizon=208, star_n=8)
    if kind == "tomorrow":
        return _vign("kt", 85, cup(46, 160, 1.05), night=False, sunpos=(160, 168, 24), W=W, H=H, horizon=170)

def harbour_art(p="hb", W=320, H=150):
    """'When it feels like too much': a calm dawn horizon over gentle water; soft rings around a low sun suggest sound settling."""
    b = defs(p) + sky(p, W, H) + stars(91, 10, 6, W - 10, 60, 7)
    b += sun(p, W * .7, H * .62, 15, rings=4)
    b += f'<path d="M0 {H*.62:.0f} C {W*.25:.0f} {H*.58:.0f}, {W*.45:.0f} {H*.64:.0f}, {W*.62:.0f} {H*.61:.0f} S {W*.9:.0f} {H*.58:.0f}, {W} {H*.6:.0f} V{H} H0z" class="s-water"/>'
    for i, (y, a, op) in enumerate(((.70, 3.2, .55), (.79, 3.8, .42), (.88, 4.4, .3))):
        b += wave(-10, W + 10, H * y, a, a, 4 + i, "s-st-a", 1.6, op)
    b += f'<path d="M{W*.7-30:.0f} {H*.66:.0f} h60" class="s-st-warm" stroke-width="2" stroke-linecap="round" opacity=".35"/>'
    b += f'<path d="M{W*.7-18:.0f} {H*.72:.0f} h36" class="s-st-warm" stroke-width="2" stroke-linecap="round" opacity=".22"/>'
    return svg(f"0 0 {W} {H}", b + grain(p, W, H, .07), "s-art s-harbour")

def tile_art(kind, W=240, H=120):
    """Small scenes for the four 'right now' tiles on 'When it feels like too much'."""
    p = "ta-" + kind
    if kind == "breath":    # slow breath: soft rings spreading over still water, a leaf resting
        inner = rings(120, 84, (16, 30, 46, 64), "s-st-a", .5, 1.5) + leaf(84, 92, .62)
        return _vign(p, 101, inner, night=False, sunpos=(196, 70, 10), W=W, H=H, horizon=78, star_n=0)
    if kind == "attention": # somewhere gentle to go: a path towards a calm horizon, a small headphone
        inner = path_road(70, H, 168, 74, 70, 5, bend=-26) + stones([(76, 112, 9, .85), (104, 98, 7, .65), (130, 87, 5, .5)]) + headphones(168, 60, .38)
        return _vign(p, 102, inner, night=False, sunpos=(176, 72, 9), W=W, H=H, horizon=74, star_n=0)
    if kind == "talk":      # tell someone: two speech bubbles
        inner = bubble(46, 22, 96, 46, 1, "s-paper") + bubble(112, 52, 88, 40, 1, "s-b") + '<circle cx="80" cy="45" r="4" class="s-a"/><circle cx="96" cy="45" r="4" class="s-a" opacity=".7"/><circle cx="112" cy="45" r="4" class="s-a" opacity=".45"/>'
        return _vign(p, 103, inner, night=True, W=W, H=H, horizon=96, star_n=6)
    if kind == "kind":      # be kind to yourself: a soft sunrise, warm and steady
        return _vign(p, 104, rings(120, 92, (30, 46, 64), "s-st-warm", .35, 1.3), night=False, sunpos=(120, 92, 18), W=W, H=H, horizon=92, star_n=0)

def conc_art(kind, W=240, H=120):
    """Small scenes for 'Concentration, work and study'."""
    p = "ca-" + kind
    if kind == "space":    # a calmer workspace: a desk lamp over an open book, soft sound rings
        return _vign(p, 111, lamp(170, 14, .42, p) + book(60, 84, .8) + rings(108, 80, (18, 30, 44), "s-st-a", .4, 1.3), night=True, W=W, H=H, horizon=96, star_n=5)
    if kind == "pace":     # pace your day: a sun arc with steady steps (short tasks, short breaks)
        dots = "".join(f'<circle cx="{40 + i*40}" cy="{92 - (24 if i in (1,2,3) else 10) + (4 if i==2 else 0)}" r="{6 if i%2==0 else 4}" class="s-a" opacity="{.9 if i%2==0 else .5}"/>' for i in range(5))
        arc = '<path d="M30 96 Q 120 20 210 96" fill="none" class="s-st-warm" stroke-width="1.6" stroke-dasharray="3 7" opacity=".6"/>'
        return _vign(p, 112, arc + dots, night=False, sunpos=(120, 58, 11), W=W, H=H, horizon=96, star_n=0)
    if kind == "recharge": # look after your sleep: a moon over still water
        return _vign(p, 113, moon(p + "m", 150, 44, 16) + wave(10, 230, 96, 3, 3, 4, "s-st-a", 1.5, .6) + wave(10, 230, 106, 3, 3, 5, "s-st-a", 1.3, .35), night=True, W=W, H=H, horizon=90, star_n=9)
    if kind == "work":     # at work: a laptop on a desk with captions on the screen
        lap = ('<rect x="70" y="40" width="100" height="58" rx="6" class="s-obj"/><rect x="78" y="48" width="84" height="40" rx="3" class="s-night"/>'
               '<rect x="86" y="74" width="68" height="5" rx="2.5" class="s-paper" opacity=".85"/><rect x="96" y="82" width="48" height="4" rx="2" class="s-paper" opacity=".5"/>'
               '<path d="M58 100 h124 l-10 8 h-104z" class="s-obj2"/>')
        return _vign(p, 114, lap + rings(186, 60, (10, 18), "s-st-a", .5, 1.3), night=False, sunpos=(40, 60, 9), W=W, H=H, horizon=100, star_n=0)
    if kind == "study":    # studying: books and a lamp-lit page
        books = ('<rect x="62" y="70" width="80" height="12" rx="3" class="s-b" opacity=".75"/><rect x="68" y="58" width="72" height="12" rx="3" class="s-a" opacity=".8"/>'
                 '<rect x="58" y="82" width="88" height="14" rx="3" class="s-obj"/>')
        return _vign(p, 115, books + lamp(178, 18, .4, p), night=True, W=W, H=H, horizon=98, star_n=6)
    if kind == "noise":    # noisy work: ear protection, loud sound kept outside
        out = "".join(f'<path d="M{186+i*12} {44-i*6} a{20+i*10} {20+i*10} 0 0 1 0 {40+i*20}" fill="none" class="s-st-warm" stroke-width="1.6" opacity="{.6-i*.18:.2f}"/>' for i in range(3))
        return _vign(p, 116, headphones(70, 22, .9) + out, night=False, sunpos=None, W=W, H=H, horizon=100, star_n=0)
    if kind == "help":     # longer-term help: a path to a sunrise
        return _vign(p, 117, path_road(90, H, 150, 78, 70, 5, bend=-20) + stones([(94, 112, 8, .8), (116, 98, 6, .6), (134, 88, 4, .45)]), night=False, sunpos=(152, 76, 12), W=W, H=H, horizon=78, star_n=0)
