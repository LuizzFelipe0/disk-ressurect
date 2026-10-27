import React from "react";
import logo from "../../assets/disk-ressurect-logo.png";
import { useRecoveryController } from "../../hooks/useRecoveryController";
import { ActionButton } from "../../components/ActionButton";
import { EmptyState } from "../../components/EmptyState";
import { ErrorNotice } from "../../components/ErrorNotice";
import { FileTypeMultiSelect } from "../../components/FileTypeMultiSelect";
import { FormField } from "../../components/FormField";
import { RecoveryTree } from "../../components/RecoveryTree";
import { sanitizeDisplayText } from "../../utils/sanitizeDisplayText";
import {
  ActionRow,
  AppTitle,
  BackendRecoveryHint,
  BrowserHeading,
  BrowserSection,
  DestinationRow,
  Eyebrow,
  FilterGroup,
  Footer,
  FormGrid,
  PageHeader,
  PageLayout,
  SelectionActions,
  SelectionSummary,
  StatusLine,
  Toolbar,
} from "./style";

export const RecoveryPage: React.FC = () => {
  const recovery = useRecoveryController();
  const progressPercent = recovery.progress?.total
    ? Math.min(100, Math.round(recovery.progress.completed * 100 / recovery.progress.total))
    : 0;

  return (
    <PageLayout>
      <PageHeader>
        <div>
          <Eyebrow>DATA RECOVERY</Eyebrow>
          <AppTitle><img src={logo} alt="" aria-hidden="true" />Disk Ressurect</AppTitle>
          <p>Find partitions and choose the files you want to restore.</p>
        </div>
      </PageHeader>

      <FormGrid>
        <FormField label="Source disk">
          <select value={recovery.selectedDiskNumber} disabled={recovery.busy}
            onChange={(event) => recovery.selectDisk(event.target.value)}>
            <option value="">{recovery.backendStatus === "error" ? "Backend unavailable" : "Select a disk"}</option>
            {recovery.disks.map((disk) => <option key={disk.number} value={disk.number}>{sanitizeDisplayText(disk.displayName)}</option>)}
          </select>
        </FormField>
        <ActionRow>
          <ActionButton type="button" disabled={recovery.busy} onClick={() => void recovery.refreshDisks()}>Refresh</ActionButton>
          <ActionButton type="button" disabled={recovery.busy || !recovery.selectedDiskNumber}
            onClick={() => void recovery.findPartitions(false)}>Find partitions</ActionButton>
          <ActionButton type="button" disabled={recovery.busy || !recovery.selectedDiskNumber}
            onClick={() => void recovery.findPartitions(true)}>Deep scan</ActionButton>
        </ActionRow>
        <FormField label="NTFS partition">
          <select value={recovery.selectedVolumeId} disabled={recovery.busy || !recovery.volumes.length}
            onChange={(event) => recovery.selectVolume(event.target.value)}>
            <option value="">{recovery.volumes.length ? "Select a partition" : "Search the disk for partitions"}</option>
            {recovery.volumes.map((volume) => <option key={volume.id} value={volume.id}>{sanitizeDisplayText(volume.name)}</option>)}
          </select>
        </FormField>
        <ActionRow>
          <ActionButton variant="primary" type="button" disabled={recovery.busy || !recovery.selectedVolumeId}
            onClick={() => void recovery.buildCatalog()}>Build catalog</ActionButton>
        </ActionRow>
      </FormGrid>

      <DestinationRow>
        <FormField label="Save recovered files to" grow>
          <input value={recovery.outputDirectory} disabled={recovery.busy} placeholder="Choose a folder on another drive"
            onChange={(event) => recovery.setOutputDirectory(event.target.value)} />
        </FormField>
        <ActionButton type="button" disabled={recovery.busy} onClick={() => void recovery.chooseOutputDirectory()}>Choose folder…</ActionButton>
      </DestinationRow>

      <Toolbar>
        <FileTypeMultiSelect
          options={recovery.availableExtensions}
          selected={recovery.extensions}
          disabled={recovery.busy}
          onSelectionChange={recovery.setExtensionSelected}
        />
        <FilterGroup><label htmlFor="minimum-size">Minimum size</label>
          <select id="minimum-size" value={recovery.minimumSizeKb} disabled={recovery.busy}
            onChange={(event) => recovery.setMinimumSizeKb(Number(event.target.value))}>
            <option value={0}>Any size</option><option value={5}>5 KB</option><option value={25}>25 KB</option>
            <option value={100}>100 KB</option><option value={1024}>1 MB</option>
          </select>
        </FilterGroup>
        <SelectionActions>
          <ActionButton type="button" disabled={recovery.busy || !recovery.catalog} onClick={recovery.selectAll}>Select all</ActionButton>
          <ActionButton type="button" disabled={recovery.busy || !recovery.catalog} onClick={recovery.clearSelection}>Clear selection</ActionButton>
          <ActionButton variant="success" type="button" disabled={recovery.busy || !recovery.selectedIds.size || !recovery.extensions.length || !recovery.outputDirectory.trim()}
            onClick={() => void recovery.recover()}>Recover selected</ActionButton>
        </SelectionActions>
      </Toolbar>

      <BrowserSection>
        <BrowserHeading>
          <div><h2>Found files</h2>
            <p>{recovery.catalog
              ? `${recovery.catalog.recordCount.toLocaleString()} MFT records · ${recovery.catalog.availableExtensions.length} file types`
              : "Select a disk and build its catalog to browse folders."}</p></div>
          {recovery.catalog && <SelectionSummary>{recovery.selectedIds.size} item(s) selected</SelectionSummary>}
        </BrowserHeading>
        {recovery.catalog ? <RecoveryTree
          roots={recovery.catalog.roots}
          childrenById={recovery.childrenById}
          expandedFolderIds={recovery.expandedFolderIds}
          loadingFolderIds={recovery.loadingFolderIds}
          isSelected={recovery.isSelected}
          onToggleFolder={(node) => void recovery.toggleFolder(node)}
          onToggleSelection={recovery.toggleSelection}
        /> : <EmptyState>The folder catalog will appear here.</EmptyState>}
      </BrowserSection>

      <Footer>
        <StatusLine><span>{recovery.status}</span><span>{recovery.progress?.total ? `${recovery.progress.completed.toLocaleString()}/${recovery.progress.total.toLocaleString()} · ${progressPercent}%` : ""}</span></StatusLine>
        <progress max={100} value={progressPercent} />
        {recovery.error && <ErrorNotice spaced>Details: {recovery.error}</ErrorNotice>}
        {!recovery.isAdministrator && <>
          <ErrorNotice spaced>Physical disk access requires elevated permission. The source will be opened in read-only mode.</ErrorNotice>
          <ActionRow $topSpacing>
            <ActionButton type="button" disabled={recovery.busy} onClick={() => void recovery.ensureAdministrator()}>
              Request disk access permission
            </ActionButton>
          </ActionRow>
        </>}
          {recovery.backendStatus === "error" && <ActionRow $topSpacing><BackendRecoveryHint>Close and reopen the application to start another Python process.</BackendRecoveryHint></ActionRow>}
      </Footer>
    </PageLayout>
  );
};
