#!/usr/bin/env node
/**
 * image-edit.js — img2img via the fecify-site-manager-v6 image provider config (OpenAI-compatible /v1/images/edits).
 *
 * node scripts/image-edit.js --ref <image> --out <out.webp> --prompt "<text>" [--size 1024x1024] [--quality low|medium|high]
 *                            [--manager-skill <dir>]
 *
 * The API key is read through the manager skill's image-client getConfig(); it is never passed as an argument.
 * Output is cropped/compressed to WebP by the manager skill's cropAndCompress.
 */
const fs = require('fs');
const path = require('path');
const os = require('os');

function arg(name, def) {
  const i = process.argv.indexOf(name);
  return i >= 0 ? process.argv[i + 1] : def;
}
const ref = arg('--ref'), out = arg('--out'), prompt = arg('--prompt');
const size = arg('--size', '1024x1024'), quality = arg('--quality', 'medium');
if (!ref || !out || !prompt) { console.error('usage: --ref <image> --out <out.webp> --prompt <text>'); process.exit(2); }

const candidates = [arg('--manager-skill'), process.env.FECIFY_SKILL_DIR,
  path.join(os.homedir(), '.claude', 'skills', 'fecify-site-manager-v6'),
  path.join(os.homedir(), '.codex', 'skills', 'fecify-site-manager-v6')].filter(Boolean);
const manager = candidates.find((d) => fs.existsSync(path.join(d, 'scripts', 'image-gen', 'image-client.js')));
if (!manager) { console.error('fecify-site-manager-v6 not found'); process.exit(2); }
const client = require(path.join(manager, 'scripts', 'image-gen', 'image-client.js'));
const cfg = client.getConfig({});
if (!cfg.apiKey || !cfg.apiBase) { console.error('image provider not configured: ' + (cfg.reason || '')); process.exit(2); }

const [w, h] = size.split('x').map((n) => parseInt(n, 10));
const boundary = '----cjbuild' + Date.now().toString(16);
const file = fs.readFileSync(ref);
const ext = path.extname(ref).toLowerCase();
const mime = ext === '.png' ? 'image/png' : ext === '.webp' ? 'image/webp' : 'image/jpeg';
function field(name, value) { return Buffer.from(`--${boundary}\r\nContent-Disposition: form-data; name="${name}"\r\n\r\n${value}\r\n`); }
const body = Buffer.concat([
  field('model', cfg.model), field('prompt', prompt), field('n', '1'), field('size', size), field('quality', quality),
  Buffer.from(`--${boundary}\r\nContent-Disposition: form-data; name="image"; filename="${path.basename(ref)}"\r\nContent-Type: ${mime}\r\n\r\n`),
  file, Buffer.from(`\r\n--${boundary}--\r\n`),
]);

(async () => {
  const url = cfg.apiBase.replace(/\/+$/, '') + '/v1/images/edits';
  const res = await fetch(url, { method: 'POST', headers: { Authorization: 'Bearer ' + cfg.apiKey, 'Content-Type': 'multipart/form-data; boundary=' + boundary }, body });
  const text = await res.text();
  if (!res.ok) { console.error('edit failed HTTP ' + res.status + ': ' + text.slice(0, 400)); process.exit(1); }
  let json;
  try { json = JSON.parse(text); } catch (e) { console.error('non-JSON response: ' + text.slice(0, 200)); process.exit(1); }
  const item = (json.data || [])[0] || {};
  let buf;
  if (item.b64_json) buf = Buffer.from(item.b64_json, 'base64');
  else if (item.url) buf = Buffer.from(await (await fetch(item.url)).arrayBuffer());
  else { console.error('no image in response: ' + text.slice(0, 300)); process.exit(1); }
  fs.mkdirSync(path.dirname(path.resolve(out)), { recursive: true });
  const tmp = out.replace(/\.\w+$/, '_tmp.png');
  fs.writeFileSync(tmp, buf);
  client.cropAndCompress(tmp, out, w, h, 85);
  try { fs.unlinkSync(tmp); } catch (_) {}
  console.log(JSON.stringify({ ok: true, out: path.resolve(out), bytes: fs.statSync(out).size }));
})().catch((e) => { console.error(e.message); process.exit(1); });
