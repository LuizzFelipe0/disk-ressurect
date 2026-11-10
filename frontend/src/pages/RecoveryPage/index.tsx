import React from "react";
import { Button, Card, DropdownCheckbox, Footer as BelagioFooter, Header, Input, LanguageToggle, Select, type SiteLanguage } from "belagio-styles-lib";
import logo from "../../assets/disk-ressurect-logo.png";
import { useRecoveryController } from "../../hooks/useRecoveryController";
import { EmptyState } from "../../components/EmptyState";
import { ErrorNotice } from "../../components/ErrorNotice";
import { RecoveryTree } from "../../components/RecoveryTree";
import { RecoveryStatusPanel } from "../../components/RecoveryStatusPanel";
import { sanitizeDisplayText } from "../../utils/sanitizeDisplayText";
import { translate, translateError, translateStatus } from "../../i18n/translations";
import {
  areAllExtensionsSelected,
  getExtensionSelectionUpdates,
  getMinimumSizeKb,
} from "../../utils/filterSelection";
import {
  ActionRow,
  BrowserFrame,
  BrowserHeading,
  BrowserSection,
  DestinationRow,
  Eyebrow,
  FormGrid,
  PageHeader,
  PageContent,
  PageLayout,
  SearchBox,
  SelectionActions,
  SelectionSummary,
  Toolbar,
  DestinationInput,
  FileTypesControls,
  FormControl,
  FormControlCaption,
  MinimumSizeControl,
} from "./style";

