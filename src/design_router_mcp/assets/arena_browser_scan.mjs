import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const [htmlPath, outputDir, shotsFlag] = process.argv.slice(2);
const shots = shotsFlag === "1";
const viewports = [
  { name: "desktop-1512", width: 1512, height: 812 },
  { name: "desktop-1280", width: 1280, height: 800 },
  { name: "tablet-768", width: 768, height: 1024 },
  { name: "mobile-390", width: 390, height: 844 },
  { name: "mobile-360", width: 360, height: 780 },
];

let chromium;
try {
  const require = createRequire(import.meta.url);
  ({ chromium } = require("playwright"));
} catch (error) {
  process.stdout.write(JSON.stringify({ available: false, reason: `playwright unavailable: ${error.message}` }));
  process.exit(0);
}

fs.mkdirSync(outputDir, { recursive: true });
const browser = await chromium.launch({ headless: true });
const rows = [];
try {
  for (const viewport of viewports) {
    const page = await browser.newPage({ viewport: { width: viewport.width, height: viewport.height } });
    const consoleErrors = [];
    const pageErrors = [];
    const blockedRequests = [];
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await page.route("**/*", async (route) => {
      const url = route.request().url();
      if (url.startsWith("file:") || url.startsWith("data:") || url.startsWith("blob:")) {
        await route.continue();
        return;
      }
      blockedRequests.push(url);
      await route.abort("blockedbyclient");
    });
    await page.goto(pathToFileURL(path.resolve(htmlPath)).href, { waitUntil: "load" });
    await page.evaluate(() => document.fonts?.ready);
    await page.waitForTimeout(250);
    await page.evaluate(async () => {
      document.documentElement.style.setProperty("scroll-behavior", "auto", "important");
      document.body.style.setProperty("scroll-behavior", "auto", "important");
      const step = Math.max(240, Math.floor(window.innerHeight * 0.75));
      const maximum = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
      for (let position = 0; position <= maximum; position += step) {
        window.scrollTo(0, position);
        await new Promise((resolve) => setTimeout(resolve, 40));
      }
      window.scrollTo(0, maximum);
      await new Promise((resolve) => setTimeout(resolve, 80));
      window.scrollTo(0, 0);
      await new Promise((resolve) => setTimeout(resolve, 80));
    });
    const state = await page.evaluate(async () => {
      const root = document.documentElement;
      const bodyText = document.body?.innerText?.trim() || "";
      const visibleElements = [...document.body.querySelectorAll("*")].filter((element) => {
        const style = getComputedStyle(element);
        const box = element.getBoundingClientRect();
        return style.display !== "none" && style.visibility !== "hidden" && box.width > 1 && box.height > 1;
      }).length;
      const interactiveSelector = "button, a[href], input:not([type=hidden]), select, textarea, [role=button]";
      const interactives = [...document.querySelectorAll(interactiveSelector)]
        .map((element) => {
          const style = getComputedStyle(element);
          const rect = element.getBoundingClientRect();
          return {
            element,
            id: element.id || "",
            tag: element.tagName,
            text: (element.textContent || element.getAttribute("aria-label") || "").trim().replace(/\s+/g, " ").slice(0, 80),
            rect,
            visible:
              style.display !== "none" &&
              style.visibility !== "hidden" &&
              style.pointerEvents !== "none" &&
              rect.width > 1 &&
              rect.height > 1,
          };
        })
        .filter((item) => item.visible);
      const undersizedInteractives = interactives
        .filter((item) => item.rect.width < 44 || item.rect.height < 44)
        .slice(0, 30)
        .map((item) => ({
          id: item.id,
          tag: item.tag,
          text: item.text,
          width: Math.round(item.rect.width),
          height: Math.round(item.rect.height),
        }));
      const overlappingInteractives = [];
      for (let leftIndex = 0; leftIndex < interactives.length; leftIndex += 1) {
        const left = interactives[leftIndex];
        for (let rightIndex = leftIndex + 1; rightIndex < interactives.length; rightIndex += 1) {
          const right = interactives[rightIndex];
          if (left.element.contains(right.element) || right.element.contains(left.element)) continue;
          const overlapWidth = Math.min(left.rect.right, right.rect.right) - Math.max(left.rect.left, right.rect.left);
          const overlapHeight = Math.min(left.rect.bottom, right.rect.bottom) - Math.max(left.rect.top, right.rect.top);
          if (overlapWidth > 4 && overlapHeight > 4) {
            overlappingInteractives.push({
              left: left.id || left.text || left.tag,
              right: right.id || right.text || right.tag,
              overlap_width: Math.round(overlapWidth),
              overlap_height: Math.round(overlapHeight),
            });
            if (overlappingInteractives.length >= 20) break;
          }
        }
        if (overlappingInteractives.length >= 20) break;
      }
      const canvases = [...document.querySelectorAll("canvas")].filter((canvas) => {
        const style = getComputedStyle(canvas);
        const rect = canvas.getBoundingClientRect();
        return style.display !== "none" && style.visibility !== "hidden" && rect.width > 2 && rect.height > 2;
      });
      const canvasChecks = canvases.map((canvas) => {
        const width = canvas.width;
        const height = canvas.height;
        if (!width || !height) return { width, height, painted: false, context: "none" };
        const context2d = canvas.getContext("2d");
        if (context2d) {
          let painted = false;
          try {
            const xStep = Math.max(1, Math.floor(width / 12));
            const yStep = Math.max(1, Math.floor(height / 12));
            for (let y = 0; y < height && !painted; y += yStep) {
              for (let x = 0; x < width; x += xStep) {
                const pixel = context2d.getImageData(x, y, 1, 1).data;
                if (pixel[3] > 0) {
                  painted = true;
                  break;
                }
              }
            }
          } catch {
            painted = false;
          }
          return { width, height, painted, context: "2d" };
        }
        const gl = canvas.getContext("webgl2") || canvas.getContext("webgl");
        if (gl) {
          const pixel = new Uint8Array(4);
          gl.readPixels(
            Math.max(0, Math.floor(width / 2)),
            Math.max(0, Math.floor(height / 2)),
            1,
            1,
            gl.RGBA,
            gl.UNSIGNED_BYTE,
            pixel,
          );
          return { width, height, painted: pixel.some((value) => value !== 0), context: "webgl" };
        }
        return { width, height, painted: false, context: "unknown" };
      });
      const hiddenMainContent = [...document.querySelectorAll("main *")]
        .filter((element) => {
          const style = getComputedStyle(element);
          const rect = element.getBoundingClientRect();
          const text = (element.textContent || "").trim();
          return (
            text.length >= 20 &&
            style.display !== "none" &&
            style.visibility !== "hidden" &&
            Number.parseFloat(style.opacity || "1") < 0.05 &&
            element.getAttribute("aria-hidden") !== "true" &&
            rect.width > 20 &&
            rect.height > 10
          );
        })
        .length;
      return {
        title: document.title,
        bodyTextLength: bodyText.length,
        body_font_size: Number.parseFloat(getComputedStyle(document.body).fontSize) || 0,
        scrollWidth: root.scrollWidth,
        clientWidth: root.clientWidth,
        scrollHeight: root.scrollHeight,
        visibleElements,
        undersized_interactives: undersizedInteractives,
        overlapping_interactives: overlappingInteractives,
        hidden_main_content: hiddenMainContent,
        canvas_checks: canvasChecks,
        canvas_pixels_ok: canvasChecks.length === 0 || canvasChecks.every((item) => item.painted),
      };
    });
    let screenshot = "";
    if (shots) {
      screenshot = path.join(outputDir, `${viewport.name}.png`);
      await page.screenshot({ path: screenshot, fullPage: true });
    }
    rows.push({
      ...viewport,
      ...state,
      screenshot,
      horizontal_overflow: state.scrollWidth > state.clientWidth + 1,
      console_errors: consoleErrors,
      page_errors: pageErrors,
      blocked_requests: blockedRequests,
      blank: state.bodyTextLength === 0 && state.visibleElements < 4,
    });
    await page.close();
  }
} finally {
  await browser.close();
}

process.stdout.write(JSON.stringify({ available: true, viewports: rows }));
