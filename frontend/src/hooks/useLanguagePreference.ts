import { useCallback, useState } from "react";
import type { SiteLanguage } from "belagio-styles-lib";

const LANGUAGE_KEY = "disk-ressurect:language";

function readLanguage(): SiteLanguage {
  const saved = window.localStorage.getItem(LANGUAGE_KEY);
  return saved === "en-US" || saved === "es-ES" || saved === "fr-FR" || saved === "zh-CN"
    ? saved : "pt-BR";
}

export function useLanguagePreference() {
  const [language, setLanguage] = useState<SiteLanguage>(readLanguage);
  const changeLanguage = useCallback((next: SiteLanguage) => {
    setLanguage(next);
    window.localStorage.setItem(LANGUAGE_KEY, next);
  }, []);
  return { language, changeLanguage };
}
