import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

export default defineConfig({
  ...base,
  testDir: "./demo",
  outputDir: `${process.env.E2E_OUTPUT_DIR || "../docs/verification/portfolio-demo"}/browser-artifacts`,
  timeout: 120000,
  use: {
    ...base.use,
    launchOptions: { slowMo: 120 },
    video: { mode: "on", size: { width: 1440, height: 1000 } },
  },
});
