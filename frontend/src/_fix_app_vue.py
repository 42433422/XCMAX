import os

src = r'E:\FHD\frontend\src\App.vue'
bak = r'E:\FHD\frontend\src\App.vue.bak'

with open(bak, 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
for i, line in enumerate(lines):
    new_lines.append(line.rstrip('\n'))
    if i == 8 and 'ProMode' in line:
        new_lines.append("import GlobalReadTokenPrompt from './fhd/GlobalReadTokenPrompt.vue'")
    if 'ProMode v-model' in line and i > 400:
        new_lines.append('')
        new_lines.append('    <GlobalReadTokenPrompt api-base="" />')

with open(src, 'w', encoding='utf-8') as f:
    for line in new_lines:
        f.write(line + '\n')

print('Updated App.vue')
