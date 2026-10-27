import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { recoveryService } from "../services/recoveryService";
import type {
  BackendStatus,
  CatalogInfo,
  CatalogNode,
  DiskInfo,
  ProgressInfo,
  VolumeInfo,
} from "../types/recovery";
import { isTreeNodeSelected, updateTreeSelection } from "../utils/selection";

export function useRecoveryController() {
  const [backendStatus, setBackendStatus] = useState<BackendStatus>("starting");
  const [isAdministrator, setIsAdministrator] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("Iniciando o serviço Python de recuperação…");
  const [progress, setProgress] = useState<ProgressInfo | null>(null);
  const [disks, setDisks] = useState<DiskInfo[]>([]);
  const [selectedDiskNumber, setSelectedDiskNumber] = useState("");
  const [volumes, setVolumes] = useState<VolumeInfo[]>([]);
  const [selectedVolumeId, setSelectedVolumeId] = useState("");
  const [catalog, setCatalog] = useState<CatalogInfo | null>(null);
  const [childrenById, setChildrenById] = useState<Record<string, CatalogNode[]>>({});
  const [parentById, setParentById] = useState<Map<string, string | null>>(new Map());
  const [loadingFolderIds, setLoadingFolderIds] = useState<Set<string>>(new Set());
  const [expandedFolderIds, setExpandedFolderIds] = useState<Set<string>>(new Set());
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [excludedIds, setExcludedIds] = useState<Set<string>>(new Set());
  const [extensions, setExtensions] = useState<string[]>([]);
  const [minimumSizeKb, setMinimumSizeKb] = useState(0);
  const [outputDirectory, setOutputDirectory] = useState("");
  const initialLoadStarted = useRef(false);

  const clearCatalog = useCallback(() => {
    setCatalog(null);
    setChildrenById({});
    setParentById(new Map());
    setExpandedFolderIds(new Set());
    setLoadingFolderIds(new Set());
    setSelectedIds(new Set());
    setExcludedIds(new Set());
    setExtensions([]);
  }, []);

  const refreshDisks = useCallback(async () => {
    setBusy(true);
    setError("");
    setStatus("Consultando discos pelo serviço Python…");
    try {
      const foundDisks = await recoveryService.listDisks();
      setDisks(foundDisks);
      setSelectedDiskNumber("");
      setVolumes([]);
      setSelectedVolumeId("");
      clearCatalog();
      setBackendStatus("ready");
      setStatus(`${foundDisks.length} disco(s) encontrado(s). Escolha o disco de origem.`);
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : String(cause);
      const runtime = await recoveryService.getBackendStatus().catch(() => null);
      if (runtime?.state === "error") {
        setBackendStatus("error");
        setError(runtime.message);
        setStatus("O processo Python de recuperação foi encerrado.");
      } else {
        setError(message);
        setStatus("A consulta de discos falhou. Consulte os detalhes abaixo.");
      }
    } finally { setBusy(false); }
  }, [clearCatalog]);

  useEffect(() => {
    const unsubscribe = recoveryService.onProgress((event) => {
      setProgress(event);
      if (event.message) setStatus(event.message);
    });
    const unsubscribeBackend = recoveryService.onBackendStatus((runtime) => {
      setBackendStatus(runtime.state);
      if (runtime.state === "error") {
        setError(runtime.message);
        setStatus("O processo Python de recuperação foi encerrado.");
      }
    });
    void recoveryService.getBackendStatus().then((runtime) => {
      setBackendStatus(runtime.state);
      if (runtime.state === "error") {
        setError(runtime.message);
        setStatus("O processo Python de recuperação foi encerrado.");
      }
    }).catch((cause: unknown) => {
      setBackendStatus("error");
      setError(cause instanceof Error ? cause.message : String(cause));
      setStatus("Não foi possível consultar o estado do serviço Python.");
    });
    void recoveryService.getPrivilegeStatus().then((privileges) => {
      setIsAdministrator(privileges.isAdministrator);
    }).catch((cause: unknown) => {
      setIsAdministrator(false);
      setError(cause instanceof Error ? cause.message : String(cause));
    });
    if (!initialLoadStarted.current) {
      initialLoadStarted.current = true;
      void refreshDisks();
    }
    return () => { unsubscribe(); unsubscribeBackend(); };
  }, [refreshDisks]);

  const ensureAdministrator = useCallback(async () => {
    try {
      const privilege = await recoveryService.getPrivilegeStatus();
      setIsAdministrator(privilege.isAdministrator);
      if (privilege.isAdministrator) return true;
      setStatus("A leitura de discos físicos exige permissão de administrador.");
      setError("");
      const result = await recoveryService.requestAdministrator();
      if (result.relaunched) {
        setStatus("O aplicativo será reaberto com permissão de administrador.");
      } else {
        setStatus("A varredura foi cancelada porque não há permissão de administrador.");
        setError("Permita a elevação no pedido do Windows para ler discos físicos.");
      }
      return false;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      setStatus("Não foi possível solicitar permissão de administrador.");
      return false;
    }
  }, []);

  const selectDisk = useCallback((diskNumber: string) => {
    setSelectedDiskNumber(diskNumber);
    setVolumes([]);
    setSelectedVolumeId("");
    clearCatalog();
    setError("");
    setStatus(diskNumber ? "Busque as partições NTFS deste disco." : "Escolha o disco de origem.");
  }, [clearCatalog]);

  const findPartitions = useCallback(async (deepScan: boolean) => {
    if (!selectedDiskNumber) return;
    if (!await ensureAdministrator()) return;
    setBusy(true); setError(""); setProgress(null);
    setStatus(deepScan ? "Procurando partições NTFS perdidas…" : "Verificando partições…");
    try {
      const foundVolumes = await recoveryService.listPartitions(Number(selectedDiskNumber), deepScan);
      setVolumes(foundVolumes); setSelectedVolumeId(""); clearCatalog();
      setStatus(foundVolumes.length
        ? `${foundVolumes.length} partição(ões) NTFS encontrada(s). Selecione uma para montar o catálogo.`
        : "Nenhuma partição NTFS legível foi encontrada.");
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); setStatus("A busca por partições falhou."); }
    finally { setBusy(false); }
  }, [selectedDiskNumber, clearCatalog, ensureAdministrator]);

  const selectVolume = useCallback((volumeId: string) => {
    setSelectedVolumeId(volumeId); clearCatalog();
    setStatus(volumeId ? "Monte o catálogo para navegar pelos arquivos encontrados." : "Selecione uma partição NTFS.");
  }, [clearCatalog]);

  const buildCatalog = useCallback(async () => {
    if (!selectedVolumeId) return;
    if (!await ensureAdministrator()) return;
    setBusy(true); setError(""); setProgress(null);
    setStatus("Lendo metadados e montando catálogo…");
    try {
      const result = await recoveryService.scanCatalog(selectedVolumeId);
      const parents = new Map<string, string | null>();
      result.roots.forEach((node) => parents.set(node.id, null));
      setCatalog(result); setParentById(parents);
      setExtensions(result.availableExtensions);
      setStatus(`Catálogo pronto: ${result.recordCount.toLocaleString()} registros MFT.`);
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); setStatus("Não foi possível montar o catálogo."); }
    finally { setBusy(false); }
  }, [selectedVolumeId, ensureAdministrator]);

  const toggleFolder = useCallback(async (node: CatalogNode) => {
    if (expandedFolderIds.has(node.id)) {
      setExpandedFolderIds((current) => { const next = new Set(current); next.delete(node.id); return next; });
      return;
    }
    if (childrenById[node.id]) {
      setExpandedFolderIds((current) => new Set(current).add(node.id));
      return;
    }
    setLoadingFolderIds((current) => new Set(current).add(node.id)); setError("");
    try {
      const children = await recoveryService.getChildren(node.id);
      setChildrenById((current) => ({ ...current, [node.id]: children }));
      setParentById((current) => {
        const next = new Map(current);
        children.forEach((child) => next.set(child.id, node.id));
        return next;
      });
      setExpandedFolderIds((current) => new Set(current).add(node.id));
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setLoadingFolderIds((current) => { const next = new Set(current); next.delete(node.id); return next; }); }
  }, [childrenById, expandedFolderIds]);

  const descendantsById = useMemo(() => {
    const descendants = new Map<string, string[]>();
    Object.entries(childrenById).forEach(([id, children]) => descendants.set(id, children.map((child) => child.id)));
    return descendants;
  }, [childrenById]);

  const toggleSelection = useCallback((nodeId: string, checked: boolean) => {
    const next = updateTreeSelection(nodeId, checked,
      { selectedIds, excludedIds }, parentById, descendantsById);
    setSelectedIds(next.selectedIds); setExcludedIds(next.excludedIds);
  }, [selectedIds, excludedIds, parentById, descendantsById]);

  const isSelected = useCallback((nodeId: string) =>
    isTreeNodeSelected(nodeId, { selectedIds, excludedIds }, parentById),
  [selectedIds, excludedIds, parentById]);

  const selectAll = useCallback(() => {
    setSelectedIds(new Set(catalog?.roots.map((node) => node.id) ?? []));
    setExcludedIds(new Set());
  }, [catalog]);

  const clearSelection = useCallback(() => { setSelectedIds(new Set()); setExcludedIds(new Set()); }, []);

  const chooseOutputDirectory = useCallback(async () => {
    try {
      const directory = await recoveryService.chooseOutputDirectory();
      if (directory) setOutputDirectory(directory);
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
  }, []);

  const recover = useCallback(async () => {
    if (!selectedIds.size || !extensions.length || !outputDirectory.trim()) {
      setError(!outputDirectory.trim() ? "Escolha uma pasta de destino para continuar." : "Marque arquivos e pelo menos um tipo de arquivo.");
      return;
    }
    if (!await ensureAdministrator()) return;
    setBusy(true); setError(""); setProgress(null); setStatus("Recuperando os itens selecionados…");
    try {
      const result = await recoveryService.recover({
        selectedNodeIds: [...selectedIds], excludedNodeIds: [...excludedIds],
        outputDirectory, extensions, minimumSizeKb,
      });
      setStatus(`Concluído: ${result.recoveredCount}/${result.candidateCount} arquivos recuperados. Relatório: ${result.reportPath}`);
      setProgress({ stage: "extract", completed: 1, total: 1, message: "Recuperação concluída." });
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); setStatus("A recuperação falhou."); }
    finally { setBusy(false); }
  }, [selectedIds, excludedIds, outputDirectory, extensions, minimumSizeKb, ensureAdministrator]);

  const setExtensionSelected = useCallback((extension: string, checked: boolean) => {
    setExtensions((current) => checked
      ? [...new Set([...current, extension])]
      : current.filter((item) => item !== extension));
  }, []);

  return {
    backendStatus, isAdministrator, busy, error, status, progress, disks, selectedDiskNumber, volumes,
    selectedVolumeId, catalog, childrenById, loadingFolderIds, expandedFolderIds,
    selectedIds, extensions, minimumSizeKb, outputDirectory,
    refreshDisks, selectDisk, findPartitions, selectVolume, buildCatalog, toggleFolder,
    toggleSelection, isSelected, selectAll, clearSelection, chooseOutputDirectory,
    recover, setExtensionSelected, setMinimumSizeKb, setOutputDirectory,
    ensureAdministrator,
  };
}
