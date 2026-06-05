# Multi-stage build for production frontend
# Stage 1: Build the production bundle
FROM node:20-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# Stage 2: Production runtime with lightweight Node.js server
FROM node:20-alpine AS runtime

# Create non-root user
RUN addgroup -g 1001 appgroup && adduser -u 1001 -G appgroup -D appuser

WORKDIR /app

# Install production server deps
COPY --chown=appuser:appuser package.json package-lock.json ./
RUN npm ci --omit=dev && npm install http-proxy

# Copy built assets and server
COPY --from=builder --chown=appuser:appuser /app/dist ./dist
COPY --chown=appuser:appuser server.js .

USER appuser

EXPOSE 3000

HEALTHCHECK --interval=15s --timeout=5s --retries=3 --start-period=10s \
    CMD wget -q -O /dev/null http://localhost:3000/ || exit 1

CMD ["node", "server.js"]
