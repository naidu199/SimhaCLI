// Inline SVG icons for the chat panel.
// Paths from Lucide (https://lucide.dev), ISC License. Copyright (c) for
// portions of Lucide are held by Cole Bemis 2013-2022 as part of Feather (MIT);
// all other copyright (c) for Lucide are held by Lucide Contributors 2022.

function svg(body: string, size = 16, extra = ""): string {
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" ` +
    `stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"${extra}>${body}</svg>`
  );
}

const SPARKLE_PATH =
  "M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z";

export const icons = {
  paperclip: () =>
    svg('<path d="m16 6-8.414 8.586a2 2 0 0 0 2.829 2.829l8.414-8.586a4 4 0 1 0-5.657-5.657l-8.379 8.551a6 6 0 1 0 8.485 8.485l8.379-8.551"/>'),
  arrowUp: () => svg('<path d="m5 12 7-7 7 7"/><path d="M12 19V5"/>'),
  stop: () => svg('<rect width="12" height="12" x="6" y="6" rx="2" fill="currentColor"/>'),
  chevronDown: (size = 12) => svg('<path d="m6 9 6 6 6-6"/>', size),
  chevronRight: (size = 12) => svg('<path d="m9 18 6-6-6-6"/>', size),
  arrowLeft: () => svg('<path d="m12 19-7-7 7-7"/><path d="M19 12H5"/>'),
  sparkle: (size = 14) => svg(`<path d="${SPARKLE_PATH}" fill="currentColor" stroke="none"/>`, size),
  trash: () =>
    svg('<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>', 14),
  search: () => svg('<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>', 14),
  check: (size = 14) => svg('<path d="M20 6 9 17l-5-5"/>', size),
  x: (size = 14) => svg('<path d="M18 6 6 18"/><path d="m6 6 12 12"/>', size),
  loader: (size = 14) => svg('<path d="M21 12a9 9 0 1 1-6.219-8.56"/>', size, ' class="spin"'),
  shield: () => svg('<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>', 15),
  alert: () => svg('<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>', 15),
  fileDiff: () => svg('<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M9 10h6"/><path d="M12 13V7"/><path d="M9 17h6"/>', 14),
  undo: () => svg('<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 5.5 5.5 5.5 5.5 0 0 1-5.5 5.5H11"/>', 13),
  compass: () => svg('<circle cx="12" cy="12" r="10"/><path d="m16.24 7.76-1.804 5.411a2 2 0 0 1-1.265 1.265L7.76 16.24l1.804-5.411a2 2 0 0 1 1.265-1.265z"/>', 16),
  bug: () => svg('<path d="m8 2 1.88 1.88"/><path d="M14.12 3.88 16 2"/><path d="M9 7.13v-1a3.003 3.003 0 1 1 6 0v1"/><path d="M12 20c-3.3 0-6-2.7-6-6v-3a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v3c0 3.3-2.7 6-6 6"/><path d="M12 20v-9"/><path d="M6.53 9C4.6 8.8 3 7.1 3 5"/><path d="M6 13H2"/><path d="M3 21c0-2.1 1.7-3.9 3.8-4"/><path d="M20.97 5c0 2.1-1.6 3.8-3.5 4"/><path d="M22 13h-4"/><path d="M17.2 17c2.1.1 3.8 1.9 3.8 4"/>', 16),
  flask: () => svg('<path d="M10 2v7.527a2 2 0 0 1-.211.896L4.72 20.55a1 1 0 0 0 .9 1.45h12.76a1 1 0 0 0 .9-1.45l-5.069-10.127A2 2 0 0 1 14 9.527V2"/><path d="M8.5 2h7"/><path d="M7 16h10"/>', 16),
  gitCompare: () => svg('<circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M13 6h3a2 2 0 0 1 2 2v7"/><path d="M11 18H8a2 2 0 0 1-2-2V9"/>', 16),
  /** The SimhaCLI mark: terminal + sparkle (same as the activity-bar icon). */
  logo: (size = 40) =>
    svg(
      '<path d="M13.8 6H5a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2v-8.8"/><path d="m6.5 11 3 2.5-3 2.5"/><path d="M11.5 16h4"/>' +
        `<path transform="translate(19 5) scale(0.37) translate(-12 -12)" fill="currentColor" stroke="none" d="${SPARKLE_PATH}"/>`,
      size,
    ),
};
