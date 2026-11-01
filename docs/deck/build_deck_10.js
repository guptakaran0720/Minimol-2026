// Builds docs/Minimol_Storage_Pitch_10.pptx, the 10-slide deck.  cd docs/deck && npm ci && npm run build:10
// Same visual language as build_deck.js; bars are drawn from shapes so they render in Keynote too.
// Visual language follows gdgc.hackmol.com: the four Google colours, dark headings with one
// accent-coloured word, a faint grid on white, and rounded blocks with a dark outline.
// Every number on these slides comes from bench/results (see docs/RESULTS.md); keep it that way.
const path = require("path");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const pptxgen = require("pptxgenjs");
const md = require("react-icons/md");

const OUT = process.argv[2] || path.join(__dirname, "..", "Minimol_Storage_Pitch_10.pptx");

const HEX = {
  ink: "222222", gray: "5F6368", line: "DADCE0", paper: "FFFFFF", mist: "F8F9FA",
  blue: "4285F4", red: "EA4335", yellow: "FBBC05", green: "34A853", deepBlue: "1967D2",
  blueTint: "E8F0FE", greenTint: "E6F4EA", yellowTint: "FEF7E0", redTint: "FCE8E6",
};

const THEME = {
  name: "Minimol GDGC",
  headFontFace: "Arial",
  bodyFontFace: "Arial",
  colors: {
    dk1: HEX.ink, lt1: HEX.paper, dk2: HEX.gray, lt2: HEX.mist,
    accent1: HEX.blue, accent2: HEX.red, accent3: HEX.yellow, accent4: HEX.green,
    accent5: HEX.deepBlue, accent6: HEX.blueTint, hlink: HEX.deepBlue, folHlink: HEX.gray,
  },
};

const W = 13.333, H = 7.5, M = 0.6;
let objectCount = 0;
const name = (kind) => `${kind}-${++objectCount}`;

// ---------- images: grid backgrounds and icons ----------

async function gridPng(bg, lineColor, step = 40) {
  const w = 1600, h = 900;
  let lines = "";
  for (let x = step; x < w; x += step) lines += `<line x1="${x}" y1="0" x2="${x}" y2="${h}"/>`;
  for (let y = step; y < h; y += step) lines += `<line x1="0" y1="${y}" x2="${w}" y2="${y}"/>`;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}"><rect width="100%" height="100%" fill="#${bg}"/><g stroke="#${lineColor}" stroke-width="1.2">${lines}</g></svg>`;
  return "image/png;base64," + (await sharp(Buffer.from(svg)).png().toBuffer()).toString("base64");
}

const iconCache = new Map();
async function icon(Comp, color) {
  const key = `${Comp.name}-${color}`;
  if (!iconCache.has(key)) {
    const svg = ReactDOMServer.renderToStaticMarkup(React.createElement(Comp, { color: `#${color}`, size: 256 }));
    const png = await sharp(Buffer.from(svg)).resize(256, 256).png().toBuffer();
    iconCache.set(key, "image/png;base64," + png.toString("base64"));
  }
  return iconCache.get(key);
}

// ---------- building blocks (scheme colours, so a theme change restyles everything) ----------

function setup(pres) {
  const C = pres.SchemeColor;
  const outline = () => ({ color: C.text1, width: 1.5 });

  const block = (slide, x, y, w, h, fill, opts = {}) =>
    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x, y, w, h, rectRadius: opts.radius ?? 0.18, fill: { color: fill }, line: opts.noLine ? { type: "none" } : outline(),
      objectName: name("block"),
    });

  const circle = (slide, x, y, d, fill, opts = {}) =>
    slide.addShape(pres.shapes.OVAL, {
      x, y, w: d, h: d, fill: { color: fill }, line: opts.noLine ? { type: "none" } : outline(), objectName: name("circle"),
    });

  const iconInCircle = async (slide, Comp, x, y, d, fill, iconColor) => {
    circle(slide, x, y, d, fill);
    const pad = d * 0.22;
    slide.addImage({ data: await icon(Comp, iconColor), x: x + pad, y: y + pad, w: d - 2 * pad, h: d - 2 * pad, objectName: name("icon") });
  };

  const text = (slide, value, opts) =>
    slide.addText(value, { isTextBox: true, margin: 0, valign: "top", color: C.text1, fontSize: 16, objectName: name("text"), ...opts });

  const dot = (slide, x, y, fill, d = 0.16) => circle(slide, x, y, d, fill, { noLine: true });

  return { C, block, circle, iconInCircle, text, dot };
}

// ---------- deck: 10 slides, same visual language as build_deck.js ----------
// Every number comes from measured runs: docs/RESULTS.md (Docker bench, three laptops) and the
// live runs recorded in PR #11 / #17 (scrubbing, audits, drain, chaos run).

