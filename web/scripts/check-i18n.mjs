// Check every dictionary against English: same keys, same {placeholders}, no leftovers.
//   node scripts/check-i18n.mjs            (all languages)
//   node scripts/check-i18n.mjs hi kn      (some)
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const dir = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "src", "i18n");

function parse(file) {
  const text = fs.readFileSync(path.join(dir, file), "utf8");
  const out = new Map();
  const re = /^\s*"([^"]+)":\s*"((?:[^"\\]|\\.)*)",?\s*$/gm;
  let m;
  while ((m = re.exec(text))) out.set(m[1], JSON.parse(`"${m[2]}"`));
  return out;
}
const holes = (s) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort().join(",");

const en = parse("en.ts");
const langs = process.argv.slice(2).length ? process.argv.slice(2) : ["hi", "kn", "ta", "te", "ml", "ne"];
let bad = 0;
for (const lang of langs) {
  const d = parse(`${lang}.ts`);
  const missing = [...en.keys()].filter((k) => !d.has(k));
  const extra = [...d.keys()].filter((k) => !en.has(k));
  const holesWrong = [...d.keys()].filter((k) => en.has(k) && holes(en.get(k)) !== holes(d.get(k)));
  const untranslated = [...d.keys()].filter((k) => en.has(k) && d.get(k) === en.get(k) && /[a-z]{4,}/i.test(en.get(k)) && !/^(JalSmriti|PDF|ha|m)$/.test(en.get(k)));
  console.log(`${lang}: ${d.size}/${en.size} keys, ${missing.length} missing, ${extra.length} unknown, ${holesWrong.length} placeholder mismatches, ${untranslated.length} identical to English`);
  for (const k of extra) console.log(`  unknown key: ${k}`);
  for (const k of holesWrong) console.log(`  placeholders differ: ${k}: "${d.get(k)}"`);
  if (missing.length && missing.length < 25) console.log(`  missing: ${missing.join(", ")}`);
  if (extra.length || holesWrong.length) bad++;
}
process.exit(bad ? 1 : 0);
