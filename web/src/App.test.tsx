import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App, { availableValue, resolveMemberPlaySelection } from "./App";

const placements = [
  {
    card_instance_id: "member-a",
    slot: "center",
    payment_cost: 4,
    use_baton_touch: false,
    replaced_card_instance_id: "old-center",
    replaced_member_cost: 2,
  },
  {
    card_instance_id: "member-a",
    slot: "center",
    payment_cost: 2,
    use_baton_touch: true,
    replaced_card_instance_id: "old-center",
    replaced_member_cost: 2,
  },
  {
    card_instance_id: "member-a",
    slot: "left",
    payment_cost: 4,
    use_baton_touch: false,
    replaced_card_instance_id: null,
    replaced_member_cost: 0,
  },
  {
    card_instance_id: "member-b",
    slot: "right",
    payment_cost: 1,
    use_baton_touch: false,
    replaced_card_instance_id: null,
    replaced_member_cost: 0,
  },
];

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

  it("falls back when the previously selected Member card or area is no longer legal", () => {
    expect(availableValue("center", ["left", "right"])).toBe("left");
    expect(availableValue("member-old", ["member-new"])).toBe("member-new");
    expect(availableValue("right", ["left", "right"])).toBe("right");
  });

  it("deduplicates Member instances and prefers center, then Baton Touch", () => {
    const selection = resolveMemberPlaySelection(placements, "", "", "");

    expect(selection.memberIds).toEqual(["member-a", "member-b"]);
    expect(selection.selectedMemberId).toBe("member-a");
    expect(selection.selectedSlot).toBe("center");
    expect(selection.selectedMode).toBe("baton");
    expect(selection.placement?.payment_cost).toBe(2);
  });

  it("falls back to the next legal area when center is unavailable", () => {
    const selection = resolveMemberPlaySelection(
      placements.filter((item) => item.slot !== "center"),
      "member-a",
      "center",
      "baton",
    );

    expect(selection.selectedSlot).toBe("left");
    expect(selection.selectedMode).toBe("normal");
  });

  it("automatically uses normal play when Baton Touch is unavailable", () => {
    const selection = resolveMemberPlaySelection(
      placements.filter((item) => !item.use_baton_touch),
      "member-a",
      "center",
      "baton",
    );

    expect(selection.availableModes).toEqual(["normal"]);
    expect(selection.selectedMode).toBe("normal");
  });

  it("drops stale Member, area, and mode selections after legal actions change", () => {
    const selection = resolveMemberPlaySelection(
      placements.filter((item) => item.card_instance_id === "member-b"),
      "member-a",
      "center",
      "baton",
    );

    expect(selection.selectedMemberId).toBe("member-b");
    expect(selection.selectedSlot).toBe("right");
    expect(selection.selectedMode).toBe("normal");
  });
});
