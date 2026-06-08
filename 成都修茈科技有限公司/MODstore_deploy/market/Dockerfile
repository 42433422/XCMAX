FROM node:20-alpine AS build

WORKDIR /app
COPY package*.json ./
# node:20-alpine 自带 npm 10.8.x 对部分 lockfile 会抛 edgesOut；先升级 npm 再 ci
RUN npm install -g npm@11.13.0 && npm ci
COPY . .

ARG VITE_XCAGI_DOWNLOAD_VERSION=10.0.0
ARG VITE_XCAGI_ANDROID_VERSION=10.0.0
ARG VITE_XCAGI_DOWNLOAD_BASE_URL=https://xiu-ci.com/xcagi-v10.0.0
ENV VITE_XCAGI_DOWNLOAD_VERSION=$VITE_XCAGI_DOWNLOAD_VERSION
ENV VITE_XCAGI_ANDROID_VERSION=$VITE_XCAGI_ANDROID_VERSION
ENV VITE_XCAGI_DOWNLOAD_BASE_URL=$VITE_XCAGI_DOWNLOAD_BASE_URL
RUN npm run build

FROM nginx:1.27-alpine

COPY nginx-errors/ /etc/nginx/errors/
COPY nginx-snippets/ /etc/nginx/snippets/
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html/market

EXPOSE 80
