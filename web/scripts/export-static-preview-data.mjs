import { spawnSync } from "node:child_process";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const webDir = path.resolve(scriptDir, "..");
const repoRoot = path.resolve(webDir, "..");
const distDir = path.join(webDir, "dist");
const databasePath = path.join(repoRoot, "data", "loveca.sqlite3");
const manifestPath = path.join(repoRoot, "data", "loveca-db-manifest.json");
const outputDir = path.join(distDir, "preview-data");
const runtimeConfigPath = path.join(distDir, "runtime-config.json");
const python = process.env.PYTHON ?? "python";

if (!existsSync(databasePath)) {
  throw new Error(`Card database not found: ${databasePath}`);
}

const env = {
  ...process.env,
  PYTHONPATH: [path.join(repoRoot, "src"), process.env.PYTHONPATH].filter(Boolean).join(path.delimiter),
};

const exportResult = spawnSync(
  python,
  [
    path.join(repoRoot, "scripts", "export-preview-data.py"),
    "--database",
    databasePath,
    "--output-dir",
    outputDir,
    "--effect-registry",
    path.join(repoRoot, "data_sources", "effect-registry.v0.json"),
  ],
  {
    cwd: repoRoot,
    env,
    stdio: "inherit",
  },
);

if (exportResult.error) {
  throw exportResult.error;
}
if (exportResult.status !== 0) {
  process.exit(exportResult.status ?? 1);
}

if (existsSync(runtimeConfigPath) && existsSync(manifestPath)) {
  const runtimeConfig = JSON.parse(readFileSync(runtimeConfigPath, "utf8"));
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  if (!runtimeConfig.apiBaseUrl) {
    runtimeConfig.mode = "preview";
    runtimeConfig.browserPreview = true;
  }
  runtimeConfig.cardDatabaseFingerprint = manifest.card_database_fingerprint ?? "";
  writeFileSync(runtimeConfigPath, `${JSON.stringify(runtimeConfig, null, 2)}\n`, "utf8");
}
