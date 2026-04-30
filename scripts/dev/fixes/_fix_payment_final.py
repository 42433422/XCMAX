import os

file = r'E:\FHD\frontend\src\views\AIEcosystemView.vue'

with open(file, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 删除残留的第21-24行 (不完整的内容)
new_lines = []
for i, line in enumerate(lines, 1):
    if 21 <= i <= 24:
        continue
    new_lines.append(line)

with open(file, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print('Fixed!')
