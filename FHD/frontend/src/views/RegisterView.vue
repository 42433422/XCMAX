<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { marketRegisterUrl } from '@/constants/loginBranding'
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl'
import { isDesktopShell } from '@/utils/desktopShell'

const route = useRoute()
const router = useRouter()
const admin = isAdminConsoleSpa()
const desktop = isDesktopShell()
const registerUrl = computed(() => marketRegisterUrl(
  route.query.redirect === '/app/mobile-register-complete' ? 'xcagi-mobile' : 'xcagi-desktop',
))

onMounted(() => {
  if (admin) {
    void router.replace({ name: 'login', query: route.query })
  } else if (!desktop) {
    window.location.replace(registerUrl.value)
  }
})
</script>

<template>
  <main v-if="!admin">
    <a :href="registerUrl" :target="desktop ? '_blank' : undefined" rel="noopener noreferrer">
      注册 XCAGI 账号
    </a>
  </main>
</template>
