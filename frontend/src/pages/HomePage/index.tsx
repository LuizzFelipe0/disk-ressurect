import React from "react";
import { Card } from "belagio-styles-lib";
import { WorkflowFooter, WorkflowHeader } from "../../components/WorkflowChrome";
import { WorkflowSteps } from "../../components/WorkflowSteps";
import { useLanguagePreference } from "../../hooks/useLanguagePreference";
import { translate } from "../../i18n/translations";
import {
  HomeContent, HomeEyebrow, HomeLayout, SourceCard, SourceGrid, SourceIcon,
  SourceDescription, SourceTitle, WelcomeBody, WelcomeTitle, ReadOnlyNotice,
} from "./style";

export const HomePage: React.FC = () => {
  const { language, changeLanguage } = useLanguagePreference();
  const t = (key: Parameters<typeof translate>[1]) => translate(language, key);

  return <HomeLayout>
    <WorkflowHeader language={language} onLanguageChange={changeLanguage} />
    <HomeContent>
      <WorkflowSteps activeStep={0} highestAvailableStep={0}
        labels={[t("home"), t("storageStep"), t("scanStep"), t("catalogStep"), t("recoveryStep")]}
        ariaLabel={t("stepsNavigation")} onStepChange={() => undefined} />
      <Card size="sm" variant="flat">
        <HomeEyebrow>DISK-RESSURECT</HomeEyebrow>
        <WelcomeTitle>{t("welcomeTitle")}</WelcomeTitle>
        <WelcomeBody>{t("welcomeBody")}</WelcomeBody>
        <SourceGrid>
          <SourceCard to="/recovery?source=physical" aria-label={t("startPhysical")}>
              <SourceIcon aria-hidden="true">▣</SourceIcon>
              <SourceTitle>{t("startPhysical")}</SourceTitle>
              <SourceDescription>{t("physicalSourceDescription")}</SourceDescription>
              <span>{t("continue")} →</span>
          </SourceCard>
          <SourceCard to="/recovery?source=image" aria-label={t("startImage")}>
              <SourceIcon aria-hidden="true">▤</SourceIcon>
              <SourceTitle>{t("startImage")}</SourceTitle>
              <SourceDescription>{t("imageSourceDescription")}</SourceDescription>
              <span>{t("continue")} →</span>
          </SourceCard>
        </SourceGrid>
        <ReadOnlyNotice role="note"><span aria-hidden="true">♧</span> {t("sourceReadOnlyNotice")}</ReadOnlyNotice>
      </Card>
    </HomeContent>
    <WorkflowFooter language={language} />
  </HomeLayout>;
};
