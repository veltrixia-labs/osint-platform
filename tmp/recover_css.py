import os

path = r"c:\RDTP project\Development\OSINT_analytics\web_dashboard\src\style.css"
with open(path, 'rb') as f:
    data = f.read()

# Try to detect if it's UTF-16LE (PowerShell default)
try:
    # Most likely it's UTF-16LE
    text = data.decode('utf-16-le')
    print("Decoded as UTF-16LE")
except:
    try:
        text = data.decode('utf-8')
        print("Decoded as UTF-8")
    except:
        text = data.decode('utf-8', errors='ignore')
        print("Decoded as UTF-8 (ignored errors)")

# Clean up NULL bytes if it was misinterpreted
text = text.replace('\x00', '')

# If it starts with a BOM, remove it
if text.startswith('\ufeff'):
    text = text[1:]

with open(path, 'w', encoding='utf-8', newline='\n') as f:
    f.write(text)
print("Sanitized and written as UTF-8.")
