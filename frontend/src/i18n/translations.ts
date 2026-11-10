import type { SiteLanguage } from "belagio-styles-lib";

export type TranslationKey = keyof typeof messages["en-US"];

const messages = {
  "en-US": {
    sourceDisk: "Source disk", sourceDiskAria: "Source disk", backendUnavailable: "Backend unavailable", selectDisk: "Select a disk",
    refresh: "Refresh", findPartitions: "Find partitions", deepScanAgain: "Deep scan again", deepScan: "Deep scan", ntfsPartition: "NTFS partition",
    selectPartition: "Select a partition", searchPartitions: "Search the disk for partitions", buildCatalog: "Build catalog", saveFiles: "Save recovered files to",
    chooseFolderPlaceholder: "Choose a folder on another drive", chooseFolder: "Choose folder…", fileTypes: "File types", allFileTypes: "All file types",
    allTypes: "All Types", minimumSize: "Minimum size", anySize: "Any size", selectAll: "Select all", clearSelection: "Clear selection",
    recoverSelected: "Recover selected", foundFiles: "Found files", selectedItems: "item(s) selected", searchFiles: "Search files and folders…",
    searchFilesAria: "Search files and folders", emptyCatalog: "The folder catalog will appear here.", searchingCatalog: "Searching the catalog…",
    noMatches: "No matching files or folders.", noFiles: "No folders or files to display.", catalogPrompt: "Select a disk and build its catalog to browse folders.",
    matchingItems: "matching item(s)", showingMatches: "Showing {visible} of {total} matches", fileTypesCount: "file types", mftRecords: "MFT records", folder: "Folder", loadingContents: "Loading contents of {name}…",
    expand: "Expand", collapse: "Collapse", select: "Select", contentsOf: "Contents of {name}", recoveryCatalog: "Recovery catalog",
    recoveryStatus: "Recovery status", progress: "Recovery progress", complete: "{percent}% complete", noProgress: "No active progress", retryScan: "Retry scan",
    recoveryProblem: "Recovery problem", adminRequired: "Administrator permission required", elevatedAccess: "Physical disk access requires elevated permission. The source will be opened in read-only mode.",
    requestAccess: "Request disk access permission", restartApp: "Close and reopen the application to start another Python process.",
    footerTitle: "NTFS data recovery", desktopApp: "Desktop application", version: "Version 0.2.0",
    statusStarting: "Starting the Python recovery service…", statusChecking: "Checking disks through the Python service…", statusProcessExited: "The Python recovery process has exited.", statusPreviousDisk: "The previous source disk was restored. Search it for NTFS partitions.",
    statusDiscoveryFailed: "Disk discovery failed. See the details below.", statusUnableCheck: "Unable to check the Python service status.",
    statusElevated: "Reading physical disks requires elevated permission.", statusPermissionGranted: "Disk access permission was granted.",
    statusRestarting: "The application is restarting with elevated permissions.", statusCanceledPermission: "The scan was canceled because disk access permission was not granted.",
    errorAuthorize: "Authorize the system permission request to read physical disks.", statusUnableRequest: "Unable to request elevated disk access.",
    statusSearchDisk: "Search this disk for NTFS partitions.", statusChooseDisk: "Choose a source disk.", statusResumeScan: "Resuming lost-partition scan…",
    statusSearchingLost: "Searching for lost NTFS partitions…", statusScanning: "Scanning partitions…", statusNoPartitions: "No readable NTFS partitions were found.",
    statusScanFailed: "Partition search failed. The scan position has been saved when available.", statusBuildBrowse: "Build the catalog to browse the discovered files.",
    statusSelectPartition: "Select an NTFS partition.", statusReadingCatalog: "Reading metadata and building the catalog…", statusUnableCatalog: "Unable to build the catalog.",
    statusRecovering: "Recovering the selected items…", statusRecoveryFailed: "Recovery failed.", statusRecoveryCompleted: "Recovery completed.",
    destinationRequired: "Choose a destination folder to continue.", selectionRequired: "Select files and at least one file type.",
  },
  "pt-BR": {
    sourceDisk: "Disco de origem", sourceDiskAria: "Disco de origem", backendUnavailable: "Serviço indisponível", selectDisk: "Selecione um disco",
    refresh: "Atualizar", findPartitions: "Buscar partições", deepScanAgain: "Repetir busca profunda", deepScan: "Busca profunda", ntfsPartition: "Partição NTFS",
    selectPartition: "Selecione uma partição", searchPartitions: "Busque partições no disco", buildCatalog: "Montar catálogo", saveFiles: "Salvar arquivos recuperados em",
    chooseFolderPlaceholder: "Escolha uma pasta em outro disco", chooseFolder: "Escolher pasta…", fileTypes: "Tipos de arquivo", allFileTypes: "Todos os tipos de arquivo",
    allTypes: "Todos os tipos", minimumSize: "Tamanho mínimo", anySize: "Qualquer tamanho", selectAll: "Selecionar tudo", clearSelection: "Limpar seleção",
    recoverSelected: "Recuperar selecionados", foundFiles: "Arquivos encontrados", selectedItems: "item(ns) selecionado(s)", searchFiles: "Buscar arquivos e pastas…",
    searchFilesAria: "Buscar arquivos e pastas", emptyCatalog: "O catálogo de pastas aparecerá aqui.", searchingCatalog: "Buscando no catálogo…",
    noMatches: "Nenhum arquivo ou pasta corresponde à busca.", noFiles: "Nenhuma pasta ou arquivo para exibir.", catalogPrompt: "Selecione um disco e monte o catálogo para navegar pelas pastas.",
    matchingItems: "item(ns) correspondente(s)", showingMatches: "Exibindo {visible} de {total} resultados", fileTypesCount: "tipos de arquivo", mftRecords: "registros MFT", folder: "Pasta", loadingContents: "Carregando conteúdo de {name}…",
    expand: "Expandir", collapse: "Recolher", select: "Selecionar", contentsOf: "Conteúdo de {name}", recoveryCatalog: "Catálogo de recuperação",
    recoveryStatus: "Status da recuperação", progress: "Progresso da recuperação", complete: "{percent}% concluído", noProgress: "Sem progresso ativo", retryScan: "Tentar busca novamente",
    recoveryProblem: "Problema na recuperação", adminRequired: "Permissão de administrador necessária", elevatedAccess: "O acesso ao disco físico exige permissão elevada. A origem será aberta em modo somente leitura.",
    requestAccess: "Solicitar permissão de acesso ao disco", restartApp: "Feche e reabra o aplicativo para iniciar outro processo Python.",
    footerTitle: "Recuperação de dados NTFS", desktopApp: "Aplicativo para desktop", version: "Versão 0.2.0",
    statusStarting: "Iniciando o serviço de recuperação Python…", statusChecking: "Verificando discos pelo serviço Python…", statusProcessExited: "O processo Python de recuperação foi encerrado.", statusPreviousDisk: "O disco de origem anterior foi restaurado. Busque partições NTFS nele.",
    statusDiscoveryFailed: "Falha ao localizar discos. Veja os detalhes abaixo.", statusUnableCheck: "Não foi possível verificar o status do serviço Python.",
    statusElevated: "A leitura dos discos físicos exige permissão elevada.", statusPermissionGranted: "A permissão de acesso ao disco foi concedida.",
    statusRestarting: "O aplicativo está reiniciando com permissões elevadas.", statusCanceledPermission: "A busca foi cancelada porque a permissão de acesso ao disco não foi concedida.",
    errorAuthorize: "Autorize a solicitação do sistema para ler discos físicos.", statusUnableRequest: "Não foi possível solicitar acesso elevado ao disco.",
    statusSearchDisk: "Busque partições NTFS neste disco.", statusChooseDisk: "Escolha um disco de origem.", statusResumeScan: "Retomando a busca por partições perdidas…",
    statusSearchingLost: "Buscando partições NTFS perdidas…", statusScanning: "Verificando partições…", statusNoPartitions: "Nenhuma partição NTFS legível foi encontrada.",
    statusScanFailed: "Falha na busca por partições. A posição foi salva quando disponível.", statusBuildBrowse: "Monte o catálogo para navegar pelos arquivos encontrados.",
    statusSelectPartition: "Selecione uma partição NTFS.", statusReadingCatalog: "Lendo metadados e montando o catálogo…", statusUnableCatalog: "Não foi possível montar o catálogo.",
    statusRecovering: "Recuperando os itens selecionados…", statusRecoveryFailed: "Falha na recuperação.", statusRecoveryCompleted: "Recuperação concluída.",
    destinationRequired: "Escolha uma pasta de destino para continuar.", selectionRequired: "Selecione arquivos e pelo menos um tipo de arquivo.",
  },
  "es-ES": {
    sourceDisk: "Disco de origen", sourceDiskAria: "Disco de origen", backendUnavailable: "Servicio no disponible", selectDisk: "Selecciona un disco",
    refresh: "Actualizar", findPartitions: "Buscar particiones", deepScanAgain: "Repetir búsqueda profunda", deepScan: "Búsqueda profunda", ntfsPartition: "Partición NTFS",
    selectPartition: "Selecciona una partición", searchPartitions: "Buscar particiones en el disco", buildCatalog: "Crear catálogo", saveFiles: "Guardar archivos recuperados en",
    chooseFolderPlaceholder: "Elige una carpeta en otra unidad", chooseFolder: "Elegir carpeta…", fileTypes: "Tipos de archivo", allFileTypes: "Todos los tipos de archivo",
    allTypes: "Todos los tipos", minimumSize: "Tamaño mínimo", anySize: "Cualquier tamaño", selectAll: "Seleccionar todo", clearSelection: "Borrar selección",
    recoverSelected: "Recuperar seleccionados", foundFiles: "Archivos encontrados", selectedItems: "elemento(s) seleccionado(s)", searchFiles: "Buscar archivos y carpetas…",
    searchFilesAria: "Buscar archivos y carpetas", emptyCatalog: "El catálogo de carpetas aparecerá aquí.", searchingCatalog: "Buscando en el catálogo…",
    noMatches: "No hay archivos ni carpetas que coincidan.", noFiles: "No hay carpetas ni archivos para mostrar.", catalogPrompt: "Selecciona un disco y crea su catálogo para explorar las carpetas.",
    matchingItems: "elemento(s) coincidente(s)", showingMatches: "Mostrando {visible} de {total} resultados", fileTypesCount: "tipos de archivo", mftRecords: "registros MFT", folder: "Carpeta", loadingContents: "Cargando contenido de {name}…",
    expand: "Expandir", collapse: "Contraer", select: "Seleccionar", contentsOf: "Contenido de {name}", recoveryCatalog: "Catálogo de recuperación",
    recoveryStatus: "Estado de recuperación", progress: "Progreso de recuperación", complete: "{percent}% completado", noProgress: "Sin progreso activo", retryScan: "Reintentar búsqueda",
    recoveryProblem: "Problema de recuperación", adminRequired: "Se requieren permisos de administrador", elevatedAccess: "El acceso al disco físico requiere permisos elevados. El origen se abrirá en modo de solo lectura.",
    requestAccess: "Solicitar permiso de acceso al disco", restartApp: "Cierra y vuelve a abrir la aplicación para iniciar otro proceso de Python.",
    footerTitle: "Recuperación de datos NTFS", desktopApp: "Aplicación de escritorio", version: "Versión 0.2.0",
    statusStarting: "Iniciando el servicio de recuperación de Python…", statusChecking: "Comprobando discos mediante el servicio de Python…", statusProcessExited: "El proceso de recuperación de Python se ha cerrado.", statusPreviousDisk: "Se restauró el disco de origen anterior. Busca particiones NTFS en él.",
    statusDiscoveryFailed: "No se pudieron detectar los discos. Consulta los detalles.", statusUnableCheck: "No se pudo comprobar el estado del servicio de Python.",
    statusElevated: "La lectura de discos físicos requiere permisos elevados.", statusPermissionGranted: "Se concedió el permiso de acceso al disco.",
    statusRestarting: "La aplicación se está reiniciando con permisos elevados.", statusCanceledPermission: "Se canceló el análisis porque no se concedió el permiso de acceso al disco.",
    errorAuthorize: "Autoriza la solicitud del sistema para leer discos físicos.", statusUnableRequest: "No se pudo solicitar acceso elevado al disco.",
    statusSearchDisk: "Busca particiones NTFS en este disco.", statusChooseDisk: "Elige un disco de origen.", statusResumeScan: "Reanudando la búsqueda de particiones perdidas…",
    statusSearchingLost: "Buscando particiones NTFS perdidas…", statusScanning: "Analizando particiones…", statusNoPartitions: "No se encontraron particiones NTFS legibles.",
    statusScanFailed: "Falló la búsqueda de particiones. Se guardó la posición cuando fue posible.", statusBuildBrowse: "Crea el catálogo para explorar los archivos encontrados.",
    statusSelectPartition: "Selecciona una partición NTFS.", statusReadingCatalog: "Leyendo metadatos y creando el catálogo…", statusUnableCatalog: "No se pudo crear el catálogo.",
    statusRecovering: "Recuperando los elementos seleccionados…", statusRecoveryFailed: "Falló la recuperación.", statusRecoveryCompleted: "Recuperación completada.",
    destinationRequired: "Elige una carpeta de destino para continuar.", selectionRequired: "Selecciona archivos y al menos un tipo de archivo.",
  },
  "fr-FR": {
    sourceDisk: "Disque source", sourceDiskAria: "Disque source", backendUnavailable: "Service indisponible", selectDisk: "Sélectionner un disque",
    refresh: "Actualiser", findPartitions: "Rechercher des partitions", deepScanAgain: "Relancer l’analyse approfondie", deepScan: "Analyse approfondie", ntfsPartition: "Partition NTFS",
    selectPartition: "Sélectionner une partition", searchPartitions: "Rechercher des partitions sur le disque", buildCatalog: "Créer le catalogue", saveFiles: "Enregistrer les fichiers récupérés dans",
    chooseFolderPlaceholder: "Choisir un dossier sur un autre disque", chooseFolder: "Choisir un dossier…", fileTypes: "Types de fichiers", allFileTypes: "Tous les types de fichiers",
    allTypes: "Tous les types", minimumSize: "Taille minimale", anySize: "Toute taille", selectAll: "Tout sélectionner", clearSelection: "Effacer la sélection",
    recoverSelected: "Récupérer la sélection", foundFiles: "Fichiers trouvés", selectedItems: "élément(s) sélectionné(s)", searchFiles: "Rechercher des fichiers et dossiers…",
    searchFilesAria: "Rechercher des fichiers et dossiers", emptyCatalog: "Le catalogue des dossiers apparaîtra ici.", searchingCatalog: "Recherche dans le catalogue…",
    noMatches: "Aucun fichier ou dossier ne correspond.", noFiles: "Aucun dossier ou fichier à afficher.", catalogPrompt: "Sélectionnez un disque et créez son catalogue pour parcourir les dossiers.",
    matchingItems: "élément(s) correspondant(s)", showingMatches: "Affichage de {visible} résultats sur {total}", fileTypesCount: "types de fichiers", mftRecords: "enregistrements MFT", folder: "Dossier", loadingContents: "Chargement du contenu de {name}…",
    expand: "Développer", collapse: "Réduire", select: "Sélectionner", contentsOf: "Contenu de {name}", recoveryCatalog: "Catalogue de récupération",
    recoveryStatus: "État de la récupération", progress: "Progression de la récupération", complete: "{percent}% terminé", noProgress: "Aucune progression active", retryScan: "Relancer l’analyse",
    recoveryProblem: "Problème de récupération", adminRequired: "Autorisation administrateur requise", elevatedAccess: "L’accès au disque physique nécessite une autorisation élevée. La source sera ouverte en lecture seule.",
    requestAccess: "Demander l’autorisation d’accès au disque", restartApp: "Fermez puis rouvrez l’application pour démarrer un autre processus Python.",
    footerTitle: "Récupération de données NTFS", desktopApp: "Application de bureau", version: "Version 0.2.0",
    statusStarting: "Démarrage du service de récupération Python…", statusChecking: "Vérification des disques via le service Python…", statusProcessExited: "Le processus de récupération Python s’est arrêté.", statusPreviousDisk: "Le disque source précédent a été restauré. Recherchez-y des partitions NTFS.",
    statusDiscoveryFailed: "Échec de la détection des disques. Consultez les détails.", statusUnableCheck: "Impossible de vérifier l’état du service Python.",
    statusElevated: "La lecture des disques physiques nécessite une autorisation élevée.", statusPermissionGranted: "L’autorisation d’accès au disque a été accordée.",
    statusRestarting: "L’application redémarre avec des autorisations élevées.", statusCanceledPermission: "L’analyse a été annulée faute d’autorisation d’accès au disque.",
    errorAuthorize: "Autorisez la demande système pour lire les disques physiques.", statusUnableRequest: "Impossible de demander un accès élevé au disque.",
    statusSearchDisk: "Recherchez des partitions NTFS sur ce disque.", statusChooseDisk: "Choisissez un disque source.", statusResumeScan: "Reprise de la recherche des partitions perdues…",
    statusSearchingLost: "Recherche des partitions NTFS perdues…", statusScanning: "Analyse des partitions…", statusNoPartitions: "Aucune partition NTFS lisible n’a été trouvée.",
    statusScanFailed: "Échec de la recherche. La position a été enregistrée si possible.", statusBuildBrowse: "Créez le catalogue pour parcourir les fichiers trouvés.",
    statusSelectPartition: "Sélectionnez une partition NTFS.", statusReadingCatalog: "Lecture des métadonnées et création du catalogue…", statusUnableCatalog: "Impossible de créer le catalogue.",
    statusRecovering: "Récupération des éléments sélectionnés…", statusRecoveryFailed: "Échec de la récupération.", statusRecoveryCompleted: "Récupération terminée.",
    destinationRequired: "Choisissez un dossier de destination pour continuer.", selectionRequired: "Sélectionnez des fichiers et au moins un type de fichier.",
  },
  "zh-CN": {
    sourceDisk: "源磁盘", sourceDiskAria: "源磁盘", backendUnavailable: "后端不可用", selectDisk: "选择磁盘",
    refresh: "刷新", findPartitions: "查找分区", deepScanAgain: "再次深度扫描", deepScan: "深度扫描", ntfsPartition: "NTFS 分区",
    selectPartition: "选择分区", searchPartitions: "搜索磁盘分区", buildCatalog: "创建目录", saveFiles: "将恢复的文件保存到",
    chooseFolderPlaceholder: "选择另一块磁盘上的文件夹", chooseFolder: "选择文件夹…", fileTypes: "文件类型", allFileTypes: "所有文件类型",
    allTypes: "所有类型", minimumSize: "最小大小", anySize: "任意大小", selectAll: "全选", clearSelection: "清除选择",
    recoverSelected: "恢复所选项目", foundFiles: "找到的文件", selectedItems: "项已选择", searchFiles: "搜索文件和文件夹…",
    searchFilesAria: "搜索文件和文件夹", emptyCatalog: "文件夹目录将显示在此处。", searchingCatalog: "正在搜索目录…",
    noMatches: "没有匹配的文件或文件夹。", noFiles: "没有可显示的文件或文件夹。", catalogPrompt: "选择磁盘并创建目录以浏览文件夹。",
    matchingItems: "个匹配项", showingMatches: "显示 {visible} / {total} 个结果", fileTypesCount: "种文件类型", mftRecords: "条 MFT 记录", folder: "文件夹", loadingContents: "正在加载 {name} 的内容…",
    expand: "展开", collapse: "折叠", select: "选择", contentsOf: "{name} 的内容", recoveryCatalog: "恢复目录",
    recoveryStatus: "恢复状态", progress: "恢复进度", complete: "已完成 {percent}%", noProgress: "当前没有进度", retryScan: "重试扫描",
    recoveryProblem: "恢复问题", adminRequired: "需要管理员权限", elevatedAccess: "访问物理磁盘需要提升权限。源磁盘将以只读模式打开。",
    requestAccess: "请求磁盘访问权限", restartApp: "关闭并重新打开应用以启动另一个 Python 进程。",
    footerTitle: "NTFS 数据恢复", desktopApp: "桌面应用", version: "版本 0.2.0",
    statusStarting: "正在启动 Python 恢复服务…", statusChecking: "正在通过 Python 服务检查磁盘…", statusProcessExited: "Python 恢复进程已退出。", statusPreviousDisk: "已恢复上次的源磁盘。搜索其中的 NTFS 分区。",
    statusDiscoveryFailed: "磁盘发现失败。请查看下方详情。", statusUnableCheck: "无法检查 Python 服务状态。",
    statusElevated: "读取物理磁盘需要提升权限。", statusPermissionGranted: "已授予磁盘访问权限。",
    statusRestarting: "应用正在以提升的权限重新启动。", statusCanceledPermission: "未授予磁盘访问权限，扫描已取消。",
    errorAuthorize: "请授权系统权限请求以读取物理磁盘。", statusUnableRequest: "无法请求提升的磁盘访问权限。",
    statusSearchDisk: "搜索此磁盘上的 NTFS 分区。", statusChooseDisk: "选择源磁盘。", statusResumeScan: "正在恢复丢失分区扫描…",
    statusSearchingLost: "正在搜索丢失的 NTFS 分区…", statusScanning: "正在扫描分区…", statusNoPartitions: "未找到可读取的 NTFS 分区。",
    statusScanFailed: "分区搜索失败；可用时已保存扫描位置。", statusBuildBrowse: "创建目录以浏览发现的文件。",
    statusSelectPartition: "选择 NTFS 分区。", statusReadingCatalog: "正在读取元数据并创建目录…", statusUnableCatalog: "无法创建目录。",
    statusRecovering: "正在恢复所选项目…", statusRecoveryFailed: "恢复失败。", statusRecoveryCompleted: "恢复完成。",
    destinationRequired: "选择目标文件夹以继续。", selectionRequired: "请选择文件和至少一种文件类型。",
  },
} satisfies Record<SiteLanguage, Record<string, string>>;

