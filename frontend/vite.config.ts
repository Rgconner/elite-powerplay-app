/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      // All /api/* requests proxied to the FastAPI backend during local dev.
      "/api": "http://localhost:8000",
    },
  },
  test: {
    // Run tests in a jsdom environment so DOM globals are available if needed.
    environment: "node",
    // Only pick up *.test.ts / *.test.tsx files.
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
