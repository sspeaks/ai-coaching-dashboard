import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { mkdir, readdir, rm, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { inflateSync, deflateSync } from "node:zlib";
import { chromium } from "playwright";

const FIXED_RENDER_TIME = "2026-08-12T12:00:00.000Z";
const VIEWPORTS = [
  { name: "phone-390x844", width: 390, height: 844 },
  { name: "narrow-phone-360x800", width: 360, height: 800 },
  { name: "desktop-1440x900", width: 1440, height: 900 },
];

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const webRoot = path.resolve(__dirname, "..");
const repoRoot = path.resolve(webRoot, "..", "..");
const captureDate = process.env.UX_CAPTURE_DATE ?? new Date().toISOString().slice(0, 10);
const outputRoot = path.join(repoRoot, ".squad", "files", "ux-review", captureDate);
const baseUrl = "http://127.0.0.1:5173";

const states = [
  {
    file: "01-feedback-empty-first-run.png",
    description: "opened Feedback before any recordings have been added.",
    run: async (page) => {
      await page.goto(`${baseUrl}/?mockState=empty`);
      await page.getByRole("heading", { name: "No feedback yet" }).waitFor();
    },
  },
  {
    file: "02-upload-ready-idle.png",
    description: "opened Upload before choosing a recording; the form is ready for a file.",
    run: async (page) => {
      await page.goto(`${baseUrl}/upload?mockState=empty`);
      await page.getByRole("heading", { name: "Upload a coaching recording" }).waitFor();
      await page.getByRole("button", { name: "Upload recording" }).waitFor();
    },
  },
  {
    file: "03-upload-in-progress.png",
    description: "upload is partway through, progress is visible, and upload controls are disabled.",
    run: async (page) => {
      await page.goto(`${baseUrl}/upload?mockState=upload-progress`);
      await page.getByRole("heading", { name: "Upload a coaching recording" }).waitFor();
      await page.getByLabel("Audio file").setInputFiles({
        name: "synthetic-quartet-upload.wav",
        mimeType: "audio/wav",
        buffer: Buffer.from("synthetic audio for ux capture"),
      });
      await page.getByRole("button", { name: "Upload recording" }).click();
      await page.locator(".upload-progress strong", { hasText: "46%" }).waitFor();
    },
  },
  {
    file: "04-feedback-processing-transcribing.png",
    description: "opened Feedback while a recording is being transcribed; processing progress is visible.",
    run: async (page) => {
      await page.goto(`${baseUrl}/?mockState=processing`);
      await page.getByRole("heading", { name: "Coaching notes are not ready yet" }).waitFor();
      await page.locator(".processing-progress").waitFor();
    },
  },
  {
    file: "05-feedback-failed-error.png",
    description: "opened Feedback after processing failed; the error message and recovery guidance are visible.",
    run: async (page) => {
      await page.goto(`${baseUrl}/?mockState=failed`);
      await page.getByText("We could not finish this recording.").waitFor();
    },
  },
  {
    file: "06-feedback-awaiting-review.png",
    description: "opened Feedback when coaching notes are ready but have not all been reviewed.",
    run: async (page) => {
      await page.goto(`${baseUrl}/?mockState=awaiting-review`);
      await page.getByRole("heading", { name: "What the coach worked on" }).waitFor();
      await page.getByRole("button", { name: /See every coaching note/ }).click();
      await page.getByText("Not checked").first().waitFor();
    },
  },
  {
    file: "07-feedback-reviewed-complete.png",
    description: "opened Feedback after all coaching notes have been reviewed and the session is complete.",
    run: async (page) => {
      await page.goto(`${baseUrl}/?mockState=complete`);
      await page.getByRole("heading", { name: "What the coach worked on" }).waitFor();
      await page.getByRole("button", { name: /See every coaching note/ }).click();
      await page.getByText("Checked").first().waitFor();
    },
  },
].sort((a, b) => a.file.localeCompare(b.file));

main().catch((error) => {
  console.error(error instanceof Error ? error.stack : error);
  process.exit(1);
});

async function main() {
  if (!process.env.PLAYWRIGHT_BROWSERS_PATH) {
    throw new Error(
      "PLAYWRIGHT_BROWSERS_PATH is not set. Run UX capture inside `nix develop` so Nix provides reproducible Playwright browsers.",
    );
  } else if (!existsSync(process.env.PLAYWRIGHT_BROWSERS_PATH)) {
    throw new Error(`PLAYWRIGHT_BROWSERS_PATH does not exist: ${process.env.PLAYWRIGHT_BROWSERS_PATH}`);
  }
  await assertPlaywrightNixAlignment(process.env.PLAYWRIGHT_BROWSERS_PATH);

  await rm(outputRoot, { recursive: true, force: true });
  await mkdir(outputRoot, { recursive: true });

  const server = startServer();
  try {
    await waitForReady(`${baseUrl}/`);
    const browser = await chromium.launch({
      headless: true,
      executablePath: await chromiumExecutablePath(),
    });
    const manifest = {
      generatedAt: new Date().toISOString(),
      fixedRenderTime: FIXED_RENDER_TIME,
      command: "cd apps/web && npm run ux:capture",
      outputRoot: path.relative(repoRoot, outputRoot),
      viewports: VIEWPORTS.map(({ name, width, height }) => ({ name, width, height })),
      shots: [],
      caveats: [
        "Only states reachable through the current mock client are captured.",
        "No backend, real audio processing, or credentials are required.",
      ],
    };

    try {
      for (const viewport of VIEWPORTS) {
        const viewportDir = path.join(outputRoot, viewport.name);
        await mkdir(viewportDir, { recursive: true });
        for (const state of states) {
          const page = await newPage(browser, viewport);
          try {
            await state.run(page);
            await stabilize(page);
            const outPath = path.join(viewportDir, state.file);
            const screenshot = await page.screenshot({
              fullPage: true,
              animations: "disabled",
              caret: "hide",
            });
            await writeFile(outPath, canonicalizePng(screenshot));
            const size = (await stat(outPath)).size;
            if (size <= 0) throw new Error(`Screenshot is empty: ${outPath}`);
            manifest.shots.push({
              file: path.relative(outputRoot, outPath),
              viewport: viewport.name,
              state: state.file.replace(/\.png$/, ""),
              description: state.description,
              bytes: size,
            });
          } finally {
            await page.close().catch(() => undefined);
          }
        }
      }
    } finally {
      await browser.close().catch(() => undefined);
    }

    await writeFile(
      path.join(outputRoot, "manifest.json"),
      `${JSON.stringify(manifest, null, 2)}\n`,
    );
    console.log(`Captured ${manifest.shots.length} screenshots in ${path.relative(repoRoot, outputRoot)}`);
  } finally {
    await stopServer(server);
  }
}

function canonicalizePng(input) {
  const signature = input.subarray(0, 8);
  if (!signature.equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))) {
    throw new Error("Screenshot was not a PNG.");
  }

  let offset = 8;
  let ihdr;
  const idat = [];
  while (offset < input.length) {
    const length = input.readUInt32BE(offset);
    const type = input.subarray(offset + 4, offset + 8).toString("ascii");
    const data = input.subarray(offset + 8, offset + 8 + length);
    offset += 12 + length;
    if (type === "IHDR") ihdr = Buffer.from(data);
    if (type === "IDAT") idat.push(data);
    if (type === "IEND") break;
  }
  if (!ihdr || idat.length === 0) throw new Error("Screenshot PNG is missing IHDR or IDAT chunks.");

  const pixelStream = inflateSync(Buffer.concat(idat));
  const compressed = deflateSync(pixelStream, { level: 9 });
  return Buffer.concat([
    signature,
    pngChunk("IHDR", ihdr),
    pngChunk("IDAT", compressed),
    pngChunk("IEND", Buffer.alloc(0)),
  ]);
}

