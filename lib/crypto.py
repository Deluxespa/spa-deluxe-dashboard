"""
AES-256-GCM Verschlüsselung für das Dashboard-HTML.

Kompatibel zum client-seitigen Entschlüsseler im Original-Tool:

    const keyData = await crypto.subtle.digest('SHA-256', encoder.encode(password));
    const cryptoKey = await crypto.subtle.importKey('raw', keyData, 'AES-GCM', false, ['decrypt']);
    const decrypted = await crypto.subtle.decrypt({name:'AES-GCM', iv:nonce}, cryptoKey, ciphertext);

D.h.:
  - Schlüssel = SHA-256(passwort_utf8)  (32 Byte -> AES-256)
  - Nonce/IV  = 12 zufällige Bytes (Web Crypto AES-GCM Default)
  - Ciphertext-Layout wie bei Web Crypto: ciphertext || 16-Byte-Auth-Tag angehängt
  - beides base64url-kodiert (- statt +, _ statt /, ohne Padding) im JSON {"n":..., "c":...}
"""
import base64
import hashlib
import json
import os

from Crypto.Cipher import AES


def _b64url(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii").replace("+", "-").replace("/", "_").rstrip("=")


def encrypt_html(html: str, password: str) -> dict:
    """Verschlüsselt HTML-Text und gibt das {"n":..., "c":...}-Dict zurück,
    das 1:1 in <script id="encData" type="application/json"> eingebettet wird."""
    key = hashlib.sha256(password.encode("utf-8")).digest()
    nonce = os.urandom(12)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    ciphertext, tag = cipher.encrypt_and_digest(html.encode("utf-8"))
    return {"n": _b64url(nonce), "c": _b64url(ciphertext + tag)}


def build_gate_html(enc_data: dict, title: str = "Marketing Intelligence Forecast") -> str:
    """Baut die äußere Passwort-Gate-Seite (das, was ohne Passwort sichtbar ist),
    identisch zum Original-Mechanismus: Passwort kommt per ?k= oder #k= aus der URL,
    sonst Eingabefeld. Der verschlüsselte Inhalt wird per iframe/Blob eingeblendet."""
    enc_json = json.dumps(enc_data, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0f172a;color:#e2e8f0;
  min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}}
.gate{{background:#1e293b;border:1px solid #334155;border-radius:14px;padding:36px 32px;max-width:360px;width:100%;text-align:center}}
.gate .lock{{font-size:32px;margin-bottom:10px}}
.gate h1{{font-size:16px;font-weight:600;margin-bottom:6px}}
.gate p{{font-size:13px;color:#94a3b8;margin-bottom:18px}}
.gate input{{width:100%;padding:10px 12px;border-radius:8px;border:1px solid #334155;background:#0f172a;color:#e2e8f0;font-size:14px;margin-bottom:10px}}
.gate button{{width:100%;padding:10px 12px;border-radius:8px;border:none;background:#f59e0b;color:#0f172a;font-weight:600;font-size:14px;cursor:pointer}}
.gate button:hover{{background:#d97706}}
#error{{display:none;color:#f87171;font-size:12px;margin-top:10px}}
</style>
</head>
<body>
<div class="gate">
  <div class="lock">🔒</div>
  <h1>{title}</h1>
  <p>Zugriff nur mit Passwort</p>
  <input type="password" id="keyInput" placeholder="Passwort" autofocus>
  <button onclick="unlock()">Öffnen</button>
  <div id="error">Falsches Passwort</div>
</div>
<script id="encData" type="application/json">{enc_json}</script>
<script>
function getEncData() {{
  return JSON.parse(document.getElementById('encData').textContent);
}}
function b64ToBytes(b64) {{
  let s = b64.replace(/-/g, '+').replace(/_/g, '/');
  while (s.length % 4) s += '=';
  const bin = atob(s);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
}}
async function tryDecrypt(password) {{
  try {{
    const enc = getEncData();
    const encoder = new TextEncoder();
    const keyData = await crypto.subtle.digest('SHA-256', encoder.encode(password));
    const cryptoKey = await crypto.subtle.importKey('raw', keyData, 'AES-GCM', false, ['decrypt']);
    const nonce = b64ToBytes(enc.n);
    const ciphertext = b64ToBytes(enc.c);
    const decrypted = await crypto.subtle.decrypt({{name:'AES-GCM', iv:nonce}}, cryptoKey, ciphertext);
    const html = new TextDecoder().decode(decrypted);
    var blob = new Blob([html], {{type: 'text/html'}});
    var url = URL.createObjectURL(blob);
    var iframe = document.createElement('iframe');
    iframe.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;border:none;z-index:9999;';
    document.body.innerHTML = '';
    document.body.appendChild(iframe);
    iframe.src = url;
  }} catch (e) {{
    const err = document.getElementById('error');
    if (err) {{ err.style.display = 'block'; }}
    const inp = document.getElementById('keyInput');
    if (inp) {{ inp.value = ''; inp.focus(); }}
  }}
}}
function unlock() {{
  const key = document.getElementById('keyInput').value;
  if (key) tryDecrypt(key);
}}
document.getElementById('keyInput').addEventListener('keypress', function(e) {{
  if (e.key === 'Enter') unlock();
}});
(function() {{
  var key = new URLSearchParams(window.location.search).get('k');
  if (!key && window.location.hash.indexOf('#k=') === 0) {{
    key = decodeURIComponent(window.location.hash.substring(3));
  }}
  if (key) tryDecrypt(key);
}})();
</script>
</body>
</html>
"""


def decrypt_html(enc_data: dict, password: str) -> str:
    """Nur für lokale Tests: entschlüsselt wieder, um zu prüfen, dass encrypt/decrypt zusammenpassen."""
    def _b64url_decode(s: str) -> bytes:
        s = s.replace("-", "+").replace("_", "/")
        pad = (-len(s)) % 4
        return base64.b64decode(s + "=" * pad)

    key = hashlib.sha256(password.encode("utf-8")).digest()
    nonce = _b64url_decode(enc_data["n"])
    blob = _b64url_decode(enc_data["c"])
    ciphertext, tag = blob[:-16], blob[-16:]
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    return cipher.decrypt_and_verify(ciphertext, tag).decode("utf-8")


if __name__ == "__main__":
    # Selbsttest
    sample = "<h1>Hallo Dashboard</h1>"
    enc = encrypt_html(sample, "test-passwort-123")
    assert decrypt_html(enc, "test-passwort-123") == sample
    print("crypto.py Selbsttest OK")
