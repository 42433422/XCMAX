import os
import shutil

src = r'E:\FHD\frontend\src\App.vue'
bak = r'E:\FHD\frontend\src\App.vue.new'

# 备份
shutil.copy(src, bak)

with open(src, 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
for i, line in enumerate(lines):
    new_lines.append(line.rstrip('\n'))
    # 添加import
    if i == 8 and 'ProMode' in line:
        new_lines.append("import GlobalReadTokenPrompt from './fhd/GlobalReadTokenPrompt.vue'")
    # 添加组件到template
    if 'ProMode v-model="isProMode"' in line and i > 400:
        new_lines.append('')
        new_lines.append('    <GlobalReadTokenPrompt api-base="" />')

# 写入
with open(bak, 'w', encoding='utf-8') as f:
    for line in new_lines:
        f.write(line + '\n')

# 替换
os.remove(src)
os.rename(bak, src)

print("App.vue fixed with GlobalReadTokenPrompt!")
