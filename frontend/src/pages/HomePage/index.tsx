import React from "react";
import { Button, Card, Footer as BelagioFooter, Header, LanguageToggle, type SiteLanguage } from "belagio-styles-lib";
import { Link } from "react-router-dom";
import logo from "../../assets/disk-ressurect-logo.png";
import { translate } from "../../i18n/translations";
import { HomeContent, HomeEyebrow, HomeLayout, WelcomeBody, WelcomeTitle } from "./style";

const LANGUAGE_KEY = "disk-ressurect:language";

function readLanguage(): SiteLanguage {
  const saved = window.localStorage.getItem(LANGUAGE_KEY);
  return saved === "en-US" || saved === "es-ES" || saved === "fr-FR" || saved === "zh-CN"
    ? saved : "pt-BR";
}

export const HomePage: React.FC = () => {
  const [language, setLanguage] = React.useState<SiteLanguage>(readLanguage);
  const t = (key: Parameters<typeof translate>[1]) => translate(language, key);

  return <HomeLayout>
    <Header icon={logo} title="Disk-Ressurect" actions={
      <LanguageToggle value={language} size="sm" onChange={(next) => {
        setLanguage(next);
        window.localStorage.setItem(LANGUAGE_KEY, next);
      }} aria-label="Idioma / Language / Idioma / Langue / 语言" />
    } />
    <HomeContent>
      <Card size="sm" variant="flat">
        <HomeEyebrow>DISK-RESSURECT</HomeEyebrow>
        <WelcomeTitle>{t("welcomeTitle")}</WelcomeTitle>
        <WelcomeBody>{t("welcomeBody")}</WelcomeBody>
        <Link to="/recovery">
          <Button className="brand-button--primary" variant="primary" size="md">{t("startRecovery")}</Button>
        </Link>
        <Link to="/recovery?source=image">
          <Button className="brand-button--ghost" variant="ghost" size="md">{t("startImage")}</Button>
        </Link>
      </Card>
    </HomeContent>
    <BelagioFooter left={["Disk-Ressurect", t("version")]} center={[t("footerTitle")]} right={[t("desktopApp")]} />
  </HomeLayout>;
};
