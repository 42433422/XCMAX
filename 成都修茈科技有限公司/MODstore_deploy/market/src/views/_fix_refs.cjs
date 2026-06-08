const fs = require('fs');
const path = require('path');

const filePath = path.join(__dirname, 'WorkbenchHomeView.vue');
let content = fs.readFileSync(filePath, 'utf8');

// Step 1: Remove extracted type/interface declarations
// Remove MakeIntent type
content = content.replace(/type MakeIntent = 'mod' \| 'employee' \| 'skill' \| 'workflow'\n/, '');
// Remove PlanPhase type
content = content.replace(/type PlanPhase = 'summary' \| 'chat' \| 'done' \| string\n/, '');
// Remove PlanSession interface (multi-line)
content = content.replace(/interface PlanSession \{[\s\S]*?\n\}\n/, '');

// Step 2: Remove extracted ref/const/let declarations
// Remove planSession, planReplyDraft, autoPilotRunning, autoPilotError, planOptionSelections, PLAN_OPTION_OTHER_ID, planOptionOtherText, clearPlanOptionOtherText, planPanelRef
content = content.replace(/\/\*\* 需求规划：多轮澄清 → 执行清单 → 再进入制作草稿 \*\/\nconst planSession = ref<PlanSession \| null>\(null\)\nconst planReplyDraft = ref\(''\)\n\/\*\* 「AI 自主全部进行」[\s\S]*?function clearPlanOptionOtherText\(\) \{\n  for \(const k of Object\.keys\(planOptionOtherText\)\) \{\n    delete planOptionOtherText\[k\]\n  \}\n\}\nconst planPanelRef = ref<HTMLElement \| null>\(null\)\n/, '');

// Remove planSurfaceKey, MAKE_PROGRESS_CACHE_KEY, MAKE_PROGRESS_CACHE_TTL_MS, planLoadingStepsSummary, planLoadingStepsChat, planLoadingAdvance, planLoadingIntervalId, planLoadingStepLabelsForUi
content = content.replace(/\/\*\* 每次打开规划会话递增[\s\S]*?const planLoadingStepLabelsForUi = computed\(\(\) => \{\n  if \(!planSession\.value\?\.loading\) return \[\]\n  return planSession\.value\.phase === 'summary' \? planLoadingStepsSummary : planLoadingStepsChat\n\}\)\n\n/, '');

// Remove planDiagramError, planDiagramPreviewIdx, planDiagramPreviewMountRef, planDiagramPreviewViewportRef, planPreviewScale, planPreviewTx, planPreviewTy, planDiagramPreviewEscUnlisten, planDiagramPreviewPointerCleanup, planDiagramPreviewPanStyle
content = content.replace(/const planDiagramError = ref<Record<string, string>>\(\{\}\)\nlet planDiagramPreviewEscUnlisten[\s\S]*?const planDiagramPreviewPanStyle = computed\(\(\) => \(\{\n  transform: `translate\(\$planPreviewTx\.value}px, \$planPreviewTy\.value}px\) scale\(\$planPreviewScale\.value\)`,\n  transformOrigin: '0 0',\n\}\)\)\n/, '');

// Remove mermaidApi, mermaidInitDone, _planMermaidRenderedHash
content = content.replace(/let mermaidApi: any = null\nlet mermaidInitDone = false\nconst _planMermaidRenderedHash: Record<number, string> = \{\}\n/, '');

// Remove _cacheMakeProgressTimer
content = content.replace(/let _cacheMakeProgressTimer: ReturnType<typeof setTimeout> \| null = null\n/, '');