function pngChunk(type, data) {
  const typeBuffer = Buffer.from(type, "ascii");
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(Buffer.concat([typeBuffer, data])));
  return Buffer.concat([length, typeBuffer, data, crc]);
}

function crc32(buffer) {
  let crc = 0xffffffff;
  for (const byte of buffer) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) {
      crc = crc & 1 ? (crc >>> 1) ^ 0xedb88320 : crc >>> 1;
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}

async function assertPlaywrightNixAlignment(browsersPath) {
  const npmVersion = require("playwright/package.json").version;
  const nixVersion = process.env.PLAYWRIGHT_NIX_DRIVER_VERSION ?? "unknown";
  const browsersJsonPath = path.join(path.dirname(require.resolve("playwright-core/package.json")), "browsers.json");
  const browsersJson = JSON.parse(readFileSync(browsersJsonPath, "utf8"));
  const expectedChromium = browsersJson.browsers.find((browser) => browser.name === "chromium");
  if (!expectedChromium?.revision) {
    throw new Error(`Could not determine npm Playwright ${npmVersion} Chromium revision from ${browsersJsonPath}`);
  }

  const entries = await readdir(browsersPath, { withFileTypes: true });
  const chromiumEntry = entries.find((entry) => /^chromium-\d+$/.test(entry.name));
  const actualRevision = chromiumEntry?.name.match(/^chromium-(\d+)$/)?.[1];
  if (nixVersion !== "unknown" && nixVersion !== npmVersion) {
    throw new Error(
      `Playwright/Nix version mismatch: npm playwright ${npmVersion} but Nix playwright-driver ${nixVersion}. ` +
        "Pin apps/web's playwright dependency to the Nix driver version or update flake.lock so they match exactly.",
    );
  }
  if (actualRevision !== expectedChromium.revision) {
    throw new Error(
      `Playwright/Nix browser mismatch: npm playwright ${npmVersion} expects chromium-${expectedChromium.revision}, ` +
        `but Nix playwright-driver ${nixVersion} provides ${chromiumEntry?.name ?? "no chromium-* browser"} in ${browsersPath}. ` +
        "Do not use npx playwright install; align apps/web/package-lock.json with flake.lock instead.",
    );
  }
}

