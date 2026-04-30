import os

file = r'E:\FHD\frontend\src\views\AIEcosystemView.vue'
with open(file, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 找到并删除模型支付按钮所在的行(21-25)
new_lines = []
for i, line in enumerate(lines, 1):
    # 跳过第21-25行 (模型支付按钮)
    if 21 <= i <= 25:
        continue
    new_lines.append(line)

with open(file, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print('Model payment button removed (lines 21-25)!')
