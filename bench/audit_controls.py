"""
Audit all HTML controls in web/static/index.html and check their event bindings in web/static/app.js
"""
import re
from pathlib import Path

html = Path("web/static/index.html").read_text(encoding="utf-8")
js = Path("web/static/app.js").read_text(encoding="utf-8")

# Extract all input, select, button, textarea, a tags
tags = re.findall(r'(<(?:input|select|button|textarea|a)[^>]*>)', html, re.IGNORECASE)

print(f"Total interactive tags found: {len(tags)}")

controls = []
for tag in tags:
    id_match = re.search(r'id=["\']([^"\']+)["\']', tag)
    type_match = re.search(r'type=["\']([^"\']+)["\']', tag)
    tag_name = re.match(r'<(\w+)', tag).group(1).lower()
    ctrl_id = id_match.group(1) if id_match else None
    ctrl_type = type_match.group(1) if type_match else ""
    disabled = "disabled" in tag.lower()
    readonly = "readonly" in tag.lower()
    onclick = "onclick" in tag.lower()

    wired = False
    if ctrl_id and ctrl_id in js:
        wired = True
    elif onclick:
        wired = True

    controls.append({
        "tag": tag_name,
        "id": ctrl_id,
        "type": ctrl_type,
        "disabled": disabled,
        "readonly": readonly,
        "wired": wired,
        "raw": tag.strip()
    })

print("\n=== UNWIRED CONTROLS (POTENTIAL FAKE CONTROLS) ===")
unwired_count = 0
for c in controls:
    if not c["wired"] and not c["disabled"] and not c["readonly"] and c["tag"] in ["input", "select", "button", "textarea"]:
        unwired_count += 1
        print(f"  [{c['tag']}] id={c['id']} type={c['type']}: {c['raw']}")

print(f"\nTotal potential unwired: {unwired_count}")

print("\n=== ALL CONTROLS DETAILED LIST ===")
for c in controls:
    status = "WIRED" if c["wired"] else ("DISABLED/READONLY" if (c["disabled"] or c["readonly"]) else "UNWIRED_ACTIVE")
    print(f"{status:18} | {c['tag']:8} | id={str(c['id']):28} | type={c['type']}")

# Check all getElementById calls in JS against HTML
js_ids = re.findall(r'document\.getElementById\(["\']([^"\']+)["\']\)', js)
print(f"\nTotal getElementById calls in JS: {len(js_ids)}")
missing_ids = [jid for jid in set(js_ids) if f'id="{jid}"' not in html and f"id='{jid}'" not in html]
print(f"IDs queried in JS but missing in HTML: {missing_ids}")
