import { createGlobalStyle } from "styled-components";
import { brandColors } from "./brandColors";

export const GlobalStyle = createGlobalStyle`
  :root {
    color: ${brandColors.ink};
    background: ${brandColors.bone};
    color-scheme: light;
    font-synthesis: none;
    --disk-ink: ${brandColors.ink};
    --disk-bone: ${brandColors.bone};
    --disk-revive: ${brandColors.revive};
    --disk-surface: ${brandColors.surface};
    --disk-border: ${brandColors.border};
    --disk-text-secondary: ${brandColors.textSecondary};
    --disk-text-tertiary: ${brandColors.textTertiary};
    --belagio-color-primary: ${brandColors.ink};
    --belagio-color-success: ${brandColors.revive};
    --belagio-color-error: ${brandColors.error};
    --belagio-color-warning: #B7791F;
    --belagio-color-surface: ${brandColors.surface};
    --belagio-color-border: ${brandColors.border};
    --belagio-color-text: ${brandColors.ink};
    --belagio-color-info-surface: ${brandColors.infoSurface};
    --belagio-color-success-surface: #EEF9D9;
    --belagio-color-success-text: #486B13;
    --belagio-color-warning-surface: ${brandColors.warningSurface};
    --belagio-color-warning-text: ${brandColors.warning};
    --belagio-color-error-surface: ${brandColors.errorSurface};
    --belagio-color-error-text: ${brandColors.error};
    --belagio-progress-track: ${brandColors.border};
    --belagio-progress-fill: ${brandColors.revive};
  }
  * { box-sizing: border-box; }
  html, body, #root {
    min-width: 320px;
    min-height: 100%;
    margin: 0;
    color: ${brandColors.ink};
    background-color: ${brandColors.bone};
  }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
  button, input, select { font: inherit; }
  button, select, input[type="checkbox"] { cursor: pointer; }
  button:disabled, select:disabled, input:disabled { cursor: not-allowed; }
  ::selection { color: ${brandColors.ink}; background: ${brandColors.revive}; }

  #root button.brand-button--primary,
  #root button.brand-button--success {
    color: ${brandColors.ink} !important;
    background-color: ${brandColors.revive} !important;
    border-color: ${brandColors.revive} !important;
  }
  #root button.brand-button--ghost {
    color: ${brandColors.ink} !important;
    background-color: transparent !important;
    border-color: ${brandColors.border} !important;
  }
  #root button[aria-expanded] {
    color: ${brandColors.ink} !important;
    background-color: ${brandColors.surface} !important;
    border-color: ${brandColors.border} !important;
  }
  #recovery-page-content > div[style],
  #recovery-page-content > div > div[style] {
    background-color: ${brandColors.surface} !important;
    border-color: ${brandColors.border} !important;
  }
  #recovery-page-content > div[style]:focus,
  #recovery-page-content > div[style]:focus-within,
  #recovery-page-content > div > div[style]:focus,
  #recovery-page-content > div > div[style]:focus-within {
    outline: none !important;
    outline-offset: 0 !important;
  }
  #root input:not([type="checkbox"]), #root select {
    color: ${brandColors.ink} !important;
    background-color: ${brandColors.surface} !important;
    border-color: ${brandColors.border} !important;
  }
  #root input::placeholder { color: ${brandColors.textTertiary} !important; }
  #root input:focus, #root select:focus, #root button[aria-expanded]:focus-visible {
    border-color: ${brandColors.revive} !important;
    outline-color: ${brandColors.revive} !important;
    box-shadow: 0 0 0 3px rgba(182, 242, 60, .24) !important;
  }
  #root input[type="checkbox"] { accent-color: ${brandColors.revive} !important; }
  #root header, #root footer { border-color: ${brandColors.border} !important; color: ${brandColors.ink}; }
`;
