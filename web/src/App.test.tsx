import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App, {
  StageAttachments,
  availableValue,
  canResolveEffect,
  formatEffectText,
  formatHeartSummary,
  resolveMemberPlaySelection,
} from "./App";

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
    cleanup();
    localStorage.clear();
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
    expect(screen.getByPlaceholderText("自动生成")).toHaveValue("");
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/matches", expect.anything()));
  });

  it("switches the operational UI to Japanese and persists the choice", async () => {
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: "日本語" }));

    expect(screen.getByText("ルール検証対戦を作成")).toBeInTheDocument();
    expect(localStorage.getItem("loveca-ui-locale")).toBe("ja");
  });

  it("renders Heart slots and effect tokens as localized color names", () => {
    expect(
      formatHeartSummary({ heart01: 2, heart04: 1, heart05: 3 }, "zh"),
    ).toBe("粉色 2 / 绿色 1 / 蓝色 3");
    expect(formatHeartSummary({ heart0: 1, heart06: 2 }, "ja")).toBe(
      "任意色 1 / 紫 2",
    );
    expect(formatEffectText("heart01を2つ、heart05を1つ得る。", "ja")).toBe(
      "ピンクを2つ、青を1つ得る。",
    );
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

  it("requires effect card and Energy selections before resolution", () => {
    expect(canResolveEffect(1, 0, 0, 0)).toBe(false);
    expect(canResolveEffect(1, 1, 1, 0)).toBe(false);
    expect(canResolveEffect(1, 1, 1, 1)).toBe(true);
    expect(canResolveEffect(0, 0, 0, 0)).toBe(true);
  });

  it("shows attached Member and Energy cards under a Stage Member", () => {
    const onCard = vi.fn();
    const state = {
      cards: {
        "attached-member": {
          instance_id: "attached-member",
          owner_id: "player_1",
          orientation: "wait",
          face_up: true,
          card: {
            card_id: "member-printing",
            card_code: "member-code",
            card_type: "member",
            name_ja: "下のメンバー",
          },
        },
        "attached-energy": {
          instance_id: "attached-energy",
          owner_id: "player_1",
          orientation: "active",
          face_up: true,
          card: {
            card_id: "energy-printing",
            card_code: "energy-code",
            card_type: "energy",
            name_ja: "エネルギー",
          },
        },
      },
    };

    render(
      <StageAttachments
        ids={["attached-member", "attached-energy"]}
        state={state as never}
        onCard={onCard}
      />,
    );

    expect(screen.getByText("下方 2")).toBeInTheDocument();
    expect(screen.getByText("Member 1 · Energy 1")).toBeInTheDocument();
    screen.getByText("下のメンバー").click();
    expect(onCard).toHaveBeenCalledWith(state.cards["attached-member"]);
  });
});
