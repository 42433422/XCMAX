<template>
  <div class="field-editor">
    <div class="editor-layout" :style="editorPaneStyle">
      <div class="preview-section">
        <h4 style="margin-top: 0"><i class="fa fa-file-text-o" aria-hidden="true"></i> 预览</h4>
        <div class="preview-container">
          <ExcelPreview v-if="templateType === 'excel'" :fields="fields" />
          <div v-else-if="templateType === 'word'" class="word-preview-box">
            <p class="muted" style="font-size: 13px; margin: 0 0 10px; line-height: 1.5">
              Word 模板以文档中的占位符为准；下列词条参与「必备词条」匹配与导出替换。
            </p>
            <div class="word-preview-chips">
              <span v-for="(f, i) in fields" :key="i" class="word-chip">{{ f.label }}</span>
              <span v-if="!fields.length" class="muted">暂无占位词条</span>
            </div>
          </div>
          <LabelPreview v-else-if="templateType === 'label'" :fields="fields" />
        </div>
        <PaneResizeHandle
          v-if="isEditorPaneResizable"
          orientation="vertical"
          label="调整预览区宽度"
          @resize-start="onEditorPaneResizeStart"
          @reset="resetEditorPaneWidth"
        />
      </div>

      <div class="fields-section">
        <h4 style="margin-top: 0"><i class="fa fa-list-alt" aria-hidden="true"></i> 字段列表</h4>

        <div class="fields-list">
          <div
            v-for="(field, index) in fields"
            :key="index"
            class="field-item"
            :class="{ active: editingIndex === index }"
            @click="selectField(index)"
          >
            <div class="field-main">
              <div class="field-label-input">
                <input type="text" v-model="field.label" class="form-control-sm" placeholder="字段名" @click.stop @change="onFieldChange" />
                <span class="separator">：</span>
                <input
                  type="text"
                  v-model="field.value"
                  class="form-control-sm value-input"
                  placeholder="示例值"
                  @click.stop
                  @change="onFieldChange"
                />
              </div>
            </div>

            <div class="field-actions">
              <span
                class="type-badge"
                :class="field.type === 'fixed' ? 'badge-fixed' : 'badge-dynamic'"
                @click.stop="toggleType(index)"
                title="点击切换类型"
              >
                {{ field.type === 'fixed' ? '固定' : '可变' }}
              </span>
              <button type="button" class="btn-icon" @click.stop="editField(index)" title="编辑">
                <i class="fa fa-pencil" aria-hidden="true"></i>
              </button>
              <button type="button" class="btn-icon btn-danger" @click.stop="deleteField(index)" title="删除">
                <i class="fa fa-trash-o" aria-hidden="true"></i>
              </button>
            </div>
          </div>

          <div v-if="fields.length === 0" class="empty-fields">暂无字段，请添加或上传文件自动识别</div>
        </div>

        <div class="add-field-actions">
          <button type="button" class="btn btn-secondary btn-sm" @click="addField">
            <i class="fa fa-plus" aria-hidden="true"></i> 添加字段
          </button>
        </div>
      </div>
    </div>

    <div v-if="editingField" class="field-edit-modal">
      <div class="modal-overlay" @click.self="closeEditModal"></div>
      <div class="modal-content">
        <div class="modal-header">
          <h3>编辑字段</h3>
          <button type="button" class="modal-close" @click="closeEditModal">&times;</button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>字段标签</label>
            <input type="text" v-model="editingField.label" class="form-control" placeholder="例如：品名" />
          </div>
          <div class="form-group">
            <label>示例值</label>
            <input type="text" v-model="editingField.value" class="form-control" placeholder="例如：运动鞋" />
          </div>
          <div class="form-group">
            <label>字段类型</label>
            <div class="type-radio-group">
              <label class="radio-label">
                <input type="radio" v-model="editingField.type" value="fixed" />
                <span class="radio-text">固定词条</span>
                <span class="radio-desc">标签上的标识文字，不可编辑</span>
              </label>
              <label class="radio-label">
                <input type="radio" v-model="editingField.type" value="dynamic" />
                <span class="radio-text">可变词条</span>
                <span class="radio-desc">对应的值，可以修改</span>
              </label>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" @click="closeEditModal">取消</button>
          <button type="button" class="btn btn-primary" @click="saveFieldEdit">保存</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { appConfirm } from '@/utils/appDialog'
