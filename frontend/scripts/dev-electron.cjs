const http = require("node:http");
const { spawn } = require("node:child_process");
const electron = require("electron");

const url = "http://127.0.0.1:5173";
const startedAt = Date.now();
const timeoutMs = 90000;

function waitForVite() {
  if (Date.now() - startedAt > timeoutMs) {
    console.error("Vite did not become ready within 90 seconds.");
    process.exit(1);
  }
  const request = http.get(url, (response) => {
    response.resume();
    const child = spawn(electron, ["."], {
      stdio: "inherit",
      env: { ...process.env, ELECTRON_RENDERER_URL: url },
    });
    child.on("exit", (code) => process.exit(code ?? 0));
  });
  request.on("error", () => setTimeout(waitForVite, 300));
}

waitForVite();
