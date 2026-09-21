import os
import re

print("=== SCANNING DOCS FOR LEAKED SECRETS ===")
secret_patterns = [
    re.compile(r'(password|secret|token|api_key|private_key)\s*[:=]\s*["\'][^"\']{10,}["\']', re.I),
    re.compile(r'-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----'),
]
violations = []
for root, dirs, files in os.walk('docs'):
    for f in files:
        if f.endswith('.md'):
            path = os.path.join(root, f)
            with open(path, 'r', encoding='utf-8', errors='ignore') as fp:
                for line_no, line in enumerate(fp, 1):
                    line_lower = line.lower()
                    if any(x in line_lower for x in ['example', 'placeholder', 'secret123', 'token_xyz', 'auth999', 'test_', 'dummy', 'redacted']):
                        continue
                    for pat in secret_patterns:
                        m = pat.search(line)
                        if m:
                            val = m.group(0).lower()
                            if 'http://' in val or 'https://' in val or 'redacted' in val:
                                continue
                            violations.append((path, line_no, line.strip()))

if violations:
    print(f"VIOLATIONS FOUND: {len(violations)}")
    for v in violations[:5]:
        print(v)
else:
    print("ZERO SECRET VIOLATIONS FOUND. All docs clean.")

print("\n=== CHECKING INTERNAL MARKDOWN FILE LINKS ===")
link_pattern = re.compile(r'\[([^\]]+)\]\((file:///[^\)]+)\)')
broken_links = []
total_links = 0
for root, dirs, files in os.walk('docs'):
    for f in files:
        if f.endswith('.md'):
            path = os.path.join(root, f)
            with open(path, 'r', encoding='utf-8', errors='ignore') as fp:
                content = fp.read()
                for match in link_pattern.finditer(content):
                    total_links += 1
                    target_url = match.group(2)
                    local_target = target_url.split('#')[0].replace('file:///', '').replace('/', os.sep)
                    if not os.path.exists(local_target):
                        broken_links.append((path, match.group(1), target_url, local_target))

print(f"Total file:// links checked: {total_links}")
if broken_links:
    print(f"BROKEN LINKS FOUND: {len(broken_links)}")
    for b in broken_links:
        print("In:", b[0], "Label:", b[1], "Target:", b[2])
else:
    print("ALL FILE LINKS RESOLVED SUCCESSFULLY.")
