<template>
  <div class="transition-overlay" id="transitionOverlay"></div>

  <div class="preview-float-window" id="previewFloatWindow">
    <div class="preview-header">
      <h4><i class="fa fa-television" aria-hidden="true"></i> 媒体预览</h4>
      <button class="preview-close" id="previewCloseBtn" data-close-action="closePreviewWindow">&times;</button>
    </div>
    <div class="preview-content">
      <div class="preview-media" id="previewMedia">
        <div class="preview-placeholder">暂无预览内容</div>
      </div>
    </div>
  </div>

  <div class="progress-panel" id="progressPanel">
    <div class="progress-panel-header">
      <div class="progress-title">任务进度</div>
      <button class="progress-close" id="progressCloseBtn" data-close-action="hideProgress">&times;</button>
    </div>
    <div class="progress-info">
      <span class="progress-status">处理中...</span>
      <span class="progress-percent" id="progressPercent">0%</span>
    </div>
    <div class="progress-bar-wrapper">
      <div class="progress-bar-fill" id="progressBarFill" style="width: 0%;"></div>
    </div>
    <div class="progress-task" id="progressTask">正在初始化任务...</div>
  </div>

  <div class="file-upload-entry" id="fileUploadEntry">
    <span class="entry-icon" aria-hidden="true"><i class="fa fa-folder-open-o"></i></span>
    <span class="entry-text">上传文件</span>
  </div>

  <div class="import-float-window" id="importFloatWindow">
    <div class="import-header">
      <h4><i class="fa fa-folder-open-o" aria-hidden="true"></i> 导入文件</h4>
      <button class="import-close" id="importCloseBtn" data-close-action="closeImportWindow">&times;</button>
    </div>
    <div class="import-content">
      <div class="drop-zone" id="dropZone">
        <div class="drop-zone-icon" aria-hidden="true"><i class="fa fa-folder-open"></i></div>
        <div class="drop-zone-text">拖拽文件到此处或点击选择</div>
        <div class="drop-zone-hint">支持 Excel、CSV、图片等文件</div>
      </div>
      <input type="file" class="file-input" id="fileInput" multiple accept="*/*">
      <div class="import-actions">
        <button class="btn btn-primary" id="chooseFileBtn">选择文件</button>
        <button class="btn btn-success" id="openCameraBtn"><i class="fa fa-camera" aria-hidden="true"></i> 拍照识别</button>
        <button class="btn btn-secondary" id="cancelImportBtn" data-close-action="closeImportWindow">取消</button>
      </div>
      <div class="camera-panel" id="cameraPanel" style="display: none;">
        <video id="cameraVideo" autoplay playsinline></video>
        <canvas id="cameraCanvas" style="display: none;"></canvas>
        <div class="camera-buttons">
          <button class="btn btn-primary" id="capturePhotoBtn">拍照</button>
          <button class="btn btn-secondary" id="closeCameraBtn" data-close-action="closeCamera">关闭</button>
        </div>
      </div>
      <div class="import-progress" id="importProgress">
        <div class="progress-bar-container">
          <div class="progress-bar" id="progressBar"></div>
        </div>
        <div class="progress-text">
          <span id="progressText">读取中...</span>
          <span id="importProgressPercent">0%</span>
        </div>
      </div>
      <div class="import-status" id="importStatus"></div>
    </div>
  </div>

  <div class="import-float-window" id="labelsExportWindow">
    <div class="import-header">
      <h4><i class="fa fa-tag" aria-hidden="true"></i> 商标导出</h4>
      <button class="import-close" id="labelsExportCloseBtn" type="button" title="关闭">&times;</button>
    </div>
    <div class="import-content">
      <div id="labelsExportList" class="labels-export-list">
        <p class="labels-export-hint">暂无标签文件（发货任务生成后可在此下载）</p>
      </div>
      <div class="import-actions" style="margin-top: 12px;">
        <button class="btn btn-secondary" id="labelsExportCloseBtn2" type="button">关闭</button>
      </div>
    </div>
  </div>

  <div class="import-float-window" id="printPanelWindow">
    <div class="import-header">
      <h4><i class="fa fa-print" aria-hidden="true"></i> 标签打印</h4>
      <button class="import-close" id="printPanelCloseBtn" type="button" title="关闭">&times;</button>
    </div>
    <div class="import-content">
      <div id="printPanelStatus" class="labels-export-hint">正在连接打印机...</div>
      <div id="printPanelProgress" class="print-panel-progress" style="display:none; margin:10px 0;"></div>
      <div id="printPanelResults" class="print-panel-results" style="margin:10px 0; max-height:240px; overflow-y:auto;"></div>
      <div class="import-actions" style="margin-top: 12px;">
        <button class="btn btn-primary" id="printPanelStartBtn" type="button">开始打印</button>
        <button class="btn btn-secondary" id="printPanelCloseBtn2" type="button">关闭</button>
      </div>
    </div>
  </div>

  <div id="labelFloatPreviews" class="label-float-previews hidden" aria-hidden="true"></div>

  <div id="labelPreviewModal" class="label-preview-modal hidden" aria-hidden="true">
    <div class="label-preview-modal-backdrop"></div>
    <div class="label-preview-modal-content">
      <img id="labelPreviewModalImg" src="" alt="标签预览" />
      <div class="label-preview-modal-actions">
        <a id="labelPreviewModalDownload" href="" download="" class="btn btn-primary">下载标签</a>
        <button type="button" class="btn btn-secondary label-preview-modal-close">关闭</button>
      </div>
    </div>
  </div>
</template>
