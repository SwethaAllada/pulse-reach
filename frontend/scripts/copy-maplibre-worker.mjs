// MapLibre runs tile decoding in a web worker that bundlers do not emit; serve the
// published worker file from /vendor (copied from node_modules, never committed).
import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const out = join(root, "public", "vendor");
mkdirSync(out, { recursive: true });
copyFileSync(join(root, "node_modules", "maplibre-gl", "dist", "maplibre-gl-worker.mjs"), join(out, "maplibre-gl-worker.mjs"));
