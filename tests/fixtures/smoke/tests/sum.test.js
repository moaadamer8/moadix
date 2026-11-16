"use strict";
const test = require("node:test");
const assert = require("node:assert");
const { sum } = require("../src/sum.js");

test("sum adds two numbers", () => {
  assert.strictEqual(sum(2, 3), 5);
  assert.strictEqual(sum(-1, 1), 0);
});
