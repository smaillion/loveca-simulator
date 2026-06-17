// @vitest-environment jsdom

import { beforeEach, describe, expect, it, vi } from "vitest";
import { listPreviewCatalogFacets } from "./browser-preview-api";

describe("browser preview API", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("reports a clear error when preview data resolves to HTML", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response("<!doctype html>", {
          headers: { "Content-Type": "text/html" },
          status: 200,
        }),
      ),
    );

    await expect(listPreviewCatalogFacets()).rejects.toThrow(
      "Expected JSON from preview-data/facets.json",
    );
  });
});
