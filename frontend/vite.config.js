import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
// 127.0.0.1 (nunca "localhost") e porta 8100: em Windows, "localhost" pode
// resolver para ::1, onde o Docker/WSL segura a porta 8000 de outros projetos.
var backendTarget = "http://127.0.0.1:8100";
export default defineConfig({
    plugins: [react()],
    test: {
        environment: "node",
        include: ["src/**/*.test.ts"],
    },
    server: {
        host: "0.0.0.0",
        port: 5173,
        proxy: {
            "/health": backendTarget,
            "/mode": backendTarget,
            "/version": backendTarget,
            "/auth": backendTarget,
            "/market-data": backendTarget,
            "/signals": backendTarget,
            "/backtests": backendTarget,
            "/strategy-combinations": backendTarget,
            "/broker-connections": backendTarget,
            "/realtime": { target: backendTarget, ws: true },
        },
    },
});