export function translate(language: SiteLanguage, key: TranslationKey, values: Record<string, string | number> = {}) {
  return messages[language][key].replace(/\{(\w+)\}/g, (_match, name: string) => String(values[name] ?? `{${name}}`));
}

export function translateStatus(status: string, language: SiteLanguage) {
  const lookup: Record<string, TranslationKey> = {
    "Starting the Python recovery service…": "statusStarting", "Checking disks through the Python service…": "statusChecking",
    "The Python recovery process has exited.": "statusProcessExited", "Disk discovery failed. See the details below.": "statusDiscoveryFailed",
    "Unable to check the Python service status.": "statusUnableCheck", "Reading physical disks requires elevated permission.": "statusElevated",
    "Disk access permission was granted.": "statusPermissionGranted", "The application is restarting with elevated permissions.": "statusRestarting",
    "The scan was canceled because disk access permission was not granted.": "statusCanceledPermission", "Unable to request elevated disk access.": "statusUnableRequest",
    "Search this disk for NTFS partitions.": "statusSearchDisk", "Choose a source disk.": "statusChooseDisk", "Resuming lost-partition scan…": "statusResumeScan",
    "Searching for lost NTFS partitions…": "statusSearchingLost", "Scanning partitions…": "statusScanning", "No readable NTFS partitions were found.": "statusNoPartitions",
    "Partition search failed. The scan position has been saved when available.": "statusScanFailed", "Build the catalog to browse the discovered files.": "statusBuildBrowse",
    "Select an NTFS partition.": "statusSelectPartition", "Reading metadata and building the catalog…": "statusReadingCatalog",
    "Unable to build the catalog.": "statusUnableCatalog", "Recovering the selected items…": "statusRecovering", "Recovery failed.": "statusRecoveryFailed",
    "The previous source disk was restored. Search it for NTFS partitions.": "statusPreviousDisk",
  };
  const key = lookup[status];
  if (key) return translate(language, key);
  const catalogReady = status.match(/^Catalog ready: ([\d,]+) MFT records\.$/);
  if (catalogReady) return language === "pt-BR" ? `Catálogo pronto: ${catalogReady[1]} registros MFT.` : language === "es-ES" ? `Catálogo listo: ${catalogReady[1]} registros MFT.` : language === "fr-FR" ? `Catalogue prêt : ${catalogReady[1]} enregistrements MFT.` : language === "zh-CN" ? `目录已就绪：${catalogReady[1]} 条 MFT 记录。` : status;
  let match = status.match(/^(\d+) disk\(s\) found\. Choose a source disk\.$/);
  if (match) return language === "pt-BR" ? `${match[1]} disco(s) encontrado(s). Escolha um disco de origem.` : language === "es-ES" ? `${match[1]} disco(s) encontrado(s). Elige un disco de origen.` : language === "fr-FR" ? `${match[1]} disque(s) trouvé(s). Choisissez un disque source.` : language === "zh-CN" ? `找到 ${match[1]} 个磁盘。选择源磁盘。` : `${match[1]} disk(s) found. Choose a source disk.`;
  match = status.match(/^Completed: (\d+)\/(\d+) files recovered\.$/);
  if (match) return language === "pt-BR" ? `Concluído: ${match[1]}/${match[2]} arquivos recuperados.` : language === "es-ES" ? `Completado: ${match[1]}/${match[2]} archivos recuperados.` : language === "fr-FR" ? `Terminé : ${match[1]}/${match[2]} fichiers récupérés.` : language === "zh-CN" ? `已完成：恢复 ${match[1]}/${match[2]} 个文件。` : status;
  match = status.match(/^(\d+) NTFS partition\(s\) found\. Select one to build the catalog\.$/);
  if (match) return language === "pt-BR" ? `${match[1]} partição(ões) NTFS encontrada(s). Selecione uma para montar o catálogo.` : language === "es-ES" ? `Se encontraron ${match[1]} partición(es) NTFS. Selecciona una para crear el catálogo.` : language === "fr-FR" ? `${match[1]} partition(s) NTFS trouvée(s). Sélectionnez-en une pour créer le catalogue.` : language === "zh-CN" ? `找到 ${match[1]} 个 NTFS 分区。选择一个以创建目录。` : status;
  match = status.match(/^(\d+) saved deep-scan candidate\(s\) (restored|loaded)( \([^)]*\))?\. (.*)$/);
  if (match) {
    const count = match[1], date = match[3] ?? "";
    if (language === "pt-BR") return `${count} candidato(s) de busca profunda ${match[2] === "restored" ? "restaurado(s)" : "carregado(s)"}${date}. Selecione uma partição para continuar.`;
    if (language === "es-ES") return `${count} candidato(s) de búsqueda profunda ${match[2] === "restored" ? "restaurado(s)" : "cargado(s)"}${date}. Selecciona una partición para continuar.`;
    if (language === "fr-FR") return `${count} candidat(s) d’analyse approfondie ${match[2] === "restored" ? "restauré(s)" : "chargé(s)"}${date}. Sélectionnez une partition pour continuer.`;
    if (language === "zh-CN") return `已${match[2] === "restored" ? "恢复" : "加载"} ${count} 个深度扫描候选项${date}。选择分区以继续。`;
  }
  match = status.match(/^(Checking|Checked) partition (\d+)$/);
  if (match && language !== "en-US") {
    const action = match[1] === "Checking";
    return language === "pt-BR" ? `${action ? "Verificando" : "Verificada"} partição ${match[2]}` : language === "es-ES" ? `${action ? "Comprobando" : "Comprobada"} partición ${match[2]}` : language === "fr-FR" ? `${action ? "Vérification de la" : "Vérifiée :"} partition ${match[2]}` : `${action ? "正在检查" : "已检查"}分区 ${match[2]}`;
  }
  match = status.match(/^Reading MFT records$/);
  if (match && language !== "en-US") return language === "pt-BR" ? "Lendo registros MFT" : language === "es-ES" ? "Leyendo registros MFT" : language === "fr-FR" ? "Lecture des enregistrements MFT" : "正在读取 MFT 记录";
  match = status.match(/^(.+) \| ([\d,]+)\/([\d,]+) bytes$/);
  if (match && language !== "en-US") return `${match[1]} | ${match[2]}/${match[3]} ${language === "zh-CN" ? "字节" : "octets"}`;
  return status;
}

export function translateError(error: string, language: SiteLanguage) {
  const lookup: Record<string, TranslationKey> = {
    "Authorize the system permission request to read physical disks.": "errorAuthorize",
    "Choose a destination folder to continue.": "destinationRequired",
    "Select files and at least one file type.": "selectionRequired",
  };
  const key = lookup[error];
  return key ? translate(language, key) : error;
}
