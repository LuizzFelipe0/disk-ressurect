import React from "react";
import { NavLink, Outlet } from "react-router-dom";
import { Footer, Header, LanguageToggle } from "belagio-styles-lib";
import logo from "../assets/disk-ressurect-logo.png";
import { RecoveryStatusPanel } from "../components/RecoveryStatusPanel";
import { translate, translateError, translateStatus } from "../i18n/translations";
import { useAppLanguage } from "./language";
import { useRecoveryActivity, useRecoveryOperation, useStorageSession } from "./recoverySession";
import { LayoutRoot, LayoutHeader, LayoutMain, LayoutNavigation } from "./layoutStyle";

export const AppLayout: React.FC = () => {
  const { language, setLanguage } = useAppLanguage();
  const operation = useRecoveryOperation();
  const activity = useRecoveryActivity();
  const storage = useStorageSession();
  const t = (key: Parameters<typeof translate>[1]) => translate(language, key);
  return <LayoutRoot>
    <LayoutHeader>
      <Header icon={logo} title="Disk-Ressurect" actions={
        <LanguageToggle value={language} size="sm" onChange={setLanguage}
          aria-label="Idioma / Language / Idioma / Langue / 语言" />
      } />
      <LayoutNavigation aria-label={t("stepsNavigation")}>
        <NavLink to="/">{t("home")}</NavLink>
        <NavLink to="/storage">{t("storageStep")}</NavLink>
        <NavLink to="/scan">{t("scanStep")}</NavLink>
        <NavLink to="/catalog">{t("catalogStep")}</NavLink>
        <NavLink to="/recovery">{t("recoveryStep")}</NavLink>
      </LayoutNavigation>
    </LayoutHeader>
    <LayoutMain><Outlet /></LayoutMain>
    <RecoveryStatusPanel
      status={translateStatus(activity.status, language)} progress={activity.progress}
      error={translateError(operation.error, language)} busy={operation.busy}
      isAdministrator={operation.isAdministrator}
      partitionScanCanResume={operation.partitionScanCanResume}
      selectedDiskNumber={storage.selectedDiskNumber} backendStatus={operation.backendStatus}
      onRetryScan={() => void storage.findPartitions(true, true)}
      onRequestDiskAccess={() => void operation.ensureAdministrator()} language={language}
    />
    <Footer left={["Disk-Ressurect", t("version")]} center={[t("footerTitle")]} right={[t("desktopApp")]} />
  </LayoutRoot>;
};
