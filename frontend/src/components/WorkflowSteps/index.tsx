import React from "react";
import { useNavigate } from "react-router-dom";
import { StepsNavigation, StepButton, StepNumber, StepConnector } from "./style";

export type WorkflowStep = 0 | 1 | 2 | 3 | 4;

interface WorkflowStepsProps {
  activeStep: WorkflowStep;
  highestAvailableStep: WorkflowStep;
  labels: [string, string, string, string, string];
  ariaLabel: string;
  disabled?: boolean;
  onStepChange: (step: WorkflowStep) => void;
}

export const WorkflowSteps: React.FC<WorkflowStepsProps> = ({
  activeStep, highestAvailableStep, labels, ariaLabel, disabled = false, onStepChange,
}) => {
  const navigate = useNavigate();

  return <StepsNavigation aria-label={ariaLabel}>
    {labels.map((label, index) => {
      const step = index as WorkflowStep;
      const isCurrent = step === activeStep;
      const isComplete = step < activeStep;
      const isAvailable = step === 0 || step <= highestAvailableStep;
      return <React.Fragment key={label}>
        {index > 0 && <StepConnector aria-hidden="true" />}
        <StepButton
          type="button"
          $active={isCurrent}
          $complete={isComplete}
          disabled={disabled || !isAvailable}
          aria-current={isCurrent ? "step" : undefined}
          onClick={() => step === 0 ? navigate("/") : onStepChange(step)}
        >
          <StepNumber $active={isCurrent} $complete={isComplete}>{isComplete ? "✓" : index + 1}</StepNumber>
          <span>{label}</span>
        </StepButton>
      </React.Fragment>;
    })}
  </StepsNavigation>;
};
