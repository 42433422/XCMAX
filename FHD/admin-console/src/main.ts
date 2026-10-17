/**
 * XCMAX 平台运维台独立入口（构建产物 templates/admin-vue-dist，挂载 /admin）。
 * 业务组件与路由主体复用 frontend/src，运维专属源码在 admin-console/src。
 */
import 'font-awesome/css/font-awesome.min.css';
import '@host/main';

// 图标字体随管理端本地打包（不走 CDN）；启动即请求字体，不等首次绘制，避免后台/被遮挡窗口里图标一直是占位方块。
void document.fonts?.load('14px FontAwesome').catch(() => undefined);
