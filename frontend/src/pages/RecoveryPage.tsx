import React from "react";
import { useRecoveryController } from "../hooks/useRecoveryController";
import { RecoveryTree } from "../components/RecoveryTree";
import {
  ActionRow,
  Badge,
  BrowserHeading,
  BrowserSection,
  Button,
  DestinationRow,
  EmptyState,
  ErrorNotice,
  Eyebrow,
  Field,
  FileTypes,
  FilterGroup,
  Footer,
  FormGrid,
  Header,
  Page,
  SelectionActions,
  SelectionSummary,
  StatusLine,
  Toolbar,
} from "../components/ui";

export const RecoveryPage: React.FC = () => {
  const recovery = useRecoveryController();
  const progressPercent = recovery.progress?.total
    ? Math.min(100, Math.round(recovery.progress.completed * 100 / recovery.progress.total))
    : 0;

  return (
    <Page>
      <Header>
        <div>
          <Eyebrow>RECUPERAÇÃO DE DADOS</Eyebrow>
          <h1>Disk Ressurect</h1>
          <p>Encontre partições e escolha os arquivos que deseja restaurar.</p>
        </div>
        <Badge $tone={!recovery.isAdministrator || recovery.backendStatus === "error" ? "error" : recovery.backendStatus === "ready" ? "ready" : "working"}>
          {!recovery.isAdministrator ? "Permissão de administrador necessária" : recovery.backendStatus === "ready" ? "Serviço Python ativo" : recovery.backendStatus === "error" ? "Serviço Python indisponível" : "Iniciando serviço Python…"}
        </Badge>
      </Header>

      <FormGrid>
        <Field>Disco de origem
          <select value={recovery.selectedDiskNumber} disabled={recovery.busy}
            onChange={(event) => recovery.selectDisk(event.target.value)}>
            <option value="">{recovery.backendStatus === "error" ? "Backend indisponível" : "Selecione um disco"}</option>
            {recovery.disks.map((disk) => <option key={disk.number} value={disk.number}>{disk.displayName}</option>)}
          </select>
        </Field>
        <ActionRow>
          <Button type="button" disabled={recovery.busy} onClick={() => void recovery.refreshDisks()}>Atualizar</Button>
          <Button type="button" disabled={recovery.busy || !recovery.selectedDiskNumber}
            onClick={() => void recovery.findPartitions(false)}>Buscar partições</Button>
          <Button type="button" disabled={recovery.busy || !recovery.selectedDiskNumber}
            onClick={() => void recovery.findPartitions(true)}>Deep scan</Button>
        </ActionRow>
        <Field>Partição NTFS
          <select value={recovery.selectedVolumeId} disabled={recovery.busy || !recovery.volumes.length}
            onChange={(event) => recovery.selectVolume(event.target.value)}>
            <option value="">{recovery.volumes.length ? "Selecione uma partição" : "Busque partições do disco"}</option>
            {recovery.volumes.map((volume) => <option key={volume.id} value={volume.id}>{volume.name}</option>)}
          </select>
        </Field>
        <ActionRow>
          <Button $variant="primary" type="button" disabled={recovery.busy || !recovery.selectedVolumeId}
            onClick={() => void recovery.buildCatalog()}>Montar catálogo</Button>
        </ActionRow>
      </FormGrid>

      <DestinationRow>
        <Field style={{ flex: 1 }}>Salvar arquivos recuperados em
          <input value={recovery.outputDirectory} disabled={recovery.busy} placeholder="Escolha uma pasta em outro disco"
            onChange={(event) => recovery.setOutputDirectory(event.target.value)} />
        </Field>
        <Button type="button" disabled={recovery.busy} onClick={() => void recovery.chooseOutputDirectory()}>Escolher pasta…</Button>
      </DestinationRow>

      <Toolbar>
        <FilterGroup>
          <label>Tipos de arquivo</label>
          {recovery.extensions.length ? (
            <FileTypes>
              {recovery.extensions.map((extension) => (
                <label key={extension}>
                  <input type="checkbox" checked={recovery.extensions.includes(extension)} onChange={(event) => recovery.setExtensionSelected(extension, event.target.checked)} disabled={recovery.busy} />
                  {extension}
                </label>
              ))}
            </FileTypes>
          ) : <small>Monte o catálogo para listar os tipos disponíveis.</small>}
        </FilterGroup>
        <FilterGroup><label htmlFor="minimum-size">Tamanho mínimo</label>
          <select id="minimum-size" value={recovery.minimumSizeKb} disabled={recovery.busy}
            onChange={(event) => recovery.setMinimumSizeKb(Number(event.target.value))}>
            <option value={0}>Qualquer tamanho</option><option value={5}>5 KB</option><option value={25}>25 KB</option>
            <option value={100}>100 KB</option><option value={1024}>1 MB</option>
          </select>
        </FilterGroup>
        <SelectionActions>
          <Button type="button" disabled={recovery.busy || !recovery.catalog} onClick={recovery.selectAll}>Selecionar tudo</Button>
          <Button type="button" disabled={recovery.busy || !recovery.catalog} onClick={recovery.clearSelection}>Limpar seleção</Button>
          <Button $variant="success" type="button" disabled={recovery.busy || !recovery.selectedIds.size || !recovery.extensions.length || !recovery.outputDirectory.trim()}
            onClick={() => void recovery.recover()}>Recuperar selecionados</Button>
        </SelectionActions>
      </Toolbar>

      <BrowserSection>
        <BrowserHeading>
          <div><h2>Arquivos encontrados</h2>
            <p>{recovery.catalog
              ? `${recovery.catalog.recordCount.toLocaleString()} registros MFT · ${recovery.catalog.availableExtensions.length} tipos de arquivo`
              : "Selecione um disco e monte o catálogo para navegar pelas pastas."}</p></div>
          {recovery.catalog && <SelectionSummary>{recovery.selectedIds.size} item(ns) selecionado(s)</SelectionSummary>}
        </BrowserHeading>
        {recovery.catalog ? <RecoveryTree
          roots={recovery.catalog.roots}
          childrenById={recovery.childrenById}
          expandedFolderIds={recovery.expandedFolderIds}
          loadingFolderIds={recovery.loadingFolderIds}
          isSelected={recovery.isSelected}
          onToggleFolder={(node) => void recovery.toggleFolder(node)}
          onToggleSelection={recovery.toggleSelection}
        /> : <EmptyState>O catálogo de pastas aparecerá aqui.</EmptyState>}
      </BrowserSection>

      <Footer>
        <StatusLine><span>{recovery.status}</span><span>{recovery.progress?.total ? `${recovery.progress.completed.toLocaleString()}/${recovery.progress.total.toLocaleString()} · ${progressPercent}%` : ""}</span></StatusLine>
        <progress max={100} value={progressPercent} />
        {recovery.error && <ErrorNotice style={{ marginTop: 10 }}>Detalhes: {recovery.error}</ErrorNotice>}
        {!recovery.isAdministrator && <>
          <ErrorNotice style={{ marginTop: 10 }}>O Windows exige permissão de administrador para ler discos físicos. A origem será aberta somente para leitura.</ErrorNotice>
          <ActionRow style={{ marginTop: 9 }}>
            <Button type="button" disabled={recovery.busy} onClick={() => void recovery.ensureAdministrator()}>
              Solicitar permissão ao Windows
            </Button>
          </ActionRow>
        </>}
          {recovery.backendStatus === "error" && <ActionRow style={{ marginTop: 9 }}><span style={{ color: "#a4313e", fontSize: 11 }}>Feche e reabra o aplicativo para iniciar outro processo Python.</span></ActionRow>}
      </Footer>
    </Page>
  );
};
