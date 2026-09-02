// 拆分自 HomeView.vue：上架素材模态框状态与上传动作（逻辑逐字迁移，行为不变）。
import { ref } from 'vue'
import type { Ref } from 'vue'
import { api } from '@/api'
import type { MarketItem } from './homeViewTypes'

export interface UploadModalDeps {
  items: Ref<MarketItem[]>
}

export function useUploadModal(deps: UploadModalDeps) {
  const { items } = deps

  const showUploadModal = ref(false)
  const uploadForm = ref({
    name: '',
    description: '',
    industry: '',
    price: 0,
    license_scope: 'personal',
    origin_type: 'original',
    ip_risk_level: 'low',
  })
  const uploadFile = ref<File | null>(null)
  const uploadError = ref('')
  const uploadSuccess = ref(false)
  const uploading = ref(false)

  function handleFileChange(event: Event) {
    const input = event.target as HTMLInputElement | null
    uploadFile.value = input?.files?.[0] ?? null
  }

  async function uploadEmployee() {
    if (!uploadFile.value) {
      uploadError.value = '请选择员工包文件'
      return
    }

    uploadError.value = ''
    uploadSuccess.value = false
    uploading.value = true

    try {
      const paid = Number(uploadForm.value.price || 0) > 0
      const risky = ['derivative', 'collaboration', 'fan_linkage', 'suspected_plagiarism'].includes(uploadForm.value.origin_type)
        || ['medium', 'high'].includes(uploadForm.value.ip_risk_level)
      if (paid && uploadForm.value.license_scope !== 'commercial') {
        throw new Error('收费商品必须选择商业授权')
      }
      if (risky && (paid || uploadForm.value.license_scope === 'commercial')) {
        throw new Error('疑似抄袭、二创、联动或中高风险素材只能免费或限制个人使用')
      }
      // 生成唯一的包ID和版本号
      const pkgId = `employee_${Date.now()}_${Math.floor(Math.random() * 1000)}`
      const version = '1.0.0'

      const metadata = {
        id: pkgId,
        version: version,
        name: uploadForm.value.name,
        description: uploadForm.value.description,
        artifact: 'employee_pack',
        material_category: 'ai_employee',
        license_scope: uploadForm.value.license_scope,
        origin_type: uploadForm.value.origin_type,
        ip_risk_level: uploadForm.value.ip_risk_level,
        industry: uploadForm.value.industry || '通用',
        commerce: {
          price: uploadForm.value.price
        }
      }

      await api.uploadPackage(metadata, uploadFile.value)
      uploadSuccess.value = true

      // 重置表单
      uploadForm.value = {
        name: '',
        description: '',
        industry: '',
        price: 0,
        license_scope: 'personal',
        origin_type: 'original',
        ip_risk_level: 'low',
      }
      uploadFile.value = null

      // 重新加载商品列表
      try {
        const res = await api.catalog('', '', 4, 0)
        items.value = res.items.map((item) => ({ ...item, price: Number(item.price ?? 0) }))
      } catch {
        // 加载失败不影响上传成功的提示
      }

      // 3秒后关闭模态框
      setTimeout(() => {
        showUploadModal.value = false
      }, 3000)
    } catch (error) {
      uploadError.value = (error as Error)?.message || '上传失败，请重试'
    } finally {
      uploading.value = false
    }
  }

  return {
    showUploadModal,
    uploadForm,
    uploadFile,
    uploadError,
    uploadSuccess,
    uploading,
    handleFileChange,
    uploadEmployee,
  }
}