function startServer() {
  const child = spawn("npm", ["run", "dev", "--", "--host", "127.0.0.1", "--port", "5173"], {
    cwd: webRoot,
    env: {
      ...process.env,
      VITE_API_MODE: "mock",
      PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD: "1",
      FORCE_COLOR: "0",
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  const output = [];
  const remember = (chunk) => {
    output.push(chunk.toString());
    if (output.length > 80) output.shift();
  };
  child.stdout.on("data", remember);
  child.stderr.on("data", remember);
  child.recentOutput = () => output.join("");
  return child;
}

async function stopServer(child) {
  if (child.exitCode !== null) return;
  child.kill("SIGTERM");
  await new Promise((resolve) => {
    const timeout = setTimeout(resolve, 5_000);
    child.once("exit", () => {
      clearTimeout(timeout);
      resolve();
    });
  });
  if (child.exitCode === null) child.kill("SIGKILL");
}

async function waitForReady(url) {
  const deadline = Date.now() + 30_000;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
      lastError = new Error(`HTTP ${response.status}`);
    } catch (error) {
      lastError = error;
    }
    await delay(250);
  }
  throw new Error(`Vite did not become ready at ${url}: ${lastError?.message ?? "timeout"}`);
}

async function newPage(browser, viewport) {
  const context = await browser.newContext({
    viewport: { width: viewport.width, height: viewport.height },
    deviceScaleFactor: 1,
    reducedMotion: "reduce",
    colorScheme: "light",
    locale: "en-US",
    timezoneId: "America/Los_Angeles",
  });
  await context.addInitScript(({ fixedTime }) => {
    const RealDate = Date;
    const fixed = new RealDate(fixedTime).getTime();
    class FrozenDate extends RealDate {
      constructor(...args) {
        super(...(args.length === 0 ? [fixed] : args));
      }
      static now() {
        return fixed;
      }
    }
    FrozenDate.UTC = RealDate.UTC;
    FrozenDate.parse = RealDate.parse;
    FrozenDate.prototype = RealDate.prototype;
    globalThis.Date = FrozenDate;
    Math.random = () => 0.123456789;
  }, { fixedTime: FIXED_RENDER_TIME });
  const page = await context.newPage();
  await page.addStyleTag({
    content: `
      *, *::before, *::after {
        animation-delay: 0s !important;
        animation-duration: 0s !important;
        animation-iteration-count: 1 !important;
        scroll-behavior: auto !important;
        transition-delay: 0s !important;
        transition-duration: 0s !important;
      }
      .spinner { animation: none !important; }
    `,
  }).catch(() => undefined);
  return page;
}

async function stabilize(page) {
  await page.addStyleTag({
    content: `
      *, *::before, *::after {
        animation: none !important;
        transition: none !important;
        caret-color: transparent !important;
      }
    `,
  });
  await page.evaluate(async () => {
    window.scrollTo(0, 0);
    await document.fonts?.ready?.catch?.(() => undefined);
  });
  await page.waitForTimeout(100);
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function chromiumExecutablePath() {
  if (process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH) {
    return process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;
  }
  const browsersPath = process.env.PLAYWRIGHT_BROWSERS_PATH;
  if (!browsersPath) return undefined;

  const preferred = [
    ["chromium", "chrome-linux64", "chrome"],
    ["chromium_headless_shell", "chrome-headless-shell-linux64", "chrome-headless-shell"],
  ];
  const entries = await readdir(browsersPath, { withFileTypes: true });
  for (const [prefix, subdir, executable] of preferred) {
    const match = entries.find((entry) => entry.name.startsWith(`${prefix}-`));
    if (!match) continue;
    const candidate = path.join(browsersPath, match.name, subdir, executable);
    if (existsSync(candidate)) return candidate;
  }
  return undefined;
}
