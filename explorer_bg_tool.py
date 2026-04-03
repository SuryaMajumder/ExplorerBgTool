"""
Explorer Background Tool - Browser-based GUI
Run this script as Administrator, then your browser opens automatically.
Requires: pip install pillow
"""

import os, sys, json, base64, subprocess, shutil, threading, webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
from PIL import Image, ImageEnhance, ImageFilter

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "bg_config.json")
PORT        = 57821

DEFAULT_CONFIG = {
    "image_path": "", "brightness": 1.0, "blur": 0,
    "opacity": 255,   "pos_type": 3,     "dll_path": "",
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            cfg = json.load(open(CONFIG_FILE))
            for k, v in DEFAULT_CONFIG.items(): cfg.setdefault(k, v)
            return cfg
        except: pass
    return dict(DEFAULT_CONFIG)

def save_config(cfg):
    json.dump(cfg, open(CONFIG_FILE, "w"), indent=2)

def process_image(src, brightness, blur, opacity):
    img = Image.open(src).convert("RGBA")
    rgb = ImageEnhance.Brightness(img.convert("RGB")).enhance(brightness)
    if blur > 0: rgb = rgb.filter(ImageFilter.GaussianBlur(radius=blur))
    rgba = rgb.convert("RGBA")
    r,g,b,a = rgba.split()
    a = a.point(lambda p: int(p * opacity / 255))
    return Image.merge("RGBA", (r,g,b,a))

def image_to_base64(path, brightness, blur, opacity, max_size=(800,500)):
    import io
    img = process_image(path, brightness, blur, opacity)
    img.thumbnail(max_size, Image.LANCZOS)
    bg = Image.new("RGBA", img.size, (15, 15, 25, 255))
    bg.paste(img, (0,0), img)
    buf = io.BytesIO()
    bg.convert("RGB").save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()

def write_ini(ini_path, pos_type, image_folder):
    open(ini_path, "w").write(f"""[load]
folderExt=false
noerror=false
[image]
random=false
custom=false
posType={pos_type}
imgAlpha=255
folder={image_folder}
""")

def register_dll(dll_path):
    r = subprocess.run(["regsvr32", "/s", dll_path], capture_output=True)
    return r.returncode == 0

def unregister_dll(dll_path):
    r = subprocess.run(["regsvr32", "/s", "/u", dll_path], capture_output=True)
    return r.returncode == 0

def restart_explorer():
    subprocess.run(["taskkill", "/f", "/im", "explorer.exe"], capture_output=True)
    subprocess.Popen(["explorer.exe"])

def is_admin():
    try:
        import ctypes; return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except: return False

# ── HTML UI ───────────────────────────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Explorer Background Tool</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {
    --bg:     #0d0d14;
    --card:   #13131f;
    --border: #1e1e30;
    --acc:    #b48ef7;
    --acc2:   #7ee8c8;
    --err:    #f87272;
    --ok:     #7ee8a2;
    --fg:     #e2e0f0;
    --muted:  #5a5870;
    --slider: #2a2a40;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'Syne', sans-serif;
    background: var(--bg);
    color: var(--fg);
    min-height: 100vh;
    padding: 32px 24px;
  }
  body::before {
    content: '';
    position: fixed; inset: 0;
    background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.75' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.04'/%3E%3C/svg%3E");
    pointer-events: none; z-index: 0;
  }
  .wrap { max-width: 960px; margin: 0 auto; position: relative; z-index: 1; }
  header { display: flex; align-items: center; gap: 16px; margin-bottom: 36px; }
  .logo { font-size: 28px; }
  h1 { font-size: 26px; font-weight: 800; letter-spacing: -0.5px; }
  h1 span { color: var(--acc); }
  .admin-badge {
    margin-left: auto; font-family: 'DM Mono', monospace;
    font-size: 11px; padding: 5px 12px; border-radius: 99px;
    border: 1px solid; letter-spacing: 0.5px;
  }
  .admin-badge.ok  { border-color: var(--ok);  color: var(--ok); }
  .admin-badge.err { border-color: var(--err); color: var(--err); }
  .grid { display: grid; grid-template-columns: 1fr 380px; gap: 20px; }
  .card {
    background: var(--card); border: 1px solid var(--border);
    border-radius: 16px; padding: 24px;
  }
  .card-title {
    font-size: 11px; font-weight: 700; letter-spacing: 2px;
    text-transform: uppercase; color: var(--muted); margin-bottom: 16px;
  }
  .preview-wrap { margin-bottom: 20px; }
  #preview {
    width: 100%; aspect-ratio: 16/9; border-radius: 12px;
    background: #0a0a12; border: 1px solid var(--border);
    display: flex; align-items: center; justify-content: center;
    color: var(--muted); font-size: 13px; overflow: hidden;
  }
  #preview img { width: 100%; height: 100%; object-fit: cover; border-radius: 12px; }
  #preview.empty::after { content: 'No image selected'; }
  .file-row { display: flex; gap: 8px; align-items: center; }
  .file-path {
    flex: 1; background: #0d0d18; border: 1px solid var(--border);
    border-radius: 8px; padding: 9px 14px;
    font-family: 'DM Mono', monospace; font-size: 11px; color: var(--muted);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .btn {
    padding: 9px 18px; border-radius: 8px; border: none;
    font-family: 'Syne', sans-serif; font-weight: 700; font-size: 13px;
    cursor: pointer; transition: all 0.15s; white-space: nowrap;
  }
  .btn-acc  { background: var(--acc);  color: #0d0d14; }
  .btn-acc:hover  { filter: brightness(1.15); transform: translateY(-1px); }
  .btn-dim  { background: var(--border); color: var(--fg); }
  .btn-dim:hover  { background: #252538; }
  .btn-ok   { background: var(--ok);  color: #0d0d14; }
  .btn-ok:hover   { filter: brightness(1.1); transform: translateY(-1px); }
  .btn-err  { background: var(--err); color: #0d0d14; }
  .btn-err:hover  { filter: brightness(1.1); }
  .btn-blue { background: #7eb8f8; color: #0d0d14; }
  .btn-blue:hover { filter: brightness(1.1); transform: translateY(-1px); }
  .btn:active { transform: translateY(0) !important; filter: brightness(0.95) !important; }
  .slider-row { margin-bottom: 20px; }
  .slider-header { display: flex; justify-content: space-between; margin-bottom: 8px; }
  .slider-label { font-size: 13px; font-weight: 600; color: var(--fg); }
  .slider-val { font-family: 'DM Mono', monospace; font-size: 12px; color: var(--acc); font-weight: 500; }
  input[type=range] {
    -webkit-appearance: none; width: 100%; height: 4px;
    background: var(--slider); border-radius: 2px; outline: none;
  }
  input[type=range]::-webkit-slider-thumb {
    -webkit-appearance: none; width: 16px; height: 16px;
    border-radius: 50%; background: var(--acc); cursor: pointer;
    box-shadow: 0 0 8px rgba(180,142,247,0.5); transition: transform 0.1s;
  }
  input[type=range]::-webkit-slider-thumb:hover { transform: scale(1.2); }
  .pos-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
  .pos-btn {
    padding: 8px 4px; border-radius: 8px; border: 1px solid var(--border);
    background: #0d0d18; color: var(--muted); font-family: 'Syne', sans-serif;
    font-size: 11px; font-weight: 600; cursor: pointer;
    transition: all 0.15s; text-align: center;
  }
  .pos-btn:hover { border-color: var(--acc); color: var(--acc); }
  .pos-btn.active { border-color: var(--acc); background: rgba(180,142,247,0.12); color: var(--acc); }
  .dll-row { display: flex; gap: 8px; margin-top: 8px; }
  .dll-path {
    flex: 1; background: #0d0d18; border: 1px solid var(--border);
    border-radius: 8px; padding: 9px 14px;
    font-family: 'DM Mono', monospace; font-size: 11px; color: var(--muted);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .actions { display: flex; gap: 10px; margin-top: 20px; flex-wrap: wrap; }
  #toast {
    position: fixed; bottom: 32px; left: 50%; transform: translateX(-50%);
    padding: 12px 24px; border-radius: 99px; font-size: 13px; font-weight: 600;
    pointer-events: none; opacity: 0; transition: opacity 0.3s; z-index: 999;
  }
  #toast.show { opacity: 1; }
  #toast.ok   { background: var(--ok);  color: #0d0d14; }
  #toast.err  { background: var(--err); color: #fff; }
  #toast.info { background: var(--acc); color: #0d0d14; }
  .spin { display: inline-block; animation: spin 0.8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  hr { border: none; border-top: 1px solid var(--border); margin: 20px 0; }
  .hint { font-size: 11px; color: var(--muted); line-height: 1.6; margin-top: 6px; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="logo">🖼️</div>
    <h1>Explorer <span>Background</span> Tool</h1>
    <div class="admin-badge" id="adminBadge">checking...</div>
  </header>
  <div class="grid">
    <div>
      <div class="card preview-wrap">
        <div class="card-title">Live Preview</div>
        <div id="preview" class="empty"></div>
      </div>
      <div class="card">
        <div class="card-title">Image</div>
        <div class="file-row">
          <div class="file-path" id="imgPathLabel">No image selected</div>
          <button class="btn btn-acc" onclick="pickImage()">Browse</button>
        </div>
        <p class="hint">Supports PNG, JPG, WEBP, BMP</p>
        <hr>
        <div class="card-title">Adjustments</div>
        <div class="slider-row">
          <div class="slider-header">
            <span class="slider-label">✨ Brightness</span>
            <span class="slider-val" id="brightVal">1.0×</span>
          </div>
          <input type="range" id="brightness" min="10" max="200" value="100"
                 oninput="onSlider()" onchange="updatePreview()">
        </div>
        <div class="slider-row">
          <div class="slider-header">
            <span class="slider-label">🌫️ Blur / Haze</span>
            <span class="slider-val" id="blurVal">0px</span>
          </div>
          <input type="range" id="blur" min="0" max="20" value="0"
                 oninput="onSlider()" onchange="updatePreview()">
        </div>
        <div class="slider-row">
          <div class="slider-header">
            <span class="slider-label">💧 Opacity</span>
            <span class="slider-val" id="opacVal">255</span>
          </div>
          <input type="range" id="opacity" min="0" max="255" value="255"
                 oninput="onSlider()" onchange="updatePreview()">
        </div>
      </div>
    </div>
    <div style="display:flex;flex-direction:column;gap:20px;">
      <div class="card">
        <div class="card-title">Image Position</div>
        <div class="pos-grid" id="posGrid">
          <button class="pos-btn" onclick="setPos(0)">↖ Top Left</button>
          <button class="pos-btn" onclick="setPos(1)">↗ Top Right</button>
          <button class="pos-btn" onclick="setPos(2)">↙ Bot Left</button>
          <button class="pos-btn active" onclick="setPos(3)">↘ Bot Right</button>
          <button class="pos-btn" onclick="setPos(4)">⊙ Center</button>
          <button class="pos-btn" onclick="setPos(5)">⤢ Stretch</button>
          <button class="pos-btn" style="grid-column:span 3" onclick="setPos(6)">⊞ Zoom & Fill</button>
        </div>
      </div>
      <div class="card">
        <div class="card-title">explorerTool DLL</div>
        <p class="hint">Select your ExplorerBgTool.dll file</p>
        <div class="dll-row">
          <div class="dll-path" id="dllPathLabel">Not selected</div>
          <button class="btn btn-dim" onclick="pickDll()">Browse</button>
        </div>
      </div>
      <div class="card">
        <div class="card-title">Actions</div>
        <div class="actions" style="flex-direction:column;">
          <button class="btn btn-ok" style="width:100%;padding:14px;" onclick="applyBg()">
            ✅ &nbsp;Apply to Explorer
          </button>
          <button class="btn btn-blue" style="width:100%" onclick="restartExp()">
            🔄 &nbsp;Restart Explorer
          </button>
          <button class="btn btn-err" style="width:100%" onclick="uninstall()">
            ❌ &nbsp;Uninstall Background
          </button>
        </div>
        <p class="hint" style="margin-top:12px;">
          After applying, click Restart Explorer or reopen your File Explorer windows.
        </p>
      </div>
    </div>
  </div>
</div>
<div id="toast"></div>
<script>
let cfg = {};
let previewTimer = null;

async function api(endpoint, params={}) {
  const q = new URLSearchParams(params).toString();
  const r = await fetch(`/api/${endpoint}${q ? '?'+q : ''}`);
  return r.json();
}

async function init() {
  cfg = await api('config');
  const badge = document.getElementById('adminBadge');
  if (cfg.is_admin) {
    badge.textContent = '✓ Administrator';
    badge.className = 'admin-badge ok';
  } else {
    badge.textContent = '⚠ Not Admin — Apply won\'t work';
    badge.className = 'admin-badge err';
  }
  document.getElementById('brightness').value = Math.round(cfg.brightness * 100);
  document.getElementById('blur').value = cfg.blur;
  document.getElementById('opacity').value = cfg.opacity;
  onSlider();
  if (cfg.image_path) {
    document.getElementById('imgPathLabel').textContent = cfg.image_path.split(/[\\/]/).pop();
    updatePreview();
  }
  if (cfg.dll_path)
    document.getElementById('dllPathLabel').textContent = cfg.dll_path.split(/[\\/]/).pop();
  setPos(cfg.pos_type ?? 3);
}

function onSlider() {
  const b  = document.getElementById('brightness').value;
  const bl = document.getElementById('blur').value;
  const op = document.getElementById('opacity').value;
  document.getElementById('brightVal').textContent = (b/100).toFixed(1) + '×';
  document.getElementById('blurVal').textContent   = bl + 'px';
  document.getElementById('opacVal').textContent   = op;
}

function updatePreview() {
  if (!cfg.image_path) return;
  clearTimeout(previewTimer);
  previewTimer = setTimeout(async () => {
    const b  = document.getElementById('brightness').value / 100;
    const bl = document.getElementById('blur').value;
    const op = document.getElementById('opacity').value;
    const prev = document.getElementById('preview');
    prev.innerHTML = '<span class="spin">⟳</span>';
    prev.classList.remove('empty');
    const res = await api('preview', { brightness: b, blur: bl, opacity: op });
    if (res.img) {
      prev.innerHTML = `<img src="data:image/jpeg;base64,${res.img}">`;
    } else {
      prev.innerHTML = '';
      prev.classList.add('empty');
    }
  }, 300);
}

let currentPos = 3;
function setPos(n) {
  currentPos = n;
  document.querySelectorAll('.pos-btn').forEach((b,i) => {
    b.classList.toggle('active', i === n);
  });
}

async function pickImage() {
  const r = await api('pick_image');
  if (r.path) {
    cfg.image_path = r.path;
    document.getElementById('imgPathLabel').textContent = r.path.split(/[\\/]/).pop();
    document.getElementById('preview').classList.remove('empty');
    updatePreview();
    toast('Image selected!', 'info');
  }
}

async function pickDll() {
  const r = await api('pick_dll');
  if (r.path) {
    cfg.dll_path = r.path;
    document.getElementById('dllPathLabel').textContent = r.path.split(/[\\/]/).pop();
    toast('DLL selected!', 'info');
  }
}

async function applyBg() {
  const b  = document.getElementById('brightness').value / 100;
  const bl = document.getElementById('blur').value;
  const op = document.getElementById('opacity').value;
  const r  = await api('apply', { brightness: b, blur: bl, opacity: op, pos_type: currentPos });
  toast(r.msg, r.ok ? 'ok' : 'err');
}

async function restartExp() {
  if (!confirm('This will briefly close all Explorer windows. Continue?')) return;
  const r = await api('restart_explorer');
  toast(r.msg, 'info');
}

async function uninstall() {
  if (!confirm('Remove background from Explorer?')) return;
  const r = await api('uninstall');
  toast(r.msg, r.ok ? 'ok' : 'err');
}

function toast(msg, type='info') {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = `show ${type}`;
  setTimeout(() => t.className = '', 3500);
}

init();
</script>
</body>
</html>"""

# ── HTTP Handler ──────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    cfg = load_config()

    def log_message(self, *a): pass

    def send_json(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}

        if parsed.path == "/":
            body = HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed.path == "/api/config":
            self.send_json({**self.cfg, "is_admin": is_admin()})

        elif parsed.path == "/api/preview":
            if not self.cfg.get("image_path") or not os.path.exists(self.cfg["image_path"]):
                self.send_json({"img": None}); return
            try:
                b64 = image_to_base64(
                    self.cfg["image_path"],
                    float(params.get("brightness", 1.0)),
                    int(params.get("blur", 0)),
                    int(params.get("opacity", 255)),
                )
                self.send_json({"img": b64})
            except Exception as e:
                self.send_json({"img": None, "error": str(e)})

        elif parsed.path == "/api/pick_image":
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)
            path = filedialog.askopenfilename(
                title="Pick background image",
                filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.webp"), ("All", "*.*")]
            )
            root.destroy()
            if path:
                self.cfg["image_path"] = path
                save_config(self.cfg)
            self.send_json({"path": path or ""})

        elif parsed.path == "/api/pick_dll":
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)
            path = filedialog.askopenfilename(
                title="Select ExplorerBgTool.dll",
                filetypes=[("DLL", "*.dll"), ("All", "*.*")]
            )
            root.destroy()
            if path:
                self.cfg["dll_path"] = path
                save_config(self.cfg)
            self.send_json({"path": path or ""})

        elif parsed.path == "/api/apply":
            img  = self.cfg.get("image_path", "")
            dll  = self.cfg.get("dll_path", "")
            b    = float(params.get("brightness", 1.0))
            bl   = int(params.get("blur", 0))
            op   = int(params.get("opacity", 255))
            pos  = int(params.get("pos_type", 3))
            self.cfg.update({"brightness": b, "blur": bl, "opacity": op, "pos_type": pos})
            save_config(self.cfg)
            if not img or not os.path.exists(img):
                self.send_json({"ok": False, "msg": "No image selected!"}); return
            if not dll or not os.path.exists(dll):
                self.send_json({"ok": False, "msg": "DLL not selected!"}); return
            try:
                dll_dir   = os.path.dirname(dll)
                image_dir = os.path.join(dll_dir, "image")
                ini_path  = os.path.join(dll_dir, "config.ini")
                os.makedirs(image_dir, exist_ok=True)
                img_out = process_image(img, b, bl, op)
                img_out.save(os.path.join(image_dir, "bg_custom.png"), "PNG")
                write_ini(ini_path, pos, image_dir)
                ok = register_dll(dll)
                if ok:
                    self.send_json({"ok": True,  "msg": "Applied! Now restart Explorer."})
                else:
                    self.send_json({"ok": False, "msg": "regsvr32 failed — are you running as Admin?"})
            except PermissionError:
                self.send_json({"ok": False, "msg": "Permission denied — run as Administrator!"})
            except Exception as e:
                self.send_json({"ok": False, "msg": f"Error: {e}"})

        elif parsed.path == "/api/restart_explorer":
            restart_explorer()
            self.send_json({"msg": "Explorer restarted!"})

        elif parsed.path == "/api/uninstall":
            dll = self.cfg.get("dll_path", "")
            if not dll or not os.path.exists(dll):
                self.send_json({"ok": False, "msg": "DLL not selected!"}); return
            ok = unregister_dll(dll)
            self.send_json({"ok": ok, "msg": "Uninstalled! Restart Explorer." if ok else "Failed — run as Admin?"})

        else:
            self.send_response(404); self.end_headers()


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}"
    print(f"\n  Explorer Background Tool running at {url}")
    print(f"  Admin: {is_admin()}")
    print(f"  Press Ctrl+C to stop.\n")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
