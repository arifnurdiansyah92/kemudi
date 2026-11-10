# Kemudi web UI: build with Node, serve the static files with nginx.
FROM node:22-alpine AS build
WORKDIR /app
# corepack in some Node 22 images predates npm's current signing keys, so
# install the pnpm version pinned in package.json directly.
RUN npm install -g pnpm@10.30.1
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

FROM nginx:1.27-alpine
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