export const RecoveryPage: React.FC = () => {
  const recovery = useRecoveryController();
  const [language, setLanguage] = React.useState<SiteLanguage>(() => {
    const saved = window.localStorage.getItem("disk-ressurect:language");
    return saved === "en-US" || saved === "es-ES" || saved === "fr-FR" || saved === "zh-CN" ? saved : "pt-BR";
  });
  const t = (key: Parameters<typeof translate>[1], values?: Record<string, string | number>) => translate(language, key, values);
  const searchActive = Boolean(recovery.searchQuery.trim());
  const allExtensionsSelected = areAllExtensionsSelected(recovery.availableExtensions, recovery.extensions);
  const visibleRoots = searchActive
    ? recovery.searchResult?.results
    : recovery.catalog?.roots;
  const selectedDiskHasCachedScan = recovery.disks.some((disk) =>
    String(disk.number) === recovery.selectedDiskNumber && Boolean(disk.cachedPartitions?.length));
  const catalogSummary = !recovery.catalog
    ? t("catalogPrompt")
    : searchActive && recovery.searchResult
      ? recovery.searchResult.totalMatches > recovery.searchResult.results.length
        ? t("showingMatches", { visible: recovery.searchResult.results.length.toLocaleString(language), total: recovery.searchResult.totalMatches.toLocaleString(language) })
        : `${recovery.searchResult.totalMatches.toLocaleString(language)} ${t("matchingItems")}`
      : `${recovery.catalog.recordCount.toLocaleString(language)} ${t("mftRecords")} · ${recovery.catalog.availableExtensions.length.toLocaleString(language)} ${t("fileTypesCount")}`;

  return (
    <PageLayout lang={language}>
      <PageHeader>
        <Header icon={logo} title="Disk-Ressurect" actions={<LanguageToggle value={language} size="sm" onChange={(next) => {
          setLanguage(next);
          window.localStorage.setItem("disk-ressurect:language", next);
        }} aria-label="Idioma / Language / Idioma / Langue / 语言" />} />
      </PageHeader>

      <PageContent id="recovery-page-content">
      <Card size="sm" variant="flat"><FormGrid>
        <FormControl><FormControlCaption>{t("sourceDisk")}</FormControlCaption><Select aria-label={t("sourceDiskAria")} value={recovery.selectedDiskNumber} disabled={recovery.busy}
          onChange={recovery.selectDisk} options={[
            { value: "", label: recovery.backendStatus === "error" ? t("backendUnavailable") : t("selectDisk") },
            ...recovery.disks.map((disk) => ({ value: String(disk.number), label: sanitizeDisplayText(disk.displayName) })),
          ]} /></FormControl>
        <ActionRow>
          <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy} onClick={() => void recovery.refreshDisks()}>{t("refresh")}</Button>
          <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy || !recovery.selectedDiskNumber}
            onClick={() => void recovery.findPartitions(false)}>{t("findPartitions")}</Button>
          <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy || !recovery.selectedDiskNumber}
            onClick={() => void recovery.findPartitions(true)}>{selectedDiskHasCachedScan ? t("deepScanAgain") : t("deepScan")}</Button>
        </ActionRow>
        <FormControl><FormControlCaption>{t("ntfsPartition")}</FormControlCaption><Select aria-label={t("ntfsPartition")} value={recovery.selectedVolumeId}
          disabled={recovery.busy || !recovery.volumes.length} onChange={recovery.selectVolume} options={[
            { value: "", label: recovery.volumes.length ? t("selectPartition") : t("searchPartitions") },
            ...recovery.volumes.map((volume) => ({ value: volume.id, label: sanitizeDisplayText(volume.name) })),
          ]} /></FormControl>
        <ActionRow>
          <Button className="brand-button--primary" variant="primary" size="md" disabled={recovery.busy || !recovery.selectedVolumeId}
            onClick={() => void recovery.buildCatalog()}>{t("buildCatalog")}</Button>
        </ActionRow>
      </FormGrid></Card>

      <Card size="sm" variant="flat"><DestinationRow>
        <DestinationInput><FormControl><FormControlCaption>{t("saveFiles")}</FormControlCaption><Input type="text" aria-label={t("saveFiles")} value={recovery.outputDirectory}
          disabled={recovery.busy} placeholder={t("chooseFolderPlaceholder")}
          onChange={recovery.setOutputDirectory} /></FormControl></DestinationInput>
        <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy} onClick={() => void recovery.chooseOutputDirectory()}>{t("chooseFolder")}</Button>
      </DestinationRow></Card>

      <Card size="sm" variant="flat"><Toolbar>
        <FileTypesControls>
          <DropdownCheckbox label={t("fileTypes")} placeholder={t("allFileTypes")}
            options={recovery.availableExtensions.map((extension) => ({ value: extension, label: extension }))}
            value={recovery.extensions} disabled={recovery.busy}
            onChange={(values) => getExtensionSelectionUpdates(recovery.availableExtensions, values).forEach(({ extension, checked }) =>
              recovery.setExtensionSelected(extension, checked))} />
          <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy || !recovery.availableExtensions.length}
            onClick={() => recovery.availableExtensions.forEach((extension) =>
              recovery.setExtensionSelected(extension, !allExtensionsSelected))}>{t("allTypes")}</Button>
        </FileTypesControls>
        <MinimumSizeControl><DropdownCheckbox label={t("minimumSize")} placeholder={t("anySize")} value={[String(recovery.minimumSizeKb)]}
          disabled={recovery.busy} options={[
            { value: "0", label: t("anySize") },
            { value: "5", label: "5 KB" },
            { value: "25", label: "25 KB" },
            { value: "100", label: "100 KB" },
            { value: "1024", label: "1 MB" },
          ]} onChange={(values) => recovery.setMinimumSizeKb(getMinimumSizeKb(values))} /></MinimumSizeControl>
        <SelectionActions>
          <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy || !recovery.catalog} onClick={recovery.selectAll}>{t("selectAll")}</Button>
          <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy || !recovery.catalog} onClick={recovery.clearSelection}>{t("clearSelection")}</Button>
          <Button className="brand-button--success" variant="success" size="md" disabled={recovery.busy || !recovery.selectedIds.size || !recovery.extensions.length || !recovery.outputDirectory.trim()}
            onClick={() => void recovery.recover()}>{t("recoverSelected")}</Button>
        </SelectionActions>
      </Toolbar></Card>

      <BrowserFrame><Card size="sm" variant="flat"><BrowserSection>
        <BrowserHeading>
          <div><h2>{t("foundFiles")}</h2>
            <p>{catalogSummary}</p></div>
          {recovery.catalog && <SelectionSummary>{recovery.selectedIds.size} {t("selectedItems")}</SelectionSummary>}
        </BrowserHeading>
        {recovery.catalog && <SearchBox><Input
          type="search"
          aria-label={t("searchFilesAria")}
          placeholder={t("searchFiles")}
          disabled={recovery.busy}
          value={recovery.searchQuery}
          onChange={recovery.setSearchQuery}
        /></SearchBox>}
        {!recovery.catalog ? <EmptyState>{t("emptyCatalog")}</EmptyState>
          : searchActive && recovery.searchingCatalog ? <EmptyState>{t("searchingCatalog")}</EmptyState>
            : visibleRoots?.length ? <RecoveryTree
          roots={visibleRoots}
          childrenById={recovery.childrenById}
          expandedFolderIds={recovery.expandedFolderIds}
          loadingFolderIds={recovery.loadingFolderIds}
          isSelected={recovery.isSelected}
          onToggleFolder={(node) => void recovery.toggleFolder(node)}
          onToggleSelection={recovery.toggleSelection}
          language={language}
        /> : <EmptyState>{searchActive ? t("noMatches") : t("noFiles")}</EmptyState>}
      </BrowserSection></Card></BrowserFrame>

      <RecoveryStatusPanel
        status={translateStatus(recovery.status, language)}
        progress={recovery.progress}
        error={translateError(recovery.error, language)}
        busy={recovery.busy}
        isAdministrator={recovery.isAdministrator}
        partitionScanCanResume={recovery.partitionScanCanResume}
        selectedDiskNumber={recovery.selectedDiskNumber}
        backendStatus={recovery.backendStatus}
        onRetryScan={() => void recovery.findPartitions(true, true)}
        onRequestDiskAccess={() => void recovery.ensureAdministrator()}
        language={language}
      />
      </PageContent>
      <BelagioFooter
        left={["Disk-Ressurect", t("version")]}
        center={[t("footerTitle")]}
        right={[t("desktopApp")]}
      />
    </PageLayout>
  );
};
