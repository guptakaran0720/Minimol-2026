import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The node serves the built app at /ui (node/main.py). In `npm run dev`, API calls
// are proxied to a local node; set NODE_URL to point at another one.
const node = process.env.NODE_URL ?? "http://127.0.0.1:8001";

export default defineConfig({
  base: "/ui/",
  plugins: [react()],
  server: {
    proxy: Object.fromEntries(["/stats", "/files", "/recover", "/events"].map((p) => [p, node])),
  },
});
