const test = require('node:test');
const assert = require('node:assert/strict');

function computeEquityDates({ equityHistory, lastDate, playbackDates }) {
  if (!equityHistory || equityHistory.length === 0) return [];

  if (lastDate) {
    const endIdx = playbackDates.indexOf(lastDate);
    if (endIdx >= 0) {
      const startIdx = Math.max(0, endIdx - equityHistory.length + 1);
      const alignedDates = playbackDates.slice(startIdx, endIdx + 1);
      if (alignedDates.length === equityHistory.length) {
        return alignedDates;
      }
    }
  }

  if (playbackDates.length >= equityHistory.length) {
    return playbackDates.slice(-equityHistory.length);
  }

  return equityHistory.map((_, idx) => `Day ${idx + 1}`);
}

test('equity dates align to workflow last_date instead of global playback start', () => {
  const playbackDates = [
    '2026-03-17',
    '2026-03-18',
    '2026-03-19',
    '2026-03-20',
    '2026-03-23',
    '2026-03-24',
    '2026-03-25',
    '2026-03-26',
    '2026-03-27',
    '2026-03-30',
    '2026-03-31',
  ];

  const result = computeEquityDates({
    equityHistory: [1, 2, 3],
    lastDate: '2026-03-19',
    playbackDates,
  });

  assert.deepEqual(result, ['2026-03-17', '2026-03-18', '2026-03-19']);
});

test('equity dates use trailing playback dates when last_date is missing', () => {
  const playbackDates = ['2026-03-27', '2026-03-30', '2026-03-31'];
  const result = computeEquityDates({
    equityHistory: [1, 2],
    lastDate: null,
    playbackDates,
  });

  assert.deepEqual(result, ['2026-03-30', '2026-03-31']);
});