// Step 3: Remove extracted function declarations
const functionsToRemove = [
  'isModHostStackSurveyQuestion',
  'normalizePlanOptions',
  'parsePlanAssistantContent',
  'planQuickOptions',
  'planPanelTitle',
  'mermaidChecklistLabel',
  'buildChecklistFlowMarkdown',
  'planChecklistFlowMarkdown',
  'compactPlanVisibleText',
  'extractInitialIdeaFromHandoff',
  'buildPlanSummarySystemPrompt',
  'parsePlanSummary',
  'canSendPlanQuickPicks',
  'planAssistantParts',
  'sanitizeMermaidLabel',
  'sanitizeMermaidSource',
  'clearPlanDiagramPreviewPointerListeners',
  'onPlanDiagramPreviewWheel',
  'onPlanDiagramPreviewPointerDown',
  'planDiagramPreviewZoomStep',
  'planDiagramPreviewFitView',
  'openPlanDiagramPreview',
  'closePlanDiagramPreview',
  'getMermaidSingleton',
  '_planMermaidHashStr',
  'flushPlanMermaidDiagrams',
  'dismissPlanSession',
  'resetMakeComposer',
  'serializablePlanSession',
  'restorePlanSession',
  'serializablePendingHandoff',
  'restorePendingHandoff',
  'makeHasCachedProgress',
  'cacheMakeProgress',
  '_doSaveMakeProgress',
  'clearMakeProgressCache',
  'restoreMakeProgressCache',
  'friendlyPlanPanelApiError',
  '_checklistBodyToResult',
  'parseChecklistNumberedTail',
  'parseChecklistBlock',
  'formatPlanMessagesForBrief',
  'buildPlanSystemPrompt',
  'buildChecklistGenerationSystemPrompt',
  'scrollPlanIntoView',
  'planWorkbenchMsgToApi',
  'appendUserAndAssistantPlanTurn',
  'summarizePlanSession',
  'openPlanSession',
  'backSummaryToComposer',
  'confirmSummaryAndStartPlanning',
  'runAutoPilotFromSummary',
  'pickPlanOption',
  'autoPickPlanQuickOptions',
  'submitPlanUserMessage',
  'sendPlanReply',
  'sendPlanReplyFromQuickPicks',
  'requestExecutionChecklist',
  'backPlanToChat',
  'confirmPlanAndOpenHandoff',
];

for (const fnName of functionsToRemove) {
  // Match function declarations (async or sync) with various patterns
  // Pattern: [async] function fnName(...) { ... }
  // We need to handle nested braces carefully
  const patterns = [
    // const fnName = computed(() => { ... })
    new RegExp(`const ${fnName} = computed\\(([\\s\\S]*?)\\)\\n`, 'g'),
    // async function fnName(...) { ... }
    new RegExp(`async function ${fnName}\\([^)]*\\) \\{`, 'g'),
    // function fnName(...) { ... }
    new RegExp(`function ${fnName}\\([^)]*\\) \\{`, 'g'),
    // function fnName() { ... }
    new RegExp(`function ${fnName}\\(\\) \\{`, 'g'),
  ];
  // We'll mark these for removal later - for now just log
}

// Step 4: Update references in script section (not in function declarations being removed)
// This is the tricky part - we need to replace references but NOT in the function declarations themselves
// Since we're removing the function declarations, we just need to update references in the remaining code

// Template references (in <template> section) - these use the variable directly without .value
// Script references - these use .value for refs

// For template: planSession -> plan.planSession, etc.
// For script: planSession.value -> plan.planSession.value, etc.

// We need to be careful not to replace:
// 1. Function declarations (which we're removing)
// 2. Object property names (like { planSession: ... })
// 3. String literals

// Let's do targeted replacements for the most common patterns

