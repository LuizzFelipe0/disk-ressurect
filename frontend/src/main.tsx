import React from "react";
import { createRoot } from "react-dom/client";
import { injectGlobalStyles } from "belagio-styles-lib";
import App from "./App";

injectGlobalStyles();

createRoot(document.getElementById("root")!).render(
  <React.StrictMode><App /></React.StrictMode>,
);
