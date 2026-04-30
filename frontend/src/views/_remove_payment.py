import shutil

src = r'E:\FHD\frontend\src\views\AIEcosystemView.vue'
bak = r'E:\FHD\frontend\src\views\AIEcosystemView.vue.bak'

# 备份
shutil.copy(src, bak)

with open(src, 'r', encoding='utf-8') as f:
    content = f.read()

# 删除模型支付按钮
old = '''        <button class="app-launcher" type="button" @click="goShellPage('model-payment')">
          <span class="app-launcher-icon" aria-hidden="true">💳</span>
          <span class="app-launcher-name">模型支付</span>
          <span class="app-launcher-desc">个人套餐与微信 / 支付宝演示下单</span>
        </button>
'''

content = content.replace(old, '')

with open(src, 'w', encoding='utf-8') as f:
    f.write(content)

print('Removed model-payment from AIEcosystemView.vue')
