import React from "react";
import { Button, Card, DropdownCheckbox, Footer as BelagioFooter, Header, Input, Select } from "belagio-styles-lib";
import logo from "../../assets/disk-ressurect-logo.png";
import { useRecoveryController } from "../../hooks/useRecoveryController";
import { EmptyState } from "../../components/EmptyState";
import { ErrorNotice } from "../../components/ErrorNotice";
import { RecoveryTree } from "../../components/RecoveryTree";
import { RecoveryStatusPanel } from "../../components/RecoveryStatusPanel";
import { sanitizeDisplayText } from "../../utils/sanitizeDisplayText";
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
  const searchActive = Boolean(recovery.searchQuery.trim());
  const allExtensionsSelected = areAllExtensionsSelected(recovery.availableExtensions, recovery.extensions);
  const visibleRoots = searchActive
    ? recovery.searchResult?.results
    : recovery.catalog?.roots;
  const selectedDiskHasCachedScan = recovery.disks.some((disk) =>
    String(disk.number) === recovery.selectedDiskNumber && Boolean(disk.cachedPartitions?.length));
  const catalogSummary = !recovery.catalog
    ? "Select a disk and build its catalog to browse folders."
    : searchActive && recovery.searchResult
      ? recovery.searchResult.totalMatches > recovery.searchResult.results.length
        ? `Showing ${recovery.searchResult.results.length.toLocaleString()} of ${recovery.searchResult.totalMatches.toLocaleString()} matches`
        : `${recovery.searchResult.totalMatches.toLocaleString()} matching item(s)`
      : `${recovery.catalog.recordCount.toLocaleString()} MFT records · ${recovery.catalog.availableExtensions.length} file types`;

  return (
    <PageLayout>
      <PageHeader>
        <Header icon={logo} title="Disk-Ressurect" />
      </PageHeader>

      <PageContent id="recovery-page-content">
      <Card size="sm" variant="flat"><FormGrid>
        <FormControl><FormControlCaption>Source disk</FormControlCaption><Select aria-label="Source disk" value={recovery.selectedDiskNumber} disabled={recovery.busy}
          onChange={recovery.selectDisk} options={[
            { value: "", label: recovery.backendStatus === "error" ? "Backend unavailable" : "Select a disk" },
            ...recovery.disks.map((disk) => ({ value: String(disk.number), label: sanitizeDisplayText(disk.displayName) })),
          ]} /></FormControl>
        <ActionRow>
          <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy} onClick={() => void recovery.refreshDisks()}>Refresh</Button>
          <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy || !recovery.selectedDiskNumber}
            onClick={() => void recovery.findPartitions(false)}>Find partitions</Button>
          <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy || !recovery.selectedDiskNumber}
            onClick={() => void recovery.findPartitions(true)}>{selectedDiskHasCachedScan ? "Deep scan again" : "Deep scan"}</Button>
        </ActionRow>
        <FormControl><FormControlCaption>NTFS partition</FormControlCaption><Select aria-label="NTFS partition" value={recovery.selectedVolumeId}
          disabled={recovery.busy || !recovery.volumes.length} onChange={recovery.selectVolume} options={[
            { value: "", label: recovery.volumes.length ? "Select a partition" : "Search the disk for partitions" },
            ...recovery.volumes.map((volume) => ({ value: volume.id, label: sanitizeDisplayText(volume.name) })),
          ]} /></FormControl>
        <ActionRow>
          <Button className="brand-button--primary" variant="primary" size="md" disabled={recovery.busy || !recovery.selectedVolumeId}
            onClick={() => void recovery.buildCatalog()}>Build catalog</Button>
        </ActionRow>
      </FormGrid></Card>

      <Card size="sm" variant="flat"><DestinationRow>
        <DestinationInput><FormControl><FormControlCaption>Save recovered files to</FormControlCaption><Input type="text" aria-label="Save recovered files to" value={recovery.outputDirectory}
          disabled={recovery.busy} placeholder="Choose a folder on another drive"
          onChange={recovery.setOutputDirectory} /></FormControl></DestinationInput>
        <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy} onClick={() => void recovery.chooseOutputDirectory()}>Choose folder…</Button>
      </DestinationRow></Card>

      <Card size="sm" variant="flat"><Toolbar>
        <FileTypesControls>
          <DropdownCheckbox label="File types" placeholder="All file types"
            options={recovery.availableExtensions.map((extension) => ({ value: extension, label: extension }))}
            value={recovery.extensions} disabled={recovery.busy}
            onChange={(values) => getExtensionSelectionUpdates(recovery.availableExtensions, values).forEach(({ extension, checked }) =>
              recovery.setExtensionSelected(extension, checked))} />
          <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy || !recovery.availableExtensions.length}
            onClick={() => recovery.availableExtensions.forEach((extension) =>
              recovery.setExtensionSelected(extension, !allExtensionsSelected))}>All Types</Button>
        </FileTypesControls>
        <MinimumSizeControl><DropdownCheckbox label="Minimum size" placeholder="Any size" value={[String(recovery.minimumSizeKb)]}
          disabled={recovery.busy} options={[
            { value: "0", label: "Any size" },
            { value: "5", label: "5 KB" },
            { value: "25", label: "25 KB" },
            { value: "100", label: "100 KB" },
            { value: "1024", label: "1 MB" },
          ]} onChange={(values) => recovery.setMinimumSizeKb(getMinimumSizeKb(values))} /></MinimumSizeControl>
        <SelectionActions>
          <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy || !recovery.catalog} onClick={recovery.selectAll}>Select all</Button>
          <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy || !recovery.catalog} onClick={recovery.clearSelection}>Clear selection</Button>
          <Button className="brand-button--success" variant="success" size="md" disabled={recovery.busy || !recovery.selectedIds.size || !recovery.extensions.length || !recovery.outputDirectory.trim()}
            onClick={() => void recovery.recover()}>Recover selected</Button>
        </SelectionActions>
      </Toolbar></Card>

      <BrowserFrame><Card size="sm" variant="flat"><BrowserSection>
        <BrowserHeading>
          <div><h2>Found files</h2>
            <p>{catalogSummary}</p></div>
          {recovery.catalog && <SelectionSummary>{recovery.selectedIds.size} item(s) selected</SelectionSummary>}
        </BrowserHeading>
        {recovery.catalog && <SearchBox><Input
          type="search"
          aria-label="Search files and folders"
          placeholder="Search files and folders…"
          disabled={recovery.busy}
          value={recovery.searchQuery}
          onChange={recovery.setSearchQuery}
        /></SearchBox>}
        {!recovery.catalog ? <EmptyState>The folder catalog will appear here.</EmptyState>
          : searchActive && recovery.searchingCatalog ? <EmptyState>Searching the catalog…</EmptyState>
            : visibleRoots?.length ? <RecoveryTree
          roots={visibleRoots}
          childrenById={recovery.childrenById}
          expandedFolderIds={recovery.expandedFolderIds}
          loadingFolderIds={recovery.loadingFolderIds}
          isSelected={recovery.isSelected}
          onToggleFolder={(node) => void recovery.toggleFolder(node)}
          onToggleSelection={recovery.toggleSelection}
        /> : <EmptyState>{searchActive ? "No matching files or folders." : "No folders or files to display."}</EmptyState>}
      </BrowserSection></Card></BrowserFrame>

      <RecoveryStatusPanel
        status={recovery.status}
        progress={recovery.progress}
        error={recovery.error}
        busy={recovery.busy}
        isAdministrator={recovery.isAdministrator}
        partitionScanCanResume={recovery.partitionScanCanResume}
        selectedDiskNumber={recovery.selectedDiskNumber}
        backendStatus={recovery.backendStatus}
        onRetryScan={() => void recovery.findPartitions(true, true)}
        onRequestDiskAccess={() => void recovery.ensureAdministrator()}
      />
      </PageContent>
      <BelagioFooter
        left={["Disk-Ressurect", "Version 0.2.0"]}
        center={["NTFS data recovery"]}
        right={["Desktop application"]}
      />
    </PageLayout>
  );
};
