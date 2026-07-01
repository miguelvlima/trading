import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

const backendTarget = "http://localhost:8000";

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
