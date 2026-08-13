import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir, readdir, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const VIEWPORTS = [
  { name: "phone-390x844", width: 390, height: 844 },
  { name: "narrow-phone-360x800", width: 360, height: 800 },
];
const FIXED_RENDER_TIME = "2026-08-12T12:00:00.000Z";
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(__dirname, "..");
const repoRoot = path.resolve(webRoot, "..", "..");
const outputDate = process.env.UX_CAPTURE_DATE ?? new Date().toISOString().slice(0, 10);
const outputRoot = path.join(repoRoot, ".squad", "files", "ux-review", outputDate);
const baseUrl = "http://127.0.0.1:5173";

main().catch((error) => {
  console.error(error instanceof Error ? error.stack : error);
  process.exit(1);
});

async function main() {
  if (!process.env.PLAYWRIGHT_BROWSERS_PATH) {
    throw new Error(
      "PLAYWRIGHT_BROWSERS_PATH is not set. Run inside `nix develop` so Nix provides Playwright browsers.",
    );
  }

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
      command: "cd apps/web && npm run test:phone-audio-controls",
      outputRoot: path.relative(repoRoot, outputRoot),
      viewports: VIEWPORTS,
      assertions: [],
      screenshots: [],
    };

    try {
      for (const viewport of VIEWPORTS) {
        const viewportDir = path.join(outputRoot, viewport.name);
        await mkdir(viewportDir, { recursive: true });
        const page = await newPage(browser, viewport);
        try {
          await openSummaryAndPlay(page, "summary-source-moment-1-74000");
          const first = await assertVisibleNativeControls(page, viewport.name);
          manifest.assertions.push(first);
          const firstProgress = await assertProgressTracksAudio(page, 74, 286);
          manifest.assertions.push({
            viewport: viewport.name,
            type: "mini-playhead",
            ...firstProgress,
          });
          const postTapPath = path.join(
            viewportDir,
            "issue54-first-summary-control-post-tap-active.png",
          );
          await saveScreenshot(page, postTapPath);
          manifest.screenshots.push(path.relative(outputRoot, postTapPath));

          await page.locator(".audio-section").scrollIntoViewIfNeeded();
          const controlsPath = path.join(
            viewportDir,
            "issue54-native-audio-controls-scroll-target.png",
          );
          await saveScreenshot(page, controlsPath);
          manifest.screenshots.push(path.relative(outputRoot, controlsPath));

          await openSummaryAndPlay(page, "summary-source-moment-2-132000");
          const secondProgress = await assertProgressTracksAudio(page, 132, 286);
          manifest.assertions.push({
            viewport: viewport.name,
            type: "mini-playhead-second-moment",
            ...secondProgress,
          });
        } finally {
          await page.close().catch(() => undefined);
        }
      }
    } finally {
      await browser.close().catch(() => undefined);
    }

    await writeFile(
      path.join(outputRoot, "issue54-phone-audio-controls-manifest.json"),
      `${JSON.stringify(manifest, null, 2)}\n`,
    );
    console.log(
      `Issue #54 phone audio controls visible at ${VIEWPORTS.map((viewport) => `${viewport.width}x${viewport.height}`).join(" and ")}`,
    );
    console.log(`Captured screenshots in ${path.relative(repoRoot, outputRoot)}`);
  } finally {
    await stopServer(server);
  }
}

