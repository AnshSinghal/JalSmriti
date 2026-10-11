// Copy the words the server writes (place report PDF, narration, rain emails) from the website's dictionaries into
// backend/src/jalsmriti/data/ui_strings.json, so the page, the PDF and the email say the same thing.
//   node scripts/export-strings.mjs           (write)
//   node scripts/export-strings.mjs --check   (exit 1 if the JSON is out of date)
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const dir = path.join(here, "..", "src", "i18n");
const out = path.join(here, "..", "..", "backend", "src", "jalsmriti", "data", "ui_strings.json");
const LANGS = ["en", "hi", "kn", "ta", "te", "ml", "ne"];
const PREFIXES = ["f.", "lc.", "io.", "grade.", "month.", "place.memory.", "place.radar.", "act.", "report.", "rain.",
  "speech.", "heat.", "wl.", "signal.", "unit.", "share.", "rti.", "verdict."];

function parse(file) {
  const text = fs.readFileSync(path.join(dir, file), "utf8");
  const m = new Map();
  const re = /^\s*"([^"]+)":\s*"((?:[^"\\]|\\.)*)",?\s*$/gm;
  let x;
  while ((x = re.exec(text))) m.set(x[1], JSON.parse(`"${x[2]}"`));
  return m;
}

const data = {};
for (const lang of LANGS) {
  const d = parse(`${lang}.ts`);
  data[lang] = Object.fromEntries([...d].filter(([k]) => PREFIXES.some((p) => k.startsWith(p))).sort(([a], [b]) => (a < b ? -1 : 1)));
}
const json = JSON.stringify(data, null, 0) + "\n";
if (process.argv.includes("--check")) {
  const cur = fs.existsSync(out) ? fs.readFileSync(out, "utf8") : "";
  if (cur !== json) {
    console.log("ui_strings.json is out of date: run npm run export:strings");
    process.exit(1);
  }
  console.log("ui_strings.json is up to date");
} else {
  fs.mkdirSync(path.dirname(out), { recursive: true });
  fs.writeFileSync(out, json);
  console.log(`wrote ${path.relative(process.cwd(), out)}: ${LANGS.map((l) => `${l} ${Object.keys(data[l]).length}`).join(", ")}`);
}
