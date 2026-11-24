import React from "react";
import { Button, Card } from "belagio-styles-lib";
import { Link } from "react-router-dom";
import { translate } from "../../i18n/translations";
import { useAppLanguage } from "../../app/language";
import { SimplePage, PageActions } from "../../app/layoutStyle";

export const HomePage: React.FC = () => {
  const { language } = useAppLanguage();
  const t = (key: Parameters<typeof translate>[1]) => translate(language, key);
  return <SimplePage>
    <Card size="sm" variant="flat">
      <h1>{t("welcomeTitle")}</h1>
      <p>{t("welcomeBody")}</p>
      <PageActions>
        <Link to="/storage"><Button className="brand-button--primary" variant="primary" size="md">{t("startPhysical")}</Button></Link>
        <Link to="/storage?source=image"><Button className="brand-button--ghost" variant="ghost" size="md">{t("startImage")}</Button></Link>
      </PageActions>
    </Card>
  </SimplePage>;
};
