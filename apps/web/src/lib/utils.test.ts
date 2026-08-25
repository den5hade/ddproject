import { describe, expect, it } from "vitest";
import { cn } from "./utils";

describe("cn", () => {
  it("merges class names", () => {
    expect(cn("a", "b")).toBe("a b");
  });

  it("resolves tailwind conflicts keeping the last value", () => {
    expect(cn("px-2", "px-4")).toBe("px-4");
  });

  it("skips falsy inputs", () => {
    expect(cn("a", false, undefined, null, "c")).toBe("a c");
  });
});
