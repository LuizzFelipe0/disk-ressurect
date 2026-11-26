// @vitest-environment jsdom
import React, { useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { useRecoveryNavigationGuard } from "./useRecoveryNavigationGuard";

const ActiveOperation = () => {
  const [busy, setBusy] = useState(true);
  useRecoveryNavigationGuard(busy);
  return <button onClick={() => setBusy(false)}>Finish operation</button>;
};

describe("useRecoveryNavigationGuard", () => {
  it("blocks route changes while busy and allows navigation after completion", async () => {
    const router = createMemoryRouter([
      { path: "/operation", element: <ActiveOperation /> },
      { path: "/home", element: <h1>Home</h1> },
    ], { initialEntries: ["/operation"] });
    render(<RouterProvider router={router} />);

    await router.navigate("/home");
    await waitFor(() => expect(router.state.location.pathname).toBe("/operation"));
    expect(screen.getByRole("button", { name: "Finish operation" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Finish operation" }));
    await router.navigate("/home");
    await waitFor(() => expect(router.state.location.pathname).toBe("/home"));
    expect(screen.getByRole("heading", { name: "Home" })).toBeTruthy();
  });

  it("prevents a window close while busy and unregisters the listener after unmount", () => {
    const router = createMemoryRouter([
      { path: "/operation", element: <ActiveOperation /> },
    ], { initialEntries: ["/operation"] });
    const page = render(<RouterProvider router={router} />);
    const closing = new Event("beforeunload", { cancelable: true });
    expect(window.dispatchEvent(closing)).toBe(false);

    page.unmount();
    const laterClosing = new Event("beforeunload", { cancelable: true });
    expect(window.dispatchEvent(laterClosing)).toBe(true);
  });
});
