<script setup lang="ts">
import { onBeforeUnmount, watch } from 'vue'
import { useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import { useOnboardingTutorialStore } from '@/stores/onboardingTutorial'
import { runOnboardingTour } from '@/tutorial/runOnboardingTour'

const router = useRouter()
const store = useOnboardingTutorialStore()
const { active, schedules } = storeToRefs(store)

let stopTour: (() => void) | null = null

const teardown = () => {
  stopTour?.()
  stopTour = null
}

watch(
  active,
  (on) => {
    teardown()
    if (!on || !schedules.value.length) return
    stopTour = runOnboardingTour({
      steps: schedules.value,
      router,
      store,
      onComplete: () => store.finish(true),
      onSkip: () => store.finish(false),
    })
  },
  { flush: 'post' },
)

onBeforeUnmount(teardown)
</script>

<template>
  <span class="onboarding-tutorial-host" aria-hidden="true" />
</template>

<style src="@/styles/onboarding-tour.css"></style>
