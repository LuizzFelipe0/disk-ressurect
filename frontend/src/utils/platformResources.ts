function joinPath(platform: string, ...segments: string[]): string {
  const separator = platform === "win32" ? "\\" : "/";
  return segments.map((segment) => segment.replace(/[\\/]+/g, separator)).reduce((result, segment) => {
    if (!result) return segment;
    return `${result.replace(/[\\/]+$/, "")}${separator}${segment.replace(/^[\\/]+/, "")}`;
  }, "");
}

export function getBundledBackendPath(platform: string, resourcesPath: string): string {
  const executable = platform === "win32" ? "backend_orchestrator.exe" : "backend_orchestrator";
  return joinPath(platform, resourcesPath, "backend", executable);
}

export function getAppIconPath(
  platform: string,
  isPackaged: boolean,
  appPath: string,
  resourcesPath: string,
): string {
  if (platform === "win32") {
    return joinPath(platform, isPackaged ? resourcesPath : appPath, "disk-ressurect.ico");
  }
  if (platform === "linux" && isPackaged) {
    return joinPath(platform, resourcesPath, "disk-ressurect-logo.png");
  }
  return joinPath(platform, appPath, "src", "assets", "disk-ressurect-logo.png");
}
