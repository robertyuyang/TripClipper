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
    this.paused = true;
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
    this.paused = true;
    this.dispatch("pause");
  }

  play() {
    this.playCount += 1;
    this.paused = false;
    this.dispatch("play");
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
const samplePlayer = new FakeElement("sample-player");
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
  ["sample-player", samplePlayer],
  ["image-preview", new FakeElement("image-preview")],
  ["player-status", new FakeElement("player-status")],
  ["previous-candidate", new FakeElement("previous-candidate")],
  ["replay-candidate", new FakeElement("replay-candidate")],
  ["next-candidate", new FakeElement("next-candidate")],
  ["open-source", new FakeElement("open-source")],
  ["sample-status", new FakeElement("sample-status")],
  ["sample-skipped-count", new FakeElement("sample-skipped-count")],
  ["sample-toggle", new FakeElement("sample-toggle")],
  ["sample-restart", new FakeElement("sample-restart")],
  ["sample-previous", new FakeElement("sample-previous")],
  ["sample-next", new FakeElement("sample-next")],
]);
for (const id of [
  "sample-progress",
  "sample-candidate",
  "sample-session",
  "sample-range",
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

if (process.argv[3] === "invalid-range") {
  const invalidCandidateIndex = reviewData.sampleQueue[0].candidateIndex;
  const nextCandidate = reviewData.sampleQueue.find(
    (segment) => segment.candidateIndex !== invalidCandidateIndex,
  );
  const skippedBeforeInvalid = Number(ids.get("sample-skipped-count").textContent);
  samplePlayer.duration = 0;
  samplePlayer.dispatch("loadedmetadata");
  assert.equal(
    Number(ids.get("sample-skipped-count").textContent),
    skippedBeforeInvalid + 1,
    "运行时无效候选应增加一次跳过计数",
  );
  assert(
    ids.get("sample-candidate").textContent.includes(nextCandidate.candidateId),
    "运行时无效候选应被移除并继续定位下一候选",
  );
  console.log("ok");
  process.exit(0);
}

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

assert(reviewData.sampleQueue.length >= 2, "测试数据至少应生成两个小样片段");
ids.get("sample-restart").dispatch("click");
samplePlayer.dispatch("loadedmetadata");
assert.equal(
  samplePlayer.currentTime,
  reviewData.sampleQueue[0].startSec,
  "从头播放应定位到第一段起点",
);
assert.equal(samplePlayer.playCount, 1, "从头播放应主动播放第一段");
assert(player.pauseCount > 0, "小样开始播放时应暂停单候选播放器");

samplePlayer.currentTime = reviewData.sampleQueue[0].endSec;
samplePlayer.dispatch("timeupdate");
samplePlayer.dispatch("loadedmetadata");
assert.equal(
  samplePlayer.currentTime,
  reviewData.sampleQueue[1].startSec,
  "到达终点应定位到下一段",
);
assert.equal(samplePlayer.playCount, 2, "到达终点应自动播放下一段");

player.play();
assert(samplePlayer.pauseCount > 0, "单候选播放器开始播放时应暂停小样");

ids.get("sample-restart").dispatch("click");
samplePlayer.dispatch("loadedmetadata");
for (let index = 0; index < reviewData.sampleQueue.length - 1; index += 1) {
  samplePlayer.currentTime = reviewData.sampleQueue[index].endSec;
  samplePlayer.dispatch("timeupdate");
  samplePlayer.dispatch("loadedmetadata");
}
const finalSegment = reviewData.sampleQueue.at(-1);
samplePlayer.currentTime = finalSegment.endSec;
samplePlayer.dispatch("timeupdate");
assert.equal(samplePlayer.currentTime, finalSegment.endSec, "最后一段应停在终点");
assert.equal(samplePlayer.paused, true, "最后一段结束后应停止且不循环");

filterButtons.find((button) => button.dataset.category === "category-001").dispatch("click");
assert.equal(
  candidateCards.filter((card) => !card.hidden).length,
  1,
  "多分类候选在分类筛选后仍只出现一次",
);

console.log("ok");
