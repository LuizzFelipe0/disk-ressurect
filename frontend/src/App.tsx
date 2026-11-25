import React from "react";
import { HashRouter, Navigate, Route, Routes } from "react-router-dom";
import { GlobalStyle } from "./globalStyles";
import { HomePage } from "./pages/HomePage";
import { RecoveryPage } from "./pages/RecoveryPage";

const App: React.FC = () => <>
  <GlobalStyle />
  <HashRouter>
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/recovery" element={<RecoveryPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  </HashRouter>
</>;

export default App;
