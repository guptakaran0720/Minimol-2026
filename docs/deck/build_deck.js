// Builds docs/Minimol_Storage_Pitch.pptx.  cd docs/deck && npm ci && npm run build
// Visual language follows gdgc.hackmol.com: the four Google colours, dark headings with one
// accent-coloured word, a faint grid on white, and rounded blocks with a dark outline.
// Every number on these slides comes from bench/results (see docs/RESULTS.md); keep it that way.
const path = require("path");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const pptxgen = require("pptxgenjs");
const md = require("react-icons/md");

const OUT = path.join(__dirname, "..", "Minimol_Storage_Pitch.pptx");

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

// ---------- deck ----------

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
  // Title runs: dark text with one accent-coloured phrase, like "Learn. Build. Belong."
  const t = (plain, accent, color) => [
    { text: plain, options: { color: C.text1 } },
    ...(accent ? [{ text: accent, options: { color } }] : []),
  ];

  // ===== 1. Cover =====
  pres.addSection({ title: "Opening" });
  {
    const s = pres.addSlide({ masterName: "COVER", sectionTitle: "Opening" });
    dot(s, M, 1.27, C.accent1, 0.14);
    text(s, "Peer-to-peer cloud storage · client-side compression · smart routing", { x: M + 0.25, y: 1.18, w: 7, h: 0.32, fontSize: 14, color: C.text2 });
    s.addText(
      [
        { text: "Store. Survive.", options: { color: C.text1, breakLine: true } },
        { text: "Heal.", options: { color: C.accent1 } },
      ],
      { isTextBox: true, x: M, y: 1.75, w: 7.2, h: 2.5, fontSize: 64, bold: true, margin: 0, valign: "top", objectName: name("cover-title") },
    );
    text(s, "Minimol Storage turns the laptops you already have into one drive. Files are compressed and encrypted before they leave your machine, kept as 3 copies on 3 different laptops, and repaired automatically when one dies.", {
      x: M, y: 4.35, w: 6.6, h: 1.3, fontSize: 18, color: C.text2, lineSpacingMultiple: 1.15,
    });
    block(s, M, 5.85, 2.55, 0.62, C.accent5, { noLine: true, radius: 0.31 });
    text(s, "Live demo · 3 laptops", { x: M, y: 5.85, w: 2.55, h: 0.62, fontSize: 15, bold: true, color: C.background1, align: "center", valign: "middle" });
    block(s, M + 2.8, 5.85, 2.9, 0.62, C.background1, { radius: 0.31 });
    text(s, "Python · React · Docker", { x: M + 2.8, y: 5.85, w: 2.9, h: 0.62, fontSize: 15, color: C.accent5, align: "center", valign: "middle" });

    // Four-block motif, one per pillar
    const gx = 7.75, gy = 1.25, bw = 2.45, gap = 0.25;
    block(s, gx, gy, bw, bw, C.accent1);
    await iconInCircle(s, md.MdLock, gx + 0.62, gy + 0.62, 1.2, C.background1, HEX.blue);
    circle(s, gx + bw + gap, gy, bw, C.accent2);
    await iconInCircle(s, md.MdHub, gx + bw + gap + 0.62, gy + 0.62, 1.2, C.background1, HEX.red);
    block(s, gx, gy + bw + gap, bw, bw, C.accent4);
    await iconInCircle(s, md.MdAutorenew, gx + 0.62, gy + bw + gap + 0.62, 1.2, C.background1, HEX.green);
    block(s, gx + bw + gap, gy + bw + gap, bw, bw, C.accent3);
    await iconInCircle(s, md.MdSpeed, gx + bw + gap + 0.62, gy + bw + gap + 0.62, 1.2, C.background1, HEX.ink);
    [C.accent1, C.accent2, C.accent3, C.accent4].forEach((c, i) =>
      s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: gx + 1.45 + i * 0.42, y: gy + 2 * bw + gap + 0.35, w: 0.34, h: 0.08, rectRadius: 0.04, fill: { color: c }, line: { type: "none" }, objectName: name("dash") }),
    );
    text(s, "Your laptops. One drive.", { x: gx + 3.2, y: gy + 2 * bw + gap + 0.24, w: 2.4, h: 0.3, fontSize: 12, color: C.text2 });
    s.addNotes("Open with the promise in three words: store, survive, heal. One sentence on what it is, then go straight to the problem. About 20 seconds.");
  }

  // ===== 2. Problem =====
  pres.addSection({ title: "Problem" });
  {
    const s = content("Problem", t("Your cloud has ", "one owner", C.accent2),
      "Three problems with renting someone else's disks. Keep it fast: single point of failure, someone else can read it, and the spare disk we already own goes unused. Land the question at the bottom.");
    const cards = [
      [md.MdCloudOff, C.accent2, HEX.red, "Single point of failure", "One outage, price change or account ban takes every file with it."],
      [md.MdVisibility, C.accent3, HEX.ink, "Someone else can read it", "Unless you encrypt first, the provider holds your plaintext."],
      [md.MdStorage, C.accent4, HEX.green, "Spare disk sits idle", "Every laptop in a lab, club or office has free space nobody uses."],
    ];
    const cw = 3.85, gap = 0.27;
    for (const [i, [Ic, color, hex, head, body]] of cards.entries()) {
      const x = M + i * (cw + gap);
      block(s, x, 1.7, cw, 3.7, C.background1);
      await iconInCircle(s, Ic, x + 0.4, 2.05, 1.0, color, color === C.accent3 ? HEX.ink : HEX.paper);
      text(s, head, { x: x + 0.4, y: 3.3, w: cw - 0.8, h: 0.8, fontSize: 21, bold: true });
      text(s, body, { x: x + 0.4, y: 4.15, w: cw - 0.8, h: 1.2, fontSize: 16, color: C.text2, lineSpacingMultiple: 1.1 });
    }
    block(s, M, 5.65, W - 2 * M, 0.95, C.accent6, { noLine: true });
    text(s, "What if the laptops you already have were the cloud?", { x: M + 0.4, y: 5.65, w: W - 2 * M - 0.8, h: 0.95, fontSize: 22, bold: true, italic: true, color: C.accent5, valign: "middle" });
  }

  // ===== 3. Solution =====
  pres.addSection({ title: "Solution" });
  {
    const s = content("Solution", t("One program on ", "every laptop", C.accent1),
      "The four pillars. Each one maps to a word in the problem statement: client-side compression, storage across peers, smart routing, and we add self-healing because judges will kill a node.");
    const pillars = [
      [md.MdLock, C.accent1, HEX.blue, C.background1, "Compress, then encrypt", "zstd, then AES-256-GCM, per 1 MiB chunk. Peers only ever see ciphertext."],
      [md.MdContentCopy, C.accent4, HEX.green, C.background1, "3 copies, 3 machines", "Every chunk lands on 3 distinct hosts. Lose 2 holders and it still downloads."],
      [md.MdSpeed, C.accent3, HEX.ink, C.text1, "Smart routing", "Slow peers get no new chunks. Downloads ask the fastest holder first."],
      [md.MdAutorenew, C.accent2, HEX.red, C.background1, "Self-healing", "When a node dies, the survivors re-copy its chunks: about 20 to 40 s."],
    ];
    const bw = 5.9, bh = 2.4, gx = 0.333, gy = 0.3;
    for (const [i, [Ic, fill, hex, ink, head, body]] of pillars.entries()) {
      const x = M + (i % 2) * (bw + gx), y = 1.65 + Math.floor(i / 2) * (bh + gy);
      block(s, x, y, bw, bh, fill);
      await iconInCircle(s, Ic, x + 0.35, y + 0.4, 1.05, C.background1, hex);
      text(s, head, { x: x + 1.7, y: y + 0.45, w: bw - 2.0, h: 0.5, fontSize: 22, bold: true, color: ink });
      text(s, body, { x: x + 1.7, y: y + 1.05, w: bw - 2.0, h: 1.1, fontSize: 16, color: ink, lineSpacingMultiple: 1.1 });
    }
  }

  // ===== 4. Pipeline =====
  pres.addSection({ title: "How it works" });
  {
    const s = content("How it works", t("How a file ", "travels", C.accent1),
      "Walk left to right. Stress the order: compress before encrypt, because encrypted bytes don't compress. The chunk's name is the hash of its ciphertext, so anyone can check a chunk without the key.");
    const steps = [
      [md.MdContentCut, C.accent1, HEX.blue, "Split", "1 MiB chunks, read as a stream"],
      [md.MdCompress, C.accent4, HEX.green, "Compress", "zstd level 3, kept only if 3%+ smaller"],
      [md.MdLock, C.accent2, HEX.red, "Encrypt", "AES-256-GCM, a fresh key per file"],
      [md.MdFingerprint, C.accent3, HEX.ink, "Name", "SHA-256 of the ciphertext"],
      [md.MdHub, C.accent1, HEX.blue, "Place", "3 distinct hosts, rendezvous hashing"],
      [md.MdVerified, C.accent4, HEX.green, "Verify", "Re-hashed on store and on download"],
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

  // ===== 5. Architecture =====
  {
    const s = content("How it works", t("No server. Every node is ", "equal", C.accent4),
      "There is no central server. Every laptop runs the same program: it stores chunks for others and uploads its own. Peers find each other with a seed address, gossip and mDNS, and every request is HMAC-signed.");
    // mesh of four nodes
    const nodes = [[M + 0.2, 1.75, C.accent1], [M + 3.9, 1.75, C.accent2], [M + 0.2, 4.6, C.accent4], [M + 3.9, 4.6, C.accent3]];
    const nw = 1.75, nh = 1.15;
    const centre = (i) => [nodes[i][0] + nw / 2, nodes[i][1] + nh / 2];
    for (const [a, b] of [[0, 1], [0, 2], [0, 3], [1, 2], [1, 3], [2, 3]]) {
      const [x1, y1] = centre(a), [x2, y2] = centre(b);
      s.addShape(pres.shapes.LINE, { x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1) || 0.001, h: Math.abs(y2 - y1) || 0.001, flipV: (x2 - x1) * (y2 - y1) < 0, line: { color: C.text2, width: 1 }, objectName: name("link") });
    }
    for (const [i, [x, y, fill]] of nodes.entries()) {
      block(s, x, y, nw, nh, fill);
      await iconInCircle(s, md.MdLaptopMac, x + 0.18, y + 0.27, 0.6, C.background1, fill === C.accent3 ? HEX.ink : HEX.ink);
      text(s, `node-${i + 1}`, { x: x + 0.88, y: y + 0.38, w: 0.85, h: 0.4, fontSize: 15, bold: true, color: fill === C.accent3 ? C.text1 : C.background1 });
    }
    block(s, M + 1.55, 3.42, 2.95, 0.62, C.background1, { radius: 0.31 });
    text(s, "HMAC-signed HTTP", { x: M + 1.55, y: 3.42, w: 2.95, h: 0.62, fontSize: 15, bold: true, align: "center", valign: "middle" });

    text(s, "Inside each node", { x: 7.15, y: 1.7, w: 5.5, h: 0.45, fontSize: 20, bold: true });
    const layers = [
      [C.accent1, "Dashboard (React)", "served by the node at /ui"],
      [C.accent1, "User API", "localhost only: upload, download, recover"],
      [C.accent2, "Pipeline", "chunk, compress, encrypt, keys, manifests"],
      [C.accent3, "Routing + transfer", "placement, ETA ranking, hedging"],
      [C.accent4, "Repair loop", "every 10 s, elected holder re-copies"],
      [C.accent1, "Peer API", "chunks, inventory, heartbeats, gossip, mDNS"],
      [C.accent2, "Chunk store", "atomic writes, quota, hash check"],
    ];
    for (const [i, [c, head, body]] of layers.entries()) {
      const y = 2.32 + i * 0.6;
      dot(s, 7.15, y + 0.1, c, 0.2);
      s.addText([{ text: head + "  ", options: { bold: true, color: C.text1 } }, { text: body, options: { color: C.text2 } }], { isTextBox: true, x: 7.5, y, w: 5.3, h: 0.42, fontSize: 15, margin: 0, valign: "top", objectName: name("layer") });
    }
  }

  // ===== 6. Placement =====
  pres.addSection({ title: "Evidence" });
  {
    const s = content("Evidence", t("Slow peers get ", "no new chunks", C.accent3),
      "Placement uses weighted rendezvous hashing over healthy peers. A peer whose estimated fetch time stays above three times the cluster median for 30 seconds drops to a fallback tier. The chart is the benchmark: node-4 was delayed 300 ms. Say that the delay is simulated.");
    s.addChart(pres.charts.BAR, [
      { name: "Smart placement", labels: ["node-1", "node-2", "node-3", "node-4 (slow)"], values: [20, 20, 20, 0] },
      { name: "Random baseline", labels: ["node-1", "node-2", "node-3", "node-4 (slow)"], values: [18, 14, 17, 11] },
    ], {
      x: M, y: 1.6, w: 7.4, h: 4.95, barDir: "col", barGrouping: "clustered", chartColors: [HEX.blue, "BDC1C6"],
      showTitle: true, title: "Where 60 chunk copies landed (one 20 MB upload)", titleFontSize: 14, titleColor: HEX.ink, titleFontFace: "+mn-lt",
      showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 12, dataLabelColor: HEX.ink, dataLabelFontFace: "+mn-lt",
      catAxisLabelColor: HEX.gray, valAxisLabelColor: HEX.gray, catAxisLabelFontSize: 12, valAxisLabelFontSize: 11,
      catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt",
      valGridLine: { color: "E8EAED", size: 0.75 }, catGridLine: { style: "none" },
      showLegend: true, legendPos: "b", legendFontSize: 12, legendColor: HEX.ink, legendFontFace: "+mn-lt", valAxisMinVal: 0, valAxisMaxVal: 24, valAxisMajorUnit: 4,
    });
    block(s, 8.4, 1.6, 4.33, 2.35, C.accent3);
    text(s, "0% vs 21.7%", { x: 8.75, y: 1.9, w: 3.7, h: 0.8, fontSize: 40, bold: true });
    text(s, "share of copies on the slow peer: smart vs random placement (median, 5 runs)", { x: 8.75, y: 2.75, w: 3.7, h: 1.0, fontSize: 14 });
    text(s, "Why rendezvous hashing", { x: 8.4, y: 4.25, w: 4.33, h: 0.4, fontSize: 17, bold: true });
    const why = ["Same answer on every node, no shared state", "A peer leaving only moves the chunks it held", "Live metrics stay out, so chunks don't churn"];
    why.forEach((w, i) => {
      dot(s, 8.4, 4.83 + i * 0.52, [C.accent1, C.accent4, C.accent2][i]);
      text(s, w, { x: 8.72, y: 4.74 + i * 0.52, w: 4.0, h: 0.42, fontSize: 14, color: C.text2 });
    });
  }

  // ===== 7. Retrieval =====
  {
    const s = content("Evidence", t("Downloads ask the ", "fastest holder", C.accent1),
      "Each chunk has three holders. We rank them by estimated fetch time: round-trip time plus chunk size divided by measured bandwidth. If a request runs past twice its estimate, we also ask the next holder and keep whichever verified reply lands first. Same file, same cluster. To be precise: the smart path is ETA ranking plus hedged reads, the baseline is a random holder with no hedging.");
    s.addChart(pres.charts.BAR, [
      { name: "Median download time (s)", labels: ["ETA + hedged reads", "Random holder"], values: [0.146, 1.697] },
    ], {
      x: M, y: 1.6, w: 7.4, h: 4.95, barDir: "bar", chartColors: [HEX.blue], invertedColors: [HEX.blue],
      showTitle: true, title: "Median time to download a 20 MB file (s), node-4 delayed 300 ms", titleFontSize: 14, titleColor: HEX.ink, titleFontFace: "+mn-lt",
      showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 13, dataLabelColor: HEX.ink, dataLabelFormatCode: "0.000", dataLabelFontFace: "+mn-lt",
      catAxisLabelColor: HEX.ink, valAxisLabelColor: HEX.gray, catAxisLabelFontSize: 14, valAxisLabelFontSize: 11,
      catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt", catAxisOrientation: "maxMin",
      valGridLine: { color: "E8EAED", size: 0.75 }, catGridLine: { style: "none" }, showLegend: false, valAxisMinVal: 0, valAxisMaxVal: 2, valAxisMajorUnit: 0.5,
    });
    block(s, 8.4, 1.6, 4.33, 2.35, C.accent1);
    text(s, "11.6× faster", { x: 8.75, y: 1.9, w: 3.7, h: 0.8, fontSize: 40, bold: true, color: C.background1 });
    text(s, "median download: ETA ranking with hedged reads vs a random holder, same file and cluster", { x: 8.75, y: 2.75, w: 3.7, h: 1.0, fontSize: 14, color: C.background1 });
    text(s, "How the ranking works", { x: 8.4, y: 4.25, w: 4.33, h: 0.4, fontSize: 17, bold: true });
    const how = ["ETA = round-trip time + size ÷ bandwidth", "A peer that just failed waits 15 s at the back", "Stalled request? Ask the next holder too"];
    how.forEach((w, i) => {
      dot(s, 8.4, 4.83 + i * 0.52, [C.accent1, C.accent2, C.accent4][i]);
      text(s, w, { x: 8.72, y: 4.74 + i * 0.52, w: 4.0, h: 0.42, fontSize: 14, color: C.text2 });
    });
  }

  // ===== 8. Self-healing =====
  {
    const s = content("Evidence", t("Kill a node. ", "Watch it heal", C.accent4),
      "This is the live moment. Stop a laptop. After about 20 seconds every peer has marked it dead. Within the next 10 to 20 seconds the elected holder of each affected chunk copies it to a new peer. Only one holder copies; the next one takes over if the leader is silent. A race can only add a copy, never lose one.");
    const stages = [
      [C.accent2, HEX.paper, md.MdPowerOff, "0 s", "Node stops", "Downloads already skip it"],
      [C.accent3, HEX.ink, md.MdSearch, "≈ 20 s", "Marked dead", "Every peer agrees within 1 s"],
      [C.accent1, HEX.paper, md.MdContentCopy, "+ 0–20 s", "Leader re-copies", "One holder per chunk acts"],
      [C.accent4, HEX.paper, md.MdVerified, "Healthy", "3 copies again", "No one touched a thing"],
    ];
    const sw = 2.8, gap = 0.31;
    s.addShape(pres.shapes.LINE, { x: M + 0.7, y: 2.3, w: 3 * (sw + gap), h: 0, line: { color: C.text2, width: 1.5, dashType: "dash" }, objectName: name("timeline") });
    for (const [i, [fill, hex, Ic, when, head, body]] of stages.entries()) {
      const x = M + i * (sw + gap);
      await iconInCircle(s, Ic, x + 0.15, 1.72, 1.15, fill, hex);
      text(s, when, { x, y: 3.0, w: sw, h: 0.35, fontSize: 15, bold: true, color: fill === C.accent3 ? C.text1 : fill });
      text(s, head, { x, y: 3.35, w: sw, h: 0.45, fontSize: 20, bold: true });
      text(s, body, { x, y: 3.8, w: sw, h: 0.45, fontSize: 14, color: C.text2 });
    }
    const stats = [
      [C.accent6, C.text1, "19.5–20.6 s", "each node marked the stopped one dead"],
      [C.accent6, C.text1, "21 s / 43 s", "death to 3 copies in two runs (10 s cycles)"],
      [C.accent4, C.background1, "27 / 27", "files back to healthy after a manual kill"],
    ];
    for (const [i, [fill, ink, big, label]] of stats.entries()) {
      const sw3 = (W - 2 * M - 2 * 0.27) / 3, x = M + i * (sw3 + 0.27);
      block(s, x, 4.55, sw3, 1.95, fill, { noLine: fill === C.accent6 });
      text(s, big, { x: x + 0.35, y: 4.8, w: sw3 - 0.6, h: 0.7, fontSize: 32, bold: true, color: ink });
      text(s, label, { x: x + 0.35, y: 5.55, w: sw3 - 0.6, h: 0.8, fontSize: 14, color: ink });
    }
  }

  // ===== 9. Delta sync =====
  {
    const s = content("Evidence", t("Change 1%, ", "send 1%", C.accent4),
      "Delta sync comes from our production app OTA pipeline, where a 21.6 MB release shipped as 0.41 MB. Here, re-uploading a file with the same name reuses its key, so unchanged chunks encrypt to identical bytes and are already stored. We appended about 1% to a 20 MB file and sent 0.19 MB.");
    s.addChart(pres.charts.BAR, [
      { name: "MB", labels: ["File size (v2)", "Actually sent"], values: [20.2, 0.188] },
    ], {
      x: M, y: 1.6, w: 7.4, h: 3.1, barDir: "bar", chartColors: [HEX.green],
      showTitle: true, title: "Re-upload after appending ~1% to a 20 MB CSV (MB)", titleFontSize: 14, titleColor: HEX.ink, titleFontFace: "+mn-lt",
      showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 13, dataLabelColor: HEX.ink, dataLabelFormatCode: "0.00", dataLabelFontFace: "+mn-lt",
      catAxisLabelColor: HEX.ink, valAxisLabelColor: HEX.gray, catAxisLabelFontSize: 14, valAxisLabelFontSize: 11,
      catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt", catAxisOrientation: "maxMin",
      valGridLine: { color: "E8EAED", size: 0.75 }, catGridLine: { style: "none" }, showLegend: false, valAxisMinVal: 0, valAxisMaxVal: 24, valAxisMajorUnit: 4,
    });
    const flow = [
      [C.accent1, "Same name", "same file key"],
      [C.accent3, "Same chunk", "same encrypted bytes"],
      [C.accent4, "Same hash", "already on 3 hosts: skip"],
    ];
    flow.forEach(([fill, head, body], i) => {
      const x = M + i * 2.55;
      block(s, x, 5.0, 2.3, 1.5, fill === C.accent3 ? C.accent3 : fill);
      const ink = fill === C.accent3 ? C.text1 : C.background1;
      text(s, head, { x: x + 0.25, y: 5.2, w: 1.9, h: 0.45, fontSize: 18, bold: true, color: ink });
      text(s, body, { x: x + 0.25, y: 5.68, w: 1.9, h: 0.7, fontSize: 14, color: ink });
    });
    block(s, 8.4, 1.6, 4.33, 2.35, C.accent4);
    text(s, "1 of 21", { x: 8.75, y: 1.9, w: 3.7, h: 0.8, fontSize: 40, bold: true, color: C.background1 });
    text(s, "chunks sent: 0.19 MB of 20.2 MB", { x: 8.75, y: 2.75, w: 3.7, h: 1.0, fontSize: 15, color: C.background1 });
    block(s, 8.4, 4.25, 4.33, 2.25, C.background2, { noLine: true });
    await iconInCircle(s, md.MdSystemUpdate, 8.7, 4.55, 0.85, C.accent1, HEX.paper);
    text(s, "Born from app OTA", { x: 9.75, y: 4.55, w: 2.8, h: 0.4, fontSize: 17, bold: true });
    text(s, "Our production update pipeline shipped a 21.6\u00A0MB release as 0.41\u00A0MB. Same idea, now encrypted.", { x: 9.75, y: 5.0, w: 2.8, h: 1.4, fontSize: 13, color: C.text2 });
  }

  // ===== 10. Security & recovery =====
  {
    const s = content("Evidence", t("Lose your laptop, ", "not your files", C.accent2),
      "Keys come from a username and passphrase through scrypt, so nothing secret is stored on peers. Each file has its own key, wrapped by the owner's key. The list of your files is signed and kept on every peer. A fresh laptop with the same username and passphrase recovers everything; we test exactly that.");
    const flow = [
      [C.accent1, HEX.paper, md.MdPerson, "Username + passphrase"],
      [C.accent3, HEX.ink, md.MdKey, "scrypt → owner keys"],
      [C.accent4, HEX.paper, md.MdListAlt, "Signed file list from peers"],
      [C.accent2, HEX.paper, md.MdLaptopMac, "Fresh laptop has every file"],
    ];
    for (const [i, [fill, hex, Ic, label]] of flow.entries()) {
      const y = 1.65 + i * 1.22;
      await iconInCircle(s, Ic, M, y, 0.95, fill, hex);
      text(s, label, { x: M + 1.2, y: y + 0.25, w: 4.4, h: 0.45, fontSize: 18, bold: true });
      if (i < flow.length - 1) s.addShape(pres.shapes.LINE, { x: M + 0.475, y: y + 1.0, w: 0, h: 0.2, line: { color: C.text2, width: 1.5, endArrowType: "triangle" }, objectName: name("arrow") });
    }
    block(s, 6.6, 1.6, 6.13, 4.95, C.background1);
    await iconInCircle(s, md.MdShield, 6.95, 1.9, 0.8, C.accent5, HEX.paper);
    text(s, "What protects the data", { x: 7.95, y: 2.05, w: 4.5, h: 0.5, fontSize: 20, bold: true });
    const guards = [
      [C.accent1, "Peers only ever hold ciphertext"],
      [C.accent4, "Every chunk re-hashed on store and download"],
      [C.accent2, "AES-GCM rejects any tampered byte"],
      [C.accent3, "Peer requests HMAC-signed, ±30 s window"],
      [C.accent1, "Owner file list signed; highest version wins"],
      [C.accent4, "Quotas, size caps, owner-only delete"],
    ];
    guards.forEach(([c, g], i) => {
      dot(s, 6.95, 3.03 + i * 0.55, c, 0.18);
      text(s, g, { x: 7.3, y: 2.93 + i * 0.55, w: 5.2, h: 0.42, fontSize: 15 });
    });
  }

  // ===== 11. Results =====
  {
    const s = content("Evidence", t("Measured, ", "not promised", C.accent1),
      "Every number here came out of bench.py on a four-node Docker cluster with real encryption and compression, median of five runs. Say clearly that it's one machine; the multi-laptop run is part of the demo.");
    const tiles = [
      [C.accent1, C.background1, "0.30×", "size of a 20 MB CSV after compression and encryption"],
      [C.accent4, C.background1, "11.6×", "faster downloads: ETA ranking + hedged reads vs a random holder"],
      [C.accent3, C.text1, "0%", "of new copies on the slow peer (random: 21.7%)"],
      [C.accent2, C.background1, "≈ 20–40 s", "from a node dying to every chunk back at 3 copies"],
      [C.background1, C.text1, "0.19 MB", "sent to re-upload a 20 MB file after a 1% append"],
      [C.background1, C.text1, "193 + 1", "automated tests passing, plus a live 4-node cluster test"],
    ];
    const tw = 3.85, th = 2.25, gx = 0.27, gy = 0.3;
    tiles.forEach(([fill, ink, big, label], i) => {
      const x = M + (i % 3) * (tw + gx), y = 1.6 + Math.floor(i / 3) * (th + gy);
      block(s, x, y, tw, th, fill);
      text(s, big, { x: x + 0.35, y: y + 0.3, w: tw - 0.7, h: 0.85, fontSize: 40, bold: true, color: ink });
      text(s, label, { x: x + 0.35, y: y + 1.2, w: tw - 0.7, h: 0.9, fontSize: 14, color: ink });
    });
    text(s, "4-node Docker cluster on one laptop · real encryption + compression · node-4 delayed 300 ms (simulated) · median of 5 runs", { x: M, y: 6.6, w: W - 2 * M, h: 0.3, fontSize: 10, color: C.text2 });
  }

  // ===== 11b. Real laptops =====
  {
    const s = content("Evidence", t("Tested on three ", "real laptops", C.accent4),
      "Everything on the previous slide also ran on three real laptops over campus Wi-Fi. Each laptop ran the same automated self-test. Laptop 3 was switched off and on during the run, and laptop 2 was replaced by an empty node; both healed on their own. Numbers are from the run on 1 November.");
    const tiles = [
      [C.accent4, C.background1, "6 s", "for a file uploaded while a laptop was off to heal once it rejoined"],
      [C.accent1, C.background1, "≈ 19 s", "to refill an empty replacement laptop (13 repair copies)"],
      [C.accent3, C.text1, "8 / 8", "files downloaded, SHA-256 match, with a laptop switched off"],
      [C.background1, C.text1, "0.85%", "of the file sent to re-upload after a 1% edit"],
    ];
    const tw = 2.95, th = 2.3, g = 0.3;
    tiles.forEach(([fill, ink, big, label], i) => {
      const x = M + (i % 2) * (tw + g), y = 1.6 + Math.floor(i / 2) * (th + g);
      block(s, x, y, tw, th, fill);
      text(s, big, { x: x + 0.3, y: y + 0.28, w: tw - 0.6, h: 0.8, fontSize: 36, bold: true, color: ink });
      text(s, label, { x: x + 0.3, y: y + 1.15, w: tw - 0.6, h: 1.0, fontSize: 14, color: ink });
    });
    const cx = M + 2 * tw + g + 0.35, cw = W - M - cx;
    block(s, cx, 1.6, cw, 4.9, C.background1);
    await iconInCircle(s, md.MdVerified, cx + 0.3, 1.85, 0.75, C.accent4, HEX.paper);
    text(s, "Every laptop passed", { x: cx + 1.25, y: 1.98, w: cw - 1.5, h: 0.5, fontSize: 20, bold: true });
    const checks = [
      [C.accent1, "CSV compressed to 0.30× its size"],
      [C.accent4, "Every chunk on 3 distinct laptops"],
      [C.accent2, "Every download matches its SHA-256"],
      [C.accent3, "Flipped byte caught, file still correct"],
      [C.accent1, "Wrong passphrase sees no files"],
      [C.accent4, "Wrong cluster key can't join"],
      [C.accent2, "0 of 261 stored chunks readable"],
      [C.accent3, "File list restored from peers on unlock"],
    ];
    checks.forEach(([c, label], i) => {
      const y = 2.85 + i * 0.44;
      dot(s, cx + 0.35, y + 0.09, c, 0.17);
      text(s, label, { x: cx + 0.68, y, w: cw - 1.75, h: 0.36, fontSize: 14 });
      text(s, "3/3", { x: cx + cw - 0.95, y, w: 0.65, h: 0.36, fontSize: 14, bold: true, color: C.accent4, align: "right" });
    });
    text(s, "3 laptops · campus Wi-Fi, 18–140 ms round trips · real encryption + compression · 1 Nov 2026 · slow-node A/B is from the Docker run", { x: M, y: 6.6, w: W - 2 * M, h: 0.3, fontSize: 10, color: C.text2 });
  }

  // ===== 12. Comparison =====
  pres.addSection({ title: "Context" });
  {
    const s = content("Context", t("Where we ", "fit", C.accent1),
      "Be generous to the others: Tahoe-LAFS is the closest design and we borrowed its ideas. Our difference is the combination on a few ordinary laptops: client-side compression, measured routing, owner-independent repair, and passphrase recovery.");
    const head = (txt) => ({ text: txt, options: { bold: true, color: HEX.paper, fill: { color: HEX.ink }, fontSize: 14 } });
    const row = (sys, model, gap, highlight) => [
      { text: sys, options: { bold: true, fontSize: 14, color: HEX.ink, fill: { color: highlight ? HEX.blueTint : HEX.paper } } },
      { text: model, options: { fontSize: 13, color: HEX.ink, fill: { color: highlight ? HEX.blueTint : HEX.paper } } },
      { text: gap, options: { fontSize: 13, color: highlight ? HEX.deepBlue : HEX.gray, fill: { color: highlight ? HEX.blueTint : HEX.paper } } },
    ];
    s.addTable([
      [head("System"), head("How it works"), head("Gap for this problem")],
      row("Google Drive", "One company's data centres", "Single owner; the provider can read your files"),
      row("IPFS / Kubo", "Content-addressed P2P blocks", "Data persists only where pinned; no built-in encryption; Kubo recommends 6 GB RAM"),
      row("Syncthing", "Syncs folders between your devices", "Full copies on your own devices, not sharded across peers"),
      row("Storj", "Erasure-coded pieces on storage nodes", "Satellites coordinate metadata and payments"),
      row("Tahoe-LAFS", "Encrypted, erasure-coded storage grid", "Closest design; no client compression or measured routing"),
      row("Minimol", "Equal nodes, 3 copies, self-repair", "LAN-first today; DHT + NAT traversal planned", true),
    ], {
      x: M, y: 1.6, w: W - 2 * M, colW: [2.2, 4.0, W - 2 * M - 6.2], rowH: 0.62, valign: "middle",
      border: { type: "solid", pt: 0.75, color: HEX.line }, margin: [0.06, 0.12, 0.06, 0.12], fontFace: "Arial", objectName: name("table"),
    });
    text(s, "Sources: Tahoe-LAFS configuration docs (3-of-10 encoding), Kubo README (6 GB RAM), Storj community docs (29-of-80 pieces).", { x: M, y: 6.6, w: W - 2 * M, h: 0.3, fontSize: 10, color: C.text2 });
  }

  // ===== 13. Demo =====
  {
    const s = content("Context", t("What you'll see ", "live", C.accent2),
      "Read the steps as a promise, then do them, following docs/DEMO_SCRIPT.md. Smart routing is not on this list because with 3 laptops every chunk must be on all three; it is on slides 6 and 7. If the network misbehaves, switch to the Docker cluster on one laptop and say so.");
    const steps = [
      "Upload a log: it shrinks to about 30% and spreads to 3 laptops",
      "Upload a photo: compression is skipped, it is already compressed",
      "Show a stored piece: unreadable, and named by its own hash",
      "Switch a laptop off: the file still downloads, SHA-256 matches",
      "Watch it turn red: files are honestly marked degraded",
      "Switch it back on: missing copies refilled, healthy in seconds",
      "Append to the log and re-upload: only the changed piece travels",
      "Brand-new laptop: username + passphrase recover everything",
    ];
    const colors = [C.accent1, C.accent2, C.accent3, C.accent4];
    const cw = 5.9, rh = 1.12;
    steps.forEach((st, i) => {
      const col = Math.floor(i / 4), r = i % 4;
      const x = M + col * (cw + 0.333), y = 1.65 + r * (rh + 0.12);
      block(s, x, y, cw, rh, C.background1);
      circle(s, x + 0.25, y + 0.24, 0.64, colors[i % 4]);
      text(s, String(i + 1), { x: x + 0.25, y: y + 0.24, w: 0.64, h: 0.64, fontSize: 20, bold: true, align: "center", valign: "middle", color: i % 4 === 2 ? C.text1 : C.background1 });
      text(s, st, { x: x + 1.1, y: y + 0.2, w: cw - 1.35, h: rh - 0.4, fontSize: 15, valign: "middle" });
    });
  }

  // ===== 14. Limits and roadmap =====
  {
    const s = content("Context", t("Honest limits, ", "clear next steps", C.accent4),
      "Say the limits before a judge does. Each limit has a known fix and we can say which part of the code changes.");
    const pairs = [
      ["One network (LAN or hotspot)", "Kademlia DHT + relays for the internet"],
      ["3 full copies = 3× before compression", "Erasure coding with zfec once there are 8+ nodes"],
      ["Extra copies are never deleted", "Garbage collection of unreferenced chunks"],
      ["Peer links signed, not encrypted (data is)", "Per-node identities with mutual TLS"],
      ["Inserting bytes breaks delta sync", "Content-defined chunking (FastCDC)"],
      ["Health check is not proof of storage", "Random challenge-response audits"],
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

  // ===== 15. Closing =====
  pres.addSection({ title: "Closing" });
  {
    const s = pres.addSlide({ masterName: "CLOSING", sectionTitle: "Closing" });
    s.addText([
      { text: "Store. Survive.", options: { breakLine: true } },
      { text: "Heal." },
    ], { isTextBox: true, x: M, y: 1.4, w: 8, h: 2.6, fontSize: 66, bold: true, color: C.background1, margin: 0, valign: "top", objectName: name("closing-title") });
    text(s, "Minimol Storage: the laptops you already have, working as one drive that repairs itself.", { x: M, y: 4.15, w: 7.6, h: 0.9, fontSize: 20, color: C.background1 });
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
