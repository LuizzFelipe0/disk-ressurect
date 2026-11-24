import React, { createContext, useContext, useMemo, useState } from "react";
import type { SiteLanguage } from "belagio-styles-lib";

const STORAGE_KEY = "disk-ressurect:language";
const LanguageContext = createContext<{
  language: SiteLanguage;
  setLanguage: (language: SiteLanguage) => void;
}>({
  language: "pt-BR",
  setLanguage: () => undefined,
});

export const LanguageProvider: React.FC<React.PropsWithChildren> = ({ children }) => {
  const [language, setLanguageValue] = useState<SiteLanguage>(() => {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    return saved === "en-US" || saved === "es-ES" || saved === "fr-FR" || saved === "zh-CN"
      ? saved : "pt-BR";
  });
  const setLanguage = (next: SiteLanguage) => {
    setLanguageValue(next);
    window.localStorage.setItem(STORAGE_KEY, next);
  };
  const value = useMemo(() => ({ language, setLanguage }), [language]);
  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
};

export const useAppLanguage = () => useContext(LanguageContext);
