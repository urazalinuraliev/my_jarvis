import assert from "node:assert/strict";
import test from "node:test";
import {
  MAX_BYTES_PER_FILE,
  MAX_FILES_PER_TURN,
  mergePickedFiles,
} from "../src/lib/file-attachments.ts";

test("rejects oversized files with an actionable message", () => {
  const oversized = { name: "quarterly-report.pdf", size: MAX_BYTES_PER_FILE + 1 };

  const result = mergePickedFiles([], [oversized]);

  assert.deepEqual(result.files, []);
  assert.deepEqual(result.rejected, ["quarterly-report.pdf is too large (max 20 MB)"]);
});

test("keeps valid files while rejecting oversized files from the same pick", () => {
  const valid = { name: "notes.txt", size: 100 };
  const oversized = { name: "archive.zip", size: MAX_BYTES_PER_FILE + 1 };

  const result = mergePickedFiles([], [valid, oversized]);

  assert.deepEqual(result.files, [valid]);
  assert.deepEqual(result.rejected, ["archive.zip is too large (max 20 MB)"]);
});

test("preserves the existing file-count cap and de-duplicates files", () => {
  const current = Array.from({ length: MAX_FILES_PER_TURN }, (_, i) => ({
    name: `file-${i}.txt`,
    size: i + 1,
  }));

  const result = mergePickedFiles(current, [current[0], { name: "extra.txt", size: 10 }]);

  assert.deepEqual(result.files, current);
  assert.deepEqual(result.rejected, []);
});
