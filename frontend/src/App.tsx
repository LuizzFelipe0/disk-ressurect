import React from "react";
import { HashRouter, Navigate, Route, Routes } from "react-router-dom";
import { GlobalStyle } from "./globalStyles";
import { useRecoveryController } from "./hooks/useRecoveryController";
import { RecoverySessionProvider, useCatalogSession, useStorageSession } from "./app/recoverySession";
import { AppLayout } from "./app/AppLayout";
import { LanguageProvider } from "./app/language";
import { HomePage } from "./pages/storage/HomePage";
import { StoragePage } from "./pages/storage/StoragePage";
import { ScanPage } from "./pages/scan/ScanPage";
import { CatalogPage } from "./pages/catalog/CatalogPage";
import { RecoveryPage } from "./pages/recovery/RecoveryPage";

const ScanRoute: React.FC = () => {
  const storage = useStorageSession();
  return storage.selectedVolumeId ? <ScanPage /> : <Navigate to="/storage" replace />;
};

const CatalogRoute: React.FC = () => {
  const catalog = useCatalogSession();
  return catalog.catalog ? <CatalogPage /> : <Navigate to="/scan" replace />;
};

const RecoveryRoutes: React.FC = () => <Routes>
  <Route element={<AppLayout />}>
    <Route index element={<HomePage />} />
    <Route path="storage" element={<StoragePage />} />
    <Route path="scan" element={<ScanRoute />} />
    <Route path="catalog" element={<CatalogRoute />} />
    <Route path="recovery" element={<RecoveryPage />} />
    <Route path="*" element={<Navigate to="/" replace />} />
  </Route>
</Routes>;

const RecoveryApplication: React.FC = () => {
  const recovery = useRecoveryController();
  return <RecoverySessionProvider value={recovery}><HashRouter><RecoveryRoutes /></HashRouter></RecoverySessionProvider>;
};

const App: React.FC = () => <><GlobalStyle /><LanguageProvider><RecoveryApplication /></LanguageProvider></>;

export default App;