// Script section replacements (with .value)
const scriptReplacements = [
  // Refs with .value
  [/(?<![\w.])planSession\.value/g, 'plan.planSession.value'],
  [/(?<![\w.])planReplyDraft\.value/g, 'plan.planReplyDraft.value'],
  [/(?<![\w.])autoPilotRunning\.value/g, 'plan.autoPilotRunning.value'],
  [/(?<![\w.])autoPilotError\.value/g, 'plan.autoPilotError.value'],
  [/(?<![\w.])planOptionSelections\.value/g, 'plan.planOptionSelections.value'],
  [/(?<![\w.])planOptionOtherText\[/g, 'plan.planOptionOtherText['],
  [/(?<![\w.])planPanelRef\.value/g, 'plan.planPanelRef.value'],
  [/(?<![\w.])planSurfaceKey\.value/g, 'plan.planSurfaceKey.value'],
  [/(?<![\w.])planLoadingAdvance\.value/g, 'plan.planLoadingAdvance.value'],
  [/(?<![\w.])planDiagramError\.value/g, 'plan.planDiagramError.value'],
  [/(?<![\w.])planDiagramPreviewIdx\.value/g, 'plan.planDiagramPreviewIdx.value'],
  [/(?<![\w.])planDiagramPreviewMountRef\.value/g, 'plan.planDiagramPreviewMountRef.value'],
  [/(?<![\w.])planDiagramPreviewViewportRef\.value/g, 'plan.planDiagramPreviewViewportRef.value'],
  [/(?<![\w.])planPreviewScale\.value/g, 'plan.planPreviewScale.value'],
  [/(?<![\w.])planPreviewTx\.value/g, 'plan.planPreviewTx.value'],
  [/(?<![\w.])planPreviewTy\.value/g, 'plan.planPreviewTy.value'],
  [/(?<![\w.])planLoadingStepLabelsForUi\.value/g, 'plan.planLoadingStepLabelsForUi.value'],
  [/(?<![\w.])planQuickOptions\.value/g, 'plan.planQuickOptions.value'],
  [/(?<![\w.])planPanelTitle\.value/g, 'plan.planPanelTitle.value'],
  [/(?<![\w.])planChecklistFlowMarkdown\.value/g, 'plan.planChecklistFlowMarkdown.value'],
  [/(?<![\w.])canSendPlanQuickPicks\.value/g, 'plan.canSendPlanQuickPicks.value'],
  [/(?<![\w.])planDiagramPreviewPanStyle\.value/g, 'plan.planDiagramPreviewPanStyle.value'],
  // Constants
  [/(?<![\w.])PLAN_OPTION_OTHER_ID/g, 'plan.PLAN_OPTION_OTHER_ID'],
  [/(?<![\w.])MAKE_PROGRESS_CACHE_KEY/g, 'plan.MAKE_PROGRESS_CACHE_KEY'],
  [/(?<![\w.])MAKE_PROGRESS_CACHE_TTL_MS/g, 'plan.MAKE_PROGRESS_CACHE_TTL_MS'],
  [/(?<![\w.])planLoadingStepsSummary/g, 'plan.planLoadingStepsSummary'],
  [/(?<![\w.])planLoadingStepsChat/g, 'plan.planLoadingStepsChat'],
  // Functions
  [/(?<![\w.])clearPlanOptionOtherText\(\)/g, 'plan.clearPlanOptionOtherText()'],
  [/(?<![\w.])serializablePlanSession\(/g, 'plan.serializablePlanSession('],
  [/(?<![\w.])restorePlanSession\(/g, 'plan.restorePlanSession('],
  [/(?<![\w.])serializablePendingHandoff\(/g, 'plan.serializablePendingHandoff('],
  [/(?<![\w.])restorePendingHandoff\(/g, 'plan.restorePendingHandoff('],
  [/(?<![\w.])makeHasCachedProgress\(\)/g, 'plan.makeHasCachedProgress()'],
  [/(?<![\w.])cacheMakeProgress\(\)/g, 'plan.cacheMakeProgress()'],
  [/(?<![\w.])_doSaveMakeProgress\(\)/g, 'plan._doSaveMakeProgress()'],
  [/(?<![\w.])clearMakeProgressCache\(\)/g, 'plan.clearMakeProgressCache()'],
  [/(?<![\w.])restoreMakeProgressCache\(\)/g, 'plan.restoreMakeProgressCache()'],
  [/(?<![\w.])friendlyPlanPanelApiError\(/g, 'plan.friendlyPlanPanelApiError('],
  [/(?<![\w.])isModHostStackSurveyQuestion\(/g, 'plan.isModHostStackSurveyQuestion('],
  [/(?<![\w.])normalizePlanOptions\(/g, 'plan.normalizePlanOptions('],
  [/(?<![\w.])parsePlanAssistantContent\(/g, 'plan.parsePlanAssistantContent('],
  [/(?<![\w.])planAssistantParts\(/g, 'plan.planAssistantParts('],
  [/(?<![\w.])compactPlanVisibleText\(/g, 'plan.compactPlanVisibleText('],
  [/(?<![\w.])extractInitialIdeaFromHandoff\(/g, 'plan.extractInitialIdeaFromHandoff('],
  [/(?<![\w.])buildPlanSummarySystemPrompt\(/g, 'plan.buildPlanSummarySystemPrompt('],
  [/(?<![\w.])parsePlanSummary\(/g, 'plan.parsePlanSummary('],
  [/(?<![\w.])buildPlanSystemPrompt\(/g, 'plan.buildPlanSystemPrompt('],
  [/(?<![\w.])buildChecklistGenerationSystemPrompt\(/g, 'plan.buildChecklistGenerationSystemPrompt('],
  [/(?<![\w.])formatPlanMessagesForBrief\(/g, 'plan.formatPlanMessagesForBrief('],
  [/(?<![\w.])scrollPlanIntoView\(\)/g, 'plan.scrollPlanIntoView()'],
  [/(?<![\w.])planWorkbenchMsgToApi\(/g, 'plan.planWorkbenchMsgToApi('],
  [/(?<![\w.])appendUserAndAssistantPlanTurn\(/g, 'plan.appendUserAndAssistantPlanTurn('],
  [/(?<![\w.])summarizePlanSession\(\)/g, 'plan.summarizePlanSession()'],
  [/(?<![\w.])openPlanSession\(/g, 'plan.openPlanSession('],
  [/(?<![\w.])backSummaryToComposer\(\)/g, 'plan.backSummaryToComposer()'],
  [/(?<![\w.])confirmSummaryAndStartPlanning\(\)/g, 'plan.confirmSummaryAndStartPlanning()'],
  [/(?<![\w.])runAutoPilotFromSummary\(\)/g, 'plan.runAutoPilotFromSummary()'],
  [/(?<![\w.])pickPlanOption\(/g, 'plan.pickPlanOption('],
  [/(?<![\w.])autoPickPlanQuickOptions\(\)/g, 'plan.autoPickPlanQuickOptions()'],
  [/(?<![\w.])submitPlanUserMessage\(/g, 'plan.submitPlanUserMessage('],
  [/(?<![\w.])sendPlanReply\(\)/g, 'plan.sendPlanReply()'],
  [/(?<![\w.])sendPlanReplyFromQuickPicks\(\)/g, 'plan.sendPlanReplyFromQuickPicks()'],
  [/(?<![\w.])requestExecutionChecklist\(\)/g, 'plan.requestExecutionChecklist()'],
  [/(?<![\w.])backPlanToChat\(\)/g, 'plan.backPlanToChat()'],
  [/(?<![\w.])confirmPlanAndOpenHandoff\(\)/g, 'plan.confirmPlanAndOpenHandoff()'],
  [/(?<![\w.])dismissPlanSession\(\)/g, 'plan.dismissPlanSession()'],
  [/(?<![\w.])resetMakeComposer\(\)/g, 'plan.resetMakeComposer()'],
  [/(?<![\w.])mermaidChecklistLabel\(/g, 'plan.mermaidChecklistLabel('],
  [/(?<![\w.])buildChecklistFlowMarkdown\(/g, 'plan.buildChecklistFlowMarkdown('],
  [/(?<![\w.])_checklistBodyToResult\(/g, 'plan._checklistBodyToResult('],
  [/(?<![\w.])parseChecklistNumberedTail\(/g, 'plan.parseChecklistNumberedTail('],
  [/(?<![\w.])parseChecklistBlock\(/g, 'plan.parseChecklistBlock('],
  [/(?<![\w.])sanitizeMermaidLabel\(/g, 'plan.sanitizeMermaidLabel('],
  [/(?<![\w.])sanitizeMermaidSource\(/g, 'plan.sanitizeMermaidSource('],
  [/(?<![\w.])getMermaidSingleton\(\)/g, 'plan.getMermaidSingleton()'],
  [/(?<![\w.])_planMermaidHashStr\(/g, 'plan._planMermaidHashStr('],
  [/(?<![\w.])flushPlanMermaidDiagrams\(\)/g, 'plan.flushPlanMermaidDiagrams()'],
  [/(?<![\w.])clearPlanDiagramPreviewPointerListeners\(\)/g, 'plan.clearPlanDiagramPreviewPointerListeners()'],
  [/(?<![\w.])onPlanDiagramPreviewWheel\(/g, 'plan.onPlanDiagramPreviewWheel('],
  [/(?<![\w.])onPlanDiagramPreviewPointerDown\(/g, 'plan.onPlanDiagramPreviewPointerDown('],
  [/(?<![\w.])planDiagramPreviewZoomStep\(/g, 'plan.planDiagramPreviewZoomStep('],
  [/(?<![\w.])planDiagramPreviewFitView\(\)/g, 'plan.planDiagramPreviewFitView()'],
  [/(?<![\w.])openPlanDiagramPreview\(/g, 'plan.openPlanDiagramPreview('],
  [/(?<![\w.])closePlanDiagramPreview\(\)/g, 'plan.closePlanDiagramPreview()'],
];

// Apply script replacements
for (const [pattern, replacement] of scriptReplacements) {
  content = content.replace(pattern, replacement);
}

// Template replacements (without .value - Vue auto-unwraps refs in templates)
// In templates, refs are auto-unwrapped, so planSession -> plan.planSession
// But we need to be careful not to replace in script section where .value is used
// Since we already replaced .value patterns above, we need to handle template-only patterns

// Find the template section
const templateStart = content.indexOf('<template>');
const templateEnd = content.indexOf('</template>');
const scriptStart = content.indexOf('<script setup');

if (templateStart !== -1 && templateEnd !== -1) {
  let templateSection = content.substring(templateStart, templateEnd + '</template>'.length);
  const scriptAndStyleSection = content.substring(templateEnd + '</template>'.length);
  
  // Template replacements
  const templateReplacements = [
    // These are for template-only references (without .value)
    // planSession (not plan.planSession.value - already handled above)
    [/(?<![\w.])planSession(?!\.value)(?![\w])/g, 'plan.planSession'],
    [/(?<![\w.])planReplyDraft(?!\.value)(?![\w])/g, 'plan.planReplyDraft'],
    [/(?<![\w.])autoPilotRunning(?!\.value)(?![\w])/g, 'plan.autoPilotRunning'],
    [/(?<![\w.])autoPilotError(?!\.value)(?![\w])/g, 'plan.autoPilotError'],
    [/(?<![\w.])planOptionSelections(?!\.value)(?![\w\[])/g, 'plan.planOptionSelections'],
    [/(?<![\w.])planOptionOtherText(?!\[)(?![\w])/g, 'plan.planOptionOtherText'],
    [/(?<![\w.])planPanelRef(?!\.value)(?![\w])/g, 'plan.planPanelRef'],
    [/(?<![\w.])planSurfaceKey(?!\.value)(?![\w])/g, 'plan.planSurfaceKey'],
    [/(?<![\w.])planLoadingAdvance(?!\.value)(?![\w])/g, 'plan.planLoadingAdvance'],
    [/(?<![\w.])planDiagramError(?!\.value)(?![\w])/g, 'plan.planDiagramError'],
    [/(?<![\w.])planDiagramPreviewIdx(?!\.value)(?![\w])/g, 'plan.planDiagramPreviewIdx'],
    [/(?<![\w.])planDiagramPreviewMountRef(?!\.value)(?![\w])/g, 'plan.planDiagramPreviewMountRef'],
    [/(?<![\w.])planDiagramPreviewViewportRef(?!\.value)(?![\w])/g, 'plan.planDiagramPreviewViewportRef'],
    [/(?<![\w.])planPreviewScale(?!\.value)(?![\w])/g, 'plan.planPreviewScale'],
    [/(?<![\w.])planPreviewTx(?!\.value)(?![\w])/g, 'plan.planPreviewTx'],
    [/(?<![\w.])planPreviewTy(?!\.value)(?![\w])/g, 'plan.planPreviewTy'],
    [/(?<![\w.])planLoadingStepLabelsForUi(?!\.value)(?![\w])/g, 'plan.planLoadingStepLabelsForUi'],
    [/(?<![\w.])planQuickOptions(?!\.value)(?![\w])/g, 'plan.planQuickOptions'],
    [/(?<![\w.])planPanelTitle(?!\.value)(?![\w])/g, 'plan.planPanelTitle'],
    [/(?<![\w.])planChecklistFlowMarkdown(?!\.value)(?![\w])/g, 'plan.planChecklistFlowMarkdown'],
    [/(?<![\w.])canSendPlanQuickPicks(?!\.value)(?![\w])/g, 'plan.canSendPlanQuickPicks'],
    [/(?<![\w.])planDiagramPreviewPanStyle(?!\.value)(?![\w])/g, 'plan.planDiagramPreviewPanStyle'],
  ];
  
  for (const [pattern, replacement] of templateReplacements) {
    templateSection = templateSection.replace(pattern, replacement);
  }
  
  content = templateSection + scriptAndStyleSection;
}

// Fix any double plan.plan. references
content = content.replace(/plan\.plan\./g, 'plan.');

fs.writeFileSync(filePath, content, 'utf8');
console.log('Done - references updated');
