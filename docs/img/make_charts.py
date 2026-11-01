"""Draws the README charts as plain SVG from the numbers in docs/RESULTS.md.

    python3 docs/img/make_charts.py

No plotting library: every value below is copied from RESULTS.md, so if a result
changes, change it here and re-run. White card background so the charts read in
both GitHub light and dark mode.
"""
from pathlib import Path

OUT = Path(__file__).parent
INK, MUTED, GRID = "#202124", "#5f6368", "#e8eaed"
BLUE, RED, YELLOW, GREEN, GREY = "#4285F4", "#EA4335", "#FBBC05", "#34A853", "#BDC1C6"
FONT = "font-family='Arial, Helvetica, sans-serif'"


def card(w, h, title, subtitle, body):
    return (f"<svg xmlns='http://www.w3.org/2000/svg' width='{w}' height='{h}' viewBox='0 0 {w} {h}' {FONT}>"
            f"<rect x='0.5' y='0.5' width='{w - 1}' height='{h - 1}' rx='14' fill='#ffffff' stroke='#dadce0'/>"
            f"<text x='24' y='36' font-size='18' font-weight='700' fill='{INK}'>{title}</text>"
            f"<text x='24' y='58' font-size='13' fill='{MUTED}'>{subtitle}</text>{body}</svg>")


def hbars(name, title, subtitle, rows, vmax, fmt, label_w=210, w=760):
    """rows: (label, value, colour). Horizontal bars with the value printed at the end."""
    top, bar_h, gap = 84, 34, 18
    h = top + len(rows) * (bar_h + gap) + 24
    plot_w = w - label_w - 110
    body = ""
    for i in range(5):
        x = label_w + plot_w * i / 4
        body += f"<line x1='{x:.1f}' y1='{top - 8}' x2='{x:.1f}' y2='{h - 20}' stroke='{GRID}'/>"
    for i, (label, value, colour) in enumerate(rows):
        y = top + i * (bar_h + gap)
        bw = max(plot_w * value / vmax, 3)
        body += (f"<text x='{label_w - 12}' y='{y + bar_h / 2 + 5}' font-size='14' text-anchor='end' fill='{INK}'>{label}</text>"
                 f"<rect x='{label_w}' y='{y}' width='{bw:.1f}' height='{bar_h}' rx='6' fill='{colour}'/>"
                 f"<text x='{label_w + bw + 10:.1f}' y='{y + bar_h / 2 + 5}' font-size='14' font-weight='700' fill='{INK}'>{fmt(value)}</text>")
    (OUT / name).write_text(card(w, h, title, subtitle, body))


def grouped(name, title, subtitle, groups, series, vmax, w=760, h=360):
    """groups: labels; series: (name, colour, values)."""
    left, top, bottom = 60, 84, h - 70
    plot_w, plot_h = w - left - 30, bottom - top
    gw = plot_w / len(groups)
    bw = gw / (len(series) + 1)
    body = ""
    for i in range(0, vmax + 1, 5):
        y = bottom - plot_h * i / vmax
        body += (f"<line x1='{left}' y1='{y:.1f}' x2='{w - 30}' y2='{y:.1f}' stroke='{GRID}'/>"
                 f"<text x='{left - 10}' y='{y + 4:.1f}' font-size='12' text-anchor='end' fill='{MUTED}'>{i}</text>")
    for g, label in enumerate(groups):
        for s, (_, colour, values) in enumerate(series):
            v = values[g]
            x = left + g * gw + bw * (s + 0.5)
            bh = plot_h * v / vmax
            body += (f"<rect x='{x:.1f}' y='{bottom - bh:.1f}' width='{bw * 0.9:.1f}' height='{max(bh, 1):.1f}' rx='4' fill='{colour}'/>"
                     f"<text x='{x + bw * 0.45:.1f}' y='{bottom - bh - 6:.1f}' font-size='13' font-weight='700' text-anchor='middle' fill='{INK}'>{v}</text>")
        body += f"<text x='{left + g * gw + gw / 2:.1f}' y='{bottom + 22}' font-size='14' text-anchor='middle' fill='{INK}'>{label}</text>"
    lx = left
    for sname, colour, _ in series:
        body += (f"<rect x='{lx}' y='{h - 30}' width='14' height='14' rx='3' fill='{colour}'/>"
                 f"<text x='{lx + 20}' y='{h - 18}' font-size='13' fill='{INK}'>{sname}</text>")
        lx += 30 + 8 * len(sname)
    (OUT / name).write_text(card(w, h, title, subtitle, body))


hbars("compression.svg", "Client-side compression (encoded ÷ original)",
      "zstd level 3 per 1 MiB chunk, kept only if it saves ≥ 3% · includes 28 B AES-GCM overhead per chunk",
      [("Sensor CSV, 20 MB", 0.302, BLUE), ("Sensor CSV, 4 MB (laptops)", 0.301, BLUE),
       ("JPEG photo", 1.000, GREY), ("Random bytes", 1.000, GREY)],
      1.1, lambda v: f"{v:.3f}")
grouped("placement.svg", "Where 60 chunk copies landed: smart vs random placement",
        "4-node Docker cluster · node-4 delayed 300 ms (simulated) · one 20 MB upload · median run of 5",
        ["node-1", "node-2", "node-3", "node-4 (slow)"],
        [("Tiered rendezvous (ours)", BLUE, [20, 20, 20, 0]), ("Random baseline", GREY, [18, 14, 17, 11])], 25)
hbars("retrieval.svg", "Median time to download a 20 MB file",
      "Same file, same cluster · node-4 delayed 300 ms (simulated) · 5 runs, alternating order",
      [("ETA ranking + hedged reads", 0.146, BLUE), ("Random holder", 1.697, GREY)],
      2.0, lambda v: f"{v:.3f} s  " + ("(11.6× faster)" if v < 1 else ""), label_w=240)
hbars("delta.svg", "Delta sync: bytes sent to re-upload after a ~1% append",
      "Same file name ⇒ same per-file key ⇒ unchanged chunks encrypt identically and are skipped",
      [("Docker: 20.2 MB file", 20.2, GREY), ("Docker: actually sent", 0.188, GREEN),
       ("Laptops: 4.23 MB file", 4.234, GREY), ("Laptops: actually sent", 0.036, GREEN)],
      22, lambda v: f"{v:g} MB")
hbars("healing.svg", "Self-healing on 3 real laptops (seconds)",
      "Campus Wi-Fi · 1 Nov 2026 · seen from laptop 1 · every download still matched while a laptop was down",
      [("Dead laptop detected", 20, YELLOW), ("Refill an empty replacement", 19, BLUE),
       ("Heal after a laptop rejoins", 6, GREEN)],
      24, lambda v: f"{'≈ ' if v != 6 else ''}{v} s", label_w=250)
print("wrote", ", ".join(p.name for p in sorted(OUT.glob("*.svg"))))
