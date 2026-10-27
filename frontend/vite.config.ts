import { defineConfig } from "vite";
import path from "node:path";

export default defineConfig({
  root: __dirname,
  base: "./",
  server: { host: "127.0.0.1", port: 5173, strictPort: true },
  build: {
    outDir: path.resolve(__dirname, "dist", "ui"),
    emptyOutDir: false,
  },
});
