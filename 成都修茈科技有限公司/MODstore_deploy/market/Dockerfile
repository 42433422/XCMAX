FROM node:20-alpine AS build

WORKDIR /app
COPY package*.json ./
# node:20-alpine 自带 npm 10.8.x 对部分 lockfile 会抛 edgesOut；先升级 npm 再 ci
RUN npm install -g npm@11.13.0 && npm ci
COPY . .

RUN npm run build

FROM nginx:1.27-alpine

COPY nginx-errors/ /etc/nginx/errors/
COPY nginx-snippets/ /etc/nginx/snippets/
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html/market

EXPOSE 80
