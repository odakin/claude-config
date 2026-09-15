// Hermetic self-test for artifact-presentation.mjs; uses a fake slide API and needs no Office app.
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { createPresentationKit } from "./artifact-presentation.mjs";

const temporary = await fs.mkdtemp(path.join(os.tmpdir(), "artifact-presentation-test-"));
await fs.writeFile(path.join(temporary, "figure.png"), "fixture");

class FakeText {
  constructor() {
    this.value = "";
    this.style = {};
    this.ranges = new Map();
  }
  get(value) {
    if (!this.ranges.has(value)) this.ranges.set(value, {});
    return this.ranges.get(value);
  }
}

class FakeSlide {
  constructor() {
    this.background = {};
    this.shapeItems = [];
    this.imageItems = [];
    this.shapes = {
      add: (options) => {
        const textFacade = new FakeText();
        const item = {
          options,
          get text() { return textFacade; },
          set text(value) { textFacade.value = value; },
        };
        this.shapeItems.push(item);
        return item;
      },
    };
    this.images = {
      add: (options) => {
        this.imageItems.push(options);
        return options;
      },
    };
    this.speakerNotes = { textFrame: { setText: (value) => { this.note = value; } } };
  }
}

class FakePresentation {
  static create({ slideSize }) {
    const items = [];
    return { slideSize, slides: { items, add: () => { const s = new FakeSlide(); items.push(s); return s; } } };
  }
}

const kit = createPresentationKit({
  Presentation: FakePresentation,
  width: 1920,
  height: 1080,
  assetDir: temporary,
  titleFont: "Title Font",
  bodyFont: "Body Font",
});
const first = kit.slide("Title", "Subtitle");
const emphasized = kit.rich(first, "alpha beta", ["beta"], 10, 20, 30, 40);
kit.link(first, "example", "https://example.com", 10, 20, 30, 40);
await kit.image(first, "figure.png", 1, 2, 3, 4, "contain", "fixture image");
kit.footer(first, 7);
kit.note(first, 1, "body", "source");

assert.deepEqual(kit.presentation.slideSize, { width: 1920, height: 1080 });
assert.equal(first.background.fill, "#FFFFFF");
assert.equal(first.shapeItems[0].text.value, "Title");
assert.equal(first.shapeItems[0].text.style.typeface, "Title Font");
assert.equal(emphasized.text.get("beta").bold, true);
assert.deepEqual(first.imageItems[0].position, { left: 1, top: 2, width: 3, height: 4 });
assert.equal(first.imageItems[0].contentType, "image/png");
assert.match(first.note, /出典\nsource/);
assert.match(kit.notes[0], /## 1/);
console.log("artifact-presentation selftest: PASS");
