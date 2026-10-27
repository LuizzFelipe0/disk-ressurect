import { app, BrowserWindow, dialog, ipcMain } from "electron";
import { spawn, spawnSync, ChildProcessWithoutNullStreams, execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import readline from "node:readline";
import { randomUUID } from "node:crypto";

type PendingRequest = {
  resolve: (value: unknown) => void;
  reject: (error: Error) => void;
};

class PythonBackend {
  private child: ChildProcessWithoutNullStreams;
  private pending = new Map<string, PendingRequest>();
  private status: { state: "starting" | "ready" | "error"; message: string } = {
    state: "starting", message: "Starting the Python recovery service",
  };
  private stopping = false;

  constructor() {
    const projectRoot = app.isPackaged
      ? process.resourcesPath
      : path.resolve(__dirname, "../../..");
    const pythonScript = path.join(projectRoot, "backend", "src", "electron_backend.py");
    const configuredPython = process.env.DISK_RESURRECT_PYTHON
      || process.argv.find((argument) => argument.startsWith("--disk-resurrect-python="))?.split("=").slice(1).join("=");
    const venvPython = process.platform === "win32"
      ? path.join(projectRoot, "venv", "Scripts", "python.exe")
      : path.join(projectRoot, "venv", "bin", "python");
    const executable = configuredPython || (existsSync(venvPython) ? venvPython : "python");

    this.child = spawn(executable, [pythonScript], {
      cwd: projectRoot,
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    });
    const lines = readline.createInterface({ input: this.child.stdout });
    lines.on("line", (line) => this.handleLine(line));
    this.child.stderr.on("data", (data: Buffer) => console.error(`[python] ${data.toString().trimEnd()}`));
    this.child.on("error", (error) => {
      this.rejectAll(error);
      this.updateStatus("error", error.message);
    });
    this.child.on("exit", (code, signal) => {
      const message = `Python backend stopped (${signal || code})`;
      this.rejectAll(new Error(message));
      if (!this.stopping) this.updateStatus("error", message);
    });
  }

  getStatus() {
    return this.status;
  }

  request<T>(operation: string, payload: unknown): Promise<T> {
    const id = randomUUID();
    return new Promise<T>((resolve, reject) => {
      this.pending.set(id, { resolve: resolve as (value: unknown) => void, reject });
      this.child.stdin.write(`${JSON.stringify({ id, operation, payload })}\n`, (error) => {
        if (error) {
          this.pending.delete(id);
          reject(error);
        }
      });
    });
  }

  stop() {
    this.stopping = true;
    this.child.kill();
  }

  private handleLine(line: string) {
    let message: { id?: string; type?: string; payload?: unknown; error?: string };
    try {
      message = JSON.parse(line);
    } catch {
      console.error(`Invalid backend message: ${line}`);
      return;
    }
    if (message.type === "progress") {
      for (const window of BrowserWindow.getAllWindows()) {
        window.webContents.send("recovery:progress", message.payload);
      }
      return;
    }
    if (message.type === "ready") {
      this.updateStatus("ready", "Python recovery service is ready");
      return;
    }
    if (!message.id) return;
    const pending = this.pending.get(message.id);
    if (!pending) return;
    this.pending.delete(message.id);
    if (message.type === "error") pending.reject(new Error(message.error || "Backend operation failed"));
    else pending.resolve(message.payload);
  }

  private rejectAll(error: Error) {
    for (const request of this.pending.values()) request.reject(error);
    this.pending.clear();
  }

  private updateStatus(state: "starting" | "ready" | "error", message: string) {
    this.status = { state, message };
    for (const window of BrowserWindow.getAllWindows()) {
      window.webContents.send("backend:status", this.status);
    }
  }
}

let mainWindow: BrowserWindow | null = null;
let backend: PythonBackend;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1180,
    height: 820,
    minWidth: 850,
    minHeight: 620,
    title: "Disk Ressurect",
    backgroundColor: "#f3f6fb",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  const rendererUrl = process.env.ELECTRON_RENDERER_URL
    || process.argv.find((argument) => argument.startsWith("--disk-resurrect-renderer-url="))?.split("=").slice(1).join("=");
  if (rendererUrl) void mainWindow.loadURL(rendererUrl);
  else void mainWindow.loadFile(path.resolve(__dirname, "../ui/index.html"));
  mainWindow.on("closed", () => { mainWindow = null; });
}

function isWindowsAdministrator() {
  if (process.platform !== "win32") return false;
  const powershell = path.join(process.env.SystemRoot || "C:\\Windows",
    "System32", "WindowsPowerShell", "v1.0", "powershell.exe");
  const check = "$identity = [Security.Principal.WindowsIdentity]::GetCurrent(); "
    + "$principal = [Security.Principal.WindowsPrincipal]::new($identity); "
    + "if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { 'yes' } else { 'no' }";
  try {
    return execFileSync(powershell, ["-NoLogo", "-NoProfile", "-NonInteractive", "-Command", check], {
      encoding: "utf8", windowsHide: true, timeout: 5000,
    }).trim() === "yes";
  } catch {
    return false;
  }
}

