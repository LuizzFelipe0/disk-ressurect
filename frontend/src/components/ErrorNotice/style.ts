import styled from "styled-components";
import { colors, spacing, typography } from "belagio-styles-lib";

export const Notice = styled.div<{ $spaced: boolean; $tone: "error" | "warning" | "info" }>`
  display: grid;
  gap: ${spacing[1]};
  margin-top: ${({ $spaced }) => $spaced ? "10px" : "0"};
  padding: ${spacing[3]} ${spacing[4]};
  border: 1px solid ${({ $tone }) => $tone === "error" ? colors.red.trim() : $tone === "warning" ? colors.orange : colors.blue};
  border-radius: ${spacing.radiusLg};
  background: ${({ $tone }) => $tone === "error" ? "#fff2f3" : $tone === "warning" ? "#fff8eb" : "#f1f5ff"};
  color: ${({ $tone }) => $tone === "error" ? colors.red.trim() : $tone === "warning" ? "#805200" : colors.blue};
  font-family: ${typography.fontFamily};
  font-size: ${typography.sizeSm};
  line-height: ${typography.lineHeightNormal};
  overflow-wrap: anywhere;
  strong { font-weight: ${typography.weightBold}; }
`;
