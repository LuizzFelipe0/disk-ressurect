import React from "react";
import { Button, Card, Input } from "belagio-styles-lib";
import { useNavigate } from "react-router-dom";
import { useAppLanguage } from "../../app/language";
import { useCatalogSession, useRecoveryOperation, useRecoverySession, useStorageSession } from "../../app/recoverySession";
import { useCatalogScrollPosition } from "../../app/recoverySession";
import { PageActions, SimplePage } from "../../app/layoutStyle";
import { EmptyState } from "../../components/EmptyState";
import { RecoveryTree } from "../../components/RecoveryTree";
import { translate } from "../../i18n/translations";
import { CatalogViewport } from "./style";
import { DiskAuditReport } from "./DiskAuditReport";

export const CatalogPage: React.FC = () => {
  const catalogState = useCatalogSession();
  const recovery = useRecoverySession();
  const operation = useRecoveryOperation();
  const storage = useStorageSession();
  const scrollPosition = useCatalogScrollPosition();
  const navigate = useNavigate();
  const { language } = useAppLanguage();
  const t = (key: Parameters<typeof translate>[1], values?: Record<string, string | number>) => translate(language, key, values);
  const viewportRef = React.useRef<HTMLDivElement>(null);
  React.useLayoutEffect(() => {
    if (viewportRef.current) viewportRef.current.scrollTop = scrollPosition.read();
  }, [storage.sessionId]);
  const searchActive = Boolean(catalogState.searchQuery.trim());
  const roots = searchActive ? catalogState.searchResult?.results : catalogState.catalog?.roots;

  return <SimplePage>
    <h1>{t("catalogStep")}</h1>
    <Card size="sm" variant="flat">
      <PageActions>
        <span>{catalogState.catalog
          ? `${catalogState.catalog.recordCount.toLocaleString(language)} ${t("catalogItems")} · ${catalogState.catalog.availableExtensions.length} ${t("fileTypesCount")}${catalogState.catalog.orphanScanPerformed ? ` · ${t("orphanedEntriesCount", { count: catalogState.catalog.orphanedRecordCount ?? 0 })}` : ""}${(catalogState.catalog.contentCarvedCount ?? 0) > 0 ? ` · ${t("contentCarvedCount", { count: catalogState.catalog.contentCarvedCount ?? 0 })}` : ""}`
          : t("catalogPrompt")}</span>
        <span>{catalogState.selectedIds.size} {t("selectedItems")}</span>
        <Button className="brand-button--ghost" variant="ghost" size="md" disabled={!catalogState.catalog || operation.busy}
          onClick={catalogState.selectAll}>{t("selectAll")}</Button>
        <Button className="brand-button--ghost" variant="ghost" size="md" disabled={!catalogState.catalog || operation.busy}
          onClick={catalogState.clearSelection}>{t("clearSelection")}</Button>
        <Button className="brand-button--primary" variant="primary" size="md"
          disabled={!catalogState.selectedIds.size || operation.busy} onClick={() => navigate("/recovery")}>{t("recoveryStep")}</Button>
        {catalogState.catalog && <DiskAuditReport catalog={catalogState.catalog} />}
      </PageActions>
      {catalogState.catalog && <Input type="search" aria-label={t("searchFilesAria")}
        placeholder={t("searchFiles")} value={catalogState.searchQuery}
        onChange={recovery.setSearchQuery} disabled={operation.busy} />}
      <CatalogViewport ref={viewportRef} onScroll={(event) => scrollPosition.remember(event.currentTarget.scrollTop)}>
      {!catalogState.catalog ? <EmptyState>{t("emptyCatalog")}</EmptyState>
        : catalogState.searchingCatalog ? <EmptyState>{t("searchingCatalog")}</EmptyState>
          : roots?.length ? <RecoveryTree
            roots={roots} childrenById={catalogState.childrenById}
            expandedFolderIds={catalogState.expandedFolderIds}
            loadingFolderIds={catalogState.loadingFolderIds} isSelected={catalogState.isSelected}
            onToggleFolder={(node) => void catalogState.toggleFolder(node)}
            onToggleSelection={catalogState.toggleSelection}
            onPreview={(node) => void catalogState.previewFile(node)} language={language}
          /> : <EmptyState>{searchActive ? t("noMatches") : t("noFiles")}</EmptyState>}
      </CatalogViewport>
      <section aria-label={t("preview")}>
        {catalogState.previewLoading ? <p>{t("previewLoading")}</p>
          : catalogState.preview?.available && catalogState.preview.kind === "image"
            && catalogState.preview.dataBase64 ? <img alt={catalogState.preview.name ?? t("preview")}
              src={`data:${catalogState.preview.mimeType};base64,${catalogState.preview.dataBase64}`} />
            : catalogState.preview?.available && catalogState.preview.kind === "pdf"
              && catalogState.preview.dataBase64 ? <iframe title={catalogState.preview.name ?? t("preview")}
                src={`data:${catalogState.preview.mimeType};base64,${catalogState.preview.dataBase64}`} />
            : <p>{t("previewHint")}</p>}
      </section>
      {storage.rawImage && <p role="note">{t("rawDestinationNotice")}</p>}
    </Card>
  </SimplePage>;
};
