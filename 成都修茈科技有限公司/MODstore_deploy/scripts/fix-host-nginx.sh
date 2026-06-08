#!/bin/sh
CONF=/etc/nginx/conf.d/xiu-ci.com.conf

# Add proxy_intercept_errors off to the API location blocks
# This prevents Nginx from intercepting 404s from FastAPI and serving HTML error pages

# Fix location ~ ^/(api|modstore)/
sed -i '/location ~ \^\/(api|modstore)\//,/}/ {
    /proxy_buffering off/a\        proxy_intercept_errors off;
}' "$CONF"

# Fix location /api/
sed -i '/location \/api\/ {/,/}/ {
    /proxy_set_header X-Forwarded-Proto/a\        proxy_intercept_errors off;
}' "$CONF"

# Fix location ^~ /api/realtime/
sed -i '/location \^~ \/api\/realtime\//,/}/ {
    /proxy_buffering off/a\        proxy_intercept_errors off;
}' "$CONF"

# Fix location /v1/
sed -i '/location \/v1\//,/}/ {
    /proxy_buffering off/a\        proxy_intercept_errors off;
}' "$CONF"

# Test and reload
nginx -t && nginx -s reload && echo "Nginx reloaded OK"
