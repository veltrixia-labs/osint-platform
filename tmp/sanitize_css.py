import os

path = r"c:\RDTP project\Development\OSINT_analytics\web_dashboard\src\style.css"
try:
    with open(path, 'rb') as f:
        data = f.read()
    
    # Try decoding common encodings
    for enc in ['utf-8', 'utf-16', 'utf-16le', 'cp1252', 'shift-jis']:
        try:
            text = data.decode(enc)
            print(f"Decoded with {enc}")
            break
        except UnicodeDecodeError:
            continue
    else:
        text = data.decode('utf-8', errors='ignore')
        print("Decoded with utf-8 (ignoring errors)")

    # Clean up any NULL bytes often introduced by PowerShell UTF-16
    text = text.replace('\x00', '')

    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
    print("Rewritten as UTF-8.")
except Exception as e:
    print(f"Error: {e}")
