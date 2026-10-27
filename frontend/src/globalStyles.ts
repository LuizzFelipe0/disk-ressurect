import { createGlobalStyle } from "styled-components";

export const GlobalStyle = createGlobalStyle`
  :root { color: #18243a; background: #f2f5fb; font-synthesis: none; }
  * { box-sizing: border-box; }
  html, body, #root { min-width: 800px; min-height: 100%; margin: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
  button, input, select { font: inherit; }
  button, select, input[type="checkbox"] { cursor: pointer; }
  button:disabled, select:disabled, input:disabled { cursor: not-allowed; }
  ::selection { color: #fff; background: #2879d5; }
`;