function quotePowerShell(value: string) {
  return `'${value.replace(/'/g, "''")}'`;
}

function quoteWindowsArgument(value: string) {
  return `"${value.replace(/(\\*)"/g, "$1$1\\\"").replace(/(\\+)$/g, "$1$1")}"`;
}

function relaunchAsAdministrator() {
  const powershell = path.join(process.env.SystemRoot || "C:\\Windows",
    "System32", "WindowsPowerShell", "v1.0", "powershell.exe");
  const args = process.argv.slice(1).filter((argument) => !argument.startsWith("--disk-resurrect-"));
  const rendererUrl = process.env.ELECTRON_RENDERER_URL
    || process.argv.find((argument) => argument.startsWith("--disk-resurrect-renderer-url="))?.split("=").slice(1).join("=");
  const pythonPath = process.env.DISK_RESURRECT_PYTHON
    || process.argv.find((argument) => argument.startsWith("--disk-resurrect-python="))?.split("=").slice(1).join("=");
  if (rendererUrl) args.push(`--disk-resurrect-renderer-url=${rendererUrl}`);
  if (pythonPath) args.push(`--disk-resurrect-python=${pythonPath}`);
  args.push("--disk-resurrect-elevated");
  const argumentList = args.map(quoteWindowsArgument).join(" ");
  const command = `try { Start-Process -FilePath ${quotePowerShell(process.execPath)} `
    + `-ArgumentList ${quotePowerShell(argumentList)} `
    + `-WorkingDirectory ${quotePowerShell(process.cwd())} -Verb RunAs; exit 0 } `
    + "catch { exit 1223 }";
  const result = spawnSync(powershell,
    ["-NoLogo", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", command],
    { encoding: "utf8", windowsHide: true, timeout: 30000 });
  if (result.error || result.status !== 0) return false;
  app.quit();
  return true;
}

async function requestAdministratorAtStartup() {
  if (process.platform !== "win32" || isWindowsAdministrator()) return true;
  const choice = await dialog.showMessageBox({
    type: "question",
    title: "Permissão para ler discos físicos",
    message: "O Disk Ressurect precisa de permissão de administrador para ler discos físicos.",
    detail: "A leitura da origem é somente leitura. Os arquivos recuperados serão gravados apenas na pasta de destino escolhida. O Windows exibirá o pedido de Controle de Conta de Usuário (UAC).",
    buttons: ["Solicitar permissão ao Windows", "Continuar sem acesso a discos"],
    defaultId: 0,
    cancelId: 1,
  });
  if (choice.response === 0 && relaunchAsAdministrator()) return false;
  return true;
}

app.whenReady().then(async () => {
  if (!await requestAdministratorAtStartup()) return;
  backend = new PythonBackend();
  ipcMain.handle("backend:get-status", () => backend.getStatus());
  ipcMain.handle("backend:get-privileges", () => ({
    isAdministrator: process.platform !== "win32" || isWindowsAdministrator(),
  }));
  ipcMain.handle("backend:request-administrator", async () => {
    if (process.platform === "win32" && isWindowsAdministrator()) {
      return { relaunched: false, cancelled: false };
    }
    const options: Electron.MessageBoxOptions = {
      type: "question",
      title: "Solicitar permissão de administrador",
      message: "Para varrer partições, o aplicativo precisa ler o disco físico.",
      detail: "A leitura da origem não altera seus dados. O Windows abrirá o UAC para você permitir ou cancelar essa elevação.",
      buttons: ["Continuar para o pedido do Windows", "Cancelar"],
      defaultId: 0,
      cancelId: 1,
    };
    const choice = mainWindow
      ? await dialog.showMessageBox(mainWindow, options)
      : await dialog.showMessageBox(options);
    if (choice.response !== 0) return { relaunched: false, cancelled: true };
    const relaunched = relaunchAsAdministrator();
    return { relaunched, cancelled: !relaunched };
  });
  ipcMain.handle("recovery:list-disks", () => backend.request("list_disks", {}));
  ipcMain.handle("recovery:list-partitions", (_event, payload) => backend.request("list_partitions", payload));
  ipcMain.handle("recovery:scan-catalog", (_event, payload) => backend.request("scan_catalog", payload));
  ipcMain.handle("recovery:catalog-children", (_event, payload) => backend.request("catalog_children", payload));
  ipcMain.handle("recovery:extract", (_event, payload) => backend.request("extract", payload));
  ipcMain.handle("recovery:choose-output", async () => {
    const result = await dialog.showOpenDialog({ properties: ["openDirectory", "createDirectory"] });
    return result.canceled ? null : result.filePaths[0] || null;
  });
  createWindow();
  app.on("activate", () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
});

app.on("window-all-closed", () => {
  backend?.stop();
  if (process.platform !== "darwin") app.quit();
});
