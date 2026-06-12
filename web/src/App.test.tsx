import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

describe("App", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        json: async () => [],
      })),
    );
  });

  it("renders the local match creation workflow", async () => {
    render(<App />);

    expect(screen.getByText("创建规则验证对局")).toBeInTheDocument();
    expect(screen.getByText("examples/decks/sample-deck.json")).toBeInTheDocument();
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/matches", expect.anything()));
  });
});
