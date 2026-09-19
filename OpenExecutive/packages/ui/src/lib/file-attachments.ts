// Mirror the backend's `_MAX_FILES_PER_TURN` / `_MAX_BYTES_PER_FILE`. Kept
// in sync manually; a mismatch only costs an extra round-trip + the user
// sees the server's 413 message, so no correctness risk.
export const MAX_FILES_PER_TURN = 5;
export const MAX_BYTES_PER_FILE = 20 * 1024 * 1024;

export interface FileSelection<T> {
  files: T[];
  rejected: string[];
}

type AttachmentFile = {
  name: string;
  size: number;
};

export function mergePickedFiles<T extends AttachmentFile>(
  current: readonly T[],
  picked: readonly T[],
): FileSelection<T> {
  const files = [...current];
  const rejected: string[] = [];

  for (const file of picked) {
    if (file.size > MAX_BYTES_PER_FILE) {
      const maxSizeMb = MAX_BYTES_PER_FILE / (1024 * 1024);
      rejected.push(`${file.name} is too large (max ${maxSizeMb} MB)`);
      continue;
    }
    if (files.length >= MAX_FILES_PER_TURN) break;
    if (files.some((existing) => existing.name === file.name && existing.size === file.size)) {
      continue;
    }
    files.push(file);
  }

  return { files, rejected };
}
