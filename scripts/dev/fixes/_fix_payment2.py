import shutil
import os

src = r'E:\FHD\frontend\src\views\AIEcosystemView.vue'
dst = r'E:\FHD\frontend\src\views\AIEcosystemView_new.vue'

# 读取源文件
with open(src, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 删除第21-25行 (模型支付按钮)
new_lines = []
for i, line in enumerate(lines, 1):
    if 21 <= i <= 25:
        continue
    new_lines.append(line)

# 写入新文件
with open(dst, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print('New file created: ' + dst)

# 尝试替换
try:
    os.remove(src)
    os.rename(dst, src)
    print('File replaced successfully!')
except Exception as e:
    print('Cannot replace: ' + str(e))
    print('Manual action needed: delete ' + src + ' and rename ' + dst + ' to ' + src)
