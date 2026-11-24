import { useCallback, useEffect, useRef, useState } from "react";
import { recoveryService } from "../../services/recoveryService";
import type { BackendStatus, ProgressInfo } from "../../types/recovery";

export function useRecoveryOperationState() {
  const [backendStatus, setBackendStatus] = useState<BackendStatus>("starting");
  const [isAdministrator, setIsAdministrator] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("Starting the Python recovery service…");
  const [progress, setProgress] = useState<ProgressInfo | null>(null);
  const [partitionScanCanResume, setPartitionScanCanResume] = useState(false);
  const [backendSessionGeneration, setBackendSessionGeneration] = useState(0);
  const activeOperationId = useRef<string | null>(null);
  const lastBackendStatus = useRef<BackendStatus>("starting");

  const beginOperation = useCallback(() => {
    const id = window.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
    activeOperationId.current = id;
    return id;
  }, []);
  const finishOperation = useCallback((id: string) => {
    if (activeOperationId.current === id) activeOperationId.current = null;
  }, []);

  const applyBackendStatus = useCallback((runtime: { state: BackendStatus; message: string }) => {
    if (runtime.state === "starting" && lastBackendStatus.current !== "starting") {
      setBackendSessionGeneration((current) => current + 1);
      setBusy(false);
      setProgress(null);
      setIsAdministrator(false);
      activeOperationId.current = null;
    }
    lastBackendStatus.current = runtime.state;
    setBackendStatus(runtime.state);
    if (runtime.state === "error") {
      setError(runtime.message);
      setStatus("The Python recovery process has exited.");
    }
    if (runtime.state === "ready") {
      void recoveryService.getPrivilegeStatus().then((privilege) => {
        setIsAdministrator(privilege.isAdministrator);
      }).catch(() => setIsAdministrator(false));
    }
  }, []);

  useEffect(() => {
    const unsubscribe = recoveryService.onProgress((event) => {
      if (activeOperationId.current) {
        if (event.operationId !== activeOperationId.current) return;
      } else if (event.operationId) return;
      setProgress(event);
      if (event.message) setStatus(event.message);
    });
    const unsubscribeBackend = recoveryService.onBackendStatus(applyBackendStatus);
    void recoveryService.getBackendStatus().then(applyBackendStatus).catch((cause: unknown) => {
      setBackendStatus("error");
      setError(cause instanceof Error ? cause.message : String(cause));
      setStatus("Unable to check the Python service status.");
    });
    void recoveryService.getPrivilegeStatus().then((privilege) => {
      setIsAdministrator(privilege.isAdministrator);
    }).catch((cause: unknown) => {
      setIsAdministrator(false);
      setError(cause instanceof Error ? cause.message : String(cause));
    });
    return () => { unsubscribe(); unsubscribeBackend(); };
  }, [applyBackendStatus]);

  const ensureAdministrator = useCallback(async () => {
    try {
      const privilege = await recoveryService.getPrivilegeStatus();
      setIsAdministrator(privilege.isAdministrator);
      if (privilege.isAdministrator) return true;
      setStatus("Reading physical disks requires elevated permission.");
      setError("");
      const result = await recoveryService.requestAdministrator();
      if (result.accessGranted) {
        setIsAdministrator(true);
        setStatus("Disk access permission was granted.");
        return true;
      }
      if (result.relaunched) {
        setStatus("The application is restarting with elevated permissions.");
      } else {
        setStatus("The scan was canceled because disk access permission was not granted.");
        setError("Authorize the system permission request to read physical disks.");
      }
      return false;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      setStatus("Unable to request elevated disk access.");
      return false;
    }
  }, []);

  return {
    backendStatus, isAdministrator, busy, error, status, progress, partitionScanCanResume,
    backendSessionGeneration, activeOperationId, beginOperation, finishOperation,
    setIsAdministrator, setBusy, setError, setStatus, setProgress, setPartitionScanCanResume,
    ensureAdministrator,
  };
}
