import styled from "styled-components";
import { spacing, typography } from "belagio-styles-lib";
import { brandColors } from "../../brandColors";

export const Notice = styled.div<{ $spaced: boolean; $tone: "error" | "warning" | "info" }>`
  display: grid;
  gap: ${spacing[1]};
  margin-top: ${({ $spaced }) => $spaced ? "10px" : "0"};
  padding: ${spacing[3]} ${spacing[4]};
  border: 1px solid ${({ $tone }) => $tone === "error" ? brandColors.error : $tone === "warning" ? brandColors.warning : brandColors.revive};
  border-radius: ${spacing.radiusLg};
  background: ${({ $tone }) => $tone === "error" ? brandColors.errorSurface : $tone === "warning" ? brandColors.warningSurface : brandColors.infoSurface};
  color: ${({ $tone }) => $tone === "error" ? brandColors.error : $tone === "warning" ? brandColors.warning : brandColors.ink};
  font-family: ${typography.fontFamily};
  font-size: ${typography.sizeSm};
  line-height: ${typography.lineHeightNormal};
  overflow-wrap: anywhere;
  strong { font-weight: ${typography.weightBold}; }
`;
