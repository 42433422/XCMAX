import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import LegacyFloatPanels from './LegacyFloatPanels.vue'

describe('LegacyFloatPanels', () => {
  function mountPanels() {
    return mount(LegacyFloatPanels)
  }

  it('renders the transition overlay', () => {
    const wrapper = mountPanels()
    expect(wrapper.find('#transitionOverlay').exists()).toBe(true)
    expect(wrapper.find('#transitionOverlay').classes()).toContain('transition-overlay')
  })

  it('renders the preview float window with header and close button', () => {
    const wrapper = mountPanels()
    const win = wrapper.find('#previewFloatWindow')
    expect(win.exists()).toBe(true)
    expect(win.classes()).toContain('preview-float-window')
    expect(win.find('.preview-header h4').text()).toContain('媒体预览')
    expect(win.find('#previewCloseBtn').exists()).toBe(true)
    expect(win.find('#previewCloseBtn').attributes('data-close-action')).toBe('closePreviewWindow')
  })

  it('renders the preview media placeholder', () => {
    const wrapper = mountPanels()
    expect(wrapper.find('#previewMedia').exists()).toBe(true)
    expect(wrapper.find('.preview-placeholder').text()).toBe('暂无预览内容')
  })

  it('renders the progress panel with title and close button', () => {
    const wrapper = mountPanels()
    const panel = wrapper.find('#progressPanel')
    expect(panel.exists()).toBe(true)
    expect(panel.classes()).toContain('progress-panel')
    expect(panel.find('.progress-title').text()).toBe('任务进度')
    expect(panel.find('#progressCloseBtn').exists()).toBe(true)
    expect(panel.find('#progressCloseBtn').attributes('data-close-action')).toBe('hideProgress')
  })

  it('renders the progress panel with initial state', () => {
    const wrapper = mountPanels()
    expect(wrapper.find('.progress-status').text()).toBe('处理中...')
    expect(wrapper.find('#progressPercent').text()).toBe('0%')
    expect(wrapper.find('#progressBarFill').attributes('style')).toContain('width:0%')
    expect(wrapper.find('#progressTask').text()).toBe('正在初始化任务...')
  })

  it('renders the file upload entry', () => {
    const wrapper = mountPanels()
    const entry = wrapper.find('#fileUploadEntry')
    expect(entry.exists()).toBe(true)
    expect(entry.classes()).toContain('file-upload-entry')
    expect(entry.find('.entry-text').text()).toBe('上传文件')
  })

  it('renders the import float window with header and close button', () => {
    const wrapper = mountPanels()
    const win = wrapper.find('#importFloatWindow')
    expect(win.exists()).toBe(true)
    expect(win.classes()).toContain('import-float-window')
    expect(win.find('.import-header h4').text()).toContain('导入文件')
    expect(win.find('#importCloseBtn').exists()).toBe(true)
    expect(win.find('#importCloseBtn').attributes('data-close-action')).toBe('closeImportWindow')
  })

  it('renders the drop zone in import window', () => {
    const wrapper = mountPanels()
    const dropZone = wrapper.find('#dropZone')
    expect(dropZone.exists()).toBe(true)
    expect(dropZone.classes()).toContain('drop-zone')
    expect(dropZone.find('.drop-zone-text').text()).toBe('拖拽文件到此处或点击选择')
    expect(dropZone.find('.drop-zone-hint').text()).toContain('Excel')
  })

  it('renders the file input with multiple and accept attributes', () => {
    const wrapper = mountPanels()
    const input = wrapper.find('#fileInput')
    expect(input.exists()).toBe(true)
    expect(input.attributes('multiple')).toBeDefined()
    expect(input.attributes('accept')).toBe('*/*')
  })

  it('renders the import action buttons', () => {
    const wrapper = mountPanels()
    const actions = wrapper.find('#importFloatWindow .import-actions')
    expect(actions.exists()).toBe(true)
    expect(actions.find('#chooseFileBtn').text()).toBe('选择文件')
    expect(actions.find('#openCameraBtn').text()).toContain('拍照识别')
    expect(actions.find('#cancelImportBtn').text()).toBe('取消')
    expect(actions.find('#cancelImportBtn').attributes('data-close-action')).toBe('closeImportWindow')
  })

  it('renders the camera panel hidden by default', () => {
    const wrapper = mountPanels()
    const panel = wrapper.find('#cameraPanel')
    expect(panel.exists()).toBe(true)
    expect(panel.attributes('style')).toContain('display: none')
    expect(panel.find('#cameraVideo').exists()).toBe(true)
    expect(panel.find('#capturePhotoBtn').text()).toBe('拍照')
    expect(panel.find('#closeCameraBtn').attributes('data-close-action')).toBe('closeCamera')
  })

  it('renders the import progress section', () => {
    const wrapper = mountPanels()
    expect(wrapper.find('#importProgress').exists()).toBe(true)
    expect(wrapper.find('#progressBar').exists()).toBe(true)
    expect(wrapper.find('#progressText').text()).toBe('读取中...')
    expect(wrapper.find('#importProgressPercent').text()).toBe('0%')
  })

  it('renders the import status container', () => {
    const wrapper = mountPanels()
    expect(wrapper.find('#importStatus').exists()).toBe(true)
  })

  it('renders the labels export window with header and close button', () => {
    const wrapper = mountPanels()
    const win = wrapper.find('#labelsExportWindow')
    expect(win.exists()).toBe(true)
    expect(win.classes()).toContain('import-float-window')
    expect(win.find('.import-header h4').text()).toContain('商标导出')
    expect(win.find('#labelsExportCloseBtn').exists()).toBe(true)
  })

  it('renders the labels export list with hint when empty', () => {
    const wrapper = mountPanels()
    const list = wrapper.find('#labelsExportList')
    expect(list.exists()).toBe(true)
    expect(list.classes()).toContain('labels-export-list')
    expect(list.find('.labels-export-hint').text()).toContain('暂无标签文件')
  })

  it('renders the labels export close button', () => {
    const wrapper = mountPanels()
    expect(wrapper.find('#labelsExportCloseBtn2').text()).toBe('关闭')
  })

  it('renders the print panel window with header and close button', () => {
    const wrapper = mountPanels()
    const win = wrapper.find('#printPanelWindow')
    expect(win.exists()).toBe(true)
    expect(win.classes()).toContain('import-float-window')
    expect(win.find('.import-header h4').text()).toContain('标签打印')
    expect(win.find('#printPanelCloseBtn').exists()).toBe(true)
  })

  it('renders the print panel status and action buttons', () => {
    const wrapper = mountPanels()
    expect(wrapper.find('#printPanelStatus').text()).toContain('正在连接打印机')
    expect(wrapper.find('#printPanelStartBtn').text()).toBe('开始打印')
    expect(wrapper.find('#printPanelCloseBtn2').text()).toBe('关闭')
  })

  it('renders the print panel progress and results containers', () => {
    const wrapper = mountPanels()
    expect(wrapper.find('#printPanelProgress').exists()).toBe(true)
    expect(wrapper.find('#printPanelResults').exists()).toBe(true)
  })

  it('renders the label float previews container hidden by default', () => {
    const wrapper = mountPanels()
    const el = wrapper.find('#labelFloatPreviews')
    expect(el.exists()).toBe(true)
    expect(el.classes()).toContain('label-float-previews')
    expect(el.classes()).toContain('hidden')
    expect(el.attributes('aria-hidden')).toBe('true')
  })

  it('renders the label preview modal hidden by default', () => {
    const wrapper = mountPanels()
    const modal = wrapper.find('#labelPreviewModal')
    expect(modal.exists()).toBe(true)
    expect(modal.classes()).toContain('label-preview-modal')
    expect(modal.classes()).toContain('hidden')
    expect(modal.attributes('aria-hidden')).toBe('true')
  })

  it('renders the label preview modal content with image and download link', () => {
    const wrapper = mountPanels()
    const modal = wrapper.find('#labelPreviewModal')
    expect(modal.find('.label-preview-modal-backdrop').exists()).toBe(true)
    expect(modal.find('.label-preview-modal-content').exists()).toBe(true)
    expect(modal.find('#labelPreviewModalImg').exists()).toBe(true)
    const download = modal.find('#labelPreviewModalDownload')
    expect(download.exists()).toBe(true)
    expect(download.attributes('download')).toBeDefined()
    expect(download.text()).toBe('下载标签')
  })

  it('renders the label preview modal close button', () => {
    const wrapper = mountPanels()
    const closeBtn = wrapper.find('#labelPreviewModal .label-preview-modal-close')
    expect(closeBtn.exists()).toBe(true)
    expect(closeBtn.text()).toBe('关闭')
  })
})
