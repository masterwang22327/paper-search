import assert from 'node:assert/strict';
import { locateCitationQuote } from '../content/pdf-viewer/source-locator.mjs';
const item = (str, y = 100) => ({str, transform: [1,0,0,12,20,y], width: 200, height: 12});
assert.equal(locateCitationQuote([item('Unrelated passage here')], 'This is missing evidence'), null);
assert.equal(locateCitationQuote([item('Repeated evidence text'), item('Repeated evidence text')], 'Repeated evidence text'), null);
assert.deepEqual(locateCitationQuote([item('The efﬁcient multi-'), item('turn method works.', 80)], 'The efficient multi-turn method works.'), [[20,100,220,112],[20,80,220,92]]);
assert.equal(locateCitationQuote([item('The efficient method works.')], 'The inefficient method works.'), null);
assert.equal(locateCitationQuote([item('short')], 'short'), null);
console.log('citation locator: PASS');