import PaneResizeHandle from '@/components/PaneResizeHandle.vue'
import { useResizablePane } from '@/composables/useResizablePane'
import ExcelPreview from './ExcelPreview.vue'
import LabelPreview from './LabelPreview.vue'

export default {
  name: 'FieldEditor',
  components: {
    ExcelPreview,
    LabelPreview,
    PaneResizeHandle,
  },
  setup() {
    const FIELD_EDITOR_MQ = '(max-width: 960px)'
    const isEditorPaneResizable = ref(true)
    let editorPaneViewportMedia = null
    const {
      paneStyle: editorPaneStyle,
      startResize: onEditorPaneResizeStart,
      resetSize: resetEditorPaneWidth,
      stopResize: stopEditorPaneResize,
    } = useResizablePane({
      paneKey: 'template.field-editor.preview',
      cssVarName: '--field-editor-preview-width',
      orientation: 'vertical',
      defaultSize: 420,
      minSize: 320,
      maxSize: 620,
      enabled: () => isEditorPaneResizable.value,
    })

    const onEditorPaneViewportChange = (event) => {
      isEditorPaneResizable.value = !event.matches
      if (!isEditorPaneResizable.value) {
        stopEditorPaneResize()
      }
    }

    onMounted(() => {
      editorPaneViewportMedia = window.matchMedia(FIELD_EDITOR_MQ)
      onEditorPaneViewportChange(editorPaneViewportMedia)
      if (typeof editorPaneViewportMedia.addEventListener === 'function') {
        editorPaneViewportMedia.addEventListener('change', onEditorPaneViewportChange)
      } else if (typeof editorPaneViewportMedia.addListener === 'function') {
        editorPaneViewportMedia.addListener(onEditorPaneViewportChange)
      }
    })

    onBeforeUnmount(() => {
      stopEditorPaneResize()
      if (!editorPaneViewportMedia) return
      if (typeof editorPaneViewportMedia.removeEventListener === 'function') {
        editorPaneViewportMedia.removeEventListener('change', onEditorPaneViewportChange)
      } else if (typeof editorPaneViewportMedia.removeListener === 'function') {
        editorPaneViewportMedia.removeListener(onEditorPaneViewportChange)
      }
    })

    return {
      editorPaneStyle,
      isEditorPaneResizable,
      onEditorPaneResizeStart,
      resetEditorPaneWidth,
    }
  },
  props: {
    fields: {
      type: Array,
      default: () => [],
    },
    templateType: {
      type: String,
      default: 'excel',
    },
  },
  data() {
    return {
      editingIndex: null,
      editingField: null,
    }
  },
  methods: {
    selectField(index) {
      this.editingIndex = index
    },

    editField(index) {
      this.editingIndex = index
      this.editingField = { ...this.fields[index] }
    },

    closeEditModal() {
      this.editingField = null
    },

    saveFieldEdit() {
      if (this.editingIndex !== null && this.editingField) {
        this.$emit('update-field', this.editingIndex, { ...this.editingField })
        this.closeEditModal()
      }
    },

    toggleType(index) {
      const field = this.fields[index]
      const newType = field.type === 'fixed' ? 'dynamic' : 'fixed'
      this.$emit('update-field', index, { ...field, type: newType })
    },

    async deleteField(index) {
      if (await appConfirm('确定要删除这个字段吗？', { danger: true })) {
        this.$emit('delete-field', index)
        if (this.editingIndex === index) {
          this.editingIndex = null
        }
      }
    },

    addField() {
      this.$emit('add-field', {
        label: '新字段',
        value: '示例值',
        type: 'dynamic',
      })
    },

    onFieldChange() {
      this.$emit('fields-change', [...this.fields])
    },

    getFields() {
      return [...this.fields]
    },
  },
}
</script>

<style scoped src="./FieldEditor.css"></style>
