function tokens(value) {
  return String(value || "").toLocaleLowerCase().match(/[\p{L}\p{N}]+/gu) || [];
}

function tokenMatches(left, right) {
  if (left === right) return true;
  if (Math.min(left.length, right.length) >= 4 && (left.startsWith(right) || right.startsWith(left))) return true;
  if (left.length !== right.length || left.length < 5) return false;
  let differences = 0;
  for (let index = 0; index < left.length; index += 1) {
    if (left[index] !== right[index] && ++differences > 1) return false;
  }
  return true;
}

function fuzzyMatch(pageWords, wanted) {
  const anchors = wanted.map((token, index) => ({ token, index })).filter(item => item.token.length >= 4);
  let best = null;
  for (const anchor of anchors) {
    for (let pageIndex = 0; pageIndex < pageWords.length; pageIndex += 1) {
      if (!tokenMatches(anchor.token, pageWords[pageIndex].token)) continue;
      const matched = [pageWords[pageIndex]];
      let matchedCharacters = anchor.token.length;
      let cursor = pageIndex + 1;
      for (let wantedIndex = anchor.index + 1; wantedIndex < wanted.length; wantedIndex += 1) {
        const searchEnd = Math.min(pageWords.length, cursor + 7);
        let found = -1;
        for (let candidate = cursor; candidate < searchEnd; candidate += 1) {
          if (tokenMatches(wanted[wantedIndex], pageWords[candidate].token)) {
            found = candidate;
            break;
          }
        }
        if (found < 0) continue;
        matched.push(pageWords[found]);
        matchedCharacters += wanted[wantedIndex].length;
        cursor = found + 1;
      }
      const coverage = matchedCharacters / Math.max(1, wanted.join("").length);
      const score = coverage + Math.min(matched.length, 8) * 0.025;
      if ((!best || score > best.score) && matched.length >= 2 && coverage >= 0.52) {
        best = { score, words: matched };
      }
    }
  }
  return best?.words || null;
}

export function locationLabel(block) {
  if (block.location_match === "visual-text-fuzzy") return "定位：模糊";
  if (Array.isArray(block.bbox)) return "定位：精确";
  return "定位：仅页面";
}

export async function locateBlocks(record, blocks) {
  const unresolved = blocks.filter(block => !Array.isArray(block.bbox) && tokens(block.original_text).length >= 2);
  if (!unresolved.length) return false;
  record.textContentPromise ||= record.page.getTextContent();
  const content = await record.textContentPromise;
  const words = [];
  let compactPage = "";
  const compactItems = [];
  content.items.forEach((item, itemIndex) => {
    for (const token of tokens(item.str)) words.push({ token, itemIndex });
    for (const character of tokens(item.str).join("")) {
      compactPage += character;
      compactItems.push(itemIndex);
    }
  });
  let changed = false;
  for (const block of unresolved) {
    const wanted = tokens(block.original_text);
    const compactWanted = wanted.join("");
    const compactStart = compactPage.indexOf(compactWanted);
    let matchedItemIndexes;
    if (compactStart >= 0) {
      matchedItemIndexes = compactItems.slice(compactStart, compactStart + compactWanted.length);
      block.location_match = "visual-text-exact";
    } else {
      const fuzzyWords = fuzzyMatch(words, wanted);
      if (!fuzzyWords) continue;
      matchedItemIndexes = fuzzyWords.map(word => word.itemIndex);
      block.location_match = "visual-text-fuzzy";
    }
    const matchedItems = [...new Set(matchedItemIndexes)].map(index => content.items[index]);
    const boxes = matchedItems.map(item => {
      const x = item.transform[4];
      const baseline = item.transform[5];
      const height = item.height || Math.hypot(item.transform[2], item.transform[3]);
      return [x, baseline, x + item.width, baseline + height];
    });
    block.bbox = [
      Math.min(...boxes.map(box => box[0])),
      Math.min(...boxes.map(box => box[1])),
      Math.max(...boxes.map(box => box[2])),
      Math.max(...boxes.map(box => box[3]))
    ];
    changed = true;
  }
  return changed;
}
