<script setup lang="ts">
import WizardStepper from './WizardStepper.vue'
import WizardStepIntro from './WizardStepIntro.vue'
import WizardStepEmployees from './WizardStepEmployees.vue'
import WizardStepFrontend from './WizardStepFrontend.vue'
import WizardStepRelease from './WizardStepRelease.vue'
import { useModAuthoringContext } from '../composables/useModAuthoringContext'
import { useModAuthoringWizard } from '../composables/useModAuthoringWizard'

const emit = defineEmits<{
  'open-expert': [tabId?: string]
}>()

const ctx = useModAuthoringContext()
const wizard = useModAuthoringWizard(ctx)

const { currentStep, stepCompletion, goNext, goPrev, goToStep, markFrontendSkipped } = wizard
</script>

<template>
  <WizardStepper :current-step="currentStep" :completion="stepCompletion" @go="goToStep" />

  <WizardStepIntro v-show="currentStep === 1" />
  <WizardStepEmployees v-show="currentStep === 2" @open-expert-files="emit('open-expert', 'files')" />
  <WizardStepFrontend v-show="currentStep === 3" @skip="markFrontendSkipped" />
  <WizardStepRelease v-show="currentStep === 4" @open-expert="emit('open-expert', $event)" />

  <footer class="wizard-footer">
    <button type="button" class="btn" :disabled="currentStep <= 1" @click="goPrev">上一步</button>
    <button v-if="currentStep < 4" type="button" class="btn btn-primary" @click="goNext">下一步</button>
  </footer>
</template>
