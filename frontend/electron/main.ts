import { app, BrowserWindow, dialog, ipcMain, nativeImage } from "electron";
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
  private child!: ChildProcessWithoutNullStreams;
  private pending = new Map<string, PendingRequest>();
  private projectRoot: string;
  private pythonScript: string;
  private backendArguments: string[];
  private executable: string;
  private dataDirectory: string;
  private elevated = false;
  private expectsElevated = false;
  private privilegeResolver: ((authorized: boolean) => void) | null = null;
  private status: { state: "starting" | "ready" | "error"; message: string } = {
    state: "starting", message: "Starting the Python recovery service",
  };
  private stopping = false;

  constructor() {
    this.projectRoot = app.isPackaged
      ? process.resourcesPath
      : path.resolve(__dirname, "../../..");
    this.pythonScript = path.join(this.projectRoot, "backend", "src", "backend_orchestrator.py");
    this.backendArguments = app.isPackaged ? [] : [this.pythonScript];
    const configuredPython = process.env.DISK_RESURRECT_PYTHON
      || process.argv.find((argument) => argument.startsWith("--disk-resurrect-python="))?.split("=").slice(1).join("=");
    const venvPython = process.platform === "win32"
      ? path.join(this.projectRoot, "venv", "Scripts", "python.exe")
      : path.join(this.projectRoot, "venv", "bin", "python");
    this.executable = app.isPackaged
      ? path.join(process.resourcesPath, "backend", "backend_orchestrator.exe")
      : configuredPython || (existsSync(venvPython)
        ? venvPython
        : process.platform === "win32" ? "python" : "python3");
    this.dataDirectory = app.getPath("userData");
    this.elevated = process.platform === "linux" && process.getuid?.() === 0;
    this.start(this.executable, this.backendArguments, this.elevated);
  }

  private start(command: string, args: string[], elevated: boolean) {
    const isPolkitLaunch = command === "pkexec";
    this.expectsElevated = elevated;
    this.elevated = process.platform === "linux" && process.getuid?.() === 0;
    this.stopping = false;
    this.updateStatus("starting", "Starting the Python recovery service");
    const child = spawn(command, args, {
      cwd: this.projectRoot,
      env: { ...process.env, DISK_RESURRECT_DATA_DIR: this.dataDirectory },
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    });
    this.child = child;
    const lines = readline.createInterface({ input: child.stdout });
    lines.on("line", (line) => this.handleLine(line, child));
    child.stderr.on("data", (data: Buffer) => console.error(`[python] ${data.toString().trimEnd()}`));
    child.on("error", (error) => {
      if (this.child !== child) return;
      this.rejectAll(error);
      this.updateStatus("error", error.message);
      this.resolvePrivilege(false);
      if (isPolkitLaunch && !this.stopping) this.start(this.executable, [this.pythonScript], false);
    });
    child.on("exit", (code, signal) => {
      if (this.child !== child) return;
      const message = `Python backend stopped (${signal || code})`;
      this.rejectAll(new Error(message));
      this.resolvePrivilege(false);
      if (isPolkitLaunch && code !== 0 && !this.stopping) {
        this.start(this.executable, [this.pythonScript], false);
        return;
      }
      if (!this.stopping) this.updateStatus("error", message);
    });
  }

  getStatus() {
    return this.status;
  }

  hasElevatedAccess() {
    return this.elevated;
  }

  requestLinuxDiskAccess(): Promise<boolean> {
    if (process.platform !== "linux" || this.elevated) return Promise.resolve(this.elevated);
    this.rejectAll(new Error("Restarting the Python service with disk access permissions"));
    const previousChild = this.child;
    const args = ["env", `DISK_RESURRECT_DATA_DIR=${this.dataDirectory}`, this.executable, ...this.backendArguments];
    const authorization = new Promise<boolean>((resolve) => {
      this.privilegeResolver = resolve;
      this.start("pkexec", args, true);
      const timeout = setTimeout(() => this.resolvePrivilege(false), 120_000);
      timeout.unref();
    });
    previousChild.kill();
    return authorization;
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

  private handleLine(line: string, source: ChildProcessWithoutNullStreams) {
    if (this.child !== source) return;
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
      if (this.expectsElevated) this.elevated = true;
      this.updateStatus("ready", "Python recovery service is ready");
      this.resolvePrivilege(true);
      return;
    }
    if (!message.id) return;
    const pending = this.pending.get(message.id);
    if (!pending) return;
    this.pending.delete(message.id);
    if (message.type === "error") pending.reject(new Error(message.error || "Backend operation failed"));
    else pending.resolve(message.payload);
  }

  private resolvePrivilege(authorized: boolean) {
    const resolve = this.privilegeResolver;
    if (!resolve) return;
    this.privilegeResolver = null;
    resolve(authorized);
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

function getAppIconPath() {
  return process.platform === "win32"
    ? path.join(app.isPackaged ? process.resourcesPath : app.getAppPath(), "disk-ressurect.ico")
    : path.join(app.getAppPath(), "src", "assets", "disk-ressurect-logo.png");
}

function getAppIcon() {
  return nativeImage.createFromPath(getAppIconPath());
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1180,
    height: 820,
    minWidth: 850,
    minHeight: 620,
    title: "Disk Ressurect",
    icon: getAppIconPath(),
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
    icon: getAppIcon(),
    title: "Permission to read physical disks",
    message: "Disk Ressurect needs administrator permission to read physical disks.",
    detail: "The source is accessed in read-only mode. Recovered files will only be written to the selected destination folder. Windows will display a User Account Control (UAC) prompt.",
    buttons: ["Request permission from Windows", "Continue without disk access"],
    defaultId: 0,
    cancelId: 1,
  });
  if (choice.response === 0 && relaunchAsAdministrator()) return false;
  return true;
}

async function requestLinuxDiskAccess() {
  if (process.platform !== "linux" || backend.hasElevatedAccess()) return true;
  const choice = await dialog.showMessageBox({
    type: "question",
    icon: getAppIcon(),
    title: "Authorize physical disk access",
    message: "Disk Ressurect needs permission to read physical disks.",
    detail: "Only the Python recovery service will run with elevated permissions. Source disks are opened read-only. Your desktop session will request authorization.",
    buttons: ["Authorize disk access", "Continue without disk access"],
    defaultId: 0,
    cancelId: 1,
  });
  if (choice.response !== 0) return false;
  return backend.requestLinuxDiskAccess();
}

app.whenReady().then(async () => {
  if (!await requestAdministratorAtStartup()) return;
  backend = new PythonBackend();
  ipcMain.handle("backend:get-status", () => backend.getStatus());
  ipcMain.handle("backend:get-privileges", () => ({
    isAdministrator: process.platform === "win32"
      ? isWindowsAdministrator()
      : process.platform === "linux"
        ? backend.hasElevatedAccess()
        : true,
  }));
  ipcMain.handle("backend:request-administrator", async () => {
    if (process.platform === "linux") {
      const authorized = await requestLinuxDiskAccess();
      return { relaunched: false, cancelled: !authorized, accessGranted: authorized };
    }
    if (process.platform === "win32" && isWindowsAdministrator()) {
      return { relaunched: false, cancelled: false };
    }
    const options: Electron.MessageBoxOptions = {
      type: "question",
      icon: getAppIcon(),
      title: "Request administrator permission",
      message: "The application needs to read the physical disk to scan partitions.",
      detail: "Reading the source does not modify its data. Windows will open a UAC prompt so you can allow or cancel elevation.",
      buttons: ["Continue to the Windows prompt", "Cancel"],
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
