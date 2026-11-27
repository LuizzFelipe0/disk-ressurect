import React from "react";
import { Card, InfoButton } from "belagio-styles-lib";
import { WorkflowFooter, WorkflowHeader } from "../../components/WorkflowChrome";
import { WorkflowSteps } from "../../components/WorkflowSteps";
import { useLanguagePreference } from "../../hooks/useLanguagePreference";
import { translate } from "../../i18n/translations";
import {
  HomeContent, HomeLayout, SourceCard, SourceGrid, SourceIcon,
  SourceOption, SourceInfo, SourceTitle, WelcomeBody, WelcomeTitle, ReadOnlyNotice,
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
        <WelcomeTitle>{t("welcomeTitle")}</WelcomeTitle>
        <WelcomeBody>{t("welcomeBody")}</WelcomeBody>
        <SourceGrid>
          <SourceOption>
            <SourceCard to="/recovery" aria-label={t("startPhysical")}>
              <SourceIcon aria-hidden="true">▣</SourceIcon>
              <SourceTitle>{t("startPhysical")}</SourceTitle>
              <span>{t("continue")} →</span>
            </SourceCard>
            <SourceInfo><InfoButton description={t("physicalSourceDescription")} label={t("moreInfo")} /></SourceInfo>
          </SourceOption>
        </SourceGrid>
        <ReadOnlyNotice role="note"><span aria-hidden="true">♧</span> {t("sourceReadOnlyNotice")}</ReadOnlyNotice>
      </Card>
    </HomeContent>
    <WorkflowFooter language={language} />
  </HomeLayout>;
};
