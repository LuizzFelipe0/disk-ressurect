import { useEffect } from "react";
import { useBlocker } from "react-router-dom";

export function useRecoveryNavigationGuard(busy: boolean) {
  const { state, reset } = useBlocker(({ currentLocation, nextLocation }) =>
    busy && (currentLocation.pathname !== nextLocation.pathname
      || currentLocation.search !== nextLocation.search
      || currentLocation.hash !== nextLocation.hash));

  useEffect(() => {
    if (state === "blocked") reset();
  }, [state, reset]);

  useEffect(() => {
    if (!busy) return undefined;
    const preventWindowClose = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", preventWindowClose);
    return () => window.removeEventListener("beforeunload", preventWindowClose);
  }, [busy]);
}
