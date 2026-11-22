import { describe, expect, it } from "vitest";
import { sum } from "../src/sum.js";

describe("US-001 sum", () => {
  it("adds two numbers", () => {
    expect(sum(2, 3)).toBe(5);
    expect(sum(-1, 1)).toBe(0);
  });
});
