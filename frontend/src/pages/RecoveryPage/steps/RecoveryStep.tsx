import React from "react";
import { Button, Card, FormField, InfoButton, Input } from "belagio-styles-lib";
import type { RecoveryStepProps } from "./types";
import { DestinationInput, DestinationRow, Eyebrow, PageIntro, StepActions } from "../style";

interface RecoveryStageProps extends RecoveryStepProps {
  onBack: () => void;
}

export const RecoveryStep: React.FC<RecoveryStageProps> = ({ recovery, t, onBack }) => <>
  <PageIntro><Eyebrow>{t("recoveryStep")}</Eyebrow><h1>{t("recoverSelected")}</h1>
    <p>{t("chooseDestinationDescription")}</p></PageIntro>
  <Card size="sm" variant="flat">
    <div><strong>{t("selectedItems")}: {recovery.selectedIds.size}</strong></div>
    <DestinationRow>
      <DestinationInput><FormField label={t("saveFiles")}><Input type="text" aria-label={t("saveFiles")}
        value={recovery.outputDirectory} disabled={recovery.busy} placeholder={t("chooseFolderPlaceholder")}
        onChange={recovery.setOutputDirectory} /></FormField></DestinationInput>
      <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy}
        onClick={() => void recovery.chooseOutputDirectory()}>{t("chooseFolder")}</Button>
      <InfoButton description={t("physicalDestinationNotice")} label={t("moreInfo")} />
    </DestinationRow>
  </Card>
  <StepActions>
    <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy}
      onClick={onBack}>← {t("back")}</Button>
    <Button className="brand-button--success" variant="success" size="md"
      disabled={recovery.busy || !recovery.outputDirectory.trim() || !recovery.extensions.length}
      onClick={() => void recovery.recover()}>{recovery.busy ? t("recovering") : t("recoverSelected")}</Button>
  </StepActions>
</>;
