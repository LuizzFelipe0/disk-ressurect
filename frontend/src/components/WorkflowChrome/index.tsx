import React from "react";
import { Footer, Header, LanguageToggle, type SiteLanguage } from "belagio-styles-lib";
import logo from "../../assets/disk-ressurect-logo.png";
import { translate } from "../../i18n/translations";
import { HeaderActions, PageHeader } from "./style";

interface WorkflowHeaderProps {
  language: SiteLanguage;
  onLanguageChange: (language: SiteLanguage) => void;
  children?: React.ReactNode;
}

export const WorkflowHeader: React.FC<WorkflowHeaderProps> = ({ language, onLanguageChange, children }) => (
  <PageHeader>
    <Header icon={logo} title="Disk-Ressurect" actions={<HeaderActions>
      {children}
      <LanguageToggle value={language} size="sm" onChange={onLanguageChange}
        aria-label="Idioma / Language / Idioma / Langue / 语言" />
    </HeaderActions>} />
  </PageHeader>
);

export const WorkflowFooter: React.FC<{ language: SiteLanguage }> = ({ language }) => (
  <Footer left={["Disk-Ressurect", translate(language, "version")]}
    center={[translate(language, "footerTitle")]} right={[translate(language, "desktopApp")]} />
);
