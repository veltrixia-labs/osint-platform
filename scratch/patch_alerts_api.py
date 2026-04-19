import sys
import os

target_file = r"c:\RDTP project\Development\OSINT_analytics\api\routes\alerts.py"

with open(target_file, 'r', encoding='utf-8') as f:
    content = f.read()

# First block replacement
target1 = """            "country": a.metadata_json.get("country") if a.metadata_json else None
        }"""
replacement1 = """            "country": a.metadata_json.get("country") if a.metadata_json else None,
            "backbone_discovery_status": a.metadata_json.get("backbone_discovery_status", "idle") if a.metadata_json else "idle"
        }"""

# Second block replacement (live alerts)
target2 = """            "country": a.metadata_json.get("country") if a.metadata_json else None
        }"""
# Wait, target1 and target2 might be identical. Let's see.
# I'll use replace with count=2 to do both if they match.

if target1 in content:
    print("Found target block. Applying replacements...")
    new_content = content.replace(target1, replacement1)
    with open(target_file, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print("Successfully updated api/routes/alerts.py")
else:
    print("Could not find target block. Checking exact content...")
    # Maybe whitespace issue?
    import re
    # Try more flexible approach
    pattern = re.compile(r'\"country\":\s+a\.metadata_json\.get\(\"country\"\)\s+if\s+a\.metadata_json\s+else\s+None\n\s+\}')
    if pattern.search(content):
        print("Found with regex!")
    else:
        print("Regex also failed. Showing a small snippet of the file.")
        start = content.find('"country"')
        if start != -1:
            print(f"DEBUG: '{content[start:start+100]}'")
