import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

// the same "@/" alias as tsconfig, so tests can import app code the way the app does
export default defineConfig({
  resolve: { alias: { "@": fileURLToPath(new URL("./", import.meta.url)) } },
});
