/**
 * Copies web-ifc.wasm from node_modules to public/vendor/web-ifc/
 * so Vite serves it locally without a CDN dependency.
 *
 * Run automatically via the predev / prebuild npm scripts.
 */

import { mkdir, copyFile } from "node:fs/promises"
import { resolve, dirname } from "node:path"
import { fileURLToPath } from "node:url"

const __dirname = dirname(fileURLToPath(import.meta.url))
const root = resolve(__dirname, "..")

const src = resolve(root, "node_modules/web-ifc/web-ifc.wasm")
const destDir = resolve(root, "public/vendor/web-ifc")
const dest = resolve(destDir, "web-ifc.wasm")

await mkdir(destDir, { recursive: true })
await copyFile(src, dest)

console.log("sync-viewer-assets: copied web-ifc.wasm → public/vendor/web-ifc/")
