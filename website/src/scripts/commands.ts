/**
 * Command explorer: search, category filter and copy.
 *
 * The catalogue is server-rendered from the generated JSON, so the page is complete without
 * JavaScript; this file only narrows the visible rows. Arabic matching strips diacritics and
 * unifies the letter variants people type differently (أ/ا, ى/ي, ة/ه).
 */
const normalize = (value: string): string =>
  value
    .toLowerCase()
    .replace(/[\u064B-\u065F\u0670\u0640\u06D6-\u06ED]/g, '')
    .replace(/[أإآٱ]/g, 'ا')
    .replace(/ى/g, 'ي')
    .replace(/ة/g, 'ه')
    .replace(/\s+/g, ' ')
    .trim();

export function initCommands(): void {
  const root = document.querySelector<HTMLElement>('[data-explorer]');
  if (!root) return;

  const search = root.querySelector<HTMLInputElement>('[data-command-search]');
  const chips = [...root.querySelectorAll<HTMLButtonElement>('[data-cat]')];
  const rows = [...root.querySelectorAll<HTMLElement>('[data-command]')];
  const ownerGroup = root.querySelector<HTMLDetailsElement>('[data-owner-group]');
  const ownerRows = ownerGroup ? [...ownerGroup.querySelectorAll<HTMLElement>('[data-command]')] : [];
  const visibleCount = root.querySelector<HTMLElement>('[data-visible]');
  const empty = root.querySelector<HTMLElement>('[data-empty]');
  const copyLabel = root.dataset.labelCopy ?? 'Copy';
  const copiedLabel = root.dataset.labelCopied ?? 'Copied';

  const haystack = new Map(rows.map((row) => [row, normalize(row.dataset.search ?? '')]));
  let category = '';
  let terms: string[] = [];

  // Owner tools live in a collapsed group. A match inside it must not be invisible, so the group
  // opens itself on a search hit (and when its own chip is selected) and closes again when the
  // search is cleared, unless the visitor opened it by hand.
  let ownerOpenedByHand = false;
  ownerGroup?.addEventListener('toggle', () => {
    ownerOpenedByHand = ownerGroup.open && !search?.value && category !== '__owner__';
  });

  const apply = (): void => {
    let visible = 0;
    const ownerChip = category === '__owner__';
    for (const row of rows) {
      const text = haystack.get(row) ?? '';
      const inCategory = ownerChip ? row.dataset.owner === 'true' : !category || row.dataset.category === category;
      const show = terms.every((term) => text.includes(term)) && inCategory;
      row.hidden = !show;
      if (show) visible += 1;
    }
    if (visibleCount) visibleCount.textContent = String(visible);
    if (empty) empty.hidden = visible !== 0;

    if (ownerGroup) {
      const ownerVisible = ownerRows.some((row) => !row.hidden);
      if (ownerChip) ownerGroup.open = true;
      else if (terms.length > 0 || category) ownerGroup.open = ownerVisible;
      else if (!ownerOpenedByHand) ownerGroup.open = false;
    }
  };

  search?.addEventListener('input', () => {
    terms = normalize(search.value).split(' ').filter(Boolean);
    apply();
  });
  search?.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && search.value) {
      search.value = '';
      terms = [];
      apply();
    }
  });

  for (const chip of chips) {
    chip.addEventListener('click', () => {
      category = chip.dataset.cat ?? '';
      for (const other of chips) other.setAttribute('aria-pressed', String(other === chip));
      apply();
    });
  }

  root.addEventListener('click', async (event) => {
    const button = (event.target as HTMLElement).closest<HTMLButtonElement>('[data-copy]');
    if (!button) return;
    const value = button.dataset.copy ?? '';
    const label = button.querySelector<HTMLElement>('[data-copy-label]');

    try {
      await navigator.clipboard.writeText(value);
    } catch {
      const area = document.createElement('textarea');
      area.value = value;
      area.setAttribute('readonly', '');
      area.style.position = 'fixed';
      area.style.opacity = '0';
      document.body.appendChild(area);
      area.select();
      try {
        document.execCommand('copy');
      } catch {
        /* clipboard is unavailable; the label still confirms the attempt */
      }
      area.remove();
    }

    if (label) {
      label.textContent = copiedLabel;
      window.setTimeout(() => {
        label.textContent = copyLabel;
      }, 1500);
    }
  });

  apply();
}
