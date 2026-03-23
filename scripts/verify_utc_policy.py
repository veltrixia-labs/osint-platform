import os
import re
import sys

# Color codes for output
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RESET = "\033[0m"

def check_utc_policy(directory):
    """
    Scans Python files for naive datetime usage.
    """
    naive_patterns = [
        re.compile(r"datetime\.now\(\)"),
        re.compile(r"datetime\.utcnow\(\)"),
        re.compile(r"datetime\.today\(\)")
    ]
    
    # Exclude directories
    exclude_dirs = {".venv", "venv", ".git", "__pycache__", "node_modules", ".gemini"}
    
    violations = []
    
    print(f"Scanning {directory} for UTC policy violations...")
    
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        
        for file in files:
            if not file.endswith(".py"):
                continue
            
            # Skip this script
            if file == "verify_utc_policy.py":
                continue
                
            path = os.path.join(root, file)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    for i, line in enumerate(lines):
                        # Skip comments and strings (simplistic)
                        clean_line = line.split("#")[0].strip()
                        if not clean_line:
                            continue
                            
                        for pattern in naive_patterns:
                            if pattern.search(clean_line):
                                violations.append({
                                    "file": path,
                                    "line": i + 1,
                                    "content": line.strip(),
                                    "pattern": pattern.pattern
                                })
            except Exception as e:
                print(f"Error reading {path}: {e}")

    if violations:
        print(f"\n{RED}Found {len(violations)} UTC policy violations:{RESET}")
        for v in violations:
            print(f"- {YELLOW}{v['file']}:{v['line']}{RESET} -> {v['content']} (Matches: {v['pattern']})")
        return False
    else:
        print(f"\n{GREEN}No UTC policy violations found. All backend logic appears UTC-compliant.{RESET}")
        return True

if __name__ == "__main__":
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    success = check_utc_policy(base_dir)
    sys.exit(0 if success else 1)