async function build() {
  const pres = new pptxgen();
  pres.layout = "LAYOUT_WIDE";
  pres.title = "Minimol Storage: peer-to-peer cloud storage that heals itself";
  pres.author = "Minimol Storage team";
  pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
  const { C, block, circle, iconInCircle, text, dot } = setup(pres);

  const lightGrid = await gridPng(HEX.paper, "EEF1F5");
  const blueGrid = await gridPng(HEX.blue, "5C96F5");
  const footer = [
    { text: { text: "Minimol Storage", options: { x: M, y: 7.0, w: 4, h: 0.3, fontSize: 10, color: C.text2, margin: 0 } } },
  ];
  const slideNumber = { x: W - M - 0.6, y: 7.0, w: 0.6, h: 0.3, fontSize: 10, color: C.text2, align: "right" };
  const titlePlaceholder = {
    placeholder: {
      options: { name: "title", type: "title", x: M, y: 0.45, w: W - 2 * M, h: 0.85, fontSize: 34, bold: true, color: C.text1, valign: "middle", align: "left", margin: 0 },
      text: "",
    },
  };
  pres.defineSlideMaster({ title: "COVER", background: { data: lightGrid }, objects: [] });
  pres.defineSlideMaster({ title: "CONTENT", background: { data: lightGrid }, objects: [titlePlaceholder, ...footer], slideNumber });
  pres.defineSlideMaster({ title: "CLOSING", background: { data: blueGrid }, objects: [] });

  const content = (section, titleRuns, notes) => {
    const s = pres.addSlide({ masterName: "CONTENT", sectionTitle: section });
    s.addText(titleRuns, { placeholder: "title" });
    s.addNotes(notes);
    return s;
  };
  const t = (plain, accent, color) => [
    { text: plain, options: { color: C.text1 } },
    ...(accent ? [{ text: accent, options: { color } }] : []),
  ];
  const onFill = (fill) => (fill === C.accent3 || fill === C.background1 || fill === C.background2 || fill === C.accent6 ? C.text1 : C.background1);
  const iconHex = (fill) => (fill === C.accent3 ? HEX.ink : HEX.paper);

  // Horizontal bars drawn from shapes, so they render in PowerPoint, Keynote and Google Slides alike.
  const bar = (s, x, y, w, h, fill) =>
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: Math.max(w, 0.02), h, fill: { color: fill }, line: { type: "none" }, objectName: name("bar") });

  // ===== 1. Cover =====
  pres.addSection({ title: "Opening" });
  {
    const s = pres.addSlide({ masterName: "COVER", sectionTitle: "Opening" });
    dot(s, M, 1.27, C.accent1, 0.14);
    text(s, "Peer-to-peer cloud storage · compressed + encrypted · audited · self-healing", { x: M + 0.25, y: 1.18, w: 7, h: 0.32, fontSize: 14, color: C.text2 });
    s.addText(
      [
        { text: "Store. Survive.", options: { color: C.text1, breakLine: true } },
        { text: "Heal.", options: { color: C.accent1 } },
      ],
      { isTextBox: true, x: M, y: 1.75, w: 7.2, h: 2.5, fontSize: 64, bold: true, margin: 0, valign: "top", objectName: name("cover-title") },
    );
    text(s, "Minimol Storage turns the laptops you already have into one drive. Files are compressed and encrypted before they leave your machine, kept as 3 copies on 3 laptops, checked for rot and lies, and repaired automatically.", {
      x: M, y: 4.35, w: 6.6, h: 1.3, fontSize: 18, color: C.text2, lineSpacingMultiple: 1.15,
    });
    block(s, M, 5.85, 2.55, 0.62, C.accent5, { noLine: true, radius: 0.31 });
    text(s, "Live demo · 3 laptops", { x: M, y: 5.85, w: 2.55, h: 0.62, fontSize: 15, bold: true, color: C.background1, align: "center", valign: "middle" });
    block(s, M + 2.8, 5.85, 2.9, 0.62, C.background1, { radius: 0.31 });
    text(s, "Python · React · Docker", { x: M + 2.8, y: 5.85, w: 2.9, h: 0.62, fontSize: 15, color: C.accent5, align: "center", valign: "middle" });

    const gx = 7.75, gy = 1.25, bw = 2.45, gap = 0.25;
    block(s, gx, gy, bw, bw, C.accent1);
    await iconInCircle(s, md.MdLock, gx + 0.62, gy + 0.62, 1.2, C.background1, HEX.blue);
    circle(s, gx + bw + gap, gy, bw, C.accent2);
    await iconInCircle(s, md.MdHub, gx + bw + gap + 0.62, gy + 0.62, 1.2, C.background1, HEX.red);
    block(s, gx, gy + bw + gap, bw, bw, C.accent4);
    await iconInCircle(s, md.MdAutorenew, gx + 0.62, gy + bw + gap + 0.62, 1.2, C.background1, HEX.green);
    block(s, gx + bw + gap, gy + bw + gap, bw, bw, C.accent3);
    await iconInCircle(s, md.MdGppGood, gx + bw + gap + 0.62, gy + bw + gap + 0.62, 1.2, C.background1, HEX.ink);
    [C.accent1, C.accent2, C.accent3, C.accent4].forEach((c, i) =>
      s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: gx + 1.45 + i * 0.42, y: gy + 2 * bw + gap + 0.35, w: 0.34, h: 0.08, rectRadius: 0.04, fill: { color: c }, line: { type: "none" }, objectName: name("dash") }),
    );
    text(s, "Your laptops. One drive.", { x: gx + 3.2, y: gy + 2 * bw + gap + 0.24, w: 2.4, h: 0.3, fontSize: 12, color: C.text2 });
    s.addNotes("Open with the promise in three words: store, survive, heal. One sentence on what it is: the laptops you already have, working as one drive that checks and repairs itself. About 20 seconds, then straight to how.");
  }

  // ===== 2. Solution =====
  pres.addSection({ title: "Solution" });
  {
    const s = content("Solution", t("One program on ", "every laptop", C.accent1),
      "Start with the problem in one breath: a rented cloud has one owner, can read your files, and the spare disk in every laptop goes unused. Then the six things one program on every laptop does about it. The last two are new since the first version: every disk is scrubbed and every laptop is audited by its peers, and you control where files live.");
    const cards = [
      [md.MdLock, C.accent1, "Compress, then encrypt", "zstd, then AES-256-GCM per 1 MiB chunk. Peers only ever hold ciphertext."],
      [md.MdContentCopy, C.accent4, "3 copies, 3 laptops", "Every chunk on 3 distinct laptops. Lose 2 and it still downloads."],
      [md.MdSpeed, C.accent3, "Smart routing", "Slow laptops get no new chunks. Downloads ask the fastest holder first."],
      [md.MdAutorenew, C.accent2, "Self-healing", "A dead laptop's chunks are re-copied to the others in about 20 to 40 s."],
      [md.MdGppGood, C.accent5, "Proof of storage", "Disks are scrubbed for rot and peers audit each other. Bad copies get replaced."],
      [md.MdManageSearch, C.background1, "You stay in control", "Lock a file to your laptop, see where every chunk went, drain a laptop before it leaves."],
    ];
    const cw = (W - 2 * M - 2 * 0.27) / 3, ch = 2.05;
    for (const [i, [Ic, fill, head, body]] of cards.entries()) {
      const x = M + (i % 3) * (cw + 0.27), y = 1.6 + Math.floor(i / 3) * (ch + 0.25);
      const ink = onFill(fill);
      block(s, x, y, cw, ch, fill);
      await iconInCircle(s, Ic, x + 0.3, y + 0.3, 0.8, fill === C.background1 ? C.accent1 : C.background1, fill === C.background1 ? HEX.paper : (fill === C.accent3 ? HEX.ink : (fill === C.accent5 ? HEX.deepBlue : { [C.accent1]: HEX.blue, [C.accent4]: HEX.green, [C.accent2]: HEX.red }[fill])));
      text(s, head, { x: x + 1.25, y: y + 0.42, w: cw - 1.45, h: 0.5, fontSize: 19, bold: true, color: ink });
      text(s, body, { x: x + 0.3, y: y + 1.28, w: cw - 0.55, h: 0.72, fontSize: 14, color: ink, lineSpacingMultiple: 1.05 });
    }
    block(s, M, 6.25, W - 2 * M, 0.6, C.accent6, { noLine: true });
    text(s, "What if the laptops you already have were the cloud?", { x: M + 0.4, y: 6.25, w: W - 2 * M - 0.8, h: 0.6, fontSize: 19, bold: true, italic: true, color: C.accent5, valign: "middle" });
  }

  // ===== 3. Pipeline =====
  pres.addSection({ title: "How it works" });
  {
    const s = content("How it works", t("How a file ", "travels", C.accent1),
      "Walk left to right. Stress the order: compress before encrypt, because encrypted bytes don't compress. The chunk's name is the hash of its ciphertext, so anyone can check a chunk without the key: that is what scrubbing and audits build on.");
    const steps = [
      [md.MdContentCut, C.accent1, HEX.blue, "Split", "1 MiB chunks, read as a stream"],
      [md.MdCompress, C.accent4, HEX.green, "Compress", "zstd level 3, kept only if 3%+ smaller"],
      [md.MdLock, C.accent2, HEX.red, "Encrypt", "AES-256-GCM, a fresh key per file"],
      [md.MdFingerprint, C.accent3, HEX.ink, "Name", "SHA-256 of the ciphertext"],
      [md.MdHub, C.accent1, HEX.blue, "Place", "3 distinct laptops, rendezvous hashing"],
      [md.MdVerified, C.accent4, HEX.green, "Verify", "Re-hashed on store, download and scrub"],
    ];
    const n = steps.length, d = 1.15, x0 = M + 0.3, span = (W - 2 * M - 0.6 - d) / (n - 1);
    for (const [i, [Ic, fill, hex, head, body]] of steps.entries()) {
      const cx = x0 + i * span;
      if (i < n - 1) {
        s.addShape(pres.shapes.LINE, { x: cx + d + 0.08, y: 2.3, w: span - d - 0.16, h: 0, line: { color: C.text2, width: 1.5, endArrowType: "triangle" }, objectName: name("arrow") });
      }
      await iconInCircle(s, Ic, cx, 1.72, d, fill, fill === C.accent3 ? HEX.ink : HEX.paper);
      text(s, `${i + 1}. ${head}`, { x: cx - 0.3, y: 3.05, w: d + 0.6, h: 0.4, fontSize: 18, bold: true, align: "center" });
      text(s, body, { x: cx - 0.35, y: 3.5, w: d + 0.7, h: 0.9, fontSize: 13, color: C.text2, align: "center" });
    }
    block(s, M, 4.75, 5.9, 1.75, C.accent6, { noLine: true });
    await iconInCircle(s, md.MdDownload, M + 0.35, 5.15, 0.9, C.accent5, HEX.paper);
    text(s, "Download reverses it", { x: M + 1.5, y: 5.0, w: 4.2, h: 0.4, fontSize: 18, bold: true });
    text(s, "Fetch, check each hash, decrypt, decompress, then check the whole file's SHA-256 before handing it over.", { x: M + 1.5, y: 5.45, w: 4.2, h: 0.95, fontSize: 14, color: C.text2 });
    block(s, M + 6.233, 4.75, 5.9, 1.75, C.background2, { noLine: true });
    await iconInCircle(s, md.MdMemory, M + 6.583, 5.15, 0.9, C.accent4, HEX.paper);
    text(s, "Memory stays small", { x: M + 7.733, y: 5.0, w: 4.2, h: 0.4, fontSize: 18, bold: true });
    text(s, "Only a few chunks are in RAM at once, and a bad chunk is caught before decryption.", { x: M + 7.733, y: 5.45, w: 4.2, h: 0.95, fontSize: 14, color: C.text2 });
  }

  // ===== 4. Architecture =====
  {
    const s = content("How it works", t("No server. Every node is ", "equal", C.accent4),
      "There is no central server. Every laptop runs the same program: it stores chunks for others, uploads its own, scrubs its disk, audits its peers and runs repair. Every request and every reply between laptops is HMAC-signed. New since the first version: scrub, audits, the live timeline, metrics, drain and the per-file transfer log.");
    const nodes = [[M + 0.2, 1.75, C.accent1], [M + 3.9, 1.75, C.accent2], [M + 0.2, 4.6, C.accent4], [M + 3.9, 4.6, C.accent3]];
    const nw = 1.75, nh = 1.15;
    const centre = (i) => [nodes[i][0] + nw / 2, nodes[i][1] + nh / 2];
    for (const [a, b] of [[0, 1], [0, 2], [0, 3], [1, 2], [1, 3], [2, 3]]) {
      const [x1, y1] = centre(a), [x2, y2] = centre(b);
      s.addShape(pres.shapes.LINE, { x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1) || 0.001, h: Math.abs(y2 - y1) || 0.001, flipV: (x2 - x1) * (y2 - y1) < 0, line: { color: C.text2, width: 1 }, objectName: name("link") });
    }
    for (const [i, [x, y, fill]] of nodes.entries()) {
      block(s, x, y, nw, nh, fill);
      await iconInCircle(s, md.MdLaptopMac, x + 0.18, y + 0.27, 0.6, C.background1, HEX.ink);
      text(s, `node-${i + 1}`, { x: x + 0.88, y: y + 0.38, w: 0.85, h: 0.4, fontSize: 15, bold: true, color: fill === C.accent3 ? C.text1 : C.background1 });
    }
    block(s, M + 1.4, 3.42, 3.25, 0.62, C.background1, { radius: 0.31 });
    text(s, "Signed requests + replies", { x: M + 1.4, y: 3.42, w: 3.25, h: 0.62, fontSize: 15, bold: true, align: "center", valign: "middle" });

    text(s, "Inside each node", { x: 7.15, y: 1.6, w: 5.5, h: 0.45, fontSize: 20, bold: true });
    const layers = [
      [C.accent1, "Dashboard (React)", "files, Logs, timeline at /ui"],
      [C.accent1, "User API", "localhost only: upload (lock), download, delete"],
      [C.accent2, "Pipeline", "chunk, compress, encrypt, keys, manifests"],
      [C.accent3, "Routing + transfer", "placement, ETA ranking, hedging"],
      [C.accent4, "Repair loop", "every 10 s, an elected holder re-copies"],
      [C.accent4, "Scrub + audits", "check own disk, challenge peers"],
      [C.accent1, "Peer API", "chunks, inventory, heartbeats, gossip, mDNS"],
      [C.accent2, "Ops", "timeline, /metrics, drain, IP/MAC transfer log"],
    ];
    for (const [i, [c, head, body]] of layers.entries()) {
      const y = 2.2 + i * 0.56;
      dot(s, 7.15, y + 0.1, c, 0.2);
      s.addText([{ text: head + "  ", options: { bold: true, color: C.text1 } }, { text: body, options: { color: C.text2 } }], { isTextBox: true, x: 7.5, y, w: 5.3, h: 0.42, fontSize: 15, margin: 0, valign: "top", objectName: name("layer") });
    }
  }

  // ===== 5. Smart routing (evidence) =====
  pres.addSection({ title: "Evidence" });
  {
    const s = content("Evidence", t("Slow laptops skipped, ", "fastest holder first", C.accent1),
      "Placement uses weighted rendezvous hashing over healthy peers; a peer whose estimated fetch time stays above 3× the cluster median for 30 s drops to a slow tier and gets no new chunks. Downloads rank holders by estimated fetch time and hedge to the next holder if a request stalls. Both charts are the Docker benchmark with node-4 delayed 300 ms: say that the delay is simulated.");
    // left card: where 60 copies landed
    const lx = M, cw = 5.9, cy = 1.6, chh = 3.25;
    block(s, lx, cy, cw, chh, C.background1);
    text(s, "Where 60 chunk copies landed (one 20 MB upload)", { x: lx + 0.3, y: cy + 0.22, w: cw - 0.6, h: 0.35, fontSize: 14, bold: true });
    const rows = [["node-1", 20, 18], ["node-2", 20, 14], ["node-3", 20, 17], ["node-4 (slow)", 0, 11]];
    const bx = lx + 1.75, bwMax = cw - 1.75 - 0.75;
    rows.forEach(([label, smart, rnd], i) => {
      const y = cy + 0.72 + i * 0.5;
      text(s, label, { x: lx + 0.3, y: y + 0.03, w: 1.4, h: 0.4, fontSize: 13, bold: label.includes("slow"), color: label.includes("slow") ? C.accent2 : C.text1, valign: "middle" });
      bar(s, bx, y, bwMax * smart / 24, 0.2, C.accent1);
      text(s, String(smart), { x: bx + bwMax * smart / 24 + 0.08, y: y - 0.04, w: 0.5, h: 0.28, fontSize: 12, bold: true });
      s.addShape(pres.shapes.RECTANGLE, { x: bx, y: y + 0.24, w: bwMax * rnd / 24, h: 0.2, fill: { color: "BDC1C6" }, line: { type: "none" }, objectName: name("bar") });
      text(s, String(rnd), { x: bx + bwMax * rnd / 24 + 0.08, y: y + 0.2, w: 0.5, h: 0.28, fontSize: 12, color: C.text2 });
    });
    dot(s, lx + 0.3, cy + chh - 0.38, C.accent1, 0.16);
    text(s, "Smart placement", { x: lx + 0.55, y: cy + chh - 0.43, w: 1.7, h: 0.28, fontSize: 12 });
    s.addShape(pres.shapes.OVAL, { x: lx + 2.35, y: cy + chh - 0.38, w: 0.16, h: 0.16, fill: { color: "BDC1C6" }, line: { type: "none" }, objectName: name("dot") });
    text(s, "Random baseline", { x: lx + 2.6, y: cy + chh - 0.43, w: 1.8, h: 0.28, fontSize: 12 });

    // right card: median download time
    const rx = M + 6.233;
    block(s, rx, cy, cw, chh, C.background1);
    text(s, "Median time to download a 20 MB file", { x: rx + 0.3, y: cy + 0.22, w: cw - 0.6, h: 0.35, fontSize: 14, bold: true });
    const dl = [["ETA + hedged reads", 0.146, C.accent1], ["Random holder", 1.697, "BDC1C6"]];
    const rbx = rx + 2.45, rbw = cw - 2.45 - 1.0;
    dl.forEach(([label, v, fill], i) => {
      const y = cy + 0.95 + i * 0.95;
      text(s, label, { x: rx + 0.3, y, w: 2.1, h: 0.5, fontSize: 13, bold: i === 0, valign: "middle" });
      s.addShape(pres.shapes.RECTANGLE, { x: rbx, y: y + 0.05, w: Math.max(rbw * v / 2, 0.04), h: 0.4, fill: { color: fill }, line: { type: "none" }, objectName: name("bar") });
      text(s, `${v.toFixed(3)} s`, { x: rbx + rbw * v / 2 + 0.1, y, w: 0.9, h: 0.5, fontSize: 13, bold: true, valign: "middle" });
    });
    text(s, "same file, same cluster; node-4 delayed 300 ms (simulated)", { x: rx + 0.3, y: cy + chh - 0.45, w: cw - 0.6, h: 0.3, fontSize: 12, color: C.text2 });

    // stat callouts
    block(s, M, 5.05, 5.9, 1.55, C.accent3);
    text(s, "0% vs 21.7%", { x: M + 0.35, y: 5.2, w: 5.2, h: 0.7, fontSize: 34, bold: true });
    text(s, "of new copies on the slow laptop: smart vs random placement (median, 5 runs)", { x: M + 0.35, y: 5.9, w: 5.2, h: 0.6, fontSize: 14 });
    block(s, rx, 5.05, 5.9, 1.55, C.accent1);
    text(s, "11.6× faster", { x: rx + 0.35, y: 5.2, w: 5.2, h: 0.7, fontSize: 34, bold: true, color: C.background1 });
    text(s, "median download: ETA ranking with hedged reads vs a random holder", { x: rx + 0.35, y: 5.9, w: 5.2, h: 0.6, fontSize: 14, color: C.background1 });
  }

  // ===== 6. Healing =====
  {
    const s = content("Evidence", t("Kill it. Corrupt it. ", "Watch it heal", C.accent4),
      "Two kinds of failure, one repair path. A laptop dies: after 20 s every peer marks it dead and the elected holder of each chunk copies it to a new laptop. A byte rots or a peer lies: the laptop's own scrub quarantines the bad chunk, or another laptop's audit catches it with a random challenge, and the same repair restores a good copy. Times are measured: node death on the Docker cluster, scrub and audits on 4 local nodes with a byte flipped on purpose.");
    const stages = [
      [C.accent2, HEX.paper, md.MdPowerOff, "Fails", "Laptop dies, byte rots", "Downloads already skip it"],
      [C.accent3, HEX.ink, md.MdSearch, "Spotted", "Heartbeat, scrub, audit", "Dead, quarantined or distrusted"],
      [C.accent1, HEX.paper, md.MdContentCopy, "Re-copied", "One holder copies", "A race only adds a copy"],
      [C.accent4, HEX.paper, md.MdVerified, "Healthy", "3 good copies again", "No one touched a thing"],
    ];
    const sw = 2.8, gap = 0.31;
    s.addShape(pres.shapes.LINE, { x: M + 0.7, y: 2.3, w: 3 * (sw + gap), h: 0, line: { color: C.text2, width: 1.5, dashType: "dash" }, objectName: name("timeline") });
    for (const [i, [fill, hex, Ic, when, head, body]] of stages.entries()) {
      const x = M + i * (sw + gap);
      await iconInCircle(s, Ic, x + 0.15, 1.72, 1.15, fill, hex);
      text(s, when, { x, y: 3.0, w: sw, h: 0.35, fontSize: 15, bold: true, color: fill === C.accent3 ? C.text1 : fill });
      text(s, head, { x, y: 3.35, w: sw + 0.2, h: 0.45, fontSize: 17, bold: true });
      text(s, body, { x, y: 3.85, w: sw + 0.2, h: 0.45, fontSize: 14, color: C.text2 });
    }
    const stats = [
      [C.accent6, "≈ 20 s", "until every laptop marks a stopped one dead (19.5–20.6 s)"],
      [C.accent6, "21 / 43 s", "from death to every chunk back at 3 copies (two runs)"],
      [C.accent4, "< 1 s", "for a laptop's scrub to quarantine a rotten chunk; good copy back in 16–20 s"],
      [C.accent1, "7–17 s", "for another laptop's audit to catch a bad copy; 3 good copies in 12–23 s"],
    ];
    const tw = (W - 2 * M - 3 * 0.27) / 4;
    for (const [i, [fill, big, label]] of stats.entries()) {
      const x = M + i * (tw + 0.27), ink = onFill(fill);
      block(s, x, 4.55, tw, 1.95, fill, { noLine: fill === C.accent6 });
      text(s, big, { x: x + 0.3, y: 4.75, w: tw - 0.5, h: 0.65, fontSize: 30, bold: true, color: ink });
      text(s, label, { x: x + 0.3, y: 5.45, w: tw - 0.5, h: 0.95, fontSize: 13, color: ink });
    }
  }

  // ===== 7. Control & visibility =====
  pres.addSection({ title: "Control" });
  {
    const s = content("Control", t("See every chunk. ", "Lock what's yours", C.accent2),
      "Everything on this slide is in the dashboard. Logs: click it next to any file to see which laptop holds each chunk, and which laptops this one uploaded it to and downloaded it from, with IP and MAC. Lock: a locked file opens only on the laptop whose MAC uploaded it, even for someone with the same login. Be precise: the lock is a rule every node enforces, not encryption. Drain: the honest way to leave. Metrics: Prometheus counters for everything above.");
    const cards = [
      [md.MdManageSearch, C.accent1, "Logs for every file", "Which laptop holds each chunk, and where it was uploaded to and downloaded from, by IP and MAC."],
      [md.MdLock, C.accent2, "Locked files", "Lock to this laptop: other devices get no download, preview, replace or delete, even with the same login."],
      [md.MdTimeline, C.accent3, "Live timeline + metrics", "Joins, deaths, quarantines and repairs as they happen; /metrics for Prometheus."],
      [md.MdExitToApp, C.accent4, "Graceful drain", "A leaving laptop takes no new chunks and says when it's safe to power off (about 20 s)."],
      [md.MdKey, C.accent1, "Passphrase recovery", "Username + passphrase on a brand-new laptop brings every file back from the peers."],
      [md.MdDeleteForever, C.accent2, "Owner-only delete", "Only the owner's derived token can erase a file's chunks, on every laptop."],
    ];
    const cw = (W - 2 * M - 2 * 0.27) / 3, ch = 2.4;
    for (const [i, [Ic, fill, head, body]] of cards.entries()) {
      const x = M + (i % 3) * (cw + 0.27), y = 1.6 + Math.floor(i / 3) * (ch + 0.27);
      block(s, x, y, cw, ch, C.background1);
      await iconInCircle(s, Ic, x + 0.3, y + 0.3, 0.8, fill, iconHex(fill));
      text(s, head, { x: x + 1.25, y: y + 0.45, w: cw - 1.45, h: 0.5, fontSize: 18, bold: true });
      text(s, body, { x: x + 0.3, y: y + 1.25, w: cw - 0.55, h: 1.05, fontSize: 14, color: C.text2, lineSpacingMultiple: 1.05 });
    }
  }

  // ===== 8. Measured =====
  pres.addSection({ title: "Results" });
  {
    const s = content("Results", t("Measured, ", "not promised", C.accent1),
      "Every number here was measured. The first three come from bench.py on a 4-node Docker cluster, median of 5 runs. The chaos run crashed a random node every 20 to 40 s for 10 minutes while reading and writing. The real-laptop self-test ran on three laptops over campus Wi-Fi on 1 November.");
    const tiles = [
      [C.accent1, "0.30×", "size of a 20 MB CSV after compression and encryption"],
      [C.accent4, "11.6×", "faster downloads: ETA ranking + hedged reads vs a random holder"],
      [C.accent3, "0.19 MB", "sent to re-upload a 20 MB file after a 1% append (1 of 21 chunks)"],
      [C.accent2, "565 / 565", "reads succeeded in a 10-minute chaos run with 12 random crashes; 0 corrupt"],
      [C.background1, "3 / 3", "real laptops passed every self-test check, incl. tamper and wrong-key tests"],
      [C.background1, "221 + 1", "automated tests passing, plus a live cluster test"],
    ];
    const tw = 3.85, th = 2.25, gx = 0.27, gy = 0.3;
    tiles.forEach(([fill, big, label], i) => {
      const x = M + (i % 3) * (tw + gx), y = 1.6 + Math.floor(i / 3) * (th + gy), ink = onFill(fill);
      block(s, x, y, tw, th, fill);
      text(s, big, { x: x + 0.35, y: y + 0.3, w: tw - 0.7, h: 0.85, fontSize: 40, bold: true, color: ink });
      text(s, label, { x: x + 0.35, y: y + 1.2, w: tw - 0.7, h: 0.9, fontSize: 14, color: ink });
    });
    text(s, "Docker: 4 nodes on one laptop, real crypto, node-4 delayed 300 ms (simulated), median of 5 · chaos run: 4 local nodes · real laptops: campus Wi-Fi · all 1 Nov 2026", { x: M, y: 6.6, w: W - 2 * M, h: 0.3, fontSize: 10, color: C.text2 });
  }

  // ===== 9. Limits =====
  pres.addSection({ title: "Context" });
  {
    const s = content("Context", t("Honest limits, ", "clear next steps", C.accent4),
      "Say the limits before a judge does. Proof of storage is no longer on this list: audits shipped. Two items are new and worth saying plainly: the lock is a policy, not encryption, and two laptops publishing their file list at the same moment can drop a file from the list (its data stays safe); the chaos run caught it once and a merge-before-publish fix is written but not merged yet.");
    const pairs = [
      ["One network (LAN, hotspot or Tailscale)", "Kademlia DHT + relays for the internet"],
      ["3 full copies = 3× before compression", "Erasure coding with zfec once there are 8+ nodes"],
      ["Lock is a rule nodes enforce, not encryption", "Per-device keys plus an owner recovery key"],
      ["Two writers at once can drop a file from the list", "Merge-before-publish (fix written, not merged)"],
      ["Chunks from before delete tokens can't be erased", "Garbage collection of unreferenced chunks"],
      ["Peer links signed, not encrypted (data is)", "Per-node identities with mutual TLS"],
    ];
    block(s, M, 1.6, 5.9, 0.62, C.accent2, { radius: 0.31 });
    text(s, "Today", { x: M, y: 1.6, w: 5.9, h: 0.62, fontSize: 18, bold: true, color: C.background1, align: "center", valign: "middle" });
    block(s, M + 6.233, 1.6, 5.9, 0.62, C.accent4, { radius: 0.31 });
    text(s, "Next", { x: M + 6.233, y: 1.6, w: 5.9, h: 0.62, fontSize: 18, bold: true, color: C.background1, align: "center", valign: "middle" });
    pairs.forEach(([now, next], i) => {
      const y = 2.42 + i * 0.7;
      dot(s, M + 0.1, y + 0.13, C.accent2, 0.18);
      text(s, now, { x: M + 0.45, y, w: 5.4, h: 0.5, fontSize: 15 });
      s.addShape(pres.shapes.LINE, { x: M + 5.95, y: y + 0.22, w: 0.25, h: 0, line: { color: C.text2, width: 1.25, endArrowType: "triangle" }, objectName: name("arrow") });
      dot(s, M + 6.333, y + 0.13, C.accent4, 0.18);
      text(s, next, { x: M + 6.683, y, w: 5.4, h: 0.5, fontSize: 15 });
    });
  }

  // ===== 10. Closing =====
  pres.addSection({ title: "Closing" });
  {
    const s = pres.addSlide({ masterName: "CLOSING", sectionTitle: "Closing" });
    s.addText([
      { text: "Store. Survive.", options: { breakLine: true } },
      { text: "Heal." },
    ], { isTextBox: true, x: M, y: 1.4, w: 8, h: 2.6, fontSize: 66, bold: true, color: C.background1, margin: 0, valign: "top", objectName: name("closing-title") });
    text(s, "Minimol Storage: the laptops you already have, working as one drive that checks and repairs itself.", { x: M, y: 4.15, w: 7.6, h: 0.9, fontSize: 20, color: C.background1 });
    block(s, M, 5.35, 3.0, 0.68, C.background1, { radius: 0.34 });
    text(s, "Questions?", { x: M, y: 5.35, w: 3.0, h: 0.68, fontSize: 18, bold: true, color: C.accent5, align: "center", valign: "middle" });
    text(s, "github.com/guptakaran0720/Minimol-2026", { x: M + 3.3, y: 5.47, w: 5.5, h: 0.45, fontSize: 16, color: C.background1, valign: "middle" });
    const roles = [
      [C.accent2, "P1", "Crypto + data"], [C.accent3, "P2", "Node + network"],
      [C.accent4, "P3", "Routing + repair"], [C.background1, "P4", "Story + demo"],
    ];
    for (const [i, [fill, tag, label]] of roles.entries()) {
      const y = 1.5 + i * 1.18;
      block(s, 9.3, y, 3.43, 0.95, fill);
      text(s, tag, { x: 9.55, y, w: 0.7, h: 0.95, fontSize: 22, bold: true, valign: "middle", color: fill === C.accent2 || fill === C.accent4 ? C.background1 : C.text1 });
      text(s, label, { x: 10.3, y, w: 2.3, h: 0.95, fontSize: 16, valign: "middle", color: fill === C.accent2 || fill === C.accent4 ? C.background1 : C.text1 });
    }
    s.addNotes("Close with the three words and invite questions. Answer from docs/JUDGE_QA.md; the owner of each part answers its questions.");
  }

  await pres.writeFile({ fileName: OUT });
  await applyThemeColors(OUT, THEME);
  console.log(`wrote ${OUT}`);
}

// pptxgenjs can't write theme colours, so scheme colours would fall back to Office's stock
// palette. Rewrite the colour scheme in every theme part of the saved file.
async function applyThemeColors(file, theme) {
  const fs = require("fs");
  const JSZip = require("jszip");
  const zip = await JSZip.loadAsync(fs.readFileSync(file));
  for (const part of Object.keys(zip.files).filter((f) => /^ppt\/theme\/theme\d+\.xml$/.test(f))) {
    let xml = await zip.file(part).async("string");
    xml = xml.replace(/<a:clrScheme name="[^"]*">/, `<a:clrScheme name="${theme.name}">`);
    for (const [slot, hex] of Object.entries(theme.colors)) {
      const re = new RegExp(`<a:${slot}>[\\s\\S]*?</a:${slot}>`);
      if (!re.test(xml)) throw new Error(`${part}: no <a:${slot}> in colour scheme`);
      xml = xml.replace(re, `<a:${slot}><a:srgbClr val="${hex}"/></a:${slot}>`);
    }
    zip.file(part, xml);
  }
  fs.writeFileSync(file, await zip.generateAsync({ type: "nodebuffer", compression: "DEFLATE" }));
}

build().catch((e) => {
  console.error(e);
  process.exit(1);
});
