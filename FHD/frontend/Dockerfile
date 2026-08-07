# Frontend Dockerfile for Vue.js
#
# 复用 release-orchestrator 的 build-frontend 产出的共享 templates/vue-dist，
# 不再在镜像内 npx vite build —— 确保网页镜像与桌面端内嵌的是字节级同一份前端，
# 消除「网页≠桌面」与反复打包漂移/回退。
#
# 构建上下文必须是 FHD/（templates/vue-dist 与 frontend/nginx.conf 都在上下文内），
# 由 release-web.yml 的 docker job 指定 context: FHD。

# Production stage
FROM nginx:alpine as production

COPY templates/vue-dist /usr/share/nginx/html

COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]