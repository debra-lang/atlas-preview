// Quality-gate helper (test tooling only; the Ask worker does not use it): does an Ask answer ASSERT that something cures tinnitus?
//
// The gate must reject an affirmative cure claim ("Lenire cures tinnitus") and must accept the honest statement the feature is built to make ("No treatment in this database is shown
// to cure tinnitus"). A word ban cannot do both, and "a negative word anywhere in the sentence" is bypassable ("There is no doubt that this treatment cures tinnitus"). So the rule is
// local and parity-based. For every cure/cures/cured/curing in a sentence:
//   1. a mention is not an assertion and is skipped when the word is in quotation marks ("Cure" claims ...) or is the noun of a denied claim ("cure claims are not supported");
//   2. look only at the CLAUSE the word is in (text after the last comma, semicolon, colon, dash, bracket or the words but/yet/however/although/though/while/whereas/and) and at the
//      10 words before it;
//   3. remove phrases that LOOK negative but affirm ("no doubt", "no denying", "no one can deny", "cannot be denied", "not only", "without question", "no wonder");
//   4. count the negators left ("no, not, never, cannot, nothing, none, nobody, neither/nor (together one), without, n't, let alone, fail(s) to"): an ODD count is a denial, an EVEN count
//      (none, or a double negative such as "never fails to cure", "it is not true that X does not cure") is an assertion and is flagged.
// A weaker negation than this passes only by being ODD and LOCAL, which is what a real denial is. It is a heuristic for model output, not a parser: when in doubt it flags.

const AFFIRMING_NEGATIVES = [
  /\b(?:no|not|never|without)\s+(?:a\s+|any\s+)?(?:doubt|question|wonder|denying|denial|mistake|surprise|secret)\b/g,
  /\b(?:no|nobody|none|not)\s+(?:[a-z']+\s+){0,4}?(?:deny|denies|doubt|doubts|dispute|disputes|question|questions|contest|contests)\b/g,      // "no one can deny", "nobody doubts", "no serious clinician disputes"
  /\b(?:cannot|can\s+not|can't|couldn't)\s+(?:possibly\s+)?be\s+(?:denied|doubted|disputed|questioned)\b/g,
  /\bnot\s+only\b/g,
  /\bno\s+wonder\b/g,
  /\bnothing\s+(?:[a-z']+\s+){0,2}?(?:better|more|else|beats|compares)\b/g,      // "nothing works better than CBT to cure tinnitus"
  /\bnot\s+(?:hard|difficult|surprising)\s+to\s+(?:see|believe|understand)\b/g,
];

const NEGATOR = /\b(?:no|not|never|cannot|nothing|none|nobody|neither|nor|without|unable)\b|n't\b|\blet\s+alone\b|\bfail(?:s|ed)?\s+to\b/g;
const CURE = /\bcur(?:e|es|ed|ing)\b/gi;
const CLAUSE_BREAK = /[,;:()\[\]—–]|\s-\s|\b(?:but|yet|however|although|though|while|whereas|and)\b/gi;
const WINDOW = 14;

function clauseBefore(sentence, index) {
  const before = sentence.slice(0, index);
  let cut = 0, m;
  CLAUSE_BREAK.lastIndex = 0;
  while ((m = CLAUSE_BREAK.exec(before)) !== null) cut = m.index + m[0].length;
  return before.slice(cut);
}

function negatorCount(clause) {
  let t = " " + clause.toLowerCase().replace(/[’‘]/g, "'") + " ";
  for (const rx of AFFIRMING_NEGATIVES) t = t.replace(rx, " ");
  const words = t.match(/[a-z']+/g) || [];
  t = " " + words.slice(-WINDOW).join(" ") + " ";
  let n = (t.match(NEGATOR) || []).length;
  if (/\bneither\b/.test(t) && /\bnor\b/.test(t)) n -= 1;      // "neither ... nor" is ONE negation
  return n;
}

// Parentheticals sit between a negator and the word it governs ("no treatment, including Lenire, is established as a cure"; "no treatment — supplement or otherwise — can be claimed to
// cure"), so they are removed before the clause is cut. Markdown links keep their text only.
function tidy(sentence) {
  return sentence.replace(/[’‘]/g, "'")
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/\([^)]{0,80}\)/g, " ")
    .replace(/\s[—–-]\s[^—–]{0,80}?\s[—–-]\s/g, " ")
    .replace(/,\s*(?:including|such as|e\.g\.|especially|even|among them|like|namely)\b[^,]{0,80},/gi, " ");
}

export function affirmativeCureClaims(text) {
  const flagged = [];
  for (const sentence of String(text || "").split(/(?<=[.!?])\s+|\n+/)) {
    const s = tidy(sentence);
    CURE.lastIndex = 0;
    let m, claim = false;
    while ((m = CURE.exec(s)) !== null) {
      const around = s.slice(Math.max(0, m.index - 1), m.index + m[0].length + 1);
      if (/["“”]cur(?:e|es|ed|ing)["“”]/i.test(around)) continue;                                  // the word is quoted: a mention, not an assertion
      if (/^cure\s+claims?\s+(?:is|are)\s+(?:not|never|unsupported|unproven|misleading|false)\b/i.test(s.slice(m.index))) continue;   // "cure claims are not supported"
      if (negatorCount(clauseBefore(s, m.index)) % 2 === 0) claim = true;                                              // none or a double negative: an assertion
    }
    if (claim) flagged.push(sentence.trim().slice(0, 160));
  }
  return flagged;
}
