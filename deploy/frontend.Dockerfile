FROM nginxinc/nginx-unprivileged:1.28-alpine
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY public/program-studio.html /usr/share/nginx/html/index.html
COPY public/program-studio.js public/program-studio.css public/program-editor.js public/workspace.js public/usage.js public/workspace.css /usr/share/nginx/html/
COPY public/brand.png public/brand.svg public/favicon.png public/favicon.svg public/favicon.ico /usr/share/nginx/html/
EXPOSE 8000
