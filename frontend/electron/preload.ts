import { contextBridge, ipcRenderer } from "electron";
import type { DesktopApi } from "./contracts";

const api: DesktopApi = {
  listDisks: () => ipcRenderer.invoke("recovery:list-disks"),
  listPartitions: (diskNumber, deepScan) =>
    ipcRenderer.invoke("recovery:list-partitions", { diskNumber, deepScan }),
  scanCatalog: (volumeId) => ipcRenderer.invoke("recovery:scan-catalog", { volumeId }),
  getChildren: (nodeId) => ipcRenderer.invoke("recovery:catalog-children", { nodeId }),
  recover: (options) => ipcRenderer.invoke("recovery:extract", options),
  chooseOutputDirectory: () => ipcRenderer.invoke("recovery:choose-output"),
  onProgress: (callback) => {
    const listener = (_event: Electron.IpcRendererEvent, payload: Parameters<typeof callback>[0]) => callback(payload);
    ipcRenderer.on("recovery:progress", listener);
    return () => ipcRenderer.removeListener("recovery:progress", listener);
  },
  getBackendStatus: () => ipcRenderer.invoke("backend:get-status"),
  onBackendStatus: (callback) => {
    const listener = (_event: Electron.IpcRendererEvent, payload: Parameters<typeof callback>[0]) => callback(payload);
    ipcRenderer.on("backend:status", listener);
    return () => ipcRenderer.removeListener("backend:status", listener);
  },
  getPrivilegeStatus: () => ipcRenderer.invoke("backend:get-privileges"),
  requestAdministrator: () => ipcRenderer.invoke("backend:request-administrator"),
};

contextBridge.exposeInMainWorld("diskResurrect", api);
