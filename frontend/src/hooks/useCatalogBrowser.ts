import { useCallback, useEffect, useRef, useState } from "react";
import { recoveryService } from "../services/recoveryService";
import type { CatalogInfo, CatalogNode, CatalogSearchResult, FilePreview } from "../types/recovery";

export function useCatalogBrowser(setError: (message: string) => void) {
  const [catalog, setCatalog] = useState<CatalogInfo | null>(null);
  const [preview, setPreview] = useState<FilePreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResult, setSearchResult] = useState<CatalogSearchResult | null>(null);
  const [searchingCatalog, setSearchingCatalog] = useState(false);
  const [childrenById, setChildrenById] = useState<Record<string, CatalogNode[]>>({});
  const [parentById, setParentById] = useState<Map<string, string | null>>(new Map());
  const [loadingFolderIds, setLoadingFolderIds] = useState<Set<string>>(new Set());
  const [expandedFolderIds, setExpandedFolderIds] = useState<Set<string>>(new Set());
  const generation = useRef(0);
  const searchRequestId = useRef(0);
  const previewRequestId = useRef(0);

  const clear = useCallback(() => {
    generation.current += 1;
    searchRequestId.current += 1;
    previewRequestId.current += 1;
    setCatalog(null);
    setPreview(null);
    setPreviewLoading(false);
    setSearchQuery("");
    setSearchResult(null);
    setSearchingCatalog(false);
    setChildrenById({});
    setParentById(new Map());
    setLoadingFolderIds(new Set());
    setExpandedFolderIds(new Set());
  }, []);

  const setRootParents = useCallback((roots: CatalogNode[]) => {
    setParentById(new Map(roots.map((node) => [node.id, node.parentId ?? null])));
  }, []);

  useEffect(() => {
    const query = searchQuery.trim();
    if (!catalog || !query) {
      searchRequestId.current += 1;
      setSearchResult(null);
      setSearchingCatalog(false);
      return undefined;
    }
    const requestId = ++searchRequestId.current;
    const catalogGeneration = generation.current;
    setSearchingCatalog(true);
    const timeout = window.setTimeout(() => {
      void recoveryService.searchCatalog(query).then((result) => {
        if (searchRequestId.current !== requestId || generation.current !== catalogGeneration) return;
        setSearchResult(result);
        setParentById((current) => {
          const next = new Map(current);
          result.results.forEach((node) => {
            let parentId: string | null = null;
            (node.ancestorIds ?? []).forEach((ancestorId) => {
              next.set(ancestorId, parentId);
              parentId = ancestorId;
            });
            next.set(node.id, node.parentId ?? parentId);
          });
          return next;
        });
      }).catch((cause: unknown) => {
        if (searchRequestId.current === requestId && generation.current === catalogGeneration) {
          setSearchResult({ totalMatches: 0, results: [] });
          setError(cause instanceof Error ? cause.message : String(cause));
        }
      }).finally(() => {
        if (searchRequestId.current === requestId && generation.current === catalogGeneration) {
          setSearchingCatalog(false);
        }
      });
    }, 220);
    return () => window.clearTimeout(timeout);
  }, [catalog, searchQuery, setError]);

  const toggleFolder = useCallback(async (node: CatalogNode) => {
    if (expandedFolderIds.has(node.id)) {
      setExpandedFolderIds((current) => { const next = new Set(current); next.delete(node.id); return next; });
      return;
    }
    if (childrenById[node.id]) {
      setExpandedFolderIds((current) => new Set(current).add(node.id));
      return;
    }
    const catalogGeneration = generation.current;
    setLoadingFolderIds((current) => new Set(current).add(node.id));
    setError("");
    try {
      const children = await recoveryService.getChildren(node.id);
      if (generation.current !== catalogGeneration) return;
      setChildrenById((current) => ({ ...current, [node.id]: children }));
      setParentById((current) => {
        const next = new Map(current);
        children.forEach((child) => next.set(child.id, node.id));
        return next;
      });
      setExpandedFolderIds((current) => new Set(current).add(node.id));
    } catch (cause) {
      if (generation.current === catalogGeneration) setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      if (generation.current === catalogGeneration) {
        setLoadingFolderIds((current) => { const next = new Set(current); next.delete(node.id); return next; });
      }
    }
  }, [childrenById, expandedFolderIds, setError]);

  const previewFile = useCallback(async (node: CatalogNode) => {
    if (node.isDirectory) return;
    const requestId = ++previewRequestId.current;
    const catalogGeneration = generation.current;
    setPreviewLoading(true);
    setPreview(null);
    try {
      const result = await recoveryService.previewFile(node.id);
      if (previewRequestId.current === requestId && generation.current === catalogGeneration) setPreview(result);
    } catch (cause) {
      if (previewRequestId.current === requestId && generation.current === catalogGeneration) {
        setPreview({ available: false, reason: "invalid_content" });
        setError(cause instanceof Error ? cause.message : String(cause));
      }
    } finally {
      if (previewRequestId.current === requestId && generation.current === catalogGeneration) setPreviewLoading(false);
    }
  }, [setError]);

  const getGeneration = useCallback(() => generation.current, []);
  return {
    catalog, setCatalog, preview, previewLoading, searchQuery, setSearchQuery,
    searchResult, searchingCatalog, childrenById, parentById, loadingFolderIds,
    expandedFolderIds, setRootParents, clear, getGeneration, toggleFolder, previewFile,
  };
}
