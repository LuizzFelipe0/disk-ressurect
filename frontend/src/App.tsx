import React from "react";
import { createHashRouter, Navigate, RouterProvider } from "react-router-dom";
import { GlobalStyle } from "./globalStyles";
import { HomePage } from "./pages/HomePage";

const App: React.FC = () => {
  const router = React.useMemo(() => createHashRouter([
    { path: "/", element: <HomePage /> },
    { path: "/recovery", lazy: async () => {
      const { RecoveryPage } = await import("./pages/RecoveryPage");
      return { Component: RecoveryPage };
    } },
    { path: "*", element: <Navigate to="/" replace /> },
  ]), []);

  return <>
    <GlobalStyle />
    <RouterProvider router={router} />
  </>;
};

export default App;
