import os

file_path = "c:\\RDTP project\\Development\\OSINT_analytics\\web_dashboard\\src\\main.ts"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# The python script wrote split('\n') instead of split('\\n')
# We need to replace it. A literal newline inside split('') looks like:
bad_str = "split('\n')"
good_str = "split('\\n')"

content = content.replace(bad_str, good_str)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)
print("Fix applied")
