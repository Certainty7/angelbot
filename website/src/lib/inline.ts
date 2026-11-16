/**
 * Inline content formatter.
 *
 * The only markup allowed in content strings is `text` → <bdi dir="ltr">text</bdi>.
 * Arabic runs and Latin terms share one paragraph, and a bare Latin run inside an RTL
 * sentence is reordered by the bidi algorithm at the punctuation boundary; <bdi> isolates
 * it. No other HTML is accepted, so content can never inject markup.
 */
export function inline(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/`([^`]+)`/g, '<bdi dir="ltr">$1</bdi>');
}