function startServer() {
  return spawn("npm", ["run", "dev", "--", "--host", "127.0.0.1", "--port", "5173"], {
    cwd: webRoot,
    env: {
      ...process.env,
      VITE_API_MODE: "mock",
      PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD: "1",
      FORCE_COLOR: "0",
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
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
    const currentTimes = new WeakMap();
    Object.defineProperty(HTMLMediaElement.prototype, "duration", {
      configurable: true,
      get() {
        return Number(this.dataset.testDuration ?? 286);
      },
    });
    Object.defineProperty(HTMLMediaElement.prototype, "currentTime", {
      configurable: true,
      get() {
        return currentTimes.get(this) ?? 0;
      },
      set(value) {
        currentTimes.set(this, Number(value));
      },
    });
    HTMLMediaElement.prototype.play = function play() {
      this.dispatchEvent(new Event("play"));
      return Promise.resolve();
    };
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
    `,
  }).catch(() => undefined);
  return page;
}

async function openSummaryAndPlay(page, testId) {
  await page.goto(`${baseUrl}/?mockState=complete`);
  await page.getByRole("heading", { name: "What the coach worked on" }).waitFor();
  const button = page.getByTestId(testId);
  await button.scrollIntoViewIfNeeded();
  await button.click();
  await page.locator(".audio-section--active audio[controls]").waitFor();
  await page.waitForFunction(() => {
    const audio = document.querySelector(".audio-section--active audio[controls]");
    return audio && audio.getBoundingClientRect().height > 0;
  });
}

async function assertVisibleNativeControls(page, viewportName) {
  const result = await page.evaluate(() => {
    const audio = document.querySelector(".audio-section--active audio[controls]");
    if (!(audio instanceof HTMLAudioElement)) {
      throw new Error("No active native audio controls were rendered.");
    }
    const style = getComputedStyle(audio);
    const rect = audio.getBoundingClientRect();
    return {
      viewport: { width: innerWidth, height: innerHeight, scrollY },
      display: style.display,
      visibility: style.visibility,
      width: rect.width,
      height: rect.height,
      top: rect.top,
      bottom: rect.bottom,
      controls: audio.controls,
    };
  });
  if (!result.controls) throw new Error(`${viewportName}: audio element lacks controls`);
  if (result.display === "none") throw new Error(`${viewportName}: audio controls are display:none`);
  if (result.visibility === "hidden") throw new Error(`${viewportName}: audio controls are hidden`);
  if (result.width <= 0 || result.height <= 0) {
    throw new Error(`${viewportName}: audio controls have zero rendered size ${result.width}x${result.height}`);
  }
  if (result.bottom <= 0 || result.top >= result.viewport.height) {
    throw new Error(`${viewportName}: audio controls are offscreen`);
  }
  return { viewport: viewportName, type: "native-controls", ...result };
}

async function assertProgressTracksAudio(page, currentTime, duration) {
  return page.evaluate(
    ({ currentTime: nextCurrentTime, duration: nextDuration }) => {
      const audio = document.querySelector(".audio-section--active audio");
      const track = document.querySelector(".now-playing-cue--section .now-playing-cue__track");
      const fill = track?.querySelector("span");
      if (!(audio instanceof HTMLAudioElement) || !track || !(fill instanceof HTMLElement)) {
        throw new Error("Missing audio or now-playing progress track.");
      }
      audio.dataset.testDuration = String(nextDuration);
      audio.currentTime = nextCurrentTime;
      audio.dispatchEvent(new Event("timeupdate"));
      const expectedPercent = (nextCurrentTime / nextDuration) * 100;
      const actualPercent = Number.parseFloat(fill.style.width);
      const trackWidth = track.getBoundingClientRect().width;
      const fillWidth = fill.getBoundingClientRect().width;
      const renderedPercent = trackWidth > 0 ? (fillWidth / trackWidth) * 100 : Number.NaN;
      if (Math.abs(actualPercent - expectedPercent) > 0.01) {
        throw new Error(`Expected style width ${expectedPercent}%, got ${fill.style.width}`);
      }
      if (Math.abs(renderedPercent - expectedPercent) > 1) {
        throw new Error(`Expected rendered width near ${expectedPercent}%, got ${renderedPercent}%`);
      }
      return {
        currentTime: nextCurrentTime,
        duration: nextDuration,
        expectedPercent,
        actualStyleWidth: fill.style.width,
        renderedPercent,
      };
    },
    { currentTime, duration },
  );
}

async function saveScreenshot(page, outPath) {
  const screenshot = await page.screenshot({
    path: outPath,
    fullPage: false,
    animations: "disabled",
    caret: "hide",
  });
  const size = (await stat(outPath)).size;
  if (size <= 0 || screenshot.length <= 0) throw new Error(`Screenshot is empty: ${outPath}`);
}

async function chromiumExecutablePath() {
  if (process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH) {
    return process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;
  }
  const browsersPath = process.env.PLAYWRIGHT_BROWSERS_PATH;
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

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
