import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Em desenvolvimento (npm run dev) as chamadas a /api vão para a API local.
// Em produção, o Nginx do contêiner faz o mesmo proxy (ver nginx.conf).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://localhost:8000", changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, "") } },
  },
});
