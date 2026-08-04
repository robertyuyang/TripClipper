import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const html = fs.readFileSync(process.argv[2], "utf8");
const dataMatch = html.match(
  /<script id="review-data" type="application\/json">([\s\S]*?)<\/script>/,
);
assert(dataMatch, "缺少 review-data");
const reviewData = JSON.parse(dataMatch[1].replaceAll("<\\/", "</"));
const scriptMatches = [...html.matchAll(/<script(?: [^>]*)?>([\s\S]*?)<\/script>/g)];
const applicationScript = scriptMatches.at(-1)[1];

class FakeClassList {
  constructor() {
    this.values = new Set();
  }

  toggle(name, force) {
    if (force) this.values.add(name);
    else this.values.delete(name);
  }
}

class FakeElement {
  constructor(id, dataset = {}) {
    this.id = id;
    this.dataset = dataset;
    this.classList = new FakeClassList();
    this.listeners = new Map();
    this.hidden = false;
    this.disabled = false;
    this.textContent = "";
    this.href = "#";
    this.src = "";
    this.currentTime = 0;
    this.duration = 30;
    this.pauseCount = 0;
    this.playCount = 0;
  }

  addEventListener(type, callback, options = {}) {
    const entries = this.listeners.get(type) || [];
    entries.push({ callback, once: Boolean(options.once) });
    this.listeners.set(type, entries);
  }

  dispatch(type) {
    const entries = this.listeners.get(type) || [];
    this.listeners.set(type, entries.filter((entry) => !entry.once));
    for (const entry of entries) entry.callback({ target: this });
  }

  pause() {
    this.pauseCount += 1;
  }

  play() {
    this.playCount += 1;
    return Promise.resolve();
  }

  load() {}

  removeAttribute(name) {
    if (name === "src") this.src = "";
  }

  getAttribute(name) {
    return name === "src" ? this.src : null;
  }
}

const player = new FakeElement("review-player");
const candidateCards = reviewData.candidates.map(
  (candidate, index) => new FakeElement(`candidate-${index}`, {
    index: String(index),
    categories: candidate.categoryIds.join(" "),
  }),
);
const filterButtons = [
  new FakeElement("filter-all", { category: "all" }),
  ...reviewData.categories.map(
    (category) => new FakeElement(`filter-${category.categoryId}`, {
      category: category.categoryId,
    }),
  ),
];
const ids = new Map([
  ["review-data", Object.assign(new FakeElement("review-data"), {
    textContent: JSON.stringify(reviewData),
  })],
  ["review-player", player],
  ["image-preview", new FakeElement("image-preview")],
  ["player-status", new FakeElement("player-status")],
  ["previous-candidate", new FakeElement("previous-candidate")],
  ["replay-candidate", new FakeElement("replay-candidate")],
  ["next-candidate", new FakeElement("next-candidate")],
  ["open-source", new FakeElement("open-source")],
]);
for (const id of [
  "detail-candidate",
  "detail-asset",
  "detail-filename",
  "detail-path",
  "detail-range",
  "detail-categories",
  "detail-use",
  "detail-reason",
]) {
  ids.set(id, new FakeElement(id));
}

const document = {
  getElementById(id) {
    return ids.get(id);
  },
  querySelectorAll(selector) {
    if (selector === "button.candidate-card") return candidateCards;
    if (selector === "button.filter-chip") return filterButtons;
    return [];
  },
};
vm.runInNewContext(applicationScript, { document, JSON, Number, Math, console });

player.dispatch("loadedmetadata");
assert.equal(player.currentTime, 2, "初始候选应定位到 start_sec");
assert.equal(player.playCount, 0, "初始定位不得自动播放");

ids.get("next-candidate").dispatch("click");
player.dispatch("loadedmetadata");
assert.equal(player.currentTime, 10, "下一条应定位到候选起点");
assert.equal(player.playCount, 0, "下一条不得自动播放");

ids.get("replay-candidate").dispatch("click");
assert.equal(player.playCount, 1, "重新播放应主动播放");
assert.equal(player.currentTime, 10, "重新播放应返回候选起点");

player.currentTime = 25.2;
player.dispatch("timeupdate");
assert.equal(player.currentTime, 25, "到达 end_sec 应停在候选终点");
assert(player.pauseCount > 0, "到达 end_sec 应暂停");

player.currentTime = 99;
player.dispatch("seeking");
assert.equal(player.currentTime, 25, "拖动到区间外应约束回 end_sec");

filterButtons.find((button) => button.dataset.category === "category-001").dispatch("click");
assert.equal(
  candidateCards.filter((card) => !card.hidden).length,
  1,
  "多分类候选在分类筛选后仍只出现一次",
);

console.log("ok");
