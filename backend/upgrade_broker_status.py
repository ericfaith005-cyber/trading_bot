from pathlib import Path

path = Path("server.py")
text = path.read_text(encoding="utf-8")

old = '"broker": "Exness / MT5 (not connected)",'
new = '"broker": "Exness / MT5 (read-only connection)",'

if old not in text:
    raise SystemExit(
        "Broker status line was not found. No changes were made."
    )

text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")

print("Broker status label upgraded successfully.")