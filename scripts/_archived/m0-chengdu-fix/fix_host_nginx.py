#!/usr/bin/env python3
import re

CONF = "/etc/nginx/conf.d/xiu-ci.com.conf"

with open(CONF) as f:
    content = f.read()

# 1. Add proxy_intercept_errors off to location ~ ^/(api|modstore)/
# Find the block and add the directive after proxy_buffering off
pattern1 = r'(location ~ \^/\(api\|modstore\)/ \{[^}]*?proxy_buffering off;)'
match1 = re.search(pattern1, content, re.DOTALL)
if match1 and 'proxy_intercept_errors' not in match1.group(0):
    content = content.replace(match1.group(1), match1.group(1) + '\n        proxy_intercept_errors off;')
    print("Added proxy_intercept_errors to location ~ ^/(api|modstore)/")

# 2. Add proxy_intercept_errors off to location /api/ (the last one in the file)
# Find all location /api/ blocks and add to the one that doesn't have it
pattern2 = r'(location /api/ \{[^}]*?proxy_set_header X-Forwarded-Proto \$scheme;)'
match2 = re.search(pattern2, content, re.DOTALL)
if match2 and 'proxy_intercept_errors' not in match2.group(0):
    content = content.replace(match2.group(1), match2.group(1) + '\n        proxy_intercept_errors off;')
    print("Added proxy_intercept_errors to location /api/")

# 3. Add proxy_intercept_errors off to location ^~ /api/realtime/
pattern3 = r'(location \^~ /api/realtime/ \{[^}]*?proxy_buffering off;)'
match3 = re.search(pattern3, content, re.DOTALL)
if match3 and 'proxy_intercept_errors' not in match3.group(0):
    content = content.replace(match3.group(1), match3.group(1) + '\n        proxy_intercept_errors off;')
    print("Added proxy_intercept_errors to location ^~ /api/realtime/")

# 4. Add proxy_intercept_errors off to location /v1/
pattern4 = r'(location /v1/ \{[^}]*?proxy_buffering off;)'
match4 = re.search(pattern4, content, re.DOTALL)
if match4 and 'proxy_intercept_errors' not in match4.group(0):
    content = content.replace(match4.group(1), match4.group(1) + '\n        proxy_intercept_errors off;')
    print("Added proxy_intercept_errors to location /v1/")

with open(CONF, "w") as f:
    f.write(content)

print("Config updated. Testing...")
import subprocess
r = subprocess.run(["nginx", "-t"], capture_output=True, text=True)
if r.returncode == 0:
    subprocess.run(["nginx", "-s", "reload"])
    print("Nginx reloaded OK")
else:
    print(f"Nginx test failed: {r.stderr}")
